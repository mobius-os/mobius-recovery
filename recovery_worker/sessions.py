"""Ephemeral one-time-code and browser-session state."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .control import ControlClient, ExchangeResult, RecoveryResumed
from .protocol import ProtocolError, TargetCapability


COOKIE_NAME = "mobius_recovery_session"
LOCAL_SESSION_TTL = timedelta(minutes=30)
START_ATTEMPT_BURST = 6
START_ATTEMPT_REFILL_SECONDS = 30.0
MAX_CONCURRENT_STARTS = 1


@dataclass
class Message:
  role: str
  content: str


@dataclass
class RecoverySession:
  session_id: str
  target: TargetCapability
  expires_at: datetime
  managed_exchange: ExchangeResult | None = None
  messages: list[Message] = field(default_factory=list)
  readiness_error: str | None = None


class SessionStore:
  """Single-owner, process-local recovery session store.

  Codes and browser tokens never touch disk. A successful start replaces any
  prior session and consumes its launch code. Restarting the worker invalidates
  everything, which is intentional for an on-demand recovery capability.
  """

  def __init__(
    self,
    *,
    local_token: str | None,
    local_target: TargetCapability | None,
    control: ControlClient | None,
    instance_id: str | None,
  ) -> None:
    self._local_token = local_token
    self._local_target = local_target
    self._control = control
    self._instance_id = instance_id
    self._sessions: dict[str, RecoverySession] = {}
    self._used_codes: set[str] = set()
    self._starting_codes: set[str] = set()
    self._start_tokens = float(START_ATTEMPT_BURST)
    self._start_refill_at = time.monotonic()
    self._start_inflight = 0
    self._lock = threading.Lock()

  @staticmethod
  def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

  def start(self, code: str, instance_id: str | None) -> tuple[str, RecoverySession]:
    if not isinstance(code, str) or not code.strip() or len(code) > 4096:
      raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
    code = code.strip()
    code_digest = self._digest(code)
    with self._lock:
      now = time.monotonic()
      elapsed = max(0.0, now - self._start_refill_at)
      self._start_tokens = min(
        float(START_ATTEMPT_BURST),
        self._start_tokens + elapsed / START_ATTEMPT_REFILL_SECONDS,
      )
      self._start_refill_at = now
      if (
        self._start_tokens < 1.0
        or self._start_inflight >= MAX_CONCURRENT_STARTS
      ):
        raise ProtocolError(
          "rate_limited",
          "Too many recovery launch attempts. Wait and open Recovery again.",
          429,
        )
      self._start_tokens -= 1.0
      self._start_inflight += 1
      if code_digest in self._used_codes or code_digest in self._starting_codes:
        self._start_inflight -= 1
        raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
      self._starting_codes.add(code_digest)

    try:
      if self._control is not None:
        if not instance_id or not hmac.compare_digest(instance_id, self._instance_id or ""):
          raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
        exchange = self._control.exchange(code, instance_id)
        session = RecoverySession(
          session_id=exchange.session_id,
          target=exchange.target,
          expires_at=exchange.expires_at,
          managed_exchange=exchange,
        )
      else:
        with self._lock:
          local_token = self._local_token
          valid = bool(local_token) and hmac.compare_digest(code, local_token or "")
          if not valid:
            raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
          self._local_token = None
        if self._local_target is None:
          raise ProtocolError("worker_misconfigured", "local target is unavailable", 500)
        session = RecoverySession(
          session_id=f"local-{secrets.token_hex(12)}",
          target=self._local_target,
          expires_at=datetime.now(timezone.utc) + LOCAL_SESSION_TTL,
        )
    except Exception:
      with self._lock:
        self._starting_codes.discard(code_digest)
        self._start_inflight -= 1
      raise

    browser_token = secrets.token_urlsafe(32)
    browser_digest = self._digest(browser_token)
    with self._lock:
      self._starting_codes.discard(code_digest)
      self._start_inflight -= 1
      self._used_codes.add(code_digest)
      self._sessions.clear()
      self._sessions[browser_digest] = session
    return browser_token, session

  def get(self, browser_token: str | None) -> RecoverySession | None:
    if not browser_token:
      return None
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
      if session and session.expires_at > datetime.now(timezone.utc):
        return session
      if session:
        self._sessions.pop(digest, None)
    return None

  def finish(self, browser_token: str, outcome: str) -> RecoverySession:
    if outcome not in {"recovered", "cancelled"}:
      raise ProtocolError("invalid_outcome", "invalid recovery outcome", 400)
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
    if session is None:
      raise ProtocolError("auth_failed", "Recovery session expired.", 401)
    if session.managed_exchange and self._control:
      try:
        self._control.finish(session.managed_exchange, outcome)
      except RecoveryResumed as resumed:
        with self._lock:
          # Swap all target-bearing state together. The existing browser and
          # finish capabilities remain valid for the resumed session.
          session.target = resumed.target
          session.expires_at = resumed.expires_at
          session.managed_exchange.target = resumed.target
          session.managed_exchange.expires_at = resumed.expires_at
        raise
    with self._lock:
      self._sessions.clear()
    session.target.token = ""  # Destroy the in-memory target capability.
    if session.managed_exchange:
      session.managed_exchange.session_capability = ""
    return session
