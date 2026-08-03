"""HTTP entrypoint for the standalone Mobius recovery worker."""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .chat import (
  claim_finish,
  finish_active,
  release_finish,
  stream_turn,
  turn_active,
)
from .broker import BROKER_SOCKET, TargetBroker
from .config import WORKER_PROTOCOL_VERSION, Settings
from .control import ControlClient
from .pages import closed_page, login_page, lost_page, recovery_page
from .preflight import PreflightBindings, managed_target_url
from .protocol import ProtocolError, TargetCapability
from .providers import ProviderAuth
from .security import harden_process
from .sessions import COOKIE_NAME, RecoverySession, SessionStore
from .target_client import TargetClient
from .workspace import SessionWorkspaces, WORKSPACES_DIR


MAX_API_BODY = 64 * 1024
MAX_START_BODY = 16 * 1024
CLOSED_COOKIE = "mobius_recovery_closed"
SSE_KEEPALIVE_SECONDS = 15.0
MAX_BROWSER_SESSION_SECONDS = 60 * 60


def _target_health(
  capability: TargetCapability,
  transport: httpx.BaseTransport | None,
  allowed_modes: frozenset[str],
) -> dict:
  target = TargetClient(
    capability,
    allowed_modes=allowed_modes,
    transport=transport,
  )
  try:
    return target.health()
  finally:
    target.close()


def _target_self_revoke(
  capability: TargetCapability,
  transport: httpx.BaseTransport | None,
  allowed_modes: frozenset[str],
) -> dict[str, str]:
  """Use one fixed controller-supplied capability to revoke its own target sid."""
  target = TargetClient(
    capability,
    allowed_modes=allowed_modes,
    transport=transport,
  )
  try:
    return target.self_revoke()
  finally:
    target.close()


def _target_identity(result: dict, field: str) -> str:
  value = result.get(field)
  if not isinstance(value, str) or not 1 <= len(value) <= 128:
    raise ProtocolError(
      "invalid_response",
      f"Mobius target {field} is invalid.",
      502,
    )
  return value


class RecoveryRuntime:
  """Serializes broker/provider ownership for the one active session."""

  def __init__(
    self,
    providers: ProviderAuth,
    workspaces: SessionWorkspaces,
    preflight: PreflightBindings,
    *,
    target_transport,
    broker_path,
    target_modes: frozenset[str],
  ) -> None:
    self._providers = providers
    self._workspaces = workspaces
    self._preflight = preflight
    self._target_transport = target_transport
    self._broker_path = broker_path or BROKER_SOCKET
    self._target_modes = target_modes
    self._active: tuple[str, TargetBroker] | None = None
    self._sessions: SessionStore | None = None
    self._lock = threading.RLock()

  def bind_sessions(self, sessions: SessionStore) -> None:
    self._sessions = sessions

  def _broker_expired(self) -> None:
    sessions = self._sessions
    if sessions:
      sessions.expire()

  def activate(
    self,
    session: RecoverySession,
    *,
    clear_providers: bool = True,
    release_gate: bool = True,
  ) -> None:
    if session.revoked or session.expires_at <= datetime.now(timezone.utc):
      raise ProtocolError("auth_expired", "Recovery session expired.", 401)
    with self._lock:
      if session.revoked or session.expires_at <= datetime.now(timezone.utc):
        raise ProtocolError("auth_expired", "Recovery session expired.", 401)
      if self._active:
        self._active[1].stop()
        self._active = None
      if clear_providers:
        self._providers.clear()
      broker = None
      try:
        session.workspace = self._workspaces.create()
        session.provider_generation = self._providers.enable()
        broker = TargetBroker(
          session.target,
          allowed_modes=self._target_modes,
          transport=self._target_transport,
          path=self._broker_path,
          expires_at=session.expires_at,
          on_expire=self._broker_expired,
        )
        broker.start()
        if session.revoked or session.expires_at <= datetime.now(timezone.utc):
          raise ProtocolError("auth_expired", "Recovery session expired.", 401)
        self._active = (session.session_id, broker)
        self._preflight.clear()
        if release_gate:
          release_finish()
      except Exception:
        if broker:
          broker.stop()
        self._providers.clear()
        self._workspaces.clear()
        self._preflight.clear()
        session.provider_generation = None
        session.workspace = None
        raise

  def revoke(self, session: RecoverySession, reason: str) -> None:
    with self._lock:
      session.provider_generation = None
      session.workspace = None
      if self._active and self._active[0] != session.session_id:
        # Delayed expiry/replacement cleanup from an older session must not
        # erase the process-global state now owned by a newer active session.
        return
      active = None
      if self._active and self._active[0] == session.session_id:
        active = self._active[1]
        self._active = None
      try:
        if active:
          active.stop()
      finally:
        try:
          self._providers.clear()
        finally:
          try:
            self._workspaces.clear()
            self._preflight.clear()
          finally:
            if reason != "finishing":
              release_finish()

  def resume(self, session: RecoverySession) -> None:
    self.activate(session, clear_providers=False, release_gate=False)

  def quiesce(self, session: RecoverySession) -> None:
    """Revoke live target authority, then close every local target process."""
    try:
      with self._lock:
        if not self._active or self._active[0] != session.session_id:
          raise ProtocolError(
            "broker_unavailable", "target broker is unavailable", 502
          )
        self._active[1].self_revoke()
    finally:
      # Even an ambiguous remote failure must leave no local agent, socket, or
      # bearer able to continue. The exception propagates so controller finish
      # cannot be committed without a confirmed live-target revocation.
      self.revoke(session, "finishing")

  def close(self) -> None:
    with self._lock:
      try:
        if self._active:
          self._active[1].stop()
          self._active = None
      finally:
        try:
          self._providers.clear()
        finally:
          self._workspaces.clear()
          self._preflight.clear()
          release_finish()


