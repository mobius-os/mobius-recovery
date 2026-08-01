# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is the owner of a managed or self-hosted Mobius instance that
is unavailable or damaged. They need to diagnose and repair their own instance
while its normal interface and agent may be unusable.

## Product Purpose

Mobius Recovery provides an independently deployed AI repair session with a
full-power capability fixed to one target. Success means the owner can repair
and verify that target without giving the recovery agent any way to edit or
redeploy the recovery worker itself.

## Positioning

The worker combines an immutable, unprivileged control surface with a
short-lived, target-bound repair capability. Privilege exists only across the
versioned target protocol, never in the worker container.

## Operating Context

Managed sessions are opened from mobius.you and run in a sleeping Railway
service inside the instance's project. Self-hosted sessions use the same image,
a locally generated one-time token, and a private repair target. The owner may
need to reconnect Claude or Codex during the incident.

## Capabilities and Constraints

- One-time owner authentication and an expiring browser session.
- Claude and Codex provider login and recovery chat.
- Remote health, command, read, write, and list operations through
  `mobius-recovery-target/v1`.
- A narrow finish callback that cannot select or mutate the recovery service.
- No Railway token, Docker socket, sudo, setuid program, persistent code, or
  self-update mechanism in the worker.
- Provider credentials and chat history are ephemeral.
- A visible managed recovery page keeps its in-memory worker awake; hidden or
  closed pages permit sleep, and a restarted process requires a fresh launch.

## Brand Commitments

Use the Mobius name, direct incident-focused language, and the restrained
neutral shell with purple accent established by the main product.

## Evidence on Hand

The repository contains the executable protocol client and security tests.
There are no customer claims, benchmarks, or recovery guarantees to present.

## Product Principles

- Preserve the owner's agency while making every repair reversible.
- Keep privilege in the target capability, outside the recovery worker.
- Name current state and the next action plainly during an incident.
- Fail closed on stale, replayed, mismatched, or oversized protocol data.

## Accessibility & Inclusion

The recovery flow must remain keyboard usable, screen-reader legible, responsive
on phones, and respectful of reduced-motion preferences.
