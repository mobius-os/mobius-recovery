"""Bounded client and CLI for the fixed recovery target capability."""

from __future__ import annotations

import argparse
import base64
import json
import os
import posixpath
import sys
import threading
from typing import Any

import httpx

from .protocol import (
  MAX_EXEC_STREAM_BYTES,
  MAX_FILE_BYTES,
  MAX_HTTP_RESPONSE_BYTES,
  MAX_LIST_ENTRIES,
  ProtocolError,
  TargetCapability,
  decode_bounded_base64,
  require_protocol,
)


# An 8 MiB decoded file expands to ~10.67 MiB in base64 JSON. The target and
# local broker cap the wire envelope at 12 MiB while independently enforcing
# the 8 MiB decoded-data limit.
MAX_REQUEST_BYTES = 12 * 1024 * 1024
READ_ROOTS = frozenset({"/data", "/app", "/tmp"})
WRITE_ROOTS = frozenset({"/data", "/tmp"})


def validate_fs_path(path: object, *, writable: bool) -> str:
  """Applies a lexical least-privilege boundary before target openat2 checks."""
  if not isinstance(path, str) or not path.startswith("/") or len(path) > 4096:
    raise ProtocolError("path_forbidden", "target path is outside recovery roots", 403)
  if "\x00" in path:
    raise ProtocolError("path_forbidden", "target path is outside recovery roots", 403)
  normalized = posixpath.normpath(path)
  if path not in {normalized, normalized + "/"}:
    raise ProtocolError("path_forbidden", "target path must be canonical", 403)
  root = "/" + normalized.split("/", 2)[1] if normalized != "/" else "/"
  allowed = WRITE_ROOTS if writable else READ_ROOTS
  if root not in allowed:
    raise ProtocolError("path_forbidden", "target path is outside recovery roots", 403)
  return normalized


