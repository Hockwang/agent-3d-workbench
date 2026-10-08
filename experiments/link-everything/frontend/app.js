import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {project:null, previous:null, mode:'assembled', compare:false, selectedType:'tongue_slot', busy:false, playing:false, progress:1, models:new Map(), loadToken:0, recording:null, selectedPart:null};
const fields = {clearance_mm:'#clearance', engagement_mm:'#engagement', position_mm:'#position', wall_mm:'#wall', cavity_depth_mm:'#cavity-depth',beam_thickness_mm:'#beam-thickness',hook_mm:'#hook-depth'};
const limits = {clearance_mm:[.1,.65],engagement_mm:[5,10],position_mm:[-5,5],wall_mm:[2,3.2],cavity_depth_mm:[28,45],beam_thickness_mm:[.9,1.6],hook_mm:[.45,1.1]};
const typeName = (type) => type === 'snap_fit' ? '可释放卡扣' : '插舌与槽';
const revisionName = (revision) => `R${String(revision).padStart(4,'0')}`;
const safe = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

for (const [key, selector] of Object.entries(fields)) { const el=$(selector); el.min=limits[key][0]; el.max=limits[key][1]; }
$('#clearance-range').max=.65;
$('#cavity-depth').step=.01;
const query = new URLSearchParams(location.search);
document.body.classList.toggle('embed', query.get('embed')==='1');
if(query.get('embed')==='1')$('.embed-banner span').textContent=window.parent!==window?'本地工作台联调 · 未合入上游插件':'独立装配设计模块 · 嵌入布局预览';
$('#embed-toggle').onclick = () => { const url=new URL(location.href);url.searchParams.set('embed','1');location.href=url.href; };
$('#exit-embed').onclick = () => { const url=new URL(location.href);url.searchParams.delete('embed');location.href=url.href; };

const viewport = $('#viewport');
const scene = new THREE.Scene(); scene.background = new THREE.Color('#e8ede7');
const camera = new THREE.PerspectiveCamera(34, 1, .0002, 10);
const renderer = new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.25;
renderer.localClippingEnabled=true;
viewport.appendChild(renderer.domElement);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.08;controls.minDistance=.025;controls.maxDistance=.65;controls.maxPolarAngle=Math.PI*.88;controls.target.set(0,0,0);
scene.add(new THREE.HemisphereLight('#f9fff5','#bcc5b7',2.7));
const keyLight=new THREE.DirectionalLight('#fff8e9',4.5);keyLight.position.set(.09,.15,.09);keyLight.castShadow=true;keyLight.shadow.mapSize.set(2048,2048);keyLight.shadow.camera.left=-.12;keyLight.shadow.camera.right=.12;keyLight.shadow.camera.top=.12;keyLight.shadow.camera.bottom=-.12;keyLight.shadow.camera.near=.01;keyLight.shadow.camera.far=.6;keyLight.shadow.bias=-.00002;keyLight.shadow.normalBias=.00006;scene.add(keyLight);
const fillLight=new THREE.DirectionalLight('#d4ebee',1.1);fillLight.position.set(-.1,.04,-.12);scene.add(fillLight);
const ground=new THREE.Mesh(new THREE.PlaneGeometry(1,1),new THREE.MeshStandardMaterial({color:'#e8ede4',roughness:1}));ground.rotation.x=-Math.PI/2;ground.receiveShadow=true;ground.position.y=-.03;scene.add(ground);
const grid=new THREE.GridHelper(.24,24,'#c8d3c7','#d9e1d4');grid.position.y=ground.position.y+.000025;grid.material.transparent=true;grid.material.opacity=.32;scene.add(grid);
const modelRoot=new THREE.Group();scene.add(modelRoot);
const loader=new GLTFLoader();
const clippingPlane=new THREE.Plane(new THREE.Vector3(0,0,-1),0);
let currentBox=new THREE.Box3(), lastTime=0, roiGroup=null;
const connectionLabel=document.createElement('div');connectionLabel.className='connection-label hidden';connectionLabel.innerHTML='<span></span><b>连接 01</b><small>双方结构同步生成</small>';viewport.appendChild(connectionLabel);

