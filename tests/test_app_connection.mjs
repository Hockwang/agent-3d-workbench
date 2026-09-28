import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {createMcpApi} from '../studio/app/api.js';
import {presentationFor, safeAreaFor} from '../studio/app/presentation.js';
import {t} from '../studio/web/i18n.js';
import {createSelectionContextSync} from '../studio/app/selection-context.js';

const main=(await readFile(new URL('../studio/app/main.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({workspaceId='task-a',connect,modelContext}={}) {
  const nodes=new Map(),calls=[],workspaces=[],contexts=[];
  const node=id=>{
    if(!nodes.has(id))nodes.set(id,{dataset:{workspaceId},hidden:true,disabled:false,textContent:'',
      classList:{toggle(){}},style:{setProperty(){}},querySelector:()=>node(id+' span')});
    return nodes.get(id);
  };
  let app,attempts=0;
  class App {
    constructor(){app=this;}
    async connect(...args){attempts++;await connect?.(attempts,...args);}
    async updateModelContext(payload){contexts.push(payload);await modelContext?.(payload);}
    getHostContext(){return {displayMode:'fullscreen',availableDisplayModes:['inline','fullscreen']};}
    async callServerTool(request){
      calls.push(request);
      if(request.name==='studio_open')return {_meta:{'studio/uiNonce':`nonce-${attempts}`},structuredContent:{ok:true,parts:[],workspace_id:request.arguments.workspace_id,workbench:{objects:[],selection:[]}}};
      return {structuredContent:{ok:true,parts:[],workspace_id:request.arguments.workspace_id,workbench:{objects:[],selection:[]}}};
    }
  }
  vm.runInNewContext(main,{
    App,THREE:{},createMcpApi,presentationFor,safeAreaFor,t,
    createSelectionContextSync,
    createWorkspace(api,options){const item={api,options,ready:Promise.resolve(),setState(){},setActive(value){this.active=value;},dispose(){}};workspaces.push(item);return item;},
    document:{getElementById:node,addEventListener(){},hidden:false},window:{addEventListener(){},innerWidth:1000},
    ResizeObserver:class {observe(){}disconnect(){}},requestAnimationFrame(){return 1;},cancelAnimationFrame(){},setTimeout(){return 1;},clearTimeout(){},
  });
  return {node,calls,workspaces,contexts,get app(){return app;},get attempts(){return attempts;}};
}

test('host startup and reconnect clear old context; workspace attaches only on explicit action',async()=>{
  const f=fixture();await tick();
  assert.deepEqual(f.contexts,[{content:[]}]);
  const options=f.workspaces[0].options;
  await options.onSelectionContext({mode:'edit',state:{workbench:{objects:[{id:'a',name:'body'}],selection:['a'],revision:1}}});
  assert.equal(f.contexts.length,1);
  await options.onAttachSelection();
  assert.equal(f.contexts.at(-1).structuredContent.selectedObjects[0].id,'a');
  f.app.onclose();await f.node('workspace-retry').onclick();
  assert.deepEqual(f.contexts.at(-1),{content:[]});
});

test('host teardown waits for the pending attachment and its removal',async()=>{
  let release;
  const f=fixture({modelContext:p=>p.structuredContent?new Promise(r=>{release=r;}):undefined});await tick();
  const options=f.workspaces[0].options;
  await options.onSelectionContext({mode:'edit',state:{workbench:{objects:[{id:'a',name:'body'}],selection:['a'],revision:1}}});
  const attaching=options.onAttachSelection();
  let closed=false;
  const closing=f.app.onteardown().then(()=>{closed=true;});
  await tick();assert.equal(closed,false);
  release();await Promise.all([attaching,closing]);
  assert.deepEqual(f.contexts.at(-1),{content:[]});
});

test('retry performs a new host handshake after initialization failed',async()=>{
  const f=fixture({connect:async n=>{if(n===1)throw Error('host initialization unavailable');}});
  await tick();assert.equal(f.attempts,1);assert.equal(f.workspaces.length,0);
  await f.node('workspace-retry').onclick();await tick();
  assert.equal(f.attempts,2);assert.equal(f.workspaces.length,1);
  assert.equal(f.workspaces[0].api.workspaceId,'task-a');assert.equal(f.node('workspace-error').hidden,true);
});

test('retry proactively refreshes the nonce via studio_open, and the fresh nonce reaches the next human write',async()=>{
  const f=fixture({connect:async n=>{if(n===1)throw Error('host initialization unavailable');}});
  await tick();
  await f.node('workspace-retry').onclick();await tick();
  assert.deepEqual(f.calls.map(c=>c.name),['studio_open','studio_get_state']);
  assert.equal(f.calls[0].arguments.workspace_id,'task-a');
  await f.workspaces[0].api.select(['body']);
  const write=f.calls.find(c=>c.name==='studio_ui_action');
  assert.equal(write.arguments.ui_nonce,'nonce-2');
});

test('unscoped launcher binds from host tool input even without tool result',async()=>{
  const f=fixture({workspaceId:''});await tick();assert.equal(f.workspaces.length,0);
  f.app.ontoolinput({arguments:{workspace_id:'task-a'}});await tick();
  assert.equal(f.workspaces.length,1);assert.equal(f.workspaces[0].api.workspaceId,'task-a');
  assert.equal(f.node('workspace-error').hidden,true);
  f.app.ontoolinput({arguments:{workspace_id:'task-b'}});await tick();
  assert.equal(f.workspaces[0].api.workspaceId,'task-a');assert.equal(f.workspaces.length,1);
  assert.match(f.node('workspace-error span').textContent,/另一个任务/);
});

test('concurrent retry clicks share one pending handshake',async()=>{
  let resolve;
  const f=fixture({connect:()=>new Promise(r=>{resolve=r;})});
  const a=f.node('workspace-retry').onclick(),b=f.node('workspace-retry').onclick();
  assert.equal(f.attempts,1);resolve();await Promise.all([a,b]);await tick();
  assert.equal(f.attempts,1);assert.equal(f.workspaces.length,1);
});

test('disconnect permits reconnect while preserving workspace and reports the actual failure',async()=>{
  const f=fixture({connect:async n=>{if(n===2)throw Error('host bridge closed');}});await tick();
  f.app.onclose();await f.node('workspace-retry').onclick();await tick();
  assert.equal(f.workspaces[0].active,false);
  assert.equal(f.attempts,2);assert.match(f.node('workspace-error span').textContent,/host bridge closed/);
  await f.node('workspace-retry').onclick();await tick();
  assert.equal(f.attempts,3);assert.equal(f.workspaces.length,1);assert.equal(f.workspaces[0].api.workspaceId,'task-a');
  assert.equal(f.workspaces[0].active,true);
});
