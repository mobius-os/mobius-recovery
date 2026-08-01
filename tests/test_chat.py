from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from recovery_worker import chat
from recovery_worker.broker import BrokerClient, TargetBroker
from recovery_worker.providers import ProviderAuth
from recovery_worker.protocol import TargetCapability
from recovery_worker.sessions import RecoverySession


TARGET_TOKEN = "target-secret-" + "x" * 40


def _dead_or_zombie(pid: int) -> bool:
  try:
    stat = open(f"/proc/{pid}/stat", encoding="ascii").read()
  except FileNotFoundError:
    return True
  return stat.rsplit(")", 1)[1].strip().split()[0] == "Z"


def test_turn_cleanup_kills_escaped_helper_without_revoking_broker(
  tmp_path, monkeypatch
) -> None:
  helpers: list[tuple[subprocess.Popen, int]] = []

  async def escaped_provider(_provider, _session, _provider_auth):
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
    helpers.append((helper, escaped_pid))
    yield {"type": "text", "content": "checked"}

  monkeypatch.setattr(chat, "_spawn", escaped_provider)

  def target(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
      "status": "ready",
      "protocol": "mobius-recovery-target/v1",
      "target": "mobius",
      "mode": "recovery",
    })

  socket_path = tmp_path / "target.sock"
  broker = TargetBroker(
    TargetCapability("http://target.internal", TARGET_TOKEN),
    transport=httpx.MockTransport(target),
    path=socket_path,
  )
  broker.start()
  session = RecoverySession(
    session_id="active-session",
    target=TargetCapability("http://target.internal", TARGET_TOKEN),
    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
  )
  provider_auth = ProviderAuth()
  session.provider_generation = provider_auth.active_generation()

  async def run_turn() -> list[dict]:
    return [
      event
      async for event in chat.stream_turn(
        "inspect target", "claude", session, provider_auth
      )
    ]

  try:
    events = asyncio.run(run_turn())
    assert events[-1] == {"type": "done"}
    helper, escaped_pid = helpers[0]
    helper.wait(timeout=3)
    deadline = time.monotonic() + 3
    while not _dead_or_zombie(escaped_pid) and time.monotonic() < deadline:
      time.sleep(0.02)
    assert _dead_or_zombie(escaped_pid)
    assert BrokerClient(socket_path).health()["status"] == "ready"
    assert not session.revoked
  finally:
    broker.stop()
    for helper, _escaped_pid in helpers:
      try:
        os.killpg(helper.pid, 9)
      except ProcessLookupError:
        pass
