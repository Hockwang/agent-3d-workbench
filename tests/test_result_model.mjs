import test from 'node:test';
import assert from 'node:assert/strict';
import { resultGroups, primaryArtifact, resultIdentity, thumbnailArtifact } from '../studio/web/result-model.js';

const task = (id, work, variant, finished) => ({id, title:id, status:'completed', finished, artifacts:[{name:'scene.glb', meshes:2}], result:{work_id:work, work_title:'Cup', variant, version:id}});
test('latest delivery keeps independent local/generated/split variants and folds older revisions', () => {
  const groups = resultGroups([task('L1','cup','Local',1), task('G1','cup','Generated',2), task('S1','cup','Split',3), task('G2','cup','Generated',4), task('other','head','Local',0)]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].latest.map(t=>t.id), ['G2','S1','L1']);
  assert.deepEqual(groups[0].older.map(t=>t.id), ['G1']);
  assert.equal(groups[1].id, 'work:head');
});
test('legacy rebuild lineage groups without guessing from similar names', () => {
  const base = {...task('a',null,'',1), result:undefined};
  const next = {...task('b',null,'',2), result:undefined, source_task:'a'};
  const unrelated = {...task('c',null,'',3), result:undefined, title:'a'};
  const groups = resultGroups([base,next,unrelated]);
  assert.equal(groups.length,2);
  assert.deepEqual(groups[1].older.map(t=>t.id), ['a']);
});
test('explicit primary and thumbnail are bound to artifacts; preview identity includes actual file', () => {
  const data = task('v1','cup','Split',1);
  data.artifacts.push({name:'display.glb'},{name:'preview.png'},{name:'reference.png'});
  data.result.primary='display.glb'; data.result.thumbnail='preview.png';
  assert.equal(primaryArtifact(data.artifacts,data.result).name,'display.glb');
  assert.equal(thumbnailArtifact(data).name,'preview.png');
  assert.match(resultIdentity(data, {name:'inspection/cutaway.glb'}).detail,/inspection\/cutaway.glb/);
  data.result.primary='https://outside/model.glb'; data.result.thumbnail='https://outside/image.png';
  assert.equal(primaryArtifact(data.artifacts,data.result).name,'scene.glb');
  assert.equal(thumbnailArtifact(data).name,'preview.png');
});