new ResizeObserver(() => {const {width,height}=viewport.getBoundingClientRect();renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();}).observe(viewport);

function fitView(){
  if(modelRoot.children.length===0)return;
  const box=new THREE.Box3().setFromObject(modelRoot);const size=box.getSize(new THREE.Vector3());const center=box.getCenter(new THREE.Vector3());
  const radius=Math.max(size.x,size.y,size.z)*1.65;
  camera.position.copy(center).add(new THREE.Vector3(1.2,.82,1.35).normalize().multiplyScalar(radius*1.9));
  controls.target.copy(center);controls.update();
}

function disposeGroup(group){group.traverse(o=>{if(o.isMesh){o.geometry?.dispose();if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material?.dispose();}});}

function setBusy(busy,title='正在生成配对连接',detail='计算实体布尔、配合尺寸与装配路径…'){
  state.busy=busy;$('#loading-overlay').classList.toggle('hidden',!busy);$('#loading-title').textContent=title;$('#loading-detail').textContent=detail;
  $('#generate-design').disabled=busy;$('#reset-project').disabled=busy;$('#play-motion').disabled=busy;
  $$('.candidate').forEach(el=>el.disabled=busy);
}
function showError(error){$('#error-message').textContent=error?.message||String(error);$('#error-banner').classList.remove('hidden');$('#status-message').textContent='操作未完整完成 · 查看错误详情与版本记录。';}
$('#dismiss-error').onclick=()=>$('#error-banner').classList.add('hidden');
async function request(path, options={}){
  const response=await fetch(path,{...options,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}});
  let data;try{data=await response.json();}catch{throw new Error(`服务未返回 JSON（HTTP ${response.status}）`);}
  if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
  return data;
}

function applyParameters(parameters){
  for(const [key,selector] of Object.entries(fields))if(parameters[key]!==undefined)$(selector).value=parameters[key];
  $('#clearance-range').value=parameters.clearance_mm;
  selectType(parameters.type,false);
  $('#change-state').textContent='当前参数已保存。修改后点击生成，查看新版本。';$('#change-state').classList.remove('dirty');
}
function getParameters(){const parameters={type:state.selectedType,revision:state.project?.revision};for(const [key,selector] of Object.entries(fields)){const el=$(selector);if(!el.checkValidity())throw new Error(`${el.closest('.parameter').querySelector('label').textContent}需在 ${el.min}–${el.max} mm 之间。`);parameters[key]=Number(el.value);}return parameters;}
function selectType(type,dirty=true){state.selectedType=type;$$('.candidate').forEach(el=>el.classList.toggle('selected',el.dataset.type===type));$('#snap-parameters').classList.toggle('hidden',type!=='snap_fit');if(dirty)markDirty();}
function markDirty(){$('#change-state').textContent='参数有修改 · 点击生成后才会更新真实几何。';$('#change-state').classList.add('dirty');}

