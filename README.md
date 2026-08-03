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
- an agent-facing self-update, deployment, target selector, or image-management
  interface;
- the target bearer in a provider subprocess environment.

Managed mode exposes authenticated controller-only
`POST /internal/target/verify` and `POST /internal/target/revoke`. Verify binds
the exact private target supplied by mobius.you. Revoke can close only the
supplied signed target capability and returns target-authenticated identity;
neither route is agent-facing or returns a target credential.

The container runs as uid/gid `10001:10001`. `/app` and the target-client wrapper
are root-owned and non-writable. Every activation gets an unpredictable
mode-`0700` workspace which is also the provider subprocess `HOME`; replacement,
expiry, and finish destroy it together with both providers' state. Browser
sessions and chat history remain process-local. In managed deployments, `/state`
is ephemeral container-local storage; the self-hosted launcher mounts `/state`
as tmpfs. Neither is application data. A same-container process restart revokes
the in-memory session, but is not the freshness or cleanup contract: mobius.you
force-deploys the approved immutable digest before every managed open, while
`mobiusctl` pulls `stable` and recreates the worker and its tmpfs before every
self-hosted open or reopen.

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
argument. `mobius-target` is the human-readable client for that broker. Its
launcher uses Python isolated mode and inserts only the immutable `/app` import
root, so a writable session cwd, `PYTHONPATH`, or old project memory cannot
replace the target client.
File reads and listings are lexically restricted to `/data`, `/app`, and `/tmp`;
writes are restricted to `/data` and `/tmp`. The target independently enforces
the same roots with beneath/no-magic-link filesystem resolution. Root repair
outside those convenience roots remains possible only through the explicit
`exec` operation.

The same-uid boundary does not protect a provider credential from that provider
itself. After the owner authorizes Claude or Codex, its model-controlled Bash or
other tool execution can read that CLI's own ephemeral OAuth credential beneath
the session `HOME`. Treat that credential as inside the agent session's trust
boundary. The remote target bearer, managed bootstrap and control capabilities
remain in the non-dumpable PID 1 process and outside provider environments and
files; Railway credentials never enter the worker. Use a dedicated,
short-lived, narrowly scoped, and readily revocable provider authorization when
the provider supports one. Finish the session to trigger the credential wipe
and revoke the authorization after recovery when appropriate; wiping cannot
invalidate a token that was copied before cleanup.

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
`target_token_sha256`, `session_capability`, and RFC3339 `expires_at`. All are
ephemeral. Finishing starts generation `1` and posts the session capability with
`{"session_id":"...","outcome":"recovered|cancelled","generation":1}`.
Before that first blocking request, the worker claims a process-wide finish
gate. For a live normal-mode target it first asks the active broker to revoke
the signed target session and requires the target's exact confirmation. It then
stops the broker and provider processes, deletes their workspace/state, and
clears its target bearer. A revoke failure keeps local access closed and
prevents the controller finish from being committed. Legacy recovery-mode
targets have no per-session revoke and retain their existing container-close
flow. Browser cancellation or a lost response cannot reopen the local boundary.
The worker retains only the finish capability and polls the authenticated
`status_url`; reloading the page continues that poll without restoring target
access. Every queued, running, failed, resumed, or finished result carries its
exact generation.
The browser also echoes the generation rendered into its page, so a delayed
request from a pre-resume page can observe generation `2` but cannot start it.

A successful result erases the session. Only `503 resumed` with
`normal_boot_failed` may carry a fresh, preflight-bound target and
`next_generation = generation + 1`. The worker installs both atomically before
restarting the broker, clears the finish gate, and requires the next finish to
use that new generation. Late responses from an older generation are discarded
and their bearer is erased. Any other definitive rejection or terminal failure
is represented as `failed` and remains fail-closed until the session expires or
the owner opens a new Recovery launch.
Mobius.you compares the baked build identity and its recorded deployed image
digest with the latest durable release inside the same transaction that consumes
the code, so an older process cannot win a launch-time release race.
The controller retains an encrypted, short-lived exchange receipt so the worker
can safely retry the identical request once if a committed response is lost.
Only after the parsed session is in the worker's in-memory store does it call
authenticated `POST /recovery/exchange/ack`; ACK itself is idempotent and retried
once on transport loss.

