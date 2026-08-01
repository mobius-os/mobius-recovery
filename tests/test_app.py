from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from recovery_worker.app import _cookie_max_age, _sse_events, create_app
from recovery_worker.chat import _claim, _release
from recovery_worker.config import (
  TARGET_PROTOCOL_VERSION,
  WORKER_PROTOCOL_VERSION,
  Settings,
  baked_build_revision,
)
from recovery_worker.protocol import TargetCapability
from recovery_worker.sessions import RecoverySession


LOCAL_CODE = "local-code-" + "c" * 32
TARGET_TOKEN = "target-token-" + "t" * 32
SAME_ORIGIN = {
  "Origin": "http://testserver",
  "Sec-Fetch-Site": "same-origin",
}


def local_settings() -> Settings:
  return Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="local",
    secure_cookie=False,
    control_plane_url=None,
    instance_id=None,
    bootstrap_secret=None,
    local_target_url="http://target.internal",
    local_target_token=TARGET_TOKEN,
    local_token=LOCAL_CODE,
  )


def target(request: httpx.Request) -> httpx.Response:
  assert request.headers["authorization"] == f"Bearer {TARGET_TOKEN}"
  return httpx.Response(200, json={
    "status": "ready",
    "protocol": TARGET_PROTOCOL_VERSION,
    "target": "mobius",
    "target_id": "local",
    "mode": "recovery",
  })


def test_browser_cookie_tracks_grant_with_one_hour_ceiling() -> None:
  now = datetime(2026, 8, 1, tzinfo=timezone.utc)
  target_capability = TargetCapability("http://target.internal", TARGET_TOKEN)
  short = RecoverySession(
    session_id="short",
    target=target_capability,
    expires_at=now + timedelta(minutes=45),
  )
  long = RecoverySession(
    session_id="long",
    target=target_capability,
    expires_at=now + timedelta(hours=2),
  )
  assert _cookie_max_age(short, now=now) == 45 * 60
  assert _cookie_max_age(long, now=now) == 60 * 60


