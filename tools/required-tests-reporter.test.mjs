import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const reporter = new URL('./required-tests-reporter.mjs', import.meta.url).href;
const passing = "import {test} from 'node:test'; test('real', () => {});\n";
const cases = [
  ['registered passing test', [passing], 0],
  ['multiple passing files', [passing, passing], 0],
  ['passing suite with a registered test', ["import {describe,it} from 'node:test'; describe('suite', () => { it('real', () => {}); });"], 0],
  ['empty file', [''], 1],
  ['passing file cannot hide empty file', [passing, ''], 1],
  ['empty suite', ["import {describe} from 'node:test'; describe('empty', () => {});"], 1],
  ['all skipped', ["import {test} from 'node:test'; test.skip('skip', () => {});"], 1],
  ['one skipped among passing tests', [passing + "test.skip('skip', () => {});"], 1],
  ['todo', ["import {test} from 'node:test'; test.todo('later');"], 1],
  ['cancelled', ["import {test} from 'node:test'; test('cancelled', {signal: AbortSignal.abort()}, () => {});"], 1],
  ['assertion failure', ["import {test} from 'node:test'; test('fails', () => { throw Error('expected'); });"], 1],
  ['module load failure', ["throw Error('load failure');"], 1],
];

for (const [name, sources, expected] of cases) {
  test(`required test guard: ${name}`, t => {
    const root = mkdtempSync(join(tmpdir(), 'core-required-tests-'));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const files = sources.map((source, index) => {
      const file = join(root, `${index}.test.mjs`);
      writeFileSync(file, source);
      return file;
    });
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT; // Start an independent Node test runner.
    const result = spawnSync(process.execPath,
      ['--test', `--test-reporter=${reporter}`, ...files],
      { env, encoding: 'utf8', timeout: 10000 });
    assert.ifError(result.error);
    assert.equal(result.status, expected, result.stdout + result.stderr);
    assert.match(result.stdout, expected ? /FAIL: required tests/ : /registered required tests/);
  });
}
