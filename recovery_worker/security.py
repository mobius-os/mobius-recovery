"""Small process-level hardening independent of container settings."""

from __future__ import annotations

import ctypes
import os
import resource


def require_pid_one() -> None:
  """Rejects same-uid init/wrapper processes that would retain secrets."""
  if os.getpid() != 1:
    raise RuntimeError(
      "recovery worker must be container PID 1; remove init/wrapper processes"
    )


def harden_process() -> None:
  """Hides parent environment/memory from same-uid AI subprocesses."""
  os.umask(0o077)
  resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
  libc = ctypes.CDLL(None, use_errno=True)
  try:
    prctl = libc.prctl
  except AttributeError as exc:
    raise RuntimeError("PR_SET_DUMPABLE is unavailable") from exc
  # This is mandatory: provider CLIs intentionally share the container uid,
  # while only the parent process may hold target and control capabilities.
  # Dumpability gates /proc/<pid>/{environ,mem,fd} and ptrace-style access.
  if prctl(4, 0, 0, 0, 0) != 0:
    error = ctypes.get_errno()
    raise RuntimeError(
      f"PR_SET_DUMPABLE hardening failed with errno {error}"
    )
  # Prevent any later exec (including provider tools) from acquiring privilege
  # through an accidentally introduced setid bit or file capability.
  if prctl(38, 1, 0, 0, 0) != 0:
    error = ctypes.get_errno()
    raise RuntimeError(
      f"PR_SET_NO_NEW_PRIVS hardening failed with errno {error}"
    )
  # Provider CLIs may spawn helpers that create their own session. Acting as a
  # subreaper keeps those escaped descendants attached to this PID 1 so session
  # revocation can still terminate them.
  if prctl(36, 1, 0, 0, 0) != 0:
    error = ctypes.get_errno()
    raise RuntimeError(
      f"PR_SET_CHILD_SUBREAPER hardening failed with errno {error}"
    )
