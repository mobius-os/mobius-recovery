from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from recovery_worker.app import create_app
from recovery_worker.chat import _claim, finish_active, release_finish
from recovery_worker.config import Settings
from recovery_worker.control import ControlClient, ExchangeResult, FinishResult
from recovery_worker.protocol import ProtocolError, TargetCapability
from recovery_worker.sessions import COOKIE_NAME, SessionStore


OLD_TOKEN = "old-target-" + "o" * 40
NEW_TOKEN = "new-target-" + "n" * 40
POISON_TOKEN = "poison-target-" + "p" * 40
MANAGED_URL = "http://mobius.railway.internal:18002"


def _expiry(minutes: int = 20) -> datetime:
  return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _exchange(session_id: str = "generation-session") -> ExchangeResult:
  return ExchangeResult(
    session_id=session_id,
    target=TargetCapability(MANAGED_URL, OLD_TOKEN),
    session_capability="finish-" + "f" * 40,
    expires_at=_expiry(),
  )


def _finish_result(
  *,
  finish_id: str,
  session_id: str,
  status: str,
  generation: int,
  target: TargetCapability | None = None,
  next_generation: int | None = None,
) -> FinishResult:
  return FinishResult(
    finish_id=finish_id,
    session_id=session_id,
    status=status,
    outcome="recovered",
    generation=generation,
    status_url=f"/recovery/finish/{finish_id}",
    target=target,
    expires_at=_expiry() if target is not None else None,
    next_generation=next_generation,
    error_code="normal_boot_failed" if status == "resumed" else None,
    error_message="normal boot failed" if status == "resumed" else None,
  )


def test_two_finish_generations_ignore_late_old_response_and_finish() -> None:
  exchange = _exchange()
  finish_calls: list[int] = []
  resume_observations: list[tuple[int, str]] = []
  released: list[bool] = []

  class Control:
    def exchange(self, _code, _instance_id):
      return exchange

    def acknowledge(self, _exchange):
      return None

    def finish(self, current, outcome, generation):
      assert current is exchange
      assert outcome == "recovered"
      finish_calls.append(generation)
      return _finish_result(
        finish_id=f"finish_generation_{generation}",
        session_id=exchange.session_id,
        status="queued",
        generation=generation,
      )

    def poll_finish(self, current, pending):
      assert current is exchange
      if pending.generation == 1:
        return _finish_result(
          finish_id=pending.finish_id,
          session_id=exchange.session_id,
          status="resumed",
          generation=1,
          target=TargetCapability(MANAGED_URL, NEW_TOKEN),
          next_generation=2,
        )
      assert pending.generation == 2
      return _finish_result(
        finish_id=pending.finish_id,
        session_id=exchange.session_id,
        status="finished",
        generation=2,
      )

  def resumed(session) -> None:
    # The new capability and generation must be installed together before any
    # target-owning runtime is restarted.
    resume_observations.append((session.finish_generation, session.target.token))

  store = SessionStore(
    local_token=None,
    local_target=None,
    control=Control(),
    instance_id="mob_instance-1",
    on_resume=resumed,
    on_finish_released=lambda: released.append(True),
  )
  browser, session = store.start("generation-code", "mob_instance-1")

  first = store.begin_finish(browser, "recovered")
  assert first == {
    "status": "queued",
    "outcome": "recovered",
    "generation": 1,
    "finish_id": "finish_generation_1",
  }
  assert session.target.token == ""

  resumed_payload = store.poll_finish(browser)
  assert resumed_payload == {
    "status": "resumed", "outcome": "recovered", "generation": 2
  }
  assert resume_observations == [(2, NEW_TOKEN)]
  assert released == [True]
  assert not session.finishing
  assert store.poll_finish(browser) == {
    "status": "resumed", "outcome": "recovered", "generation": 2
  }

  # A delayed duplicate browser request that began during generation 1 may
  # report the resume, but it must never initiate generation 2.
  late_first = store.begin_finish(
    browser, "recovered", expected_generation=1
  )
  assert late_first == {
    "status": "resumed", "outcome": "recovered", "generation": 2
  }
  assert finish_calls == [1]

  second = store.begin_finish(browser, "recovered")
  assert second["status"] == "queued"
  assert second["generation"] == 2
  current_second = session.finish_result
  assert current_second is not None and current_second.generation == 2

  stale_target = TargetCapability(MANAGED_URL, POISON_TOKEN)
  stale = _finish_result(
    finish_id="finish_generation_1",
    session_id=exchange.session_id,
    status="resumed",
    generation=1,
    target=stale_target,
    next_generation=2,
  )
  stale_payload = store._apply_finish_result(
    store._digest(browser), session, stale
  )
  assert stale_payload["status"] == "queued"
  assert stale_payload["generation"] == 2
  assert session.finish_result is current_second
  assert session.finish_generation == 2
  assert stale_target.base_url == ""
  assert stale_target.token == ""

  finished = store.poll_finish(browser)
  assert finished == {
    "status": "finished",
    "outcome": "recovered",
    "generation": 2,
    "finish_id": "finish_generation_2",
  }
  assert finish_calls == [1, 2]
  assert store.get(browser) is None