function checkStatus(status){return status==='pass'?'pass':status==='fail'?'fail':['review','warning','warn'].includes(status)?'warn':'neutral';}
function statusSymbol(status){return {pass:'✓',fail:'×',warn:'!',neutral:'○'}[checkStatus(status)];}
function renderReport(project){
  const report=project.report||{}, checks=report.checks||[];
  const passes=checks.filter(c=>c.status==='pass').length;
  $('#check-count').textContent=`${passes}/${checks.length} 项通过 · 实物待验证`;
  $('#check-summary').innerHTML=checks.map(c=>`<button class="check-chip ${checkStatus(c.status)}" title="${safe(c.detail)}"><span class="check-dot">${statusSymbol(c.status)}</span>${safe(c.label)}</button>`).join('');
  $('#check-details').innerHTML=checks.map(c=>`<div class="check-detail ${checkStatus(c.status)}"><span>${statusSymbol(c.status)}</span><div><b>${safe(c.label)}</b><p>${safe(c.detail)}</p></div></div>`).join('')+(report.limitations?.length?`<div class="report-limitations"><b>当前边界</b><ul>${report.limitations.map(l=>`<li>${safe(l)}</li>`).join('')}</ul></div>`:'');
  $$('.check-chip').forEach(el=>el.onclick=()=>{$('#check-details').classList.remove('hidden');$('#detail-toggle').textContent='收起详情 ↑';});
  const assembly=report.assembly||{};
  $('#preview-status').textContent=assembly.rigid_collision?'存在刚性接触 · 需弹性验证':'采样路径无体积穿插';
  $('#preview-status').classList.toggle('warning',!!assembly.rigid_collision);
  $('#motion-note').textContent=assembly.elastic_contact_expected?'卡扣运动显示刚体轨迹；接触处需要弹性让位，动画不代表真实形变或强度验证。':'刚体平移预览；后端检查 41 个离散姿态，不代表连续扫掠或实物装配已验证。';
  const artifact=project.artifacts?.find(a=>a.id==='coupon_pair_print_layout.stl')||project.artifacts?.find(a=>/coupon.*stl/i.test(a.id));
  $('#export-button').disabled=!artifact;$('#export-button').onclick=()=>artifact&&downloadUrl(artifact.url,artifact.id);
  const important=['assembly.glb','part_a.stl','part_b.stl','parameters.json','report.json','workbench_handoff.json'];
  $('#artifact-list').innerHTML=(project.artifacts||[]).filter(a=>important.includes(a.id)).map(a=>`<a href="${safe(a.url)}" download="${safe(a.id)}">${safe(a.label)} ↗</a>`).join('');
}

function renderHistory(project){
  $('#history-list').innerHTML=[...(project.history||[])].reverse().slice(0,12).map(h=>`<div class="history-row"><span class="history-revision">${revisionName(h.revision)}</span><div class="history-title"><b>${safe(typeName(h.type||h.parameters?.type))}</b><small>间隙 ${safe(h.parameters?.clearance_mm)} mm · 深度 ${safe(h.parameters?.cavity_depth_mm)} mm · ${safe(h.created_at||'')}</small></div><a class="text-button" href="${safe(h.report_url)}" target="_blank">报告 ↗</a></div>`).join('');
}

function renderProject(project){
  $('#revision-label').textContent=revisionName(project.revision);
  $('#api-status').innerHTML='<i></i>本地服务已连接';$('#api-status').classList.remove('error');
  $('#part-list').innerHTML=project.parts.map((p,i)=>`<button class="part-card ${state.selectedPart===p.id?'selected':''}" data-part="${safe(p.id)}"><span class="part-color" style="background:${safe(p.color||'#9bbbbc')}"></span><span><b>${safe(p.name)}</b><small>${i===0?'A · 接收侧':'B · 插入侧'}</small></span><span class="part-state">实体</span></button>`).join('');
  $$('.part-card').forEach(el=>el.onclick=()=>selectPart(el.dataset.part));
  $('#show-source').disabled=!project.source?.url;
  $('#view-modes [data-view=source]').disabled=!project.source?.url;
  $('#compare-toggle').disabled=!state.previous;
  $('#execution-info').textContent=`版本：${revisionName(project.revision)}\n生成耗时：${project.elapsed_ms??'—'} ms\n源单位：mm / 预览单位：m\n执行：参数化模板 + 实体布尔\n大模型调用：${project.report?.real_llm_invocation?'是':'否'}\nFEA：${project.report?.fea_performed?'是':'否'}\n真实打印：${project.report?.physical_print_performed?'是':'否'}\n部件：${project.parts.map(p=>p.id).join(', ')}`;
  $('#status-message').textContent=`${revisionName(project.revision)} · 真实几何已保存 · ${project.elapsed_ms??'—'} ms · 几何服务返回 ${project.report?.checks?.length??0} 项检查`;
  applyParameters(project.parameters);renderReport(project);renderHistory(project);
}

async function fetchModel(part){const gltf=await loader.loadAsync(part.url);const object=gltf.scene;object.name=part.id;object.userData={part,originalPosition:object.position.clone()};object.traverse(child=>{if(!child.isMesh)return;const color=part.color||'#8cbdc6';if(!child.geometry.getAttribute('normal')){const oldGeometry=child.geometry;child.geometry=oldGeometry.index?oldGeometry.toNonIndexed():oldGeometry.clone();child.geometry.computeVertexNormals();oldGeometry.dispose();}child.material=new THREE.MeshStandardMaterial({color,vertexColors:false,roughness:.55,metalness:.02,flatShading:true,side:THREE.DoubleSide,clippingPlanes:[],clipShadows:true});child.castShadow=true;child.receiveShadow=true;child.userData.baseColor=color;});return object;}

