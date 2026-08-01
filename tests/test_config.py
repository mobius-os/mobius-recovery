from __future__ import annotations

import pytest

from recovery_worker.config import Settings


def managed_settings(**changes) -> Settings:
  values = {
    "port": 8000,
    "build_sha": "abc123",
    "service_id": "recovery-service",
    "secure_cookie": True,
    "control_plane_url": "https://mobius.you",
    "instance_id": "mob_instance-1",
    "bootstrap_secret": "bootstrap-" + "b" * 32,
    "local_target_url": None,
    "local_target_token": None,
    "local_token": None,
  }
  values.update(changes)
  return Settings(**values)


@pytest.mark.parametrize(
  ("change", "message"),
  [
    ({"control_plane_url": "http://mobius.you"}, "HTTPS origin"),
    ({"secure_cookie": False}, "SECURE_COOKIE"),
    ({"instance_id": "instance-1"}, "mob_ instance id"),
    ({"instance_id": "mob_x/../../proc"}, "mob_ instance id"),
  ],
)
def test_managed_environment_requires_https_cookie_and_instance_shape(
  change, message
) -> None:
  with pytest.raises(RuntimeError, match=message):
    managed_settings(**change).validate()


def test_valid_managed_environment_passes() -> None:
  managed_settings().validate()
