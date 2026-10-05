#!/usr/bin/env bash
# 合成専用の使い捨てpgvector環境。既存DB・daemon設定・既存containerは変更しない。
set -euo pipefail

if [[ ${1:-} == --help ]]; then
  printf '%s\n' 'Usage: bash tools/test-pgvector-poc.sh [-- command [args...]]' \
    'Default: uv run --no-sync pytest -m pgvector -q' \
    'Creates a private Unix-socket fixture, exports DSC_PGVECTOR_POC_*, then removes only its own container.'
  exit 0
fi
if (($#)); then
  if [[ $1 != -- ]] || (($# < 2)); then
    printf '%s\n' 'Expected -- followed by a command.' >&2
    exit 2
  fi
  shift
else
  command -v uv >/dev/null || { printf '%s\n' 'uv must be on PATH.' >&2; exit 2; }
  set -- uv run --no-sync pytest -m pgvector -q
fi
command -v docker >/dev/null || { printf '%s\n' 'Docker CLI is required.' >&2; exit 2; }

image='pgvector/pgvector:0.8.7-pg18-bookworm@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11'
fixture_dir=$(mktemp -d /tmp/core-pgvector-poc.XXXXXXXX)
container_name="core-pgvector-poc-${fixture_dir##*.}"
owner_label='org.digital-souls.core.pgvector-poc'
container_id=''
mkdir -m 700 "$fixture_dir/socket" "$fixture_dir/docker-config"
# Explicit local daemon and an empty private profile: no stored registry credentials.
docker_cmd=(docker --host unix:///var/run/docker.sock --config "$fixture_dir/docker-config")

cleanup() {
  result=$?
  trap - EXIT
  if [[ -f $fixture_dir/container.id && ! -L $fixture_dir/container.id ]]; then
    container_id=$(cat "$fixture_dir/container.id")
  fi
  if [[ -n $container_id ]]; then
    if [[ ! $container_id =~ ^[a-f0-9]{64}$ ]]; then
      printf '%s\n' "Unknown container ID; fixture retained: $fixture_dir" >&2
      exit 1
    fi
    if actual_label=$("${docker_cmd[@]}" inspect --format \
      '{{index .Config.Labels "org.digital-souls.core.pgvector-poc"}}' "$container_id" 2>/dev/null); then
      if [[ $actual_label != "$container_name" ]]; then
        printf '%s\n' "Container label mismatch; refusing cleanup: $container_id" >&2
        exit 1
      fi
      if ! "${docker_cmd[@]}" rm --force "$container_id" >/dev/null; then
        printf '%s\n' "Container cleanup failed; fixture retained: $fixture_dir" >&2
        exit 1
      fi
    else
      printf '%s\n' "Cannot verify own container; inspect fixture manually: $fixture_dir" >&2
      exit 1
    fi
  fi
  # Delete only known files within this invocation's mktemp directory. Never recurse.
  rm -f -- "$fixture_dir/socket/.s.PGSQL.5432" "$fixture_dir/socket/.s.PGSQL.5432.lock" \
    "$fixture_dir/container.id"
  if ! rmdir -- "$fixture_dir/socket" "$fixture_dir/docker-config" "$fixture_dir"; then
    printf '%s\n' "Unexpected fixture files retained: $fixture_dir" >&2
    exit 1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"${docker_cmd[@]}" info --format '{{.ServerVersion}}' >/dev/null
if "${docker_cmd[@]}" container inspect "$container_name" >/dev/null 2>&1; then
  printf '%s\n' 'Generated container name already exists; refusing to reuse it.' >&2
  exit 1
fi
# Pull only when the exact immutable image is absent. No apt or host service operation.
if ! "${docker_cmd[@]}" image inspect "$image" >/dev/null 2>&1; then
  "${docker_cmd[@]}" pull --platform linux/amd64 "$image"
fi
container_id=$("${docker_cmd[@]}" run --detach --rm --cidfile "$fixture_dir/container.id" \
  --name "$container_name" --label "$owner_label=$container_name" --network none \
  --cpus 1 --memory 1g --memory-swap 1g --pids-limit 128 --shm-size 64m \
  --cap-drop ALL --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" \
  --tmpfs "/var/lib/postgresql:uid=$(id -u),gid=$(id -g),mode=0700,size=512m" \
  --mount "type=bind,source=$fixture_dir/socket,target=/var/run/postgresql" \
  --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=core_pgvector_synthetic \
  --env POSTGRES_USER=core_pgvector_synthetic "$image" postgres \
  -c listen_addresses= -c unix_socket_permissions=0700 \
  -c shared_buffers=64MB -c max_connections=20)

ready=false
for attempt in {1..60}; do
  # Wait for entrypoint's temporary init server to finish before invoking tests.
  if [[ $("${docker_cmd[@]}" exec "$container_id" cat /proc/1/comm 2>/dev/null) == postgres ]] \
    && "${docker_cmd[@]}" exec "$container_id" pg_isready -q \
      -U core_pgvector_synthetic -d core_pgvector_synthetic; then
    ready=true
    break
  fi
  sleep 1
done
if [[ $ready != true ]]; then
  "${docker_cmd[@]}" logs "$container_id" >&2
  printf '%s\n' 'Dedicated pgvector fixture did not become ready.' >&2
  exit 1
fi
versions=$("${docker_cmd[@]}" exec "$container_id" psql -X -w -At -v ON_ERROR_STOP=1 \
  -U core_pgvector_synthetic -d core_pgvector_synthetic -c \
  "CREATE EXTENSION vector; SELECT current_setting('server_version_num'),extversion FROM pg_extension WHERE extname='vector';")
if [[ $versions != $'CREATE EXTENSION\n180006|0.8.7' ]]; then
  printf '%s\n' 'Pinned PostgreSQL/pgvector version assertion failed.' >&2
  exit 1
fi
export DSC_PGVECTOR_POC_SOCKET="$fixture_dir/socket"
export DSC_PGVECTOR_POC_PORT=5432
export DSC_PGVECTOR_POC_DATABASE=core_pgvector_synthetic
export DSC_PGVECTOR_POC_USER=core_pgvector_synthetic
export LITELLM_LOCAL_MODEL_COST_MAP=True
printf '%s\n' 'Synthetic fixture: PostgreSQL 18.6 / pgvector 0.8.7, network none, private Unix socket.'
"$@"