def test_definitive_finish_rejection_is_terminal_and_fail_closed() -> None:
  exchange = _exchange("rejected-session")
  calls = 0
  quiesced: list[bool] = []

  class RejectingControl:
    def exchange(self, _code, _instance_id):
      return exchange

    def finish(self, _exchange, _outcome, generation):
      nonlocal calls
      calls += 1
      assert generation == 1
      raise ProtocolError("finish_rejected", "controller rejected finish", 409)

  store = SessionStore(
    local_token=None,
    local_target=None,
    control=RejectingControl(),
    instance_id="mob_instance-1",
    on_finish_accepted=lambda _session: quiesced.append(True),
  )
  browser, session = store.start("reject-code", "mob_instance-1")

  failed = store.begin_finish(browser, "recovered")
  assert failed["status"] == "failed"
  assert failed["generation"] == 1
  assert failed["error"]["code"] == "finish_rejected"
  assert "remains closed" in failed["error"]["message"]
  assert session.finishing
  assert session.target.base_url == ""
  assert session.target.token == ""
  assert quiesced == [True]

  assert store.begin_finish(browser, "recovered") == failed
  assert store.poll_finish(browser) == failed
  assert calls == 1
  store.close()


def test_terminal_finish_result_decrypt_failure_has_failed_shape() -> None:
  exchange = _exchange("decrypt-failure-session")

  def no_target(_target, _digest) -> None:
    raise AssertionError("terminal failure disclosed target access")

  def handler(request: httpx.Request) -> httpx.Response:
    assert json.loads(request.content) == {
      "session_id": exchange.session_id,
      "outcome": "recovered",
      "generation": 1,
    }
    return httpx.Response(503, json={
      "finish_id": "finish_decrypt_failure",
      "session_id": exchange.session_id,
      "status": "failed",
      "outcome": "recovered",
      "generation": 1,
      "status_url": "/recovery/finish/finish_decrypt_failure",
      "error": {
        "code": "finish_result_unavailable",
        "message": "Finish result could not be decrypted.",
      },
    })

  control = ControlClient(
    _managed_settings(),
    target_validator=no_target,
    transport=httpx.MockTransport(handler),
  )
  try:
    result = control.finish(exchange, "recovered", 1)
  finally:
    control.close()
  assert result.status == "failed"
  assert result.generation == 1
  assert result.error_code == "finish_result_unavailable"
  assert result.target is None
  assert result.next_generation is None


def _managed_settings() -> Settings:
  return Settings(
    port=8000,
    build_sha="test-build",
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 40,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )


