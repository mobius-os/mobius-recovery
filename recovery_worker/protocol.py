"""Small shared validation primitives for recovery protocol v3."""

from __future__ import annotations

from datetime import datetime, timezone


class ProtocolError(RuntimeError):
  """A bounded, user-safe remote protocol failure."""

  def __init__(self, code: str, message: str, status: int = 502) -> None:
    super().__init__(message)
    self.code = code
    self.message = message
    self.status = status


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
