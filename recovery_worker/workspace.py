"""Session-scoped writable workspaces for hostile provider subprocesses."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
from pathlib import Path

from .config import STATE_DIR


WORKSPACES_DIR = STATE_DIR / "workspaces"


class SessionWorkspaces:
  """Creates unpredictable workspaces and destroys all prior project memory."""

  def __init__(self, root: Path = WORKSPACES_DIR) -> None:
    self._root = root
    self._lock = threading.Lock()

  @staticmethod
  def _remove(path: Path) -> None:
    try:
      info = path.lstat()
    except FileNotFoundError:
      return
    if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
      shutil.rmtree(path)
    else:
      path.unlink()

  def clear(self) -> None:
    with self._lock:
      self._remove(self._root)

  def create(self) -> Path:
    with self._lock:
      self._remove(self._root)
      self._root.mkdir(parents=True, mode=0o700)
      self._root.chmod(0o700)
      workspace = Path(tempfile.mkdtemp(prefix="session-", dir=self._root))
      workspace.chmod(0o700)
      return workspace

  def validate(self, workspace: Path | None) -> Path:
    if workspace is None:
      raise OSError("session workspace is unavailable")
    try:
      root_info = self._root.lstat()
      if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise OSError("session workspace root is invalid")
      root = self._root.resolve(strict=True)
      info = workspace.lstat()
      resolved = workspace.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
      raise OSError("session workspace is unavailable") from exc
    if (
      not stat.S_ISDIR(info.st_mode)
      or stat.S_ISLNK(info.st_mode)
      or resolved.parent != root
      or not os.access(resolved, os.R_OK | os.W_OK | os.X_OK)
    ):
      raise OSError("session workspace is invalid")
    return resolved
