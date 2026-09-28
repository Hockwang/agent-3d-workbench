import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('offline assembly bundle has one intact executable script and no external module', () => {
  const html = readFileSync(new URL('../studio/app/dist/assembly-review.html', import.meta.url), 'utf8');
  const scripts = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 2, 'a replacement-string $& must not reinsert module tags inside the bundled script');
  assert.match(scripts[0][1], /application\/json/);
  assert.equal(scripts[0][2], '__ASSEMBLY_REVIEW_DATA__');
  assert.doesNotThrow(() => new vm.Script(scripts[1][2]));
  assert.doesNotMatch(html, /<script[^>]+src=/);
});