def test_stale_browser_generation_cannot_claim_or_quiesce_resumed_target(
  tmp_path,
) -> None:
  local_code = "local-code-" + "c" * 32
  settings = Settings(
    port=8000,
    build_sha="test-build",
    service_id="local",
    secure_cookie=False,
    control_plane_url=None,
    instance_id=None,
    bootstrap_secret=None,
    local_target_url="http://127.0.0.1:18002",
    local_target_token=NEW_TOKEN,
    local_token=local_code,
  )

  def target(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
      "status": "ready",
      "protocol": "mobius-recovery-target/v1",
      "target": "mobius",
      "mode": "recovery",
    })

  broker_path = tmp_path / "broker" / "target.sock"
  app = create_app(
    settings,
    target_transport=httpx.MockTransport(target),
    broker_path=broker_path,
  )
  release_finish()
  with TestClient(app) as client:
    started = client.post(
      "/session/start",
      data={"code": local_code},
      headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert started.status_code == 200
    browser = client.cookies.get(COOKIE_NAME)
    session = app.state.sessions.get(browser)
    assert session is not None
    with session._finish_lock:
      session.finish_generation = 2

    stale = client.post(
      "/api/finish",
      headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
      json={"outcome": "recovered", "generation": 1},
    )
    assert stale.status_code == 200
    assert stale.json() == {
      "status": "resumed", "outcome": "recovered", "generation": 2
    }
    assert not finish_active()
    assert not session.finishing
    assert session.target.token == NEW_TOKEN
    assert broker_path.exists()
    assert "const initialGeneration=2;" in client.get("/").text
  assert not finish_active()


def test_cancelled_http_finish_during_blocked_control_post_stays_closed(
  tmp_path,
) -> None:
  entered = threading.Event()
  release = threading.Event()
  finish_bodies: list[dict] = []
  expiry = _expiry().isoformat()

  def control(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/recovery/exchange":
      return httpx.Response(200, json={
        "session_id": "cancelled-http-session",
        "target_url": MANAGED_URL,
        "target_token": OLD_TOKEN,
        "target_token_sha256": hashlib.sha256(OLD_TOKEN.encode()).hexdigest(),
        "session_capability": "finish-" + "f" * 40,
        "expires_at": expiry,
      })
    if request.url.path == "/recovery/exchange/ack":
      return httpx.Response(200, json={
        "status": "acknowledged", "session_id": "cancelled-http-session"
      })
    assert request.url.path == "/recovery/finish"
    finish_bodies.append(json.loads(request.content))
    entered.set()
    assert release.wait(5)
    return httpx.Response(202, json={
      "finish_id": "finish_cancelled_http",
      "session_id": "cancelled-http-session",
      "status": "queued",
      "outcome": "recovered",
      "generation": 1,
      "status_url": "/recovery/finish/finish_cancelled_http",
    })

  app = create_app(
    _managed_settings(),
    control_transport=httpx.MockTransport(control),
    target_transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    broker_path=tmp_path / "broker" / "target.sock",
    workspace_root=tmp_path / "workspaces",
  )

  async def exercise() -> None:
    release_finish()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
      app.state.preflight_bindings.record(
        TargetCapability(MANAGED_URL, OLD_TOKEN)
      )
      browser, session = await asyncio.to_thread(
        app.state.sessions.start, "cancel-code", "mob_instance-1"
      )
      await asyncio.to_thread(app.state.runtime.activate, session)
      workspace = session.workspace
      assert workspace is not None and workspace.is_dir()

      async with httpx.AsyncClient(
        transport=transport, base_url="https://worker.test"
      ) as client:
        headers = {
          "Origin": "https://worker.test",
          "Sec-Fetch-Site": "same-origin",
          "Cookie": f"{COOKIE_NAME}={browser}",
        }
        pending = asyncio.create_task(client.post(
          "/api/finish", headers=headers,
          json={"outcome": "recovered", "generation": 1}
        ))
        assert await asyncio.to_thread(entered.wait, 3)
        pending.cancel()
        try:
          await pending
        except asyncio.CancelledError:
          pass
        else:
          raise AssertionError("blocked finish request was not cancelled")

        assert finish_active()
        assert session.finishing
        assert session.target.base_url == ""
        assert session.target.token == ""
        assert not (tmp_path / "broker" / "target.sock").exists()
        assert not workspace.exists()
        assert not _claim()

        frozen = await client.get("/api/providers", headers=headers)
        assert frozen.status_code == 409
        assert frozen.json()["error"]["code"] == "finish_in_progress"

        release.set()
        for _attempt in range(300):
          if session.finish_result is not None:
            break
          await asyncio.sleep(0.01)
        assert session.finish_result is not None
        assert session.finish_result.status == "queued"
        assert finish_active()
        assert finish_bodies == [{
          "session_id": "cancelled-http-session",
          "outcome": "recovered",
          "generation": 1,
        }]
    assert not finish_active()

  try:
    asyncio.run(exercise())
  finally:
    release.set()
    release_finish()
