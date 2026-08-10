# Mobius Recovery Worker

Mobius Recovery is a temporary, unprivileged web process for repairing one
managed Mobius instance. Mobius itself does not run a recovery daemon. The
worker sends commands to mobius.you, which executes them through Railway's
native SSH endpoint using the owner's OAuth connection and a launcher-held SSH
key.

## Trust boundary

- mobius.you creates the worker only when the owner opens Recovery.
- A one-time browser handoff becomes one expiring session capability.
- The capability is bound server-side to one instance, service instance, and
  deployment. The worker cannot supply or change any of those identifiers.
- Provider subprocesses see only a mode-`0600` Unix socket with one operation:
  execute a command in the bound Mobius container.
- Railway OAuth tokens, SSH keys, and the session capability remain in parent
  processes. They are never passed to Claude or Codex.
- The worker runs as uid/gid `10001:10001`, has immutable application code,
  ephemeral state, no volume, no Railway CLI, no Docker socket, no `sudo`, and
  no self-update or deployment API.

The agent-facing command is:

```sh
mobius-ssh -- /bin/bash -lc 'COMMAND'
```

It has no host, project, service, or target selector. Reads and writes use
ordinary commands over the same SSH session. Input and output are bounded,
HTTP redirects and process proxy variables are disabled, and the launcher pins
Railway's SSH host key.

## Lifecycle

1. mobius.you verifies the owner's OAuth connection has `ssh_keys`, registers a
   per-connection public key, and creates a fresh worker service.
2. The launcher verifies root access to the exact current Mobius service
   instance without restarting or changing that service.
3. The browser exchanges its one-time handoff with the worker. The worker keeps
   its short-lived command capability in memory and starts the local socket.
4. Finishing or expiry stops provider processes, removes temporary files,
   revokes the session, and asks mobius.you to delete the temporary service.

There is no recovery boot mode, target protocol, crash-loop counter, recovery
volume mutation, or resume generation. If a worker disappears, open Recovery
again; Mobius continues running unchanged.

## Configuration

The launcher supplies four values to each worker:

```text
MOBIUS_RECOVERY_CONTROL_PLANE_URL
MOBIUS_RECOVERY_INSTANCE_ID
MOBIUS_RECOVERY_SERVICE_ID
MOBIUS_RECOVERY_BOOTSTRAP_SECRET
```

The worker accepts no local-mode or target URL/token settings. Self-hosted
operators repair directly with `docker compose exec -u 0 app bash`.

## Development

```sh
python -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock
pytest
docker build --build-arg VCS_REF=development -t mobius-recovery:dev .
scripts/verify-image.sh mobius-recovery:dev development
```

`GET /health` reports the baked image revision and protocol version. CI tests
the code, builds once, verifies that exact image, publishes an immutable commit
tag, and advances `stable` from `main`. No fleet reconciliation is needed
because workers do not exist between sessions.
