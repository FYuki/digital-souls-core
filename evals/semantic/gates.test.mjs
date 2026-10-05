import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import checker from './assertions.cjs';
import { inspectReport } from './report_gate.mjs';

const SPEC = { type: 'javascript', metric: checker.METRIC, value: 'file://./assertions.cjs' };
const PROVIDER_PATH = fileURLToPath(new URL('./provider.py', import.meta.url));
const SCOPE = { subject: 'synthetic', client: 'fixture', audience: 'local-private', character_id: 'sample' };
const SOURCE = { source_id: 'source-a', revision: 2, epoch: 3,
  conversation_id: 'conversation-a', turn_revision: 4, message_index: 5 };

function expected(id = 'case-a') {
  return { id, category: 'synthetic', binding: { ...SCOPE }, expected_ids: ['memory-a'],
    relevant_ids: ['memory-a'], min_recall: 1, forbidden_ids: ['forbidden-a'],
    expected_sources: { 'memory-a': [{ ...SOURCE }] }, input_rejected: false,
    rejected_memory_ids: [], dispatch: { allowed: true, memory_ids: ['memory-a'], invalid_tokens: [] },
    answer: { behavior: 'grounded', required_facts: ['合成の青い自転車'],
      forbidden_facts: ['SYNTHETIC_PRIVATE_CANARY'], required_citations: ['memory-a'], discarded: false } };
}

function output(suite = 'retrieval', id = 'case-a') {
  return { schema_version: 1, case_id: id, provider_id: 'core-semantic', suite,
    mode: 'offline_fixture', quality_evidence: false, input_rejected: false,
    retrieved: [{ memory_id: 'memory-a', revision: 1, generation: 1, score: 0.9,
      binding: { ...SCOPE }, sources: [{ ...SOURCE }] }],
    dispatch: { allowed: true, memory_ids: ['memory-a'], invalid_tokens: [],
      revalidated_before: true, revalidated_after: true, model_called: false },
    answer: { text: suite === 'answer' ? '[memory-a] 合成の青い自転車' : null,
      mode: suite === 'answer' ? 'template' : 'not_run', discarded: false },
    rejected_memory_ids: [], calls: { embedding_requests: 0, embedding_texts: 0, chat_requests: 0 },
    embedded_memory_ids: [], embedding_input_ids: ['memory-a'], model_identity: { embedding: null, chat: null } };
}

function report(suite = 'retrieval', cases = [expected()]) {
  return { results: { version: 3, stats: { successes: cases.length, failures: 0, errors: 0 },
    results: cases.map((item, index) => {
      const value = output(suite, item.id);
      const checked = checker.evaluate(value, item, suite, 'offline_fixture');
      return { promptIdx: 0, testIdx: index, prompt: { raw: item.id },
        vars: { case_id: item.id }, provider: { id: `file://${PROVIDER_PATH}`, label: 'core-semantic' },
        testCase: { vars: { case_id: item.id }, assert: [{ ...SPEC }] },
        response: { output: JSON.stringify(value) }, success: true, score: 1,
        failureReason: 0, namedScores: { privacy: 1 }, latencyMs: 1,
        gradingResult: { pass: true, score: 1, reason: 'synthetic', componentResults: [{
          pass: true, score: 1, reason: 'synthetic', assertion: { ...SPEC },
          metadata: { gate_version: 1, ...checked },
        }] } };
    }) }, config: { prompts: ['{{case_id}}'], providers: [{ id: `file://${PROVIDER_PATH}`,
      label: 'core-semantic', config: { suite, mode: 'offline_fixture' } }],
    defaultTest: { assert: [{ ...SPEC }] }, tests: cases.map((item) => ({ vars: { case_id: item.id } })) } };
}

function options(suite = 'retrieval', cases = [expected()]) {
  return { suite, mode: 'offline_fixture', providers: ['core-semantic'],
    expectations: { schema_version: 1, cases } };
}

function mutateOutput(value, change) {
  const parsed = JSON.parse(value.results.results[0].response.output);
  change(parsed);
  value.results.results[0].response.output = JSON.stringify(parsed);
}

test('complete fixtures pass but never become model-quality evidence', () => {
  for (const suite of ['retrieval', 'answer']) {
    const result = inspectReport(report(suite), options(suite));
    assert.equal(result.status, 'PASS');
    assert.equal(result.evaluated_pairs, 1);
    assert.equal(result.mean_recall_at_k, 1);
    assert.equal(result.quality_evidence, false);
    assert.equal(result.model_quality_status, 'NOT_RUN');
  }
});

