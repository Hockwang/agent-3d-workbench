import {defaultMotion,validateMotion,trackEvaluator} from './motion-engine.js';
import {MotionPlayer} from './motion-player.js';
import {t} from './i18n.js';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function rigPrompt(workspaceId,object){
  const source = 'scene_export';
  return t('motionPanel.rigPrompt', {
    workspace: workspaceId || t('motionPanel.rigPromptCurrentProjectFallback'),
    id: object.id, name: object.name, source, asset: object.scene?.asset || object.asset,
  });
}
export function createMotionPanel({api,viewport,host,stage,getState,run,onError,onContextChange,canAttachSelection}){
  let selected=null,draft=null,stamp='',active=false,dirty=false;
  const panel=document.createElement('div');panel.className='motion-panel';panel.hidden=true;host.append(panel);
  const timeline=document.createElement('div');timeline.className='motion-timeline';timeline.hidden=true;timeline.innerHTML=`<button type="button" data-play aria-label="${t('motionPanel.playAriaLabel')}">▶</button><input data-time aria-label="${t('motionPanel.timeAriaLabel')}" type="range" min="0" max="4" step="0.001" value="0"><output>0.00 / 0.00 s</output><label><input type="checkbox" data-loop checked>${t('motionPanel.loopLabel')}</label>`;stage.append(timeline);
  let lastPlaying=false;
  const player=new MotionPlayer(viewport,(time,duration,playing)=>{timeline.querySelector('[data-time]').max=duration;timeline.querySelector('[data-time]').value=time;timeline.querySelector('output').textContent=`${time.toFixed(2)} / ${duration.toFixed(2)} s`;timeline.querySelector('[data-play]').textContent=playing?'Ⅱ':'▶';if(active&&(!playing||playing!==lastPlaying))onContextChange?.();lastPlaying=playing;},error=>{status(error.message,true);});viewport.motionPlayer=player;
  timeline.querySelector('[data-time]').oninput=e=>player.seek(Number(e.target.value));timeline.querySelector('[data-play]').onclick=()=>player.play();timeline.querySelector('[data-loop]').onchange=e=>player.loop=e.target.checked;
  function status(message,error=false){const target=panel.querySelector('[data-status]');if(target){target.textContent=message;target.classList.toggle('motion-error',error);}}
  function showUnsaved(){const row=panel.querySelector('[data-unsaved]');if(row)row.hidden=!dirty;}
  function preview(){if(!draft||!selected)return;dirty=true;showUnsaved();onContextChange?.();try{validateMotion(draft);const s=getState();player.setState({...s,objects:s.objects.map(o=>o.id===selected.id?{...o,motion:structuredClone(draft)}:o)});status(t('motionPanel.status.previewUpdated'));}catch(error){status(error.message,true);}}
  function draw(){
    const advancedOpen=panel.querySelector('[data-advanced]')?.open||false;
    const state=getState();selected=state?.objects.find(o=>state.selection.includes(o.id));
    panel.innerHTML=`<div class="motion-heading"><span>${t('motionPanel.heading')}</span><strong>${escape(selected?.name||t('motionPanel.selectAModel'))}</strong></div>
      <p class="ed-muted">${t(canAttachSelection?'motionPanel.chatHint':'motionPanel.browserChatHint')}</p>
      <div class="motion-unsaved" data-unsaved ${dirty?'':'hidden'}><span>${t('motionPanel.unsavedPreview')}</span><button data-command="save" ${!draft?'disabled':''}>${t('motionPanel.saveButton')}</button></div>
      <p data-status role="status"></p>
      <section class="motion-export"><strong>${t('motionPanel.exportSummary')}</strong><div class="motion-actions"><button data-command="zip">${t('motionPanel.exportZipButton')}</button><button data-command="glb">${t('motionPanel.exportGlbButton')}</button></div><label>${t('motionPanel.exportScopeLabel')}<select data-export-scope><option value="all">${t('motionPanel.exportScope.all')}</option><option value="selected">${t('motionPanel.exportScope.selected')}</option></select></label><p class="ed-muted">${t('motionPanel.exportNote')}</p><input data-output readonly hidden aria-label="${t('motionPanel.outputPathAriaLabel')}"></section>
      <details class="motion-import"><summary>${t('motionPanel.importSummary')}</summary><label>${t('motionPanel.chooseFileLabel')}<input type="file" data-file accept=".glb,.zip"></label><label>${t('motionPanel.localPathLabel')}<input data-path placeholder="${t('motionPanel.localPathPlaceholder')}"></label><button data-command="import">${t('motionPanel.importButton')}</button></details>
      <details class="motion-advanced" data-advanced ${advancedOpen?'open':''}><summary>${t('motionPanel.advancedSummary')}</summary><p class="ed-muted">${t('motionPanel.advancedHint')}</p>
        <div class="motion-actions"><button data-command="add" ${!selected||selected.scene||selected.motion?.kind==='skin'?'disabled':''}>${t('motionPanel.addJointButton')}</button><button data-command="clear" ${!selected?.motion?'disabled':''}>${t('motionPanel.clearButton')}</button></div>
        <div data-controls></div>
      </details>`;
    panel.querySelector('[data-file]').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const result=await api.upload(f);const path=result.path||result.file?.path; if(!path)throw Error(t('motionPanel.error.uploadMissingPath'));panel.querySelector('[data-path]').value=path;}catch(error){status(error.message,true);}};
    if(!draft)return;
    const target=panel.querySelector('[data-controls]');
    target.innerHTML=`<div class="motion-row"><label>${t('motionPanel.durationLabel')}<input data-field="duration" type="number" min="0.01" max="120" step="0.1" value="${draft.duration}"></label><label>${t('motionPanel.fpsLabel')}<input data-field="fps" type="number" min="1" max="60" value="${draft.fps}"></label></div>
      <label>${t('motionPanel.modeLabel')}<select data-field="mode">${(draft.kind==='joint'?[['pkf',t('motionPanel.mode.pkfSteps')],['keyframes',t('motionPanel.mode.keyframes')]]:draft.kind==='gltf'?[['clip',t('motionPanel.mode.sourceClip')]]:[['clip',t('motionPanel.mode.sourceClip')],['pkf',t('motionPanel.mode.bonePkfSteps')]]).map(([v,label])=>`<option value="${v}" ${draft.mode===v?'selected':''}>${label}</option>`).join('')}</select></label>
      <div data-joint></div><div data-skin></div>
      <div class="motion-subheading">${t('motionPanel.parametersHeading')} <button data-command="parameter">${t('motionPanel.addParameterButton')}</button></div><div data-parameters></div>
      <div class="motion-subheading">${draft.mode==='keyframes'?t('motionPanel.keyframesHeading'):t('motionPanel.stepsHeading')} <button data-command="step">${draft.mode==='keyframes'?t('motionPanel.addCurrentFrameButton'):t('motionPanel.addStepButton')}</button></div><div data-steps></div>
      <details><summary>${t('motionPanel.editJsonSummary')}</summary><textarea data-json rows="8" spellcheck="false">${escape(JSON.stringify(draft,null,2))}</textarea><button data-command="json">${t('motionPanel.applyPreviewButton')}</button></details>`;
    if(draft.kind==='joint')panel.querySelector('[data-joint]').innerHTML=`<label>${t('motionPanel.jointTypeLabel')}<select data-joint-field="type">${[['revolute',t('motionPanel.jointType.revolute')],['prismatic',t('motionPanel.jointType.prismatic')],['fixed',t('motionPanel.jointType.fixed')]].map(([v,label])=>`<option value="${v}" ${draft.joint.type===v?'selected':''}>${label}</option>`).join('')}</select></label>
      <div class="motion-row"><label>${t('motionPanel.worldAxisLabel')}<select data-joint-field="axis">${[['x','X'],['y',t('motionPanel.axis.y')],['z','Z']].map(([v,label])=>`<option value="${v}" ${draft.joint.axis===v?'selected':''}>${label}</option>`).join('')}</select></label><label>${t('motionPanel.parentJointLabel')}<select data-joint-field="parent"><option value="">${t('motionPanel.worldOption')}</option>${state.objects.filter(o=>o.id!==selected.id).map(o=>`<option value="${o.id}" ${draft.joint.parent===o.id?'selected':''}>${escape(o.name)}</option>`).join('')}</select></label></div>
      <label>${t('motionPanel.originLabel')}</label><div class="motion-row">${draft.joint.origin.map((v,i)=>`<input aria-label="${t('motionPanel.originAxisAriaLabel',{axis:'XYZ'[i]})}" data-origin="${i}" type="number" step="0.001" value="${v}">`).join('')}</div>
      <div class="motion-row">${draft.joint.limits.map((v,i)=>`<label>${i?t('motionPanel.upperLimit'):t('motionPanel.lowerLimit')}<input data-limit="${i}" type="number" step="any" value="${v}"></label>`).join('')}</div>`;
    else panel.querySelector('[data-skin]').innerHTML=`<label>${t('motionPanel.sourceClipLabel')}<select data-field="clip">${(draft.clips||[]).map((c,i)=>`<option value="${i}" ${(draft.clip||0)===i?'selected':''}>${escape(c.name)} · ${c.duration.toFixed(2)} s</option>`).join('')}</select></label><div class="motion-row"><label>${t('motionPanel.startLabel')}<input data-field="start" type="number" value="${draft.start||0}" min="0" step="0.1"></label><label>${t('motionPanel.speedLabel')}<input data-field="speed" type="number" value="${draft.speed||1}" min="0.1" max="4" step="0.1"></label></div><details open><summary>${t('motionPanel.skeletonSummary',{count:(draft.bones||[]).length})}</summary><div class="motion-bones">${(draft.bones||[]).map(b=>`<span title="${escape(b.parent||t('motionPanel.rootBoneFallback'))}" >${escape(b.name)}</span>`).join('')}</div></details>`;
    if(draft.mode==='clip'){for(const element of panel.querySelectorAll('.motion-subheading,[data-parameters],[data-steps]'))element.hidden=true;}
    panel.querySelector('[data-parameters]').innerHTML=draft.parameters.map((p,i)=>`<div class="motion-row"><input aria-label="${t('motionPanel.paramNameAriaLabel')}" data-param="${i}" data-key="id" value="${escape(p.id)}"><input aria-label="${t('motionPanel.paramValueAriaLabel',{name:escape(p.id)})}" data-param="${i}" data-key="default" type="number" step="any" value="${p.default}"><button data-remove-param="${i}" aria-label="${t('motionPanel.removeParamAriaLabel')}">×</button></div>`).join('');
    panel.querySelector('[data-steps]').innerHTML=draft.mode==='keyframes'?draft.keyframes.map((k,i)=>`<div class="motion-row"><input aria-label="${t('motionPanel.keyframeTimeAriaLabel')}" data-keyframe="${i}" data-key="time" type="number" step="0.01" value="${k.time}"><input aria-label="${t('motionPanel.keyframeValueAriaLabel')}" data-keyframe="${i}" data-key="value" type="number" step="any" value="${k.value}"><button data-remove-key="${i}">×</button></div>`).join(''):draft.steps.map((s,i)=>`<div class="motion-step"><header>${t('motionPanel.stepHeading',{n:i+1})}<button data-remove-step="${i}" aria-label="${t('motionPanel.removeStepAriaLabel')}">×</button></header>${draft.kind==='skin'?`<div class="motion-row"><select aria-label="${t('motionPanel.boneChannelAriaLabel')}" data-step="${i}" data-key="bone">${(draft.bones||[]).map(b=>`<option ${s.bone===b.name?'selected':''}>${escape(b.name)}</option>`).join('')}</select><select aria-label="${t('motionPanel.boneAxisAriaLabel')}" data-step="${i}" data-key="axis">${['x','y','z'].map(a=>`<option ${s.axis===a?'selected':''}>${a}</option>`).join('')}</select></div>`:''}<div class="motion-row"><label>${t('motionPanel.stepStartLabel')}<input data-step="${i}" data-key="t_start" type="number" step="0.1" value="${s.t_start}"></label><label>${t('motionPanel.stepEndLabel')}<input data-step="${i}" data-key="t_end" type="number" step="0.1" value="${s.t_end}"></label></div><div class="motion-row"><input aria-label="${t('motionPanel.startFormulaAriaLabel')}" data-step="${i}" data-key="value_start" value="${escape(s.value_start)}"><span>→</span><input aria-label="${t('motionPanel.endFormulaAriaLabel')}" data-step="${i}" data-key="value_end" value="${escape(s.value_end)}"></div><select aria-label="${t('motionPanel.easingAriaLabel')}" data-step="${i}" data-key="easing">${['linear','ease-in','ease-out','ease-in-out'].map(e=>`<option ${s.easing===e?'selected':''}>${e}</option>`).join('')}</select></div>`).join('');
  }
  panel.oninput=e=>{
    const el=e.target,d=el.dataset;
    if(!draft)return;
    if(d.field)draft[d.field]=el.tagName==='SELECT'&&d.field==='mode'?el.value:Number(el.value);
    else if(d.jointField)draft.joint[d.jointField]=el.value||null;
    else if(d.origin!==undefined)draft.joint.origin[Number(d.origin)]=Number(el.value);
    else if(d.limit!==undefined)draft.joint.limits[Number(d.limit)]=Number(el.value);
    else if(d.param!==undefined)draft.parameters[Number(d.param)][d.key]=d.key==='default'?Number(el.value):el.value;
    else if(d.step!==undefined)draft.steps[Number(d.step)][d.key]=['t_start','t_end'].includes(d.key)?Number(el.value):el.value;
    else if(d.keyframe!==undefined)draft.keyframes[Number(d.keyframe)][d.key]=Number(el.value);
    else return;
    if(d.field==='clip'&&draft.clips?.[draft.clip])draft.duration=(draft.clips[draft.clip].duration-(draft.start||0))/(draft.speed||1);
    preview();if(['mode','clip'].includes(d.field))draw();
  };
  panel.onclick=async event=>{
    const el=event.target.closest('button');if(!el)return;const d=el.dataset;
    try{
      if(d.removeParam!==undefined){draft.parameters.splice(Number(d.removeParam),1);preview();draw();return;}
      if(d.removeStep!==undefined){draft.steps.splice(Number(d.removeStep),1);preview();draw();return;}
      if(d.removeKey!==undefined){draft.keyframes.splice(Number(d.removeKey),1);preview();draw();return;}
      switch(d.command){
        case 'add':{draft=defaultMotion();const b=selected.bounds_mm;if(b){const center=b[0].map((v,i)=>(v+b[1][i])/2000);draft.joint.origin=[center[0],-center[1],center[2]];}preview();draw();break;}
        case 'parameter':{let n=1;while(draft.parameters.some(p=>p.id==='value'+n))n++;draft.parameters.push({id:'value'+n,default:0});preview();draw();break;}
        case 'step':if(draft.mode==='keyframes'){draft.keyframes=draft.keyframes.filter(k=>Math.abs(k.time-player.time)>1e-5);draft.keyframes.push({time:player.time,value:trackEvaluator(draft)(player.time).value||0});draft.keyframes.sort((a,b)=>a.time-b.time);}else draft.steps.push({id:crypto.randomUUID(),t_start:0,t_end:draft.duration,value_start:'0',value_end:'0',easing:'linear',...(draft.kind==='skin'?{bone:draft.bones?.[0]?.name||'',axis:'z'}:{})});preview();draw();break;
        case 'json':draft=JSON.parse(panel.querySelector('[data-json]').value);validateMotion(draft);preview();draw();break;
        case 'save':{validateMotion(draft);const result=await run('motion_set',{ids:[selected.id],motion:draft});if(result){dirty=false;stamp='';update(getState());status(t('motionPanel.status.saved'));}break;}
        case 'clear':await run('motion_clear',{ids:[selected.id]});dirty=false;stamp='';update(getState());break;
        case 'import':await run('motion_import',{path:panel.querySelector('[data-path]').value.trim()});stamp='';update(getState());break;
        case 'zip':case 'glb':{if(dirty)throw Error(t('motionPanel.error.saveBeforeExport'));const scope=panel.querySelector('[data-export-scope]').value;const result=await run('motion_export',{format:d.command,...(scope==='selected'?{ids:getState().selection}:{})});if(result){const output=panel.querySelector('[data-output]');output.hidden=false;output.value=result.path;status(result.summary);}break;}
      }
    }catch(error){status(error.message,true);}
  };
  function update(state){if(!state)return;const current=state.objects.find(o=>state.selection.includes(o.id));const next=JSON.stringify([current?.id,current?.motion,current?.asset,state.objects.map(o=>[o.id,o.name])]);if(next!==stamp){stamp=next;selected=current;draft=current?.motion?structuredClone(current.motion):null;dirty=false;draw();}if(!dirty)player.setState(state);if(active)onContextChange?.();}
  return {update,getContext:()=>({time_seconds:Number(player.time.toFixed(3)),duration_seconds:player.duration||0,unsaved_preview:dirty,playing:player.playing}),pause(){player.playing=false;player.seek(player.time);},setActive(value){active=value;panel.hidden=!value;timeline.hidden=!value;viewport.setMotionMode(value);player.setActive(value);if(value)update(getState());},dispose(){player.dispose();panel.remove();timeline.remove();}};
}
