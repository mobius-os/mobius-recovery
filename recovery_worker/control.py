"""Narrow, session-bound client for the mobius.you recovery relay."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from .config import WORKER_PROTOCOL_VERSION, Settings
from .protocol import ProtocolError, parse_expiry


MAX_CONTROL_RESPONSE_BYTES = 16 * 1024 * 1024
CONTROL_RETRY_BACKOFF_SECONDS = 0.1


@dataclass
class ExchangeResult:
  session_id: str
  session_capability: str
  expires_at: datetime

  def clear(self) -> None:
    self.session_capability = ""


class ControlClient:
  """Exchanges a launch code, relays fixed-session commands, and closes it."""

  def __init__(
    self,
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
  ) -> None:
    self._settings = settings
    self._client = httpx.Client(
      base_url=settings.control_plane_url,
      timeout=httpx.Timeout(20.0, connect=8.0),
      follow_redirects=False,
      trust_env=False,
      transport=transport,
      headers={"User-Agent": "mobius-recovery-worker/2"},
    )

  def close(self) -> None:
    self._client.close()

  def _request_json(
    self,
    method: str,
    path: str,
    body: dict,
    *,
    capability: str | None = None,
    retry_transport_once: bool = False,
  ) -> tuple[int, dict]:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if capability:
      headers["Authorization"] = f"Bearer {capability}"
    attempts = 2 if retry_transport_once else 1
    for attempt in range(attempts):
      try:
        with self._client.stream(
          method, path, content=encoded, headers=headers
        ) as response:
          if response.is_redirect:
            raise ProtocolError(
              "invalid_control_response", "mobius.you returned a redirect", 502
            )
          raw = bytearray()
          for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_CONTROL_RESPONSE_BYTES:
              raise ProtocolError(
                "control_response_too_large", "mobius.you response is too large", 502
              )
          status = response.status_code
        break
      except ProtocolError:
        raise
      except httpx.TransportError as exc:
        if attempt + 1 < attempts:
          time.sleep(CONTROL_RETRY_BACKOFF_SECONDS)
          continue
        code = "control_timeout" if isinstance(exc, httpx.TimeoutException) else "control_unreachable"
        status = 504 if code == "control_timeout" else 502
        raise ProtocolError(code, "mobius.you is unavailable", status) from exc
    try:
      data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
      raise ProtocolError(
        "invalid_control_response", "mobius.you returned invalid JSON", 502
      ) from exc
    if not isinstance(data, dict):
      raise ProtocolError(
        "invalid_control_response", "mobius.you returned invalid JSON", 502
      )
    return status, data

  @staticmethod
  def _raise_remote(status: int, data: dict, fallback: str) -> None:
    error = data.get("error")
    message = (
      str(error.get("message"))
      if isinstance(error, dict) and error.get("message") else fallback
    )
    raise ProtocolError("control_rejected", message[:500], status)

  def exchange(self, code: str, instance_id: str) -> ExchangeResult:
    status, data = self._request_json(
      "POST",
      "/recovery/exchange",
      {
        "code": code,
        "instance_id": instance_id,
        "service_id": self._settings.service_id,
        "bootstrap_secret": self._settings.bootstrap_secret,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "build_sha": self._settings.build_sha,
      },
      retry_transport_once=True,
    )
    if status >= 300:
      self._raise_remote(
        status, data, "Recovery link is invalid or expired. Open Recovery again."
      )
    session_id = data.get("session_id")
    capability = data.get("session_capability")
    launcher_url = data.get("launcher_url")
    if not isinstance(session_id, str) or not session_id:
      raise ProtocolError("invalid_exchange", "session id is missing", 502)
    if not isinstance(capability, str) or len(capability) < 32:
      raise ProtocolError("invalid_exchange", "session capability is missing", 502)
    if launcher_url != self._settings.control_plane_url:
      raise ProtocolError("invalid_exchange", "launcher origin changed", 502)
    return ExchangeResult(
      session_id=session_id,
      session_capability=capability,
      expires_at=parse_expiry(data.get("expires_at")),
    )

  def acknowledge(self, exchange: ExchangeResult) -> None:
    status, data = self._request_json(
      "POST",
      "/recovery/exchange/ack",
      {"session_id": exchange.session_id},
      capability=exchange.session_capability,
      retry_transport_once=True,
    )
    if status >= 300:
      self._raise_remote(status, data, "Could not acknowledge recovery launch.")

  def exec(self, exchange: ExchangeResult, args: dict) -> dict:
    status, data = self._request_json(
      "POST",
      "/internal/recovery/exec",
      args,
      capability=exchange.session_capability,
    )
    if status >= 300:
      self._raise_remote(status, data, "Remote command failed to start.")
    required = {"stdout_base64", "stderr_base64", "exit_code"}
    if not required.issubset(data):
      raise ProtocolError("invalid_control_response", "command result is malformed", 502)
    return {key: data[key] for key in required}

  def finish(self, exchange: ExchangeResult, outcome: str) -> dict:
    if outcome not in {"recovered", "cancelled"}:
      raise ProtocolError("invalid_outcome", "invalid recovery outcome", 400)
    status, data = self._request_json(
      "POST",
      "/recovery/finish",
      {"session_id": exchange.session_id, "outcome": outcome},
      capability=exchange.session_capability,
      retry_transport_once=True,
    )
    if status >= 300:
      self._raise_remote(status, data, "Could not close the recovery session.")
    if data.get("status") != "finished" or data.get("outcome") != outcome:
      raise ProtocolError("invalid_control_response", "finish result is malformed", 502)
    return {"status": "finished", "outcome": outcome}
