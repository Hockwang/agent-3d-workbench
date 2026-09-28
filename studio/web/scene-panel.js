import {rigPrompt} from './motion-panel.js';
import {t} from './i18n.js';

// Small controls around the existing editor: one selection, one renderer,
// immutable GLB versions. Runtime simulation is deliberately not persisted.
export function createScenePanel({api, viewport, browser, inspector, getState, run, onMotion, onError}) {
  const library=document.createElement('details');library.className='ed-section';
  library.innerHTML=`<summary>${t('scenePanel.libraryTitle')}</summary>
    <p class="ed-muted">${t('scenePanel.libraryDescription')}</p>
    <label>${t('scenePanel.importAssetLabel')}<input data-scene-file type="file" accept=".glb" multiple></label>
    <details class="ui-paths"><summary>${t('scenePanel.importByPath')}</summary><textarea data-scene-path rows="2" aria-label="${t('scenePanel.pathAriaLabel')}" placeholder="${t('scenePanel.pathPlaceholder')}"></textarea><button data-scene-import>${t('scenePanel.importInstancesButton')}</button></details>`;
  browser.prepend(library);
  const panel=document.createElement('section');panel.className='ed-section scene-properties';panel.hidden=true;
  panel.innerHTML=`<div class="ed-section-head"><h2>${t('scenePanel.instanceTitle')}</h2><span data-scene-kind></span></div>
    <p data-scene-info class="ed-muted"></p><p class="ed-muted">${t('scenePanel.editScopeNote')}</p>
    <div class="ed-row"><button data-scene-motion>${t('scenePanel.motionEditButton')}</button><button data-scene-rig>${t('scenePanel.rigButton')}</button></div>
    <label class="ed-inline"><input data-scene-bones type="checkbox">${t('scenePanel.showSkeletonLabel')}</label>
    <details><summary>${t('scenePanel.externalRepairTitle')}</summary><button data-scene-export>${t('scenePanel.exportSourceButton')}</button>
    <label>${t('scenePanel.replaceInstanceLabel')}<input data-scene-replace type="file" accept=".glb"></label>
    <p class="ed-muted">${t('scenePanel.replaceNote')}</p></details>
    <p data-scene-status role="status"></p>`;
  inspector.prepend(panel);
  const find=s=>panel.querySelector(s);
  const status=text=>{find('[data-scene-status]').textContent=text;};
  let busy=false;
  const selected=()=>{const s=getState();return s?.selection.length===1?s.objects.find(o=>o.id===s.selection[0]):null;};
  const snapshot=()=>{const s=getState(),obj=selected();if(!obj)throw Error(t('scenePanel.error.selectOneInstance'));return {obj,revision:s.revision,versions:obj.version==null?undefined:{[obj.id]:obj.version}};};
  const handle=fn=>async e=>{if(busy)return;busy=true;try{await fn(e);}catch(error){status(error.message);onError(error);}finally{busy=false;}};
  library.querySelector('[data-scene-import]').onclick=handle(async()=>{
    const files=library.querySelector('[data-scene-path]').value.split('\n').map(x=>x.trim()).filter(Boolean);
    if(await run('scene_import',{files}))library.open=false;
  });
  library.querySelector('[data-scene-file]').onchange=handle(async e=>{
    const files=[];for(const f of e.target.files)files.push((await api.upload(f)).path);
    if(files.length&&await run('scene_import',{files}))library.open=false;
    e.target.value='';
  });
  find('[data-scene-export]').onclick=handle(async()=>{
    const {obj}=snapshot();const r=await run('scene_export',{ids:[obj.id]});if(r)status(r.path);
  });
  find('[data-scene-replace]').onchange=handle(async e=>{
    const f=e.target.files[0];if(!f)return;
    const {obj,revision,versions}=snapshot(),uploaded=await api.upload(f);
    const r=await run('scene_replace',{ids:[obj.id],path:uploaded.path},revision,versions);
    if(r)status(t('scenePanel.status.replacedInPlace'));e.target.value='';
  });
  find('[data-scene-bones]').onchange=e=>viewport.setSkeleton(e.target.checked);
  find('[data-scene-motion]').onclick=()=>onMotion?.();
  find('[data-scene-rig]').onclick=handle(async()=>{
    const prompt=rigPrompt(api.workspaceId,snapshot().obj);
    if(api.requestMotionRig)status(await api.requestMotionRig(prompt));
    else {const text=document.createElement('textarea');text.value=prompt;find('[data-scene-status]').replaceChildren(t('scenePanel.status.sendToCodexChat'),text);}
  });
  return {update(state){
    const obj=selected();panel.hidden=!obj?.scene;
    if(!obj?.scene)return;
    const info=obj.scene,siblings=state.objects.filter(o=>o.scene?.family===info.family).length;
    find('[data-scene-kind]').textContent={skin:t('scenePanel.kind.skin'),animated:t('scenePanel.kind.animated'),static:t('scenePanel.kind.static')}[info.kind]||t('scenePanel.kind.static');
    find('[data-scene-info]').textContent=t('scenePanel.instanceInfo',{nodes:info.nodes,bones:info.bones,clips:info.clips,siblings});
  },dispose(){library.remove();panel.remove();}};
}
