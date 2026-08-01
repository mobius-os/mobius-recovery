from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import threading

import httpx
import pytest

from recovery_worker.config import Settings
from recovery_worker import control as control_module
from recovery_worker.control import ControlClient, ExchangeResult, FinishResult
from recovery_worker.protocol import ProtocolError, TargetCapability
from recovery_worker import sessions as sessions_module
from recovery_worker.sessions import SessionStore
from recovery_worker.sessions import (
  MAX_HISTORY_CHARS,
  MAX_HISTORY_MESSAGES,
  MAX_STORED_MESSAGE_CHARS,
  RecoverySession,
)


LOCAL_CODE = "local-code-" + "c" * 32
OLD_TOKEN = "old-target-" + "o" * 32
NEW_TOKEN = "new-target-" + "n" * 32
MANAGED_TARGET_URL = "http://mobius.railway.internal:18002"


def _target_token_sha256(token: str) -> str:
  return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_managed_target(
  target: TargetCapability, advertised_token_sha256: object
) -> None:
  assert target.base_url == MANAGED_TARGET_URL
  assert advertised_token_sha256 == _target_token_sha256(target.token)


def test_wrong_managed_instance_does_not_consume_global_launch_limit() -> None:
  class AcceptingControl:
    calls = 0

    def exchange(self, code, _instance_id):
      self.calls += 1
      return ExchangeResult(
        session_id=code,
        target=TargetCapability(MANAGED_TARGET_URL, OLD_TOKEN),
        session_capability="finish-" + "f" * 40,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
      )

  control = AcceptingControl()
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="mob_instance-1",
  )
  for _attempt in range(sessions_module.START_ATTEMPT_BURST + 3):
    with pytest.raises(ProtocolError) as rejected:
      store.start("attacker-code", "mob_someone-else")
    assert rejected.value.status == 401
  assert store._start_tokens == sessions_module.START_ATTEMPT_BURST
  browser, _session = store.start("valid-code", "mob_instance-1")
  assert store.get(browser) is not None
  assert control.calls == 1
  store.close()


def test_expiry_revokes_all_capabilities_and_history() -> None:
  revoked = threading.Event()
  reasons: list[str] = []

  class ExpiringControl:
    def exchange(self, _code, _instance_id):
      return ExchangeResult(
        session_id="expiring",
        target=TargetCapability(MANAGED_TARGET_URL, OLD_TOKEN),
        session_capability="finish-" + "f" * 40,
        expires_at=datetime.now(timezone.utc) + timedelta(milliseconds=120),
      )

  def on_revoke(_session, reason):
    reasons.append(reason)
    revoked.set()

  store = SessionStore(
    local_token=None,
    local_target=None,
    control=ExpiringControl(),
    instance_id="mob_instance-1",
    on_revoke=on_revoke,
  )
  browser, session = store.start("valid-code", "mob_instance-1")
  session.add_message("user", "secret conversation")
  exchange = session.managed_exchange
  assert exchange is not None
  assert revoked.wait(2)
  deadline = __import__("time").monotonic() + 2
  while session.target.token and __import__("time").monotonic() < deadline:
    __import__("time").sleep(0.01)
  assert reasons == ["expired"]
  assert store.get(browser) is None
  assert session.target.base_url == ""
  assert session.target.token == ""
  assert exchange.session_capability == ""
  assert session.history() == []


def test_early_expiry_check_rearms_the_exact_cleanup_timer() -> None:
  revoked = threading.Event()
  store = SessionStore(
    local_token=LOCAL_CODE,
    local_target=TargetCapability("http://target.internal", OLD_TOKEN),
    control=None,
    instance_id=None,
    on_revoke=lambda _session, _reason: revoked.set(),
  )
  browser, session = store.start(LOCAL_CODE, None)
  with store._lock:
    session.expires_at = datetime.now(timezone.utc) + timedelta(milliseconds=120)
    store._schedule_expiry_locked()

  assert store.expire() == 0
  assert revoked.wait(2)
  assert store.get(browser) is None
  assert session.revoked


def test_recovery_history_has_hard_count_and_character_bounds() -> None:
  session = RecoverySession(
    session_id="bounded",
    target=TargetCapability("http://target.internal", OLD_TOKEN),
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
  )
  for index in range(MAX_HISTORY_MESSAGES * 3):
    session.add_message("user", f"{index}:" + "x" * MAX_STORED_MESSAGE_CHARS)
  history = session.history(MAX_HISTORY_MESSAGES * 4)
  assert len(history) <= MAX_HISTORY_MESSAGES
  assert sum(len(message.content) for message in history) <= MAX_HISTORY_CHARS
  assert all(len(message.content) <= MAX_STORED_MESSAGE_CHARS for message in history)


