// City uses the existing editor canvas/renderer. Packages stay outside the plugin.
import * as THREE from 'three';
import { t } from './i18n.js';
export function createCityPanel({api,viewport,browser,stage,getState,run,onError}){
  const panel=document.createElement('details');panel.className='ed-section';
  panel.innerHTML=`<summary>${t('city.summary')}</summary><p class="ed-muted">${t('city.description')}</p><input data-city-path placeholder="${t('city.pathPlaceholder')}" aria-label="${t('city.pathAriaLabel')}"><button data-city-import>${t('city.importButton')}</button><button data-city-open hidden>${t('city.openButton')}</button><div data-city-search hidden><input data-city-query placeholder="${t('city.searchPlaceholder')}"><div data-city-list></div><button data-city-more>${t('city.nextPage')}</button></div><p data-city-status role="status"></p>`;
  browser.prepend(panel);
  const bar=document.createElement('div');bar.className='city-controls';bar.hidden=true;bar.title=t('city.bar.title');
  bar.innerHTML=`<button data-city-play>${t('city.playButton')}</button><button data-city-overview>${t('city.overviewButton')}</button><button data-city-close>${t('city.closeButton')}</button><span data-city-info>${t('city.editModeInfo')}</span>`;stage.append(bar);
  const find=s=>panel.querySelector(s),status=t=>find('[data-city-status]').textContent=t;
  let runtime=null,packageId=null,pending=false,disposed=false,offset=0,queue=Promise.resolve(),stamp='',readQueue=Promise.resolve(),attempted=null;
  const read=(digest,name)=>{const next=readQueue.then(()=>api.cityResource(digest,name));readQueue=next.catch(()=>{});return next;};
  async function list(){
    const result=await run('city_catalog',{query:find('[data-city-query]').value,offset,limit:25});if(!result)return;
    const target=find('[data-city-list]');target.replaceChildren();
    for(const row of result.items){const b=document.createElement('button');b.textContent=row.name;b.className='ed-wide';b.onclick=()=>checkout(row.id);target.append(b);}
    find('[data-city-more]').hidden=offset+result.items.length>=result.total;
  }
  async function checkout(id){
    try{if(!runtime)return;runtime.setRunning(false);bar.querySelector('[data-city-play]').textContent=t('city.playButton');viewport.orbit.enabled=true;
      const result=await run('city_checkout',{instance_id:id});if(!result)return;
      const center=await runtime.focus(id);if(center)viewport.orbit.target.fromArray(center);viewport.loop.invalidate();
      // Simulation positions are transient; the editable GLB shows its saved
      // placement. Focus that actual preview after its asynchronous load.
      await viewport.assetQueue;
      if(getState()?.selection.includes(result.created[0]))viewport.fit(result.created);
    }catch(e){onError(e);}
  }
  async function open(){
    if(pending||runtime||disposed)return;
    const root=getState()?.objects.find(o=>o.city);if(!root)return;
    pending=true;attempted=root.city.package;status(t('city.status.loadingRuntime'));
    try{
      const raw=await read(root.city.package,'runtime.js');
      const url=URL.createObjectURL(new Blob([raw],{type:'text/javascript'}));
      globalThis.__StudioCityTHREE=THREE;
      try{await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=url;script.onload=()=>{script.remove();resolve();};script.onerror=()=>{script.remove();reject(Error(t('city.error.hostLoadFailed')));};document.head.append(script);});}
      finally{URL.revokeObjectURL(url);delete globalThis.__StudioCityTHREE;}
      if(disposed)return;
      const module=globalThis.StudioCubelyRuntime;if(!module?.create)throw Error(t('city.error.incompatibleModule'));
      viewport.loop.setActive(false);
      runtime=await module.create({renderer:viewport.renderer,read:name=>read(root.city.package,name),
        editorAsset:asset=>api.editorAsset({asset,asset_url:`/api/editor-asset/${asset}.glb`}),
        register:async instances=>{const r=await run('city_register',{instances});if(!r)throw Error(t('city.error.registerFailed'));},
        progress:status,report:status,invalidate:()=>viewport.loop.invalidate()});
      if(disposed){runtime.dispose();runtime=null;return;}
      if(getState()?.objects.find(o=>o.city)?.city.package!==root.city.package){runtime.dispose();runtime=null;viewport.loop.setActive(viewport.active);return;}
      packageId=root.city.package;viewport.mountCity(runtime);viewport.onCityPick=checkout;
      bar.hidden=false;find('[data-city-search]').hidden=false;find('[data-city-open]').hidden=true;
      await list();stamp='';update(getState());
    }catch(e){if(runtime){viewport.unmountCity();runtime.dispose();runtime=null;}status(e.message);onError(e);viewport.loop.setActive(viewport.active);find('[data-city-open]').hidden=false;}
    finally{pending=false;}
  }
  find('[data-city-import]').onclick=async()=>{if(await run('city_import',{path:find('[data-city-path]').value.trim()}))await open();};
  find('[data-city-open]').onclick=open;
  find('[data-city-query]').onchange=()=>{offset=0;list();};find('[data-city-more]').onclick=()=>{offset+=25;list();};
  function controls(){if(!runtime)return;viewport.orbit.enabled=!runtime.running;viewport.transform.detach();bar.querySelector('[data-city-play]').textContent=runtime.running?t('city.pauseButton'):t('city.playButton');bar.querySelector('[data-city-info]').textContent=runtime.running?t('city.runningInfo'):t('city.editModeInfo');viewport.loop.invalidate();}
  bar.querySelector('[data-city-play]').onclick=()=>{if(!runtime)return;runtime.setRunning(!runtime.running);controls();};
  bar.querySelector('[data-city-overview]').onclick=()=>{if(!runtime)return;viewport.orbit.target.copy(runtime.overview());controls();};
  function close(){viewport.unmountCity();runtime?.dispose();runtime=null;packageId=null;bar.hidden=true;find('[data-city-search]').hidden=true;find('[data-city-open]').hidden=false;}
  bar.querySelector('[data-city-close]').onclick=close;
  viewport.renderer.domElement.tabIndex=0;
  const key=(e,down)=>{if(runtime?.running&&['KeyW','KeyA','KeyS','KeyD','Space','KeyE','KeyF','KeyC','KeyR'].includes(e.code)){e.preventDefault();e.stopPropagation();if(!e.repeat||['KeyW','KeyA','KeyS','KeyD','Space'].includes(e.code))runtime.input(e.code,down);}};
  const down=e=>key(e,true),up=e=>key(e,false),blur=()=>{for(const code of ['KeyW','KeyA','KeyS','KeyD','Space'])runtime?.input(code,false);};
  viewport.renderer.domElement.addEventListener('keydown',down);viewport.renderer.domElement.addEventListener('keyup',up);viewport.renderer.domElement.addEventListener('blur',blur);
  function update(state){
    const root=state?.objects.find(o=>o.city);find('[data-city-open]').hidden=!root||!!runtime;
    if(!runtime){if(root&&!pending&&attempted!==root.city.package)open();return;}
    if(!root||root.city.package!==packageId){close();return;}
    const next=JSON.stringify([state.objects.filter(o=>o.city_link).map(o=>[o.id,o.scene.asset,o.transform,o.visible]),state.selection]);
    if(next===stamp)return;stamp=next;
    const current=runtime;current.setRunning(false);controls();
    queue=queue.then(()=>runtime===current?current.update(state.objects,state.selection):null).then(()=>{viewport.loop.invalidate();}).catch(e=>{stamp='';runtime?.setRunning(false);controls();onError(e);status(t('city.status.syncPaused',{detail:e.message}));});
  }
  return {update,detailMode(){if(runtime){close();status(t('city.status.detailModeLoaded'));}},dispose(){disposed=true;viewport.unmountCity();runtime?.dispose();runtime=null;panel.remove();bar.remove();const c=viewport.renderer.domElement;c.removeEventListener('keydown',down);c.removeEventListener('keyup',up);c.removeEventListener('blur',blur);}};
}
