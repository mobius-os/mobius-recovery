from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
  "release_contract", ROOT / "scripts" / "release_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
release_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_contract)


JOB_ID = "releasejob_" + "a" * 32
SEQUENCE = 123_001
BUILD_SHA = "b" * 40
DIGEST = "sha256:" + "c" * 64


def accepted_body(**changes):
  body = {
    "status": "accepted",
    "release_sequence": SEQUENCE,
    "build_sha": BUILD_SHA,
    "image_digest": DIGEST,
    "job_id": JOB_ID,
    "total": 3,
    "status_url": f"/control/internal/recovery/releases/jobs/{JOB_ID}",
  }
  body.update(changes)
  return body


def job_body(**changes):
  body = {
    "job_id": JOB_ID,
    "release_sequence": SEQUENCE,
    "status": "running",
    "total": 3,
    "completed": 1,
    "succeeded": 1,
    "failed": 0,
    "deferred": 0,
    "failures": [],
    "deferred_instances": [],
  }
  body.update(changes)
  return body


def test_acceptance_requires_exact_identity_and_job_url():
  assert release_contract.validate_acceptance(
    accepted_body(),
    base_url="https://www.mobius.you/control/",
    sequence=SEQUENCE,
    build_sha=BUILD_SHA,
    image_digest=DIGEST,
  ) == (
    JOB_ID,
    f"https://www.mobius.you/control/internal/recovery/releases/jobs/{JOB_ID}",
  )

  for changed in (
    {"status": "queued"},
    {"release_sequence": SEQUENCE + 1},
    {"build_sha": "d" * 40},
    {"image_digest": "sha256:" + "e" * 64},
    {"job_id": "releasejob_unsafe"},
    {"status_url": f"/control/internal/recovery/releases/jobs/releasejob_{'f' * 32}"},
    {"status_url": f"https://example.test/control/internal/recovery/releases/jobs/{JOB_ID}"},
  ):
    with pytest.raises(release_contract.ContractError):
      release_contract.validate_acceptance(
        accepted_body(**changed),
        base_url="https://www.mobius.you/control",
        sequence=SEQUENCE,
        build_sha=BUILD_SHA,
        image_digest=DIGEST,
      )


def test_job_status_accepts_only_complete_or_fully_deferred_success():
  assert release_contract.validate_job_status(
    job_body(), job_id=JOB_ID, sequence=SEQUENCE
  ) == "pending"
  assert release_contract.validate_job_status(
    job_body(
      status="completed", completed=3, succeeded=3, failed=0, deferred=0
    ),
    job_id=JOB_ID,
    sequence=SEQUENCE,
  ) == "success"
  assert release_contract.validate_job_status(
    job_body(
      status="waiting", completed=1, succeeded=1, failed=0, deferred=2,
      deferred_instances=["instance-1", "instance-2"],
    ),
    job_id=JOB_ID,
    sequence=SEQUENCE,
  ) == "success"


@pytest.mark.parametrize(
  "changes",
  [
    {"status": "failed"},
    {"status": "completed", "completed": 2, "succeeded": 2},
    {"status": "waiting", "completed": 1, "succeeded": 1, "deferred": 1},
    {"status": "running", "completed": 1, "succeeded": 0, "failed": 1},
    {"status": "running", "completed": 1, "succeeded": 2},
    {"status": "running", "completed": 3, "succeeded": 3, "deferred": 1},
    {"status": "completed", "completed": 3, "succeeded": 3, "failures": [{}]},
    {"release_sequence": SEQUENCE + 1},
    {"job_id": "releasejob_" + "f" * 32},
  ],
)
def test_job_status_rejects_failures_mismatches_and_partial_terminal_states(changes):
  with pytest.raises(release_contract.ContractError):
    release_contract.validate_job_status(
      job_body(**changes), job_id=JOB_ID, sequence=SEQUENCE
    )
