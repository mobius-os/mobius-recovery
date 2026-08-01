from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from recovery_worker import providers
from recovery_worker.providers import ProviderAuth


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
  monkeypatch.setenv("MOBIUS_RECOVERY_TARGET_TOKEN", "target-secret")
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