def _nonce() -> str:
  return secrets.token_urlsafe(18)


def _cookie_max_age(
  session: RecoverySession,
  *,
  now: datetime | None = None,
) -> int:
  now = now or datetime.now(timezone.utc)
  remaining = int((session.expires_at - now).total_seconds())
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
    raise ProtocolError(
      "unsupported_media_type",
      "Request body must use application/json.",
      415,
    )
  length = request.headers.get("content-length")
  if length:
    try:
      if int(length) > limit:
        raise ProtocolError("request_too_large", "Request is too large.", 413)
    except ValueError:
      pass
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
    raise ProtocolError(
      "unsupported_media_type",
      "Session start requires a URL-encoded form.",
      415,
    )
  length = request.headers.get("content-length")
  if length:
    try:
      if int(length) > MAX_START_BODY:
        raise ProtocolError("request_too_large", "Session form exceeds 16 KiB.", 413)
    except ValueError:
      pass
  body = bytearray()
  async for chunk in request.stream():
    body.extend(chunk)
    if len(body) > MAX_START_BODY:
      raise ProtocolError("request_too_large", "Session form exceeds 16 KiB.", 413)
  try:
    parsed = parse_qs(
      body.decode("utf-8"),
      keep_blank_values=True,
      max_num_fields=4,
      encoding="utf-8",
      errors="strict",
    )
  except (UnicodeDecodeError, ValueError) as exc:
    raise ProtocolError("invalid_form", "Session form is invalid.", 400) from exc
  return {
    key: values[0]
    for key, values in parsed.items()
    if key in {"code", "instance_id"} and values
  }


def _same_origin(request: Request) -> None:
  # Sec-Fetch-Site and Origin are forbidden browser request headers. Requiring
  # both avoids relying on cookie SameSite/PSL behavior between sibling Railway
  # domains and avoids trusting proxy-rewritten URL schemes.
  if request.headers.get("sec-fetch-site", "").lower() != "same-origin":
    raise ProtocolError("cross_site", "Cross-site request rejected.", 403)
  origin = request.headers.get("origin", "")
  parsed = urlparse(origin)
  host = request.headers.get("host", "")
  if (
    parsed.scheme not in {"http", "https"}
    or not parsed.netloc
    or parsed.netloc.lower() != host.lower()
    or parsed.path not in {"", "/"}
    or parsed.params
    or parsed.query
    or parsed.fragment
    or parsed.username
    or parsed.password
  ):
    raise ProtocolError("cross_site", "Cross-site request rejected.", 403)


def _require_controller_auth(request: Request, settings: Settings) -> None:
  if not settings.managed or not settings.bootstrap_secret:
    raise ProtocolError("not_found", "Endpoint not found.", 404)
  supplied = request.headers.get("authorization", "")
  expected = f"Bearer {settings.bootstrap_secret}"
  if len(supplied) > 1024 or not hmac.compare_digest(
    supplied.encode("utf-8", "surrogatepass"),
    expected.encode("utf-8"),
  ):
    raise ProtocolError("unauthorized", "Invalid controller credential.", 401)


