#!/usr/bin/env bash
set -euo pipefail

# Run in Ubuntu-dogfood as the normal operator. Never acquire sudo here.
if [[ $(id -u) == 0 ]]; then
  echo 'Run as the normal operator, not root.' >&2
  exit 1
fi
ollama_load=$(systemctl show digital-souls-ollama.service --property=LoadState --value)
ollama_state=$(systemctl show digital-souls-ollama.service --property=ActiveState --value)
if [[ $ollama_load != loaded || $ollama_state != inactive ]]; then
  echo 'Ollama must be a known, stopped service. Explicitly stop it before switching; existing Ollama clients will be unavailable.' >&2
  exit 1
fi
: "${CORE_LLAMACPP_MODEL:?Set the verified user-owned model GGUF path}"
expected=1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606
actual=$(sha256sum -- "$CORE_LLAMACPP_MODEL")
if [[ ${actual%% *} != "$expected" ]]; then
  echo 'Model SHA-256 does not match the verified Gemma 4 weights.' >&2
  exit 1
fi
export CORE_LLAMACPP_UID="$(id -u)" CORE_LLAMACPP_GID="$(id -g)"
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker compose -f "$repo_dir/compose.llamacpp.yml" config --quiet
docker compose -f "$repo_dir/compose.llamacpp.yml" up -d --no-build --pull never
