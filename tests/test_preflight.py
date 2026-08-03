from __future__ import annotations

import hashlib

import httpx
from fastapi.testclient import TestClient
import pytest

from recovery_worker.app import create_app
from recovery_worker.config import Settings, baked_build_revision
from recovery_worker.preflight import PreflightBindings, managed_target_url
from recovery_worker.protocol import ProtocolError, TargetCapability


BOOTSTRAP = "bootstrap-" + "b" * 32
TARGET_TOKEN = "target-" + "t" * 40
MANAGED_TARGET_URL = "http://mobius.railway.internal:18002"


def settings() -> Settings:
  return Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret=BOOTSTRAP,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )


def request(client: TestClient, **overrides):
  body = {
    "target_url": MANAGED_TARGET_URL,
    "target_token": TARGET_TOKEN,
  }
  body.update(overrides)
  return client.post(
    "/internal/target/verify",
    headers={"Authorization": f"Bearer {BOOTSTRAP}"},
    json=body,
  )


def revoke_request(client: TestClient, **overrides):
  body = {
    "target_url": MANAGED_TARGET_URL,
    "target_token": TARGET_TOKEN,
  }
  body.update(overrides)
  return client.post(
    "/internal/target/revoke",
    headers={"Authorization": f"Bearer {BOOTSTRAP}"},
    json=body,
  )


def test_preflight_validates_recovery_target_without_retaining_secret(tmp_path) -> None:
  def target(call: httpx.Request) -> httpx.Response:
    assert call.headers["authorization"] == f"Bearer {TARGET_TOKEN}"
    return httpx.Response(200, json={
      "protocol": "mobius-recovery-target/v1",
      "mode": "normal",
      "target": "mobius",
      "build_sha": "a" * 40,
      "deployment_id": "deployment-123",
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
      "mode": "normal",
      "deployment_id": "deployment-123",
    }
  assert not hasattr(app.state, "target_token")
  assert TARGET_TOKEN not in repr(app.state.__dict__)


def test_preflight_preserves_legacy_managed_recovery_mode(tmp_path) -> None:
  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(
      lambda _request: httpx.Response(200, json={
        "protocol": "mobius-recovery-target/v1",
        "mode": "recovery",
        "target": "mobius",
        "build_sha": "a" * 40,
      })
    ),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    response = request(client)
  assert response.status_code == 200
  assert response.json() == {
    "status": "ok",
    "protocol": "mobius-recovery-target/v1",
    "build_sha": "a" * 40,
    "mode": "recovery",
  }


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
        "target_url": MANAGED_TARGET_URL,
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
        "target_url": MANAGED_TARGET_URL,
        "target_token": TARGET_TOKEN,
      },
    )
    assert unicode_auth.status_code == 401
    assert calls == 0


