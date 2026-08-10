from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest

from recovery_worker import providers
from recovery_worker.providers import ProviderAuth
from recovery_worker.protocol import ProtocolError


class _Response:
  headers = {"content-length": "256"}

  def __enter__(self):
    return self

  def __exit__(self, *_args):
    return False

  def read(self, _limit: int) -> bytes:
    return json.dumps({
      "access_token": "access",
      "refresh_token": "refresh",
      "expires_in": 3600,
      "scope": "user:inference",
      "account": {"email_address": "owner@example.com"},
    }).encode()


def test_provider_environment_excludes_worker_and_proxy_secrets(monkeypatch) -> None:
  monkeypatch.setenv("MOBIUS_RECOVERY_BOOTSTRAP_SECRET", "bootstrap-secret")
  monkeypatch.setenv("MOBIUS_RECOVERY_BOOTSTRAP_SECRET", "bootstrap-secret")
  monkeypatch.setenv("MOBIUS_RECOVERY_CONTROL_PLANE_URL", "https://control")
  monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid")
  monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
  child = providers.subprocess_env()
  assert child["PATH"] == "/usr/local/bin:/usr/bin"
  assert not any(
    key.startswith("MOBIUS_RECOVERY_") or "PROXY" in key
    for key in child
  )


def test_claude_pkce_uses_no_proxy_and_ephemeral_private_credentials(
  tmp_path, monkeypatch
) -> None:
  claude_dir = tmp_path / "providers" / "claude"
  monkeypatch.setattr(providers, "CLAUDE_DIR", claude_dir)
  seen: dict = {}

  class Opener:
    def open(self, request, timeout):
      seen["url"] = request.full_url
      seen["timeout"] = timeout
      return _Response()

  def build_opener(*handlers):
    seen["handlers"] = handlers
    return Opener()

  monkeypatch.setattr(providers.urllib.request, "build_opener", build_opener)
  auth = ProviderAuth()
  started = auth.claude_start()
  state = parse_qs(urlparse(started["auth_url"]).query)["state"][0]
  auth.claude_exchange(f"authorization-code#state={state}")

  assert seen["url"] == "https://platform.claude.com/v1/oauth/token"
  assert seen["timeout"] == 30
  assert len(seen["handlers"]) == 1
  assert seen["handlers"][0].proxies == {}
  credential = claude_dir / ".credentials.json"
  assert credential.stat().st_mode & 0o777 == 0o600
  assert json.loads(credential.read_text())["claudeAiOauth"]["accessToken"] == "access"
  assert auth.status()["claude"] is True
  auth.clear()
  assert not credential.exists()


def test_clear_terminates_provider_child_that_escaped_process_group() -> None:
  helper = subprocess.Popen(
    [
      sys.executable,
      "-c",
      (
        "import subprocess,time; "
        "child=subprocess.Popen(['sleep','60'],start_new_session=True); "
        "print(child.pid,flush=True); time.sleep(60)"
      ),
    ],
    stdout=subprocess.PIPE,
    text=True,
    start_new_session=True,
  )
  assert helper.stdout is not None
  escaped_pid = int(helper.stdout.readline().strip())
  try:
    assert escaped_pid in providers.descendant_pids()
    ProviderAuth().clear()
    helper.wait(timeout=3)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
      try:
        state = open(f"/proc/{escaped_pid}/stat", encoding="ascii").read().split()[2]
      except FileNotFoundError:
        break
      if state == "Z":
        break
      time.sleep(0.02)
    else:
      raise AssertionError("escaped provider helper survived cleanup")
  finally:
    try:
      os.killpg(helper.pid, 9)
    except ProcessLookupError:
      pass


def test_clear_prevents_inflight_claude_exchange_from_recreating_credentials(
  tmp_path, monkeypatch
) -> None:
  claude_dir = tmp_path / "providers" / "claude"
  monkeypatch.setattr(providers, "CLAUDE_DIR", claude_dir)
  entered = threading.Event()
  release = threading.Event()

  class Opener:
    def open(self, _request, _timeout=None, **_kwargs):
      entered.set()
      assert release.wait(3)
      return _Response()

  monkeypatch.setattr(
    providers.urllib.request,
    "build_opener",
    lambda *_handlers: Opener(),
  )
  auth = ProviderAuth()
  started = auth.claude_start()
  state = parse_qs(urlparse(started["auth_url"]).query)["state"][0]
  errors: list[Exception] = []

  def exchange() -> None:
    try:
      auth.claude_exchange(f"authorization-code#state={state}")
    except Exception as exc:
      errors.append(exc)

  worker = threading.Thread(target=exchange)
  worker.start()
  assert entered.wait(3)
  auth.clear()
  release.set()
  worker.join(3)
  assert not worker.is_alive()
  assert len(errors) == 1
  assert isinstance(errors[0], ProtocolError)
  assert errors[0].code == "auth_expired"
  assert not (claude_dir / ".credentials.json").exists()


def test_replaced_session_generation_cannot_launch_provider_process() -> None:
  auth = ProviderAuth()
  stale_generation = auth.active_generation()
  auth.clear()
  current_generation = auth.enable()

  assert current_generation != stale_generation
  with pytest.raises(ProtocolError) as rejected:
    with auth.launch_guard(stale_generation):
      raise AssertionError("stale generation entered launch guard")
  assert rejected.value.code == "auth_expired"

  with auth.launch_guard(current_generation):
    pass
  auth.clear()


def test_clear_waits_for_inflight_provider_process_launch() -> None:
  auth = ProviderAuth()
  generation = auth.active_generation()
  entered = threading.Event()
  release = threading.Event()
  cleared = threading.Event()

  def launch() -> None:
    with auth.launch_guard(generation):
      entered.set()
      assert release.wait(3)

  def clear() -> None:
    auth.clear()
    cleared.set()

  launcher = threading.Thread(target=launch)
  launcher.start()
  assert entered.wait(3)
  cleaner = threading.Thread(target=clear)
  cleaner.start()
  assert not cleared.wait(0.05)
  release.set()
  assert cleared.wait(3)
  launcher.join(3)
  cleaner.join(3)
  assert not launcher.is_alive()
  assert not cleaner.is_alive()
