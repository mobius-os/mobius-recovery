from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from recovery_worker.pages import _SCRIPT, recovery_page


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_inline_browser_script_parses() -> None:
  result = subprocess.run(
    ["node", "--check"],
    input=_SCRIPT,
    text=True,
    capture_output=True,
    check=False,
  )
  assert result.returncode == 0, result.stderr


def test_browser_heartbeat_redirects_a_lost_session() -> None:
  assert "error.status = response.status" in _SCRIPT
  assert "error.code = data.error?.code" in _SCRIPT
  assert "if (error?.status === 401)" in _SCRIPT
  assert "const data = await api('/api/turn')" in _SCRIPT
  assert "redirectLost(error)" in _SCRIPT


def test_browser_explains_agent_start_and_server_backed_expiry() -> None:
  assert "Recovery agent is starting" in _SCRIPT
  assert "first response can take about a minute" in _SCRIPT
  assert "api('/api/session/activity'" in _SCRIPT
  assert "Math.min(idleDeadline, absoluteDeadline)" in _SCRIPT


def test_recovery_page_has_one_end_action_and_an_explicit_idle_policy() -> None:
  now = datetime.now(timezone.utc)
  page = recovery_page(
    "nonce",
    protocol_version="mobius-recovery-worker/v2",
    build_sha="a" * 40,
    session_id="rec_test",
    idle_expires_at=now + timedelta(minutes=20),
    expires_at=now + timedelta(hours=1),
    idle_timeout_seconds=20 * 60,
  )
  assert "Ends automatically" in page
  assert "After 20 minutes without activity" in page
  assert page.count("End recovery") == 3
  assert "Cancel session" not in page
  assert "Secure remote access" in page
  assert "stops any active recovery agent" in page
  assert "const initialSession = null;" not in page


def test_end_recovery_remains_available_while_agent_is_working() -> None:
  assert "$('#finish').disabled = finishing" in _SCRIPT
  assert "$('#finish-mobile').disabled = finishing" in _SCRIPT
  assert "disabled || !targetReady || !providerReady" in _SCRIPT
  assert "Wait for the active recovery turn" not in _SCRIPT
