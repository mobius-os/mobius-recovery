"""Narrow mobius.you control-plane exchange and finish client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import httpx

from .config import WORKER_PROTOCOL_VERSION, Settings
from .protocol import ProtocolError, TargetCapability, parse_expiry


MAX_CONTROL_RESPONSE_BYTES = 1024 * 1024


@dataclass
class ExchangeResult:
  session_id: str
  target: TargetCapability
  session_capability: str
  expires_at: datetime


class RecoveryResumed(ProtocolError):
  """Normal boot failed and control returned a fresh repair capability."""

  def __init__(
    self,
    *,
    session_id: str,
    target: TargetCapability,
    expires_at: datetime,
  ) -> None:
    super().__init__(
      "normal_boot_failed",
      "Normal boot failed; recovery resumed with a fresh target.",
      503,
    )
    self.session_id = session_id
    self.target = target
    self.expires_at = expires_at


class ControlClient:
  """Uses only the two recovery endpoints exposed by mobius.you."""

  def __init__(
    self,
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
  ) -> None:
    if not settings.managed:
      raise ValueError("control client requires managed mode")
    self._settings = settings
    self._client = httpx.Client(
      base_url=settings.control_plane_url,
      timeout=httpx.Timeout(20.0, connect=8.0),
      follow_redirects=False,
      trust_env=False,
      transport=transport,
      headers={"User-Agent": "mobius-recovery-worker/1"},
    )

  def close(self) -> None:
    self._client.close()

  def _post_json(
    self,
    path: str,
    body: dict,
    *,
    headers: dict[str, str] | None = None,
  ) -> tuple[int, dict]:
    try:
      with self._client.stream(
        "POST", path, json=body, headers=headers
      ) as response:
        length = response.headers.get("content-length")
        if length:
          try:
            if int(length) > MAX_CONTROL_RESPONSE_BYTES:
              raise ProtocolError(
                "control_response_too_large",
                "control response is too large",
              )
          except ValueError:
            pass
        raw = bytearray()
        for chunk in response.iter_bytes():
          raw.extend(chunk)
          if len(raw) > MAX_CONTROL_RESPONSE_BYTES:
            raise ProtocolError(
              "control_response_too_large",
              "control response is too large",
            )
        status = response.status_code
    except ProtocolError:
      raise
    except httpx.TimeoutException as exc:
      raise ProtocolError("control_timeout", "mobius.you timed out", 504) from exc
    except httpx.HTTPError as exc:
      raise ProtocolError("control_unreachable", "mobius.you is unreachable", 502) from exc
    try:
      data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
      raise ProtocolError("invalid_control_response", "control returned invalid JSON") from exc
    if not isinstance(data, dict):
      raise ProtocolError("invalid_control_response", "control returned invalid JSON")
    return status, data

  def exchange(self, code: str, instance_id: str) -> ExchangeResult:
    status, data = self._post_json(
      "/recovery/exchange",
      {
          "code": code,
          "instance_id": instance_id,
          "service_id": self._settings.service_id,
          "bootstrap_secret": self._settings.bootstrap_secret,
          "protocol_version": WORKER_PROTOCOL_VERSION,
      },
    )
    if status >= 400:
      error = data.get("error")
      message = (
        str(error.get("message"))
        if isinstance(error, dict) and error.get("message")
        else "Recovery link is invalid or expired. Open Recovery again."
      )
      raise ProtocolError("exchange_rejected", message[:500], status)
    if status >= 300:
      raise ProtocolError("invalid_control_response", "unexpected control redirect")
    session_id = data.get("session_id")
    capability = data.get("session_capability")
    if not isinstance(session_id, str) or not session_id:
      raise ProtocolError("invalid_exchange", "session id is missing")
    if not isinstance(capability, str) or len(capability) < 32:
      raise ProtocolError("invalid_exchange", "session capability is missing")
    return ExchangeResult(
      session_id=session_id,
      target=TargetCapability.parse(data.get("target_url"), data.get("target_token")),
      session_capability=capability,
      expires_at=parse_expiry(data.get("expires_at")),
    )

  def finish(self, result: ExchangeResult, outcome: str) -> None:
    if outcome not in {"recovered", "cancelled"}:
      raise ProtocolError("invalid_outcome", "invalid recovery outcome", 400)
    status, data = self._post_json(
      "/recovery/finish",
      {"session_id": result.session_id, "outcome": outcome},
      headers={"Authorization": f"Bearer {result.session_capability}"},
    )
    if status >= 400:
      error = data.get("error")
      if (
        status == 503
        and isinstance(error, dict)
        and error.get("code") == "normal_boot_failed"
      ):
        session_id = data.get("session_id")
        if session_id != result.session_id:
          raise ProtocolError(
            "invalid_control_response",
            "resumed recovery session id does not match",
          )
        raise RecoveryResumed(
          session_id=session_id,
          target=TargetCapability.parse(
            data.get("target_url"), data.get("target_token")
          ),
          expires_at=parse_expiry(data.get("expires_at")),
        )
      message = (
        str(error.get("message"))
        if isinstance(error, dict) and error.get("message")
        else "Could not finish the recovery session."
      )
      raise ProtocolError("finish_rejected", message[:500], status)
    if status >= 300:
      raise ProtocolError("invalid_control_response", "unexpected control redirect")
