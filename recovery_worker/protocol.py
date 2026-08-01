"""Shared value objects and validation for recovery protocol v1."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from .config import TARGET_PROTOCOL_VERSION


MAX_HTTP_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_EXEC_STREAM_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LIST_ENTRIES = 10_000


class ProtocolError(RuntimeError):
  """A bounded, user-safe remote protocol failure."""

  def __init__(self, code: str, message: str, status: int = 502) -> None:
    super().__init__(message)
    self.code = code
    self.message = message
    self.status = status


@dataclass
class TargetCapability:
  """A capability fixed to exactly one recovery target."""

  base_url: str
  token: str

  def clear(self) -> None:
    """Drops both parts of the bearer capability from live object graphs."""
    self.base_url = ""
    self.token = ""

  @classmethod
  def parse(cls, base_url: object, token: object) -> "TargetCapability":
    if not isinstance(base_url, str) or not isinstance(token, str):
      raise ProtocolError("invalid_exchange", "target capability is malformed")
    parsed = urlparse(base_url)
    try:
      port = parsed.port
    except ValueError as exc:
      raise ProtocolError("invalid_exchange", "target URL is not valid") from exc
    if (
      parsed.scheme not in {"http", "https"}
      or not parsed.netloc
      or parsed.username
      or parsed.password
      or parsed.query
      or parsed.fragment
      or parsed.path not in {"", "/"}
      or port is not None and not 1 <= port <= 65535
    ):
      raise ProtocolError("invalid_exchange", "target URL is not valid")
    token_bytes = token.encode("utf-8")
    if not 32 <= len(token_bytes) <= 512:
      raise ProtocolError("invalid_exchange", "target token length is invalid")
    return cls(base_url=base_url.rstrip("/"), token=token)


def parse_expiry(value: object) -> datetime:
  if not isinstance(value, str):
    raise ProtocolError("invalid_exchange", "session expiry is missing")
  try:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
  except ValueError as exc:
    raise ProtocolError("invalid_exchange", "session expiry is invalid") from exc
  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=timezone.utc)
  if parsed <= datetime.now(timezone.utc):
    raise ProtocolError("expired_exchange", "recovery session already expired")
  return parsed


def decode_bounded_base64(value: object, maximum: int = MAX_FILE_BYTES) -> bytes:
  if not isinstance(value, str):
    raise ProtocolError("invalid_response", "remote data is not base64 text")
  if len(value) > ((maximum + 2) // 3) * 4 + 4:
    raise ProtocolError("response_too_large", "remote data exceeds the size limit")
  try:
    result = base64.b64decode(value, validate=True)
  except (ValueError, TypeError) as exc:
    raise ProtocolError("invalid_response", "remote data is invalid base64") from exc
  if len(result) > maximum:
    raise ProtocolError("response_too_large", "remote data exceeds the size limit")
  return result


def require_protocol(payload: dict) -> None:
  if payload.get("protocol") != TARGET_PROTOCOL_VERSION:
    raise ProtocolError(
      "protocol_mismatch",
      f"target does not speak {TARGET_PROTOCOL_VERSION}",
    )
