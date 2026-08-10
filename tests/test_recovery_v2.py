from __future__ import annotations

import base64
import json
import stat
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from recovery_worker.broker import CommandBroker, broker_request
from recovery_worker.config import Settings, WORKER_PROTOCOL_VERSION
from recovery_worker.control import ControlClient, ExchangeResult
from recovery_worker.protocol import ProtocolError
from recovery_worker.sessions import SessionStore


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
  return {
    "session_id": "rec_session",
    "launcher_url": ORIGIN,
    "session_capability": CAPABILITY,
    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
  }


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

  exchange = ExchangeResult(
    "rec_session", CAPABILITY,
    datetime.now(timezone.utc) + timedelta(minutes=5),
  )
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
      return ExchangeResult(
        "rec_session", CAPABILITY,
        datetime.now(timezone.utc) + timedelta(minutes=5),
      )

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


def test_exec_relay_uses_capability_and_has_no_target_selector() -> None:
  seen = []

  def transport(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    return httpx.Response(200, json={
      "stdout_base64": "", "stderr_base64": "", "exit_code": 0,
    })

  client = ControlClient(settings(), transport=httpx.MockTransport(transport))
  exchange = ExchangeResult(
    "rec_session", CAPABILITY,
    datetime.now(timezone.utc) + timedelta(minutes=5),
  )
  client.exec(exchange, {"argv": ["true"]})
  request = seen[0]
  assert request.url.path == "/internal/recovery/exec"
  assert request.headers["authorization"] == f"Bearer {CAPABILITY}"
  assert json.loads(request.content) == {"argv": ["true"]}
