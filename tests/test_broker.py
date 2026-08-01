from __future__ import annotations

import base64
import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from recovery_worker.broker import BrokerClient, TargetBroker
from recovery_worker.chat import _environment
from recovery_worker.protocol import TargetCapability
from recovery_worker.protocol import MAX_FILE_BYTES
from recovery_worker.protocol import ProtocolError
from recovery_worker.providers import subprocess_env
from recovery_worker.sessions import RecoverySession
from recovery_worker.target_client import TargetClient, cli


TARGET_TOKEN = "target-secret-" + "x" * 40
BOOTSTRAP = "bootstrap-secret-" + "y" * 40


def test_broker_keeps_target_bearer_out_of_subprocess(tmp_path, monkeypatch) -> None:
  monkeypatch.setenv("MOBIUS_RECOVERY_TARGET_TOKEN", TARGET_TOKEN)
  monkeypatch.setenv("MOBIUS_RECOVERY_BOOTSTRAP_SECRET", BOOTSTRAP)
  monkeypatch.setenv("MOBIUS_RECOVERY_SESSION_CAPABILITY", "session-secret")
  monkeypatch.setenv("HTTPS_PROXY", "https://hostile-proxy.invalid")
  monkeypatch.setenv("HTTP_PROXY", "http://hostile-proxy.invalid")
  clean = subprocess_env()
  assert TARGET_TOKEN not in clean.values()
  assert BOOTSTRAP not in clean.values()
  assert not any(key.startswith("MOBIUS_RECOVERY_") for key in clean)
  assert "HTTPS_PROXY" not in clean
  assert "HTTP_PROXY" not in clean

  session = RecoverySession(
    session_id="s1",
    target=TargetCapability("http://target.internal", TARGET_TOKEN),
    expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
  )
  child = _environment(session, "claude")
  assert TARGET_TOKEN not in child.values()
  assert BOOTSTRAP not in child.values()
  assert "MOBIUS_RECOVERY_TARGET_TOKEN" not in child
  assert "MOBIUS_RECOVERY_TARGET_URL" not in child
  assert "MOBIUS_RECOVERY_BROKER_SOCKET" in child


