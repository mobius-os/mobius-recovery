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

docker run --rm --entrypoint /bin/sh "$image" -c '
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
  claude --version | grep -F "2.1.218"
  codex --version | grep -F "0.145.0"
  codex exec --help >/dev/null
  codex login --help >/dev/null
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
  -e MOBIUS_RECOVERY_INSTANCE_ID=verify-instance \
  -e MOBIUS_RECOVERY_SERVICE_ID=verify-service \
  -e MOBIUS_RECOVERY_BOOTSTRAP_SECRET=verify-bootstrap-secret-0000000000000000 \
  "$image" >/dev/null 2>&1; then
  echo "worker accepted a same-uid init process" >&2
  exit 1
fi

container=$(docker run -d \
  -e MOBIUS_RECOVERY_CONTROL_PLANE_URL=https://control.invalid \
  -e MOBIUS_RECOVERY_INSTANCE_ID=verify-instance \
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
    docker exec "$container" /bin/sh -c '
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
