"""One-use binding between control-plane preflight and managed capabilities."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable
from urllib.parse import urlparse

from .protocol import ProtocolError, TargetCapability


PREFLIGHT_BINDING_TTL_SECONDS = 15 * 60
_RAILWAY_SERVICE_HOST = re.compile(
  r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.railway\.internal\Z"
)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def managed_target_url(value: object) -> str:
  """Returns the canonical Railway-private target URL or rejects it."""
  if not isinstance(value, str):
    raise ProtocolError("invalid_target", "Managed target URL is invalid.", 400)
  parsed = urlparse(value)
  try:
    port = parsed.port
  except ValueError as exc:
    raise ProtocolError("invalid_target", "Managed target URL is invalid.", 400) from exc
  hostname = parsed.hostname or ""
  canonical = f"http://{hostname}:18002"
  if (
    parsed.scheme != "http"
    or not _RAILWAY_SERVICE_HOST.fullmatch(hostname)
    or port != 18002
    or parsed.netloc != f"{hostname}:18002"
    or value != canonical
    or parsed.params
    or parsed.query
    or parsed.fragment
    or parsed.username
    or parsed.password
  ):
    raise ProtocolError("invalid_target", "Managed target URL is invalid.", 400)
  return canonical


class PreflightBindings:
  """Keeps only a keyed digest of the latest successful target preflight."""

  def __init__(
    self,
    *,
    clock: Callable[[], float] = time.monotonic,
  ) -> None:
    self._key = secrets.token_bytes(32)
    self._clock = clock
    self._binding: bytes | None = None
    self._expires_at = 0.0
    self._lock = threading.Lock()

  def _digest(self, capability: TargetCapability) -> bytes:
    target_url = managed_target_url(capability.base_url).encode("utf-8")
    target_token = capability.token.encode("utf-8")
    payload = (
      len(target_url).to_bytes(2, "big") + target_url
      + len(target_token).to_bytes(2, "big") + target_token
    )
    return hmac.digest(self._key, payload, "sha256")

  def record(self, capability: TargetCapability) -> None:
    binding = self._digest(capability)
    with self._lock:
      self._binding = binding
      self._expires_at = self._clock() + PREFLIGHT_BINDING_TTL_SECONDS

  def consume(
    self,
    capability: TargetCapability,
    advertised_token_sha256: object,
  ) -> None:
    if (
      not isinstance(advertised_token_sha256, str)
      or not _SHA256_HEX.fullmatch(advertised_token_sha256)
      or not hmac.compare_digest(
        hashlib.sha256(capability.token.encode("utf-8")).hexdigest(),
        advertised_token_sha256,
      )
    ):
      capability.clear()
      raise ProtocolError(
        "invalid_exchange", "Managed target capability hash is invalid."
      )
    binding = self._digest(capability)
    with self._lock:
      matches = bool(
        self._binding is not None
        and self._expires_at > self._clock()
        and hmac.compare_digest(self._binding, binding)
      )
      self._binding = None
      self._expires_at = 0.0
    if not matches:
      capability.clear()
      raise ProtocolError(
        "unverified_target",
        "Managed target was not bound to a successful worker preflight.",
      )

  def clear(self) -> None:
    with self._lock:
      self._binding = None
      self._expires_at = 0.0
