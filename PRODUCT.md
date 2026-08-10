# Product

## Purpose

Mobius Recovery gives the owner a temporary AI-assisted shell into one managed
Mobius instance when its normal interface is unavailable.

## Principles

- Never restart, redeploy, reconfigure, or write recovery state into Mobius.
- Create the recovery worker only on demand and remove it when the session ends.
- Bind authority in mobius.you; the worker and model cannot select a target.
- Keep Railway OAuth and SSH credentials in the launcher.
- Expose one familiar remote primitive—command execution over native SSH.
- Treat remote output as untrusted data and prefer reversible repairs.
- Fail closed on expiry, replay, identity drift, redirects, or oversized data.

## User flow

The owner opens Recovery from mobius.you, connects Claude or Codex, describes
the incident, reviews the repair, and finishes the session. A lost worker simply
requires a fresh launch and has no effect on the Mobius deployment.
