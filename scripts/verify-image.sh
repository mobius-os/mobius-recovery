#!/bin/sh
set -eu

image=${1:?usage: verify-image.sh IMAGE EXPECTED_SHA}
expected_sha=${2:?usage: verify-image.sh IMAGE EXPECTED_SHA}

user=$(docker image inspect "$image" --format '{{.Config.User}}')
test "$user" = "10001:10001"

label=$(docker image inspect "$image" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
test "$label" = "$expected_sha"

healthcheck=$(docker image inspect "$image" \
  --format '{{if .Config.Healthcheck}}present{{end}}')
test -z "$healthcheck"

host_python=$(command -v python3 || command -v python)
expected_claude=$("$host_python" -c \
  'import json; print(json.load(open("package.json"))["dependencies"]["@anthropic-ai/claude-code"])')
expected_codex=$("$host_python" -c \
  'import json; print(json.load(open("package.json"))["dependencies"]["@openai/codex"])')

docker run --rm \
  -e EXPECTED_CLAUDE="$expected_claude" \
  -e EXPECTED_CODEX="$expected_codex" \
  --entrypoint /bin/sh "$image" -eu -c '
  test "$(id -u):$(id -g)" = "10001:10001"
  test ! -w /app
  test ! -w /app/recovery_worker/app.py
  ! chmod u+w /app/recovery_worker/app.py 2>/dev/null
  test ! -e /app/.git
  test -z "$(find /app /opt/codex /usr/local/bin -writable -print)"
  python -c "import os,sys; paths=[os.path.abspath(p or os.getcwd()) for p in sys.path]; bad=[p for p in paths if os.path.exists(p) and os.access(p,os.W_OK)]; assert not bad,bad"
  grep -q "^CapEff:[[:space:]]*0000000000000000$" /proc/self/status
  grep -q "^CapPrm:[[:space:]]*0000000000000000$" /proc/self/status
  grep -q "^CapAmb:[[:space:]]*0000000000000000$" /proc/self/status
  test -z "$(find / -xdev -type f -perm /6000 -print 2>/dev/null)"
  ! command -v sudo
  ! command -v docker
  ! command -v railway
  ! command -v node
  test ! -e /usr/local/lib/node_modules
  test "$(claude --version)" = "$EXPECTED_CLAUDE (Claude Code)"
  test "$(codex --version)" = "codex-cli $EXPECTED_CODEX"
  codex exec --help >/dev/null
  codex login --help >/dev/null
'

# Exercise the installed launcher, not a host checkout. The first session
# leaves project memory behind; the workspace manager must delete it. The
# second writable cwd deliberately shadows recovery_worker, and -I plus the
# fixed /app import must still select the root-owned command client.
docker run --rm --entrypoint python "$image" -c '
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading

sys.path.insert(0, "/app")
from recovery_worker.workspace import SessionWorkspaces

spaces = SessionWorkspaces(pathlib.Path("/state/image-workspaces"))
first = spaces.create()
poison = first / "recovery_worker"
poison.mkdir()
(poison / "__init__.py").write_text("raise SystemExit(91)\n", encoding="utf-8")
(poison / "command_cli.py").write_text("raise SystemExit(92)\n", encoding="utf-8")
(first / "CLAUDE.md").write_text("old-session-memory\n", encoding="utf-8")

second = spaces.create()
assert second != first
assert not first.exists()
poison = second / "recovery_worker"
poison.mkdir()
(poison / "__init__.py").write_text("raise SystemExit(93)\n", encoding="utf-8")
(poison / "command_cli.py").write_text("raise SystemExit(94)\n", encoding="utf-8")

broker_path = pathlib.Path("/state/image-test-broker.sock")
try:
  broker_path.unlink()
except FileNotFoundError:
  pass
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(str(broker_path))
listener.listen(1)

def serve():
  connection, _address = listener.accept()
  with connection:
    raw = b""
    while not raw.endswith(b"\n"):
      raw += connection.recv(4096)
    request = json.loads(raw)
    assert request["operation"] == "exec"
    assert request["args"]["argv"] == ["/usr/bin/id", "-u"]
    connection.sendall(json.dumps({
      "ok": True,
      "result": {"stdout_base64": "MAo=", "stderr_base64": "", "exit_code": 0},
    }).encode() + b"\n")
  listener.close()

server = threading.Thread(target=serve)
server.start()
environment = os.environ.copy()
environment["MOBIUS_RECOVERY_BROKER_SOCKET"] = str(broker_path)
result = subprocess.run(
  ["/usr/local/bin/mobius-ssh", "--", "/usr/bin/id", "-u"],
  cwd=second,
  env=environment,
  text=True,
  capture_output=True,
  timeout=10,
)
server.join(10)
assert not server.is_alive()
assert result.returncode == 0, (result.stdout, result.stderr)
assert result.stdout == "0\n"
assert "SystemExit" not in result.stderr
'

docker run --rm --entrypoint python "$image" -c '
import os
paths = (
  os.path.join(root, name)
  for base in ("/bin", "/sbin", "/usr", "/app", "/opt")
  for root, _dirs, files in os.walk(base)
  for name in files
)
bad = [
  path for path in paths
  if "security.capability" in os.listxattr(path, follow_symlinks=False)
]
assert not bad, bad
'

# A same-uid init/wrapper would keep the original secret-bearing environment
# readable even after Python makes itself non-dumpable. Production must exec the
# hardened worker directly as PID 1.
if docker run --rm --init \
  -e MOBIUS_RECOVERY_CONTROL_PLANE_URL=https://control.invalid \
  -e MOBIUS_RECOVERY_INSTANCE_ID=mob_verify-instance \
  -e MOBIUS_RECOVERY_SERVICE_ID=verify-service \
  -e MOBIUS_RECOVERY_BOOTSTRAP_SECRET=verify-bootstrap-secret-0000000000000000 \
  "$image" >/dev/null 2>&1; then
  echo "worker accepted a same-uid init process" >&2
  exit 1
fi

container=$(docker run -d \
  -e MOBIUS_RECOVERY_CONTROL_PLANE_URL=https://control.invalid \
  -e MOBIUS_RECOVERY_INSTANCE_ID=mob_verify-instance \
  -e MOBIUS_RECOVERY_SERVICE_ID=verify-service \
  -e MOBIUS_RECOVERY_BOOTSTRAP_SECRET=verify-bootstrap-secret-0000000000000000 \
  -e MOBIUS_RECOVERY_BUILD_SHA=spoofed-runtime-value \
  "$image")
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT INT TERM

attempt=0
while [ "$attempt" -lt 30 ]; do
  if actual=$(docker exec "$container" python -c \
    "import http.client,json; c=http.client.HTTPConnection('127.0.0.1',8000,timeout=2); c.request('GET','/health'); print(json.load(c.getresponse())['build_sha'])" \
    2>/dev/null); then
    test "$actual" = "$expected_sha"
    docker exec "$container" /bin/sh -eu -c '
      ! test -r /proc/1/environ
      ! test -r /proc/1/mem
      ! test -r /proc/1/fd
      ! test -r /proc/1/fdinfo
      grep -q "^NoNewPrivs:[[:space:]]*1$" /proc/1/status
      ! cat /proc/1/environ >/dev/null 2>&1
      ! dd if=/proc/1/mem of=/dev/null bs=1 count=1 >/dev/null 2>&1
      ! find /proc/1/fd -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .
    '
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done

docker logs "$container"
exit 1