If normal boot fails again after further repair, the same generation transition
can repeat; each attempt has a distinct idempotency generation and a newly
preflighted capability.

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
data. Revocation on process loss is distinct from artifact freshness: before
each open, mobius.you force-deploys the currently approved immutable image
digest and waits for that deployment to verify. Railway should run the service
with serverless sleep enabled and use the external `/health` endpoint to wake
it; sleeping therefore does not pin an old recovery build.

Before mobius.you sends a launch form, it verifies the newly deployed worker
against the intended private target:

```http
POST /internal/target/verify
Authorization: Bearer <bootstrap secret>
Content-Type: application/json

{"target_url":"http://<service>.railway.internal:18002","target_token":"..."}
```

The worker accepts only the canonical single-service form
`http://*.railway.internal:18002` (no trailing path, credentials, query, or
fragment), disables redirects and process proxy variables, and requires the v1
target identity. A managed target may be a live normal-mode attachment or a
legacy recovery-mode target. A successful probe records a short-lived one-use
keyed binding of that exact URL and bearer. Exchange and resume responses must
advertise the bearer SHA-256 and consume the matching binding; an unprobed URL,
wrong bearer/hash, replay, or expired binding is rejected before a broker can
start. This authenticated controller route is the only managed target-binding
surface; neither the browser nor the provider agent receives a selector or its
bootstrap secret.

The launcher dashboard can close a live target without an active browser by
posting the same exact URL and signed bearer to bootstrap-authenticated
`POST /internal/target/revoke`. The worker calls target `POST /v1/revoke`
directly and returns only the target-authenticated
`status`, `deployment_id`, and `session_id`, which the launcher can use for a
stale-state compare-and-set. It does not create or replace an exchange preflight
binding, and the revoke operation is absent from the broker and agent schemas.

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
Restarting either recovery process invalidates the launch. Use `mobiusctl`
again: it pulls the current `stable` image, recreates the worker and `/state`
tmpfs, and mints a fresh target bearer and owner code. Restart alone is not a
substitute for that recreate path. Unlike managed mode, the local worker accepts
only a target in strict recovery mode.

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
| `POST /v1/revoke` | empty object; live signed session returns `status`, `deployment_id`, `session_id` |
| `POST /v1/exec` | `argv`, optional `cwd`, `env`, `stdin`/`stdin_base64`, timeout 1–900s |
| `POST /v1/fs/read` | absolute `path`, `offset`, `limit` (maximum 8 MiB) |
| `POST /v1/fs/write` | absolute `path`, base64 data, optional mode, atomic flag |
| `POST /v1/fs/list` | absolute `path`, at most 10,000 entries |

The client bounds remote JSON at 16 MiB, revoke confirmation at 16 KiB, and
stdout/stderr at 4 MiB each. Remote output is treated as hostile data in the
recovery agent prompt.

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
cannot spoof it. Both base images, every GitHub Action, the full Python test
closure, and the npm provider-CLI dependency graph are digest/integrity locked;
the npm install scripts are disabled and only the verified native binaries are
copied into the runtime. CI tests the worker, builds one amd64 image, runs the
container security probe, then publishes that exact image under the never-reused
`sha-<commit>-run-<run>-attempt-<attempt>` tag. On `main`, the workflow first
advances mobius.you's durable approved digest using a sequence derived from both
run and attempt. The hook must return `202 accepted` with the exact sequence,
SHA, digest, and a matching reconciliation job identity; only that response may
move `stable`. CI rechecks `origin/main` before every hook attempt. Once the ref
has advanced it sends `require_existing: true`, so a crash-restarted old run may
resume an exact release that mobius.you already committed but cannot introduce
an old release for the first time. `release_not_current` cleanly skips that stale
attempt.

After exact durable acceptance, CI always promotes that same digest to `stable`,
even if `main` advances in the meantime. This keeps managed launches and
self-hosted pulls on one release identity. It then polls the returned job URL
with the release bearer. The run succeeds only when every item completed without
failure, or every unfinished item is explicitly deferred by an active recovery;
other terminal states and partial or failed counts fail the release. A rerun is
therefore crash-safe across acceptance, stable promotion, and reconciliation.
Mobius.you deploys the approved digest and checks its baked SHA before issuing a
session. Recovery has no updater: a new release replaces its container from
outside. Missing webhook credentials, exhausted fence retries, and failed job
polls fail the release rather than silently declaring it healthy.
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
pip install --require-hashes -r requirements-dev.lock
python -m pytest

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
