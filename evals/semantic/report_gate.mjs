import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assertion from './assertions.cjs';

const { METRIC, PROVIDER, GateError, demand, object, finite, keys, evaluate,
  loadExpectations, validateExpectations } = assertion;
const PROVIDER_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), 'provider.py');

function critical(specification) {
  return object(specification) && specification.type === 'javascript'
    && specification.metric === METRIC
    && typeof specification.value === 'string'
    && /(?:^|\/)assertions\.cjs$/.test(specification.value);
}

function assertionsPresent(specifications) {
  demand(Array.isArray(specifications) && specifications.length > 0, 'assertions_missing');
  demand(specifications.filter(critical).length === 1, 'critical_assertion_missing');
}

function gradingResult(result) {
  demand(object(result) && typeof result.pass === 'boolean' && Number.isFinite(result.score)
    && result.score >= 0 && result.score <= 1, 'grading_failure');
  let criticalResults = [];
  if (critical(result.assertion)) {
    const metadata = result.metadata;
    demand(metadata?.gate_version === 1 && typeof metadata.hard_gates_pass === 'boolean'
      && typeof metadata.retrieval_quality_pass === 'boolean'
      && (metadata.answer_quality_pass === null || typeof metadata.answer_quality_pass === 'boolean')
      && metadata.quality_evidence === false, 'critical_grading_failure');
    const claimedPass = metadata.hard_gates_pass && metadata.retrieval_quality_pass && metadata.answer_quality_pass !== false;
    demand(result.pass === claimedPass && result.score === (claimedPass ? 1 : 0), 'critical_grading_inconsistent');
    criticalResults.push(result);
  }
  if (Object.hasOwn(result, 'componentResults')) {
    demand(Array.isArray(result.componentResults) && result.componentResults.length > 0, 'components_missing');
    for (const component of result.componentResults) criticalResults.push(...gradingResult(component));
  }
  return criticalResults;
}

function caseId(value) {
  keys(value, ['case_id'], 'case_vars');
  demand(typeof value.case_id === 'string', 'case_id');
  return value.case_id;
}

function hasFailedComponent(result) {
  return !result.pass || (result.componentResults || []).some(hasFailedComponent);
}

