# mobius-recovery

The frozen, root-owned recovery surface for [Möbius OS](https://github.com/mobius-os).

**Status: stub.** This repo is reserved for the carve-out of the
recovery code currently bundled inside the `mobius` repo at
`backend/app/recover_*.py`. The carve-out is tracked under feature
ticket 056 (currently parked while focus is on the app store).

## What this will become

When 056 lands, this repo will contain the entire recovery surface:

- `recover_chat.py`, `recover_chat_runner.py` — minimal chat agent
  for users to recover from broken state
- `recover_oauth.py` — OAuth flow for connecting Claude / Codex
  during recovery (independent of the main settings flow)
- `recover_auth.py` — session management for the `/recover/` page
- `recover_html.py` — inline HTML/CSS for the recovery dashboard
- A minimal entrypoint script that runs as root for refreshes

Möbius will clone this repo into `/app/recovery/` at container build
time. The update button on `/recover/` does `git fetch + reset --hard
origin/main` as root — recovery is non-editable by the agent, so
updates are mechanical (no merge resolution needed).

## Why a separate repo

Different update semantics from the rest of Möbius (mechanical reset
vs. agent-mediated rebase), different privilege (root vs. user),
different reliability requirements (must always work, even when the
rest of the platform is broken).

## License

MIT — see LICENSE.
