import { displayLabel } from './display-label.js';
import { createStudioShell } from "./studio-shell.js";
import { TaskPreview } from './task-preview.js';
import { uploadFile } from './upload.js';
import { t } from './i18n.js';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=displayLabel(text);if(cls)n.className=cls;return n;};
export function createObserve(api, root=document.getElementById('observe-space')){
  root.innerHTML=`<header class="observe-head"><div><h2>${t('observe.header.title')}</h2><small>${t('observe.header.subtitle')}</small></div><span>${t('observe.header.badge')}</span></header>
  <div class="observe-layout"><details class="observe-library studio-card" open><summary>${t('observe.section.library')}</summary><div class="studio-card-body">
  <details class="observe-new" open><summary>${t('observe.section.newObservation')}</summary><form>
  <details class="ui-paths"><summary>${t('observe.section.addByPath')}</summary><label>${t('observe.field.modelPathsLabel')}<textarea class="observe-paths" rows="2" placeholder="${t('observe.placeholder.modelPaths')}"></textarea></label></details>
  <label>${t('observe.field.selectModelFiles')}<input class="observe-upload" type="file" accept=".glb,.stl,.ply" multiple></label>
  <div class="observe-options"><label>${t('observe.field.urdfCoordinateSystem')}<select class="observe-up"><option value="z">${t('observe.option.zUp')}</option><option value="y">${t('observe.option.yUp')}</option></select></label>
  <label>${t('observe.field.observationPose')}<select class="observe-phases"><option value="0">${t('observe.option.startPose')}</option><option value="0,0.5,1">${t('observe.option.startMidEndPose')}</option></select></label></div><button>${t('observe.button.generateObservation')}</button></form></details>
  <aside class="observe-runs" aria-label="${t('observe.section.library')}"></aside></div></details><section class="observe-detail"><p class="observe-empty">${t('observe.empty.hint')}</p>
  <div class="observe-evidence" hidden><div class="observe-variants" aria-label="${t('observe.ariaLabel.compareVersions')}"></div><div class="observe-stage"></div>
  <div class="observe-viewbar"><label>${t('observe.field.pose')}<select class="observe-pose"></select></label><button class="observe-fit">${t('observe.button.fitAllVersions')}</button><span>${t('observe.hint.switchKeepsCamera')}</span></div>
  <details class="observe-report studio-card" open hidden><summary>${t('observe.section.compareAndReview')}</summary><div class="studio-card-body"><div class="observe-metrics"></div>
  <details class="observe-images"><summary>${t('observe.section.sameAngleImages')}</summary><img alt="${t('observe.imgAlt.sameAngleImages')}"></details>
  <details><summary>${t('observe.section.metricMeaningAndLimits')}</summary><ul class="observe-limits"></ul></details>
  <form class="observe-review"><label>${t('observe.field.reviewReason')}<textarea rows="2" required placeholder="${t('observe.placeholder.reviewReason')}"></textarea></label><div><select aria-label="${t('observe.ariaLabel.verdict')}"><option value="needs_review">${t('evaluation.label.needsReview')}</option><option value="good">${t('evaluation.label.pass')}</option><option value="bad">${t('evaluation.label.fail')}</option></select><button>${t('observe.button.recordReview')}</button><button type="button" class="observe-save">${t('observe.button.saveReport')}</button></div></form><div class="observe-reviews"></div></div></details></div>
  </section></div><p class="observe-error" role="alert" hidden></p>`;
  const shell = createStudioShell(root, { layout: '.observe-layout', stage: '.observe-detail', library: '.observe-library', title: t('observe.section.compareAndReview'), sections: ['.observe-head', '.observe-report'] });
  const $=s=>root.querySelector(s);
  const drafts=new Map();
  let active=true,disposed=false,selected=null,stamp='',receipt=null,preview=null,variant=0,phase=0,timer,imageUrl,pending=false,modelKey='',focusStamp='';
  const error=e=>{$('.observe-error').textContent=e.message;$('.observe-error').hidden=false;};
  async function act(fn){if(pending)return;pending=true;$('.observe-error').hidden=true;try{await fn();stamp='';await refresh();}catch(e){error(e);}finally{pending=false;}}
  const bytes=async file=>{const a=receipt.task.artifacts.find(a=>a.name===file);if(!a)throw new Error(t('observe.error.artifactMissing',{name:file}));return api.taskAsset(receipt.task.id,a);};
  async function loadModel(reset=false){
    const entry=receipt.report.variants[variant].models[phase],id=receipt.task.id,key=`${id}:${entry.file}`;
    if(modelKey===key&&!reset)return;modelKey=key;const raw=await bytes(entry.file).catch(e=>{if(modelKey===key)modelKey='';throw e;});
    if(disposed||modelKey!==key||selected!==id)return;
    preview||=new TaskPreview($('.observe-stage'));preview.reference=receipt.report.camera;
    await preview.load(raw,{preserveCamera:!reset}).catch(e=>{if(modelKey===key)modelKey='';throw e;});preview.setActive(active);
    $('.observe-variants').querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===variant)));
  }
  function metrics(){
    const groups=receipt.report.variants.map((v,i)=>{
      const group=el('section',null,'observe-metric-group'),list=el('dl'),m=v.metrics;
      group.append(el('h3',`${String.fromCharCode(65+i)} · ${v.label}`));
      for(const [label,value] of [[t('observe.metric.partsAndFaces'),`${m.part_count} / ${m.faces.toLocaleString()}`],[t('observe.metric.boundaryAndNonmanifold'),`${m.boundary_edges} / ${m.nonmanifold_edges}`],[t('observe.metric.sizeM'),m.extents_m.map(x=>x.toPrecision(3)).join(' × ')],[t('observe.metric.dof'),v.dof??t('observe.value.notDeclared')],[t('observe.metric.routeElapsed'),v.provenance.elapsed_seconds==null?t('observe.value.notRecorded'):`${v.provenance.elapsed_seconds.toFixed(2)} s`]]){
        const row=el('div');row.append(el('dt',label),el('dd',String(value)));list.append(row);
      }
      group.append(list);return group;
    });
    $('.observe-metrics').replaceChildren(...groups);$('.observe-limits').replaceChildren(...receipt.report.limitations.map(s=>el('li',s)));
    $('.observe-reviews').replaceChildren(...receipt.reviews.map(r=>el('p',t('observe.review.line',{actor:r.actor==='human'?t('observe.actor.human'):'AI',verdict:{good:t('evaluation.label.pass'),bad:t('evaluation.label.fail'),needs_review:t('evaluation.label.needsReview')}[r.verdict],note:r.note}))));
  }
  async function show(result,reset){
    if(reset){
      if(receipt)drafts.set(receipt.task.id,{note:$('.observe-review textarea').value,verdict:$('.observe-review select').value});
      const draft=drafts.get(result.task.id);$('.observe-review textarea').value=draft?.note||'';$('.observe-review select').value=draft?.verdict||'needs_review';
    }
    receipt=result;$('.observe-report').hidden=false;$('.observe-evidence').hidden=false;$('.observe-empty').hidden=true;
    if(reset){variant=0;phase=0;modelKey='';
      $('.observe-variants').replaceChildren(...result.report.variants.map((v,i)=>{const b=el('button',`${String.fromCharCode(65+i)} · ${v.label}`);b.onclick=()=>act(async()=>{variant=i;await api.observe({action:'focus',id:selected,variant,phase_index:phase});await loadModel();});return b;}));
      $('.observe-pose').replaceChildren(...result.report.phases.map((p,i)=>{const o=el('option',`${Math.round(p*100)}%`);o.value=i;return o;}));
      const id=selected,image=await bytes('contact-sheet.png');if(disposed||id!==selected)return;
      if(imageUrl)URL.revokeObjectURL(imageUrl);imageUrl=URL.createObjectURL(new Blob([image],{type:'image/png'}));$('.observe-images img').src=imageUrl;
    }if(result.focus?.task_id===selected){variant=result.focus.variant;phase=result.focus.phase_index;$('.observe-pose').value=String(phase);}
    metrics();await loadModel(reset);
  }
  async function refresh(){
    if(!active||disposed)return;const data=await api.tasks(),tasks=data.tasks.filter(t=>t.category==='observation');
    shell.setPopulated(tasks.length > 0);
    if(!selected&&tasks.length)selected=tasks[0].id;
    const focus=data.observation_focus; if(focus&&focus.at!==focusStamp){focusStamp=focus.at;selected=focus.task_id;variant=focus.variant;phase=focus.phase_index;}
    const next=JSON.stringify(tasks.map(t=>[t.id,t.status,t.review_revision,Math.round(t.elapsed_seconds||0)]))+selected+focusStamp;if(next===stamp)return;stamp=next;
    $('.observe-runs').replaceChildren(...tasks.map(task=>{const b=el('button',null,task.id===selected?'selected':'');b.append(el('strong',task.title),el('small',`${({completed:t('observe.status.completed'),running:t('observe.status.running'),queued:t('observe.status.queued'),failed:t('observe.status.failed'),cancelled:t('observe.status.cancelled')})[task.status]||task.status} · ${Math.round(task.elapsed_seconds||0)}s`));b.onclick=()=>act(async()=>{selected=task.id;if(task.status==='completed')await api.observe({action:'focus',id:selected,variant:0,phase_index:0});});return b;}));
    if(!selected)return;const result=await api.observe({action:'read',id:selected,image:false,detail:true});if(disposed||result.task.id!==selected)return;
    if(result.ready){$('.observe-new').open=false;await show(result,receipt?.task.id!==selected);}else{$('.observe-report').hidden=true;$('.observe-evidence').hidden=true;$('.observe-empty').hidden=false;$('.observe-empty').textContent=result.task.error||t('observe.status.generatingReal');preview?.setActive(false);}
  }
  $('.observe-pose').onchange=()=>act(async()=>{phase=Number($('.observe-pose').value);await api.observe({action:'focus',id:selected,variant,phase_index:phase});await loadModel();});$('.observe-fit').onclick=()=>preview?.fit();
  $('.observe-new form').onsubmit=e=>{e.preventDefault();act(async()=>{const inputs=$('.observe-paths').value.split('\n').map(x=>x.trim()).filter(Boolean);const r=await api.observe({action:'start',inputs,params:{urdf_up:$('.observe-up').value,phases:$('.observe-phases').value.split(',').map(Number)}});selected=r.task.id;});};
  $('.observe-upload').onchange=()=>act(async()=>{const paths=[];for(const f of $('.observe-upload').files)paths.push((await uploadFile(b=>api.task(b),f)).path);$('.observe-paths').value=[$('.observe-paths').value,...paths].filter(Boolean).join('\n');$('.observe-upload').value='';});
  $('.observe-review').onsubmit=e=>{e.preventDefault();act(async()=>{const id=receipt.task.id;const result=await api.observe({action:'review',id,expected_sha256:receipt.report_sha256,verdict:$('.observe-review select').value,note:$('.observe-review textarea').value});if(receipt.task.id===id){receipt=result;metrics();}});};
  $('.observe-save').onclick=()=>{if(!receipt)return;const url=URL.createObjectURL(new Blob([JSON.stringify(receipt,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='observation.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);};
  const ready=refresh().catch(error);timer=setInterval(()=>{if(!pending)refresh().catch(error);},2000);
  return{ready,setState(state){if(state?.focus_task_id){selected=state.focus_task_id;stamp='';refresh().catch(error);}},setActive(v){active=v;preview?.setActive(v);if(v)refresh().catch(error);},dispose(){disposed=true;clearInterval(timer);shell.dispose();preview?.dispose();if(imageUrl)URL.revokeObjectURL(imageUrl);}};
}