async function loadModels(project,kind='parts'){
  const token=++state.loadToken;
  modelRoot.visible=false;connectionLabel.classList.add('hidden');
  let parts=project[kind]||project.parts;
  if(kind==='source'){if(!project.source?.url)throw new Error('未找到历史原件模型。');parts=[{id:'source',url:project.source.url,name:project.source.name,color:'#92b5c1',role:'source'}];}
  const objects=await Promise.all(parts.map(fetchModel));
  if(token!==state.loadToken){objects.forEach(disposeGroup);return;}
  for(const child of [...modelRoot.children]){modelRoot.remove(child);disposeGroup(child);}
  state.models.clear();objects.forEach(object=>{modelRoot.add(object);state.models.set(object.name,object);});
  modelRoot.visible=true;state.loadedRevision=project.revision;
  modelRoot.position.set(0,0,0);
  currentBox=new THREE.Box3().setFromObject(modelRoot);const center=currentBox.getCenter(new THREE.Vector3());modelRoot.position.copy(center).multiplyScalar(-1);
  const worldBox=new THREE.Box3().setFromObject(modelRoot);ground.position.y=worldBox.min.y-.00025;grid.position.y=ground.position.y+.000025;
  roiGroup=null;
  if(kind!=='source')addConnectionHighlight(project);
  applyViewMode();fitView();selectPart(state.selectedPart);
  $('#model-caption').textContent=kind==='source'?'历史兔形源件 · 只读参考，未被本轮生成改写':`${revisionName(project.revision)} · ${typeName(project.parameters.type)} · 间隙 ${project.parameters.clearance_mm} mm`;
}

function addConnectionHighlight(project){
  const joint=project.connections?.[0];if(!joint?.anchor_mm)return;
  const [x,y,z]=joint.anchor_mm, p=project.parameters, depth=p.engagement_mm;
  const geometry=new THREE.BoxGeometry(.0088,(depth+4)*.001,.0108);
  const edges=new THREE.EdgesGeometry(geometry);geometry.dispose();
  roiGroup=new THREE.LineSegments(edges,new THREE.LineBasicMaterial({color:'#4f8064',transparent:true,opacity:.48}));
  roiGroup.position.set((x+3.8)*.001,(z-depth/2+1)*.001,-y*.001);roiGroup.userData.labelPoint=new THREE.Vector3((x+8)*.001,(z+3)*.001,-y*.001);modelRoot.add(roiGroup);
}

function updateLabel(){
  if(!modelRoot.visible||!roiGroup||state.mode==='source'||state.compare||state.mode==='coupon'){connectionLabel.classList.add('hidden');return;}
  const point=roiGroup.userData.labelPoint.clone();modelRoot.localToWorld(point);point.project(camera);
  if(point.z>1||Math.abs(point.x)>1||Math.abs(point.y)>1){connectionLabel.classList.add('hidden');return;}
  connectionLabel.classList.remove('hidden');connectionLabel.style.left=`${(point.x*.5+.5)*viewport.clientWidth}px`;connectionLabel.style.top=`${(-point.y*.5+.5)*viewport.clientHeight}px`;
}

function selectPart(id){state.selectedPart=state.selectedPart===id?null:id;$$('.part-card').forEach(el=>el.classList.toggle('selected',el.dataset.part===state.selectedPart));for(const [key,object] of state.models){object.traverse(child=>{if(child.isMesh){child.material.emissive.set(key===state.selectedPart?'#344d39':'#000000');child.material.emissiveIntensity=key===state.selectedPart ? .18 : 0;}});}}