class TargetClient:
  """Calls one target URL with one bearer capability.

  The base URL is constructor-only. None of the public operations accepts a
  host, service, instance, or token override, preventing the recovery agent
  from redirecting its privilege at another Mobius deployment.
  """

  def __init__(
    self,
    capability: TargetCapability,
    *,
    transport: httpx.BaseTransport | None = None,
  ) -> None:
    # The client owns a private copy. Revoking a broker must not mutate the
    # SessionStore's capability and make an intentional broker restart inert.
    self._capability = TargetCapability(capability.base_url, capability.token)
    self._revoked = threading.Event()
    self._client = httpx.Client(
      base_url=self._capability.base_url,
      headers={
        "Authorization": f"Bearer {self._capability.token}",
        "Accept": "application/json",
        "User-Agent": "mobius-recovery-worker/1",
      },
      timeout=httpx.Timeout(30.0, connect=10.0),
      follow_redirects=False,
      trust_env=False,
      transport=transport,
    )

  @classmethod
  def from_env(cls) -> "TargetClient":
    capability = TargetCapability.parse(
      os.environ.get("MOBIUS_RECOVERY_TARGET_URL"),
      os.environ.get("MOBIUS_RECOVERY_TARGET_TOKEN"),
    )
    return cls(capability)

  def close(self) -> None:
    self.revoke()

  def revoke(self) -> None:
    """Makes this client unusable and drops all local bearer references."""
    if self._revoked.is_set():
      return
    self._revoked.set()
    self._client.headers.pop("Authorization", None)
    self._client.close()
    self._capability.clear()

  def _request(
    self,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    timeout: httpx.Timeout | None = None,
  ) -> dict:
    if self._revoked.is_set():
      raise ProtocolError("auth_expired", "recovery session expired", 401)
    encoded = None
    if payload is not None:
      encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
      if len(encoded) > MAX_REQUEST_BYTES:
        raise ProtocolError("request_too_large", "request exceeds 12 MiB", 400)
    try:
      with self._client.stream(
        method,
        path,
        content=encoded,
        headers={"Content-Type": "application/json"} if encoded else None,
        timeout=timeout,
      ) as response:
        content_length = response.headers.get("content-length")
        if content_length:
          try:
            if int(content_length) > MAX_HTTP_RESPONSE_BYTES:
              raise ProtocolError(
                "response_too_large", "target response exceeds 16 MiB"
              )
          except ValueError:
            pass
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
          total += len(chunk)
          if total > MAX_HTTP_RESPONSE_BYTES:
            raise ProtocolError(
              "response_too_large", "target response exceeds 16 MiB"
            )
          chunks.append(chunk)
        raw = b"".join(chunks)
        try:
          data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
          raise ProtocolError(
            "invalid_response", "target returned malformed JSON"
          ) from exc
        if not isinstance(data, dict):
          raise ProtocolError("invalid_response", "target returned non-object JSON")
        if response.status_code >= 400:
          error = data.get("error")
          if isinstance(error, dict):
            code = str(error.get("code") or "target_error")[:80]
            message = str(error.get("message") or "target request failed")[:1000]
          else:
            code, message = "target_error", "target request failed"
          raise ProtocolError(code, message, response.status_code)
        if response.status_code >= 300:
          raise ProtocolError(
            "unexpected_status",
            f"target returned HTTP {response.status_code}",
          )
        if self._revoked.is_set():
          raise ProtocolError("auth_expired", "recovery session expired", 401)
        return data
    except ProtocolError:
      raise
    except httpx.TimeoutException as exc:
      raise ProtocolError("target_timeout", "target request timed out", 504) from exc
    except httpx.HTTPError as exc:
      raise ProtocolError("target_unreachable", "target is unreachable", 502) from exc

  def health(self) -> dict:
    payload = self._request(
      "GET",
      "/v1/health",
      timeout=httpx.Timeout(10.0, connect=5.0),
    )
    require_protocol(payload)
    if payload.get("target") != "mobius" or payload.get("mode") != "recovery":
      raise ProtocolError(
        "target_not_recovery",
        "Mobius target is not in recovery mode.",
        409,
      )
    return payload

  def exec(
    self,
    argv: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    stdin_base64: str | None = None,
    timeout_seconds: int = 120,
  ) -> dict:
    if not argv or not all(isinstance(arg, str) for arg in argv):
      raise ProtocolError("invalid_request", "argv must be a non-empty string list", 400)
    if stdin is not None and stdin_base64 is not None:
      raise ProtocolError("invalid_request", "choose stdin or stdin_base64", 400)
    if not 1 <= timeout_seconds <= 900:
      raise ProtocolError("invalid_request", "timeout must be 1..900 seconds", 400)
    payload: dict[str, Any] = {
      "argv": argv,
      "timeout_seconds": timeout_seconds,
    }
    if cwd:
      payload["cwd"] = cwd
    if env:
      payload["env"] = env
    if stdin is not None:
      payload["stdin"] = stdin
    if stdin_base64 is not None:
      payload["stdin_base64"] = stdin_base64
    result = self._request(
      "POST",
      "/v1/exec",
      payload,
      timeout=httpx.Timeout(timeout_seconds + 10.0, connect=10.0),
    )
    for key in ("stdout_base64", "stderr_base64"):
      decode_bounded_base64(result.get(key), MAX_EXEC_STREAM_BYTES)
    if not isinstance(result.get("exit_code"), int):
      raise ProtocolError("invalid_response", "target exit_code is missing")
    return result

  def read(self, path: str, *, offset: int = 0, limit: int = MAX_FILE_BYTES) -> tuple[bytes, bool]:
    if not 0 <= offset or not 1 <= limit <= MAX_FILE_BYTES:
      raise ProtocolError("invalid_request", "invalid read range", 400)
    path = validate_fs_path(path, writable=False)
    result = self._request(
      "POST",
      "/v1/fs/read",
      {"path": path, "offset": offset, "limit": limit},
      timeout=httpx.Timeout(30.0, connect=10.0),
    )
    data = decode_bounded_base64(result.get("data_base64"), limit)
    return data, bool(result.get("eof", False))

  def write(
    self,
    path: str,
    data: bytes,
    *,
    mode: int | None = None,
    atomic: bool = True,
  ) -> dict:
    if len(data) > MAX_FILE_BYTES:
      raise ProtocolError("request_too_large", "write exceeds 8 MiB", 400)
    path = validate_fs_path(path, writable=True)
    payload: dict[str, Any] = {
      "path": path,
      "data_base64": base64.b64encode(data).decode("ascii"),
      "atomic": atomic,
    }
    if mode is not None:
      if not 0 <= mode <= 0o7777:
        raise ProtocolError("invalid_request", "invalid file mode", 400)
      payload["mode"] = mode
    return self._request(
      "POST",
      "/v1/fs/write",
      payload,
      timeout=httpx.Timeout(30.0, connect=10.0),
    )

  def list(self, path: str) -> list[dict]:
    path = validate_fs_path(path, writable=False)
    result = self._request(
      "POST",
      "/v1/fs/list",
      {"path": path},
      timeout=httpx.Timeout(30.0, connect=10.0),
    )
    entries = result.get("entries")
    if not isinstance(entries, list):
      raise ProtocolError("invalid_response", "target entries are missing")
    if len(entries) > MAX_LIST_ENTRIES:
      raise ProtocolError("response_too_large", "target returned too many entries")
    if not all(isinstance(entry, dict) for entry in entries):
      raise ProtocolError("invalid_response", "target entries are malformed")
    return entries


