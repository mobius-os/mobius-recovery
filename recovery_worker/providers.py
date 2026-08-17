"""Ephemeral Claude PKCE and Codex device authentication."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import stat
import subprocess
import threading
import time
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .codex_login_parse import banner_has_code, parse_login_banner
from .config import STATE_DIR, WORKER_PROTOCOL_VERSION
from .protocol import ProtocolError


PROVIDERS_DIR = STATE_DIR / "providers"
CLAUDE_DIR = PROVIDERS_DIR / "claude"
CODEX_DIR = PROVIDERS_DIR / "codex"

_CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
_SCOPES = (
  "org:create_api_key user:profile user:inference "
  "user:sessions:claude_code user:mcp_servers user:file_upload"
)
_MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024
_CLAUDE_TOKEN_REFRESH_MARGIN_MS = 60_000


def _process_table() -> dict[int, tuple[int, str]]:
  processes: dict[int, tuple[int, str]] = {}
  try:
    entries = os.scandir("/proc")
  except OSError:
    return processes
  with entries:
    for entry in entries:
      if not entry.name.isdigit():
        continue
      try:
        stat = Path(entry.path, "stat").read_text(encoding="ascii")
        # comm may contain spaces and parentheses, so split after its final ')'.
        fields = stat.rsplit(")", 1)[1].strip().split()
        processes[int(entry.name)] = (int(fields[1]), fields[0])
      except (OSError, ValueError, IndexError):
        continue
  return processes


def descendant_pids(root_pid: int | None = None) -> set[int]:
  """Returns the live transitive child set from a single /proc snapshot."""
  root_pid = root_pid or os.getpid()
  processes = _process_table()
  descendants: set[int] = set()
  changed = True
  while changed:
    changed = False
    for pid, (parent, _state) in processes.items():
      if pid == root_pid or pid in descendants:
        continue
      if parent == root_pid or parent in descendants:
        descendants.add(pid)
        changed = True
  return descendants


def _reap_zombie_children() -> None:
  worker_pid = os.getpid()
  for pid, (parent, state) in _process_table().items():
    if parent != worker_pid or state != "Z":
      continue
    try:
      os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, ProcessLookupError):
      pass


def terminate_descendants(grace_seconds: float = 0.2) -> None:
  """Terminates provider helpers, including setsid/double-fork descendants."""
  descendants = descendant_pids()
  for pid in descendants:
    try:
      os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
      pass
  deadline = time.monotonic() + max(0.0, grace_seconds)
  while descendants and time.monotonic() < deadline:
    descendants &= descendant_pids()
    if descendants:
      time.sleep(0.01)
  # Repeat the snapshot after TERM: a dying parent can reparent a helper to the
  # worker between scans, and the subreaper makes that helper visible here.
  # Repeat after SIGKILL so a helper forked in the final parent-death race is
  # observed after the subreaper adopts it.
  for _round in range(5):
    current = descendant_pids()
    if not current:
      break
    for pid in current:
      try:
        os.kill(pid, signal.SIGKILL)
      except (ProcessLookupError, PermissionError):
        pass
    time.sleep(0.01)
    _reap_zombie_children()


def subprocess_env() -> dict[str, str]:
  """Returns an allowlisted environment with no worker control secret."""
  allowed = {
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
  }
  return {key: value for key, value in os.environ.items() if key in allowed}


class ProviderAuth:
  """Owns provider login state for this worker process only."""

  def __init__(self, *, claude_transport: httpx.BaseTransport | None = None) -> None:
    self._pkce: dict | None = None
    self._pkce_lock = threading.Lock()
    self._claude_refresh_lock = threading.Lock()
    self._claude_transport = claude_transport
    self._codex: dict = {"proc": None, "result": None, "output": ""}
    self._codex_lock = threading.Lock()
    self._state_lock = threading.Lock()
    self._state_changed = threading.Condition(self._state_lock)
    self._enabled = True
    self._generation = 0
    self._launches = 0

  def enable(self) -> int:
    with self._state_lock:
      self._generation += 1
      self._enabled = True
      return self._generation

  def active_generation(self) -> int:
    with self._state_lock:
      if not self._enabled:
        raise ProtocolError(
          "auth_expired", "Recovery provider session is closed.", 401
        )
      return self._generation

  @contextmanager
  def launch_guard(self, generation: int) -> Iterator[None]:
    """Serializes process creation against clear() and session replacement."""
    with self._state_changed:
      if not self._enabled or generation != self._generation:
        raise ProtocolError(
          "auth_expired", "Recovery provider session is closed.", 401
        )
      self._launches += 1
    try:
      yield
    finally:
      with self._state_changed:
        self._launches -= 1
        self._state_changed.notify_all()

  def status(self) -> dict[str, bool]:
    with self._state_lock:
      if not self._enabled:
        return {"claude": False, "codex": False}
    return {
      "claude": self._claude_credentials_usable(),
      "codex": (CODEX_DIR / "auth.json").is_file(),
    }

  @staticmethod
  def _claude_document() -> tuple[dict, dict] | None:
    path = CLAUDE_DIR / ".credentials.json"
    try:
      if path.stat().st_size > _MAX_PROVIDER_RESPONSE_BYTES:
        return None
      document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
      return None
    oauth = document.get("claudeAiOauth") if isinstance(document, dict) else None
    if not isinstance(oauth, dict):
      return None
    return document, oauth

  @staticmethod
  def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())

  @classmethod
  def _claude_access_current(cls, oauth: dict, *, margin_ms: int = 0) -> bool:
    expires_at = oauth.get("expiresAt")
    return (
      cls._nonempty(oauth.get("accessToken"))
      and isinstance(expires_at, (int, float))
      and not isinstance(expires_at, bool)
      and expires_at - time.time() * 1000 >= margin_ms
    )

  @classmethod
  def _claude_can_refresh(cls, oauth: dict) -> bool:
    refresh_expires_at = oauth.get("refreshTokenExpiresAt")
    return cls._nonempty(oauth.get("refreshToken")) and (
      "refreshTokenExpiresAt" not in oauth
      or (
        isinstance(refresh_expires_at, (int, float))
        and not isinstance(refresh_expires_at, bool)
        and refresh_expires_at > time.time() * 1000
      )
    )

  @classmethod
  def _claude_credentials_usable(cls) -> bool:
    loaded = cls._claude_document()
    if loaded is None:
      return False
    _document, oauth = loaded
    return cls._claude_access_current(oauth) or cls._claude_can_refresh(oauth)

  @staticmethod
  def _token_credentials(token_data: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")
    if (
      not isinstance(access_token, str)
      or not access_token.strip()
      or not isinstance(refresh_token, str)
      or not refresh_token.strip()
      or not isinstance(expires_in, (int, float))
      or isinstance(expires_in, bool)
      or expires_in <= 0
    ):
      raise ProtocolError(
        "provider_invalid", "Claude token response is incomplete.", 502
      )
    credentials = dict(previous)
    credentials.update({
      "accessToken": access_token,
      "refreshToken": refresh_token,
      "expiresAt": int(time.time() * 1000 + expires_in * 1000),
    })
    scope = token_data.get("scope")
    if isinstance(scope, str):
      credentials["scopes"] = scope.split()
    account = token_data.get("account")
    if isinstance(account, dict) and isinstance(account.get("email_address"), str):
      credentials["email"] = account["email_address"]
    refresh_expires_in = token_data.get("refresh_token_expires_in")
    if (
      isinstance(refresh_expires_in, (int, float))
      and not isinstance(refresh_expires_in, bool)
      and refresh_expires_in > 0
    ):
      credentials["refreshTokenExpiresAt"] = int(
        time.time() * 1000 + refresh_expires_in * 1000
      )
    return credentials

  def _claude_tokens(self, payload: dict, *, refreshing: bool) -> dict:
    try:
      with httpx.Client(
        timeout=30.0,
        trust_env=False,
        transport=self._claude_transport,
        headers={"User-Agent": WORKER_PROTOCOL_VERSION},
      ) as client:
        response = client.post(_TOKEN_URL, json=payload)
        if len(response.content) > _MAX_PROVIDER_RESPONSE_BYTES:
          raise ProtocolError(
            "provider_response_too_large", "Claude response is too large.", 502
          )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
      if exc.response.status_code == 429:
        message = "Claude is rate limiting authorization. Wait a moment and try again."
      elif refreshing:
        message = "Claude authorization expired. Reconnect Claude and retry."
      else:
        message = (
          "Claude rejected that authorization code. Start a new Claude "
          "connection and paste the newest code."
        )
      raise ProtocolError("provider_rejected", message, 502) from exc
    except httpx.TimeoutException as exc:
      raise ProtocolError("provider_timeout", "Claude login timed out.", 504) from exc
    except httpx.RequestError as exc:
      raise ProtocolError(
        "provider_unavailable", "Claude authorization could not be reached.", 502
      ) from exc
    try:
      token_data = response.json()
    except ValueError as exc:
      raise ProtocolError("provider_invalid", "Claude returned invalid data.", 502) from exc
    if not isinstance(token_data, dict):
      raise ProtocolError("provider_invalid", "Claude returned invalid data.", 502)
    return token_data

  def claude_start(self) -> dict:
    generation = self.active_generation()
    verifier = secrets.token_urlsafe(43)
    challenge = urlsafe_b64encode(
      hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    with self._state_lock:
      if not self._enabled or generation != self._generation:
        raise ProtocolError("auth_expired", "Recovery provider session is closed.", 401)
      with self._pkce_lock:
        self._pkce = {"verifier": verifier, "state": state, "ts": time.time()}
    query = urlencode({
      "code": "true",
      "client_id": _CLAUDE_CLIENT_ID,
      "response_type": "code",
      "redirect_uri": _REDIRECT_URI,
      "scope": _SCOPES,
      "code_challenge": challenge,
      "code_challenge_method": "S256",
      "state": state,
    })
    return {"auth_url": f"{_AUTHORIZE_URL}?{query}"}

  @staticmethod
  def _code_and_state(raw: str) -> tuple[str, str | None]:
    raw = raw.strip()
    parsed = urlparse(raw)
    if parsed.scheme and (parsed.query or parsed.fragment):
      values = {**parse_qs(parsed.query), **parse_qs(parsed.fragment)}
      return (values.get("code") or [raw])[0], (values.get("state") or [None])[0]
    if raw.startswith("code="):
      values = parse_qs(raw)
      return (values.get("code") or [raw])[0], (values.get("state") or [None])[0]
    code, _, fragment = raw.partition("#")
    values = parse_qs(fragment)
    return code, (values.get("state") or [None])[0]

  def claude_exchange(self, raw_code: str) -> None:
    generation = self.active_generation()
    if not raw_code or len(raw_code) > 8192:
      raise ProtocolError("invalid_code", "Authorization code is required.", 400)
    with self._pkce_lock:
      pkce = self._pkce
      self._pkce = None
    if not pkce:
      raise ProtocolError("missing_flow", "Start Claude login again.", 400)
    if time.time() - pkce["ts"] > 300:
      raise ProtocolError("expired_flow", "Claude login expired.", 400)
    code, returned_state = self._code_and_state(raw_code)
    if returned_state is not None and not secrets.compare_digest(
      returned_state, pkce["state"]
    ):
      raise ProtocolError("state_mismatch", "Claude login state mismatch.", 403)
    body = {
      "grant_type": "authorization_code",
      "code": code,
      "client_id": _CLAUDE_CLIENT_ID,
      "redirect_uri": _REDIRECT_URI,
      "code_verifier": pkce["verifier"],
      "state": pkce["state"],
    }
    token_data = self._claude_tokens(body, refreshing=False)
    credentials = {
      "claudeAiOauth": self._token_credentials(token_data)
    }
    self._private_json(
      CLAUDE_DIR / ".credentials.json", credentials, generation
    )

  def invalidate_claude(self, generation: int) -> None:
    with self._state_lock:
      if not self._enabled or generation != self._generation:
        return
      try:
        (CLAUDE_DIR / ".credentials.json").unlink()
      except FileNotFoundError:
        pass

  def ensure_claude(self, generation: int) -> None:
    """Hands each turn a current token and serializes rotating refresh grants."""
    with self._claude_refresh_lock:
      with self._state_lock:
        if not self._enabled or generation != self._generation:
          raise ProtocolError(
            "auth_expired", "Recovery provider session is closed.", 401
          )
      loaded = self._claude_document()
      if loaded is None:
        raise ProtocolError(
          "provider_auth_required", "Connect Claude before sending.", 401
        )
      document, oauth = loaded
      if self._claude_access_current(
        oauth, margin_ms=_CLAUDE_TOKEN_REFRESH_MARGIN_MS
      ):
        return
      if not self._claude_can_refresh(oauth):
        self.invalidate_claude(generation)
        raise ProtocolError(
          "provider_auth_required",
          "Claude authorization expired. Reconnect Claude and retry.",
          401,
        )
      try:
        token_data = self._claude_tokens({
          "grant_type": "refresh_token",
          "refresh_token": oauth["refreshToken"],
          "client_id": _CLAUDE_CLIENT_ID,
        }, refreshing=True)
      except ProtocolError as exc:
        if exc.code == "provider_rejected":
          self.invalidate_claude(generation)
          raise ProtocolError(
            "provider_auth_required",
            "Claude authorization expired. Reconnect Claude and retry.",
            401,
          ) from exc
        raise
      document["claudeAiOauth"] = self._token_credentials(token_data, oauth)
      self._private_json(
        CLAUDE_DIR / ".credentials.json", document, generation
      )

  def _private_json(self, path: Path, value: dict, generation: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
      with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
      with self._state_lock:
        if not self._enabled or generation != self._generation:
          raise ProtocolError(
            "auth_expired", "Recovery provider session is closed.", 401
          )
        os.replace(temp, path)
        path.chmod(0o600)
    finally:
      try:
        temp.unlink()
      except FileNotFoundError:
        pass

  @staticmethod
  def _kill(proc: subprocess.Popen | None) -> None:
    try:
      if proc is not None and proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
      try:
        if proc is not None:
          proc.kill()
      except OSError:
        pass

  def codex_start(self) -> dict:
    generation = self.active_generation()
    with self._codex_lock:
      old = self._codex.get("proc")
    self._kill(old)
    CODEX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CODEX_DIR.chmod(0o700)
    env = subprocess_env()
    env["HOME"] = str(STATE_DIR)
    env["CODEX_HOME"] = str(CODEX_DIR)
    with self._state_lock:
      if not self._enabled or generation != self._generation:
        raise ProtocolError("auth_expired", "Recovery provider session is closed.", 401)
      try:
        proc = subprocess.Popen(
          ["codex", "login", "--device-auth"],
          stdin=subprocess.DEVNULL,
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
          close_fds=True,
          env=env,
          text=True,
          start_new_session=True,
        )
      except OSError as exc:
        raise ProtocolError(
          "provider_missing", "Codex CLI could not start.", 500
        ) from exc
      with self._codex_lock:
        self._codex = {"proc": proc, "result": None, "output": ""}

    def reader() -> None:
      try:
        assert proc.stdout is not None
        for line in proc.stdout:
          with self._codex_lock:
            if self._codex.get("proc") is proc:
              self._codex["output"] = (self._codex["output"] + line)[-32768:]
      except Exception:
        pass
      proc.wait()
      with self._codex_lock:
        if self._codex.get("proc") is proc and self._codex.get("result") is None:
          self._codex["result"] = "complete" if proc.returncode == 0 else "failed"

    def watchdog() -> None:
      time.sleep(600)
      if proc.poll() is None:
        self._kill(proc)

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    deadline = time.time() + 15
    while time.time() < deadline:
      with self._codex_lock:
        output = self._codex["output"]
      if banner_has_code(output) or proc.poll() is not None:
        break
      time.sleep(0.2)
    with self._codex_lock:
      parsed = parse_login_banner(self._codex["output"])
    with self._state_lock:
      active = self._enabled and generation == self._generation
    if not active:
      self._kill(proc)
      raise ProtocolError("auth_expired", "Recovery provider session is closed.", 401)
    if parsed is None:
      self._kill(proc)
      raise ProtocolError("provider_invalid", "Could not read the Codex device code.", 500)
    return parsed

  def codex_status(self) -> dict:
    with self._codex_lock:
      proc = self._codex.get("proc")
      result = self._codex.get("result")
    if result in {"complete", "failed"}:
      return {"state": result}
    if proc is not None and proc.poll() is None:
      return {"state": "in_progress"}
    return {"state": "idle"}

  def terminate(self) -> None:
    with self._codex_lock:
      proc = self._codex.get("proc")
    self._kill(proc)

  def clear(self) -> None:
    """Destroys all ephemeral provider credentials and login state."""
    with self._state_changed:
      self._enabled = False
      self._generation += 1
      while self._launches:
        self._state_changed.wait()
    self.terminate()
    terminate_descendants()
    with self._pkce_lock:
      self._pkce = None
    with self._codex_lock:
      self._codex = {"proc": None, "result": None, "output": ""}
    for root in {CLAUDE_DIR.parent, CODEX_DIR.parent}:
      try:
        info = root.lstat()
      except FileNotFoundError:
        continue
      try:
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
          shutil.rmtree(root)
        else:
          root.unlink()
      except FileNotFoundError:
        pass
