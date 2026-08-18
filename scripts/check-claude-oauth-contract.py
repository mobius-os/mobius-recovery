#!/usr/bin/env python3
"""Verify that the worker transport reaches Claude's OAuth application."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recovery_worker.providers import (
  _CLAUDE_CLIENT_ID,
  _REDIRECT_URI,
  claude_token_response,
)


def main() -> None:
  marker = secrets.token_urlsafe(24)
  response = claude_token_response({
    "grant_type": "authorization_code",
    "code": f"invalid-{marker}",
    "client_id": _CLAUDE_CLIENT_ID,
    "redirect_uri": _REDIRECT_URI,
    "code_verifier": f"invalid-{marker}",
    "state": marker,
  })
  content_type = response.headers.get("content-type", "").lower()
  if response.status_code != 400 or "application/json" not in content_type:
    raise SystemExit(
      "Claude OAuth contract probe did not reach the token application "
      f"(status={response.status_code}, content-type={content_type or 'missing'})."
    )
  try:
    payload = response.json()
  except ValueError as exc:
    raise SystemExit("Claude OAuth contract probe returned invalid JSON.") from exc
  if not isinstance(payload, dict) or not payload.get("error"):
    raise SystemExit("Claude OAuth contract probe returned an unexpected response.")
  print("Claude OAuth transport reached the token application.")


if __name__ == "__main__":
  main()
