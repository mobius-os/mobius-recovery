from __future__ import annotations

import shutil
import subprocess

import pytest

from recovery_worker.pages import _SCRIPT


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
  assert "error.status=r.status" in _SCRIPT
  assert "error.code=data.error?.code" in _SCRIPT
  assert "if(error?.status===401){location.replace('/')" in _SCRIPT
  assert (
    "api('/api/turn')}catch(error){redirectLost(error)}"
    in _SCRIPT
  )
  assert "catch(e){if(redirectLost(e))return;" in _SCRIPT