function applyViewMode(){
  for(const object of state.models.values())object.traverse(child=>{if(child.isMesh){child.material.clippingPlanes=state.mode==='section'?[clippingPlane]:[];child.material.needsUpdate=true;}});
  if(roiGroup)roiGroup.visible=state.mode!=='source';
  $$('#view-modes button').forEach(el=>el.classList.toggle('active',el.dataset.view===state.mode));
  $('#view-title').textContent={assembled:'连接结构预览',exploded:'配对部件 · 分解查看',section:'剖面 · 检查内部空间',source:'兔形原件 · 保护参考',coupon:'局部试装件 · 配对几何'}[state.mode];
  $('#view-subtitle').textContent=state.mode==='source'?'历史源件 · 只读':'真实后端几何 · mm';
  if(state.mode==='exploded')setProgress(.25);else if(state.mode!=='source')setProgress(1);
}

async function setView(mode){
  if(state.busy||!state.project)return;
  state.playing=false;$('#play-motion').textContent='▶';
  const needsLoad=state.mode==='source'||mode==='source'||state.mode==='coupon'||mode==='coupon';state.mode=mode;
  if(needsLoad){setBusy(true,'正在载入模型',mode==='source'?'读取冻结的历史兔形原件':'读取当前版本实体模型');try{await loadModels(state.compare&&state.previous?state.previous:state.project,mode==='source'?'source':mode==='coupon'?'coupons':'parts');}catch(error){showError(error);}finally{setBusy(false);}}else applyViewMode();
}

function setProgress(value){state.progress=THREE.MathUtils.clamp(value,0,1);$('#motion-progress').value=Math.round(state.progress*100);$('#progress-value').textContent=`${Math.round(state.progress*100)}%`;}
function updateMotion(){
  if(state.mode==='source')return;
  const project=state.compare&&state.previous?state.previous:state.project;if(!project)return;
  const assembly=project.report?.assembly||{},direction=new THREE.Vector3(...(assembly.direction||[0,1,0]));
  const moving=state.mode==='coupon'?'coupon_b':assembly.moving_part_id||'part_b';
  const object=state.models.get(moving);if(object)object.position.copy(object.userData.originalPosition).addScaledVector(direction,(1-state.progress)*(assembly.travel_mm||15)*.001);
}

async function generate(reset=false){
  if(state.busy)return;
  try{const parameters=reset?{}:getParameters();setBusy(true,reset?'正在恢复初始参数':'正在生成配对连接','创建双方实体，检查尺寸、保护区域与 41 个装配姿态…');$('#error-banner').classList.add('hidden');
    const project=await request(reset?'/api/reset':'/api/design',{method:'POST',body:JSON.stringify(parameters)});
    state.previous=state.project;state.project=project;state.compare=false;state.mode='assembled';$('#compare-toggle').classList.remove('active');
    renderProject(project);await loadModels(project);document.dispatchEvent(new CustomEvent('design-updated',{detail:{revision:project.revision}}));
  }catch(error){showError(error);}finally{setBusy(false);}
}

function downloadUrl(url,name){const anchor=document.createElement('a');anchor.href=url;anchor.download=name;document.body.appendChild(anchor);anchor.click();anchor.remove();}

