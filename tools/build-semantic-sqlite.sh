#!/usr/bin/env bash
# npm ci --ignore-scripts 後、固定better-sqlite3だけを同梱sourceからoffline buildする。
set -euo pipefail
umask 077
repo=$(dirname -- "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")")
namespace_args=()
if [[ ${1:-} == --github-hosted-network ]]; then
  namespace_args=(--github-hosted)
  shift
  /usr/bin/python3 -I -B "$repo/evals/semantic/network_namespace.py" --check-github-hosted
fi
(($# == 0)) || { printf '%s\n' 'Unknown argument; no build was started.' >&2; exit 2; }
node=$(realpath -- "$(command -v node)")
prefix=$(dirname -- "$(dirname -- "$node")")
[[ $(env -i "$node" --version) == v24.19.0 ]] || { printf '%s\n' 'Node 24.19.0 is required.' >&2; exit 2; }
native="$repo/evals/semantic/node_modules/better-sqlite3"
[[ $(env -i "$node" -p 'require(process.argv[1]).version' "$native/package.json") == 11.10.0 ]] || exit 2
gyp="$prefix/lib/node_modules/npm/node_modules/node-gyp/bin/node-gyp.js"
[[ -f $gyp && -f $prefix/include/node/node.h ]] || { printf '%s\n' 'The official Node distribution with bundled npm/node-gyp and headers is required.' >&2; exit 2; }
command -v g++ >/dev/null
command -v make >/dev/null
build_home=$(mktemp -d /tmp/core-semantic-native.XXXXXXXX)
cd -- "$native"
/usr/bin/python3 -I -B "$repo/evals/semantic/network_namespace.py" "${namespace_args[@]}" -- /usr/bin/env -i \
  PATH="$prefix/bin:/usr/bin:/bin" HOME="$build_home" TMPDIR="$build_home" \
  "$node" "$gyp" rebuild --release --nodedir="$prefix" --python=/usr/bin/python3
env -i "$node" -e 'const Database=require(process.argv[1]); const db=new Database(":memory:"); if(db.prepare("SELECT 1 AS value").get().value!==1) process.exit(1); db.close();' "$native"
printf '%s\n' 'PASS: better-sqlite3 11.10.0 built from locked source without network.'