async def _sse_events(iterator, keepalive: float = SSE_KEEPALIVE_SECONDS):
  """Frames an event iterator and keeps silent remote tools through proxies."""
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


def create_app(
  settings: Settings | None = None,
  *,
  control_transport: httpx.BaseTransport | None = None,
  target_transport: httpx.BaseTransport | None = None,
  broker_path=None,
  workspace_root=None,
) -> FastAPI:
  """Creates one worker app; injection points are test-only transports."""
  settings = settings or Settings.from_env()
  settings.validate()
  target_modes = (
    frozenset({"normal", "recovery"})
    if settings.managed else frozenset({"recovery"})
  )
  preflight = PreflightBindings()
  control = (
    ControlClient(
      settings,
      target_validator=preflight.consume,
      transport=control_transport,
    )
    if settings.managed else None
  )
  local_target = (
    None if settings.managed else TargetCapability.parse(
      settings.local_target_url, settings.local_target_token
    )
  )
  providers = ProviderAuth()
  resolved_workspace_root = (
    Path(workspace_root)
    if workspace_root is not None
    else (
      Path(broker_path).parent / "workspaces"
      if broker_path is not None else WORKSPACES_DIR
    )
  )
  workspaces = SessionWorkspaces(resolved_workspace_root)
  runtime = RecoveryRuntime(
    providers,
    workspaces,
    preflight,
    target_transport=target_transport,
    broker_path=broker_path,
    target_modes=target_modes,
  )
  sessions = SessionStore(
    local_token=settings.local_token,
    local_target=local_target,
    control=control,
    instance_id=settings.instance_id,
    on_revoke=runtime.revoke,
    on_resume=runtime.resume,
    on_finish_accepted=runtime.quiesce,
    on_finish_released=release_finish,
  )
  runtime.bind_sessions(sessions)

  @asynccontextmanager
  async def lifespan(_app: FastAPI):
    harden_process()
    yield
    await asyncio.to_thread(sessions.close)
    await asyncio.to_thread(runtime.close)
    if control:
      await asyncio.to_thread(control.close)

  app = FastAPI(
    title="Mobius Recovery Worker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
  )
  app.state.settings = settings
  app.state.sessions = sessions
  app.state.providers = providers
  app.state.runtime = runtime
  app.state.preflight_bindings = preflight
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
      raise ProtocolError(
        "finish_in_progress",
        "Recovery is already finishing; target access is closed.",
        409,
      )
    return token, session

  def launch_origin(request: Request) -> None:
    if not settings.managed:
      _same_origin(request)
      return
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site not in {"cross-site", "same-site", "same-origin"}:
      raise ProtocolError("cross_site", "Recovery handoff origin rejected.", 403)
    supplied = urlparse(request.headers.get("origin", ""))
    expected = urlparse(settings.control_plane_url or "")
    try:
      supplied_port = supplied.port or (443 if supplied.scheme == "https" else 80)
      expected_port = expected.port or (443 if expected.scheme == "https" else 80)
    except ValueError as exc:
      raise ProtocolError(
        "cross_site", "Recovery handoff origin rejected.", 403
      ) from exc
    if (
      supplied.scheme != expected.scheme
      or not supplied.hostname
      or supplied.hostname.lower() != (expected.hostname or "").lower()
      or supplied_port != expected_port
      or supplied.path not in {"", "/"}
      or supplied.params
      or supplied.query
      or supplied.fragment
      or supplied.username
      or supplied.password
    ):
      raise ProtocolError("cross_site", "Recovery handoff origin rejected.", 403)

  @app.get("/health")
  async def health():
    return _security_headers(JSONResponse({
      "status": "ready",
      "build_sha": settings.build_sha,
      "protocol_version": WORKER_PROTOCOL_VERSION,
      "service_id": settings.service_id,
    }))

  @app.post("/internal/target/verify")
  async def verify_target(request: Request):
    _require_controller_auth(request, settings)
    payload = await _json_body(request, 16 * 1024)
    if set(payload) != {"target_url", "target_token"}:
      raise ProtocolError(
        "invalid_request",
        "target_url and target_token are required.",
        400,
      )
    target_url = managed_target_url(payload.get("target_url"))
    capability = TargetCapability.parse(target_url, payload.get("target_token"))
    result = await asyncio.to_thread(
      _target_health, capability, target_transport, target_modes
    )
    response = {
      "status": "ok",
      "protocol": result["protocol"],
      "build_sha": _target_identity(result, "build_sha"),
      "mode": result["mode"],
    }
    deployment_id = result.get("deployment_id")
    if deployment_id is not None:
      response["deployment_id"] = _target_identity(result, "deployment_id")
    elif result["mode"] == "normal":
      _target_identity(result, "deployment_id")
    # A normal live target is a process-local authority.  Forward its exact
    # per-boot identity so the controller can bind the eventual session token
    # to this container incarnation; a restart then invalidates the old token
    # even when Railway keeps the deployment id unchanged.  Legacy stopped-app
    # targets intentionally have no boot identity.
    if result["mode"] == "normal":
      response["boot_id"] = _target_identity(result, "boot_id")
    preflight.record(capability)
    return _security_headers(JSONResponse(response))

  @app.post("/internal/target/revoke")
  async def revoke_target(request: Request):
    """Controller-only close path for the exact supplied target capability."""
    _require_controller_auth(request, settings)
    payload = await _json_body(request, 16 * 1024)
    if set(payload) != {"target_url", "target_token"}:
      raise ProtocolError(
        "invalid_request",
        "target_url and target_token are required.",
        400,
      )
    target_url = managed_target_url(payload.get("target_url"))
    capability = TargetCapability.parse(target_url, payload.get("target_token"))
    try:
      result = await asyncio.to_thread(
        _target_self_revoke,
        capability,
        target_transport,
        target_modes,
      )
    finally:
      capability.clear()
    # Identity comes only from the authenticated target response. The caller
    # cannot submit deployment/session fields for the worker to reflect.
    return _security_headers(JSONResponse(result))

  @app.get("/", response_class=HTMLResponse)
  async def index(request: Request):
    nonce = _nonce()
    browser_token = request.cookies.get(COOKIE_NAME)
    session = await asyncio.to_thread(sessions.get, browser_token)
    if session is None:
      closed = request.cookies.get(CLOSED_COOKIE)
      if closed in {"recovered", "cancelled"}:
        body = closed_page(
          nonce,
          local=not settings.managed,
          outcome=closed,
          return_url=settings.control_plane_url if settings.managed else None,
        )
      elif browser_token and settings.managed:
        body = lost_page(nonce, return_url=settings.control_plane_url)
      else:
        body = login_page(
          nonce,
          instance_id=settings.instance_id if settings.managed else "",
        )
    else:
      body = recovery_page(
        nonce,
        protocol_version=WORKER_PROTOCOL_VERSION,
        build_sha=settings.build_sha,
        session_id=session.session_id,
        generation=session.generation,
        readiness_error=session.readiness_error,
        finishing=session.finishing,
        finish_result=session.finish_result,
      )
    return _security_headers(HTMLResponse(body), nonce)

  @app.post("/session/start", response_class=HTMLResponse)
  async def session_start(request: Request):
    nonce = _nonce()
    launch_origin(request)
    try:
      form = await _start_form(request)
      code = form.get("code", "")
      instance_id = form.get("instance_id") or None
      browser_token, session = await asyncio.to_thread(
        sessions.start, code, instance_id
      )
    except ProtocolError as exc:
      body = login_page(
        nonce,
        instance_id=settings.instance_id if settings.managed else "",
        error=exc.message,
      )
      return _security_headers(HTMLResponse(body, status_code=exc.status), nonce)
    try:
      await asyncio.to_thread(
        _target_health, session.target, target_transport, target_modes
      )
      session.readiness_error = None
    except ProtocolError as exc:
      session.readiness_error = exc.message
    try:
      await asyncio.to_thread(runtime.activate, session)
    except (OSError, ProtocolError):
      session.readiness_error = "The local target broker could not start."
    body = recovery_page(
      nonce,
      protocol_version=WORKER_PROTOCOL_VERSION,
      build_sha=settings.build_sha,
      session_id=session.session_id,
      generation=session.generation,
      readiness_error=session.readiness_error,
    )
    response = HTMLResponse(body, status_code=200)
    response.set_cookie(
      COOKIE_NAME,
      browser_token,
      max_age=_cookie_max_age(session),
      httponly=True,
      secure=settings.secure_cookie,
      samesite="strict",
      path="/",
    )
    response.delete_cookie(
      CLOSED_COOKIE,
      path="/",
      secure=settings.secure_cookie,
      httponly=True,
      samesite="strict",
    )
    return _security_headers(response, nonce)

  @app.get("/api/providers")
  async def provider_status(request: Request):
    await interactive(request)
    status = await asyncio.to_thread(providers.status)
    return _security_headers(JSONResponse(status))

  @app.get("/api/target/health")
  async def target_health(request: Request):
    _, session = await interactive(request)
    try:
      result = await asyncio.to_thread(
        _target_health, session.target, target_transport, target_modes
      )
      session.readiness_error = None
      return _security_headers(JSONResponse({"status": "ready", "target": result}))
    except ProtocolError as exc:
      session.readiness_error = exc.message
      raise

  @app.post("/api/providers/claude/start")
  async def claude_start(request: Request):
    _same_origin(request)
    await interactive(request)
    result = await asyncio.to_thread(providers.claude_start)
    return _security_headers(JSONResponse(result))

  @app.post("/api/providers/claude/exchange")
  async def claude_exchange(request: Request):
    _same_origin(request)
    await interactive(request)
    payload = await _json_body(request)
    await asyncio.to_thread(
      providers.claude_exchange, str(payload.get("code") or "")
    )
    return _security_headers(JSONResponse({"status": "connected"}))

  @app.post("/api/providers/codex/start")
  async def codex_start(request: Request):
    _same_origin(request)
    await interactive(request)
    result = await asyncio.to_thread(providers.codex_start)
    return _security_headers(JSONResponse(result))

  @app.get("/api/providers/codex/status")
  async def codex_status(request: Request):
    await interactive(request)
    status = await asyncio.to_thread(providers.codex_status)
    return _security_headers(JSONResponse(status))

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
      "active": turn_active(),
      "finishing": session.finishing,
    }))

  @app.post("/api/chat/stream")
  async def chat_stream(request: Request):
    _same_origin(request)
    _, session = await interactive(request)
    payload = await _json_body(request)
    message = payload.get("message")
    provider = payload.get("provider")
    if not isinstance(message, str) or not isinstance(provider, str):
      raise ProtocolError("invalid_request", "Message and provider are required.", 400)

    async def events():
      iterator = stream_turn(
        message, provider, session, providers, workspaces
      ).__aiter__()
      async for frame in _sse_events(iterator):
        yield frame

    return _security_headers(StreamingResponse(
      events(),
      media_type="text/event-stream",
      headers={"X-Accel-Buffering": "no"},
    ))

  @app.post("/api/finish")
  async def finish(request: Request):
    _same_origin(request)
    token, session = await current(request)
    payload = await _json_body(request)
    outcome = payload.get("outcome")
    if not isinstance(outcome, str):
      raise ProtocolError("invalid_outcome", "Outcome is required.", 400)
    requested_generation = payload.get("generation")
    if (
      isinstance(requested_generation, bool)
      or not isinstance(requested_generation, int)
      or requested_generation < 1
    ):
      raise ProtocolError("invalid_generation", "Generation is required.", 400)
    stale_progress = None
    # Pair the browser generation check with gate acquisition. A delayed g1
    # request must not claim an idle gate after another request resumes g2,
    # while a true concurrent g1 request may safely share its idempotent job.
    with session._finish_lock:
      if requested_generation < session.finish_generation:
        stale_progress = {
          "status": "resumed",
          "outcome": outcome,
          "generation": session.finish_generation,
        }
      elif requested_generation > session.finish_generation:
        raise ProtocolError(
          "invalid_generation", "Finish generation is not current.", 409
        )
      elif not finish_active() and not claim_finish():
        raise ProtocolError(
          "turn_active",
          "Wait for the active recovery turn to finish before closing recovery.",
          409,
        )
    if stale_progress is not None:
      return _finish_http_response(stale_progress)
    # Cancellation deliberately leaves the process-wide gate claimed. The
    # executor may already be about to quiesce the session even if the browser
    # task observes cancellation first, so reopening here would create a race.
    # Only a successful resume or session revocation releases the gate.
    progress = await asyncio.to_thread(
      sessions.begin_finish, token, outcome, requested_generation
    )
    return _finish_http_response(progress)

  @app.get("/api/finish/status")
  async def finish_status(request: Request):
    token, _session = await current(request)
    progress = await asyncio.to_thread(sessions.poll_finish, token)
    return _finish_http_response(progress)

  def _finish_http_response(progress: dict):
    status = progress.get("status")
    response = JSONResponse(
      progress,
      status_code=202 if status in {"queued", "running"} else 200,
    )
    if status == "finished":
      outcome = str(progress.get("outcome") or "recovered")
      response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=settings.secure_cookie,
        httponly=True,
        samesite="strict",
      )
      response.set_cookie(
        CLOSED_COOKIE,
        outcome,
        max_age=600,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        path="/",
      )
    return _security_headers(response)

  return app