$$('.candidate').forEach(el=>el.onclick=()=>selectType(el.dataset.type));
for(const selector of Object.values(fields))$(selector).addEventListener('input',()=>{if(selector==='#clearance')$('#clearance-range').value=$('#clearance').value;markDirty();});
$('#clearance-range').oninput=()=>{$('#clearance').value=$('#clearance-range').value;markDirty();};
$('#depth-demo').onclick=()=>{$('#cavity-depth').value=37.04;markDirty();$('#change-state').textContent='内腔深度改为 37.04 mm · 点击生成，检查连接是否跟随开口更新。';};
$('#generate-design').onclick=()=>generate();$('#reset-project').onclick=()=>generate(true);
$('#fit-view').onclick=fitView;
$$('#view-modes button').forEach(el=>el.onclick=()=>setView(el.dataset.view));
$('#show-source').onclick=()=>setView('source');
$('#motion-progress').oninput=(event)=>{state.playing=false;$('#play-motion').textContent='▶';if(state.mode==='source'){setView('assembled');return;}setProgress(Number(event.target.value)/100);};
$('#play-motion').onclick=async()=>{if(state.mode==='source')await setView('assembled');state.playing=!state.playing;$('#play-motion').textContent=state.playing?'Ⅱ':'▶';if(state.playing)state.playStart=performance.now();};
$('#detail-toggle').onclick=()=>{const open=$('#check-details').classList.toggle('hidden');$('#detail-toggle').textContent=open?'查看详情 ↓':'收起详情 ↑';};
$('#compare-toggle').onclick=async()=>{if(!state.previous||state.busy)return;state.compare=!state.compare;state.mode='assembled';$('#compare-toggle').classList.toggle('active',state.compare);$('#compare-toggle').textContent=state.compare?`◫ 正在看修改前 ${revisionName(state.previous.revision)}`:'◫ 修改前后';setBusy(true,'切换几何版本','检查报告与参数栏仍显示最新版本');try{await loadModels(state.compare?state.previous:state.project);}catch(error){showError(error);}finally{setBusy(false);}};
$$('.nav-item').forEach(el=>el.onclick=()=>{$$('.nav-item').forEach(n=>n.classList.toggle('active',el===n));if(el.dataset.tab==='history'){$('#history-card').classList.remove('hidden');$('#history-card').scrollIntoView({behavior:'smooth',block:'center'});}else if(el.dataset.tab==='validation'){$('#check-details').classList.remove('hidden');$('#detail-toggle').textContent='收起详情 ↑';$('#results-card').scrollIntoView({behavior:'smooth',block:'center'});}else{window.scrollTo({top:0,behavior:'smooth'});}});

// This is a real canvas recording of the loaded meshes, not a prerecorded success animation.
const recordButton=document.createElement('button');recordButton.id='record-demo';recordButton.className='record-button';recordButton.innerHTML='<i></i>录制演示';recordButton.title='录制当前版本的 10 秒三维装配演示';$('.viewer-top').insertBefore(recordButton,$('#fit-view'));
const couponButton=document.createElement('button');couponButton.className='coupon-view-button';couponButton.textContent='查看试装件 ↗';couponButton.onclick=()=>setView(state.mode==='coupon'?'assembled':'coupon');$('.deliver-row>div').appendChild(couponButton);

async function recordDemo(){
  if(state.busy||!state.project||state.recording)return;
  if(!window.MediaRecorder||!HTMLCanvasElement.prototype.captureStream){showError(new Error('当前浏览器不支持录屏；请使用 Chromium 浏览器。'));return;}
  await setView('assembled');state.playing=false;$('#play-motion').textContent='▶';
  const canvas=document.createElement('canvas');canvas.width=1440;canvas.height=1000;const context=canvas.getContext('2d');
  const mime=['video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
  if(!mime){showError(new Error('浏览器不支持 WebM 视频编码。'));return;}
  const stream=canvas.captureStream(30);const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:5500000});const chunks=[];
  const beforeCamera=camera.position.clone(), beforeTarget=controls.target.clone();
  state.recording={canvas,context,recorder,start:performance.now(),project:state.project,beforeCamera,beforeTarget};
  recordButton.disabled=true;recordButton.innerHTML='<i></i>正在录制 10 秒';$('#status-message').textContent='正在录制当前真实几何 · 画面包含版本与验证边界';
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  recorder.onstop=async()=>{
    const record=state.recording;state.recording=null;stream.getTracks().forEach(t=>t.stop());camera.position.copy(beforeCamera);controls.target.copy(beforeTarget);setProgress(1);controls.update();
    recordButton.disabled=false;recordButton.innerHTML='<i></i>录制演示';
    const blob=new Blob(chunks,{type:'video/webm'});const filename=`connection-demo-r${String(record.project.revision).padStart(4,'0')}-${Date.now()}.webm`;
    try{
      if(!/^connection-demo-r[0-9]{1,8}(?:-[A-Za-z0-9_-]{1,40})?\.webm$/.test(filename))throw new Error('视频文件名不符合服务端格式，尚未上传。');
      let response;
      try{response=await fetch(`/api/media?filename=${encodeURIComponent(filename)}`,{method:'POST',headers:{'Content-Type':'video/webm'},body:blob});}
      catch(networkError){throw new Error(`上传连接中断，浏览器未收到服务端响应（${networkError.message}）。`);}
      const raw=await response.text();let result;
      try{result=JSON.parse(raw);}catch{throw new Error(`上传服务返回 HTTP ${response.status}，响应不是 JSON。`);}
      if(!response.ok)throw new Error(`上传服务拒绝保存（HTTP ${response.status}）：${result.error||'未知原因'}`);
      $('#status-message').textContent=`视频已保存 · ${filename}`;const link=document.createElement('a');link.href=result.url;link.download=filename;link.textContent='当前版本演示视频 ↓';$('#artifact-list').prepend(link);window.appDebug.lastVideo=result;
    }
    catch(error){const url=URL.createObjectURL(blob);downloadUrl(url,filename);$('#status-message').textContent=`视频已生成并下载；自动保存未完成：${error.message}`;window.appDebug.lastVideo={url,filename,bytes:blob.size,uploadError:error.message};}
  };
  recorder.start(250);
}
recordButton.onclick=()=>recordDemo().catch(showError);