def test_health_uses_baked_identity_not_runtime_env(monkeypatch, tmp_path) -> None:
  monkeypatch.setenv("MOBIUS_RECOVERY_BUILD_DIGEST", "sha256:spoofed")
  monkeypatch.setenv("MOBIUS_RECOVERY_BUILD_SHA", "f" * 40)
  settings = local_settings()
  assert settings.build_sha == baked_build_revision()
  app = create_app(
    settings,
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    data = client.get("/health").json()
  assert data == {
    "status": "ready",
    "build_sha": baked_build_revision(),
    "protocol_version": WORKER_PROTOCOL_VERSION,
    "service_id": "local",
  }


def test_local_auth_rejects_wrong_code_and_replay(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    wrong = client.post(
      "/session/start", data={"code": "wrong"}, follow_redirects=False
    )
    assert wrong.status_code == 401
    started = client.post(
      "/session/start", data={"code": LOCAL_CODE}, follow_redirects=False
    )
    assert started.status_code == 200
    assert "HttpOnly" in started.headers["set-cookie"]
    assert "SameSite=strict" in started.headers["set-cookie"]
    assert client.get("/api/providers").status_code == 200
    replay = client.post(
      "/session/start", data={"code": LOCAL_CODE}, follow_redirects=False
    )
    assert replay.status_code == 401


def test_cross_site_launch_returns_authenticated_page_without_code_url(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    started = client.post(
      "/session/start",
      data={"code": LOCAL_CODE},
      headers={
        "Sec-Fetch-Site": "cross-site",
        "Origin": "https://www.mobius.you",
      },
    )
    assert started.status_code == 200
    assert "location" not in started.headers
    assert started.headers["referrer-policy"] == "no-referrer"
    assert "SameSite=strict" in started.headers["set-cookie"]
    assert LOCAL_CODE not in started.text
    assert "history.replaceState(null,'','/')" in started.text
    assert "Repair conversation" in started.text
    assert "document.visibilityState==='visible'" in started.text
    assert "setInterval(heartbeat,45000)" in started.text


def test_managed_process_loss_requires_fresh_launch(tmp_path) -> None:
  settings = Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  app = create_app(
    settings,
    control_transport=httpx.MockTransport(
      lambda _request: httpx.Response(500)
    ),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app, base_url="https://recovery.example") as client:
    client.cookies.set("mobius_recovery_session", "lost-process-token")
    page = client.get("/")
  assert page.status_code == 200
  assert "Recovery needs a fresh launch." in page.text
  assert "in-memory session was safely erased" in page.text
  assert "Return to Mobius" in page.text
  assert "One-time recovery code" not in page.text


def test_cross_site_state_change_is_rejected(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    client.post("/session/start", data={"code": LOCAL_CODE})
    response = client.post(
      "/api/finish",
      headers={
        "Origin": "https://hostile.example",
        "Sec-Fetch-Site": "cross-site",
      },
      json={"outcome": "recovered"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_site"

    sibling = client.post(
      "/api/finish",
      headers={
        "Origin": "https://sibling.up.railway.app",
        "Sec-Fetch-Site": "same-site",
      },
      json={"outcome": "cancelled"},
    )
    assert sibling.status_code == 403
    assert sibling.json()["error"]["code"] == "cross_site"

    wrong_origin = client.post(
      "/api/finish",
      headers={
        "Origin": "https://sibling.up.railway.app",
        "Sec-Fetch-Site": "same-origin",
      },
      json={"outcome": "cancelled"},
    )
    assert wrong_origin.status_code == 403

    missing_provenance = client.post(
      "/api/finish", json={"outcome": "cancelled"}
    )
    assert missing_provenance.status_code == 403

    text_plain = client.post(
      "/api/finish",
      headers={**SAME_ORIGIN, "Content-Type": "text/plain"},
      content='{"outcome":"cancelled"}',
    )
    assert text_plain.status_code == 415
    assert text_plain.json()["error"]["code"] == "unsupported_media_type"


def test_consumed_local_grant_keeps_session_when_target_is_waking(tmp_path) -> None:
  unavailable = httpx.MockTransport(lambda _request: httpx.Response(503, json={
    "error": {"code": "target_starting", "message": "Target is still waking."}
  }))
  app = create_app(
    local_settings(),
    target_transport=unavailable,
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    started = client.post(
      "/session/start", data={"code": LOCAL_CODE}, follow_redirects=False
    )
    assert started.status_code == 200
    assert "Secure" not in started.headers["set-cookie"]
    page = client.get("/")
    assert page.status_code == 200
    assert "Target is still waking." in page.text
    assert client.get("/api/providers").status_code == 200


def test_consumed_managed_grant_keeps_secure_session_when_target_wakes(tmp_path) -> None:
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()

  def control(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/recovery/exchange"
    return httpx.Response(200, json={
      "session_id": "managed-session",
      "target_url": "http://target.internal",
      "target_token": TARGET_TOKEN,
      "session_capability": "finish-" + "f" * 40,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  unavailable = httpx.MockTransport(lambda _request: httpx.Response(503, json={
    "error": {"code": "target_starting", "message": "Target is still waking."}
  }))
  app = create_app(
    settings,
    control_transport=httpx.MockTransport(control),
    target_transport=unavailable,
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app, base_url="https://recovery.example") as client:
    started = client.post(
      "/session/start",
      data={"code": "managed-code", "instance_id": "instance-1"},
      follow_redirects=False,
    )
    assert started.status_code == 200
    assert "Secure" in started.headers["set-cookie"]
    assert client.get("/api/providers").status_code == 200


def test_session_start_rejects_oversized_and_chunked_forms(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    oversized = client.post("/session/start", data={"code": "x" * 17000})
    assert oversized.status_code == 413

    def chunks():
      yield b"code="
      yield b"x" * 17000

    chunked = client.post(
      "/session/start",
      content=chunks(),
      headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert chunked.status_code == 413
    multipart = client.post(
      "/session/start",
      files={"code": (None, LOCAL_CODE)},
    )
    assert multipart.status_code == 415


def test_finish_is_rejected_while_recovery_stream_owns_turn(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    client.post("/session/start", data={"code": LOCAL_CODE})
    assert _claim() is True
    try:
      response = client.post(
        "/api/finish", headers=SAME_ORIGIN, json={"outcome": "recovered"}
      )
      assert response.status_code == 409
      assert response.json()["error"]["code"] == "turn_active"
      assert client.get("/api/providers").status_code == 200
    finally:
      _release()


def test_local_finish_lands_on_closed_state_with_launcher_instruction(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    client.post("/session/start", data={"code": LOCAL_CODE})
    finished = client.post(
      "/api/finish", headers=SAME_ORIGIN, json={"outcome": "recovered"}
    )
    assert finished.status_code == 200
    page = client.get("/")
    assert "Recovery finished." in page.text
    assert "scripts/mobiusctl recovery finish" in page.text
    assert "one-time recovery code" not in page.text.lower()


def test_sse_emits_keepalive_while_provider_is_silent() -> None:
  async def delayed():
    await asyncio.sleep(0.04)
    yield {"type": "text", "content": "done"}

  async def collect() -> list[str]:
    return [frame async for frame in _sse_events(delayed(), keepalive=0.01)]

  frames = asyncio.run(collect())
  assert frames[0] == ": keepalive\n\n"
  assert sum(frame == ": keepalive\n\n" for frame in frames) >= 2
  assert '"content":"done"' in frames[-1]
