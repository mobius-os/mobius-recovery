from __future__ import annotations

import base64
import json
import stat
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import recovery_worker.app as app_module
from recovery_worker.broker import CommandBroker, broker_request
from recovery_worker.chat import (
  _claim,
  _release,
  claim_finish,
  finish_active,
  release_finish,
  turn_active,
)
from recovery_worker.app import create_app
from recovery_worker.config import Settings, WORKER_PROTOCOL_VERSION
from recovery_worker.control import ControlClient, ExchangeResult
from recovery_worker.protocol import ProtocolError
from recovery_worker.sessions import COOKIE_NAME, SessionStore


ORIGIN = "https://mobius.example"
CAPABILITY = "session-" + "x" * 48


def settings(**changes) -> Settings:
  values = {
    "port": 8000,
    "build_sha": "deadbeef",
    "service_id": "svc_worker",
    "secure_cookie": True,
    "control_plane_url": ORIGIN,
    "instance_id": "mob_instance-1",
    "bootstrap_secret": "b" * 48,
  }
  values.update(changes)
  return Settings(**values)


def exchange_payload() -> dict:
  now = datetime.now(timezone.utc)
  return {
    "session_id": "rec_session",
    "launcher_url": ORIGIN,
    "session_capability": CAPABILITY,
    "expires_at": (now + timedelta(minutes=30)).isoformat(),
    "idle_expires_at": (now + timedelta(minutes=20)).isoformat(),
    "idle_timeout_seconds": 20 * 60,
  }


def exchange_result() -> ExchangeResult:
  now = datetime.now(timezone.utc)
  return ExchangeResult(
    "rec_session",
    CAPABILITY,
    now + timedelta(minutes=30),
    now + timedelta(minutes=20),
    20 * 60,
  )


def test_configuration_is_managed_only() -> None:
  settings().validate()
  with pytest.raises(RuntimeError):
    settings(control_plane_url=None).validate()
  with pytest.raises(RuntimeError):
    settings(control_plane_url="http://mobius.example").validate()
  with pytest.raises(TypeError):
    Settings(**{**settings().__dict__, "local_token": "legacy"})


def test_exchange_returns_only_launcher_capability_and_pins_origin() -> None:
  requests = []

  def transport(request: httpx.Request) -> httpx.Response:
    requests.append(request)
    return httpx.Response(200, json=exchange_payload())

  client = ControlClient(settings(), transport=httpx.MockTransport(transport))
  result = client.exchange("one-time", "mob_instance-1")
  body = json.loads(requests[0].content)
  assert requests[0].url.path == "/recovery/exchange"
  assert body["protocol_version"] == WORKER_PROTOCOL_VERSION
  assert "target_url" not in body and "target_token" not in body
  assert result.session_capability == CAPABILITY
  result.clear()
  assert result.session_capability == ""

  wrong = exchange_payload()
  wrong["launcher_url"] = "https://attacker.example"
  client = ControlClient(
    settings(), transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=wrong))
  )
  with pytest.raises(ProtocolError, match="origin"):
    client.exchange("one-time", "mob_instance-1")


def test_command_broker_exposes_only_exec_and_hides_capability(tmp_path) -> None:
  calls = []

  class FakeControl:
    def exec(self, exchange, args):
      calls.append((exchange, args))
      return {
        "stdout_base64": base64.b64encode(b"0\n").decode(),
        "stderr_base64": "",
        "exit_code": 0,
      }

  exchange = exchange_result()
  socket_path = tmp_path / "broker" / "command.sock"
  broker = CommandBroker(FakeControl(), exchange, path=socket_path)
  broker.start()
  try:
    result = broker_request({
      "operation": "exec",
      "args": {"argv": ["/usr/bin/id", "-u"], "timeout_seconds": 10},
    }, path=socket_path)
    assert result["ok"] is True
    assert calls[0][0] is exchange
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
    rejected = broker_request({"operation": "health", "args": {}}, path=socket_path)
    assert rejected["ok"] is False
    selected = broker_request({
      "operation": "exec",
      "args": {"argv": ["true"], "target": "another-instance"},
    }, path=socket_path)
    assert selected["ok"] is False
  finally:
    broker.stop()
  assert not socket_path.exists()


def test_session_code_is_single_use_and_finish_closes_before_control() -> None:
  events = []

  class FakeControl:
    def exchange(self, code, instance_id):
      events.append(("exchange", code, instance_id))
      return exchange_result()

    def acknowledge(self, exchange):
      events.append(("ack", exchange.session_id))

    def finish(self, exchange, outcome):
      events.append(("finish", exchange.session_id, outcome))
      return {"status": "finished", "outcome": outcome}

  store = SessionStore(
    control=FakeControl(),
    instance_id="mob_instance-1",
    on_finish_accepted=lambda session: events.append(("quiesce", session.session_id)),
  )
  token, _session = store.start("one-time", "mob_instance-1")
  result = store.begin_finish(token, "recovered")
  assert result["status"] == "finished"
  assert events[-2:] == [
    ("quiesce", "rec_session"),
    ("finish", "rec_session", "recovered"),
  ]
  assert store.get(token) is None
  with pytest.raises(ProtocolError):
    store.start("one-time", "mob_instance-1")


def test_finish_can_claim_and_stop_an_active_turn() -> None:
  assert _claim() is True
  try:
    assert turn_active() is True
    assert claim_finish() is True
    assert finish_active() is True
    assert claim_finish() is False
  finally:
    release_finish()
    _release()