export function inspectReport(report, options) {
  const base = { schema_version: 1, status: 'FAIL', pipeline_status: 'FAIL',
    quality_evidence: false, model_quality_status: 'NOT_RUN',
    suite: options.suite, mode: options.mode, expected_pairs: 0, evaluated_pairs: 0,
    privacy_failures: 0, retrieval_quality_failures: 0, answer_quality_failures: 0, reported_failures: 0,
    mean_recall_at_k: null, reason: 'report_invalid' };
  base.model_calls = { embedding_requests: 0, embedding_texts: 0, chat_requests: 0 };
  try {
    demand(['retrieval', 'answer'].includes(options.suite)
      && ['offline_fixture', 'local_model'].includes(options.mode), 'run_mode');
    const expected = options.expectations instanceof Map ? options.expectations
      : validateExpectations(options.expectations);
    demand(expected.size > 0, 'cases_empty');
    demand(Array.isArray(options.providers) && options.providers.length > 0
      && new Set(options.providers).size === options.providers.length
      && options.providers.every((id) => id === PROVIDER), 'providers_invalid');
    base.expected_pairs = expected.size * options.providers.length;
    demand(object(report) && object(report.results) && report.results.version === 3
      && Array.isArray(report.results.results), 'report_version');
    finite(report, 'report_nonfinite');
    demand(object(report.config) && Array.isArray(report.config.providers)
      && report.config.providers.length === options.providers.length, 'providers_missing');
    const configured = new Map();
    for (const provider of report.config.providers) {
      demand(object(provider) && typeof provider.id === 'string' && provider.id.length > 0
        && options.providers.includes(provider.label) && !configured.has(provider.label), 'provider_config');
      demand(provider.id === `file://${PROVIDER_PATH}`, 'provider_script');
      demand(provider.config?.suite === options.suite && provider.config?.mode === options.mode, 'provider_mode');
      configured.set(provider.label, provider.id);
    }
    demand(Array.isArray(report.config.tests) && report.config.tests.length === expected.size, 'configured_cases');
    const configuredCases = new Set();
    for (const test of report.config.tests) {
      const id = caseId(test?.vars);
      demand(expected.has(id) && !configuredCases.has(id), 'configured_case_set');
      configuredCases.add(id);
    }
    assertionsPresent(report.config.defaultTest?.assert);
    demand(Array.isArray(report.config.prompts) && report.config.prompts.length === 1
      && report.config.prompts[0] === '{{case_id}}', 'prompt_contract');
    const rows = report.results.results;
    demand(rows.length === base.expected_pairs && rows.length > 0, 'row_count');
    const seen = new Set();
    const recalls = [];
    const actualProviderIds = new Map();
    const identities = new Map();
    for (const row of rows) {
      demand(object(row) && typeof row.success === 'boolean'
        && (row.error === undefined || row.error === null || typeof row.error === 'string')
        && [0, 1, 2].includes(row.failureReason) && typeof row.score === 'number'
        && Number.isFinite(row.score) && row.score >= 0 && row.score <= 1, 'row_failed');
      demand(row.skipped !== true && row.skip !== true && row.status !== 'NOT_RUN'
        && row.status !== 'SKIP' && row.status !== 'SKIPPED', 'row_not_run');
      const id = caseId(row.vars);
      demand(expected.has(id) && caseId(row.testCase?.vars) === id, 'row_case_identity');
      demand(row.prompt?.raw === id, 'prompt_payload');
      demand(object(row.provider) && configured.has(row.provider.label)
        && typeof row.provider.id === 'string' && row.provider.id.length > 0, 'row_provider');
      // Promptfoo's Python provider may normalize file:// into python:path:default.
      // Pin the actual provider identifier across every row, and verify its script.
      const configuredId = configured.get(row.provider.label);
      const actualId = row.provider.id;
      const script = configuredId.startsWith('file://') ? configuredId.slice(7) : configuredId;
      demand(actualId === configuredId || actualId === `python:${script}:default`
        || actualId === `python:${path.basename(script)}:default`, 'provider_path');
      if (actualProviderIds.has(row.provider.label)) demand(actualProviderIds.get(row.provider.label) === actualId, 'provider_mixed');
      actualProviderIds.set(row.provider.label, actualId);
      const pair = `${id}\0${row.provider.label}`;
      demand(!seen.has(pair), 'row_duplicate');
      seen.add(pair);
      assertionsPresent(row.testCase.assert);
      demand(object(row.gradingResult) && Array.isArray(row.gradingResult.componentResults), 'components_missing');
      const criticalResults = gradingResult(row.gradingResult);
      demand(criticalResults.length === 1, 'critical_result_count');
      if (!row.success || row.error !== undefined && row.error !== null || row.failureReason !== 0
        || hasFailedComponent(row.gradingResult)) base.reported_failures += 1;
      demand(object(row.response) && row.response.error === undefined
        && Object.hasOwn(row.response, 'output'), 'response_missing');
      demand(row.response.cached !== true, 'cached_replay');
      const checked = evaluate(row.response.output, expected.get(id), options.suite, options.mode);
      if (!checked.hard_gates_pass) base.privacy_failures += 1;
      if (!checked.retrieval_quality_pass) base.retrieval_quality_failures += 1;
      if (checked.answer_quality_pass === false) base.answer_quality_failures += 1;
      if (checked.recall_at_k !== null) recalls.push(checked.recall_at_k);
      if (checked.hard_gates_pass) {
        const parsed = typeof row.response.output === 'string' ? JSON.parse(row.response.output) : row.response.output;
        if (options.mode === 'local_model') for (const kind of ['embedding', 'chat']) {
          const identity = JSON.stringify(parsed.model_identity[kind]);
          if (identities.has(kind)) demand(identities.get(kind) === identity, 'model_identity_drift');
          else identities.set(kind, identity);
        }
        for (const key of Object.keys(base.model_calls)) base.model_calls[key] += parsed.calls[key];
      }
      base.evaluated_pairs += 1;
    }
    for (const id of expected.keys()) for (const provider of options.providers) demand(seen.has(`${id}\0${provider}`), 'pair_missing');
    const stats = report.results.stats;
    demand(object(stats) && stats.successes === rows.filter((row) => row.success).length
      && Number.isSafeInteger(stats.failures) && stats.failures >= 0
      && Number.isSafeInteger(stats.errors) && stats.errors >= 0
      && stats.successes + stats.failures + stats.errors === base.expected_pairs, 'stats_mismatch');
    base.mean_recall_at_k = recalls.length ? recalls.reduce((sum, value) => sum + value, 0) / recalls.length : null;
    demand(base.privacy_failures === 0 && base.retrieval_quality_failures === 0
      && base.answer_quality_failures === 0 && base.reported_failures === 0, 'rechecked_failure');
    base.status = 'PASS';
    base.pipeline_status = 'PASS';
    if (Object.values(base.model_calls).some((count) => count > 0)) base.model_quality_status = 'NOT_ESTABLISHED';
    base.reason = 'all_pairs_rechecked';
    return base;
  } catch (error) {
    base.reason = error instanceof GateError ? error.message : 'report_invalid';
    return base;
  }
}

export function main(argv = process.argv.slice(2)) {
  let summary = { schema_version: 1, status: 'FAIL', pipeline_status: 'FAIL',
    quality_evidence: false, model_quality_status: 'NOT_RUN', reason: 'gate_input' };
  let output;
  try {
    const args = new Map();
    demand(argv.length % 2 === 0, 'arguments');
    for (let i = 0; i < argv.length; i += 2) {
      demand(['--report', '--providers', '--suite', '--mode', '--output'].includes(argv[i])
        && !args.has(argv[i]) && typeof argv[i + 1] === 'string', 'arguments');
      args.set(argv[i], argv[i + 1]);
    }
    demand(args.has('--report') && args.has('--providers') && args.has('--suite'), 'arguments');
    output = args.get('--output');
    const filename = args.get('--report');
    const stat = fs.lstatSync(filename);
    demand(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 32 * 1024 * 1024, 'report_file');
    const report = JSON.parse(fs.readFileSync(filename, 'utf8'));
    summary = inspectReport(report, { expectations: loadExpectations(),
      providers: args.get('--providers').split(','), suite: args.get('--suite'),
      mode: args.get('--mode') || 'offline_fixture' });
  } catch (error) {
    summary.reason = error instanceof GateError ? error.message : 'gate_input';
  }
  const encoded = `${JSON.stringify(summary, null, 2)}\n`;
  if (output) {
    try { fs.writeFileSync(output, encoded, { flag: 'wx', mode: 0o600 }); }
    catch { process.stdout.write('{"status":"FAIL","quality_evidence":false,"reason":"summary_write"}\n'); return 1; }
  }
  process.stdout.write(encoded);
  return summary.status === 'PASS' ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = main();
