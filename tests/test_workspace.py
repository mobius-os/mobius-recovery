from __future__ import annotations

from recovery_worker import providers
from recovery_worker.chat import _environment
from recovery_worker.providers import ProviderAuth
from recovery_worker.sessions import RecoverySession
from recovery_worker.protocol import TargetCapability
from recovery_worker.workspace import SessionWorkspaces


def test_new_session_destroys_old_workspace_and_generic_home(tmp_path) -> None:
  workspaces = SessionWorkspaces(tmp_path / "workspaces")
  first = workspaces.create()
  poison = first / "recovery_worker" / "target_client.py"
  poison.parent.mkdir()
  poison.write_text("raise SystemExit(97)\n", encoding="utf-8")
  (first / "CLAUDE.md").write_text("poison memory\n", encoding="utf-8")

  second = workspaces.create()
  assert first != second
  assert not first.exists()
  assert list(second.iterdir()) == []

  session = RecoverySession(
    session_id="workspace-session",
    target=TargetCapability("http://target.internal", "t" * 40),
    expires_at=__import__("datetime").datetime.max.replace(
      tzinfo=__import__("datetime").timezone.utc
    ),
    workspace=second,
  )
  assert _environment(session, "claude")["HOME"] == str(second)


def test_provider_memory_root_is_removed_even_when_replaced_by_symlink(
  tmp_path, monkeypatch
) -> None:
  provider_root = tmp_path / "providers"
  persistent = tmp_path / "attacker-controlled"
  persistent.mkdir()
  (persistent / "poison-memory").write_text("old session", encoding="utf-8")
  provider_root.symlink_to(persistent, target_is_directory=True)
  monkeypatch.setattr(providers, "CLAUDE_DIR", provider_root / "claude")
  monkeypatch.setattr(providers, "CODEX_DIR", provider_root / "codex")

  ProviderAuth().clear()

  assert not provider_root.exists()
  assert not provider_root.is_symlink()
  assert (persistent / "poison-memory").read_text(encoding="utf-8") == "old session"
  (provider_root / "claude").mkdir(parents=True)
  assert not (provider_root / "poison-memory").exists()
