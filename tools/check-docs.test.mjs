import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { checkText, checkRepository } from './check-docs.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'core-docs-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}

test('accepts real local targets and ignores external links and anchors', t => {
  const root = fixture(t);
  writeFileSync(join(root, 'target.md'), '# Target\n');
  assert.deepEqual(checkText(root, 'README.md', '[local](target.md#section) [web](https://example.com) [anchor](#x)\n'), []);
});
test('rejects missing image targets', t => {
  assert.match(checkText(fixture(t), 'a.md', '![image](missing.png)\n')[0], /missing local target/);
});
test('rejects links escaping repository', t => {
  assert.match(checkText(fixture(t), 'a.md', '[escape](../outside.md)\n')[0], /escapes repository/);
});
test('handles malformed URL encoding as validation failure', t => {
  assert.match(checkText(fixture(t), 'a.md', '[bad](%ZZ)\n')[0], /invalid link encoding/);
});
test('checks line endings, whitespace and final newline', t => {
  const errors = checkText(fixture(t), 'a.md', 'text \r\nend');
  assert.equal(errors.length, 3);
});
test('rejects malformed JSON and accepts valid JSON', t => {
  const root = fixture(t);
  assert.match(checkText(root, 'a.json', '{oops}\n')[0], /invalid JSON/);
  assert.deepEqual(checkText(root, 'a.json', '{}\n'), []);
});
test('empty tracked file set is not a pass', t => {
  const root = fixture(t);
  execFileSync('git', ['init', '-q'], { cwd: root });
  assert.throws(() => checkRepository(root), /No tracked/);
});
test('CLI checks tracked files and returns a failing exit code for broken links', t => {
  const root = fixture(t);
  execFileSync('git', ['init', '-q'], { cwd: root });
  writeFileSync(join(root, 'README.md'), '[missing](missing.md)\n');
  execFileSync('git', ['add', 'README.md'], { cwd: root });
  const script = fileURLToPath(new URL('./check-docs.mjs', import.meta.url));
  const failed = spawnSync(process.execPath, [script], { cwd: root, encoding: 'utf8' });
  assert.equal(failed.status, 1);
  assert.match(failed.stderr, /missing local target/);
  writeFileSync(join(root, 'missing.md'), '# Found\n');
  const passed = spawnSync(process.execPath, [script], { cwd: root, encoding: 'utf8' });
  assert.equal(passed.status, 0);
});
