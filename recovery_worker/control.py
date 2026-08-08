"""Narrow mobius.you control-plane exchange and finish client."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

from .config import WORKER_PROTOCOL_VERSION, Settings
from .launcher_client import LauncherTarget
from .protocol import ProtocolError, TargetCapability, parse_expiry


MAX_CONTROL_RESPONSE_BYTES = 1024 * 1024
CONTROL_RETRY_BACKOFF_SECONDS = 0.1


@dataclass
class ExchangeResult:
  session_id: str
  target: TargetCapability | LauncherTarget
  session_capability: str
  expires_at: datetime

  def clear(self) -> None:
    self.target.clear()
    self.session_capability = ""


@dataclass
class FinishResult:
  finish_id: str
  session_id: str
  status: str
  outcome: str
  generation: int
  status_url: str
  next_generation: int | None = None
  target: TargetCapability | None = None
  expires_at: datetime | None = None
  error_code: str | None = None
  error_message: str | None = None

  @property
  def pending(self) -> bool:
    return self.status in {"queued", "running"}


class ControlClient:
  """Uses only the two recovery endpoints exposed by mobius.you."""

  def __init__(
    self,
    settings: Settings,
    *,
    target_validator: Callable[[TargetCapability, object], None],
    transport: httpx.BaseTransport | None = None,
  ) -> None:
    if not settings.managed:
      raise ValueError("control client requires managed mode")
    self._settings = settings
    self._target_validator = target_validator
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

  def _request_json(
    self,
    method: str,
    path: str,
    body: dict | None,
    *,
    headers: dict[str, str] | None = None,
    retry_transport_once: bool = False,
  ) -> tuple[int, dict]:
    encoded = (
      json.dumps(body, separators=(",", ":")).encode("utf-8")
      if body is not None else None
    )
    request_headers = (
      {"Content-Type": "application/json"} if encoded is not None else {}
    )
    if headers:
      request_headers.update(headers)
    attempts = 2 if retry_transport_once else 1
    for attempt in range(attempts):
      try:
        response_context = self._client.stream(
          method, path, content=encoded, headers=request_headers
        )
        with response_context as response:
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
        break
      except ProtocolError:
        raise
      except httpx.TransportError as exc:
        if attempt + 1 < attempts:
          time.sleep(CONTROL_RETRY_BACKOFF_SECONDS)
          continue
        if isinstance(exc, httpx.TimeoutException):
          raise ProtocolError(
            "control_timeout", "mobius.you timed out", 504
          ) from exc
        raise ProtocolError(
          "control_unreachable", "mobius.you is unreachable", 502
        ) from exc
    try:
      data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
      raise ProtocolError("invalid_control_response", "control returned invalid JSON") from exc
    if not isinstance(data, dict):
      raise ProtocolError("invalid_control_response", "control returned invalid JSON")
    return status, data

  def _post_json(
    self,
    path: str,
    body: dict,
    *,
    headers: dict[str, str] | None = None,
    retry_transport_once: bool = False,
  ) -> tuple[int, dict]:
    return self._request_json(
      "POST",
      path,
      body,
      headers=headers,
      retry_transport_once=retry_transport_once,
    )

  def _get_json(
    self,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    retry_transport_once: bool = False,
  ) -> tuple[int, dict]:
    return self._request_json(
      "GET",
      path,
      None,
      headers=headers,
      retry_transport_once=retry_transport_once,
    )

  def exchange(self, code: str, instance_id: str) -> ExchangeResult:
    status, data = self._post_json(
      "/recovery/exchange",
      {
          "code": code,
          "instance_id": instance_id,
          "service_id": self._settings.service_id,
          "bootstrap_secret": self._settings.bootstrap_secret,
          "protocol_version": WORKER_PROTOCOL_VERSION,
          # Baked identity closes the final launch-to-exchange race: the
          # controller rejects an older process after a newer digest is
          # approved, before it discloses the target capability.
          "build_sha": self._settings.build_sha,
      },
      retry_transport_once=True,
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
    expires_at = parse_expiry(data.get("expires_at"))
    if self._settings.launcher_transport:
      # Approach 2 (draft): repairs run over the launcher's ssh RPC, so the
      # exchange yields no target daemon URL/token — only the session
      # capability, used as the launcher RPC bearer.
      target = LauncherTarget(
        launcher_url=self._settings.control_plane_url or "",
        session_capability=capability,
      )
    else:
      target = TargetCapability.parse(data.get("target_url"), data.get("target_token"))
      self._target_validator(target, data.get("target_token_sha256"))
    return ExchangeResult(
      session_id=session_id,
      target=target,
      session_capability=capability,
      expires_at=expires_at,
    )

  def _parse_finish(
    self,
    http_status: int,
    data: dict,
    exchange: ExchangeResult,
    expected_outcome: str,
    expected_generation: int,
  ) -> FinishResult:
    finish_id = data.get("finish_id")
    session_id = data.get("session_id")
    status = data.get("status")
    outcome = data.get("outcome")
    generation = data.get("generation")
    status_url = data.get("status_url")
    if (
      not isinstance(finish_id, str)
      or not 8 <= len(finish_id) <= 128
      or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in finish_id)
      or session_id != exchange.session_id
      or outcome != expected_outcome
      or isinstance(generation, bool)
      or not isinstance(generation, int)
      or generation != expected_generation
      or status not in {"queued", "running", "finished", "resumed", "failed"}
      or not isinstance(status_url, str)
    ):
      raise ProtocolError("invalid_control_response", "finish result is malformed")
    parsed_status_url = urlparse(status_url)
    expected_url = f"/recovery/finish/{finish_id}"
    if (
      parsed_status_url.scheme
      or parsed_status_url.netloc
      or parsed_status_url.params
      or parsed_status_url.query
      or parsed_status_url.fragment
      or parsed_status_url.path != expected_url
    ):
      raise ProtocolError("invalid_control_response", "finish status URL is invalid")
    if http_status == 202 and status not in {"queued", "running"}:
      raise ProtocolError("invalid_control_response", "finish status is invalid")
    if http_status == 200 and status != "finished":
      raise ProtocolError("invalid_control_response", "finish status is invalid")
    if http_status == 503 and status not in {"resumed", "failed"}:
      raise ProtocolError("invalid_control_response", "finish status is invalid")
    error_code = None
    error_message = None
    target = None
    expires_at = None
    next_generation = None
    if http_status == 503:
      error = data.get("error")
      if not isinstance(error, dict):
        raise ProtocolError("invalid_control_response", "finish error is missing")
      error_code = str(error.get("code") or "finish_failed")[:80]
      error_message = str(
        error.get("message") or "Recovery could not be finished."
      )[:1000]
      if error_code == "normal_boot_failed":
        if status != "resumed":
          raise ProtocolError(
            "invalid_control_response", "finish resume status is invalid"
          )
        next_generation = data.get("next_generation")
        if (
          isinstance(next_generation, bool)
          or next_generation != generation + 1
        ):
          raise ProtocolError(
            "invalid_control_response", "finish next generation is invalid"
          )
        expires_at = parse_expiry(data.get("expires_at"))
        if self._settings.launcher_transport:
          target = LauncherTarget(
            launcher_url=self._settings.control_plane_url or "",
            session_capability=exchange.session_capability,
          )
        else:
          target = TargetCapability.parse(
            data.get("target_url"), data.get("target_token")
          )
          self._target_validator(target, data.get("target_token_sha256"))
      elif status == "resumed":
        raise ProtocolError(
          "invalid_control_response", "finish resume result is invalid"
        )
    if status != "resumed" and any(
      field in data
      for field in (
        "target_url", "target_token", "target_token_sha256",
        "expires_at", "next_generation",
      )
    ):
      raise ProtocolError(
        "invalid_control_response", "finish result contains unexpected target access"
      )
    return FinishResult(
      finish_id=finish_id,
      session_id=session_id,
      status=status,
      outcome=outcome,
      generation=generation,
      status_url=status_url,
      next_generation=next_generation,
      target=target,
      expires_at=expires_at,
      error_code=error_code,
      error_message=error_message,
    )

  def finish(
    self,
    result: ExchangeResult,
    outcome: str,
    generation: int,
  ) -> FinishResult:
    if outcome not in {"recovered", "cancelled"}:
      raise ProtocolError("invalid_outcome", "invalid recovery outcome", 400)
    if (
      isinstance(generation, bool)
      or not isinstance(generation, int)
      or generation < 1
    ):
      raise ProtocolError("invalid_generation", "invalid finish generation", 400)
    status, data = self._post_json(
      "/recovery/finish",
      {
        "session_id": result.session_id,
        "outcome": outcome,
        "generation": generation,
      },
      headers={"Authorization": f"Bearer {result.session_capability}"},
      retry_transport_once=True,
    )
    if status not in {200, 202, 503}:
      error = data.get("error")
      message = (
        str(error.get("message"))
        if isinstance(error, dict) and error.get("message")
        else "Could not finish the recovery session."
      )
      raise ProtocolError("finish_rejected", message[:500], status)
    return self._parse_finish(status, data, result, outcome, generation)

  def poll_finish(
    self,
    exchange: ExchangeResult,
    finish: FinishResult,
  ) -> FinishResult:
    status, data = self._get_json(
      finish.status_url,
      headers={"Authorization": f"Bearer {exchange.session_capability}"},
      retry_transport_once=True,
    )
    if status not in {200, 202, 503}:
      error = data.get("error")
      message = (
        str(error.get("message"))
        if isinstance(error, dict) and error.get("message")
        else "Could not read recovery finish status."
      )
      raise ProtocolError("finish_status_rejected", message[:500], status)
    parsed = self._parse_finish(
      status, data, exchange, finish.outcome, finish.generation
    )
    if parsed.finish_id != finish.finish_id:
      raise ProtocolError("invalid_control_response", "finish id changed")
    return parsed

  def acknowledge(self, result: ExchangeResult) -> None:
    """Clears the controller's retry receipt after local session storage."""
    status, data = self._post_json(
      "/recovery/exchange/ack",
      {"session_id": result.session_id},
      headers={"Authorization": f"Bearer {result.session_capability}"},
      retry_transport_once=True,
    )
    if status >= 400:
      error = data.get("error")
      message = (
        str(error.get("message"))
        if isinstance(error, dict) and error.get("message")
        else "Could not acknowledge the recovery exchange."
      )
      raise ProtocolError("exchange_ack_rejected", message[:500], status)
    if status >= 300:
      raise ProtocolError("invalid_control_response", "unexpected control redirect")