def _parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="mobius-target",
    description="Operate on the single Mobius target bound to this session.",
  )
  sub = parser.add_subparsers(dest="command", required=True)
  sub.add_parser("health")

  run = sub.add_parser("exec")
  run.add_argument("--cwd")
  run.add_argument("--timeout", type=int, default=120)
  run.add_argument("argv", nargs=argparse.REMAINDER)

  read = sub.add_parser("read")
  read.add_argument("path")
  read.add_argument("--offset", type=int, default=0)
  read.add_argument("--limit", type=int, default=MAX_FILE_BYTES)

  write = sub.add_parser("write")
  write.add_argument("path")
  write.add_argument("--mode", type=lambda value: int(value, 8))
  write.add_argument("--no-atomic", action="store_true")

  listing = sub.add_parser("list")
  listing.add_argument("path")
  return parser


def cli(argv: list[str] | None = None) -> int:
  args = _parser().parse_args(argv)
  # The AI subprocess receives only a Unix socket path. The parent worker's
  # broker owns the remote bearer and fixed target URL; neither secret is in
  # this process environment or request schema.
  from .broker import BrokerClient

  client = BrokerClient.from_env()
  try:
    if args.command == "health":
      print(json.dumps(client.health(), indent=2, sort_keys=True))
      return 0
    if args.command == "exec":
      remote_argv = args.argv
      if remote_argv and remote_argv[0] == "--":
        remote_argv = remote_argv[1:]
      result = client.exec(remote_argv, cwd=args.cwd, timeout_seconds=args.timeout)
      sys.stdout.buffer.write(decode_bounded_base64(
        result.get("stdout_base64"), MAX_EXEC_STREAM_BYTES
      ))
      sys.stderr.buffer.write(decode_bounded_base64(
        result.get("stderr_base64"), MAX_EXEC_STREAM_BYTES
      ))
      return max(0, min(255, result["exit_code"]))
    if args.command == "read":
      data, _ = client.read(args.path, offset=args.offset, limit=args.limit)
      sys.stdout.buffer.write(data)
      return 0
    if args.command == "write":
      data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
      if len(data) > MAX_FILE_BYTES:
        raise ProtocolError("request_too_large", "stdin exceeds 8 MiB", 400)
      result = client.write(
        args.path, data, mode=args.mode, atomic=not args.no_atomic
      )
      print(json.dumps(result, sort_keys=True))
      return 0
    if args.command == "list":
      print(json.dumps(client.list(args.path), indent=2, sort_keys=True))
      return 0
  except ProtocolError as exc:
    print(f"mobius-target: {exc.code}: {exc.message}", file=sys.stderr)
    return 70
  finally:
    client.close()
  return 64


if __name__ == "__main__":
  raise SystemExit(cli())
