import { downloadFile } from './download.js';
import {t} from './i18n.js';

const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
const stages=['design','panels','nest','lightburn'];
const names={design:t('laser.design'),panels:t('laser.panels'),nest:t('laser.nest'),lightburn:'LightBurn'};
export function laserStepCompleted(step,stage,sheet) {
  return step?.status==='completed'||Boolean(stage==='lightburn'&&step?.report?.imported_sheets?.includes(sheet));
}
export function createLaser(api,options={}) {
  const root=document.getElementById('laser-space');
  let workflow=null,busy=false,active=true,disposed=false,tab='design',polling=false,previewKey='',renderKey='',paramsId='',pickerKey='';
  const header=node('header',null,'laser-header'), heading=node('div');
  heading.append(node('h2',t('laser.title')),node('p',t('laser.subtitle')));
  const picker=node('select');picker.setAttribute('aria-label',t('laser.saved'));
  const refresh=button(t('laser.refresh'),()=>load());
  header.append(heading,picker,refresh);
  const error=node('p',null,'laser-error');error.setAttribute('role','alert');error.hidden=true;
  const grid=node('div',null,'laser-grid'),setup=node('aside',null,'laser-setup'),result=node('section',null,'laser-result');
  grid.append(setup,result);root.replaceChildren(header,error,grid);
  setup.append(node('h3',t('laser.params')),node('p',t('laser.inner'),'laser-note'));
  const inputs={};
  for(const [key,label,value] of [['width_mm',t('laser.width'),230],['depth_mm',t('laser.depth'),120],['height_mm',t('laser.height'),90],['thickness_mm',t('laser.thickness'),3],['slot_length_mm',t('laser.slotLength'),120],['slot_width_mm',t('laser.slotWidth'),35],['clearance_mm',t('laser.clearance'),.15],['kerf_mm',t('laser.kerf'),.15],['margin_mm',t('laser.margin'),5],['gap_mm',t('laser.gap'),5]]) {
    const row=node('label',label),input=node('input');input.type='number';input.step='.05';input.value=value;input.min='0';input.name=key;
    input.setAttribute('aria-label',label+' mm');inputs[key]=input;row.append(input);setup.append(row);
  }
  const create=button(t('laser.create'),()=>perform(async()=>{
    const params=Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,Number(input.value)]));
    const r=await api.laser({action:'create',params});workflow=r.workflow;tab='design';await list();render(true);
  })); setup.append(create,node('p',t('laser.immutable'),'laser-note'));
  const connect=button(t('laser.connect'),()=>perform(async()=>{
    connection.textContent=t('laser.accept');
    const r=await api.laser({action:'connect'});connection.textContent=r.connection.paired?t('laser.connected'):t('laser.disconnected');
  }));
  const connection=node('p',t('laser.emptyProject'),'laser-note');setup.append(connect,connection);
  const title=node('h3',t('laser.welcome')),tabs=node('nav',null,'laser-steps');tabs.setAttribute('aria-label',t('laser.steps'));
  const buttons={};for(const s of stages){buttons[s]=button(names[s],()=>{tab=s;render(true);});tabs.append(buttons[s]);}
  const summary=node('p',null,'laser-summary'), actions=node('div',null,'laser-actions');
  const run=button(t('laser.runDesign'),()=>perform(async()=>{
    if(!workflow)return;
    const r=await api.laser({action:'run',id:workflow.id,expected_revision:workflow.revision,stage:tab,sheet:Number(sheet.value)||1});
    workflow=r.workflow;render(true);
  }));
  const sheet=node('select');sheet.setAttribute('aria-label',t('laser.sheet'));sheet.onchange=()=>render(true);
  const model=button(t('laser.model'),()=>perform(async()=>{
    const path=workflow?.stages.design?.artifacts.find(a=>a.name==='design/assembly.glb')?.path;
    if(path){await api.laser({action:'artifact',id:workflow.id,name:'design/assembly.glb'});await options.onModel?.(path);}
  }));actions.append(run,sheet,model);
  const picture=node('img');picture.alt=t('laser.preview');picture.className='laser-preview';picture.hidden=true;
  const details=node('div',null,'laser-details'), downloads=node('div',null,'laser-downloads');
  const note=node('p',t('laser.note'),'laser-note');
  result.append(title,tabs,summary,actions,picture,details,downloads,note);
  function button(text,fn){const b=node('button',text);b.type='button';b.onclick=fn;return b;}
  async function perform(fn){if(busy)return;busy=true;error.hidden=true;render();try{await fn();}catch(e){error.textContent=e.message.replace(/\b[a-z]+_mm\b/g,key=>inputs[key]?.getAttribute('aria-label')||key);error.hidden=false;}finally{busy=false;render(true);}}
  async function list(){const r=await api.laser({action:'list'});
    // Polling must not replace an open native menu or discard its keyboard focus.
    const key=JSON.stringify(r.workflows.map(w=>[w.id,w.title]));
    if(key!==pickerKey){pickerKey=key;picker.replaceChildren();
      for(const w of r.workflows){const o=node('option',w.title+' · '+w.id.slice(0,6));o.value=w.id;picker.append(o);}}
    if(workflow)picker.value=workflow.id;
    else if(r.workflows.length){workflow=r.workflows[0];tab=lastStage();}
  }
  function lastStage(){return stages.filter(s=>workflow?.stages[s]).at(-1)||'design';}
  async function load(){if(polling||busy||disposed)return;polling=true;try{await list();if(workflow){workflow=(await api.laser({action:'read',id:workflow.id})).workflow;}render();}catch(e){error.textContent=e.message;error.hidden=false;}finally{polling=false;}}
  picker.onchange=()=>perform(async()=>{workflow=(await api.laser({action:'read',id:picker.value})).workflow;tab=lastStage();render(true);});
  function render(force=false){
    if(workflow&&workflow.id!==paramsId){paramsId=workflow.id;for(const [key,input] of Object.entries(inputs))input.value=workflow.params[key];}
    const key=[workflow?.id,workflow?.revision,tab,busy,sheet.value].join('|');if(!force&&key===renderKey)return;renderKey=key;
    title.textContent=workflow?.title||t('laser.welcome');
    for(const s of stages){buttons[s].setAttribute('aria-current',String(s===tab));buttons[s].textContent=(workflow?.stages[s]?.status==='completed'?'✓ ':'')+names[s];buttons[s].disabled=busy;}
    create.disabled=connect.disabled=refresh.disabled=picker.disabled=busy;
    const step=workflow?.stages[tab],report=step?.report,previous=stages[stages.indexOf(tab)-1];
    const completed=laserStepCompleted(step,tab,Number(sheet.value)||1);
    run.disabled=busy||!workflow||completed||Boolean(previous&&!workflow.stages[previous]);
    run.textContent=busy?t('laser.busy'):completed?t('laser.done'):({design:t('laser.runDesign'),panels:t('laser.runPanels'),nest:t('laser.runNest'),lightburn:t('laser.import')})[tab];
    model.hidden=!workflow?.stages.design;model.disabled=busy;
    const count=workflow?.stages.nest?.report.sheets||0;
    if(sheet.options.length!==count){sheet.replaceChildren();for(let i=1;i<=count;i++){const o=node('option',t('laser.sheetNumber',{number:i}));o.value=i;sheet.append(o);}}
    sheet.hidden=!['nest','lightburn'].includes(tab)||count<2;
    summary.textContent=!workflow?t('laser.workflow'):!step?(previous&&!workflow.stages[previous]?t('laser.previous',{step:names[previous]}):t('laser.ready')):
      tab==='design'?t('laser.designSummary',{size:report.outer_mm.join(' × '),count:report.panel_count,collisions:report.solid_intersections}):
      tab==='panels'?t('laser.panelSummary',{count:report.count}):
      tab==='nest'?t('laser.nestSummary',{sheets:report.sheets,use:report.utilization_percent.toFixed(1),collisions:report.collisions,gap:report.gap_mm}):
      t('laser.importProgress',{done:report.imported_sheets?.length||1,total:report.total_sheets||1,count:report.project?.shape_count??'—'});
    details.replaceChildren();
    if(tab==='design'&&report)details.append(node('p',report.assembly));
    if(tab==='panels'&&report){const table=node('table');const head=node('tr');for(const v of [t('laser.panels'),t('laser.size'),t('laser.holes')])head.append(node('th',v));table.append(head);for(const p of report.parts){const row=node('tr');for(const v of [p.id,p.size_mm.join(' × '),p.holes])row.append(node('td',v));table.append(row);}details.append(table);}
    if(tab==='lightburn'&&report){details.append(node('p',t('laser.event',{status:report.event?.success?t('laser.success'):t('laser.unverified'),hash:report.source_sha256.slice(0,16)})));if(report.remaining_sheets?.length)details.append(node('p',t('laser.remaining')+report.remaining_sheets.join(', ')));}
    const preview=tab==='design'?'design/design.svg':tab==='panels'?'panels/panels-preview.svg':`nest/sheet-${String(Number(sheet.value)||1).padStart(2,'0')}-preview.svg`;
    const artifact=Object.values(workflow?.stages||{}).flatMap(s=>s.artifacts).find(a=>a.name===preview);
    const pk=workflow?.id+'/'+artifact?.sha256;
    if(previewKey!==pk){previewKey=pk;picture.hidden=true;if(artifact){const id=workflow.id;api.laser({action:'artifact',id,name:preview}).then(r=>{if(previewKey!==pk||disposed)return;picture.src=`data:${r.mime};base64,${r.base64}`;picture.hidden=false;}).catch(e=>{error.textContent=e.message;error.hidden=false;});}}
    downloads.replaceChildren();for(const a of step?.artifacts||[]){if(a.name.includes('preview'))continue;const b=button(a.name.split('/').at(-1),()=>perform(async()=>{const r=await api.laser({action:'artifact',id:workflow.id,name:a.name});const bytes=Uint8Array.from(atob(r.base64),c=>c.charCodeAt(0));await downloadFile(api,bytes,r.name,r.mime,{kind:'laser',id:workflow.id,artifact:a.name});}));b.disabled=busy;b.title=t('laser.download',{name:a.name.split('/').at(-1)});downloads.append(b);}
  }
  const ready=load();const timer=setInterval(()=>{if(active)load();},1800);
  return {ready,setState(){},setActive(v){active=v;if(v)load();},dispose(){disposed=true;clearInterval(timer);},
    getPresentation:()=>({id:workflow?.id,tab}),async restorePresentation(v){if(v?.id)await this.openWorkflow(v.id,v.tab);},
    async openWorkflow(id,view){workflow=(await api.laser({action:'read',id})).workflow;tab=stages.includes(view)?view:lastStage();await list();render(true);}};
}