def test_failed_launches_are_globally_bounded_without_state_growth(
  monkeypatch,
) -> None:
  clock = [100.0]
  monkeypatch.setattr(sessions_module.time, "monotonic", lambda: clock[0])

  class RejectingControl:
    calls = 0

    def exchange(self, _code, _instance_id):
      self.calls += 1
      raise ProtocolError("exchange_rejected", "invalid", 401)

  control = RejectingControl()
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="mob_instance-1",
  )
  for attempt in range(sessions_module.START_ATTEMPT_BURST):
    with pytest.raises(ProtocolError) as rejected:
      store.start(f"invalid-code-{attempt}", "mob_instance-1")
    assert rejected.value.status == 401

  with pytest.raises(ProtocolError) as limited:
    store.start("one-too-many", "mob_instance-1")
  assert limited.value.status == 429
  assert limited.value.code == "rate_limited"
  assert control.calls == sessions_module.START_ATTEMPT_BURST
  assert store._starting_codes == set()
  assert store._used_codes == set()
  assert store._start_inflight == 0

  clock[0] += sessions_module.START_ATTEMPT_REFILL_SECONDS
  with pytest.raises(ProtocolError) as refilled:
    store.start("after-refill", "mob_instance-1")
  assert refilled.value.status == 401
  assert control.calls == sessions_module.START_ATTEMPT_BURST + 1


def test_launch_exchange_concurrency_is_capped() -> None:
  entered = threading.Event()
  release = threading.Event()

  class BlockingControl:
    def __init__(self):
      self.calls = 0
      self.lock = threading.Lock()

    def exchange(self, code, _instance_id):
      with self.lock:
        self.calls += 1
        if self.calls == sessions_module.MAX_CONCURRENT_STARTS:
          entered.set()
      assert release.wait(5)
      return ExchangeResult(
        session_id=code,
        target=TargetCapability(MANAGED_TARGET_URL, OLD_TOKEN),
        session_capability="finish-" + "f" * 40,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
      )

  control = BlockingControl()
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="mob_instance-1",
  )
  failures: list[Exception] = []

  def begin(code: str) -> None:
    try:
      store.start(code, "mob_instance-1")
    except Exception as exc:
      failures.append(exc)

  workers = [
    threading.Thread(target=begin, args=(f"valid-code-{index}",))
    for index in range(sessions_module.MAX_CONCURRENT_STARTS)
  ]
  for worker in workers:
    worker.start()
  assert entered.wait(5)
  with pytest.raises(ProtocolError) as limited:
    store.start("third-code", "mob_instance-1")
  assert limited.value.status == 429
  release.set()
  for worker in workers:
    worker.join(5)
  assert not failures
  assert all(not worker.is_alive() for worker in workers)
  assert control.calls == sessions_module.MAX_CONCURRENT_STARTS


def test_local_code_is_wrong_then_one_shot() -> None:
  store = SessionStore(
    local_token=LOCAL_CODE,
    local_target=TargetCapability("http://target", OLD_TOKEN),
    control=None,
    instance_id=None,
  )
  with pytest.raises(ProtocolError) as wrong:
    store.start("wrong-code", None)
  assert wrong.value.status == 401
  browser, session = store.start(LOCAL_CODE, None)
  assert store.get(browser) is session
  with pytest.raises(ProtocolError) as replay:
    store.start(LOCAL_CODE, None)
  assert replay.value.status == 401


