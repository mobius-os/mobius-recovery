from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from recovery_worker.config import TARGET_PROTOCOL_VERSION
from recovery_worker.protocol import ProtocolError, TargetCapability
from recovery_worker.target_client import TargetClient


TOKEN = "t" * 43


def test_target_client_connects_to_ipv6_only_endpoint() -> None:
  class Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6

  class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args) -> None:
      return None

    def do_GET(self) -> None:
      assert self.path == "/v1/health"
      assert self.headers["Authorization"] == f"Bearer {TOKEN}"
      body = json.dumps({
        "status": "ready",
        "protocol": TARGET_PROTOCOL_VERSION,
        "target": "mobius",
        "mode": "recovery",
      }).encode()
      self.send_response(200)
      self.send_header("Content-Type", "application/json")
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)

  try:
    server = Server(("::1", 0), Handler)
  except OSError as exc:
    pytest.skip(f"IPv6 loopback is unavailable: {exc}")
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  try:
    port = server.server_address[1]
    client = TargetClient(
      TargetCapability.parse(f"http://[::1]:{port}", TOKEN)
    )
    try:
      assert client.health()["protocol"] == TARGET_PROTOCOL_VERSION
    finally:
      client.close()
  finally:
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_core_health_contract_uses_protocol_key() -> None:
  def handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    return httpx.Response(200, json={
      "status": "ready",
      "protocol": "mobius-recovery-target/v1",
      "target": "mobius",
      "target_id": "instance-1",
      "mode": "recovery",
    })

  client = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(handler),
  )
  assert client.health()["protocol"] == TARGET_PROTOCOL_VERSION
  assert client._client._trust_env is False


def test_protocol_mismatch_fails_closed() -> None:
  client = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(
      lambda _request: httpx.Response(200, json={"protocol": "old/v0"})
    ),
  )
  with pytest.raises(ProtocolError, match="does not speak"):
    client.health()


def test_remote_error_schema_is_preserved_and_bounded() -> None:
  client = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(lambda _request: httpx.Response(403, json={
      "error": {"code": "bad_token", "message": "not authorized"}
    })),
  )
  with pytest.raises(ProtocolError) as caught:
    client.list("/data")
  assert caught.value.code == "bad_token"
  assert caught.value.status == 403


def test_exec_and_file_shapes_match_target_contract() -> None:
  seen: list[tuple[str, dict]] = []

  def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content) if request.content else {}
    seen.append((request.url.path, body))
    if request.url.path == "/v1/exec":
      return httpx.Response(200, json={
        "exit_code": 0,
        "stdout_base64": base64.b64encode(b"ok\n").decode(),
        "stderr_base64": "",
        "truncated": False,
      })
    if request.url.path == "/v1/fs/read":
      return httpx.Response(200, json={
        "data_base64": base64.b64encode(b"hello").decode(), "eof": True
      })
    if request.url.path == "/v1/fs/write":
      return httpx.Response(200, json={"written": 5})
    return httpx.Response(200, json={"entries": [{"name": "db"}]})

  client = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(handler),
  )
  assert client.exec(["/bin/bash", "-lc", "true"])["exit_code"] == 0
  assert client.read("/data/a")[0] == b"hello"
  assert client.write("/data/a", b"hello")["written"] == 5
  assert client.list("/data") == [{"name": "db"}]
  assert seen[0][1]["timeout_seconds"] == 120
  assert seen[2][1]["atomic"] is True


def test_exec_accepts_non_utf8_bytes_and_rejects_oversize_stream() -> None:
  binary = bytes([0, 255, 128, 10])

  def valid(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
      "exit_code": 0,
      "stdout_base64": base64.b64encode(binary).decode(),
      "stderr_base64": "",
      "truncated": False,
    })

  client = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(valid),
  )
  result = client.exec(["true"])
  assert base64.b64decode(result["stdout_base64"]) == binary

  too_large = base64.b64encode(b"x" * (4 * 1024 * 1024 + 1)).decode()
  oversized = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
      "exit_code": 0,
      "stdout_base64": too_large,
      "stderr_base64": "",
      "truncated": True,
    })),
  )
  with pytest.raises(ProtocolError) as caught:
    oversized.exec(["true"])
  assert caught.value.code == "response_too_large"


def test_health_is_short_and_long_exec_gets_requested_timeout_grace() -> None:
  timeouts: list[tuple[str, float]] = []

  def handler(request: httpx.Request) -> httpx.Response:
    timeouts.append((request.url.path, request.extensions["timeout"]["read"]))
    if request.url.path == "/v1/health":
      return httpx.Response(200, json={
        "protocol": TARGET_PROTOCOL_VERSION,
        "target": "mobius",
        "mode": "recovery",
      })
    return httpx.Response(200, json={
      "exit_code": 0,
      "stdout_base64": "",
      "stderr_base64": "",
      "truncated": False,
    })

  client = TargetClient(
    TargetCapability("http://target.internal", TOKEN),
    transport=httpx.MockTransport(handler),
  )
  client.health()
  client.exec(["sleep", "300"], timeout_seconds=300)
  assert timeouts == [("/v1/health", 10.0), ("/v1/exec", 310.0)]
