import { t } from './i18n.js';
import { uploadFile } from './upload.js';

export const manufacturingStages = ['inspect','local_repair','split','connect','coupon','audit','prepare','compare','deliver','reprint'];
const geometryStages = ['inspect','local_repair','split','connect'];
const tr = (key, params) => t(`manufacture.${key}`, params);
export function manufacturingSliceTotals(scenario) {
  const plates=scenario?.check?.plates;
  if(!Array.isArray(plates)||!plates.length||plates.some(p=>p.returncode!==0||!Number.isFinite(p.grams)||p.grams<0||!Number.isFinite(p.seconds)||p.seconds<=0)) return null;
  return {grams:plates.reduce((s,p)=>s+p.grams,0),seconds:plates.reduce((s,p)=>s+p.seconds,0),plates:plates.length,warnings:plates.flatMap(p=>p.warnings||[]).length};
}
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function button(label, action) { const b = node('button', label); b.type = 'button'; b.onclick = action; return b; }

export function createManufacturing(api, options = {}) {
  const root = document.getElementById('manufacture-space');
  root.classList.add('manufacturing');
  let workflow = null, disposed = false, active = true, busy = false, polling = false, lastRevision = -1;
  let files = [], resultFiles = [], labelFiles = [], printerList = [], tasks = [], currentState = null;
  const controls = {}, rows = {};
  let partsStamp="", defectsStamp="";
  const header = node('header', null, 'mf-header');
  const title = node('div'); title.append(node('h2', tr('title')), node('p', tr('subtitle')));
  const picker = node('select'); picker.setAttribute('aria-label', tr('saved'));
  const reload = button(tr('refresh'), () => refresh(true));
  header.append(title, picker, reload);
  const error = node('p', null, 'mf-error'); error.setAttribute('role', 'alert'); error.hidden = true;
  const grid = node('div', null, 'mf-grid');
  const setup = node('div', null, 'mf-setup'), progress = node('div', null, 'mf-progress'); grid.append(setup, progress);
  root.replaceChildren(header, error, grid);
  const source = section('source', setup);
  const name = field(source, 'titleInput', 'titleInput', 'text', '');
  const fileInput = node('input'); fileInput.type = 'file'; fileInput.multiple = true; fileInput.accept = '.stl,.glb,.obj,.ply';
  const fileLabel = node('label', tr('files')); fileLabel.append(fileInput); source.append(fileLabel);
  fileInput.onchange = () => { files = [...fileInput.files]; sourceHint.textContent = files.map(f => f.name).join(' · '); };
  const sourceHint = node('p', tr('sourceHint'), 'mf-hint'); source.append(sourceHint);
  const resultSelect = node('select'); resultSelect.setAttribute('aria-label', tr('taskResult')); source.append(resultSelect);
  const sourceActions = node('div', null, 'mf-actions');
  const create = button(tr('create'), () => operation(async () => {
    const paths = [];
    for (const file of files) paths.push((await uploadFile(body => api.task(body), file)).path);
    const selected = resultFiles.find(r => r.value === resultSelect.value);
    if (selected) paths.push(selected.path);
    const result = await api.manufacture({action:'create', files:paths, title:name.value, requirements:requirements()});
    adopt(result.workflow, true); await list();
  }));
  const fromSelection = button(tr('selection'), () => operation(async () => {
    const state = await api.getState();
    const result = await api.manufacture({action:'create', from_selection:true, expected_editor_revision:state.workbench.revision,
      title:name.value, requirements:requirements()});
    adopt(result.workflow, true); await list();
  }));
  const generation = button(tr('generation'), () => options.onService?.('lux3d', 'image-to-3d'));
  const segmentation = button(tr('segmentation'), () => options.onService?.('p3sam', 'segment'));
  sourceActions.append(create, fromSelection, generation, segmentation); source.append(sourceActions);

  const requirementsSection = section('requirements', setup);
  const printer = select(requirementsSection, 'printer', 'printer', []);
  const defaultPrinter=node('option','Bambu Lab P1S 0.4 nozzle'); defaultPrinter.value='Bambu Lab P1S 0.4 nozzle'; printer.append(defaultPrinter);
  field(requirementsSection, 'material', 'material', 'text', 'PLA');
  field(requirementsSection, 'target_max_mm', 'target', 'number', '', {min:.1,max:10000,step:1});
  select(requirementsSection, 'split_mode', 'splitMode', ['fit','color','guided','keep']);
  const colors = field(requirementsSection, 'palette_rgb', 'palette', 'text', '#ffffff,#ff0000');
  colors.dataset.codec = 'palette';
  const direction = field(requirementsSection, 'pull_direction', 'pull', 'text', '0,0,1'); direction.dataset.codec = 'vector';
  field(requirementsSection, 'inlay_depth_mm', 'inlayDepth', 'number', 1.2, {min:.01,max:100,step:.1});
  const connectors = node('details'); connectors.append(node('summary', tr('connectorSettings'))); requirementsSection.append(connectors);
  select(connectors, 'profile', 'profile', ['keyed','round']);
  for (const [key, label, value] of [['radius_mm','radius',2],['depth_mm','depth',6],['clearance_mm','clearance',.2],['min_wall_mm','wall',1.6]]) {
    field(connectors, key, label, 'number', value, {min:.01,max:key==='clearance_mm'?2:100,step:.05});
  }
  const advanced = node('details'); advanced.append(node('summary', tr('advanced'))); requirementsSection.append(advanced);
  const boxes = field(advanced, 'protected_boxes_mm', 'protected', 'textarea', '[]'); boxes.dataset.codec = 'json';
  const mapping = field(advanced, 'label_map', 'labelMap', 'textarea', '{}'); mapping.dataset.codec = 'json';
  field(advanced, 'guided_seam_tolerance_mm', 'seamTolerance', 'number', 0, {min:0,max:20,step:.1});
  advanced.append(node('p', tr('seamToleranceHint'), 'mf-hint'));
  select(advanced, 'strategy', 'strategy', ['auto','flat','support','upright']);
  select(advanced, 'shape', 'shape', ['generic','figurine','relief','mechanical']);
  field(advanced, 'gap_mm', 'gap', 'number', 4, {min:0,max:100,step:.5});
  field(advanced, 'process', 'process', 'text', ''); field(advanced, 'filament', 'filament', 'text', '');
  const save = button(tr('save'), () => operation(()=>sendRaw({action:'update',requirements:requirements()})));  requirementsSection.append(save);
  requirementsSection.append(node('p', tr('invalidationHint'), 'mf-hint'));

  const guided = section('guidance', setup);
  guided.append(node('p', tr('guidanceHint'), 'mf-hint'));
  const labels = node('textarea'); labels.rows = 7; labels.setAttribute('aria-label', tr('labels')); labels.placeholder = '{"source_sha256":"…","nodes":{"node":["body","body","leg"]}}';
  const labelsInput = node('input'); labelsInput.type = 'file'; labelsInput.accept = '.json'; labelsInput.setAttribute('aria-label', tr('labelFile'));
  const labelResult = node('select'); labelResult.setAttribute('aria-label', tr('labelTask'));
  labelsInput.onchange = () => operation(async () => { if (labelsInput.files[0]) labels.value = await labelsInput.files[0].text(); });
  guided.append(labelsInput, labels, button(tr('saveLabels'), () => operation(async () => { await sendRaw({action:'labels',labels:JSON.parse(labels.value)}); })));
  guided.append(labelResult, button(tr('loadLabelTask'), () => operation(async () => {
    const item = labelFiles.find(r => r.value === labelResult.value);
    if (!item) throw new Error(tr('labelTask'));
    const buffer = await api.taskAsset(item.task, item.artifact);
    const doc = JSON.parse(new TextDecoder().decode(buffer));
    await sendRaw({action:'labels', labels:doc});
    labels.value=JSON.stringify(doc,null,2);
  })));
  const hashes = node('div', null, 'mf-hashes'); guided.append(hashes);

  const repair = section('repair', setup);
  repair.append(node('p', tr('repairHint'), 'mf-hint'));
  const repairStatus = node('p', tr('unconnected'), 'mf-status');
  repair.append(repairStatus, button(tr('repairEntry'), () => operation(async () => {
    if (!workflow) throw new Error(tr('createFirst'));
    const result = await api.manufacture({action:'repair_status',id:workflow.id});
    repairStatus.textContent = `${tr('unconnected')} · ${tr('reinspectionRequired')} · ${result.repair_api.input_sha256.map(s=>s.slice(0,12)).join(', ')}`;
  })));
  const note = node('textarea'); note.rows = 3; note.setAttribute('aria-label', tr('defectNote')); note.placeholder = tr('defectNote');
  const photos = node('input'); photos.type = 'file'; photos.accept = '.png,.jpg,.jpeg'; photos.multiple = true; photos.setAttribute('aria-label', tr('defectPhotos'));
  const defectList = node('div', null, 'mf-defects');
  repair.append(note, photos, button(tr('recordDefect'), () => operation(async () => {
    const paths = [];
    for (const file of photos.files) paths.push((await uploadFile(body=>api.task(body), file)).path);
    await sendRaw({action:'defect',note:note.value,photos:paths}); note.value=''; photos.value='';
  })), defectList);

  const stageSection = section('stages', progress);
  const summary = node('p', tr('empty'), 'mf-hint'); stageSection.append(summary);
  for (const stage of manufacturingStages) {
    const row = node('article', null, 'mf-stage'); row.dataset.stage = stage;
    const head = node('div', null, 'mf-stage-head');
    const text = node('div'); text.append(node('strong',tr(`stage.${stage}`)), node('p',tr(`stageHint.${stage}`),'mf-hint'));
    const badge = node('span',tr('pending'),'mf-badge'); head.append(text,badge);
    const actions = node('div', null,'mf-actions');
    const run = button(tr('run'), () => send({action:'run',stage, ...(stage==='reprint'?{part_ids:chosenParts()}: {})}));
    run.setAttribute('aria-label', `${tr('run')} · ${tr(`stage.${stage}`)}`);
    const preview = button(tr('result'), () => options.onResult?.(workflow?.stages?.[stage]?.task_id, false));
    const delivery = button(tr('filesResult'), () => options.onResult?.(workflow?.stages?.[stage]?.task_id, true));
    const details = node('details'); details.append(node('summary',tr('report'))); const report = node('pre'); details.append(report);
    const failure = node('p',null,'mf-error'); failure.hidden=true;
    const receipt = node('p',null,'mf-receipt'); receipt.hidden=true;
    actions.append(run,preview,delivery); row.append(head,receipt,actions,failure,details); stageSection.append(row);
    rows[stage] = {row,run,preview,delivery,badge,failure,report,receipt};
  }
  const cancel = button(tr('cancelStage'),()=>send({action:'cancel'})); stageSection.append(cancel);
  const partsSection = section('parts', progress);
  const partList = node('div',null,'mf-parts'); partsSection.append(node('p',tr('reprintHint'),'mf-hint'),partList);
  const calibration = section('calibration', progress);
  const candidate = node('select'); candidate.setAttribute('aria-label',tr('couponClearance'));
  const calibrationNote = node('textarea'); calibrationNote.rows=3; calibrationNote.setAttribute('aria-label',tr('calibrationNote')); calibrationNote.placeholder=tr('calibrationNote');
  const calibrationRecords = node('div');
  calibration.append(candidate,calibrationNote,button(tr('recordCalibration'),()=>send({action:'calibration',clearance_mm:Number(candidate.value),note:calibrationNote.value})),calibrationRecords);
  const history = section('history',progress); const historyList = node('div'); history.append(historyList);
  const jumps=node('nav',null,'mf-jumps');jumps.setAttribute('aria-label',tr('jump'));
  jumps.append(button(tr('jumpStages'),()=>stageSection.scrollIntoView({block:'start'})),
    button(tr('jumpParts'),()=>partsSection.scrollIntoView({block:'start'})),
    button(tr('jumpRepair'),()=>repair.scrollIntoView({block:'start'})));
  header.after(jumps);

  function section(key,parent) { const e=node('section',null,'mf-card'); e.append(node('h3',tr(key))); parent.append(e); return e; }
  function field(parent,key,label,type,value,attrs={}) {
    const input = node(type==='textarea'?'textarea':'input'); if(type!=='textarea') input.type=type;
    input.value=value; input.name=key; Object.assign(input,attrs); input.setAttribute('aria-label',tr(label));
    const wrapper=node('label',tr(label)); wrapper.append(input); parent.append(wrapper); controls[key]=input; return input;
  }
  function select(parent,key,label,values) {
    const input=node('select'); input.name=key; input.setAttribute('aria-label',tr(label));
    for(const value of values) { const o=node('option',tr(`option.${value}`)); o.value=value; input.append(o); }
    const wrapper=node('label',tr(label)); wrapper.append(input); parent.append(wrapper); controls[key]=input; return input;
  }
  function requirements() {
    const result={};
    for (const [key,element] of Object.entries(controls)) {
      if(key==='titleInput') continue;
      let value=element.value;
      if(element.dataset.codec==='json') value=JSON.parse(value);
      else if(element.dataset.codec==='vector') value=value.split(',').map(Number);
      else if(element.dataset.codec==='palette') value=value.split(',').map(v=>{
        if(!/^#[a-f0-9]{6}$/i.test(v.trim())) throw new Error(tr('paletteInvalid'));
        return [1,3,5].map(i=>parseInt(v.trim().slice(i,i+2),16));
      });
      else if(element.type==='number') value=value===''?null:Number(value);
      if(['process','filament'].includes(key)&&value==='') value=null;
      result[key]=value;
    }
    return result;
  }
  function chosenParts() {return [...partList.querySelectorAll('input:checked')].map(e=>e.value);}
  async function operation(fn) {
    if(busy) return false;
    busy=true; error.hidden=true; update();
    try {await fn(); return true;} catch(e) {error.textContent=e.message; error.hidden=false; return false;}
    finally {busy=false; update();}
  }
  async function sendRaw(body) {
    if(!workflow) throw new Error(tr('createFirst'));
    if(body.action==='run') {
      const stable=value=>Array.isArray(value)?value.map(stable):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).sort().map(([k,v])=>[k,stable(v)])):value;
      if(Object.entries(requirements()).some(([k,v])=>JSON.stringify(stable(v))!==JSON.stringify(stable(workflow.requirements[k]??(k==='guided_seam_tolerance_mm'?0:undefined))))) throw new Error(tr('unsavedRequirements'));
    }
    const result=await api.manufacture({...body,id:workflow.id,expected_revision:workflow.revision});
    if(result.workflow) adopt(result.workflow);
    else await refresh();
    return result;
  }
  const send = body => operation(()=>sendRaw(body));
  function adopt(doc, fill=false) {
    workflow=doc; lastRevision=doc.revision;
    if(fill) {
      name.value=doc.title;
      for(const [key,element] of Object.entries(controls)) {
        if(key==='titleInput') continue;
        let value=doc.requirements[key]??(key==='guided_seam_tolerance_mm'?0:undefined);
        if(element.dataset.codec==='json') value=JSON.stringify(value);
        else if(element.dataset.codec==='vector') value=value.join(',');
        else if(element.dataset.codec==='palette') value=value.map(rgb=>'#'+rgb.map(c=>c.toString(16).padStart(2,'0')).join('')).join(',');
        if(key==='printer'&&![...element.options].some(o=>o.value===value)) {const o=node('option',value);o.value=value;element.prepend(o);}
        element.value=value??'';
      }
      labels.value=doc.labels?JSON.stringify(doc.labels,null,2):'';
    }
    picker.value=doc.id;
    update();
  }
  function update() {
    const running=!!workflow?.active;
    picker.disabled=busy; reload.disabled=busy;
    save.disabled=!workflow||busy||running; create.disabled=busy; fromSelection.disabled=busy;
    cancel.disabled=!running||busy;
    summary.textContent=workflow?`${workflow.title} · ${tr('revision',{revision:workflow.revision})} · ${running?tr('running'):tr('savedReady')}`:tr('empty');
    for(const [stage,e] of Object.entries(rows)) {
      const record=workflow?.stages?.[stage]; const status=record?.status||'pending';
      const quality=record?.report?.status;
      e.badge.textContent=tr(status==='completed'&&['needs_review','needs_repair'].includes(quality)?quality:status);
      e.row.dataset.status=status; e.row.dataset.quality=quality||'';
      e.run.disabled=!workflow||busy||running;
      e.preview.disabled=!record?.task_id||status!=='completed'; e.delivery.disabled=e.preview.disabled;
      e.failure.hidden=!record?.error; e.failure.textContent=record?.error||'';
      e.report.textContent=record?.report?JSON.stringify(record.report,null,2):tr('noReport');
      e.receipt.hidden=!record?.report; e.receipt.textContent='';
      const result=record?.report;
      if(result) {
        if(stage==='compare') e.receipt.textContent=(result.scenarios||[]).map(s=>{
          const totals=manufacturingSliceTotals(s);
          return totals?tr('sliceTotals',{strategy:tr(`option.${s.strategy}`),grams:totals.grams.toFixed(2),minutes:(totals.seconds/60).toFixed(1),plates:totals.plates,warnings:totals.warnings}):tr('noSliceReceipt');
        }).join('\n');
        else if(stage==='audit') e.receipt.textContent=tr('auditSummary',{quality:tr(result.status),unresolved:result.unresolved_parts.length,thin:result.thin_sample_parts.length,unchecked:Array.isArray(result.unchecked_thickness_parts)?result.unchecked_thickness_parts.length:tr('coverageUnrecorded'),physical:result.unresolved_physical_defects?tr('unresolved'):tr('noRecordedDefect')});
        else if(['inspect','local_repair'].includes(stage)) e.receipt.textContent=tr('inspectSummary',{parts:result.parts.length,open:result.diagnostics.reduce((s,r)=>s+r.open_edges,0),quality:result.closed_outputs?tr('closed'):tr('needs_repair')});
        else if(['prepare','reprint'].includes(stage)) e.receipt.textContent=tr('plateSummary',{plates:result.plates.length,parts:result.parts.length});
        else if(stage==='coupon') e.receipt.textContent=tr('couponSummary',{values:result.clearance_candidates_mm.join(' / ')});
        else if(stage==='split') e.receipt.textContent=tr('splitSummary',{parts:result.parts.length});
        else if(stage==='connect') e.receipt.textContent=tr('pinSummary',{seams:result.seams.length});
        else if(stage==='deliver') e.receipt.textContent=tr('packageSummary');
      }
    }
    const selected=new Set(chosenParts());
    const current=geometryStages.map(s=>workflow?.stages?.[s]).reverse().find(s=>s?.status==='completed');
    const nextParts=JSON.stringify(current?.report?.parts||[]);
    if(nextParts!==partsStamp) {
    partsStamp=nextParts; partList.replaceChildren();
    for(const part of current?.report?.parts||[]) {
      const wrapper=node('label',null,'mf-part'); const input=node('input'); input.type='checkbox'; input.value=part.id; input.checked=selected.has(part.id);
      const color=part.color_rgb?' · #'+part.color_rgb.map(c=>c.toString(16).padStart(2,'0')).join(''):'';
      wrapper.append(input,node('span',`${part.id} · ${part.name}${color} · ${part.extents_mm.map(x=>x.toFixed(1)).join(' × ')} mm`)); partList.append(wrapper);
    }
    }
    hashes.replaceChildren(); for(const s of workflow?.sources||[]) hashes.append(node('small',`${s.name} · SHA256 ${s.source_sha256}`));
    const values=workflow?.stages?.coupon?.status==='completed'?workflow.stages.coupon.report.clearance_candidates_mm:[];
    const oldValue=candidate.value; candidate.replaceChildren();
    for(const gap of values) {const o=node('option',`${gap} mm`);o.value=gap;candidate.append(o);} if(values.includes(Number(oldValue))) candidate.value=oldValue;
    const nextDefects=JSON.stringify(workflow?.defects||[]);
    if(nextDefects!==defectsStamp) {
    defectsStamp=nextDefects; defectList.replaceChildren();
    for(const d of workflow?.defects||[]) {
      const entry=node('article'); entry.append(node('p',`${d.note} · ${d.resolved?tr('resolved'):tr('unresolved')} · ${tr('photosCount',{count:d.photos.length})}`));
      const images=node('div',null,'mf-photos');
      if(d.photos.length) entry.append(button(tr('viewPhotos'),async()=>{
        try {
          error.hidden=true;
          if(images.childElementCount) {images.hidden=!images.hidden;return;}
          for(let index=0;index<d.photos.length;index++) {
            const result=await api.manufacture({action:'photo',id:workflow.id,defect_id:d.id,photo_index:index});
            const img=node('img');img.src=`data:${result.mime};base64,${result.data_base64}`;img.alt=tr('defectImage',{index:index+1});images.append(img);
          }
        } catch(e) {error.textContent=e.message;error.hidden=false;}
      }));
      entry.append(images);
      if(!d.resolved) {
        const text=node('textarea');text.rows=2;text.setAttribute('aria-label',tr('reinspectionNote'));
        entry.append(text,button(tr('recordReinspection'),()=>send({action:'defect',defect_id:d.id,resolved:true,note:text.value})));
      } else entry.append(node('p',d.reinspection));
      defectList.append(entry);
    }
    }
    calibrationRecords.replaceChildren();
    for(const r of workflow?.calibration||[]) calibrationRecords.append(node('p',`${r.printer} · ${r.material} · ${r.clearance_mm} mm · ${r.note}`));
    historyList.replaceChildren();
    for(const h of [...(workflow?.history||[])].reverse().slice(0,30)) {
      const entry=node('p',`${tr(`stage.${h.stage}`)} · ${new Date(h.at*1000).toLocaleString()}`);
      if(h.previous?.task_id) entry.append(button(tr('previousResult'),()=>options.onResult?.(h.previous.task_id,true)));
      historyList.append(entry);
    }
  }
  async function list() {
    const data=await api.manufacture({action:'list'});
    picker.replaceChildren(); const empty=node('option',tr('newWorkflow'));empty.value='';picker.append(empty);
    for(const doc of data.workflows) {const o=node('option',doc.title);o.value=doc.id;picker.append(o);}
    if(workflow) picker.value=workflow.id;
    return data.workflows;
  }
  picker.onchange=()=>{
    const identity=picker.value;
    return operation(async()=>{
      workflow=null;lastRevision=-1;update();
      if(!identity) return;
      const result=await api.manufacture({action:'read',id:identity});adopt(result.workflow,true);
    });
  };
  async function refresh(full=false) {
    if(polling||disposed) return;
    polling=true;
    try {
      if(full) {
        await list();
        const taskData=await api.tasks(); tasks=taskData.tasks;
        labelFiles=tasks.filter(r=>r.status==='completed').flatMap(r=>(r.artifacts||[]).filter(a=>a.name.endsWith('source-bound-labels.json')).map(a=>({value:`${r.id}/${a.id}`,task:r.id,artifact:a,title:r.title})));
        const oldLabel=labelResult.value;labelResult.replaceChildren();const noLabel=node('option',tr('labelTask'));noLabel.value='';labelResult.append(noLabel);
        for(const item of labelFiles) {const o=node('option',item.title);o.value=item.value;labelResult.append(o);}labelResult.value=oldLabel;
        resultFiles=tasks.filter(r=>r.status==='completed').flatMap(r=>(r.artifacts||[]).filter(a=>/\.(glb|stl|obj|ply)$/i.test(a.name)).map(a=>({value:`${r.id}/${a.id}`,path:a.path,title:`${r.title} · ${a.name}`})));
        const old=resultSelect.value;resultSelect.replaceChildren();const none=node('option',tr('taskResult'));none.value='';resultSelect.append(none);
        for(const item of resultFiles) {const o=node('option',item.title);o.value=item.value;resultSelect.append(o);}resultSelect.value=old;
      }
      if(workflow) {
        const identity=workflow.id;
        const result=await api.manufacture({action:'read',id:identity});
        if(workflow?.id===identity&&result.workflow.revision>lastRevision) adopt(result.workflow);
      }
    } catch(e) {error.textContent=e.message;error.hidden=false;} finally {polling=false;}
  }
  const timer=setInterval(()=>{if(active&&!document.hidden&&!busy&&workflow?.active) refresh();},1200);
  const ready=(async()=>{
    await api.init();const result=await api.getPrinters();printerList=result.printers||[];
    for(const p of printerList) {const o=node('option',`${p.vendor||''} · ${p.display_name||p.name}`);o.value=p.name;printer.append(o);}
    await refresh(true);update();
  })().catch(e=>{error.textContent=e.message;error.hidden=false;});
  async function openWorkflow(identity) {
    await ready;
    if(workflow?.id===identity) {await refresh();return true;}
    return operation(async()=>{
      workflow=null;lastRevision=-1;update();
      const result=await api.manufacture({action:'read',id:identity});
      await list();adopt(result.workflow,true);
    });
  }
  return {ready,openWorkflow,getPresentation:()=>({workflow_id:workflow?.id}),
    async restorePresentation(value){if(value?.workflow_id)await openWorkflow(value.workflow_id);},
    setState(state){currentState=state;},setActive(value){active=value;if(value)refresh(true);},dispose(){disposed=true;clearInterval(timer);},refresh};
}
