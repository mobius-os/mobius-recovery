"""HTTP entrypoint for the ephemeral Mobius recovery worker."""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .broker import BROKER_SOCKET, CommandBroker
from .chat import (
  claim_finish,
  finish_active,
  release_finish,
  stream_turn,
  turn_active,
)
from .config import WORKER_PROTOCOL_VERSION, Settings
from .control import ControlClient
from .pages import closed_page, launch_page, lost_page, recovery_page
from .protocol import ProtocolError
from .providers import ProviderAuth
from .security import harden_process
from .sessions import COOKIE_NAME, RecoverySession, SessionStore
from .workspace import SessionWorkspaces, WORKSPACES_DIR


MAX_API_BODY = 64 * 1024
MAX_START_BODY = 16 * 1024
CLOSED_COOKIE = "mobius_recovery_closed"
SSE_KEEPALIVE_SECONDS = 15.0
MAX_BROWSER_SESSION_SECONDS = 60 * 60


class RecoveryRuntime:
  """Owns the one command broker, provider state, and temporary workspace."""

  def __init__(
    self,
    control: ControlClient,
    providers: ProviderAuth,
    workspaces: SessionWorkspaces,
    *,
    broker_path: Path,
  ) -> None:
    self._control = control
    self._providers = providers
    self._workspaces = workspaces
    self._broker_path = broker_path
    self._active: tuple[str, CommandBroker] | None = None
    self._sessions: SessionStore | None = None
    self._lock = threading.RLock()

  def bind_sessions(self, sessions: SessionStore) -> None:
    self._sessions = sessions

  def activate(self, session: RecoverySession) -> None:
    if session.revoked or session.expires_at <= datetime.now(timezone.utc):
      raise ProtocolError("auth_expired", "Recovery session expired.", 401)
    with self._lock:
      if self._active:
        self._active[1].stop()
        self._active = None
      self._providers.clear()
      self._workspaces.clear()
      broker = None
      try:
        session.workspace = self._workspaces.create()
        session.provider_generation = self._providers.enable()
        broker = CommandBroker(
          self._control,
          session.exchange,
          path=self._broker_path,
          on_expire=self._sessions.expire if self._sessions else None,
        )
        broker.start()
        self._active = (session.session_id, broker)
        release_finish()
      except Exception:
        if broker:
          broker.stop()
        self._providers.clear()
        self._workspaces.clear()
        session.provider_generation = None
        session.workspace = None
        raise

  def revoke(self, session: RecoverySession, _reason: str) -> None:
    with self._lock:
      if self._active and self._active[0] != session.session_id:
        return
      active = self._active[1] if self._active else None
      self._active = None
      session.provider_generation = None
      session.workspace = None
      try:
        if active:
          active.stop()
      finally:
        self._providers.clear()
        self._workspaces.clear()
        release_finish()

  def quiesce(self, session: RecoverySession) -> None:
    self.revoke(session, "finishing")

  def close(self) -> None:
    with self._lock:
      if self._active:
        self._active[1].stop()
        self._active = None
      self._providers.clear()
      self._workspaces.clear()
      release_finish()


def _nonce() -> str:
  return secrets.token_urlsafe(18)


def _cookie_max_age(session: RecoverySession) -> int:
  remaining = int((session.expires_at - datetime.now(timezone.utc)).total_seconds())
  return max(1, min(MAX_BROWSER_SESSION_SECONDS, remaining))


def _security_headers(response, nonce: str | None = None):
  response.headers["Cache-Control"] = "no-store"
  response.headers["Referrer-Policy"] = "no-referrer"
  response.headers["X-Content-Type-Options"] = "nosniff"
  response.headers["X-Frame-Options"] = "DENY"
  response.headers["Permissions-Policy"] = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
  )
  if nonce:
    response.headers["Content-Security-Policy"] = (
      "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
      f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
      "connect-src 'self'; form-action 'self'"
    )
  return response