for (const [name, change] of [
  ['zero rows', (r) => { r.results.results = []; r.results.stats.successes = 0; }],
  ['old report layout', (r) => { r.results.version = 2; }],
  ['missing case', (r) => { r.results.results[0].vars.case_id = 'absent'; }],
  ['mismatched test case', (r) => { r.results.results[0].testCase.vars.case_id = 'absent'; }],
  ['error with aggregate success', (r) => { r.results.results[0].error = 'SYNTHETIC_PRIVATE_CANARY'; }],
  ['failed row', (r) => { r.results.results[0].success = false; }],
  ['NOT_RUN row', (r) => { r.results.results[0].status = 'NOT_RUN'; }],
  ['skipped row', (r) => { r.results.results[0].skipped = true; }],
  ['bad stats', (r) => { r.results.stats.successes += 1; }],
  ['missing default assertion', (r) => { r.config.defaultTest.assert = []; }],
  ['missing row assertion', (r) => { r.results.results[0].testCase.assert = []; }],
  ['missing grading', (r) => { delete r.results.results[0].gradingResult; }],
  ['missing components', (r) => { r.results.results[0].gradingResult.componentResults = []; }],
  ['failed critical component', (r) => { r.results.results[0].gradingResult.componentResults[0].pass = false; }],
  ['false privacy flag in passing component', (r) => { r.results.results[0].gradingResult.componentResults[0].metadata.hard_gates_pass = false; }],
  ['duplicate critical assertion', (r) => { r.results.results[0].testCase.assert.push({ ...SPEC }); }],
  ['duplicate critical result', (r) => { r.results.results[0].gradingResult.componentResults.push(structuredClone(r.results.results[0].gradingResult.componentResults[0])); }],
  ['nonfinite aggregate', (r) => { r.results.results[0].score = Infinity; }],
  ['nonfinite named metric', (r) => { r.results.results[0].namedScores.privacy = NaN; }],
  ['unknown provider', (r) => { r.results.results[0].provider.label = 'external'; }],
  ['provider source changed', (r) => { r.results.results[0].provider.id = 'file:///other.py'; }],
  ['untrusted configured source', (r) => { r.config.providers[0].id = 'file:///other.py'; }],
  ['mixed configured mode', (r) => { r.config.providers[0].config.mode = 'local_model'; }],
  ['missing configured case', (r) => { r.config.tests = []; }],
  ['gold in vars', (r) => { r.results.results[0].vars.expected_ids = ['memory-a']; }],
  ['gold in prompt template', (r) => { r.config.prompts[0] = '{{expected_ids}}'; }],
  ['extra prompt payload', (r) => { r.results.results[0].prompt.raw += ' expected memory-a'; }],
  ['provider response error', (r) => { r.results.results[0].response.error = 'failure'; }],
  ['cached call-count replay', (r) => { r.results.results[0].response.cached = true; }],
  ['failed noncritical component', (r) => { r.results.results[0].gradingResult.componentResults.push({ pass: false, score: 0, reason: 'synthetic', assertion: { type: 'equals', value: 'x' } }); }],
]) {
  test(`report rejects ${name}`, () => {
    const data = report(); change(data);
    const result = inspectReport(data, options());
    assert.equal(result.status, 'FAIL');
    assert.equal(result.quality_evidence, false);
    assert.ok(!JSON.stringify(result).includes('SYNTHETIC_PRIVATE_CANARY'));
  });
}

test('duplicate pair cannot replace a missing case even with correct total count', () => {
  const cases = [expected('case-a'), expected('case-b')];
  const data = report('retrieval', cases);
  data.results.results[1] = structuredClone(data.results.results[0]);
  assert.equal(inspectReport(data, options('retrieval', cases)).reason, 'row_duplicate');
});

