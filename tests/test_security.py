from __future__ import annotations

import pytest

from recovery_worker import security


def test_worker_requires_pid_one(monkeypatch) -> None:
  monkeypatch.setattr(security.os, "getpid", lambda: 2)
  with pytest.raises(RuntimeError, match="must be container PID 1"):
    security.require_pid_one()


def test_dumpability_failure_is_fatal(monkeypatch) -> None:
  class Libc:
    @staticmethod
    def prctl(*_args):
      return -1

  monkeypatch.setattr(security.ctypes, "CDLL", lambda *_args, **_kwargs: Libc())
  monkeypatch.setattr(security.ctypes, "get_errno", lambda: 1)
  with pytest.raises(RuntimeError, match="PR_SET_DUMPABLE hardening failed"):
    security.harden_process()


def test_no_new_privileges_failure_is_fatal(monkeypatch) -> None:
  class Libc:
    calls = 0

    def prctl(self, *_args):
      self.calls += 1
      return 0 if self.calls == 1 else -1

  monkeypatch.setattr(security.ctypes, "CDLL", lambda *_args, **_kwargs: Libc())
  monkeypatch.setattr(security.ctypes, "get_errno", lambda: 1)
  with pytest.raises(RuntimeError, match="PR_SET_NO_NEW_PRIVS hardening failed"):
    security.harden_process()
