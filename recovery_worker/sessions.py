"""Ephemeral one-time-code and browser-session state."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .control import ControlClient, ExchangeResult, FinishResult
from .protocol import ProtocolError, TargetCapability


COOKIE_NAME = "mobius_recovery_session"
LOCAL_SESSION_TTL = timedelta(minutes=30)
START_ATTEMPT_BURST = 6
START_ATTEMPT_REFILL_SECONDS = 30.0
MAX_CONCURRENT_STARTS = 1
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
  target: TargetCapability
  expires_at: datetime
  managed_exchange: ExchangeResult | None = None
  messages: list[Message] = field(default_factory=list)
  readiness_error: str | None = None
  finish_outcome: str | None = None
  finish_result: FinishResult | None = None
  finish_generation: int = 1
  resume_outcome: str | None = None
  provider_generation: int | None = None
  workspace: Path | None = None
  _history_chars: int = field(default=0, init=False, repr=False)
  _messages_lock: threading.Lock = field(
    default_factory=threading.Lock, init=False, repr=False
  )
  _revoked: bool = field(default=False, init=False, repr=False)
  _revoke_lock: threading.Lock = field(
    default_factory=threading.Lock, init=False, repr=False
  )
  _finish_lock: threading.Lock = field(
    default_factory=threading.Lock, init=False, repr=False
  )
  _finish_quiesced: bool = field(default=False, init=False, repr=False)

  def add_message(self, role: str, content: str) -> None:
    """Appends history while preserving a hard process-memory bound."""
    bounded = content[-MAX_STORED_MESSAGE_CHARS:]
    with self._revoke_lock:
      if self._revoked:
        return
      with self._messages_lock:
        self.messages.append(Message(role=role, content=bounded))
        self._history_chars += len(bounded)
        while (
          len(self.messages) > MAX_HISTORY_MESSAGES
          or self._history_chars > MAX_HISTORY_CHARS
        ):
          removed = self.messages.pop(0)
          self._history_chars -= len(removed.content)

  def history(self, limit: int = MAX_HISTORY_MESSAGES) -> list[Message]:
    with self._messages_lock:
      return list(self.messages[-limit:])

  @property
  def revoked(self) -> bool:
    with self._revoke_lock:
      return self._revoked

  @property
  def finishing(self) -> bool:
    with self._finish_lock:
      return self.finish_outcome is not None

  @property
  def generation(self) -> int:
    with self._finish_lock:
      return self.finish_generation

  def revoke(self) -> None:
    """Clears every target/control capability and retained conversation."""
    with self._revoke_lock:
      if self._revoked:
        return
      self._revoked = True
      target = self.target
      exchange = self.managed_exchange
      finish_target = (
        self.finish_result.target if self.finish_result else None
      )
      with self._messages_lock:
        self.messages.clear()
        self._history_chars = 0
    target.clear()
    if exchange:
      exchange.clear()
    if finish_target:
      finish_target.clear()


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
    on_revoke: Callable[[RecoverySession, str], None] | None = None,
    on_resume: Callable[[RecoverySession], None] | None = None,
    on_finish_accepted: Callable[[RecoverySession], None] | None = None,
    on_finish_released: Callable[[], None] | None = None,
  ) -> None:
    self._local_token = local_token
    self._local_target = local_target
    self._control = control
    self._instance_id = instance_id
    self._on_revoke = on_revoke
    self._on_resume = on_resume
    self._on_finish_accepted = on_finish_accepted
    self._on_finish_released = on_finish_released
    self._sessions: dict[str, RecoverySession] = {}
    self._used_codes: set[str] = set()
    self._starting_codes: set[str] = set()
    self._start_tokens = float(START_ATTEMPT_BURST)
    self._start_refill_at = time.monotonic()
    self._start_inflight = 0
    self._expiry_timer: threading.Timer | None = None
    self._lock = threading.Lock()

  @staticmethod
  def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

  def _schedule_expiry_locked(self) -> None:
    """Schedules the next deadline; caller must hold the store lock."""
    if self._expiry_timer:
      self._expiry_timer.cancel()
      self._expiry_timer = None
    if not self._sessions:
      return
    deadline = min(session.expires_at for session in self._sessions.values())
    delay = max(
      0.0,
      (deadline - datetime.now(timezone.utc)).total_seconds(),
    )
    self._expiry_timer = threading.Timer(delay, self.expire)
    self._expiry_timer.daemon = True
    self._expiry_timer.start()

  def start(self, code: str, instance_id: str | None) -> tuple[str, RecoverySession]:
    if not isinstance(code, str) or not code.strip() or len(code) > 4096:
      raise ProtocolError("auth_failed", "Recovery link is invalid or expired.", 401)
    # Reject target selection before touching the process-global launch bucket.
    # A hostile instance id must not consume another instance's wake allowance.
    if self._control is not None and (
      not instance_id
      or not hmac.compare_digest(instance_id, self._instance_id or "")
    ):
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
        assert instance_id is not None
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
      replaced = list(self._sessions.values())
      self._sessions.clear()
      self._sessions[browser_digest] = session
      self._schedule_expiry_locked()
    for old in replaced:
      self._revoke(old, "replaced")
    if session.managed_exchange and self._control:
      # The durable retry receipt is cleared only after the parsed capability
      # is reachable from this store. ACK is idempotent and transport-retried;
      # an ACK failure never discards the already usable recovery session.
      acknowledge = getattr(self._control, "acknowledge", None)
      if acknowledge:
        try:
          acknowledge(session.managed_exchange)
        except ProtocolError:
          pass
    return browser_token, session

  def _revoke(self, session: RecoverySession, reason: str) -> None:
    # Mark the session dead and erase its directly held capabilities before
    # any slower broker/process cleanup. New work must fail while cleanup runs.
    session.revoke()
    if self._on_revoke:
      self._on_revoke(session, reason)

  def expire(self) -> int:
    """Revokes all sessions whose controller deadline has passed."""
    now = datetime.now(timezone.utc)
    with self._lock:
      self._expiry_timer = None
      expired = [
        (digest, session)
        for digest, session in self._sessions.items()
        if session.expires_at <= now
      ]
      for digest, _session in expired:
        self._sessions.pop(digest, None)
      # Wall clocks can move and Timer may be awakened spuriously. Always
      # re-arm the nearest surviving deadline instead of losing cleanup.
      self._schedule_expiry_locked()
    for _digest, session in expired:
      self._revoke(session, "expired")
    return len(expired)

  def close(self) -> None:
    """Revokes all state during process shutdown."""
    with self._lock:
      sessions = list(self._sessions.values())
      self._sessions.clear()
      if self._expiry_timer:
        self._expiry_timer.cancel()
        self._expiry_timer = None
    for session in sessions:
      self._revoke(session, "shutdown")

  def get(self, browser_token: str | None) -> RecoverySession | None:
    if not browser_token:
      return None
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
      if (
        session
        and not session.revoked
        and session.expires_at > datetime.now(timezone.utc)
      ):
        return session
      if session:
        self._sessions.pop(digest, None)
        self._schedule_expiry_locked()
    if session:
      self._revoke(session, "expired")
    return None

  @staticmethod
  def _finish_payload(
    session: RecoverySession,
    result: FinishResult | None,
  ) -> dict:
    payload = {
      "status": result.status if result else "queued",
      "outcome": session.finish_outcome or (result.outcome if result else None),
      # The browser observes the session generation, never the generation of a
      # response object that may have become stale while runtime resume ran.
      "generation": session.finish_generation,
    }
    if result and result.finish_id:
      payload["finish_id"] = result.finish_id
    if result and result.error_code:
      payload["error"] = {
        "code": result.error_code,
        "message": result.error_message or "Recovery could not be finished.",
      }
    return payload

  @staticmethod
  def _discard_result_target(
    session: RecoverySession,
    result: FinishResult,
  ) -> None:
    if result.target is not None and result.target is not session.target:
      result.target.clear()

  def _stale_finish_payload_locked(
    self,
    session: RecoverySession,
    result: FinishResult,
  ) -> dict:
    self._discard_result_target(session, result)
    current = session.finish_result
    if current and current.generation == session.finish_generation:
      return self._finish_payload(session, current)
    return {
      "status": (
        "resumed"
        if result.generation < session.finish_generation
        else "queued" if session.finish_outcome else "resumed"
      ),
      "outcome": session.finish_outcome or result.outcome,
      "generation": session.finish_generation,
    }

  def _generation_payload_locked(
    self,
    session: RecoverySession,
    outcome: str,
    requested_generation: int,
  ) -> dict:
    current = session.finish_result
    if current and current.generation == session.finish_generation:
      return self._finish_payload(session, current)
    return {
      "status": (
        "resumed"
        if requested_generation < session.finish_generation
        else "queued"
      ),
      "outcome": session.finish_outcome or outcome,
      "generation": session.finish_generation,
    }

  def _fail_finish_closed(
    self,
    session: RecoverySession,
    outcome: str,
    generation: int,
    exc: Exception,
  ) -> dict:
    message = (
      exc.message if isinstance(exc, ProtocolError)
      else "The local recovery boundary could not close cleanly."
    )
    failure = FinishResult(
      finish_id=f"local_failure_{generation}",
      session_id=session.session_id,
      status="failed",
      outcome=outcome,
      generation=generation,
      status_url="",
      error_code=(
        exc.code if isinstance(exc, ProtocolError) else "finish_failed_closed"
      ),
      error_message=(
        f"{message} Target access remains closed; open Recovery again."
      )[:1000],
    )
    with session._finish_lock:
      if (
        session.finish_generation != generation
        or session.finish_outcome != outcome
      ):
        return self._stale_finish_payload_locked(session, failure)
      current = session.finish_result
      if (
        current
        and current.generation == generation
        and not current.pending
      ):
        return self._finish_payload(session, current)
      session.finish_result = failure
      session._finish_quiesced = True
      return self._finish_payload(session, failure)

  def _quiesce_finish(self, session: RecoverySession, outcome: str) -> None:
    with session._finish_lock:
      if session.finish_outcome is not None and session.finish_outcome != outcome:
        raise ProtocolError(
          "finish_outcome_conflict",
          "Recovery is already finishing with a different outcome.",
          409,
        )
      if session._finish_quiesced:
        return
      session.finish_outcome = outcome
      session.resume_outcome = None
    try:
      if self._on_finish_accepted:
        self._on_finish_accepted(session)
      with session._finish_lock:
        session._finish_quiesced = True
    finally:
      # The session capability is still needed for polling; the target bearer
      # is not. Clear it even if process cleanup reports an error.
      session.target.clear()

  def _apply_finish_result(
    self,
    digest: str,
    session: RecoverySession,
    result: FinishResult,
  ) -> dict:
    with session._finish_lock:
      if (
        result.generation != session.finish_generation
        or session.finish_outcome != result.outcome
      ):
        # A response from an older finish generation must never regress a
        # resumed target or the next finish attempt.
        return self._stale_finish_payload_locked(session, result)
      current = session.finish_result
      if current and (
        current.generation != result.generation
        or current.finish_id != result.finish_id
      ):
        self._discard_result_target(session, result)
        raise ProtocolError("invalid_control_response", "finish id changed")
      if current and not current.pending:
        self._discard_result_target(session, result)
        return self._finish_payload(session, current)
      session.finish_result = result
    if result.pending:
      return self._finish_payload(session, result)
    if result.status == "finished":
      with self._lock:
        removed = self._sessions.pop(digest, None)
        self._schedule_expiry_locked()
      if removed:
        self._revoke(session, "finished")
      return self._finish_payload(session, result)
    if (
      result.status == "resumed"
      and result.error_code == "normal_boot_failed"
      and result.target is not None
      and result.expires_at is not None
      and result.next_generation == result.generation + 1
    ):
      with self._lock:
        if self._sessions.get(digest) is not session or session.revoked:
          result.target.clear()
          raise ProtocolError("auth_expired", "Recovery session expired.", 401)
        # Store lock first prevents the expiry callback from removing the old
        # deadline while the fresh controller grant is installed.
        with session._finish_lock:
          session.target = result.target
          session.expires_at = result.expires_at
          assert session.managed_exchange is not None
          session.managed_exchange.target = result.target
          session.managed_exchange.expires_at = result.expires_at
          session.finish_generation = result.next_generation
        self._schedule_expiry_locked()
      if self._on_resume:
        try:
          self._on_resume(session)
          session.readiness_error = None
        except (OSError, ProtocolError) as exc:
          session.target.clear()
          assert session.managed_exchange is not None
          session.managed_exchange.target.clear()
          session.readiness_error = "The local target broker could not start."
          return self._fail_finish_closed(
            session, result.outcome, result.next_generation, exc
          )
      with session._finish_lock:
        if (
          session.finish_generation != result.next_generation
          or session.finish_result is not result
        ):
          return self._stale_finish_payload_locked(session, result)
        session.finish_outcome = None
        session.finish_result = None
        session._finish_quiesced = False
        session.resume_outcome = result.outcome
      if self._on_finish_released:
        self._on_finish_released()
      return {
        "status": "resumed",
        "outcome": result.outcome,
        "generation": result.next_generation,
      }
    return self._finish_payload(session, result)

  def begin_finish(
    self,
    browser_token: str,
    outcome: str,
    expected_generation: int | None = None,
  ) -> dict:
    if outcome not in {"recovered", "cancelled"}:
      raise ProtocolError("invalid_outcome", "invalid recovery outcome", 400)
    if expected_generation is not None and (
      isinstance(expected_generation, bool)
      or not isinstance(expected_generation, int)
      or expected_generation < 1
    ):
      raise ProtocolError("invalid_generation", "invalid finish generation", 400)
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
    if session is None:
      raise ProtocolError("auth_failed", "Recovery session expired.", 401)
    with session._finish_lock:
      if (
        expected_generation is not None
        and expected_generation != session.finish_generation
      ):
        return self._generation_payload_locked(
          session, outcome, expected_generation
        )
    if not session.managed_exchange or not self._control:
      with self._lock:
        removed = self._sessions.pop(digest, None)
        self._schedule_expiry_locked()
      if removed:
        self._revoke(session, "finished")
      return {
        "status": "finished",
        "outcome": outcome,
        "generation": session.finish_generation,
      }
    try:
      self._quiesce_finish(session, outcome)
    except Exception as exc:
      return self._fail_finish_closed(
        session, outcome, session.finish_generation, exc
      )
    with session._finish_lock:
      generation = session.finish_generation
      if (
        expected_generation is not None
        and expected_generation != generation
      ):
        return self._generation_payload_locked(
          session, outcome, expected_generation
        )
      existing = session.finish_result
      if existing and not existing.pending:
        return self._finish_payload(session, existing)

    try:
      result = self._control.finish(
        session.managed_exchange, outcome, generation
      )
    except ProtocolError as exc:
      if exc.code in {"control_timeout", "control_unreachable"}:
        # A lost response may follow a committed 202. The session was already
        # quiesced, so the same generation can be posted idempotently later.
        return self._finish_payload(session, None)
      return self._fail_finish_closed(session, outcome, generation, exc)

    try:
      return self._apply_finish_result(digest, session, result)
    except ProtocolError as exc:
      return self._fail_finish_closed(session, outcome, generation, exc)

  def poll_finish(self, browser_token: str) -> dict:
    digest = self._digest(browser_token)
    with self._lock:
      session = self._sessions.get(digest)
    if session is None:
      raise ProtocolError("auth_failed", "Recovery session expired.", 401)
    with session._finish_lock:
      outcome = session.finish_outcome
      existing = session.finish_result
      generation = session.finish_generation
      resume_outcome = session.resume_outcome
    if not outcome:
      if resume_outcome:
        return {
          "status": "resumed",
          "outcome": resume_outcome,
          "generation": generation,
        }
      raise ProtocolError("finish_not_started", "Recovery is not finishing.", 409)
    if existing and existing.generation != generation:
      return {
        "status": "running",
        "outcome": outcome,
        "generation": generation,
      }
    if existing and not existing.pending:
      return self._finish_payload(session, existing)
    if existing is None:
      return self.begin_finish(browser_token, outcome)
    assert session.managed_exchange is not None and self._control is not None
    try:
      result = self._control.poll_finish(session.managed_exchange, existing)
    except ProtocolError as exc:
      if exc.code in {"control_timeout", "control_unreachable"}:
        return self._finish_payload(session, existing)
      return self._fail_finish_closed(
        session, outcome, existing.generation, exc
      )
    try:
      return self._apply_finish_result(digest, session, result)
    except ProtocolError as exc:
      return self._fail_finish_closed(
        session, outcome, existing.generation, exc
      )

  def finish(self, browser_token: str, outcome: str) -> dict:
    """Backward-compatible name for the non-blocking finish start."""
    return self.begin_finish(browser_token, outcome)
