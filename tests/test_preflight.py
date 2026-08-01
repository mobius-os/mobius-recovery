from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from recovery_worker.app import create_app
from recovery_worker.config import Settings, baked_build_revision


BOOTSTRAP = "bootstrap-" + "b" * 32
TARGET_TOKEN = "target-" + "t" * 40


def settings() -> Settings:
  return Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="instance-1",
    bootstrap_secret=BOOTSTRAP,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )


def request(client: TestClient, **overrides):
  body = {
    "target_url": "http://mobius.railway.internal:18002",
    "target_token": TARGET_TOKEN,
  }
  body.update(overrides)
  return client.post(
    "/internal/target/verify",
    headers={"Authorization": f"Bearer {BOOTSTRAP}"},
    json=body,
  )


def test_preflight_validates_recovery_target_without_retaining_secret(tmp_path) -> None:
  def target(call: httpx.Request) -> httpx.Response:
    assert call.headers["authorization"] == f"Bearer {TARGET_TOKEN}"
    return httpx.Response(200, json={
      "protocol": "mobius-recovery-target/v1",
      "mode": "recovery",
      "target": "mobius",
      "build_sha": "a" * 40,
    })

  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    response = request(client)
    assert response.status_code == 200
    assert response.json() == {
      "status": "ok",
      "protocol": "mobius-recovery-target/v1",
      "build_sha": "a" * 40,
    }
  assert not hasattr(app.state, "target_token")
  assert TARGET_TOKEN not in repr(app.state.__dict__)


def test_preflight_rejects_bad_bootstrap_and_public_ssrf_target(tmp_path) -> None:
  calls = 0

  def target(_request: httpx.Request) -> httpx.Response:
    nonlocal calls
    calls += 1
    return httpx.Response(200, json={})

  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    bad_auth = client.post(
      "/internal/target/verify",
      headers={"Authorization": "Bearer wrong"},
      json={
        "target_url": "http://mobius.railway.internal:18002",
        "target_token": TARGET_TOKEN,
      },
    )
    assert bad_auth.status_code == 401
    public = request(client, target_url="http://169.254.169.254/latest/meta-data")
    assert public.status_code == 400
    default_port = request(client, target_url="http://mobius.railway.internal")
    assert default_port.status_code == 400
    unicode_auth = client.post(
      "/internal/target/verify",
      headers=[(b"authorization", b"Bearer caf\xe9")],
      json={
        "target_url": "http://mobius.railway.internal:18002",
        "target_token": TARGET_TOKEN,
      },
    )
    assert unicode_auth.status_code == 401
    assert calls == 0


def test_preflight_rejects_redirect_protocol_mismatch_and_wrong_mode(tmp_path) -> None:
  responses = iter([
    httpx.Response(302, headers={"Location": "http://evil.invalid"}),
    httpx.Response(200, json={
      "protocol": "old/v0", "mode": "recovery", "target": "mobius"
    }),
    httpx.Response(200, json={
      "protocol": "mobius-recovery-target/v1",
      "mode": "normal",
      "target": "mobius",
    }),
  ])
  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(lambda _request: next(responses)),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    assert request(client).json()["error"]["code"] == "unexpected_status"
    assert request(client).json()["error"]["code"] == "protocol_mismatch"
    wrong_mode = request(client)
    assert wrong_mode.status_code == 409
    assert wrong_mode.json()["error"]["code"] == "target_not_recovery"
