"""Session-bound Unix-socket broker that keeps target bearers out of AI."""

from __future__ import annotations

import base64
import json
import os
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any

from .config import STATE_DIR
from .protocol import MAX_FILE_BYTES, ProtocolError, TargetCapability
from .target_client import TargetClient


BROKER_SOCKET = STATE_DIR / "broker" / "target.sock"
MAX_BROKER_MESSAGE = 12 * 1024 * 1024


def _error(exc: ProtocolError) -> dict:
  return {
    "ok": False,
    "error": {"code": exc.code, "message": exc.message, "status": exc.status},
  }


class _UnixServer(socketserver.ThreadingUnixStreamServer):
  daemon_threads = True

  def __init__(self, path: str, target: TargetClient) -> None:
    self.target = target
    super().__init__(path, _BrokerHandler)


class _BrokerHandler(socketserver.StreamRequestHandler):
  def handle(self) -> None:
    raw = self.rfile.readline(MAX_BROKER_MESSAGE + 1)
    if len(raw) > MAX_BROKER_MESSAGE:
      response = _error(ProtocolError("request_too_large", "broker request is too large", 413))
    else:
      try:
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
          raise ProtocolError("invalid_request", "broker request must be an object", 400)
        response = {"ok": True, "result": self._dispatch(request)}
      except ProtocolError as exc:
        response = _error(exc)
      except (UnicodeDecodeError, json.JSONDecodeError):
        response = _error(ProtocolError("invalid_json", "broker request is invalid", 400))
      except Exception:
        response = _error(ProtocolError("broker_failure", "target broker failed", 502))
    encoded = json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
    self.wfile.write(encoded)

  def _dispatch(self, request: dict) -> Any:
    operation = request.get("operation")
    args = request.get("args", {})
    if not isinstance(args, dict):
      raise ProtocolError("invalid_request", "broker args must be an object", 400)
    target: TargetClient = self.server.target  # type: ignore[attr-defined]
    if operation == "health":
      return target.health()
    if operation == "exec":
      return target.exec(
        args.get("argv"),
        cwd=args.get("cwd"),
        env=args.get("env"),
        stdin=args.get("stdin"),
        stdin_base64=args.get("stdin_base64"),
        timeout_seconds=args.get("timeout_seconds", 120),
      )
    if operation == "read":
      data, eof = target.read(
        args.get("path"),
        offset=args.get("offset", 0),
        limit=args.get("limit", MAX_FILE_BYTES),
      )
      return {"data_base64": base64.b64encode(data).decode("ascii"), "eof": eof}
    if operation == "write":
      encoded = args.get("data_base64")
      if not isinstance(encoded, str):
        raise ProtocolError("invalid_request", "write data is missing", 400)
      try:
        data = base64.b64decode(encoded, validate=True)
      except ValueError as exc:
        raise ProtocolError("invalid_request", "write data is invalid", 400) from exc
      return target.write(
        args.get("path"),
        data,
        mode=args.get("mode"),
        atomic=args.get("atomic", True),
      )
    if operation == "list":
      return target.list(args.get("path"))
    raise ProtocolError("unknown_operation", "unknown target operation", 400)


class TargetBroker:
  """Owns a fixed TargetClient and exposes its operations on one Unix socket."""

  def __init__(
    self,
    capability: TargetCapability,
    *,
    transport=None,
    path: Path = BROKER_SOCKET,
  ) -> None:
    self._path = path
    self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    self._path.parent.chmod(0o700)
    try:
      self._path.unlink()
    except FileNotFoundError:
      pass
    self._target = TargetClient(capability, transport=transport)
    self._server = _UnixServer(str(self._path), self._target)
    self._path.chmod(0o600)
    self._thread = threading.Thread(
      target=self._server.serve_forever,
      name="target-broker",
      daemon=True,
    )

  def start(self) -> None:
    self._thread.start()

  def stop(self) -> None:
    self._server.shutdown()
    self._server.server_close()
    self._target.close()
    try:
      self._path.unlink()
    except FileNotFoundError:
      pass


class BrokerClient:
  """Unprivileged client whose schema has no remote URL or bearer field."""

  def __init__(self, path: Path) -> None:
    self._path = path

  @classmethod
  def from_env(cls) -> "BrokerClient":
    raw = os.environ.get("MOBIUS_RECOVERY_BROKER_SOCKET", "")
    if not raw:
      raise ProtocolError("broker_unavailable", "target broker socket is missing")
    return cls(Path(raw))

  def close(self) -> None:
    return None

  def _request(self, operation: str, args: dict | None = None) -> Any:
    payload = json.dumps(
      {"operation": operation, "args": args or {}}, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if len(payload) > MAX_BROKER_MESSAGE:
      raise ProtocolError("request_too_large", "broker request is too large", 413)
    try:
      with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(920)
        connection.connect(str(self._path))
        connection.sendall(payload)
        reader = connection.makefile("rb")
        raw = reader.readline(MAX_BROKER_MESSAGE + 1)
    except (OSError, TimeoutError) as exc:
      raise ProtocolError("broker_unavailable", "target broker is unavailable", 502) from exc
    if len(raw) > MAX_BROKER_MESSAGE:
      raise ProtocolError("response_too_large", "broker response is too large")
    try:
      response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
      raise ProtocolError("invalid_response", "broker response is invalid") from exc
    if not isinstance(response, dict):
      raise ProtocolError("invalid_response", "broker response is invalid")
    if not response.get("ok"):
      error = response.get("error") or {}
      raise ProtocolError(
        str(error.get("code") or "broker_error"),
        str(error.get("message") or "target broker failed"),
        int(error.get("status") or 502),
      )
    return response.get("result")

  def health(self) -> dict:
    result = self._request("health")
    if not isinstance(result, dict):
      raise ProtocolError("invalid_response", "broker health is invalid")
    return result

  def exec(self, argv: list[str], *, cwd=None, env=None, stdin=None,
           stdin_base64=None, timeout_seconds=120) -> dict:
    result = self._request("exec", {
      "argv": argv,
      "cwd": cwd,
      "env": env,
      "stdin": stdin,
      "stdin_base64": stdin_base64,
      "timeout_seconds": timeout_seconds,
    })
    if not isinstance(result, dict):
      raise ProtocolError("invalid_response", "broker exec result is invalid")
    return result

  def read(self, path: str, *, offset=0, limit=MAX_FILE_BYTES) -> tuple[bytes, bool]:
    result = self._request("read", {"path": path, "offset": offset, "limit": limit})
    if not isinstance(result, dict):
      raise ProtocolError("invalid_response", "broker read result is invalid")
    encoded = result.get("data_base64")
    if not isinstance(encoded, str):
      raise ProtocolError("invalid_response", "broker read data is invalid")
    try:
      data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
      raise ProtocolError("invalid_response", "broker read data is invalid") from exc
    return data, bool(result.get("eof"))

  def write(self, path: str, data: bytes, *, mode=None, atomic=True) -> dict:
    result = self._request("write", {
      "path": path,
      "data_base64": base64.b64encode(data).decode("ascii"),
      "mode": mode,
      "atomic": atomic,
    })
    if not isinstance(result, dict):
      raise ProtocolError("invalid_response", "broker write result is invalid")
    return result

  def list(self, path: str) -> list[dict]:
    result = self._request("list", {"path": path})
    if not isinstance(result, list):
      raise ProtocolError("invalid_response", "broker list result is invalid")
    return result
