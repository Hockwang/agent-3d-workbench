import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {createMcpApi,payload} from '../studio/app/api.js';
import {browserEntry} from '../studio/web/quick-access.js';
import {presentationFor, safeAreaFor} from '../studio/app/presentation.js';
import {t} from '../studio/web/i18n.js';
import {createSelectionContextSync} from '../studio/app/selection-context.js';

const main=(await readFile(new URL('../studio/app/main.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({workspaceId='task-a',connect,modelContext,toolResult}={}) {
  const nodes=new Map(),calls=[],workspaces=[],contexts=[],timers=new Map();
  let timerId=0;
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
      if(toolResult)return await toolResult(request,calls.length);
      if(request.name==='studio_open')return {_meta:{'studio/uiNonce':`nonce-${attempts}`},structuredContent:{ok:true,parts:[],workspace_id:request.arguments.workspace_id,workbench:{objects:[],selection:[]}}};
      return {structuredContent:{ok:true,parts:[],workspace_id:request.arguments.workspace_id,workbench:{objects:[],selection:[]}}};
    }
  }
  vm.runInNewContext(main,{
    App,THREE:{},createMcpApi,payload,browserEntry,URLSearchParams,presentationFor,safeAreaFor,t,
    createSelectionContextSync,
    createWorkspace(api,options){const item={api,options,ready:Promise.resolve(),setState(value){this.state=value;},setActive(value){this.active=value;},dispose(){}};workspaces.push(item);return item;},
    document:{getElementById:node,addEventListener(){},hidden:false},window:{addEventListener(){},innerWidth:1000},
    ResizeObserver:class {observe(){}disconnect(){}},requestAnimationFrame(){return 1;},cancelAnimationFrame(){},
    setTimeout(fn,ms){timers.set(++timerId,{fn,ms});return timerId;},clearTimeout(id){timers.delete(id);},
  });
  return {node,calls,workspaces,contexts,timers,get app(){return app;},get attempts(){return attempts;},
    async advanceStartup(){const entry=[...timers].find(([,timer])=>timer.ms===2000);if(!entry)return false;
      timers.delete(entry[0]);await entry[1].fn();await tick();return true;}};
}

const pendingResult=()=>({structuredContent:{ok:true,workspace_id:'task-a',startup:{status:'waiting_for_thread'}}});
const readyResult=()=>({_meta:{'studio/uiNonce':'ready-nonce'},structuredContent:{ok:true,parts:[],workspace_id:'task-a',
  workbench:{objects:[{id:'saved'}],selection:[]}}});

test('draft startup stays in the launcher then automatically restores the requested task',async()=>{
  const f=fixture({toolResult:async(_request,n)=>n<3?pendingResult():readyResult()});
  f.app.ontoolinput({arguments:{workspace_id:'task-a',task_id:'chosen'}});
  await tick();
  assert.equal(f.workspaces.length,0,'no editor or state polling before the project is ready');
  assert.equal(f.node('workspace-startup').hidden,false);
  assert.equal(f.node('workspace-error').hidden,true);
  await f.advanceStartup();await f.advanceStartup();
  assert.equal(f.workspaces.length,1);
  assert.equal(f.node('workspace-startup').hidden,true);
  assert.equal(f.workspaces[0].state.workbench.objects[0].id,'saved');
  assert.equal(f.workspaces[0].state.focus_task_id,'chosen');
  assert.ok(f.calls.every(c=>c.name==='studio_open'&&c.arguments.workspace_id==='task-a'&&c.arguments.task_id==='chosen'));
});

test('draft retries are bounded and a manual retry starts a new attempt',async()=>{
  let ready=false;
  const f=fixture({toolResult:async()=>ready?readyResult():pendingResult()});await tick();
  for(let n=0;n<30;n++)await f.advanceStartup();
  assert.equal(f.calls.length,15);
  assert.equal(f.workspaces.length,0);
  assert.match(f.node('startup-message').textContent,/发送一条消息/);
  assert.equal(await f.advanceStartup(),false);
  ready=true;await f.node('startup-retry').onclick();await tick();
  assert.equal(f.workspaces.length,1);
  assert.equal(f.node('workspace-startup').hidden,true);
});

test('draft retry is cancelled on teardown and an in-flight result cannot create an editor',async()=>{
  let release;
  const f=fixture({toolResult:()=>new Promise(r=>{release=r;})});await tick();
  await f.app.onteardown();release(readyResult());await tick();
  assert.equal(f.workspaces.length,0);
  assert.equal(f.timers.size,0);
});

test('real startup failures stay visible and do not retry automatically',async()=>{
  const f=fixture({toolResult:async()=>({isError:true,structuredContent:{ok:false,error:{code:'tool_exception',message:'permission denied'}}})});
  await tick();
  assert.equal(f.workspaces.length,0);
  assert.equal(f.node('workspace-error').hidden,false);
  assert.match(f.node('workspace-error span').textContent,/permission denied/);
  assert.equal(await f.advanceStartup(),false);
});

test('native startup ignores legacy implicit edit mode but preserves explicit destinations',async()=>{
  const f=fixture(); await tick();
  const oldResult=()=>({structuredContent:{ok:true,parts:[],workspace_id:'task-a',workspace_mode:'edit',workbench:{objects:[{id:'saved'}],selection:[]}}});
  f.app.ontoolinput({arguments:{workspace_id:'task-a'}});
  f.app.ontoolresult(oldResult());
  assert.equal(f.workspaces[0].state.workspace_mode,'home');
  assert.equal(f.workspaces[0].state.workbench.objects.length,1,'saved data is retained');
  for(const mode of ['edit','print','motion']) {
    f.app.ontoolinput({arguments:{workspace_id:'task-a',mode}});
    f.app.ontoolresult(oldResult());
    assert.equal(f.workspaces[0].state.workspace_mode,mode);
  }
  f.app.ontoolinput({arguments:{workspace_id:'task-a',task_id:'chosen'}});
  f.app.ontoolresult(oldResult());
  assert.equal(f.workspaces[0].state.workspace_mode,'tasks');
});

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
  assert.deepEqual(f.calls.map(c=>c.name),['studio_open']);
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