def test_preflight_rejects_redirect_protocol_mismatch_and_wrong_mode(tmp_path) -> None:
  responses = iter([
    httpx.Response(302, headers={"Location": "http://evil.invalid"}),
    httpx.Response(200, json={
      "protocol": "old/v0", "mode": "normal", "target": "mobius"
    }),
    httpx.Response(200, json={
      "protocol": "mobius-recovery-target/v1",
      "mode": "maintenance",
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
    assert wrong_mode.json()["error"]["code"] == "target_mode_invalid"


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("build_sha", ""),
    ("build_sha", "x" * 129),
    ("deployment_id", None),
    ("deployment_id", "x" * 129),
  ],
)
def test_preflight_rejects_unbounded_target_identity(
  tmp_path, field: str, value: object,
) -> None:
  health = {
    "protocol": "mobius-recovery-target/v1",
    "mode": "normal",
    "target": "mobius",
    "build_sha": "a" * 40,
    "deployment_id": "deployment-123",
  }
  health[field] = value
  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(
      lambda _request: httpx.Response(200, json=health)
    ),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    response = request(client)
  assert response.status_code == 502
  assert response.json()["error"]["code"] == "invalid_response"
  capability = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  with pytest.raises(ProtocolError) as rejected:
    app.state.preflight_bindings.consume(
      capability,
      hashlib.sha256(TARGET_TOKEN.encode("utf-8")).hexdigest(),
    )
  assert rejected.value.code == "unverified_target"


def test_internal_revoke_returns_only_target_authenticated_identity(tmp_path) -> None:
  calls: list[httpx.Request] = []

  def target(call: httpx.Request) -> httpx.Response:
    calls.append(call)
    assert call.method == "POST"
    assert call.url.path == "/v1/revoke"
    assert call.headers["authorization"] == f"Bearer {TARGET_TOKEN}"
    assert call.content == b"{}"
    return httpx.Response(200, json={
      "status": "revoked",
      "deployment_id": "deployment-from-target",
      "session_id": "session-from-target",
    })

  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    response = revoke_request(client)
  assert response.status_code == 200
  assert response.json() == {
    "status": "revoked",
    "deployment_id": "deployment-from-target",
    "session_id": "session-from-target",
  }
  assert len(calls) == 1

  # Dashboard close must not create a one-use exchange preflight binding.
  capability = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  with pytest.raises(ProtocolError) as rejected:
    app.state.preflight_bindings.consume(
      capability,
      hashlib.sha256(TARGET_TOKEN.encode("utf-8")).hexdigest(),
    )
  assert rejected.value.code == "unverified_target"


def test_internal_revoke_rejects_bad_auth_ssrf_and_caller_identity(tmp_path) -> None:
  calls = 0

  def target(_request: httpx.Request) -> httpx.Response:
    nonlocal calls
    calls += 1
    return httpx.Response(500)

  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    bad_auth = client.post(
      "/internal/target/revoke",
      headers={"Authorization": "Bearer wrong"},
      json={"target_url": MANAGED_TARGET_URL, "target_token": TARGET_TOKEN},
    )
    assert bad_auth.status_code == 401
    assert revoke_request(
      client, target_url="http://169.254.169.254:18002"
    ).status_code == 400
    supplied_identity = revoke_request(
      client,
      deployment_id="caller-deployment",
      session_id="caller-session",
    )
    assert supplied_identity.status_code == 400
    assert supplied_identity.json()["error"]["code"] == "invalid_request"
  assert calls == 0


@pytest.mark.parametrize(
  ("target_response", "expected_code"),
  [
    (
      httpx.Response(200, json={
        "status": "revoked",
        "deployment_id": "deployment-only",
      }),
      "invalid_response",
    ),
    (
      httpx.Response(200, content=b"x" * (16 * 1024 + 1)),
      "response_too_large",
    ),
  ],
)
def test_internal_revoke_bounds_and_validates_target_confirmation(
  tmp_path, target_response: httpx.Response, expected_code: str,
) -> None:
  app = create_app(
    settings(),
    control_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    target_transport=httpx.MockTransport(lambda _request: target_response),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    response = revoke_request(client)
  assert response.status_code == 502
  assert response.json()["error"]["code"] == expected_code


@pytest.mark.parametrize(
  "candidate",
  [
    "http://other.service.railway.internal:18002",
    "http://Mobius.railway.internal:18002",
    "http://mobius.railway.internal:18002/",
    "http://user@mobius.railway.internal:18002",
    "http://mobius.railway.internal:18002?probe=1",
    "http://mobius.railway.internal:18002#fragment",
    "https://mobius.railway.internal:18002",
    "http://mobius.railway.internal:18003",
  ],
)
def test_managed_target_url_requires_canonical_private_endpoint(
  candidate: str,
) -> None:
  assert managed_target_url(MANAGED_TARGET_URL) == MANAGED_TARGET_URL
  assert managed_target_url("http://other.railway.internal:18002") == (
    "http://other.railway.internal:18002"
  )
  with pytest.raises(ProtocolError) as rejected:
    managed_target_url(candidate)
  assert rejected.value.code == "invalid_target"


def test_preflight_binding_requires_matching_token_hash_and_is_one_use() -> None:
  bindings = PreflightBindings(clock=lambda: 100.0)
  recorded = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  bindings.record(recorded)
  advertised_hash = hashlib.sha256(TARGET_TOKEN.encode("utf-8")).hexdigest()

  accepted = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  bindings.consume(accepted, advertised_hash)
  assert accepted.token == TARGET_TOKEN

  replay = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  with pytest.raises(ProtocolError) as rejected:
    bindings.consume(replay, advertised_hash)
  assert rejected.value.code == "unverified_target"
  assert replay.base_url == ""
  assert replay.token == ""


def test_preflight_binding_rejects_mismatched_advertised_token_hash() -> None:
  bindings = PreflightBindings(clock=lambda: 100.0)
  bindings.record(TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN))
  capability = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)

  with pytest.raises(ProtocolError) as rejected:
    bindings.consume(capability, "0" * 64)
  assert rejected.value.code == "invalid_exchange"
  assert capability.base_url == ""
  assert capability.token == ""


def test_preflight_binding_rejects_wrong_capability_and_expiry() -> None:
  now = [100.0]
  bindings = PreflightBindings(clock=lambda: now[0])
  bindings.record(TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN))
  wrong_token = "wrong-" + "w" * 40
  wrong = TargetCapability(MANAGED_TARGET_URL, wrong_token)
  with pytest.raises(ProtocolError) as mismatched:
    bindings.consume(
      wrong, hashlib.sha256(wrong_token.encode("utf-8")).hexdigest()
    )
  assert mismatched.value.code == "unverified_target"
  assert wrong.token == ""

  bindings.record(TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN))
  now[0] += 15 * 60
  expired = TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  with pytest.raises(ProtocolError) as rejected:
    bindings.consume(
      expired, hashlib.sha256(TARGET_TOKEN.encode("utf-8")).hexdigest()
    )
  assert rejected.value.code == "unverified_target"
  assert expired.token == ""
