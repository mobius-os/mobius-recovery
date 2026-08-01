from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_and_ci_references_are_immutable_and_integrity_locked() -> None:
  dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
  assert "# syntax=" not in dockerfile
  from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
  assert len(from_lines) == 2
  assert all(re.search(r"@sha256:[0-9a-f]{64}(?: |$)", line) for line in from_lines)
  assert "npm ci --omit=dev --ignore-scripts" in dockerfile
  assert "npm install" not in dockerfile

  workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
  uses = re.findall(r"uses:\s*([^\s#]+)", workflow)
  assert uses
  assert all(re.search(r"@[0-9a-f]{40}$", reference) for reference in uses)
  assert "pip install --require-hashes --requirement requirements-dev.lock" in workflow
  assert "run: python -m pytest" in workflow

  package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
  lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
  assert lock["packages"][""]["dependencies"] == package["dependencies"]
  dependencies = [
    value for key, value in lock["packages"].items()
    if key and "version" in value
  ]
  assert dependencies
  assert all(item.get("integrity", "").startswith("sha512-") for item in dependencies)

  dev_lock = (ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
  assert "-r requirements.lock" in dev_lock
  assert dev_lock.count("--hash=sha256:") == 5
