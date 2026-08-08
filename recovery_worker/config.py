"""Environment-only configuration for the immutable recovery worker."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


WORKER_PROTOCOL_VERSION = "mobius-recovery-worker/v1"
TARGET_PROTOCOL_VERSION = "mobius-recovery-target/v1"
STATE_DIR = Path(os.environ.get("MOBIUS_RECOVERY_STATE_DIR", "/state"))
BUILD_REVISION_PATH = Path(__file__).resolve().parents[1] / "BUILD_REVISION"
MANAGED_INSTANCE_ID = re.compile(r"mob_[A-Za-z0-9_-]{3,80}\Z")


def baked_build_revision() -> str:
  """Reads the root-owned identity baked by the image build."""
  try:
    value = BUILD_REVISION_PATH.read_text(encoding="ascii").strip()
  except OSError:
    value = "development"
  if not value or len(value) > 128 or any(
    char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    for char in value
  ):
    raise RuntimeError("baked BUILD_REVISION is invalid")
  return value


def _base_url(name: str) -> str | None:
  raw = os.environ.get(name, "").strip()
  if not raw:
    return None
  parsed = urlparse(raw)
  if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    raise RuntimeError(f"{name} must be an absolute http(s) URL")
  if parsed.username or parsed.password or parsed.fragment or parsed.query:
    raise RuntimeError(f"{name} must not contain credentials, query, or fragment")
  return raw.rstrip("/")


@dataclass(frozen=True)
class Settings:
  """Validated process configuration.

  Managed mode is selected by the presence of a control-plane URL. Local
  mode instead receives a one-time token and a target capability from the
  self-host launcher. No Railway, Docker, or host credential is accepted.
  """

  port: int
  build_sha: str
  service_id: str
  secure_cookie: bool
  control_plane_url: str | None
  instance_id: str | None
  bootstrap_secret: str | None
  local_target_url: str | None
  local_target_token: str | None
  local_token: str | None
  # Approach-2 transport flag (DRAFT, default off). When enabled in managed
  # mode, the exchange yields a LauncherTarget and repairs run over the
  # launcher's ssh RPC instead of the in-container target daemon. Off = the
  # legacy target-capability path, byte-for-byte unchanged.
  launcher_transport: bool = False

  @property
  def managed(self) -> bool:
    return self.control_plane_url is not None

  @classmethod
  def from_env(cls) -> "Settings":
    settings = cls(
      port=int(os.environ.get("PORT", "8000")),
      # Runtime environment cannot claim that a stale image is current.
      build_sha=baked_build_revision(),
      service_id=os.environ.get("MOBIUS_RECOVERY_SERVICE_ID", "local"),
      secure_cookie=os.environ.get(
        "MOBIUS_RECOVERY_SECURE_COOKIE", "1"
      ).lower() not in {"0", "false", "no"},
      control_plane_url=_base_url("MOBIUS_RECOVERY_CONTROL_PLANE_URL"),
      instance_id=os.environ.get("MOBIUS_RECOVERY_INSTANCE_ID", "").strip()
      or None,
      bootstrap_secret=os.environ.get(
        "MOBIUS_RECOVERY_BOOTSTRAP_SECRET", ""
      ).strip() or None,
      local_target_url=_base_url("MOBIUS_RECOVERY_TARGET_URL"),
      local_target_token=os.environ.get(
        "MOBIUS_RECOVERY_TARGET_TOKEN", ""
      ).strip() or None,
      local_token=os.environ.get(
        "MOBIUS_RECOVERY_LOCAL_TOKEN", ""
      ).strip() or None,
      launcher_transport=os.environ.get(
        "MOBIUS_RECOVERY_LAUNCHER_TRANSPORT", "0"
      ).lower() in {"1", "true", "yes"},
    )
    settings.validate()
    return settings

  def validate(self) -> None:
    if not 1 <= self.port <= 65535:
      raise RuntimeError("PORT must be between 1 and 65535")
    if self.managed:
      for name, value in (
        ("MOBIUS_RECOVERY_INSTANCE_ID", self.instance_id),
        ("MOBIUS_RECOVERY_SERVICE_ID", self.service_id),
        ("MOBIUS_RECOVERY_BOOTSTRAP_SECRET", self.bootstrap_secret),
      ):
        if not value:
          raise RuntimeError(f"{name} is required in managed mode")
      if self.local_token or self.local_target_url or self.local_target_token:
        raise RuntimeError("managed and local recovery settings cannot be mixed")
      if len(self.bootstrap_secret or "") < 32:
        raise RuntimeError(
          "MOBIUS_RECOVERY_BOOTSTRAP_SECRET must be at least 32 chars"
        )
      if not MANAGED_INSTANCE_ID.fullmatch(self.instance_id or ""):
        raise RuntimeError(
          "MOBIUS_RECOVERY_INSTANCE_ID must be a valid mob_ instance id"
        )
      parsed_control = urlparse(self.control_plane_url or "")
      try:
        control_port = parsed_control.port
      except ValueError as exc:
        raise RuntimeError(
          "MOBIUS_RECOVERY_CONTROL_PLANE_URL must be an HTTPS origin"
        ) from exc
      if (
        parsed_control.scheme != "https"
        or not parsed_control.hostname
        or parsed_control.path not in {"", "/"}
        or parsed_control.params
        or parsed_control.query
        or parsed_control.fragment
        or parsed_control.username
        or parsed_control.password
        or control_port is not None and not 1 <= control_port <= 65535
      ):
        raise RuntimeError(
          "MOBIUS_RECOVERY_CONTROL_PLANE_URL must be an HTTPS origin"
        )
      if not self.secure_cookie:
        raise RuntimeError(
          "MOBIUS_RECOVERY_SECURE_COOKIE must be enabled in managed mode"
        )
    else:
      for name, value in (
        ("MOBIUS_RECOVERY_TARGET_URL", self.local_target_url),
        ("MOBIUS_RECOVERY_TARGET_TOKEN", self.local_target_token),
        ("MOBIUS_RECOVERY_LOCAL_TOKEN", self.local_token),
      ):
        if not value:
          raise RuntimeError(f"{name} is required in local mode")
    if self.local_target_token and len(self.local_target_token) < 32:
      raise RuntimeError("MOBIUS_RECOVERY_TARGET_TOKEN must be at least 32 chars")
    if self.local_token and len(self.local_token) < 24:
      raise RuntimeError("MOBIUS_RECOVERY_LOCAL_TOKEN must be at least 24 chars")
