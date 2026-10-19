import {test} from 'node:test';
import assert from 'node:assert/strict';
import {restoreCamera,captureCamera} from '../studio/web/session-view.js';
test('camera round trip validates finite vectors before mutating viewport',()=>{
  const v=initial=>({value:initial,toArray(){return this.value;},fromArray(a){this.value=a;}});
  const viewport={camera:{position:v([1,2,3]),up:v([0,0,1]),near:.01,far:1000,zoom:1,updateProjectionMatrix(){}},
    orbit:{target:v([0,0,0]),update(){}},loop:{invalidate(){}}};
  const saved=captureCamera(viewport);viewport.camera.position.value=[8,8,8];
  assert(restoreCamera(viewport,saved));assert.deepEqual(viewport.camera.position.value,[1,2,3]);
  assert(!restoreCamera(viewport,{...saved,position:[NaN,1,2]}));
  assert(!restoreCamera(viewport,{...saved,near:-1}));
  assert(!restoreCamera(viewport,{...saved,target:[1,2]}));
  assert.deepEqual(viewport.camera.position.value,[1,2,3]);
});
