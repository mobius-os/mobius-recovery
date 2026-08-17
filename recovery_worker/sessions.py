"""Small process-local store for one ephemeral recovery session."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .control import ControlClient, ExchangeResult
from .protocol import ProtocolError


COOKIE_NAME = "mobius_recovery_session"
START_ATTEMPT_BURST = 6
START_ATTEMPT_REFILL_SECONDS = 30.0
MAX_HISTORY_MESSAGES = 100
MAX_HISTORY_CHARS = 256_000
MAX_STORED_MESSAGE_CHARS = 64_000


@dataclass
class Message:
  role: str
  content: str


@dataclass
class RecoverySession:
  session_id: str
  exchange: ExchangeResult
  messages: list[Message] = field(default_factory=list)
  readiness_error: str | None = None
  provider_generation: int | None = None
  workspace: Path | None = None
  _history_chars: int = field(default=0, init=False, repr=False)
  _messages_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
  _revoked: bool = field(default=False, init=False, repr=False)
  _revoke_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
  _finishing: bool = field(default=False, init=False, repr=False)
  _finish_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

  @property
  def finishing(self) -> bool:
    with self._finish_lock:
      return self._finishing

  @property
  def revoked(self) -> bool:
    with self._revoke_lock:
      return self._revoked

  def add_message(self, role: str, content: str) -> None:
    bounded = content[-MAX_STORED_MESSAGE_CHARS:]
    with self._revoke_lock:
      if self._revoked:
        return
      with self._messages_lock:
        self.messages.append(Message(role=role, content=bounded))
        self._history_chars += len(bounded)
        while len(self.messages) > MAX_HISTORY_MESSAGES or self._history_chars > MAX_HISTORY_CHARS:
          self._history_chars -= len(self.messages.pop(0).content)

  def history(self, limit: int = MAX_HISTORY_MESSAGES) -> list[Message]:
    with self._messages_lock:
      return list(self.messages[-limit:])

  def revoke(self) -> None:
    with self._revoke_lock:
      if self._revoked:
        return
      self._revoked = True
      self.exchange.clear()
      with self._messages_lock:
        self.messages.clear()
        self._history_chars = 0


class SessionStore:
  """Consumes one-time launch codes and retains at most one browser session."""

  def __init__(
    self,
    *,
    control: ControlClient,
    instance_id: str,
    on_revoke: Callable[[RecoverySession, str], None] | None = None,
    on_finish_accepted: Callable[[RecoverySession], None] | None = None,
  ) -> None:
    self._control = control
    self._instance_id = instance_id
    self._on_revoke = on_revoke
    self._on_finish_accepted = on_finish_accepted
    self._sessions: dict[str, RecoverySession] = {}
    self._used_codes: set[str] = set()
    self._starting_codes: set[str] = set()
    self._start_tokens = float(START_ATTEMPT_BURST)
    self._start_refill_at = time.monotonic()
    self._expiry_timer: threading.Timer | None = None
    self._lock = threading.Lock()

  @staticmethod
  def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

  def _schedule_expiry_locked(self) -> None:
    if self._expiry_timer:
      self._expiry_timer.cancel()
      self._expiry_timer = None
    if not self._sessions:
      return
    deadline = min(
      session.exchange.expires_at for session in self._sessions.values()
    )
    delay = max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())
    self._expiry_timer = threading.Timer(delay, self.expire)
    self._expiry_timer.daemon = True
    self._expiry_timer.start()

  def start(self, code: str, instance_id: str | None) -> tuple[str, RecoverySession]:
    if not isinstance(code, str) or not code.strip() or len(code) > 4096:
      raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
    if not instance_id or not hmac.compare_digest(instance_id, self._instance_id):
      raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
    code = code.strip()
    digest = self._digest(code)
    with self._lock:
      now = time.monotonic()
      elapsed = max(0.0, now - self._start_refill_at)
      self._start_tokens = min(
        float(START_ATTEMPT_BURST),
        self._start_tokens + elapsed / START_ATTEMPT_REFILL_SECONDS,
      )
      self._start_refill_at = now
      if self._start_tokens < 1.0 or self._starting_codes:
        raise ProtocolError("rate_limited", "Too many recovery launch attempts.", 429)
      if digest in self._used_codes:
        raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
      self._start_tokens -= 1.0
      self._starting_codes.add(digest)
    try:
      exchange = self._control.exchange(code, instance_id)
      session = RecoverySession(
        session_id=exchange.session_id,
        exchange=exchange,
      )
    except Exception:
      with self._lock:
        self._starting_codes.discard(digest)
      raise
    browser_token = secrets.token_urlsafe(32)
    browser_digest = self._digest(browser_token)
    with self._lock:
      self._starting_codes.discard(digest)
      self._used_codes.add(digest)
      replaced = list(self._sessions.values())
      self._sessions = {browser_digest: session}
      self._schedule_expiry_locked()
    for old in replaced:
      self._revoke(old, "replaced")
    try:
      self._control.acknowledge(exchange)
    except ProtocolError:
      # The launcher keeps an encrypted exchange receipt specifically so a
      # lost acknowledgement cannot strand the owner after the code exchange.
      # This worker still rejects the consumed code locally and server-side
      # expiry remains the cleanup authority.
      pass
    return browser_token, session

  def _revoke(self, session: RecoverySession, reason: str) -> None:
    session.revoke()
    if self._on_revoke:
      self._on_revoke(session, reason)

  def get(self, browser_token: str | None) -> RecoverySession | None:
    if not browser_token:
      return None
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
      if (
        session
        and not session.revoked
        and session.exchange.expires_at > datetime.now(timezone.utc)
      ):
        return session
      if session:
        self._sessions.pop(digest, None)
        self._schedule_expiry_locked()
    if session:
      self._revoke(session, "expired")
    return None

  def expire(self) -> int:
    now = datetime.now(timezone.utc)
    with self._lock:
      self._expiry_timer = None
      expired = [
        (digest, session) for digest, session in self._sessions.items()
        if session.exchange.expires_at <= now
      ]
      for digest, _session in expired:
        self._sessions.pop(digest, None)
      self._schedule_expiry_locked()
    for _digest, session in expired:
      self._revoke(session, "expired")
    return len(expired)

  def close(self) -> None:
    with self._lock:
      sessions = list(self._sessions.values())
      self._sessions.clear()
      if self._expiry_timer:
        self._expiry_timer.cancel()
        self._expiry_timer = None
    for session in sessions:
      self._revoke(session, "shutdown")

  def begin_finish(self, browser_token: str) -> dict:
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
    if not session:
      raise ProtocolError("auth_failed", "Recovery session expired.", 401)
    with session._finish_lock:
      first = not session._finishing
      session._finishing = True
    if first and self._on_finish_accepted:
      self._on_finish_accepted(session)
    result = self._control.finish(session.exchange)
    with self._lock:
      if self._sessions.get(digest) is session:
        self._sessions.pop(digest, None)
        self._schedule_expiry_locked()
    self._revoke(session, "finished")
    return result

  def poll_finish(self, browser_token: str) -> dict:
    session = self.get(browser_token)
    if not session or not session.finishing:
      raise ProtocolError("finish_not_started", "Recovery is not closing.", 409)
    return self.begin_finish(browser_token)
