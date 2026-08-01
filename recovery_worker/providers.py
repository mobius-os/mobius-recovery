"""Ephemeral Claude PKCE and Codex device authentication."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from base64 import urlsafe_b64encode
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .codex_login_parse import banner_has_code, parse_login_banner
from .config import STATE_DIR
from .protocol import ProtocolError


CLAUDE_DIR = STATE_DIR / "providers" / "claude"
CODEX_DIR = STATE_DIR / "providers" / "codex"

_CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
_SCOPES = (
  "org:create_api_key user:profile user:inference "
  "user:sessions:claude_code user:mcp_servers user:file_upload"
)


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

  def __init__(self) -> None:
    self._pkce: dict | None = None
    self._pkce_lock = threading.Lock()
    self._codex: dict = {"proc": None, "result": None, "output": ""}
    self._codex_lock = threading.Lock()

  def status(self) -> dict[str, bool]:
    return {
      "claude": (CLAUDE_DIR / ".credentials.json").is_file(),
      "codex": (CODEX_DIR / "auth.json").is_file(),
    }

  def claude_start(self) -> dict:
    verifier = secrets.token_urlsafe(43)
    challenge = urlsafe_b64encode(
      hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
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
    body = json.dumps({
      "grant_type": "authorization_code",
      "code": code,
      "client_id": _CLAUDE_CLIENT_ID,
      "redirect_uri": _REDIRECT_URI,
      "code_verifier": pkce["verifier"],
      "state": pkce["state"],
    }).encode("utf-8")
    request = urllib.request.Request(
      _TOKEN_URL,
      data=body,
      headers={"Content-Type": "application/json"},
      method="POST",
    )
    try:
      # Ignore process proxy variables. Railway service variables are mutable
      # deployment input and must not receive OAuth codes or provider tokens.
      opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
      with opener.open(request, timeout=30) as response:
        try:
          response_length = int(
            response.headers.get("content-length", "0") or 0
          )
        except (TypeError, ValueError) as exc:
          raise ProtocolError(
            "provider_invalid", "Claude returned invalid response metadata."
          ) from exc
        if response_length > 1024 * 1024:
          raise ProtocolError("provider_response_too_large", "Claude response is too large")
        raw_response = response.read(1024 * 1024 + 1)
        if len(raw_response) > 1024 * 1024:
          raise ProtocolError(
            "provider_response_too_large", "Claude response is too large"
          )
        token_data = json.loads(raw_response.decode("utf-8"))
    except urllib.error.HTTPError as exc:
      raise ProtocolError("provider_rejected", "Claude rejected the login.", 502) from exc
    except (urllib.error.URLError, socket.timeout) as exc:
      raise ProtocolError("provider_timeout", "Claude login timed out.", 504) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
      raise ProtocolError("provider_invalid", "Claude returned invalid data.", 502) from exc
    for field in ("access_token", "refresh_token", "expires_in"):
      if field not in token_data:
        raise ProtocolError("provider_invalid", "Claude token response is incomplete.")
    credentials = {
      "claudeAiOauth": {
        "accessToken": token_data["access_token"],
        "refreshToken": token_data["refresh_token"],
        "expiresAt": int(time.time() * 1000) + int(token_data["expires_in"]) * 1000,
        "scopes": str(token_data.get("scope", "")).split(),
        "email": (token_data.get("account") or {}).get("email_address", ""),
      }
    }
    self._private_json(CLAUDE_DIR / ".credentials.json", credentials)

  @staticmethod
  def _private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
      with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
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
    with self._codex_lock:
      old = self._codex.get("proc")
    self._kill(old)
    CODEX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CODEX_DIR.chmod(0o700)
    env = subprocess_env()
    env["HOME"] = str(STATE_DIR)
    env["CODEX_HOME"] = str(CODEX_DIR)
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
      raise ProtocolError("provider_missing", "Codex CLI could not start.", 500) from exc
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
    self.terminate()
    for path in (CLAUDE_DIR, CODEX_DIR):
      shutil.rmtree(path, ignore_errors=True)
