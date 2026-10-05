#!/usr/bin/env bash
# 固定合成corpusの検索/回答を分離評価。実モデルは明示opt-inだけ。
set -euo pipefail
umask 077

script=$(realpath -- "${BASH_SOURCE[0]}")
repo=$(dirname -- "$(dirname -- "$script")")
eval_dir="$repo/evals/semantic"
mode=${1:-fixture}
if (($#)); then shift; fi
profile=''
execute_real=false
while (($#)); do
  case "$1" in
    --profile)
      (($# >= 2)) || { printf '%s\n' 'Missing profile path.' >&2; exit 2; }
      profile=$2; shift 2 ;;
    --execute-local-model) execute_real=true; shift ;;
    *) printf '%s\n' 'Unknown argument; no evaluation was started.' >&2; exit 2 ;;
  esac
done
case "$mode" in
  --help)
    printf '%s\n' 'Usage: bash tools/evaluate-semantic.sh [fixture]' \
      '       bash tools/evaluate-semantic.sh local-model --profile /absolute/profile.json --execute-local-model' \
      'Fixture mode creates a disposable pgvector DB and an isolated network namespace.' \
      'Both suites are mandatory. Real-model quality is NOT_RUN by default.'
    exit 0 ;;
  fixture|--fixture-child)
    [[ -z $profile && $execute_real == false ]] || { printf '%s\n' 'Fixture mode rejects model settings.' >&2; exit 2; } ;;
  local-model|--local-model-child)
    if [[ $execute_real != true || -z $profile ]]; then
      printf '%s\n' '{"status":"NOT_RUN","reason":"explicit_profile_and_execute_local_model_required"}'
      exit 3
    fi
    [[ $profile = /* && -f $profile && ! -L $profile ]] || { printf '%s\n' 'A regular absolute profile is required.' >&2; exit 2; } ;;
  *) printf '%s\n' 'Unknown mode; no evaluation was started.' >&2; exit 2 ;;
esac

node=$(command -v node)
uv=$(command -v uv)
[[ $(env -i "$node" --version) == v24.19.0 ]] || { printf '%s\n' 'Node 24.19.0 is required.' >&2; exit 2; }
[[ $(env -i "$uv" --version) == 'uv 0.8.22' ]] || { printf '%s\n' 'uv 0.8.22 is required.' >&2; exit 2; }
python="$repo/.venv/bin/python"
[[ -x $python ]] || { printf '%s\n' 'Run uv sync --frozen first.' >&2; exit 2; }
[[ -f $eval_dir/node_modules/promptfoo/dist/src/main.js ]] || { printf '%s\n' 'Run npm ci --ignore-scripts in evals/semantic first.' >&2; exit 2; }
[[ $(env -i "$node" -p 'require(process.argv[1]).version' "$eval_dir/node_modules/promptfoo/package.json") == 0.117.2 ]] || exit 2
clean_path="$(dirname -- "$node"):$(dirname -- "$uv"):/usr/bin:/bin"

if [[ $mode == fixture || $mode == local-model ]]; then
  # Database startup remains outside the evaluation namespace; only a private Unix socket crosses it.
  namespace=$(readlink /proc/self/ns/net)
  if [[ $mode == fixture ]]; then
    exec env -i PATH="$clean_path" DSC_SEMANTIC_PARENT_NETNS="$namespace" \
      bash "$repo/tools/test-pgvector-poc.sh" -- \
      unshare --user --map-current-user --net -- bash "$script" --fixture-child
  fi
  env -i PATH="$clean_path" PYTHONPATH="$repo" LITELLM_LOCAL_MODEL_COST_MAP=True \
    "$python" -B "$eval_dir/profile_preflight.py" "$profile"
  exec env -i PATH="$clean_path" bash "$repo/tools/test-pgvector-poc.sh" -- \
    bash "$script" --local-model-child --profile "$profile" --execute-local-model
fi

for name in DSC_PGVECTOR_POC_SOCKET DSC_PGVECTOR_POC_PORT DSC_PGVECTOR_POC_DATABASE DSC_PGVECTOR_POC_USER; do
  [[ -n ${!name:-} ]] || { printf '%s\n' 'Dedicated synthetic DB configuration is missing.' >&2; exit 2; }
done
if [[ $mode == --fixture-child ]]; then
  [[ -n ${DSC_SEMANTIC_PARENT_NETNS:-} && $(readlink /proc/self/ns/net) != "$DSC_SEMANTIC_PARENT_NETNS" ]] \
    || { printf '%s\n' 'Fixture evaluation requires a separate network namespace.' >&2; exit 2; }
  selected=fixture
  evaluation_mode=offline_fixture
else
  selected=local-model
  evaluation_mode=local_model
fi

run_dir=$(mktemp -d /tmp/core-semantic-eval.XXXXXXXX)
mkdir -m 700 "$run_dir/home" "$run_dir/tmp" "$run_dir/state" "$run_dir/logs" "$run_dir/reports"
printf '%s\n' "Semantic evaluation artifacts: $run_dir"
if [[ $selected == local-model ]]; then
  env -i PATH="$clean_path" PYTHONPATH="$repo" LITELLM_LOCAL_MODEL_COST_MAP=True \
    "$python" -B "$eval_dir/profile_preflight.py" "$profile" --snapshot "$run_dir/profile.json" \
    > "$run_dir/reports/profile-validation.json"
  profile="$run_dir/profile.json"
fi
base_env=(env -i PATH="$clean_path" HOME="$run_dir/home" TMPDIR="$run_dir/tmp" LANG=C.UTF-8 \
  LITELLM_LOCAL_MODEL_COST_MAP=True PYTHONPATH="$repo" PYTHONDONTWRITEBYTECODE=1 \
  PROMPTFOO_PYTHON="$python" DOTENV_CONFIG_PATH=/dev/null \
  PROMPTFOO_CONFIG_DIR="$run_dir/state" PROMPTFOO_LOG_DIR="$run_dir/logs" \
  PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 PROMPTFOO_DISABLE_SHARING=1 \
  PROMPTFOO_DISABLE_WAL_MODE=1 PROMPTFOO_DISABLE_ERROR_LOG=1 \
  PROMPTFOO_DISABLE_CONVERSATION_VAR=1 PROMPTFOO_DISABLE_VAR_EXPANSION=1 \
  PROMPTFOO_DISABLE_TEMPLATE_ENV_VARS=1 PROMPTFOO_CACHE_ENABLED=false \
  PROMPTFOO_PASS_RATE_THRESHOLD=100 PROMPTFOO_ASSERTIONS_MAX_CONCURRENCY=1 \
  DSC_PGVECTOR_POC_SOCKET="$DSC_PGVECTOR_POC_SOCKET" DSC_PGVECTOR_POC_PORT="$DSC_PGVECTOR_POC_PORT" \
  DSC_PGVECTOR_POC_DATABASE="$DSC_PGVECTOR_POC_DATABASE" DSC_PGVECTOR_POC_USER="$DSC_PGVECTOR_POC_USER")
if [[ $selected == local-model ]]; then base_env+=(DSC_SEMANTIC_PROFILE="$profile"); fi
cd -- "$run_dir"
for suite in retrieval answer; do
  result=0
  "${base_env[@]}" "$node" --require "$eval_dir/network_guard.cjs" \
    "$eval_dir/node_modules/promptfoo/dist/src/main.js" eval \
    --config "$eval_dir/promptfoo.$suite.$selected.cjs" \
    --no-cache --no-table --no-progress-bar -j 1 \
    --output "$run_dir/reports/$suite.json" >"$run_dir/logs/$suite.log" 2>&1 || result=$?
  # Always use the full report gate; CLI exit status alone is not an acceptance criterion.
  gate_result=0
  "${base_env[@]}" "$node" --require "$eval_dir/network_guard.cjs" \
    "$eval_dir/report_gate.mjs" --report "$run_dir/reports/$suite.json" \
    --providers core-semantic --suite "$suite" --mode "$evaluation_mode" \
    --output "$run_dir/reports/$suite-gate.json" \
    || gate_result=$?
  if ((result != 0 || gate_result != 0)); then
    printf '%s\n' "FAIL: $suite (CLI=$result, gate=$gate_result); private artifacts retained: $run_dir" >&2
    exit 1
  fi
done
if [[ $selected == fixture ]]; then
  printf '%s\n' '{"fixture_status":"PASS","real_model_quality":"NOT_RUN","quality_evidence":false}'
else
  printf '%s\n' '{"execution_status":"PASS","quality_evidence":false,"scope":"synthetic_local_profile_only"}'
fi