function drawRecording(time){
  const record=state.recording;if(!record)return;
  const elapsed=(time-record.start)/1000,p=record.project.parameters;
  const phase=Math.min(1,Math.max(0,(elapsed-1)/7));setProgress(.5+.5*Math.cos(phase*Math.PI*2));
  const target=record.beforeTarget;const offset=record.beforeCamera.clone().sub(target);offset.applyAxisAngle(new THREE.Vector3(0,1,0),Math.sin(elapsed/10*Math.PI)*.28);camera.position.copy(target).add(offset);camera.lookAt(target);
  const ctx=record.context,w=record.canvas.width,h=record.canvas.height;
  ctx.fillStyle='#e8ede7';ctx.fillRect(0,0,w,h);const source=renderer.domElement,scale=Math.min(w/source.width,(h-170)/source.height),dw=source.width*scale,dh=source.height*scale;
  ctx.drawImage(source,(w-dw)/2,105+(h-170-dh)/2,dw,dh);
  ctx.fillStyle='#244438';ctx.font='600 30px Microsoft YaHei, sans-serif';ctx.fillText('构造 · 产品装配设计',45,48);ctx.fillStyle='#6e8575';ctx.font='18px Microsoft YaHei, sans-serif';ctx.fillText(`${revisionName(record.project.revision)}   ${typeName(p.type)}   间隙 ${p.clearance_mm} mm   内腔深度 ${p.cavity_depth_mm} mm`,45,83);
  ctx.fillStyle='#6d8371';ctx.font='17px Microsoft YaHei, sans-serif';ctx.fillText('真实参数化几何与刚体装配运动 · 未进行材料力学或实物验证',45,h-52);ctx.font='14px Microsoft YaHei, sans-serif';ctx.fillText('规则壳体工程样件；历史兔形原件作为保护参考。',45,h-24);
  ctx.fillStyle='#1d6a60';ctx.fillRect(w-220,h-64,Math.min(1,elapsed/10)*175,3);
  if(elapsed>=10&&record.recorder.state==='recording')record.recorder.stop();
}

function animate(time){requestAnimationFrame(animate);const delta=Math.min(.1,(time-lastTime)/1000);lastTime=time;if(state.playing&&!state.recording){const elapsed=(time-state.playStart)/1000;setProgress(.5+.5*Math.cos(elapsed*Math.PI/2.7));}updateMotion();if(!state.recording)controls.update();renderer.render(scene,camera);updateLabel();drawRecording(time);}
requestAnimationFrame(animate);

async function initialize(){setBusy(true,'正在连接设计服务','读取真实模型、参数与检查结果');try{await request('/api/health');const project=await request('/api/project');state.project=project;renderProject(project);await loadModels(project);}catch(error){$('#api-status').innerHTML='<i></i>服务连接失败';$('#api-status').classList.add('error');showError(error);}finally{setBusy(false);}}
window.appDebug={state,scene,camera,renderer,controls,setView,generate,recordDemo,getInfo:()=>({revision:state.project?.revision,loadedRevision:state.loadedRevision,modelVisible:modelRoot.visible,mode:state.mode,models:[...state.models.keys()],busy:state.busy,report:state.project?.report,loadedSource:state.project?.source})};
initialize();
