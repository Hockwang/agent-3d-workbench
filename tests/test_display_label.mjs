import test from 'node:test';
import assert from 'node:assert/strict';
import { displayLabel } from '../studio/web/display-label.js';
import { setLocale } from '../studio/web/i18n.js';
import { resultIdentity, resultGroups } from '../studio/web/result-model.js';
import { modelLabel } from '../studio/web/model-browser.js';

test('legacy task and imported motion names use capability labels in either language', () => {
  setLocale('zh-CN');
  assert.equal(displayLabel('雷伊 · Puppeteer + UniMate'), '雷伊 · 绑骨方案 A + 动作生成');
  assert.equal(displayLabel('Kimodo / SkinTokens / P3-SAM / Cubepart'), '动作生成 / 绑骨方案 B / 分件方案 A / 分件方案 B');
  assert.equal(displayLabel('unimate_walk - 30 fps'), '动作生成_walk - 30 fps');
  setLocale('en');
  assert.equal(displayLabel('UniMate walk - 30 fps'), 'Motion generation walk - 30 fps');
  assert.equal(displayLabel('Puppeteer / SkinTokens'), 'Rigging option A / Rigging option B');
  setLocale('zh-CN');
});

test('unrelated user labels and non-string values retain their meaning', () => {
  for (const value of ['雷伊', 'MyKimodoAsset', 'unimateX', 'robot-walk', 3, null, undefined]) {
    assert.equal(displayLabel(value), value);
  }
  assert.equal(displayLabel('UniRig / RigAnything / PartCrafter'), '自动绑骨 / 自动绑骨 / 自动分件');
});

test('result cards format old metadata without rewriting downloads, IDs, or evidence', () => {
  const data = { id: 'stable-task', status: 'completed', title: '雷伊 · UniMate',
    artifacts: [{ id: 'stable-artifact', name: 'unimate_walk.glb' }],
    result: { variant: 'Puppeteer', note: 'UniMate · preview only', primary: 'unimate_walk.glb' } };
  const original = structuredClone(data), identity = resultIdentity(data);
  assert.equal(identity.title, '雷伊 · 动作生成');
  assert.equal(identity.note, '动作生成 · preview only');
  assert.doesNotMatch(identity.detail, /unimate|puppeteer/i);
  assert.equal(resultGroups([data])[0].title, '雷伊 · 动作生成');
  assert.deepEqual(data, original);
});

test('new model cards format saved titles and file labels without mutating artifacts', () => {
  const artifact = { id: 'unchanged', name: 'models/unimate_walk.glb' };
  const original = structuredClone(artifact);
  setLocale('zh-CN');
  assert.equal(modelLabel(artifact), '动作生成 walk');
  assert.equal(modelLabel(artifact, 'Kimodo walking'), '动作生成 walking');
  assert.deepEqual(artifact, original);
});