def test_normal_boot_failure_atomically_resumes_session() -> None:
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
  calls = 0

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal calls
    calls += 1
    if request.url.path == "/recovery/exchange":
      return httpx.Response(200, json={
        "session_id": "session-1",
        "target_url": MANAGED_TARGET_URL,
        "target_token": OLD_TOKEN,
        "target_token_sha256": _target_token_sha256(OLD_TOKEN),
        "session_capability": "finish-" + "f" * 40,
        "expires_at": expiry,
      })
    if request.url.path == "/recovery/exchange/ack":
      assert request.headers["authorization"].startswith("Bearer finish-")
      return httpx.Response(200, json={
        "status": "acknowledged", "session_id": "session-1"
      })
    if request.url.path == "/recovery/finish":
      return httpx.Response(202, json={
        "finish_id": "finish_job-1",
        "session_id": "session-1",
        "status": "queued",
        "outcome": "recovered",
        "generation": 1,
        "status_url": "/recovery/finish/finish_job-1",
      })
    assert request.headers["authorization"].startswith("Bearer finish-")
    return httpx.Response(503, json={
      "finish_id": "finish_job-1",
      "error": {"code": "normal_boot_failed", "message": "boot failed"},
      "session_id": "session-1",
      "status": "resumed",
      "outcome": "recovered",
      "generation": 1,
      "status_url": "/recovery/finish/finish_job-1",
      "next_generation": 2,
      "target_url": MANAGED_TARGET_URL,
      "target_token": NEW_TOKEN,
      "target_token_sha256": _target_token_sha256(NEW_TOKEN),
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    target_validator=_validate_managed_target,
    transport=httpx.MockTransport(handler),
  )
  assert control._client._trust_env is False
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="mob_instance-1",
  )
  browser, session = store.start("launch-code", "mob_instance-1")
  original_target = session.target
  finish_capability = session.managed_exchange.session_capability
  started = store.begin_finish(browser, "recovered")
  assert started["status"] == "queued"
  stale_pending = session.finish_result
  assert stale_pending is not None
  assert session.finishing
  assert original_target.base_url == ""
  assert original_target.token == ""
  resumed = store.poll_finish(browser)
  assert resumed == {
    "status": "resumed", "outcome": "recovered", "generation": 2
  }
  assert store.get(browser) is session
  assert not session.finishing
  assert session.target.base_url == MANAGED_TARGET_URL
  assert session.target.token == NEW_TOKEN
  assert session.managed_exchange.session_capability == finish_capability
  stale = store._apply_finish_result(
    store._digest(browser), session, stale_pending
  )
  assert stale == {
    "status": "resumed", "outcome": "recovered", "generation": 2
  }
  assert session.target.token == NEW_TOKEN
  assert not session.finishing
  assert calls == 4


def test_expired_session_cannot_be_resurrected_by_fresh_finish_target() -> None:
  exchange = ExchangeResult(
    session_id="expired-finish",
    target=TargetCapability(MANAGED_TARGET_URL, OLD_TOKEN),
    session_capability="finish-" + "f" * 40,
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
  )
  session = RecoverySession(
    session_id=exchange.session_id,
    target=exchange.target,
    expires_at=exchange.expires_at,
    managed_exchange=exchange,
    finish_outcome="recovered",
    finish_result=FinishResult(
      finish_id="finish_expired-1",
      session_id=exchange.session_id,
      status="queued",
      outcome="recovered",
      generation=1,
      status_url="/recovery/finish/finish_expired-1",
    ),
  )
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=object(),
    instance_id="mob_instance-1",
  )
  browser = "expired-browser"
  digest = store._digest(browser)
  with store._lock:
    store._sessions[digest] = session
    store._schedule_expiry_locked()
  store.close()
  fresh_target = TargetCapability(MANAGED_TARGET_URL, NEW_TOKEN)
  resumed = FinishResult(
    finish_id="finish_expired-1",
    session_id=exchange.session_id,
    status="resumed",
    outcome="recovered",
    generation=1,
    status_url="/recovery/finish/finish_expired-1",
    next_generation=2,
    target=fresh_target,
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    error_code="normal_boot_failed",
    error_message="normal boot failed",
  )

  with pytest.raises(ProtocolError) as rejected:
    store._apply_finish_result(digest, session, resumed)
  assert rejected.value.code == "auth_expired"
  assert fresh_target.base_url == ""
  assert fresh_target.token == ""


def test_managed_exchange_body_and_code_replay() -> None:
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
  bodies: list[dict] = []

  def handler(request: httpx.Request) -> httpx.Response:
    bodies.append(__import__("json").loads(request.content))
    if request.url.path == "/recovery/exchange/ack":
      assert request.headers["authorization"].startswith("Bearer finish-")
      return httpx.Response(200, json={
        "status": "acknowledged", "session_id": "session-2"
      })
    return httpx.Response(200, json={
      "session_id": "session-2",
      "target_url": MANAGED_TARGET_URL,
      "target_token": OLD_TOKEN,
      "target_token_sha256": _target_token_sha256(OLD_TOKEN),
      "session_capability": "finish-" + "f" * 40,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-2",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    target_validator=_validate_managed_target,
    transport=httpx.MockTransport(handler),
  )
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="mob_instance-2",
  )
  store.start("managed-code", "mob_instance-2")
  assert bodies[0] == {
    "code": "managed-code",
    "instance_id": "mob_instance-2",
    "service_id": "recovery-service",
    "bootstrap_secret": "bootstrap-" + "b" * 32,
    "protocol_version": "mobius-recovery-worker/v1",
    "build_sha": "abc123",
  }
  assert bodies[1] == {"session_id": "session-2"}
  with pytest.raises(ProtocolError) as replay:
    store.start("managed-code", "mob_instance-2")
  assert replay.value.status == 401
  assert len(bodies) == 2


