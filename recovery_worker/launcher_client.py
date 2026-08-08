"""Approach-2 transport: forward target operations to the trusted launcher.

Drop-in replacement for ``TargetClient`` with the SAME operation surface
(``health``/``exec``/``read``/``write``/``list`` + lifecycle), but pointed at the
launcher's session-authenticated recovery RPC instead of the in-container target
daemon. In approach 2 the launcher holds the (broad) Railway credential and runs
each operation inside the RUNNING main service over ``railway ssh``; the
worker/AI never holds a Railway credential.

Isolation is preserved exactly as ``TargetClient``: the launcher base URL and the
session capability are constructor-only — no public operation accepts a host,
service, or token override — so the recovery agent cannot redirect its
privilege. Redirects are disabled so a compromised endpoint cannot relay the
bearer, and responses are size-bounded.

DRAFT — selected only when configured for approach 2 (see ``config.py``); the
legacy ``TargetClient`` path remains the default until the railway-ssh transport
is validated on a live Railway instance (see mobius.you
``docs/design/recovery-railway-ssh.md``).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from .protocol import MAX_FILE_BYTES, MAX_HTTP_RESPONSE_BYTES, ProtocolError

RECOVERY_RPC_PATH = "/internal/recovery/op"
REQUEST_TIMEOUT_SECONDS = 150.0


class LauncherClient:
  """Calls one launcher URL with one session capability.

  Mirrors ``TargetClient``'s method surface so ``TargetBroker`` and ``app.py``
  use it unchanged. The base URL and capability are constructor-only.
  """

  def __init__(
    self,
    launcher_url: str,
    session_capability: str,
    *,
    transport: httpx.BaseTransport | None = None,
  ) -> None:
    if not isinstance(launcher_url, str) or not launcher_url.startswith("https://"):
      raise ValueError("launcher_url must be an https URL")
    if not isinstance(session_capability, str) or len(session_capability) < 32:
      raise ValueError("session capability is missing")
    self._url = launcher_url.rstrip("/") + RECOVERY_RPC_PATH
    self._capability = session_capability
    self._client = httpx.Client(
      timeout=REQUEST_TIMEOUT_SECONDS,
      transport=transport,
      follow_redirects=False,
    )

  def close(self) -> None:
    self._client.close()

  def revoke(self) -> None:
    # No standing target capability to revoke in approach 2 — the launcher ends
    # ssh access when the session ends. Best-effort notify; never raise.
    try:
      self._call("revoke", {})
    except ProtocolError:
      pass

  def _call(self, operation: str, args: dict) -> Any:
    try:
      response = self._client.post(
        self._url,
        json={"operation": operation, "args": args},
        headers={"Authorization": f"Bearer {self._capability}"},
      )
    except httpx.HTTPError as exc:
      raise ProtocolError(
        "launcher_unreachable", "recovery launcher is unreachable", 502
      ) from exc
    body = response.read()
    if len(body) > MAX_HTTP_RESPONSE_BYTES:
      raise ProtocolError("response_too_large", "launcher response too large", 502)
    if response.status_code != 200:
      raise ProtocolError(
        "launcher_error", f"launcher op failed ({response.status_code})", 502
      )
    try:
      return response.json()
    except ValueError as exc:
      raise ProtocolError(
        "launcher_error", "launcher response was not JSON", 502
      ) from exc

  def health(self) -> dict:
    return self._call("health", {})

  def exec(
    self,
    argv,
    *,
    cwd=None,
    env=None,
    stdin=None,
    stdin_base64=None,
    timeout_seconds: int = 120,
  ) -> dict:
    return self._call(
      "exec",
      {
        "argv": argv,
        "cwd": cwd,
        "env": env,
        "stdin": stdin,
        "stdin_base64": stdin_base64,
        "timeout_seconds": timeout_seconds,
      },
    )

  def read(
    self, path: str, *, offset: int = 0, limit: int = MAX_FILE_BYTES
  ) -> tuple[bytes, bool]:
    result = self._call("read", {"path": path, "offset": offset, "limit": limit})
    data = base64.b64decode(result.get("data_base64", ""), validate=True)
    return data, bool(result.get("eof", True))

  def write(self, path: str, data: bytes, *, mode=None, atomic: bool = True) -> dict:
    return self._call(
      "write",
      {
        "path": path,
        "data_base64": base64.b64encode(data).decode("ascii"),
        "mode": mode,
        "atomic": atomic,
      },
    )

  def list(self, path: str) -> list[dict]:
    result = self._call("list", {"path": path})
    if isinstance(result, dict):
      return result.get("entries", [])
    return result