def test_exec_relay_uses_capability_and_has_no_target_selector() -> None:
  seen = []

  def transport(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    return httpx.Response(200, json={
      "stdout_base64": "", "stderr_base64": "", "exit_code": 0,
      "idle_expires_at": exchange_payload()["idle_expires_at"],
      "expires_at": exchange_payload()["expires_at"],
    })

  client = ControlClient(settings(), transport=httpx.MockTransport(transport))
  exchange = exchange_result()
  client.exec(exchange, {"argv": ["true"]})
  request = seen[0]
  assert request.url.path == "/internal/recovery/exec"
  assert request.headers["authorization"] == f"Bearer {CAPABILITY}"
  assert json.loads(request.content) == {"argv": ["true"]}


def test_activity_renewal_is_capability_scoped_and_updates_deadlines() -> None:
  seen = []
  now = datetime.now(timezone.utc)
  next_idle = now + timedelta(minutes=20)
  absolute = now + timedelta(minutes=30)

  def transport(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    return httpx.Response(200, json={
      "session_id": "rec_session",
      "status": "active",
      "idle_expires_at": next_idle.isoformat(),
      "expires_at": absolute.isoformat(),
      "idle_timeout_seconds": 20 * 60,
    })

  client = ControlClient(settings(), transport=httpx.MockTransport(transport))
  exchange = exchange_result()
  client.activity(exchange)

  assert seen[0].url.path == "/recovery/activity"
  assert seen[0].headers["authorization"] == f"Bearer {CAPABILITY}"
  assert json.loads(seen[0].content) == {"session_id": "rec_session"}
  assert exchange.idle_expires_at == next_idle
  assert exchange.expires_at == absolute


def test_control_rejects_an_idle_deadline_past_the_absolute_cap() -> None:
  payload = exchange_payload()
  payload["idle_expires_at"] = (
    datetime.fromisoformat(payload["expires_at"]) + timedelta(seconds=1)
  ).isoformat()
  client = ControlClient(
    settings(),
    transport=httpx.MockTransport(
      lambda _request: httpx.Response(200, json=payload)
    ),
  )
  with pytest.raises(ProtocolError, match="deadline"):
    client.exchange("one-time", "mob_instance-1")


def test_failed_post_exchange_probe_keeps_a_closable_browser_session(
  tmp_path, monkeypatch,
) -> None:
  paths = []

  def transport(request: httpx.Request) -> httpx.Response:
    paths.append(request.url.path)
    if request.url.path == "/recovery/exchange":
      return httpx.Response(200, json=exchange_payload())
    if request.url.path == "/recovery/exchange/ack":
      return httpx.Response(200, json={
        "status": "acknowledged",
        "idle_expires_at": exchange_payload()["idle_expires_at"],
        "expires_at": exchange_payload()["expires_at"],
      })
    if request.url.path == "/internal/recovery/exec":
      return httpx.Response(502, json={
        "error": {"message": "Railway SSH is temporarily unavailable"},
      })
    if request.url.path == "/recovery/finish":
      return httpx.Response(200, json={
        "status": "finished", "outcome": "cancelled",
      })
    raise AssertionError(request.url.path)

  monkeypatch.setattr(app_module, "harden_process", lambda: None)
  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(transport),
    broker_path=tmp_path / "broker" / "command.sock",
    workspace_root=tmp_path / "workspaces",
  )
  with TestClient(app, base_url="https://worker.example") as client:
    started = client.post(
      "/session/start",
      data={"code": "one-time", "instance_id": "mob_instance-1"},
      headers={"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
    )
    assert started.status_code == 200
    assert "Railway SSH is temporarily unavailable" in started.text
    assert COOKIE_NAME in client.cookies

    blocked = client.get("/api/providers")
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "target_unavailable"

    finished = client.post(
      "/api/finish",
      json={"outcome": "cancelled"},
      headers={
        "Origin": "https://worker.example",
        "Sec-Fetch-Site": "same-origin",
      },
    )
    assert finished.status_code == 200
    assert finished.json() == {"status": "finished", "outcome": "cancelled"}

  assert paths[-1] == "/recovery/finish"


def test_unexpected_post_exchange_failure_keeps_an_authenticated_page(
  tmp_path, monkeypatch,
) -> None:
  def fail_activate(_session) -> None:
    raise RuntimeError("internal detail")

  def transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/recovery/exchange":
      return httpx.Response(200, json=exchange_payload())
    if request.url.path == "/recovery/exchange/ack":
      return httpx.Response(200, json={
        "status": "acknowledged",
        "idle_expires_at": exchange_payload()["idle_expires_at"],
        "expires_at": exchange_payload()["expires_at"],
      })
    raise AssertionError(request.url.path)

  monkeypatch.setattr(app_module, "harden_process", lambda: None)
  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(transport),
    broker_path=tmp_path / "broker" / "command.sock",
    workspace_root=tmp_path / "workspaces",
  )
  monkeypatch.setattr(app.state.runtime, "activate", fail_activate)
  with TestClient(app, base_url="https://worker.example") as client:
    started = client.post(
      "/session/start",
      data={"code": "one-time", "instance_id": "mob_instance-1"},
      headers={"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
    )

  assert started.status_code == 200
  assert COOKIE_NAME in started.cookies
  assert "could not prepare the target connection" in started.text
  assert "internal detail" not in started.text
