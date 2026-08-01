from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading

import httpx
import pytest

from recovery_worker.config import Settings
from recovery_worker.control import ControlClient, ExchangeResult, RecoveryResumed
from recovery_worker.protocol import ProtocolError, TargetCapability
from recovery_worker import sessions as sessions_module
from recovery_worker.sessions import SessionStore


LOCAL_CODE = "local-code-" + "c" * 32
OLD_TOKEN = "old-target-" + "o" * 32
NEW_TOKEN = "new-target-" + "n" * 32


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
    instance_id="instance-1",
  )
  for attempt in range(sessions_module.START_ATTEMPT_BURST):
    with pytest.raises(ProtocolError) as rejected:
      store.start(f"invalid-code-{attempt}", "instance-1")
    assert rejected.value.status == 401

  with pytest.raises(ProtocolError) as limited:
    store.start("one-too-many", "instance-1")
  assert limited.value.status == 429
  assert limited.value.code == "rate_limited"
  assert control.calls == sessions_module.START_ATTEMPT_BURST
  assert store._starting_codes == set()
  assert store._used_codes == set()
  assert store._start_inflight == 0

  clock[0] += sessions_module.START_ATTEMPT_REFILL_SECONDS
  with pytest.raises(ProtocolError) as refilled:
    store.start("after-refill", "instance-1")
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
        target=TargetCapability("http://target.internal", OLD_TOKEN),
        session_capability="finish-" + "f" * 40,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
      )

  control = BlockingControl()
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="instance-1",
  )
  failures: list[Exception] = []

  def begin(code: str) -> None:
    try:
      store.start(code, "instance-1")
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
    store.start("third-code", "instance-1")
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
        "target_url": "http://old-target.internal",
        "target_token": OLD_TOKEN,
        "session_capability": "finish-" + "f" * 40,
        "expires_at": expiry,
      })
    assert request.headers["authorization"].startswith("Bearer finish-")
    return httpx.Response(503, json={
      "error": {"code": "normal_boot_failed", "message": "boot failed"},
      "session_id": "session-1",
      "target_url": "http://new-target.internal",
      "target_token": NEW_TOKEN,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=False,
    control_plane_url="https://mobius.you",
    instance_id="instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(settings, transport=httpx.MockTransport(handler))
  assert control._client._trust_env is False
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="instance-1",
  )
  browser, session = store.start("launch-code", "instance-1")
  finish_capability = session.managed_exchange.session_capability
  with pytest.raises(RecoveryResumed) as resumed:
    store.finish(browser, "recovered")
  assert resumed.value.code == "normal_boot_failed"
  assert store.get(browser) is session
  assert session.target.base_url == "http://new-target.internal"
  assert session.target.token == NEW_TOKEN
  assert session.managed_exchange.session_capability == finish_capability
  assert calls == 2


def test_managed_exchange_body_and_code_replay() -> None:
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
  bodies: list[dict] = []

  def handler(request: httpx.Request) -> httpx.Response:
    bodies.append(__import__("json").loads(request.content))
    return httpx.Response(200, json={
      "session_id": "session-2",
      "target_url": "http://target.internal",
      "target_token": OLD_TOKEN,
      "session_capability": "finish-" + "f" * 40,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=False,
    control_plane_url="https://mobius.you",
    instance_id="instance-2",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(settings, transport=httpx.MockTransport(handler))
  store = SessionStore(
    local_token=None,
    local_target=None,
    control=control,
    instance_id="instance-2",
  )
  store.start("managed-code", "instance-2")
  assert bodies == [{
    "code": "managed-code",
    "instance_id": "instance-2",
    "service_id": "recovery-service",
    "bootstrap_secret": "bootstrap-" + "b" * 32,
    "protocol_version": "mobius-recovery-worker/v1",
  }]
  with pytest.raises(ProtocolError) as replay:
    store.start("managed-code", "instance-2")
  assert replay.value.status == 401
  assert len(bodies) == 1


def test_control_response_is_stream_bounded() -> None:
  settings = Settings(
    port=8000,
    build_sha="abc123",
    service_id="recovery-service",
    secure_cookie=False,
    control_plane_url="https://mobius.you",
    instance_id="instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  control = ControlClient(
    settings,
    transport=httpx.MockTransport(
      lambda _request: httpx.Response(
        200,
        content=b"x" * (1024 * 1024 + 1),
      )
    ),
  )
  with pytest.raises(ProtocolError) as oversized:
    control.exchange("launch-code", "instance-1")
  assert oversized.value.code == "control_response_too_large"
