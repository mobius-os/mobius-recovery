"""Development entrypoint; the production image invokes uvicorn directly."""

import uvicorn

from .config import Settings
from .security import require_pid_one


def main() -> None:
  require_pid_one()
  settings = Settings.from_env()
  uvicorn.run(
    "recovery_worker.app:create_app",
    factory=True,
    host="0.0.0.0",
    port=settings.port,
    proxy_headers=True,
  )


if __name__ == "__main__":
  main()
