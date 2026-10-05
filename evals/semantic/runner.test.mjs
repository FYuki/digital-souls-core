import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, mkdtempSync, readdirSync, rmdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { configuration } = require('./config.cjs');
const corpus = JSON.parse(readFileSync(path.join(directory, 'cases.json'), 'utf8'));
const repo = path.resolve(directory, '../..');

for (const suite of ['retrieval', 'answer']) {
  test(`${suite}: 全caseと固定provider・hard gateを省略しない`, () => {
    const config = configuration(suite, 'offline_fixture');
    assert.deepEqual(config.tests.map((row) => row.vars.case_id), corpus.cases.map((row) => row.id));
    assert(config.tests.every((row) => Object.keys(row.vars).join() === 'case_id'));
    assert.equal(config.providers.length, 1);
    assert.equal(config.providers[0].label, 'core-semantic');
    assert.equal(config.providers[0].id, `file://${path.join(directory, 'provider.py')}`);
    assert.deepEqual(config.providers[0].config, { suite, mode: 'offline_fixture' });
    assert.equal(config.defaultTest.assert[0].metric, 'semantic-hard-gates');
    assert.equal(config.sharing, false);
    assert.deepEqual(config.prompts, ['{{case_id}}']);
  });
}

test('実モデルconfigは明示profileなしにfixtureや既定providerへ切り替わらない', () => {
  const previous = process.env.DSC_SEMANTIC_PROFILE;
  delete process.env.DSC_SEMANTIC_PROFILE;
  try {
    assert.throws(() => configuration('retrieval', 'local_model'), /NOT_RUN/);
    process.env.DSC_SEMANTIC_PROFILE = '/synthetic/profile.json';
    assert.equal(configuration('answer', 'local_model').providers[0].config.profile_path, '/synthetic/profile.json');
  } finally {
    if (previous === undefined) delete process.env.DSC_SEMANTIC_PROFILE;
    else process.env.DSC_SEMANTIC_PROFILE = previous;
  }
});

test('NodeのCJS/ESM・fetch・TCP・TLS・UDP・DNS通信は接続前に拒否する', () => {
  const script = `
    const assert=require('node:assert/strict');
    const blocked=/Node network access is disabled/;
    (async()=>{
      await assert.rejects(fetch('http://127.0.0.1:9'),blocked);
      for(const name of ['node:http','node:https']){
        assert.throws(()=>require(name).request('http://127.0.0.1:9'),blocked);
        assert.throws(()=>require(name).get('http://127.0.0.1:9'),blocked);
      }
      assert.throws(()=>require('node:http2').connect('http://127.0.0.1:9'),blocked);
      assert.throws(()=>require('node:net').createConnection({host:'127.0.0.1',port:9}),blocked);
      assert.throws(()=>new (require('node:net').Socket)().connect(9,'127.0.0.1'),blocked);
      assert.throws(()=>require('node:tls').connect(9,'127.0.0.1'),blocked);
      assert.throws(()=>require('node:dgram').createSocket('udp4'),blocked);
      assert.throws(()=>require('node:dns').lookup('localhost',()=>{}),blocked);
      await assert.rejects(require('node:dns').promises.lookup('localhost'),blocked);
      assert.throws(()=>new (require('node:dns').Resolver)().resolve('localhost',()=>{}),blocked);
      const esm=await import('node:net');
      assert.throws(()=>esm.createConnection({host:'127.0.0.1',port:9}),blocked);
    })().catch(()=>process.exit(1));
  `;
  const child = spawnSync(process.execPath, ['--require', path.join(directory, 'network_guard.cjs'), '-e', script], {
    env: { PATH: '/usr/bin:/bin' }, encoding: 'utf8', timeout: 10000,
  });
  assert.equal(child.status, 0, child.stderr);
});

for (const args of [['local-model'], ['local-model', '--execute-local-model'], ['local-model', '--profile', '/synthetic/profile.json']]) {
  test(`明示実行条件不足はNOT_RUN・副作用なし: ${args.join(' ')}`, () => {
    const cwd = mkdtempSync(path.join(os.tmpdir(), 'core-semantic-runner-test.'));
    try {
      const result = spawnSync('/bin/bash', [path.join(repo, 'tools/evaluate-semantic.sh'), ...args], {
        cwd, env: { PATH: '/usr/bin:/bin' }, encoding: 'utf8', timeout: 10000,
      });
      assert.equal(result.status, 3, result.stderr);
      assert.equal(JSON.parse(result.stdout).status, 'NOT_RUN');
      assert.deepEqual(readdirSync(cwd), []);
    } finally { rmdirSync(cwd); }
  });
}

test('fixture modeは実モデル設定を拒否する', () => {
  const result = spawnSync('/bin/bash', [path.join(repo, 'tools/evaluate-semantic.sh'), 'fixture', '--execute-local-model'], {
    env: { PATH: '/usr/bin:/bin' }, encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /rejects model settings/);
});

test('依存lockはpromptfoo exact pinと公式registryのintegrity付き配布物のみ', () => {
  const pkg = JSON.parse(readFileSync(path.join(directory, 'package.json'), 'utf8'));
  const lock = JSON.parse(readFileSync(path.join(directory, 'package-lock.json'), 'utf8'));
  assert.equal(pkg.devDependencies.promptfoo, '0.117.2');
  assert.equal(lock.packages['node_modules/promptfoo'].version, '0.117.2');
  assert.equal(lock.packages['node_modules/better-sqlite3'].version, '11.10.0');
  for (const [name, dependency] of Object.entries(lock.packages)) {
    if (!name) continue;
    assert.match(dependency.resolved, /^https:\/\/registry\.npmjs\.org\//);
    assert.match(dependency.integrity, /^sha512-/);
  }
});
