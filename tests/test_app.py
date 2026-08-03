from __future__ import annotations

import asyncio
import hashlib
import threading
import time
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
MANAGED_TARGET_URL = "http://mobius.railway.internal:18002"
SAME_ORIGIN = {
  "Origin": "http://testserver",
  "Sec-Fetch-Site": "same-origin",
}
MANAGED_HANDOFF = {
  "Origin": "https://mobius.you",
  "Sec-Fetch-Site": "cross-site",
}


def _target_token_sha256(token: str) -> str:
  return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _record_managed_preflight(app) -> None:
  app.state.preflight_bindings.record(
    TargetCapability(MANAGED_TARGET_URL, TARGET_TOKEN)
  )


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
  if request.url.path == "/v1/revoke":
    return httpx.Response(200, json={
      "status": "revoked",
      "deployment_id": "deployment-test",
      "session_id": "session-test",
    })
  mode = "normal" if request.url.host.endswith(".railway.internal") else "recovery"
  return httpx.Response(200, json={
    "status": "ready",
    "protocol": TARGET_PROTOCOL_VERSION,
    "target": "mobius",
    "target_id": "local",
    "mode": mode,
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
      "/session/start", data={"code": "wrong"}, headers=SAME_ORIGIN,
      follow_redirects=False,
    )
    assert wrong.status_code == 401
    started = client.post(
      "/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN,
      follow_redirects=False,
    )
    assert started.status_code == 200
    assert "HttpOnly" in started.headers["set-cookie"]
    assert "SameSite=strict" in started.headers["set-cookie"]
    assert client.get("/api/providers").status_code == 200
    replay = client.post(
      "/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN,
      follow_redirects=False,
    )
    assert replay.status_code == 401


def test_local_same_origin_launch_returns_page_without_code_url(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    started = client.post(
      "/session/start",
      data={"code": LOCAL_CODE},
      headers=SAME_ORIGIN,
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


def test_local_launch_rejects_missing_and_cross_site_browser_metadata(
  tmp_path,
) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    missing = client.post("/session/start", data={"code": LOCAL_CODE})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "cross_site"
    hostile = client.post(
      "/session/start",
      data={"code": LOCAL_CODE},
      headers={
        "Origin": "https://hostile.example",
        "Sec-Fetch-Site": "cross-site",
      },
    )
    assert hostile.status_code == 403
    valid = client.post(
      "/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN
    )
    assert valid.status_code == 200


def test_managed_launch_accepts_only_exact_control_plane_handoff(tmp_path) -> None:
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
  control_calls = 0

  def control(request: httpx.Request) -> httpx.Response:
    nonlocal control_calls
    control_calls += 1
    if request.url.path == "/recovery/exchange/ack":
      return httpx.Response(200, json={
        "status": "acknowledged", "session_id": "managed-origin"
      })
    return httpx.Response(200, json={
      "session_id": "managed-origin",
      "target_url": MANAGED_TARGET_URL,
      "target_token": TARGET_TOKEN,
      "target_token_sha256": _target_token_sha256(TARGET_TOKEN),
      "session_capability": "finish-" + "f" * 40,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  app = create_app(
    settings,
    control_transport=httpx.MockTransport(control),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "managed" / "target.sock",
  )
  _record_managed_preflight(app)
  body = {"code": "managed-code", "instance_id": "mob_instance-1"}
  with TestClient(app, base_url="https://recovery.example") as client:
    assert client.post("/session/start", data=body).status_code == 403
    assert client.post(
      "/session/start",
      data=body,
      headers={
        "Origin": "https://hostile.example",
        "Sec-Fetch-Site": "cross-site",
      },
    ).status_code == 403
    assert client.post(
      "/session/start",
      data=body,
      headers={"Origin": "https://mobius.you"},
    ).status_code == 403
    assert control_calls == 0
    accepted = client.post(
      "/session/start", data=body, headers=MANAGED_HANDOFF
    )
    assert accepted.status_code == 200
    assert control_calls == 2


def test_managed_process_loss_requires_fresh_launch(tmp_path) -> None:
  settings = Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
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
    client.post("/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN)
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
      "/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN,
      follow_redirects=False,
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
    if request.url.path == "/recovery/exchange/ack":
      return httpx.Response(200, json={
        "status": "acknowledged", "session_id": "managed-session"
      })
    assert request.url.path == "/recovery/exchange"
    return httpx.Response(200, json={
      "session_id": "managed-session",
      "target_url": MANAGED_TARGET_URL,
      "target_token": TARGET_TOKEN,
      "target_token_sha256": _target_token_sha256(TARGET_TOKEN),
      "session_capability": "finish-" + "f" * 40,
      "expires_at": expiry,
    })

  settings = Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
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
  _record_managed_preflight(app)
  with TestClient(app, base_url="https://recovery.example") as client:
    started = client.post(
      "/session/start",
      data={"code": "managed-code", "instance_id": "mob_instance-1"},
      headers=MANAGED_HANDOFF,
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
    oversized = client.post(
      "/session/start", data={"code": "x" * 17000}, headers=SAME_ORIGIN
    )
    assert oversized.status_code == 413

    def chunks():
      yield b"code="
      yield b"x" * 17000

    chunked = client.post(
      "/session/start",
      content=chunks(),
      headers={
        **SAME_ORIGIN,
        "Content-Type": "application/x-www-form-urlencoded",
      },
    )
    assert chunked.status_code == 413
    multipart = client.post(
      "/session/start",
      files={"code": (None, LOCAL_CODE)},
      headers=SAME_ORIGIN,
    )
    assert multipart.status_code == 415


def test_finish_is_rejected_while_recovery_stream_owns_turn(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    started = client.post(
      "/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN
    )
    assert "const initialGeneration=1;" in started.text
    missing_generation = client.post(
      "/api/finish", headers=SAME_ORIGIN, json={"outcome": "recovered"}
    )
    assert missing_generation.status_code == 400
    assert missing_generation.json()["error"]["code"] == "invalid_generation"
    assert _claim() is True
    try:
      response = client.post(
        "/api/finish", headers=SAME_ORIGIN,
        json={"outcome": "recovered", "generation": 1}
      )
      assert response.status_code == 409
      assert response.json()["error"]["code"] == "turn_active"
      assert client.get("/api/providers").status_code == 200
    finally:
      _release()


def test_managed_finish_freezes_target_and_survives_reload_and_poll_loss(
  tmp_path,
) -> None:
  expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
  status_calls = 0
  target_calls = 0

  def control(request: httpx.Request) -> httpx.Response:
    nonlocal status_calls
    if request.url.path == "/recovery/exchange":
      return httpx.Response(200, json={
        "session_id": "managed-finish-session",
        "target_url": MANAGED_TARGET_URL,
        "target_token": TARGET_TOKEN,
        "target_token_sha256": _target_token_sha256(TARGET_TOKEN),
        "session_capability": "finish-" + "f" * 40,
        "expires_at": expiry,
      })
    if request.url.path == "/recovery/exchange/ack":
      return httpx.Response(200, json={
        "status": "acknowledged", "session_id": "managed-finish-session"
      })
    if request.method == "POST":
      return httpx.Response(202, json={
        "finish_id": "finish_managed-1",
        "session_id": "managed-finish-session",
        "status": "queued",
        "outcome": "recovered",
        "generation": 1,
        "status_url": "/recovery/finish/finish_managed-1",
      })
    status_calls += 1
    if status_calls <= 2:
      raise httpx.ReadTimeout("temporary poll loss", request=request)
    return httpx.Response(200, json={
      "finish_id": "finish_managed-1",
      "session_id": "managed-finish-session",
      "status": "finished",
      "outcome": "recovered",
      "generation": 1,
      "status_url": "/recovery/finish/finish_managed-1",
    })

  def counted_target(request: httpx.Request) -> httpx.Response:
    nonlocal target_calls
    target_calls += 1
    return target(request)

  settings = Settings(
    port=8000,
    build_sha=baked_build_revision(),
    service_id="recovery-service",
    secure_cookie=True,
    control_plane_url="https://mobius.you",
    instance_id="mob_instance-1",
    bootstrap_secret="bootstrap-" + "b" * 32,
    local_target_url=None,
    local_target_token=None,
    local_token=None,
  )
  broker_path = tmp_path / "finish" / "target.sock"
  app = create_app(
    settings,
    control_transport=httpx.MockTransport(control),
    target_transport=httpx.MockTransport(counted_target),
    broker_path=broker_path,
  )
  _record_managed_preflight(app)
  with TestClient(app, base_url="https://recovery.example") as client:
    started = client.post(
      "/session/start",
      data={"code": "managed-code", "instance_id": "mob_instance-1"},
      headers=MANAGED_HANDOFF,
    )
    assert started.status_code == 200
    accepted = client.post(
      "/api/finish",
      headers={
        "Origin": "https://recovery.example",
        "Sec-Fetch-Site": "same-origin",
      },
      json={"outcome": "recovered", "generation": 1},
    )
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    assert not broker_path.exists()
    session = next(iter(app.state.sessions._sessions.values()))
    assert session.finishing
    assert session.target.token == ""
    target_calls_at_quiesce = target_calls

    frozen_target = client.get("/api/target/health")
    assert frozen_target.status_code == 409
    assert frozen_target.json()["error"]["code"] == "finish_in_progress"
    frozen_chat = client.post(
      "/api/chat/stream",
      headers={
        "Origin": "https://recovery.example",
        "Sec-Fetch-Site": "same-origin",
      },
      json={"message": "mutate after finish", "provider": "claude"},
    )
    assert frozen_chat.status_code == 409
    assert target_calls == target_calls_at_quiesce

    reloaded = client.get("/")
    assert "const initialFinishing=true;" in reloaded.text
    transient = client.get("/api/finish/status")
    assert transient.status_code == 202
    assert transient.json()["status"] == "queued"
    assert client.get("/").status_code == 200

    finished = client.get("/api/finish/status")
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"
    closed = client.get("/")
    assert "Recovery finished." in closed.text
    assert target_calls == target_calls_at_quiesce


def test_local_finish_lands_on_closed_state_with_launcher_instruction(tmp_path) -> None:
  app = create_app(
    local_settings(),
    target_transport=httpx.MockTransport(target),
    broker_path=tmp_path / "broker" / "target.sock",
  )
  with TestClient(app) as client:
    client.post("/session/start", data={"code": LOCAL_CODE}, headers=SAME_ORIGIN)
    finished = client.post(
      "/api/finish", headers=SAME_ORIGIN,
      json={"outcome": "recovered", "generation": 1}
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


def test_health_stays_responsive_during_slow_sync_integrations(tmp_path) -> None:
  async def exercise(kind: str) -> None:
    entered = threading.Event()

    def slow() -> None:
      entered.set()
      time.sleep(0.4)

    if kind == "control":
      expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()

      def control(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recovery/exchange/ack":
          return httpx.Response(200, json={
            "status": "acknowledged", "session_id": "managed-session"
          })
        slow()
        return httpx.Response(200, json={
          "session_id": "managed-session",
          "target_url": MANAGED_TARGET_URL,
          "target_token": TARGET_TOKEN,
          "target_token_sha256": _target_token_sha256(TARGET_TOKEN),
          "session_capability": "finish-" + "f" * 40,
          "expires_at": expiry,
        })

      settings = Settings(
        port=8000,
        build_sha=baked_build_revision(),
        service_id="recovery-service",
        secure_cookie=True,
        control_plane_url="https://mobius.you",
        instance_id="mob_instance-1",
        bootstrap_secret="bootstrap-" + "b" * 32,
        local_target_url=None,
        local_target_token=None,
        local_token=None,
      )
      app = create_app(
        settings,
        control_transport=httpx.MockTransport(control),
        target_transport=httpx.MockTransport(target),
        broker_path=tmp_path / kind / "target.sock",
      )
      _record_managed_preflight(app)
      launch = {"code": "managed-code", "instance_id": "mob_instance-1"}
    else:
      def target_transport(request: httpx.Request) -> httpx.Response:
        if kind == "target":
          slow()
        return target(request)

      app = create_app(
        local_settings(),
        target_transport=httpx.MockTransport(target_transport),
        broker_path=tmp_path / kind / "target.sock",
      )
      launch = {"code": LOCAL_CODE}

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
      async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
      ) as client:
        if kind == "provider":
          started = await client.post(
            "/session/start", data=launch, headers=SAME_ORIGIN
          )
          assert started.status_code == 200

          def provider_start() -> dict:
            slow()
            return {"auth_url": "https://provider.invalid/auth"}

          app.state.providers.claude_start = provider_start
          request = client.post(
            "/api/providers/claude/start", headers=SAME_ORIGIN
          )
        else:
          request = client.post(
            "/session/start",
            data=launch,
            headers=MANAGED_HANDOFF if kind == "control" else SAME_ORIGIN,
          )

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        pending = asyncio.create_task(request)
        assert await asyncio.to_thread(entered.wait, 2)
        health = await client.get("/health")
        elapsed = loop.time() - started_at
        assert health.status_code == 200
        assert elapsed < 0.25, f"{kind} blocked the event loop for {elapsed:.3f}s"
        assert (await pending).status_code == 200

  for kind in ("target", "control", "provider"):
    asyncio.run(exercise(kind))