async def _json_body(request: Request, limit: int = MAX_API_BODY) -> dict:
  media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
  if media_type != "application/json":
    raise ProtocolError("unsupported_media_type", "Request body must use application/json.", 415)
  body = bytearray()
  async for chunk in request.stream():
    body.extend(chunk)
    if len(body) > limit:
      raise ProtocolError("request_too_large", "Request is too large.", 413)
  try:
    value = json.loads(body.decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise ProtocolError("invalid_json", "Request body must be JSON.", 400) from exc
  if not isinstance(value, dict):
    raise ProtocolError("invalid_json", "Request body must be an object.", 400)
  return value


async def _start_form(request: Request) -> dict[str, str]:
  content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
  if content_type != "application/x-www-form-urlencoded":
    raise ProtocolError("unsupported_media_type", "Session start requires a URL-encoded form.", 415)
  body = bytearray()
  async for chunk in request.stream():
    body.extend(chunk)
    if len(body) > MAX_START_BODY:
      raise ProtocolError("request_too_large", "Session form exceeds 16 KiB.", 413)
  try:
    parsed = parse_qs(
      body.decode("utf-8"), keep_blank_values=True, max_num_fields=4,
      encoding="utf-8", errors="strict",
    )
  except (UnicodeDecodeError, ValueError) as exc:
    raise ProtocolError("invalid_form", "Session form is invalid.", 400) from exc
  return {
    key: values[0] for key, values in parsed.items()
    if key in {"code", "instance_id"} and values
  }


def _same_origin(request: Request) -> None:
  if request.headers.get("sec-fetch-site", "").lower() != "same-origin":
    raise ProtocolError("cross_site", "Cross-site request rejected.", 403)
  parsed = urlparse(request.headers.get("origin", ""))
  host = request.headers.get("host", "")
  if (
    parsed.scheme not in {"http", "https"}
    or parsed.netloc.lower() != host.lower()
    or parsed.path not in {"", "/"}
    or parsed.params or parsed.query or parsed.fragment
    or parsed.username or parsed.password
  ):
    raise ProtocolError("cross_site", "Cross-site request rejected.", 403)


def _launch_origin(request: Request, settings: Settings) -> None:
  fetch_site = request.headers.get("sec-fetch-site", "").lower()
  if fetch_site not in {"cross-site", "same-site", "same-origin"}:
    raise ProtocolError("cross_site", "Recovery handoff origin rejected.", 403)
  supplied = urlparse(request.headers.get("origin", ""))
  expected = urlparse(settings.control_plane_url or "")
  try:
    supplied_port = supplied.port or (443 if supplied.scheme == "https" else 80)
    expected_port = expected.port or (443 if expected.scheme == "https" else 80)
  except ValueError as exc:
    raise ProtocolError("cross_site", "Recovery handoff origin rejected.", 403) from exc
  if (
    supplied.scheme != expected.scheme
    or (supplied.hostname or "").lower() != (expected.hostname or "").lower()
    or supplied_port != expected_port
    or supplied.path not in {"", "/"}
    or supplied.params or supplied.query or supplied.fragment
    or supplied.username or supplied.password
  ):
    raise ProtocolError("cross_site", "Recovery handoff origin rejected.", 403)


async def _sse_events(iterator, keepalive: float = SSE_KEEPALIVE_SECONDS):
  pending = None
  try:
    while True:
      if pending is None:
        pending = asyncio.create_task(anext(iterator))
      done, _ = await asyncio.wait({pending}, timeout=keepalive)
      if not done:
        yield ": keepalive\n\n"
        continue
      try:
        event = pending.result()
      except StopAsyncIteration:
        return
      pending = None
      yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
  finally:
    if pending and not pending.done():
      pending.cancel()
    await iterator.aclose()


def _target_ready(control: ControlClient, session: RecoverySession) -> dict:
  result = control.exec(session.exchange, {
    "argv": ["/usr/bin/id", "-u"], "timeout_seconds": 15,
  })
  try:
    stdout = base64.b64decode(result["stdout_base64"], validate=True).strip()
  except (ValueError, TypeError) as exc:
    raise ProtocolError("invalid_control_response", "SSH probe response is invalid", 502) from exc
  if result.get("exit_code") != 0 or stdout != b"0":
    raise ProtocolError("ssh_unavailable", "Root SSH access is unavailable.", 502)
  return {"status": "ready", "transport": "railway-native-ssh"}


def create_app(
  settings: Settings | None = None,
  *,
  control_transport: httpx.BaseTransport | None = None,
  broker_path: Path | None = None,
  workspace_root: Path | None = None,
) -> FastAPI:
  settings = settings or Settings.from_env()
  settings.validate()
  control = ControlClient(settings, transport=control_transport)
  providers = ProviderAuth()
  resolved_broker_path = broker_path or BROKER_SOCKET
  resolved_workspace_root = (
    Path(workspace_root) if workspace_root is not None
    else (resolved_broker_path.parent / "workspaces" if broker_path else WORKSPACES_DIR)
  )
  workspaces = SessionWorkspaces(resolved_workspace_root)
  runtime = RecoveryRuntime(
    control, providers, workspaces, broker_path=resolved_broker_path
  )
  sessions = SessionStore(
    control=control,
    instance_id=settings.instance_id or "",
    on_revoke=runtime.revoke,
    on_finish_accepted=runtime.quiesce,
  )
  runtime.bind_sessions(sessions)

  @asynccontextmanager
  async def lifespan(_app: FastAPI):
    harden_process()
    yield
    await asyncio.to_thread(sessions.close)
    await asyncio.to_thread(runtime.close)
    await asyncio.to_thread(control.close)

  app = FastAPI(
    title="Mobius Recovery Worker", docs_url=None, redoc_url=None,
    openapi_url=None, lifespan=lifespan,
  )
  app.state.settings = settings
  app.state.sessions = sessions
  app.state.providers = providers
  app.state.runtime = runtime
  app.state.workspaces = workspaces

  @app.exception_handler(ProtocolError)
  async def protocol_error(_request: Request, exc: ProtocolError):
    return _security_headers(JSONResponse(
      status_code=exc.status,
      content={"error": {"code": exc.code, "message": exc.message}},
    ))

  async def current(request: Request) -> tuple[str, RecoverySession]:
    token = request.cookies.get(COOKIE_NAME)
    session = await asyncio.to_thread(sessions.get, token)
    if not token or session is None:
      raise ProtocolError("auth_required", "Recovery session expired.", 401)
    return token, session

  async def interactive(request: Request) -> tuple[str, RecoverySession]:
    token, session = await current(request)
    if session.finishing or finish_active():
      raise ProtocolError("finish_in_progress", "Recovery is already closing.", 409)
    return token, session

  @app.get("/health")
  async def health():
    return _security_headers(JSONResponse({
      "status": "ready", "build_sha": settings.build_sha,
      "protocol_version": WORKER_PROTOCOL_VERSION,
      "service_id": settings.service_id,
    }))

  @app.get("/", response_class=HTMLResponse)
  async def index(request: Request):
    nonce = _nonce()
    browser_token = request.cookies.get(COOKIE_NAME)
    session = await asyncio.to_thread(sessions.get, browser_token)
    if session is None:
      closed = request.cookies.get(CLOSED_COOKIE)
      if closed in {"recovered", "cancelled"}:
        body = closed_page(
          nonce, outcome=closed, return_url=settings.control_plane_url
        )
      elif browser_token:
        body = lost_page(nonce, return_url=settings.control_plane_url)
      else:
        body = launch_page(nonce, return_url=settings.control_plane_url)
    else:
      body = recovery_page(
        nonce, protocol_version=WORKER_PROTOCOL_VERSION,
        build_sha=settings.build_sha, session_id=session.session_id,
        readiness_error=session.readiness_error,
        finishing=session.finishing,
      )
    return _security_headers(HTMLResponse(body), nonce)

  @app.post("/session/start", response_class=HTMLResponse)
  async def session_start(request: Request):
    nonce = _nonce()
    _launch_origin(request, settings)
    try:
      form = await _start_form(request)
      browser_token, session = await asyncio.to_thread(
        sessions.start, form.get("code", ""), form.get("instance_id") or None
      )
      await asyncio.to_thread(runtime.activate, session)
      await asyncio.to_thread(_target_ready, control, session)
      session.readiness_error = None
    except ProtocolError as exc:
      body = launch_page(
        nonce, error=exc.message, return_url=settings.control_plane_url
      )
      return _security_headers(HTMLResponse(body, status_code=exc.status), nonce)
    except OSError:
      session.readiness_error = "The local command broker could not start."
    body = recovery_page(
      nonce, protocol_version=WORKER_PROTOCOL_VERSION,
      build_sha=settings.build_sha, session_id=session.session_id,
      readiness_error=session.readiness_error,
    )
    response = HTMLResponse(body)
    response.set_cookie(
      COOKIE_NAME, browser_token, max_age=_cookie_max_age(session),
      httponly=True, secure=settings.secure_cookie, samesite="strict", path="/",
    )
    response.delete_cookie(CLOSED_COOKIE, path="/", secure=settings.secure_cookie)
    return _security_headers(response, nonce)

  @app.get("/api/providers")
  async def provider_status(request: Request):
    await interactive(request)
    return _security_headers(JSONResponse(await asyncio.to_thread(providers.status)))

  @app.get("/api/target/health")
  async def target_health(request: Request):
    _, session = await interactive(request)
    result = await asyncio.to_thread(_target_ready, control, session)
    return _security_headers(JSONResponse({"status": "ready", "target": result}))

  @app.post("/api/providers/claude/start")
  async def claude_start(request: Request):
    _same_origin(request)
    await interactive(request)
    return _security_headers(JSONResponse(await asyncio.to_thread(providers.claude_start)))

  @app.post("/api/providers/claude/exchange")
  async def claude_exchange(request: Request):
    _same_origin(request)
    await interactive(request)
    payload = await _json_body(request)
    await asyncio.to_thread(providers.claude_exchange, str(payload.get("code") or ""))
    return _security_headers(JSONResponse({"status": "connected"}))

  @app.post("/api/providers/codex/start")
  async def codex_start(request: Request):
    _same_origin(request)
    await interactive(request)
    return _security_headers(JSONResponse(await asyncio.to_thread(providers.codex_start)))

  @app.get("/api/providers/codex/status")
  async def codex_status(request: Request):
    await interactive(request)
    return _security_headers(JSONResponse(await asyncio.to_thread(providers.codex_status)))

  @app.get("/api/history")
  async def history(request: Request):
    _, session = await current(request)
    return _security_headers(JSONResponse({
      "messages": [
        {"role": message.role, "content": message.content}
        for message in session.history()
      ]
    }))

  @app.get("/api/turn")
  async def turn_status(request: Request):
    _, session = await current(request)
    return _security_headers(JSONResponse({
      "active": turn_active(), "finishing": session.finishing,
    }))

  @app.post("/api/chat/stream")
  async def chat_stream(request: Request):
    _same_origin(request)
    _, session = await interactive(request)
    payload = await _json_body(request)
    message, provider = payload.get("message"), payload.get("provider")
    if not isinstance(message, str) or not isinstance(provider, str):
      raise ProtocolError("invalid_request", "Message and provider are required.", 400)

    async def events():
      iterator = stream_turn(message, provider, session, providers, workspaces).__aiter__()
      async for frame in _sse_events(iterator):
        yield frame

    return _security_headers(StreamingResponse(
      events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"},
    ))

  def finish_response(progress: dict):
    response = JSONResponse(progress)
    if progress.get("status") == "finished":
      outcome = str(progress.get("outcome") or "recovered")
      response.delete_cookie(
        COOKIE_NAME, path="/", secure=settings.secure_cookie,
        httponly=True, samesite="strict",
      )
      response.set_cookie(
        CLOSED_COOKIE, outcome, max_age=600, path="/",
        secure=settings.secure_cookie, httponly=True, samesite="strict",
      )
    return _security_headers(response)

  @app.post("/api/finish")
  async def finish(request: Request):
    _same_origin(request)
    token, session = await current(request)
    payload = await _json_body(request)
    outcome = payload.get("outcome")
    if outcome not in {"recovered", "cancelled"}:
      raise ProtocolError("invalid_outcome", "Outcome is invalid.", 400)
    if not session.finishing and not claim_finish():
      raise ProtocolError("turn_active", "Wait for the active recovery turn to finish.", 409)
    progress = await asyncio.to_thread(sessions.begin_finish, token, outcome)
    return finish_response(progress)

  @app.get("/api/finish/status")
  async def finish_status(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
      raise ProtocolError("auth_required", "Recovery session expired.", 401)
    return finish_response(await asyncio.to_thread(sessions.poll_finish, token))

  return app
