from __future__ import annotations

import base64
import json

import httpx

from recovery_worker.broker import BrokerClient, TargetBroker
from recovery_worker.chat import _environment
from recovery_worker.protocol import TargetCapability
from recovery_worker.protocol import MAX_FILE_BYTES
from recovery_worker.providers import subprocess_env
from recovery_worker.sessions import RecoverySession
from recovery_worker.target_client import cli


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