def test_mobius_target_operations_work_through_fixed_broker(
  tmp_path, monkeypatch, capsys
) -> None:
  socket_path = tmp_path / "private" / "target.sock"

  def target(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == f"Bearer {TARGET_TOKEN}"
    if request.url.path == "/v1/health":
      return httpx.Response(200, json={
        "status": "ready",
        "protocol": "mobius-recovery-target/v1",
        "target": "mobius",
        "mode": "recovery",
      })
    if request.url.path == "/v1/exec":
      return httpx.Response(200, json={
        "exit_code": 0,
        "stdout_base64": base64.b64encode(b"remote\n").decode(),
        "stderr_base64": "",
        "truncated": False,
      })
    if request.url.path == "/v1/fs/read":
      return httpx.Response(200, json={
        "data_base64": base64.b64encode(b"contents").decode(), "eof": True
      })
    if request.url.path == "/v1/fs/write":
      body = json.loads(request.content)
      assert base64.b64decode(body["data_base64"]) == b"new"
      return httpx.Response(200, json={"written": 3})
    return httpx.Response(200, json={"entries": [{"name": "platform"}]})

  broker = TargetBroker(
    TargetCapability("http://target.internal", TARGET_TOKEN),
    transport=httpx.MockTransport(target),
    path=socket_path,
  )
  broker.start()
  try:
    assert socket_path.parent.stat().st_mode & 0o777 == 0o700
    assert socket_path.stat().st_mode & 0o777 == 0o600
    client = BrokerClient(socket_path)
    assert client.health()["status"] == "ready"
    assert base64.b64decode(client.exec(["true"])["stdout_base64"]) == b"remote\n"
    assert client.read("/data/file")[0] == b"contents"
    assert client.write("/data/file", b"new")["written"] == 3
    assert client.list("/data") == [{"name": "platform"}]
    monkeypatch.setenv("MOBIUS_RECOVERY_BROKER_SOCKET", str(socket_path))
    assert cli(["health"]) == 0
    assert "mobius-recovery-target/v1" in capsys.readouterr().out
  finally:
    broker.stop()


def test_exact_eight_mib_write_crosses_broker_and_target_client(tmp_path) -> None:
  socket_path = tmp_path / "private" / "target.sock"
  payload = b"x" * MAX_FILE_BYTES

  def target(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    decoded = base64.b64decode(body["data_base64"])
    assert len(decoded) == MAX_FILE_BYTES
    return httpx.Response(200, json={"bytes_written": len(decoded)})

  broker = TargetBroker(
    TargetCapability("http://target.internal", TARGET_TOKEN),
    transport=httpx.MockTransport(target),
    path=socket_path,
  )
  broker.start()
  try:
    result = BrokerClient(socket_path).write("/data/exact.bin", payload)
    assert result["bytes_written"] == MAX_FILE_BYTES
  finally:
    broker.stop()


@pytest.mark.parametrize(
  ("operation", "path"),
  [
    ("read", "/proc/1/mem"),
    ("read", "/data/../proc/1/environ"),
    ("read", "/sys/kernel"),
    ("list", "/dev"),
    ("read", "/run/secrets/token"),
    ("write", "/app/recovery_worker/app.py"),
    ("write", "/data//ambiguous"),
  ],
)
def test_broker_rejects_paths_outside_fixed_roots(
  tmp_path, operation, path
) -> None:
  calls = 0

  def target(_request: httpx.Request) -> httpx.Response:
    nonlocal calls
    calls += 1
    return httpx.Response(500)

  socket_path = tmp_path / "private" / "target.sock"
  broker = TargetBroker(
    TargetCapability("http://target.internal", TARGET_TOKEN),
    transport=httpx.MockTransport(target),
    path=socket_path,
  )
  broker.start()
  client = BrokerClient(socket_path)
  try:
    with pytest.raises(ProtocolError) as forbidden:
      if operation == "read":
        client.read(path)
      elif operation == "write":
        client.write(path, b"x")
      else:
        client.list(path)
    assert forbidden.value.code == "path_forbidden"
    assert forbidden.value.status == 403
    assert calls == 0
  finally:
    broker.stop()


def test_target_client_rejects_forbidden_path_before_http() -> None:
  calls = 0

  def target(_request: httpx.Request) -> httpx.Response:
    nonlocal calls
    calls += 1
    return httpx.Response(500)

  client = TargetClient(
    TargetCapability("http://target.internal", TARGET_TOKEN),
    transport=httpx.MockTransport(target),
  )
  try:
    with pytest.raises(ProtocolError) as forbidden:
      client.read("/proc/1/maps")
    assert forbidden.value.code == "path_forbidden"
    assert calls == 0
  finally:
    client.close()


def test_broker_expiry_revokes_idle_connections_and_bearer(tmp_path) -> None:
  socket_path = tmp_path / "private" / "target.sock"
  capability = TargetCapability("http://target.internal", TARGET_TOKEN)
  expired = threading.Event()
  broker = TargetBroker(
    capability,
    transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    path=socket_path,
    expires_at=datetime.now(timezone.utc) + timedelta(milliseconds=150),
    on_expire=expired.set,
  )
  broker.start()
  idle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
  idle.settimeout(2)
  idle.connect(str(socket_path))
  try:
    assert expired.wait(2)
    deadline = time.monotonic() + 2
    closed = False
    while time.monotonic() < deadline:
      try:
        closed = idle.recv(1) == b""
      except (BrokenPipeError, ConnectionResetError, OSError):
        closed = True
      if closed:
        break
      time.sleep(0.01)
    assert closed
    assert capability.base_url == "http://target.internal"
    assert capability.token == TARGET_TOKEN
    assert broker._target._capability.base_url == ""
    assert broker._target._capability.token == ""
    with pytest.raises(ProtocolError) as unavailable:
      BrokerClient(socket_path).health()
    assert unavailable.value.code == "broker_unavailable"
  finally:
    idle.close()
    broker.stop()


def test_stopped_broker_can_be_reactivated_from_session_capability(tmp_path) -> None:
  capability = TargetCapability("http://target.internal", TARGET_TOKEN)

  def target(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
      "status": "ready",
      "protocol": "mobius-recovery-target/v1",
      "target": "mobius",
      "mode": "recovery",
    })

  transport = httpx.MockTransport(target)
  first = TargetBroker(
    capability, transport=transport, path=tmp_path / "first.sock"
  )
  first.start()
  assert BrokerClient(tmp_path / "first.sock").health()["status"] == "ready"
  first.stop()
  assert capability.token == TARGET_TOKEN

  second = TargetBroker(
    capability, transport=transport, path=tmp_path / "second.sock"
  )
  second.start()
  try:
    assert BrokerClient(tmp_path / "second.sock").health()["status"] == "ready"
  finally:
    second.stop()