def test_control_response_is_stream_bounded() -> None:
  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    target_validator=_validate_managed_target,
    transport=httpx.MockTransport(
      lambda _request: httpx.Response(
        200,
        content=b"x" * (1024 * 1024 + 1),
      )
    ),
  )
  with pytest.raises(ProtocolError) as oversized:
    control.exchange("launch-code", "mob_instance-1")
  assert oversized.value.code == "control_response_too_large"


def test_exchange_retries_exact_request_after_committed_response_is_lost(
  monkeypatch,
) -> None:
  monkeypatch.setattr(control_module.time, "sleep", lambda _seconds: None)
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
  requests: list[bytes] = []

  def handler(request: httpx.Request) -> httpx.Response:
    requests.append(request.content)
    if len(requests) == 1:
      raise httpx.ReadTimeout("response lost after commit", request=request)
    return httpx.Response(200, json={
      "session_id": "durable-receipt",
      "target_url": MANAGED_TARGET_URL,
      "target_token": OLD_TOKEN,
      "target_token_sha256": _target_token_sha256(OLD_TOKEN),
      "session_capability": "finish-" + "f" * 40,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    target_validator=_validate_managed_target,
    transport=httpx.MockTransport(handler),
  )
  result = control.exchange("same-one-time-code", "mob_instance-1")
  assert result.session_id == "durable-receipt"
  assert len(requests) == 2
  assert requests[0] == requests[1]


def test_exchange_ack_retries_exact_request_after_response_loss(monkeypatch) -> None:
  monkeypatch.setattr(control_module.time, "sleep", lambda _seconds: None)
  requests: list[tuple[bytes, str]] = []

  def handler(request: httpx.Request) -> httpx.Response:
    requests.append((request.content, request.headers.get("authorization", "")))
    if len(requests) == 1:
      raise httpx.ReadError("ack response lost", request=request)
    return httpx.Response(200, json={
      "status": "acknowledged", "session_id": "session-ack"
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    target_validator=_validate_managed_target,
    transport=httpx.MockTransport(handler),
  )
  result = ExchangeResult(
    session_id="session-ack",
    target=TargetCapability(MANAGED_TARGET_URL, OLD_TOKEN),
    session_capability="finish-" + "f" * 40,
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
  )
  control.acknowledge(result)
  assert len(requests) == 2
  assert requests[0] == requests[1]
  assert requests[0][0] == b'{"session_id":"session-ack"}'


def test_finish_start_retries_exact_idempotent_request_after_response_loss(
  monkeypatch,
) -> None:
  monkeypatch.setattr(control_module.time, "sleep", lambda _seconds: None)
  requests: list[tuple[bytes, str]] = []

  def handler(request: httpx.Request) -> httpx.Response:
    requests.append((request.content, request.headers.get("authorization", "")))
    if len(requests) == 1:
      raise httpx.ReadTimeout("accepted finish response lost", request=request)
    return httpx.Response(202, json={
      "finish_id": "finish_retry-1",
      "session_id": "session-finish",
      "status": "queued",
      "outcome": "recovered",
      "generation": 1,
      "status_url": "/recovery/finish/finish_retry-1",
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    target_validator=_validate_managed_target,
    transport=httpx.MockTransport(handler),
  )
  exchange = ExchangeResult(
    session_id="session-finish",
    target=TargetCapability(MANAGED_TARGET_URL, OLD_TOKEN),
    session_capability="finish-" + "f" * 40,
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
  )
  result = control.finish(exchange, "recovered", 1)
  assert result.finish_id == "finish_retry-1"
  assert result.pending
  assert len(requests) == 2
  assert requests[0] == requests[1]
  assert requests[0][0] == (
    b'{"session_id":"session-finish","outcome":"recovered","generation":1}'
  )