for (const [name, change] of [
  ['scope leak', (v) => { v.retrieved[0].binding.client = 'other'; }],
  ['audience leak', (v) => { v.retrieved[0].binding.audience = 'public'; }],
  ['source epoch change', (v) => { v.retrieved[0].sources[0].epoch += 1; }],
  ['source message loss', (v) => { v.retrieved[0].sources[0].message_index = 0; }],
  ['source turn change', (v) => { v.retrieved[0].sources[0].turn_revision += 1; }],
  ['source missing', (v) => { v.retrieved[0].sources = []; }],
  ['forbidden retrieval', (v) => { v.retrieved[0].memory_id = 'forbidden-a'; }],
  ['forbidden dispatch', (v) => { v.dispatch.memory_ids = ['forbidden-a']; }],
  ['missing pre-guard', (v) => { v.dispatch.revalidated_before = false; }],
  ['missing post-guard', (v) => { v.dispatch.revalidated_after = false; }],
  ['wrong case', (v) => { v.case_id = 'other-case'; }],
  ['wrong output provider', (v) => { v.provider_id = 'other-provider'; }],
  ['fake quality promotion', (v) => { v.quality_evidence = true; }],
  ['mixed output mode', (v) => { v.mode = 'local_model'; }],
  ['forbidden embedding input', (v) => { v.embedding_input_ids.push('forbidden-a'); }],
  ['fake embedding call claim', (v) => { v.calls.embedding_requests = 1; v.calls.embedding_texts = 2; }],
  ['duplicate retrieval', (v) => { v.retrieved.push(structuredClone(v.retrieved[0])); }],
  ['raw body added to retrieval', (v) => { v.retrieved[0].text = 'SYNTHETIC_PRIVATE_CANARY'; }],
]) {
  test(`raw-output recheck defeats aggregate PASS for ${name}`, () => {
    const data = report(); mutateOutput(data, change);
    const result = inspectReport(data, options());
    assert.equal(result.status, 'FAIL');
    assert.equal(result.privacy_failures, 1);
    assert.ok(!JSON.stringify(result).includes('SYNTHETIC_PRIVATE_CANARY'));
  });
}

test('nonfinite raw numeric output is rejected independently of JSON serialization', () => {
  const value = output(); value.retrieved[0].score = NaN;
  assert.equal(checker.evaluate(value, expected(), 'retrieval', 'offline_fixture').hard_gates_pass, false);
});

test('ranking and answer-quality failures stay separate from privacy failures', () => {
  const item = expected();
  item.expected_sources['memory-b'] = [{ ...SOURCE, source_id: 'source-b' }];
  item.expected_ids.push('memory-b'); item.relevant_ids.push('memory-b');
  const checked = checker.evaluate(output(), item, 'retrieval', 'offline_fixture');
  assert.equal(checked.hard_gates_pass, true);
  assert.equal(checked.retrieval_quality_pass, false);
  assert.equal(checked.recall_at_k, 0.5);
  const answer = output('answer'); answer.answer.text = '[memory-a] 合成の赤い自転車';
  const answerResult = checker.evaluate(answer, expected(), 'answer', 'offline_fixture');
  assert.equal(answerResult.hard_gates_pass, true);
  assert.equal(answerResult.answer_quality_pass, false);
});

test('answer leak and hallucinated citation cannot be rescued by matching required facts', () => {
  for (const suffix of [' SYNTHETIC_PRIVATE_CANARY', ' [forbidden-a]']) {
    const data = report('answer'); mutateOutput(data, (v) => { v.answer.text += suffix; });
    const result = inspectReport(data, options('answer'));
    assert.equal(result.status, 'FAIL'); assert.equal(result.privacy_failures, 1);
    assert.ok(!JSON.stringify(result).includes('SYNTHETIC_PRIVATE_CANARY'));
  }
});

test('post-answer revocation requires answer erasure and no dispatch', () => {
  const item = expected(); item.dispatch = { allowed: false, memory_ids: [], invalid_tokens: ['memory-a'] };
  item.answer = { behavior: 'blocked', required_facts: [], forbidden_facts: ['SYNTHETIC_PRIVATE_CANARY'], required_citations: [], discarded: true };
  const value = output('answer');
  value.dispatch.allowed = false; value.dispatch.memory_ids = []; value.dispatch.invalid_tokens = ['memory-a'];
  value.answer.text = null; value.answer.discarded = true;
  assert.equal(checker.evaluate(value, item, 'answer', 'offline_fixture').hard_gates_pass, true);
  value.answer.text = 'SYNTHETIC_PRIVATE_CANARY';
  const failure = checker.evaluate(value, item, 'answer', 'offline_fixture');
  assert.equal(failure.hard_gates_pass, false);
  assert.ok(!JSON.stringify(failure).includes('SYNTHETIC_PRIVATE_CANARY'));
});

test('malformed and zero-case gold cannot define an empty successful run', () => {
  for (const cases of [[], [expected(), expected()]]) {
    assert.throws(() => checker.validateExpectations({ schema_version: 1, cases }));
  }
  const value = expected(); delete value.expected_sources;
  assert.throws(() => checker.validateExpectations({ schema_version: 1, cases: [value] }));
});

