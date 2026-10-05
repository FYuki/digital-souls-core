'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { isDeepStrictEqual } = require('node:util');

const METRIC = 'semantic-hard-gates';
const PROVIDER = 'core-semantic';
const IDENTIFIER = /^[A-Za-z0-9_.:-]{1,128}$/;
class GateError extends Error {}

function demand(test, code) {
  if (!test) throw new GateError(code);
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function keys(value, expected, code) {
  demand(object(value) && isDeepStrictEqual(Object.keys(value).sort(), [...expected].sort()), code);
}

function ids(value, code) {
  demand(Array.isArray(value) && value.every((id) => typeof id === 'string' && IDENTIFIER.test(id)), code);
  demand(new Set(value).size === value.length, code);
}

function strings(value, code) {
  demand(Array.isArray(value) && value.every((text) => typeof text === 'string' && text.length > 0), code);
}

function finite(value, code) {
  if (typeof value === 'number') demand(Number.isFinite(value), code);
  else if (Array.isArray(value)) value.forEach((item) => finite(item, code));
  else if (object(value)) Object.values(value).forEach((item) => finite(item, code));
}

function binding(value) {
  keys(value, ['subject', 'client', 'audience', 'character_id'], 'binding_shape');
  demand(Object.values(value).every((item) => typeof item === 'string' && IDENTIFIER.test(item)), 'binding_value');
}

function source(value) {
  keys(value, ['source_id', 'revision', 'epoch', 'conversation_id', 'turn_revision', 'message_index'], 'source_shape');
  demand(typeof value.source_id === 'string' && typeof value.conversation_id === 'string'
    && IDENTIFIER.test(value.source_id) && IDENTIFIER.test(value.conversation_id), 'source_identifier');
  for (const field of ['revision', 'turn_revision']) demand(Number.isSafeInteger(value[field]) && value[field] > 0, 'source_revision');
  for (const field of ['epoch', 'message_index']) demand(Number.isSafeInteger(value[field]) && value[field] >= 0, 'source_position');
}

function validateExpectations(data) {
  demand(object(data) && data.schema_version === 1 && Array.isArray(data.cases) && data.cases.length > 0, 'expectations_missing');
  const cases = new Map();
  for (const item of data.cases) {
    keys(item, ['id', 'category', 'binding', 'expected_ids', 'relevant_ids', 'min_recall',
      'forbidden_ids', 'expected_sources', 'input_rejected', 'rejected_memory_ids', 'dispatch', 'answer'], 'expectation_shape');
    demand(typeof item.id === 'string' && IDENTIFIER.test(item.id) && !cases.has(item.id), 'case_duplicate');
    demand(typeof item.category === 'string' && item.category.length > 0, 'category_missing');
    binding(item.binding);
    for (const field of ['expected_ids', 'relevant_ids', 'forbidden_ids', 'rejected_memory_ids']) ids(item[field], 'expectation_ids');
    demand(typeof item.min_recall === 'number' && Number.isFinite(item.min_recall) && item.min_recall >= 0 && item.min_recall <= 1, 'recall_threshold');
    demand(typeof item.input_rejected === 'boolean' && object(item.expected_sources), 'expectation_source');
    for (const [id, sources] of Object.entries(item.expected_sources)) {
      demand(IDENTIFIER.test(id) && Array.isArray(sources) && sources.length > 0, 'expectation_source');
      sources.forEach(source);
      demand(new Set(sources.map((s) => s.source_id)).size === sources.length, 'source_duplicate');
    }
    for (const id of [...item.expected_ids, ...item.relevant_ids]) demand(Object.hasOwn(item.expected_sources, id) && !item.forbidden_ids.includes(id), 'expectation_conflict');
    keys(item.dispatch, ['allowed', 'memory_ids', 'invalid_tokens'], 'expectation_dispatch');
    demand(typeof item.dispatch.allowed === 'boolean', 'expectation_dispatch');
    ids(item.dispatch.memory_ids, 'expectation_dispatch');
    ids(item.dispatch.invalid_tokens, 'expectation_dispatch');
    demand(item.dispatch.memory_ids.every((id) => item.expected_ids.includes(id)), 'expectation_dispatch');
    demand(item.dispatch.invalid_tokens.every((id) => item.expected_ids.includes(id)), 'expectation_dispatch');
    demand(item.dispatch.allowed ? item.dispatch.memory_ids.length > 0 && item.dispatch.invalid_tokens.length === 0 : item.dispatch.memory_ids.length === 0, 'expectation_dispatch');
    keys(item.answer, ['behavior', 'required_facts', 'forbidden_facts', 'required_citations', 'discarded'], 'expectation_answer');
    demand(['grounded', 'abstain', 'blocked'].includes(item.answer.behavior) && typeof item.answer.discarded === 'boolean', 'expectation_answer');
    strings(item.answer.required_facts, 'expectation_answer');
    strings(item.answer.forbidden_facts, 'expectation_answer');
    ids(item.answer.required_citations, 'expectation_answer');
    demand(item.answer.required_citations.every((id) => item.expected_ids.includes(id)), 'expectation_answer');
    if (item.input_rejected) demand(item.expected_ids.length === 0 && !item.dispatch.allowed && item.answer.behavior === 'blocked', 'expectation_rejection');
    cases.set(item.id, item);
  }
  return cases;
}

function loadExpectations(filename = path.join(__dirname, 'expectations.json')) {
  const stat = fs.lstatSync(filename);
  demand(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 4 * 1024 * 1024, 'expectations_file');
  return validateExpectations(JSON.parse(fs.readFileSync(filename, 'utf8')));
}

function evaluate(output, expected, suite, mode) {
  const result = { hard_gates_pass: false, retrieval_quality_pass: false,
    answer_quality_pass: suite === 'retrieval' ? null : false, recall_at_k: null,
    quality_evidence: false, reason: 'output_invalid' };
  try {
    demand(['retrieval', 'answer'].includes(suite) && ['offline_fixture', 'local_model'].includes(mode), 'run_mode');
    const value = typeof output === 'string' ? JSON.parse(output) : output;
    keys(value, ['schema_version', 'case_id', 'provider_id', 'suite', 'mode', 'quality_evidence',
      'input_rejected', 'retrieved', 'dispatch', 'answer', 'rejected_memory_ids', 'calls',
      'embedded_memory_ids', 'embedding_input_ids', 'model_identity'], 'output_shape');
    finite(value, 'nonfinite_output');
    demand(value.schema_version === 1 && value.case_id === expected.id && value.provider_id === PROVIDER, 'output_identity');
    demand(value.suite === suite && value.mode === mode && value.quality_evidence === false, 'evidence_mode');
    demand(value.input_rejected === expected.input_rejected, 'input_rejection');
    demand(Array.isArray(value.retrieved), 'retrieved_shape');
    const retrieved = value.retrieved.map((hit) => hit?.memory_id);
    ids(retrieved, 'retrieved_duplicate');
    demand(retrieved.length <= 16, 'retrieved_limit');
    for (const hit of value.retrieved) {
      keys(hit, ['memory_id', 'revision', 'generation', 'score', 'binding', 'sources'], 'hit_shape');
      demand(Number.isSafeInteger(hit.revision) && hit.revision > 0 && Number.isSafeInteger(hit.generation) && hit.generation > 0, 'hit_revision');
      demand(typeof hit.score === 'number' && hit.score > 0 && hit.score <= 1 + 1e-6, 'hit_score');
      binding(hit.binding);
      demand(isDeepStrictEqual(hit.binding, expected.binding), 'scope_leak');
      demand(Object.hasOwn(expected.expected_sources, hit.memory_id), 'unknown_memory');
      demand(!expected.forbidden_ids.includes(hit.memory_id), 'forbidden_memory');
      demand(Array.isArray(hit.sources) && hit.sources.length > 0, 'source_missing');
      hit.sources.forEach(source);
      demand(isDeepStrictEqual(hit.sources, expected.expected_sources[hit.memory_id]), 'source_mismatch');
    }
    ids(value.rejected_memory_ids, 'rejected_ids');
    demand(isDeepStrictEqual([...value.rejected_memory_ids].sort(), [...expected.rejected_memory_ids].sort()), 'rejected_mismatch');
    keys(value.calls, ['embedding_requests', 'embedding_texts', 'chat_requests'], 'calls_shape');
    for (const count of Object.values(value.calls)) demand(Number.isSafeInteger(count) && count >= 0, 'calls_value');
    ids(value.embedded_memory_ids, 'embedded_ids');
    ids(value.embedding_input_ids, 'embedding_input_ids');
    demand(value.embedding_input_ids.every((id) => Object.hasOwn(expected.expected_sources, id)
      && !expected.forbidden_ids.includes(id)), 'embedding_input_leak');
    demand(value.embedded_memory_ids.every((id) => Object.hasOwn(expected.expected_sources, id) && !expected.forbidden_ids.includes(id)), 'embedding_leak');
    demand(value.embedded_memory_ids.every((id) => value.embedding_input_ids.includes(id)), 'embedding_input_mismatch');
    if (value.calls.embedding_requests === 0) demand(value.calls.embedding_texts === 0 && value.embedded_memory_ids.length === 0, 'calls_mismatch');
    else demand(value.calls.embedding_texts >= value.embedded_memory_ids.length && value.calls.embedding_texts > 0, 'calls_mismatch');
    if (mode === 'offline_fixture') demand(Object.values(value.calls).every((count) => count === 0) && value.embedded_memory_ids.length === 0, 'fixture_real_call');
    keys(value.model_identity, ['embedding', 'chat'], 'identity_shape');
    for (const kind of ['embedding', 'chat']) {
      const identity = value.model_identity[kind];
      if (identity === null) {
        demand(value.calls[kind === 'embedding' ? 'embedding_requests' : 'chat_requests'] === 0, 'identity_missing');
        continue;
      }
      keys(identity, kind === 'embedding'
        ? ['profile_id', 'model', 'model_digest_sha256', 'api_base_sha256', 'dimensions']
        : ['model', 'model_digest_sha256', 'api_base_sha256'], 'identity_shape');
      demand(typeof identity.model === 'string' && /^[A-Za-z0-9_.:/-]{1,128}$/.test(identity.model), 'identity_model');
      for (const field of ['model_digest_sha256', 'api_base_sha256']) demand(typeof identity[field] === 'string' && /^[a-f0-9]{64}$/.test(identity[field]), 'identity_digest');
      if (kind === 'embedding') demand(typeof identity.profile_id === 'string'
        && IDENTIFIER.test(identity.profile_id) && Number.isSafeInteger(identity.dimensions)
        && identity.dimensions >= 1 && identity.dimensions <= 2000, 'identity_dimensions');
    }
    if (mode === 'offline_fixture') demand(value.model_identity.embedding === null && value.model_identity.chat === null, 'fixture_identity');
    if (mode === 'local_model') demand(value.model_identity.embedding !== null
      && (suite === 'retrieval' || value.model_identity.chat !== null), 'configured_identity_missing');
    if (mode === 'local_model' && !value.input_rejected && Object.keys(expected.expected_sources).length > 0) {
      demand(value.calls.embedding_requests > 0 && value.calls.embedding_texts > 0
        && value.model_identity.embedding !== null, 'embedding_not_run');
    }
    keys(value.dispatch, ['allowed', 'memory_ids', 'invalid_tokens', 'revalidated_before', 'revalidated_after', 'model_called'], 'dispatch_shape');
    for (const field of ['allowed', 'revalidated_before', 'revalidated_after', 'model_called']) demand(typeof value.dispatch[field] === 'boolean', 'dispatch_value');
    ids(value.dispatch.memory_ids, 'dispatch_ids');
    ids(value.dispatch.invalid_tokens, 'dispatch_tokens');
    const invalidIds = mode === 'offline_fixture' ? expected.dispatch.invalid_tokens
      : expected.dispatch.invalid_tokens.filter((id) => retrieved.includes(id));
    const allowed = mode === 'offline_fixture' ? expected.dispatch.allowed
      : !value.input_rejected && retrieved.length > 0 && invalidIds.length === 0;
    const dispatchIds = mode === 'offline_fixture' ? expected.dispatch.memory_ids : allowed ? retrieved : [];
    demand(value.dispatch.allowed === allowed, 'dispatch_permission');
    demand(isDeepStrictEqual(value.dispatch.memory_ids, dispatchIds), 'dispatch_mismatch');
    demand(isDeepStrictEqual([...value.dispatch.invalid_tokens].sort(), [...invalidIds].sort()), 'invalid_tokens');
    demand(value.dispatch.memory_ids.every((id) => retrieved.includes(id) && !expected.forbidden_ids.includes(id)), 'dispatch_leak');
    if (!value.input_rejected) demand(value.dispatch.revalidated_before && value.dispatch.revalidated_after, 'revalidation_missing');
    demand(value.calls.chat_requests === (value.dispatch.model_called ? 1 : 0), 'chat_calls_mismatch');
    keys(value.answer, ['text', 'mode', 'discarded'], 'answer_shape');
    demand(value.answer.text === null || typeof value.answer.text === 'string', 'answer_text');
    demand(['template', 'not_run', 'local_model'].includes(value.answer.mode) && typeof value.answer.discarded === 'boolean', 'answer_mode');
    if (mode === 'offline_fixture') demand(!value.dispatch.model_called && value.answer.mode !== 'local_model', 'fixture_model_claim');
    const text = value.answer.text || '';
    demand(!expected.answer.forbidden_facts.some((fact) => text.includes(fact)), 'answer_leak');
    const citations = [...text.matchAll(/\[([A-Za-z0-9_.:-]{1,128})\]/g)].map((match) => match[1]);
    demand(citations.every((id) => value.dispatch.memory_ids.includes(id) && !expected.forbidden_ids.includes(id)), 'citation_leak');
    if (suite === 'retrieval') {
      demand(value.answer.text === null && value.answer.mode === 'not_run' && !value.answer.discarded && !value.dispatch.model_called, 'retrieval_answer');
    } else {
      const discarded = mode === 'offline_fixture' ? expected.answer.discarded
        : expected.answer.discarded && invalidIds.length > 0;
      const behavior = mode === 'offline_fixture' ? expected.answer.behavior
        : value.input_rejected || invalidIds.length > 0 ? 'blocked' : retrieved.length ? 'grounded' : 'abstain';
      demand(value.answer.discarded === discarded, 'discarded_mismatch');
      const answerMode = behavior === 'abstain' ? 'template' : behavior === 'blocked' && !discarded
        ? 'not_run' : mode === 'offline_fixture' ? 'template' : 'local_model';
      demand(value.answer.mode === answerMode, 'answer_execution_mode');
      if (behavior === 'blocked') demand(value.answer.text === null && !value.dispatch.allowed, 'revocation_leak');
      else if (behavior === 'abstain') demand(!value.dispatch.allowed && retrieved.length === 0 && !value.dispatch.model_called, 'abstention_leak');
      else demand(value.dispatch.allowed && retrieved.length > 0 && text.length > 0, 'grounding_missing');
      if (mode === 'local_model') {
        const generated = !value.input_rejected && retrieved.length > 0 && (invalidIds.length === 0 || discarded);
        demand(value.dispatch.model_called === generated && value.calls.chat_requests === (generated ? 1 : 0), 'answer_not_run');
        if (generated) demand(value.answer.mode === 'local_model' && value.model_identity.chat !== null, 'answer_identity_missing');
      }
    }
    if (value.input_rejected) demand(retrieved.length === 0 && !value.dispatch.allowed && !value.dispatch.model_called && Object.values(value.calls).every((count) => count === 0), 'rejected_execution');
    result.hard_gates_pass = true;
    const relevantCount = expected.relevant_ids.filter((id) => retrieved.includes(id)).length;
    result.recall_at_k = expected.relevant_ids.length ? relevantCount / expected.relevant_ids.length : null;
    result.retrieval_quality_pass = mode === 'offline_fixture'
      ? isDeepStrictEqual(retrieved, expected.expected_ids)
      : (result.recall_at_k === null ? retrieved.length === 0 : result.recall_at_k >= expected.min_recall)
        && value.retrieved.every((hit, index) => index === 0 || value.retrieved[index - 1].score >= hit.score);
    if (suite === 'answer') {
      result.answer_quality_pass = expected.answer.required_facts.every((fact) => text.includes(fact))
        && expected.answer.required_citations.every((id) => citations.includes(id));
      if (expected.answer.behavior === 'abstain') result.answer_quality_pass &&= text.length > 0;
    }
    result.reason = result.retrieval_quality_pass && result.answer_quality_pass !== false ? 'conformant' : 'quality_mismatch';
  } catch (error) {
    result.reason = error instanceof SyntaxError ? 'output_json' : error instanceof GateError ? error.message : 'output_invalid';
  }
  return result;
}

function assertion(output, context) {
  let checked = { hard_gates_pass: false, retrieval_quality_pass: false,
    answer_quality_pass: false, recall_at_k: null, quality_evidence: false, reason: 'assertion_input' };
  try {
    keys(context.vars, ['case_id'], 'case_vars');
    const expected = loadExpectations().get(context.vars.case_id);
    demand(expected !== undefined, 'case_unknown');
    const parsed = typeof output === 'string' ? JSON.parse(output) : output;
    checked = evaluate(parsed, expected, parsed.suite, parsed.mode);
  } catch (error) {
    checked.reason = error instanceof SyntaxError ? 'output_json' : 'assertion_input';
  }
  const pass = checked.hard_gates_pass && checked.retrieval_quality_pass && checked.answer_quality_pass !== false;
  return { pass, score: pass ? 1 : 0, reason: checked.reason,
    assertion: { type: 'javascript', metric: METRIC, value: 'file://./assertions.cjs' },
    namedScores: { privacy: checked.hard_gates_pass ? 1 : 0,
      retrieval: checked.retrieval_quality_pass ? 1 : 0,
      ...(checked.answer_quality_pass === null ? {} : { answer: checked.answer_quality_pass ? 1 : 0 }) },
    metadata: { gate_version: 1, ...checked } };
}

module.exports = assertion;
Object.assign(module.exports, { METRIC, PROVIDER, GateError, evaluate, validateExpectations, loadExpectations, finite, demand, object, keys });
