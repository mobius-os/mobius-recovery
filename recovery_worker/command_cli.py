"""Human-readable client for the session-bound recovery command socket."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from .broker import BROKER_SOCKET, broker_request


def _decode(value: object) -> bytes:
  if not isinstance(value, str):
    raise ValueError("command output is malformed")
  return base64.b64decode(value, validate=True)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(
    prog="mobius-ssh",
    description="Run a command as root in the Mobius instance bound to this session.",
  )
  parser.add_argument("--cwd")
  parser.add_argument("--timeout", type=int, default=120)
  parser.add_argument("command", nargs=argparse.REMAINDER)
  args = parser.parse_args(argv)
  command = args.command
  if command[:1] == ["--"]:
    command = command[1:]
  if not command:
    parser.error("a command is required after --")
  stdin = sys.stdin.buffer.read(8 * 1024 * 1024 + 1) if not sys.stdin.isatty() else b""
  if len(stdin) > 8 * 1024 * 1024:
    parser.error("stdin exceeds 8 MiB")
  path = Path(os.environ.get("MOBIUS_RECOVERY_BROKER_SOCKET", str(BROKER_SOCKET)))
  response = broker_request({
    "operation": "exec",
    "args": {
      "argv": command,
      "cwd": args.cwd,
      "stdin_base64": base64.b64encode(stdin).decode("ascii") if stdin else None,
      "timeout_seconds": args.timeout,
    },
  }, path=path)
  if not response.get("ok"):
    error = response.get("error") or {}
    print(str(error.get("message") or "remote command failed"), file=sys.stderr)
    return 125
  result = response.get("result") or {}
  try:
    sys.stdout.buffer.write(_decode(result.get("stdout_base64")))
    sys.stderr.buffer.write(_decode(result.get("stderr_base64")))
    exit_code = result.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
      raise ValueError("exit code is malformed")
    return max(0, min(255, exit_code))
  except (ValueError, TypeError) as exc:
    print(f"mobius-ssh: {exc}", file=sys.stderr)
    return 125


if __name__ == "__main__":
  raise SystemExit(main())