function local(value) {
  value.mode = 'local_model';
  value.calls = { embedding_requests: 1, embedding_texts: 2, chat_requests: value.suite === 'answer' ? 1 : 0 };
  value.embedded_memory_ids = ['memory-a'];
  value.model_identity.embedding = { profile_id: 'synthetic-profile', model: 'synthetic-model',
    model_digest_sha256: 'a'.repeat(64), api_base_sha256: 'b'.repeat(64), dimensions: 3 };
  if (value.suite === 'answer') {
    value.dispatch.model_called = true; value.answer.mode = 'local_model';
    value.model_identity.chat = { model: 'synthetic-chat', model_digest_sha256: 'c'.repeat(64), api_base_sha256: 'd'.repeat(64) };
  }
  return value;
}

test('local retrieval miss is quality failure, not privacy failure', () => {
  const value = local(output()); value.retrieved = [];
  value.dispatch.allowed = false; value.dispatch.memory_ids = [];
  const result = checker.evaluate(value, expected(), 'retrieval', 'local_model');
  assert.equal(result.hard_gates_pass, true);
  assert.equal(result.retrieval_quality_pass, false);
  assert.equal(result.recall_at_k, 0);
});

test('real-mode NOT_RUN cannot impersonate retrieval or answer execution', () => {
  const embedding = local(output()); embedding.calls.embedding_requests = 0;
  embedding.calls.embedding_texts = 0; embedding.embedded_memory_ids = [];
  assert.equal(checker.evaluate(embedding, expected(), 'retrieval', 'local_model').hard_gates_pass, false);
  const answer = local(output('answer')); answer.calls.chat_requests = 0;
  answer.dispatch.model_called = false; answer.answer.mode = 'template';
  assert.equal(checker.evaluate(answer, expected(), 'answer', 'local_model').hard_gates_pass, false);
});

test('structured failed rows preserve quality categories in the final FAIL report', () => {
  const data = report(); data.config.providers[0].config.mode = 'local_model';
  const value = local(output()); value.retrieved = [];
  value.dispatch.allowed = false; value.dispatch.memory_ids = [];
  const row = data.results.results[0]; row.response.output = JSON.stringify(value);
  const checked = checker.evaluate(value, expected(), 'retrieval', 'local_model');
  row.success = false; row.failureReason = 1; row.score = 0;
  row.gradingResult.pass = false; row.gradingResult.score = 0;
  Object.assign(row.gradingResult.componentResults[0], { pass: false, score: 0, metadata: { gate_version: 1, ...checked } });
  data.results.stats = { successes: 0, failures: 1, errors: 0 };
  const result = inspectReport(data, { ...options(), mode: 'local_model' });
  assert.equal(result.status, 'FAIL'); assert.equal(result.privacy_failures, 0);
  assert.equal(result.retrieval_quality_failures, 1); assert.equal(result.evaluated_pairs, 1);
});

test('profile drift between valid local rows cannot be aggregated', () => {
  const cases = [expected('case-a'), expected('case-b')];
  const data = report('retrieval', cases); data.config.providers[0].config.mode = 'local_model';
  for (const [index, row] of data.results.results.entries()) {
    const value = local(output('retrieval', cases[index].id));
    if (index) value.model_identity.embedding.model = 'different-model';
    row.response.output = JSON.stringify(value);
  }
  const result = inspectReport(data, { ...options('retrieval', cases), mode: 'local_model' });
  assert.equal(result.status, 'FAIL'); assert.equal(result.reason, 'model_identity_drift');
});

test('CLI rejects malformed JSON without exposing raw report content', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'semantic-gate-test-'));
  const filename = path.join(directory, 'report.json');
  try {
    fs.writeFileSync(filename, '{SYNTHETIC_PRIVATE_CANARY', { mode: 0o600 });
    const processResult = spawnSync(process.execPath, [fileURLToPath(new URL('./report_gate.mjs', import.meta.url)),
      '--report', filename, '--providers', 'core-semantic', '--suite', 'retrieval'], { encoding: 'utf8' });
    assert.equal(processResult.status, 1);
    assert.ok(!processResult.stdout.includes('SYNTHETIC_PRIVATE_CANARY'));
    assert.equal(JSON.parse(processResult.stdout).quality_evidence, false);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});
