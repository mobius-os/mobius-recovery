"""Session-bound Unix socket that exposes only remote command execution."""

from __future__ import annotations

import json
import socket
import socketserver
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .config import STATE_DIR
from .control import ControlClient, ExchangeResult
from .protocol import ProtocolError


BROKER_SOCKET = STATE_DIR / "broker" / "command.sock"
MAX_BROKER_MESSAGE = 12 * 1024 * 1024


def _error(exc: ProtocolError) -> dict:
  return {
    "ok": False,
    "error": {"code": exc.code, "message": exc.message, "status": exc.status},
  }


class _UnixServer(socketserver.ThreadingUnixStreamServer):
  daemon_threads = True

  def __init__(
    self,
    path: str,
    control: ControlClient,
    exchange: ExchangeResult,
  ) -> None:
    self.control = control
    self.exchange = exchange
    self.revoked = threading.Event()
    self._connections: set[socket.socket] = set()
    self._connections_lock = threading.Lock()
    super().__init__(path, _BrokerHandler)

  def ensure_active(self) -> None:
    if self.revoked.is_set() or datetime.now(timezone.utc) >= self.exchange.expires_at:
      self.revoke()
      raise ProtocolError("auth_expired", "recovery session expired", 401)

  def get_request(self):
    connection, address = super().get_request()
    try:
      self.ensure_active()
      remaining = (self.exchange.expires_at - datetime.now(timezone.utc)).total_seconds()
      connection.settimeout(max(0.01, remaining))
      with self._connections_lock:
        if self.revoked.is_set():
          raise ProtocolError("auth_expired", "recovery session expired", 401)
        self._connections.add(connection)
      return connection, address
    except Exception:
      connection.close()
      raise

  def close_request(self, request) -> None:
    with self._connections_lock:
      self._connections.discard(request)
    super().close_request(request)

  def revoke(self) -> None:
    if self.revoked.is_set():
      return
    self.revoked.set()
    with self._connections_lock:
      connections = list(self._connections)
      self._connections.clear()
    for connection in connections:
      try:
        connection.shutdown(socket.SHUT_RDWR)
      except OSError:
        pass
      connection.close()


class _BrokerHandler(socketserver.StreamRequestHandler):
  def handle(self) -> None:
    server: _UnixServer = self.server  # type: ignore[assignment]
    try:
      server.ensure_active()
      raw = self.rfile.readline(MAX_BROKER_MESSAGE + 1)
      if len(raw) > MAX_BROKER_MESSAGE:
        raise ProtocolError("request_too_large", "broker request is too large", 413)
      request = json.loads(raw.decode("utf-8"))
      if not isinstance(request, dict) or request.get("operation") != "exec":
        raise ProtocolError("invalid_request", "only exec is supported", 400)
      args = request.get("args")
      if not isinstance(args, dict):
        raise ProtocolError("invalid_request", "exec arguments are required", 400)
      if not set(args).issubset({
        "argv", "cwd", "env", "stdin_base64", "timeout_seconds"
      }):
        raise ProtocolError("invalid_request", "unknown exec argument", 400)
      result = server.control.exec(server.exchange, args)
      server.ensure_active()
      response = {"ok": True, "result": result}
    except ProtocolError as exc:
      response = _error(exc)
    except (UnicodeDecodeError, json.JSONDecodeError):
      response = _error(ProtocolError("invalid_json", "broker request is invalid", 400))
    except Exception:
      response = _error(ProtocolError("broker_failure", "command broker failed", 502))
    try:
      self.wfile.write(
        json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
      )
    except OSError:
      pass


class CommandBroker:
  """Keeps the session capability in PID 1 and offers one fixed exec method."""

  def __init__(
    self,
    control: ControlClient,
    exchange: ExchangeResult,
    *,
    path: Path = BROKER_SOCKET,
    on_expire: Callable[[], None] | None = None,
  ) -> None:
    self._path = path
    self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    self._path.parent.chmod(0o700)
    self._path.unlink(missing_ok=True)
    self._server = _UnixServer(str(path), control, exchange)
    self._path.chmod(0o600)
    self._thread = threading.Thread(
      target=self._server.serve_forever, name="command-broker", daemon=True
    )
    self._on_expire = on_expire
    self._expires_at = exchange.expires_at
    self._expiry_wakeup = threading.Event()
    self._expiry_thread = threading.Thread(
      target=self._expire, name="command-broker-expiry", daemon=True
    )
    self._lock = threading.Lock()
    self._started = False
    self._stopped = False

  def start(self) -> None:
    with self._lock:
      if self._stopped:
        raise OSError("command broker already stopped")
      if self._started:
        return
      self._started = True
      self._thread.start()
      self._expiry_thread.start()

  def _expire(self) -> None:
    delay = max(0.0, (self._expires_at - datetime.now(timezone.utc)).total_seconds())
    if not self._expiry_wakeup.wait(delay):
      self.stop()
      if self._on_expire:
        self._on_expire()

  def stop(self) -> None:
    with self._lock:
      if self._stopped:
        return
      self._stopped = True
      started = self._started
      self._expiry_wakeup.set()
    self._server.revoke()
    if started:
      self._server.shutdown()
      self._thread.join(timeout=2)
    self._server.server_close()
    self._path.unlink(missing_ok=True)


def broker_request(request: dict, *, path: Path = BROKER_SOCKET) -> dict:
  encoded = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
  if len(encoded) > MAX_BROKER_MESSAGE:
    raise ProtocolError("request_too_large", "broker request is too large", 413)
  try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
      client.connect(str(path))
      client.sendall(encoded)
      response = bytearray()
      while not response.endswith(b"\n"):
        chunk = client.recv(65536)
        if not chunk:
          break
        response.extend(chunk)
        if len(response) > MAX_BROKER_MESSAGE:
          raise ProtocolError("response_too_large", "broker response is too large", 502)
  except OSError as exc:
    raise ProtocolError("broker_unavailable", "recovery command broker is unavailable", 502) from exc
  try:
    parsed = json.loads(response.decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise ProtocolError("invalid_response", "broker response is invalid", 502) from exc
  if not isinstance(parsed, dict):
    raise ProtocolError("invalid_response", "broker response is invalid", 502)
  return parsed
