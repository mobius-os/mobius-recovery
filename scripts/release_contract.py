#!/usr/bin/env python3
"""Validate the mobius.you recovery-release HTTP contract for CI."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


JOB_ID_RE = re.compile(r"releasejob_[0-9a-f]{32}")
BUILD_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
JOB_PATH_PREFIX = "/internal/recovery/releases/jobs/"


class ContractError(ValueError):
  """The control-plane response does not match the release contract."""


def _load_object(path: str) -> dict[str, object]:
  try:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
  except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise ContractError("response is not readable JSON") from exc
  if not isinstance(value, dict):
    raise ContractError("response must be a JSON object")
  return value


def _integer(value: object, name: str) -> int:
  if isinstance(value, bool) or not isinstance(value, int) or value < 0:
    raise ContractError(f"{name} must be a non-negative integer")
  return value


def _release_base(base_url: str) -> tuple[str, str]:
  parsed = urlsplit(base_url.strip())
  if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
  ):
    raise ContractError("release base URL must be an HTTPS origin with an optional path")
  base_path = parsed.path.rstrip("/")
  if "//" in base_path or any(part in {".", ".."} for part in base_path.split("/")):
    raise ContractError("release base URL has an unsafe path")
  origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
  return origin, base_path


def validate_acceptance(
  body: dict[str, object],
  *,
  base_url: str,
  sequence: int,
  build_sha: str,
  image_digest: str,
) -> tuple[str, str]:
  if body.get("status") != "accepted":
    raise ContractError("publish response status is not accepted")
  response_sequence = body.get("release_sequence")
  if (
    isinstance(response_sequence, bool)
    or not isinstance(response_sequence, int)
    or response_sequence != sequence
  ):
    raise ContractError("publish response release_sequence does not match")
  if body.get("build_sha") != build_sha:
    raise ContractError("publish response build_sha does not match")
  if body.get("image_digest") != image_digest:
    raise ContractError("publish response image_digest does not match")

  job_id = body.get("job_id")
  if not isinstance(job_id, str) or JOB_ID_RE.fullmatch(job_id) is None:
    raise ContractError("publish response job_id is invalid")
  _integer(body.get("total"), "total")

  status_url = body.get("status_url")
  if not isinstance(status_url, str) or not status_url:
    raise ContractError("publish response status_url is invalid")
  origin, base_path = _release_base(base_url)
  expected_path = f"{base_path}{JOB_PATH_PREFIX}{job_id}"
  parsed_status = urlsplit(status_url)
  if parsed_status.query or parsed_status.fragment:
    raise ContractError("publish response status_url must not have a query or fragment")
  if parsed_status.scheme or parsed_status.netloc:
    if (
      parsed_status.scheme != "https"
      or urlunsplit((parsed_status.scheme, parsed_status.netloc, "", "", "")) != origin
    ):
      raise ContractError("publish response status_url changed origin")
  if parsed_status.path != expected_path:
    raise ContractError("publish response status_url does not match job_id")

  return job_id, f"{origin}{expected_path}"


def validate_job_status(
  body: dict[str, object],
  *,
  job_id: str,
  sequence: int,
) -> str:
  if body.get("job_id") != job_id:
    raise ContractError("job response job_id does not match")
  response_sequence = body.get("release_sequence")
  if (
    isinstance(response_sequence, bool)
    or not isinstance(response_sequence, int)
    or response_sequence != sequence
  ):
    raise ContractError("job response release_sequence does not match")
  total = _integer(body.get("total"), "total")
  completed = _integer(body.get("completed"), "completed")
  failed = _integer(body.get("failed"), "failed")
  deferred = _integer(body.get("deferred"), "deferred")
  succeeded = _integer(body.get("succeeded"), "succeeded")
  failures = body.get("failures")
  deferred_instances = body.get("deferred_instances")
  if not isinstance(failures, list) or not isinstance(deferred_instances, list):
    raise ContractError("job response detail lists are invalid")
  if failures:
    raise ContractError("release reconciliation returned failure details")
  if len(deferred_instances) != deferred:
    raise ContractError("job response deferred details do not match count")
  if failed > completed or succeeded != completed - failed:
    raise ContractError("job response completion counts are inconsistent")
  if completed + deferred > total:
    raise ContractError("job response counts exceed total")
  if failed:
    raise ContractError(f"release reconciliation reported {failed} failure(s)")

  status = body.get("status")
  if status in {"queued", "running"}:
    return "pending"
  if status == "completed":
    if completed != total:
      raise ContractError("completed job has incomplete work")
    return "success"
  if status == "waiting":
    if completed + deferred != total:
      raise ContractError("waiting job has unaccounted work")
    return "success"
  raise ContractError(f"unexpected release job status: {status!r}")


def _parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser()
  commands = parser.add_subparsers(dest="command", required=True)

  accepted = commands.add_parser("acceptance")
  accepted.add_argument("--response", required=True)
  accepted.add_argument("--base-url", required=True)
  accepted.add_argument("--sequence", required=True, type=int)
  accepted.add_argument("--build-sha", required=True)
  accepted.add_argument("--image-digest", required=True)

  status = commands.add_parser("status")
  status.add_argument("--response", required=True)
  status.add_argument("--job-id", required=True)
  status.add_argument("--sequence", required=True, type=int)
  return parser


def main(argv: list[str] | None = None) -> int:
  args = _parser().parse_args(argv)
  try:
    body = _load_object(args.response)
    if args.command == "acceptance":
      if BUILD_SHA_RE.fullmatch(args.build_sha) is None:
        raise ContractError("expected build SHA is invalid")
      if DIGEST_RE.fullmatch(args.image_digest) is None:
        raise ContractError("expected image digest is invalid")
      if args.sequence <= 0:
        raise ContractError("expected release sequence is invalid")
      job_id, status_url = validate_acceptance(
        body,
        base_url=args.base_url,
        sequence=args.sequence,
        build_sha=args.build_sha,
        image_digest=args.image_digest,
      )
      print(job_id)
      print(status_url)
    else:
      if JOB_ID_RE.fullmatch(args.job_id) is None:
        raise ContractError("expected job ID is invalid")
      if args.sequence <= 0:
        raise ContractError("expected job identity is invalid")
      print(
        validate_job_status(
          body,
          job_id=args.job_id,
          sequence=args.sequence,
        )
      )
  except ContractError as exc:
    print(f"release contract violation: {exc}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
