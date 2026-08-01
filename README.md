# Mobius Recovery Worker

The standalone recovery surface for [Mobius](https://github.com/mobius-os/mobius).
It is an on-demand, non-root service that gives an AI agent a short-lived repair
capability for exactly one Mobius target without giving it any way to edit or
redeploy recovery itself.

## Boundary

The worker image contains the web UI, Claude and Codex CLIs, and a versioned
target client. It deliberately contains none of the following:

- `sudo`, setuid programs, a Docker socket, or a Railway credential;
- a writable or persistent code mount;
- a self-update, deployment, target-selection, or image-management endpoint;
- the target bearer in a provider subprocess environment.

The container runs as uid/gid `10001:10001`. `/app` and the target-client wrapper
are root-owned and non-writable. Provider credentials, browser sessions, and chat
history live only in process memory or `/state`; production mounts `/state` as an
ephemeral volume/tmpfs and never as application data.

The Python worker must be container PID 1. Do not enable Docker/Compose `init`
or place a same-uid process wrapper in front of it: such a wrapper would retain
the original secret-bearing environment outside Python's process hardening, so
the worker refuses to start in that layout. The image intentionally declares no
Docker `HEALTHCHECK`, because health probes would also inherit container secrets;
platforms must probe the public HTTP `/health` endpoint from outside the
container.

The parent process owns the remote target bearer. Claude and Codex see only a
mode-`0600` Unix socket beneath a mode-`0700` directory. The socket broker offers
the five fixed target operations but no URL, token, instance, service, or host
argument. `mobius-target` is the human-readable client for that broker.
File reads and listings are lexically restricted to `/data`, `/app`, and `/tmp`;
writes are restricted to `/data` and `/tmp`. The target independently enforces
the same roots with beneath/no-magic-link filesystem resolution. Root repair
outside those convenience roots remains possible only through the explicit
`exec` operation.

## Session flows

### Managed by mobius.you

The Railway service receives:

```text
MOBIUS_RECOVERY_CONTROL_PLANE_URL
MOBIUS_RECOVERY_INSTANCE_ID
MOBIUS_RECOVERY_SERVICE_ID
MOBIUS_RECOVERY_BOOTSTRAP_SECRET
```

Mobius.you submits a one-time `code` and `instance_id` to `/session/start`. The
worker accepts that cross-origin browser form only when `Origin` exactly matches
its configured HTTPS control-plane origin and browser fetch metadata is present;
rejected origins never consume the launch limiter. The worker then calls:

```http
POST /recovery/exchange
Content-Type: application/json

{
  "code": "...",
  "instance_id": "...",
  "service_id": "...",
  "bootstrap_secret": "...",
  "protocol_version": "mobius-recovery-worker/v1",
  "build_sha": "<baked git commit>"
}
```

The response supplies `session_id`, `target_url`, `target_token`,
`session_capability`, and RFC3339 `expires_at`. All are ephemeral. Finishing
starts an idempotent job with `POST /recovery/finish`, the session capability,
and `{"session_id":"...","outcome":"recovered|cancelled"}`. A `202` response
closes the broker and provider processes immediately. The worker retains only
the finish capability and polls the authenticated `status_url`; reloading the
page continues that poll without restoring target access. A successful result
erases the session. `normal_boot_failed` may return one fresh target capability,
which atomically resumes the same browser session.
Mobius.you compares the baked build identity and its recorded deployed image
digest with the latest durable release inside the same transaction that consumes
the code, so an older process cannot win a launch-time release race.
The controller retains an encrypted, short-lived exchange receipt so the worker
can safely retry the identical request once if a committed response is lost.
Only after the parsed session is in the worker's in-memory store does it call
authenticated `POST /recovery/exchange/ack`; ACK itself is idempotent and retried
once on transport loss.

If normal boot fails, mobius.you returns `503 normal_boot_failed` with a fresh
target capability. The worker atomically swaps its broker back to that target and
keeps the authenticated browser session open for continued repair.

While the recovery page is visible, it sends a small authenticated heartbeat
every 45 seconds so Railway Serverless does not suspend the process and erase its
ephemeral session. Hidden or closed pages stop heartbeating and may sleep. If a
laptop or platform sleep does restart the worker, the stale browser cookie opens
a clear fresh-launch screen instead of offering an already-consumed code; the
owner returns to mobius.you and opens Recovery again.

Run exactly one worker replica. Browser sessions, provider credentials, launch
limits, and the broker are intentionally process-local; replicas cannot share
them. A deploy, crash, Railway sleep, or host restart revokes the process's
sessions and requires a fresh launch from mobius.you. This does not alter target
data. Railway should run the service with serverless sleep enabled and use the
external `/health` endpoint to wake it; every launch is gated on the currently
approved immutable image digest, so sleeping does not pin an old recovery build.

Before mobius.you sends a launch form, it verifies the newly deployed worker
against the intended private target:

```http
POST /internal/target/verify
Authorization: Bearer <bootstrap secret>
Content-Type: application/json

{"target_url":"http://<service>.railway.internal:18002","target_token":"..."}
```

The worker accepts only an exact `http://*.railway.internal:18002` target,
disables redirects and process proxy variables, requires the v1 target identity,
and returns no target credential.

### Self-hosted

The local launcher supplies:

```text
MOBIUS_RECOVERY_TARGET_URL=http://recovery-target:18002
MOBIUS_RECOVERY_TARGET_TOKEN=<43+ character random capability>
MOBIUS_RECOVERY_LOCAL_TOKEN=<one-time owner code>
```

The owner enters the one-time code from the worker's own loopback page; local
launch forms require same-origin browser metadata. The code is consumed once.
Bind the worker to loopback or an authenticated tunnel; do not put a
local recovery port directly on the public Internet. The Mobius repository ships
the `mobiusctl recovery` launcher and matching target daemon, so a reverse proxy
or custom Caddy configuration is not required for the default loopback flow.
Restarting either recovery process invalidates the launch; rerun the launcher to
mint a fresh target bearer and owner code.

The paired Mobius image and its recovery target are currently amd64-only. The
worker Dockerfile fails fast for any other `TARGETARCH`; ARM support should be
published only when the core target image and this worker can be verified as one
multi-architecture pair.

## Target protocol

Every target endpoint requires `Authorization: Bearer <target token>`. Decoded
file/stdin data is capped at 8 MiB; the base64 JSON wire envelope is capped at
12 MiB. Errors use:

```json
{"error":{"code":"stable_machine_code","message":"Safe explanation"}}
```

| Endpoint | Body/result |
| --- | --- |
| `GET /v1/health` | `protocol: mobius-recovery-target/v1`, target identity and mode |
| `POST /v1/exec` | `argv`, optional `cwd`, `env`, `stdin`/`stdin_base64`, timeout 1–900s |
| `POST /v1/fs/read` | absolute `path`, `offset`, `limit` (maximum 8 MiB) |
| `POST /v1/fs/write` | absolute `path`, base64 data, optional mode, atomic flag |
| `POST /v1/fs/list` | absolute `path`, at most 10,000 entries |

The client bounds remote JSON at 16 MiB and stdout/stderr at 4 MiB each. Remote
output is treated as hostile data in the recovery agent prompt.

## Health and releases

`GET /health` is public so Railway can wake and verify the service:

```json
{
  "status": "ready",
  "build_sha": "<baked git commit>",
  "protocol_version": "mobius-recovery-worker/v1",
  "service_id": "<configured service>"
}
```

`build_sha` comes from a root-owned file created by the image build. Runtime env
cannot spoof it. CI tests the worker, builds one amd64 image, runs the container
security probe, then publishes that exact image under the never-reused
`sha-<commit>-run-<run>-attempt-<attempt>` tag. On `main`, the workflow first
advances mobius.you's durable approved digest using a sequence derived from both
run and attempt; only an accepted update may move `stable`. It checks `main` both
before approval and immediately before promotion. A rerun therefore cannot
overwrite an immutable artifact or let an older attempt move `stable`.
Mobius.you deploys the approved digest and checks its baked SHA before issuing a
session. Recovery has no updater: a new release replaces its container from
outside. Missing webhook credentials and exhausted webhook retries fail the
release rather than leaving the control plane stale.
Before the webhook is called, CI performs an anonymous registry inspection of
the exact immutable digest. It repeats that check against `stable` after
promotion. The GHCR package must therefore be made **public before the first
main-branch release**; a private first package intentionally stops at this gate
and never advances mobius.you. Subsequent pushes to `main` rebuild, verify, and
publish immediately—there is no long-lived updater inside the worker.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.lock
pip install -r requirements-dev.txt
pytest

docker build \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  --build-arg VERSION="$(cat VERSION)" \
  -t mobius-recovery:dev .
scripts/verify-image.sh mobius-recovery:dev "$(git rev-parse HEAD)"
```

Run locally with the three self-host variables above and publish port 8000 only
to loopback. Provider login requires outbound HTTPS.

## License

MIT — see [LICENSE](LICENSE).
