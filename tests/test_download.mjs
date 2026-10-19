import test from 'node:test';
import assert from 'node:assert/strict';
import {readDownload} from '../studio/web/download.js';

test('download page reads only an artifact registered to the selected task', async()=>{
  let assetReads=0;
  const api={tasks:async id=>({task:{id,artifacts:[{id:'model',name:'output/model.glb',mime:'model/gltf-binary'}]}}),
    taskAsset:async(id,artifact)=>{assert.equal(id,'task-a');assert.equal(artifact.id,'model');assetReads++;return new Uint8Array([0,255]);}};
  const result=await readDownload(api,{kind:'task',id:'task-a',artifact:'model'});
  assert.deepEqual([...result.data],[0,255]);
  assert.equal(result.name,'output/model.glb');
  await assert.rejects(readDownload(api,{kind:'task',id:'task-a',artifact:'../../secret'}),/File not found/);
  assert.equal(assetReads,1);
});

test('laser and observation downloads use the same existing scoped transport and preserve failures', async()=>{
  const calls=[];
  const api={laser:async body=>{calls.push(body);return {base64:'AP8=',name:'sheet.svg',mime:'image/svg+xml'};},
    observe:async body=>{calls.push(body);return {report:{ready:true}};}};
  assert.deepEqual([...(await readDownload(api,{kind:'laser',id:'flow',artifact:'nest/sheet.svg'})).data],[0,255]);
  assert.deepEqual(JSON.parse((await readDownload(api,{kind:'observation',id:'run'})).data),{report:{ready:true}});
  assert.deepEqual(calls,[{action:'artifact',id:'flow',name:'nest/sheet.svg'},{action:'read',id:'run',image:false,detail:true}]);
  await assert.rejects(readDownload({}, {kind:'unknown'}),/Unsupported download/);
  await assert.rejects(readDownload({tasks:async()=>{throw new Error('workspace_mismatch');}},{kind:'task',id:'other'}),/workspace_mismatch/);
});
