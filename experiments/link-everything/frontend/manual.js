import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {TransformControls} from 'three/addons/controls/TransformControls.js';

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {project:null, selected:null, selectedIds:new Set(), type:'plug', flip:false, view:'exploded', busy:false, parts:new Map(),pickParts:new Map(), markers:[],markerPairs:[],loadToken:0,stage:'connect',whole:null,preview:null,separate:new Set(),discard:new Set(),focusPiece:null,quickFirst:null,viewingOriginal:false,connectorFlow:new URLSearchParams(location.search).get('mode')==='parametric'?'parametric':'manual',parametricPlacement:null,parametricContext:null,parametricError:null,aiProposal:null,aiSelectedId:null,aiOverrides:{},aiToken:0,cutHistory:[],cutHistoryIndex:-1,cutHistoryApplying:false,motion:{spec:null,value:0,playing:false,direction:1,lastFrame:null,modelReady:false,basePosition:null,baseQuaternion:null,pickBasePosition:null,pickBaseQuaternion:null}};
const names = {plug:'Plug 凸榫',dowel:'Dowel 定位销',snap:'Snap 卡扣',dovetail:'Dovetail 滑动燕尾',cantilever:'悬臂卡扣',hinge:'转轴铰链',linear_rail:'有限行程导轨'};
const aiOnlyFamilies=new Set(['cantilever','hinge','linear_rail']);
const embedded = new URLSearchParams(location.search).get('embed') === '1';
document.body.classList.toggle('embedded', embedded);

const scene = new THREE.Scene(); scene.background = new THREE.Color('#10151d');
const viewport = $('#viewport');
const camera = new THREE.PerspectiveCamera(38, 1, .0005, 20);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
viewport.appendChild(renderer.domElement);
renderer.domElement.tabIndex=0;
const pendingPoint=document.createElement('div');
pendingPoint.id='pending-connector-point';
pendingPoint.className='pending-connector-point';
pendingPoint.hidden=true;
pendingPoint.setAttribute('role','status');
pendingPoint.setAttribute('aria-live','polite');
pendingPoint.innerHTML='<span class="pending-connector-ring" aria-hidden="true"></span><span class="pending-connector-caption">待确认位置 · 正在计算，尚未生成实体</span>';
viewport.appendChild(pendingPoint);
const pendingCaption=pendingPoint.querySelector('.pending-connector-caption');
const controls = new OrbitControls(camera,renderer.domElement);
controls.enableDamping = true; controls.minDistance=.015; controls.maxDistance=2;
scene.add(new THREE.HemisphereLight('#ffffff','#b4c7ad',2.6));
const light = new THREE.DirectionalLight('#fff9e8',3.1); light.position.set(.06,.12,.08); scene.add(light);
const fill = new THREE.DirectionalLight('#d9f1ec',.9); fill.position.set(-.1,.06,-.08); scene.add(fill);
const grid = new THREE.GridHelper(.3,30,'#34405a','#1d283a'); grid.material.transparent=true; grid.material.opacity=.48; scene.add(grid);
const root = new THREE.Group(); scene.add(root);
const markerRoot = new THREE.Group(); scene.add(markerRoot);
const cutGuide = new THREE.Group(); scene.add(cutGuide);
const quickPointRoot = new THREE.Group(); scene.add(quickPointRoot);
const parametricMarkerRoot = new THREE.Group(); scene.add(parametricMarkerRoot);
const cutAnchor = new THREE.Object3D(); scene.add(cutAnchor);
const cutTransform = new TransformControls(camera,renderer.domElement);
cutTransform.setSpace('world'); cutTransform.setSize(1);
scene.add(cutTransform.getHelper());
cutTransform.addEventListener('dragging-changed',event=>{controls.enabled=!event.value;});
cutTransform.addEventListener('objectChange',()=>{
  if(state.stage!=='cut'||!state.whole)return;
  const origin=engineering(cutAnchor.position);
  ['cut-x','cut-y','cut-z'].forEach((id,i)=>{$('#'+id).value=origin[i].toFixed(2);});
  const direction=new THREE.Vector3(0,1,0).applyQuaternion(cutAnchor.quaternion).normalize();
  setCutNormal([direction.x,-direction.z,direction.y]);
  $('#cut-axis').value='free';
  showCutGuide(false);
});
cutTransform.addEventListener('mouseUp',()=>recordCutState());
const loader = new GLTFLoader();
const pickModelCache=new Map();
let pickCacheSourceId=null;
let displayedPairSourceId=null;
const ray = new THREE.Raycaster(); const pointer = new THREE.Vector2();
let down = null;
new ResizeObserver(() => {const r=viewport.getBoundingClientRect();renderer.setSize(Math.max(1,r.width),Math.max(1,r.height));camera.aspect=r.width/r.height;camera.updateProjectionMatrix();}).observe(viewport);
let manualRecording=null;
let pendingConnector=null;
function clearPendingConnector(){pendingConnector=null;pendingPoint.hidden=true;}
function pendingMatches(project){return !!pendingConnector&&project?.source_id===pendingConnector.sourceId&&project.revision>pendingConnector.revision&&project.connectors?.some(item=>item.id===pendingConnector.connectorId);}
function showPendingConnector(face,connectorId){
  pendingConnector={sourceId:state.project.source_id,revision:state.project.revision,connectorId,partId:face.hitPartId,base:viewer(face.center_mm)};
  pendingCaption.textContent='待确认位置 · 正在计算，尚未生成实体';
  pendingPoint.hidden=false;
  positionPendingConnector();
}
function positionPendingConnector(){
  if(!pendingConnector)return;
  const point=pendingConnector.base.clone();
  if(pendingConnector.partId==='part_b')point.add(explosionOffset());
  point.project(camera);
  const visible=point.z>=-1&&point.z<=1&&Math.abs(point.x)<1.2&&Math.abs(point.y)<1.2;
  pendingPoint.style.visibility=visible?'visible':'hidden';
  pendingPoint.style.left=`${(point.x+1)*viewport.clientWidth/2}px`;
  pendingPoint.style.top=`${(1-point.y)*viewport.clientHeight/2}px`;
}
function animate(now){requestAnimationFrame(animate);advanceMotion(now);controls.update();positionPendingConnector();renderer.render(scene,camera);drawManualRecording();}animate();
function notify(message,error=false){$('#toast').textContent=message;$('#toast').classList.toggle('error',error);}
function drawManualRecording(){
  if(!manualRecording)return;
  const {canvas,context,started}=manualRecording;
  context.fillStyle='#edf2eb';context.fillRect(0,0,canvas.width,canvas.height);
  context.fillStyle='#182c25';context.fillRect(0,0,canvas.width,100);
  context.fillStyle='#fff';context.font='bold 34px Microsoft YaHei, sans-serif';context.fillText(state.connectorFlow==='parametric'?'万物连接件 · AI 连接与运动机构设计':'万物连接件 · 手动分件与配对连接',48,65);
  context.font='24px Microsoft YaHei, sans-serif';context.fillStyle='#a6dfbf';context.fillText('真实工作台操作录屏 · '+Math.round((performance.now()-started)/1000)+'s',1370,65);
  const x=410,y=125,w=1460,h=755;
  context.fillStyle='#10151d';context.fillRect(x,y,w,h);
  try{context.drawImage(renderer.domElement,x,y,w,h);}catch(_){}
  const line=(label,value,row)=>{context.fillStyle='#6b8777';context.font='22px Microsoft YaHei, sans-serif';context.fillText(label,36,row);context.fillStyle='#193b2d';context.font='bold 23px Microsoft YaHei, sans-serif';const text=String(value||'—');context.fillText(text.length>20?text.slice(0,19)+'…':text,36,row+38);};
  line('当前模型',$('#whole-name').textContent,180);
  line('步骤',state.stage==='cut'?'调整切面':state.stage==='preview'?'选择切块':'设计连接件',280);
  line('切面位置 / mm',[$('#cut-x').value,$('#cut-y').value,$('#cut-z').value].join(' / '),380);
  line('切割方式',$('#cut-mode').selectedOptions[0]?.textContent,480);
  line('切块数量',state.preview?.components?.length||'—',580);
  line(state.connectorFlow==='parametric'?'AI 候选结构':'连接件类型',state.connectorFlow==='parametric'?(selectedAICandidate()?.name||names[state.project?.connectors?.at(-1)?.type]||'待推理'):names[state.type],680);
  line('已放置连接件',$('#connector-count').textContent,780);
  context.fillStyle='#fff';context.fillRect(0,905,canvas.width,175);
  context.fillStyle='#1e3d2f';context.font='bold 27px Microsoft YaHei, sans-serif';context.fillText('工作台反馈',48,951);
  context.font='22px Microsoft YaHei, sans-serif';const message=$('#toast').textContent||'';context.fillText(message.slice(0,68),48,997);if(message.length>68)context.fillText(message.slice(68,136),48,1030);
  context.fillStyle='#648477';context.font='20px Microsoft YaHei, sans-serif';context.fillText('原始 GLB 非水密时使用近似切割代理体；录屏不代表制造公差验证',930,951);
}
$('#manual-record').onclick=async()=>{
  if(manualRecording){if(manualRecording.recorder.state==='recording')manualRecording.recorder.stop();return;}
  if(!window.MediaRecorder||!HTMLCanvasElement.prototype.captureStream){notify('当前浏览器不支持视频录制。',true);return;}
  const mime=['video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'].find(value=>MediaRecorder.isTypeSupported(value));
  if(!mime){notify('当前浏览器没有可用的 WebM 编码器。',true);return;}
  const canvas=document.createElement('canvas');canvas.width=1920;canvas.height=1080;
  const recorder=new MediaRecorder(canvas.captureStream(24),{mimeType:mime,videoBitsPerSecond:3000000});
  const chunks=[];manualRecording={canvas,context:canvas.getContext('2d'),recorder,started:performance.now()};
  $('#manual-record').textContent='■ 停止并保存';$('#manual-record-status').textContent='录制中';
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  recorder.onstop=async()=>{const recording=manualRecording;manualRecording=null;recording.recorder.stream.getTracks().forEach(track=>track.stop());$('#manual-record').disabled=true;$('#manual-record-status').textContent='正在保存…';try{const name='connection-demo-r'+(Date.now()%100000000)+'-manual-chest.webm';const response=await fetch('/api/media?filename='+name,{method:'POST',headers:{'Content-Type':'video/webm'},body:new Blob(chunks,{type:'video/webm'})});const data=await response.json();if(!response.ok)throw new Error(data.error||'保存失败');$('#manual-record-status').textContent='已保存 '+name;notify('操作视频已保存：'+name);}catch(error){$('#manual-record-status').textContent='保存失败';notify(error.message,true);}finally{$('#manual-record').disabled=false;$('#manual-record').textContent='● 录制操作';}};
  recorder.start(500);
};
function syncCutTransform(){cutTransform.enabled=!state.busy&&state.stage==='cut'&&state.whole?.cut_ready!==false&&!state.viewingOriginal;}
function busy(value){if(value&&(state.motion.playing||!motionAtHome()))resetMotionPose();state.busy=value;$('#upload-pair').disabled=value||!($('#file-a').files[0]&&$('#file-b').files[0]);$('#save-connector').disabled=value;$('#restore-sample').disabled=value;$('#build-proxy').disabled=value||state.whole?.cut_ready!==false;for(const id of ['whole-sample','preview-cut','commit-cut','flip-cut-plane','reset-cut','edit-cut','edit-whole'])$('#'+id).disabled=value||(id==='preview-cut'&&(state.whole?.cut_ready===false||state.viewingOriginal));for(const id of ['ai-motion','ai-process','ai-material','ai-frequency','ai-removable','ai-notes','ai-clear-anchor'])$('#'+id).disabled=value;$$('[data-piece-action]').forEach(button=>button.disabled=value);renderConnectorFlowState();renderCutHistoryControls();syncCutTransform();renderMotionControls();}
async function request(path,body){let response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);return data;}
function viewer(v){return new THREE.Vector3(v[0]/1000,v[2]/1000,-v[1]/1000);}
function engineering(v){return [v.x*1000,-v.z*1000,v.y*1000].map(x=>Math.round(x*1000)/1000);}
function fit(){const bounds=new THREE.Box3();for(const object of state.parts.values())bounds.expandByObject(object);if(bounds.isEmpty())return;const size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3());const radius=Math.max(size.x,size.y,size.z)*2.25;controls.target.copy(center);camera.position.copy(center.clone().add(new THREE.Vector3(radius*.95,radius*.76,radius*.95)));camera.near=Math.max(.0002,radius/1000);camera.far=Math.max(5,radius*30);camera.updateProjectionMatrix();controls.update();}
function pairExtent(){
  const parts=state.project?.source?.parts;
  if(!parts?.length)return .04;
  const low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
  for(const part of parts){const bounds=part.bounds_mm;if(!bounds)continue;for(let axis=0;axis<3;axis++){low[axis]=Math.min(low[axis],bounds[0][axis]);high[axis]=Math.max(high[axis],bounds[1][axis]);}}
  return Math.max(.04,...low.map((value,axis)=>(high[axis]-value)/1000).filter(Number.isFinite));
}
function explosionDirection(){
  const normal=state.project?.source?.cut?.part_a_cut_normal;
  let direction=Array.isArray(normal)&&normal.length===3?viewer(normal):new THREE.Vector3();
  if(direction.lengthSq()<1e-10){
    const parts=state.project?.source?.parts;
    if(parts?.length===2){const center=part=>part.bounds_mm[0].map((value,i)=>(value+part.bounds_mm[1][i])/2);direction=viewer(center(parts[1]).map((value,i)=>value-center(parts[0])[i]));}
  }
  if(direction.lengthSq()<1e-10)direction.set(0,1,0);
  direction.normalize();
  if(Math.abs(direction.y)<.85)direction.add(new THREE.Vector3(0,.35,0)).normalize();
  return direction;
}
function explosionOffset(){return state.view==='exploded'&&state.stage==='connect'?explosionDirection().multiplyScalar(pairExtent()*.85*Number($('#explode-range').value)/100):new THREE.Vector3();}
function validMotionVector(value){return Array.isArray(value)&&value.length===3&&value.every(n=>typeof n==='number'&&Number.isFinite(n));}
function motionContract(raw,project){
  if(!raw||raw.schema!=='connector-motion-preview/v1'||raw.status!=='ready'||raw.moving_part!=='part_b'||raw.fixed_part!=='part_a')return null;
  if(raw.source_revision!==undefined&&raw.source_revision!==project?.revision)return null;
  if(raw.coordinate_space&&raw.coordinate_space!=='engineering_mm_z_up')return null;
  if(!['rotation','translation','assembly_translation','inspection_explode'].includes(raw.kind)||!validMotionVector(raw.axis))return null;
  if(!Array.isArray(raw.range)||raw.range.length!==2||!raw.range.every(n=>typeof n==='number'&&Number.isFinite(n))||raw.range[0]>=raw.range[1])return null;
  const home=raw.home_value;
  if(typeof home!=='number'||!Number.isFinite(home)||home<raw.range[0]||home>raw.range[1])return null;
  if(raw.kind==='rotation'&&(!validMotionVector(raw.pivot_mm)||raw.unit!=='deg'))return null;
  if(raw.kind!=='rotation'&&raw.unit!=='mm')return null;
  if(raw.kind==='inspection_explode'&&raw.visualization_only!==true)return null;
  if(raw.kind==='assembly_translation'&&(typeof raw.assembly_start_value!=='number'||!Number.isFinite(raw.assembly_start_value)||raw.assembly_start_value<raw.range[0]||raw.assembly_start_value>raw.range[1]||Math.abs(raw.assembly_start_value-home)<1e-6))return null;
  if(new THREE.Vector3(...raw.axis).lengthSq()<1e-10)return null;
  return raw;
}
function motionAtHome(){const motion=state.motion;return !motion.spec||Math.abs(motion.value-motion.spec.home_value)<1e-6;}
function motionReadout(){const {spec,value}=state.motion;return !spec?'—':`${value>1e-6?'+':''}${value.toFixed(1)} ${spec.unit==='deg'?'°':'mm'}`;}
function renderMotionControls(){
  const motion=state.motion,spec=motion.spec,raw=state.project?.report?.motion_preview;
  $('#motion-preview').hidden=!spec||state.stage!=='connect';
  $('#motion-unavailable').hidden=!!spec||!raw||state.stage!=='connect'||!state.project?.connectors?.length;
  if(!$('#motion-unavailable').hidden)$('#motion-unavailable').textContent=raw.status==='ready'
    ?'运动预览数据与当前生成修订不匹配，请重新加载模型。'
    :`当前结构没有可播放的运动或展示契约：${raw.note||'请重新生成连接件。'}`;
  if(!spec)return;
  $('#motion-title').textContent={rotation:'转轴开合预览',translation:'导轨行程预览',assembly_translation:'滑入装配预览',inspection_explode:'结构展示动画 · 非装配路径'}[spec.kind];
  $('#motion-value').textContent=motionReadout();
  $('#motion-range').value=Math.round((motion.value-spec.range[0])/(spec.range[1]-spec.range[0])*1000);
  $('#motion-range').disabled=!motion.modelReady||state.busy;
  $('#motion-play').disabled=!motion.modelReady||state.busy;
  $('#motion-reset').disabled=!motion.modelReady||state.busy;
  $('#motion-play').textContent=motion.playing?'Ⅱ 暂停':'▶ 播放';
  $('#motion-play').setAttribute('aria-label',motion.playing?'暂停运动预览':'播放运动预览');
  const sampled=spec.kind!=='inspection_explode'&&spec.validation?.continuous_proof===false?'采样位置通过；中间帧仅视觉插值，未证明连续无碰撞。':'';
  $('#motion-note').textContent=[spec.note,sampled].filter(Boolean).join(' ')||'以当前生成的 A/B 实体和已验证行程预览；仅移动 B 件。';
}
function resetMotionPose(){
  const motion=state.motion;motion.playing=false;motion.lastFrame=null;motion.direction=1;
  if(motion.spec)motion.value=motion.spec.home_value;
  if(state.stage==='connect')applyExplosion();
  markerRoot.visible=true;renderMotionControls();
}
function clearMotionPreview(){
  resetMotionPose();
  Object.assign(state.motion,{spec:null,value:0,playing:false,direction:1,lastFrame:null,modelReady:false,basePosition:null,baseQuaternion:null,pickBasePosition:null,pickBaseQuaternion:null});
  $('#motion-preview').hidden=true;$('#motion-unavailable').hidden=true;
}
function applyMotionPose(){
  const motion=state.motion,spec=motion.spec,partB=state.parts.get('part_b');
  if(!spec||!motion.modelReady||!partB||!motion.basePosition||!motion.baseQuaternion)return;
  if(motionAtHome()){applyExplosion();return;}
  const pickB=state.pickParts.get('part_b');
  const shift=spec.kind==='rotation'?new THREE.Vector3():viewer(spec.axis).normalize().multiplyScalar((motion.value-spec.home_value)/1000);
  if(spec.kind==='rotation'){
    const pivot=viewer(spec.pivot_mm),q=new THREE.Quaternion().setFromAxisAngle(viewer(spec.axis).normalize(),THREE.MathUtils.degToRad(motion.value-spec.home_value));
    partB.quaternion.copy(q).multiply(motion.baseQuaternion);
    partB.position.copy(motion.basePosition).sub(pivot).applyQuaternion(q).add(pivot);
    if(pickB&&motion.pickBasePosition&&motion.pickBaseQuaternion){pickB.quaternion.copy(q).multiply(motion.pickBaseQuaternion);pickB.position.copy(motion.pickBasePosition).sub(pivot).applyQuaternion(q).add(pivot);pickB.updateMatrixWorld(true);}
  }else{
    partB.quaternion.copy(motion.baseQuaternion);
    partB.position.copy(motion.basePosition).add(shift);
    if(pickB&&motion.pickBasePosition&&motion.pickBaseQuaternion){pickB.quaternion.copy(motion.pickBaseQuaternion);pickB.position.copy(motion.pickBasePosition).add(shift);pickB.updateMatrixWorld(true);}
  }
  // The cut-face markers describe the home pose. Hide them while B moves, so they cannot imply a false contact or catch clicks.
  markerRoot.visible=false;
}
function setMotionValue(value,{enter=true}={}){
  const motion=state.motion,spec=motion.spec;if(!spec||!motion.modelReady)return;
  if(enter&&state.view!=='assembled')view('assembled',{refit:false,preserveMotion:true});
  motion.value=THREE.MathUtils.clamp(value,spec.range[0],spec.range[1]);
  applyMotionPose();renderMotionControls();
}
function advanceMotion(now){
  const motion=state.motion,spec=motion.spec;if(!motion.playing||!motion.modelReady||!spec)return;
  if(motion.lastFrame===null){motion.lastFrame=now;return;}
  const elapsed=Math.min(0.1,Math.max(0,(now-motion.lastFrame)/1000));motion.lastFrame=now;
  const low=spec.range[0],high=spec.range[1],speed=(high-low)/(spec.kind==='rotation'?3.2:3.0);
  let next=motion.value+motion.direction*speed*elapsed;
  if(spec.kind==='assembly_translation'){
    if((motion.direction>0&&next>=spec.home_value)||(motion.direction<0&&next<=spec.home_value)){next=spec.home_value;motion.playing=false;motion.lastFrame=null;}
    setMotionValue(next,{enter:false});return;
  }
  if(next>high){next=high-(next-high);motion.direction=-1;}
  else if(next<low){next=low+(low-next);motion.direction=1;}
  setMotionValue(next,{enter:false});
}
$('#motion-play').onclick=()=>{
  const motion=state.motion;if(!motion.spec||!motion.modelReady)return;
  if(motion.playing){motion.playing=false;motion.lastFrame=null;renderMotionControls();return;}
  if(state.view!=='assembled')view('assembled',{refit:false,preserveMotion:true});
  if(motion.spec.kind==='assembly_translation'){
    const start=motion.spec.assembly_start_value;
    if(typeof start!=='number'||!Number.isFinite(start)){notify('缺少已验证的装配起点，无法播放。',true);return;}
    setMotionValue(start,{enter:false});motion.direction=Math.sign(motion.spec.home_value-start);
    motion.playing=true;motion.lastFrame=null;renderMotionControls();return;
  }
  if(motion.value>=motion.spec.range[1]-1e-6)motion.direction=-1;
  else if(motion.value<=motion.spec.range[0]+1e-6)motion.direction=1;
  motion.playing=true;motion.lastFrame=null;renderMotionControls();
};
$('#motion-range').addEventListener('input',event=>{
  const motion=state.motion;if(!motion.spec||!motion.modelReady)return;
  motion.playing=false;motion.lastFrame=null;
  const fraction=Number(event.target.value)/1000;
  setMotionValue(motion.spec.range[0]+fraction*(motion.spec.range[1]-motion.spec.range[0]));
});
$('#motion-reset').onclick=()=>{if(state.view!=='assembled')view('assembled',{refit:false,preserveMotion:true});resetMotionPose();};
function applyExplosion({refit=false}={}){
  const offset=explosionOffset();
  const partB=state.parts.get('part_b');if(partB){partB.position.copy(state.motion.basePosition||new THREE.Vector3()).add(offset);partB.quaternion.copy(state.motion.baseQuaternion||new THREE.Quaternion());}
  const pickB=state.pickParts.get('part_b');if(pickB){pickB.position.copy(state.motion.pickBasePosition||new THREE.Vector3()).add(offset);pickB.quaternion.copy(state.motion.pickBaseQuaternion||new THREE.Quaternion());pickB.updateMatrixWorld(true);}
  for(const [id,part] of state.parts)if(id.startsWith('pin_'))part.position.copy(offset).multiplyScalar(.5);
  for(const pair of state.markerPairs){pair.b.position.copy(pair.base).addScaledVector(pair.direction,-.001).add(offset);pair.line.geometry.dispose();pair.line.geometry=new THREE.BufferGeometry().setFromPoints([pair.a.position,pair.b.position]);pair.line.computeLineDistances();}
  $('#explode-value').textContent=$('#explode-range').value+'%';
  $('#explode-range').disabled=state.stage!=='connect'||state.view!=='exploded'||!partB;
  markerRoot.visible=true;
  if(refit)fit();
}
function view(mode,{refit=true,preserveMotion=false}={}){if(!preserveMotion)resetMotionPose();state.view=mode;$$('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===mode));applyExplosion({refit});if(state.stage==='connect')$('#pointer-note').textContent=mode==='exploded'?(state.connectorFlow==='parametric'?'右侧先生成 AI 结构候选；点击切面可指定位置偏好':'点击任一切面放置连接件；拖动标记可改位置'):'点击“分开展示”后选择切面';}
$('#explode-range').addEventListener('input',()=>{resetMotionPose();applyExplosion();});
async function loadCutModels(parts){
  displayedPairSourceId=null;
  const token=++state.loadToken;root.clear();markerRoot.clear();state.parts.clear();state.pickParts.clear();state.markers=[];state.markerPairs=[];
  const loaded=await Promise.all(parts.map(async part=>({id:part.id,source:part.source,object:(await loader.loadAsync(part.url+'?t='+Date.now())).scene})));
  if(token!==state.loadToken)return;
  for(const {id,source,object} of loaded){
    object.name=id;
    if(source?.cut_ready===false){
      object.scale.setScalar(source.input_units==='mm'?.001:1);
      if(source.input_up_axis==='Z')object.rotation.x=-Math.PI/2;
    }
    object.traverse(child=>{if(child.isMesh){
      const materials=Array.isArray(child.material)?child.material:[child.material];
      const copies=materials.map(material=>{const copy=material.clone();copy.side=THREE.DoubleSide;return copy;});
      child.material=Array.isArray(child.material)?copies:copies[0];child.castShadow=true;
    }});
    root.add(object);state.parts.set(id,object);
  }
  if(state.stage!=='visual'&&!parts.some(part=>part.originalVisual))highlightPieces();fit();
}
function highlightPieces(){for(const [id,object] of state.parts){object.traverse(child=>{if(child.isMesh){for(const material of (Array.isArray(child.material)?child.material:[child.material])){material.emissive=new THREE.Color(state.separate.has(id)?'#7d5412':state.discard.has(id)?'#4d4d4d':state.focusPiece===id?'#315b9c':'#000000');material.emissiveIntensity=state.separate.has(id)?.35:state.discard.has(id)?.25:state.focusPiece===id?.3:0;material.opacity=state.discard.has(id)?.25:1;material.transparent=state.discard.has(id);}}});}}
function showWhole(source){
  clearMotionPreview();
  const visual=source.cut_ready===false;
  const proxy=source.approximate===true||source.proxy?.approximate===true;
  state.whole=source;state.preview=null;state.stage=visual?'visual':'cut';state.viewingOriginal=false;state.focusPiece=null;document.body.classList.add('cutting');$('#explode-range').disabled=true;
  state.separate.clear();clearQuickPoint();clearParametricPlacement();
  const notes=Array.isArray(source.repair_notes)?source.repair_notes:[];
  const repaired=notes.length>0;
  const capped=notes.some(note=>/filled|capped/.test(note));
  $('#whole-name').textContent=source.label;
  $('#whole-info').textContent=visual?`原始 GLB 已载入 · 非水密，暂不能直接切割${source.face_count?' · '+source.face_count+' 面':''}`:proxy?`近似切割代理体 · ${Math.round(source.volume_mm3)} mm³ · 请与原件对照`:`闭合整件 · ${Math.round(source.volume_mm3)} mm³${capped?' · 已自动补面，请检查开口位置':repaired?' · 已自动校正网格':''}`;
  $('#visual-actions').hidden=!visual;
  $('#build-proxy').disabled=!visual;
  $('#proxy-note').hidden=!proxy;
  if(proxy)$('#proxy-note').textContent=`实验性水密代理体：体素间距 ${Number(source.proxy?.pitch_mm||0).toFixed(1)} mm，切割和连接件会作用于代理体。原始 GLB 未修改；薄壁、空隙和细节可能变化，仅供交互试验，不作制造或配合公差依据。`;
  $('#compare-original').hidden=!proxy;$('#compare-proxy').hidden=!proxy;
  $('#compare-original').classList.remove('active');$('#compare-proxy').classList.toggle('active',proxy);
  $('#edit-whole').hidden=true;$('#pair-card-label').textContent='上次保存的配对零件';$('#cut-selection').hidden=true;$('#piece-actions').hidden=true;
  $('#scene-title').textContent=visual?'原始 GLB · 保真预览':proxy?'近似水密代理体 · 可切割':'整件模型 · 拖手柄或输入数值调整切面';$('#revision').textContent=visual?'SURFACE':proxy?'PROXY':'CUT';
  $('#pointer-note').textContent=visual?'原始表面已保留；切割与连接件需要先生成水密代理体':proxy?'当前显示代理体；可切换原始 GLB 对照':'拖动彩色手柄调整切面；Shift + 连点模型两处可快速定义切面';
  $('#check-summary').textContent=visual?'原始表面已载入 · 待生成切割代理体':proxy?'近似代理体闭合 · 待检查形状':`整件闭合${repaired?'（自动修复）':''} · 待切割`;
  $('#checks').innerHTML=visual?'<span>✓ 原件保真导入</span><span class="pending">○ 待生成水密实体</span>':proxy?'<span>✓ 代理体水密</span><span class="pending">○ 与原件形状待核对</span>':`<span>✓ ${repaired?'修复后闭合':'原件闭合'}</span><span class="pending">○ 待切割</span>`;
  $('#cut-gizmo-toolbar').hidden=visual;cutGuide.visible=!visual;
  if(visual)cutTransform.detach();else cutTransform.attach(cutAnchor);
  syncCutTransform();
  if(!visual&&!state.cutHistory.length)resetCutHistory();
  renderCutHistoryControls();
  $('#preview-cut').disabled=visual;
  loadCutModels([{id:'whole',url:source.url,source}]).catch(e=>notify('整件显示失败：'+e.message,true));
  if(!visual)showCutGuide();
  renderConnectorFlowState();
}
$('#compare-original').onclick=()=>{
  const source=state.whole;
  if(!source?.proxy?.approximate||!source.original_url)return;
  state.viewingOriginal=true;state.stage='compare';cutTransform.detach();cutGuide.visible=false;syncCutTransform();
  $('#cut-gizmo-toolbar').hidden=true;$('#cut-selection').hidden=true;$('#piece-actions').hidden=true;$('#preview-cut').disabled=true;
  $('#compare-original').classList.add('active');$('#compare-proxy').classList.remove('active');
  $('#scene-title').textContent='原始 GLB · 保真对照';$('#revision').textContent='ORIGINAL';$('#pointer-note').textContent='当前显示原件；切割实际使用近似代理体，切回代理体后再切割';
  $('#check-summary').textContent='原件非水密 · 仅供对照';
  $('#checks').innerHTML='<span>✓ 原始 GLB 未改动</span><span class="pending">○ 实体切割使用代理体</span>';
  loadCutModels([{id:'whole',url:source.original_url,source:{cut_ready:false,input_units:source.input_units,input_up_axis:source.input_up_axis},originalVisual:true}]).catch(e=>notify('原件显示失败：'+e.message,true));
};
$('#compare-proxy').onclick=()=>{if(state.whole?.proxy?.approximate){showWhole(state.whole);notify('已切回近似切割代理体；请核对外形后再切割。');}};
async function generateProxy(){
  if(!state.whole||state.whole.cut_ready!==false)return;
  const sourceId=state.whole.id;
  busy(true);notify('原始 GLB 已载入；正在生成近似水密代理体，复杂模型可能需要几十秒…');
  try{
    const result=await request('/api/manual/cut/solidify',{source_id:sourceId});
    if(state.whole?.id!==sourceId)return;
    showWhole(result.source);centerCutOnSource(result.source,true);
    notify(`已生成可切割的近似代理体（体素间距 ${Number(result.source.proxy?.pitch_mm||0).toFixed(1)} mm）。请用“原始 GLB / 切割代理体”对照，确认细节后再切割。`);
  }catch(error){notify(`原始 GLB 仍可查看；代理体生成失败：${error.message}`,true);}
  finally{busy(false);}
}
$('#build-proxy').onclick=generateProxy;
function pieceDisposition(id){return state.discard.has(id)?'discard':state.separate.has(id)?'separate':'body';}
function renderFocusedPiece(){const piece=state.preview?.components.find(item=>item.id===state.focusPiece);$('#piece-actions').hidden=!piece||state.stage!=='preview';if(!piece)return;const index=state.preview.components.indexOf(piece)+1;$('#focused-piece-name').textContent=`${piece.side==='upper'?'上侧':'下侧'}切块 ${index} · ${piece.volume_mm3.toFixed(0)} mm³`;$('#focused-piece-status').textContent=`当前：${{body:'并回主体',separate:'独立件',discard:'丢弃'}[pieceDisposition(piece.id)]}；点击下方切换`;$$('[data-piece-action]').forEach(button=>button.classList.toggle('active',button.dataset.pieceAction===pieceDisposition(piece.id)));}
function selectPreviewPiece(id){if(state.stage!=='preview'||!state.preview?.components.some(item=>item.id===id))return;state.focusPiece=id;renderFocusedPiece();$$('.piece-row').forEach(row=>row.classList.toggle('focused',row.dataset.piece===id));highlightPieces();notify('已选中切块。点击视口里的“并回主体 / 独立件 / 丢弃”决定它的去向。');}
function renderPieces(){const components=state.preview?.components||[];const largest=Math.max(1,...components.map(p=>p.volume_mm3));$('#piece-list').innerHTML=components.map((p,i)=>{const status=pieceDisposition(p.id);const tiny=p.volume_mm3<largest*.001?' · 极小切块，请检查是否丢弃':'';return `<div class="piece-row ${status==='separate'?'selected':status==='discard'?'discarded':''} ${state.focusPiece===p.id?'focused':''}" data-piece="${esc(p.id)}"><span><b>${p.side==='upper'?'上侧':'下侧'}切块 ${i+1}</b><small>${p.volume_mm3.toFixed(0)} mm³ · ${p.closed?'断面已封口':'未封口'}${tiny}</small></span><select aria-label="切块 ${i+1} 处理方式"><option value="body" ${status==='body'?'selected':''}>并回主体</option><option value="separate" ${status==='separate'?'selected':''}>独立件</option><option value="discard" ${status==='discard'?'selected':''}>丢弃</option></select></div>`;}).join('');$$('.piece-row').forEach(row=>{row.querySelector('select').onchange=event=>setPieceDisposition(row.dataset.piece,event.target.value);row.onclick=event=>{if(!event.target.closest('select'))selectPreviewPiece(row.dataset.piece);};});renderFocusedPiece();highlightPieces();}
function setPieceDisposition(id,status){if(!state.preview?.components.some(item=>item.id===id)||!['body','separate','discard'].includes(status))return;state.focusPiece=id;state.separate.delete(id);state.discard.delete(id);if(status==='separate')state.separate.add(id);else if(status==='discard')state.discard.add(id);renderPieces();notify(`${{body:'已并回主体',separate:'已设为独立件',discard:'已设为丢弃'}[status]}。独立 ${state.separate.size} 块，丢弃 ${state.discard.size} 块，其余 ${state.preview.components.length-state.separate.size-state.discard.size} 块并回主体。`);}
$$('[data-piece-action]').forEach(button=>button.onclick=()=>{if(state.focusPiece)setPieceDisposition(state.focusPiece,button.dataset.pieceAction);});
function showPreview(preview){clearMotionPreview();state.preview=preview;state.stage='preview';$('#explode-range').disabled=true;state.focusPiece=null;clearQuickPoint();cutGuide.visible=false;cutTransform.detach();syncCutTransform();renderCutHistoryControls();$('#cut-gizmo-toolbar').hidden=true;$('#piece-actions').hidden=true;const upper=preview.components.filter(p=>p.side==='upper').sort((a,b)=>b.volume_mm3-a.volume_mm3);state.separate=new Set([upper[0]?.id||preview.components.slice().sort((a,b)=>b.volume_mm3-a.volume_mm3)[0].id]);state.discard.clear();$('#cut-selection').hidden=false;$('#scene-title').textContent=`切出 ${preview.components.length} 块 · 请选择独立零件`;$('#revision').textContent=preview.params.mode.toUpperCase();$('#pointer-note').textContent='点选切块，然后在视口选择“并回主体 / 独立件 / 丢弃”';$('#check-summary').textContent=`${preview.components.length} 块均自动封口`;$('#checks').innerHTML='<span>✓ 切出块闭合</span><span class="pending">○ 待确认分离块</span>';loadCutModels(preview.components).catch(e=>notify('切割预览显示失败：'+e.message,true));renderPieces();}
async function loadModels(project){const token=++state.loadToken,preserveCamera=displayedPairSourceId===project.source_id;root.clear();markerRoot.clear();state.parts.clear();state.pickParts.clear();state.markers=[];state.markerPairs=[];const loaded=await Promise.all(project.parts.map(async part=>({id:part.id,object:(await loader.loadAsync(part.url+'?v='+project.revision)).scene})));if(token!==state.loadToken)return;for(const {id,object} of loaded){object.name=id;object.traverse(child=>{if(child.isMesh){child.castShadow=true;child.material=child.material.clone();child.material.side=THREE.DoubleSide;}});root.add(object);state.parts.set(id,object);}const partB=state.parts.get('part_b');state.motion.basePosition=partB?.position.clone()||null;state.motion.baseQuaternion=partB?.quaternion.clone()||null;state.motion.modelReady=!!state.motion.spec&&!!partB;for(const item of project.connectors){const base=viewer(item.center_mm),direction=viewer(item.normal).normalize();const color=state.selectedIds.has(item.id)?'#f16834':'#477f54';const sphere=new THREE.SphereGeometry(.00115,16,12);const a=new THREE.Mesh(sphere,new THREE.MeshStandardMaterial({color,emissive:color,emissiveIntensity:.35,depthTest:false}));const b=new THREE.Mesh(sphere,new THREE.MeshStandardMaterial({color:'#e8822d',emissive:'#b35d20',emissiveIntensity:.35,depthTest:false}));a.position.copy(base).addScaledVector(direction,.001);const line=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineDashedMaterial({color:'#4d855d',dashSize:.0015,gapSize:.001,depthTest:false}));markerRoot.add(a,b,line);state.markers.push({id:item.id,object:a});state.markerPairs.push({id:item.id,a,b,line,base,direction});}displayedPairSourceId=project.source_id;view(state.view,{refit:!preserveCamera});for(const pair of state.markerPairs)pair.line.computeLineDistances();renderMotionControls();if(pendingMatches(project))clearPendingConnector();loadPickModels(project,token).catch(()=>{});}
async function loadPickModels(project,token){
  if(pickCacheSourceId!==project.source_id){pickModelCache.clear();pickCacheSourceId=project.source_id;}
  const sources=(project.source?.parts||[]).filter(part=>part.id==='part_a'||part.id==='part_b');
  const loaded=await Promise.all(sources.map(async part=>{
    const key=`${project.source_id}|${part.id}|${part.url}|${part.sha256||''}`;
    if(!pickModelCache.has(key)){
      const promise=loader.loadAsync(part.url+'?source='+project.source_id).then(gltf=>gltf.scene).catch(error=>{pickModelCache.delete(key);throw error;});
      pickModelCache.set(key,promise);
    }
    return {id:part.id,object:await pickModelCache.get(key)};
  }));
  if(token!==state.loadToken)return;
  for(const {id,object} of loaded){object.name='pick_'+id;if(id==='part_b'){if(!object.userData.pickBase) object.userData.pickBase={position:object.position.clone(),quaternion:object.quaternion.clone()};state.motion.pickBasePosition=object.userData.pickBase.position.clone();state.motion.pickBaseQuaternion=object.userData.pickBase.quaternion.clone();object.position.copy(state.motion.pickBasePosition).add(explosionOffset());object.quaternion.copy(state.motion.pickBaseQuaternion);}object.updateMatrixWorld(true);state.pickParts.set(id,object);}
  if(!motionAtHome())applyMotionPose();
}
function connectorSummary(item){
  const mm=value=>Number.isFinite(Number(value))?`${Number(value).toFixed(1)} mm`:'待校验';
  const center=Array.isArray(item.center_mm)?item.center_mm.map(value=>Number(value).toFixed(1)).join(', ')+' mm':'位置待校验';
  if(item.type==='hinge')return `${center} · 销轴半径 ${mm(item.pin_radius_mm)} · 铰链长 ${mm(item.segment_length_mm)}`;
  if(item.type==='linear_rail')return `${center} · 滑块长 ${mm(item.rail_length_mm)} · 行程 ${mm(item.travel_mm)}`;
  if(item.type==='cantilever')return `${center} · 宽 ${mm(item.size_mm)} · 臂厚 ${mm(item.beam_thickness_mm)}`;
  if(item.type==='dovetail')return `${center} · 宽 ${mm(item.size_mm)} · 滑入 ${mm(item.slide_length_mm)}`;
  return `${center} · 宽 ${mm(item.size_mm)}`;
}
function renderList(){
  const items=state.project?.connectors||[];
  $('#connector-count').textContent=items.length;
  $('#connector-list').innerHTML=items.length?items.map((item,index)=>`<button class="connector-item ${state.selectedIds.has(item.id)?'active':''}" data-id="${esc(item.id)}"><span class="badge">${index+1}</span><span><b>${esc(names[item.type]||item.type)}${['dovetail',...aiOnlyFamilies].includes(item.type)||!item.shape?'':' · '+esc(item.shape)}</b><small>${esc(connectorSummary(item))}</small></span></button>`).join(''):`<p class="empty">${state.connectorFlow==='parametric'?'先在右侧描述需求，让 AI 设计连接结构。':'点击模型的切面添加第一个连接件。'}</p>`;
  $$('.connector-item').forEach(button=>button.onclick=event=>select(button.dataset.id,event));
  $('#delete-selected').disabled=!state.selectedIds.size;
}
function renderMechanismSummary(mechanisms){
  const target=$('#mechanism-summary');
  target.hidden=!Array.isArray(mechanisms)||mechanisms.length===0;
  if(target.hidden){target.innerHTML='';return;}
  const safeNumber=value=>Number.isFinite(Number(value))?Number(value).toFixed(2):'—';
  target.innerHTML=mechanisms.map(item=>{
    if(item.type==='three_knuckle_hinge'){
      const rotation=item.rotation||{},removal=item.pin_removal||{};
      return `<div><strong>转轴铰链 · ${rotation.opens_to_90_deg?'90° 采样开合通过':'90° 采样未通过'}</strong><small>销轴${removal.removable?'可抽出':'不可确认可抽出'}；旋转轴 ${esc((item.axis||[]).map(safeNumber).join(', '))}。${rotation.continuous_proof?'连续路径已证明':'连续路径和承载寿命尚未证明'}，明细见 report.json。</small></div>`;
    }
    if(item.type==='captured_t_rail'){
      const stroke=Number(item.stroke_sweep_overlap_mm3),travel=safeNumber(item.nominal_travel_mm);
      const strokeStatus=Number.isFinite(stroke)?stroke<=1e-5?'未见实体干涉':'存在实体干涉 '+safeNumber(stroke)+' mm³':'结果缺失';
      return `<div><strong>T 槽导轨 · 标称行程 ${travel} mm</strong><small>行程采样${strokeStatus}；止挡销${item.stop_removable?'可拆卸':'拆卸性未确认'}。连续运动证明与实际耐久仍需验证，明细见 report.json。</small></div>`;
    }
    return `<div><strong>${esc(item.type||'运动机构')} · 已生成</strong><small>检查明细见 report.json；装配与实体试验仍需继续。</small></div>`;
  }).join('');
}
function renderProject(project){
  const previousSourceId=state.project?.source_id;
  if(pendingConnector&&(!pendingMatches(project))&&(project.source_id!==pendingConnector.sourceId||project.revision>pendingConnector.revision))clearPendingConnector();
  clearMotionPreview();
  state.project=project;state.stage='connect';state.viewingOriginal=false;state.focusPiece=null;
  state.motion.spec=project.connectors?.length?motionContract(project.report?.motion_preview,project):null;
  state.motion.value=state.motion.spec?.home_value??0;
  if(previousSourceId!==project.source_id)writeFields(null);
  clearParametricPlacement();state.parametricContext=null;state.parametricError=null;invalidateAIProposal();
  const valid=new Set(project.connectors.map(x=>x.id));
  state.selectedIds=new Set([...state.selectedIds].filter(id=>valid.has(id)));
  if(!valid.has(state.selected))state.selected=null;
  document.body.classList.remove('cutting');cutGuide.visible=false;cutTransform.detach();syncCutTransform();renderCutHistoryControls();
  $('#visual-actions').hidden=true;$('#proxy-note').hidden=true;
  $('#compare-original').hidden=true;$('#compare-proxy').hidden=true;
  $('#cut-gizmo-toolbar').hidden=true;$('#cut-selection').hidden=true;$('#piece-actions').hidden=true;$('#edit-whole').hidden=!state.whole;
  const curved=project.source?.cut?.params?.mode&&project.source.cut.params.mode!=='plane';
  $('[data-type="dovetail"]').disabled=!!curved;
  $('[data-type="dovetail"]').title=curved?'滑动燕尾仅支持平面配对切面':'';
  if(curved&&state.type==='dovetail')setType('plug');
  $('#pair-card-label').textContent='当前模型';$('#source-name').textContent=project.source.label;
  $('#source-note').textContent=project.source.note;
  $('#revision').textContent='R'+String(project.revision).padStart(4,'0');
  $('#scene-title').textContent=project.connectors.length?`已生成 ${project.connectors.length} 个连接件`:'点击切面布置连接件';
  const shellCounts=project.report.parts.map(part=>Number(part.components)||1);
  const groupedShells=shellCounts.some(count=>count>1)?` · A/B 壳体 ${shellCounts.join('/')}（未熔接）`:'';
  $('#check-summary').textContent=`${project.report.parts.length} 组闭合${groupedShells} · 静态干涉 ${Math.max(0,project.report.static_overlap_mm3).toFixed(5)} mm³`;
  $('#checks').innerHTML=project.report.checks.map(c=>`<span class="${c.status==='pending'?'pending':''}">${c.status==='pass'?'✓':'○'} ${esc(c.label)}</span>`).join('');
  $('#replacement-summary').hidden=true;
  renderMechanismSummary(project.report.mechanisms);
  const artifacts=project.artifacts;
  const exportIds=['assembly.glb','part_a.stl','part_b.stl','part_a_print.stl','part_b_print.stl',...project.parts.filter(p=>p.id.startsWith('pin_')).map(p=>p.id+'.stl'),'parameters.json','report.json'];
  $('#exports').innerHTML=exportIds.map(id=>{const a=artifacts.find(x=>x.id===id);return a?`<a href="${a.url}" download>${esc(id)} ↓</a>`:'';}).join('');
  $('#export-note').textContent=project.report.print_exports?'assembly.glb 与 part_a/b.stl 保留装配坐标；part_a/b_print.stl 已按所选方向放到打印床 Z=0。':'assembly.glb 与 part_a/b.stl 保留装配坐标。';
  renderList();renderConnectorFlowState();renderMotionControls();if(state.connectorFlow==='parametric')refreshParametricContext();loadModels(project).catch(error=>{if(pendingMatches(project))clearPendingConnector();notify('模型显示失败：'+error.message,true);});
}
function setType(type){state.type=type;$$('[data-type]').forEach(el=>el.classList.toggle('active',el.dataset.type===type));$$('.snap-only').forEach(el=>el.style.display=type==='snap'?'flex':'none');$$('.dovetail-only').forEach(el=>el.style.display=type==='dovetail'?(el.classList.contains('dovetail-note')?'block':'flex'):'none');$('#style').disabled=type==='dovetail';$('#shape').disabled=type==='dovetail';const selected=state.project?.connectors.find(x=>x.id===state.selected);if(type==='dovetail'&&selected?.type!=='dovetail'){const raw=$('#size').value.trim(),size=raw?Number(raw):null;$('#slide-length').min=size||2;$('#slide-length').value=size?Math.min(120,size*1.6).toFixed(1):'';}}
function readFields(){const sizeTolerance=Number($('#size-tolerance').value);const fields={type:state.type,style:state.type==='dovetail'?'prism':$('#style').value,shape:state.type==='dovetail'?'circle':$('#shape').value,rotation_deg:Number($('#rotation').value),size_tolerance_mm:sizeTolerance,depth_tolerance_mm:Number($('#depth-tolerance').value),clearance_mm:sizeTolerance,bulge_pct:Number($('#bulge').value),space_pct:Number($('#space').value),flip:state.flip};for(const [id,key] of [['depth','depth_mm'],['size','size_mm']])if($('#'+id).value.trim()!=='')fields[key]=Number($('#'+id).value);if(state.type==='dovetail'){if($('#slide-length').value.trim()!=='')fields.slide_length_mm=Number($('#slide-length').value);fields.neck_ratio=Number($('#neck-ratio').value);}return fields;}
const aiParameterLabels={size_mm:'连接宽度',depth_mm:'嵌入深度',beam_thickness_mm:'弹臂厚度',hook_mm:'扣头高度',size_tolerance_mm:'配合余量',depth_tolerance_mm:'深度余量',clearance_mm:'配合间隙',slide_length_mm:'滑入长度',neck_ratio:'燕尾颈宽比',bulge_pct:'扣头凸出',space_pct:'分叉槽',pin_radius_mm:'销轴半径',knuckle_radius_mm:'轴套外半径',segment_length_mm:'铰链总长度',gap_mm:'轴套间隔',rail_length_mm:'滑块长度',rail_width_mm:'滑块头宽',rail_depth_mm:'导轨深度',travel_mm:'总行程',stop_width_mm:'止挡销直径'};
const aiMotionLabels={fixed:'固定 / 拆卸',slide:'直线滑动',rotate:'转动开合',auto:'由 AI 判断',snap:'弹性卡合',assembly_slide:'一次性滑入装配'};
function aiDimensionText(parameters){
  const items=Object.entries(parameters||{}).filter(([,value])=>typeof value==='number'&&Number.isFinite(value)).slice(0,6);
  return items.map(([key,value])=>`${aiParameterLabels[key]||key} ${Number(value).toFixed(key.endsWith('_pct')?0:2)}${key.endsWith('_mm')?' mm':''}`).join(' · ');
}
function aiGeometryText(summary){
  if(typeof summary==='string')return summary;
  if(!summary||typeof summary!=='object')return '基于当前 A/B 的相对切面评估候选结构。';
  const count=Array.isArray(summary.placements)?summary.placements.length:0;
  const mode={plane:'平面切割',wave:'波浪曲面切割',bowl:'碗形曲面切割',independent_pair:'独立 A/B 零件'}[summary.cut_mode]||summary.cut_mode||'当前分件';
  const guidance=summary.dimension_guidance||{};
  const size=Number.isFinite(guidance.projected_short_span_mm)?`切面有效短边约 ${guidance.projected_short_span_mm} mm；`:'';
  const pitch=Number.isFinite(guidance.proxy_pitch_mm)?`代理体采样间距 ${guidance.proxy_pitch_mm} mm；细部尺寸仅能在代理体上预检。`:'';
  return `已读取 ${mode} 的 A/B 几何，找到 ${count} 个候选安装点；${size}${pitch}现有连接件 ${summary.existing_connector_count||0} 个。`;
}
function selectedAICandidate(){return state.aiProposal?.candidates?.find(item=>item.id===state.aiSelectedId)||null;}
function invalidateAIProposal(){state.aiToken++;state.aiProposal=null;state.aiSelectedId=null;state.aiOverrides={};renderAIProposal();}
function renderAIProposal(){
  const proposal=state.aiProposal;
  $('#ai-proposal').hidden=!proposal;
  if(!proposal)return;
  const analysis=proposal.analysis||{},model=proposal.model||{};
  $('#ai-model-note').textContent=`${state.project?.source?.label||'当前 A/B'} · R${proposal.revision} · `+(model.actual?`请求 ${model.requested||'AI'} / 实际 ${model.actual}`:model.status==='fallback'?'AI 暂不可用，显示规则候选':'未提供实际 AI 调用记录');
  $('#ai-geometry-summary').textContent=aiGeometryText(analysis.geometry_summary);
  const assumptions=Array.isArray(analysis.assumptions)?analysis.assumptions.join('；'):analysis.assumptions||'';
  $('#ai-assumptions').textContent=assumptions;
  $('#ai-reasoning-text').textContent=analysis.reasoning||'AI 未附加详细解释；请查看每个候选的设计理由和风险。';
  $('#ai-candidates').innerHTML=(proposal.candidates||[]).map(candidate=>{
    const supported=candidate.geometry_supported===true;
    const risk=Array.isArray(candidate.risks)?candidate.risks.join('；'):candidate.risks||'';
    const validation=Array.isArray(candidate.validation)?candidate.validation.filter(Boolean).join('；'):'';
    const adjustments=Array.isArray(candidate.parameter_adjustments)?candidate.parameter_adjustments.map(change=>`${aiParameterLabels[change.key]||change.key}：AI ${change.model} → 几何修正 ${change.geometric}`).join('；'):'';
    const mechanismMotion=candidate.assembly_motion||aiMotionLabels[candidate.motion]||candidate.motion||'连接结构';
    const badge=supported?'落点预检通过':candidate.engine_supported===false?'仅结构建议':'当前模型不可生成';
    return `<button type="button" class="ai-candidate ${candidate.id===state.aiSelectedId?'selected':''}" data-ai-candidate="${esc(candidate.id)}" aria-pressed="${candidate.id===state.aiSelectedId}"><span class="ai-candidate-header"><strong>${esc(candidate.name||candidate.family_id||'连接方案')}${candidate.id===proposal.recommended_id?' · AI 推荐':''}</strong><span class="ai-candidate-badge ${supported?'':'concept'}">${badge}</span></span><p>${esc(mechanismMotion)} · ${esc(candidate.reason||'')}</p><p class="ai-dimensions">${esc(aiDimensionText(candidate.parameters)||'尺寸待几何校验')}</p>${adjustments?`<p class="ai-adjustments">最终参数已由几何校正：${esc(adjustments)}</p>`:''}<p class="ai-risk">${esc([risk,validation].filter(Boolean).join('；')||(!supported?'当前模型或几何内核尚未支持此结构。':'落点预检通过；实体生成与打印配合仍需验证。'))}</p></button>`;
  }).join('')||'<p class="empty">没有通过当前约束的候选结构，请调整需求后重新分析。</p>';
  $$('[data-ai-candidate]').forEach(button=>button.onclick=()=>{state.aiSelectedId=button.dataset.aiCandidate;renderAIProposal();});
  const candidate=selectedAICandidate();
  $('#ai-selected-controls').hidden=!candidate;
  if(!candidate)return;
  const numeric=Object.entries(candidate.parameters||{}).filter(([,value])=>typeof value==='number'&&Number.isFinite(value));
  $('#ai-parameter-fields').innerHTML=candidate.geometry_supported===true
    ?numeric.map(([key,value])=>`<label>${esc(aiParameterLabels[key]||key)}<input type="number" data-ai-parameter="${esc(key)}" value="${esc(state.aiOverrides[candidate.id]?.[key]??value)}" step="any" aria-label="${esc(aiParameterLabels[key]||key)}"></label>`).join('')+'<p class="ai-parameter-note">尺寸以毫米计；这是落点预检，生成时会检查布尔结果、闭合与干涉；材料和打印配合需实物验证。</p>'
    :'<p class="ai-parameter-note">当前方案无法生成实体。请选择标有“落点预检通过”的候选，或调整需求后重新分析。</p>';
  $$('#ai-parameter-fields [data-ai-parameter]').forEach(input=>input.addEventListener('input',()=>{
    (state.aiOverrides[candidate.id]??={})[input.dataset.aiParameter]=input.value;
  }));
  const canGenerate=candidate.geometry_supported===true;
  const replacing=state.project?.connectors?.length||0;
  $('#parametric-build').disabled=state.busy||!canGenerate;
  $('#parametric-build').textContent=canGenerate?(replacing?`替换当前 ${replacing} 个连接件并尝试生成`:'尝试生成已选结构与配对零件'):'当前方案不可生成实体';
}
function renderConnectorFlowState(){
  const parametric=state.connectorFlow==='parametric';
  $$('[data-connector-flow]').forEach(button=>button.classList.toggle('active',button.dataset.connectorFlow===state.connectorFlow));
  $('#parametric-controls').hidden=!parametric;
  $('#manual-connector-controls').hidden=parametric;
  $('#connector-panel-title').textContent=parametric?'AI 连接 / 运动机构设计':'连接件设置';
  parametricMarkerRoot.visible=parametric;
  const selected=state.project?.connectors?.find(item=>item.id===state.selected);
  const aiOnlySelected=aiOnlyFamilies.has(selected?.type);
  const replacing=state.project?.connectors?.length||0;
  $('#ai-replace-note').hidden=!parametric||!replacing;
  if(replacing)$('#ai-replace-note').textContent=`当前 ${replacing} 个连接件会被所选 AI 方案替换；旧修订及其导出文件会保留。`;
  $('#manual-connector-controls').classList.toggle('ai-only-selected',aiOnlySelected);
  $('#manual-readonly-note').hidden=!aiOnlySelected;
  if(aiOnlySelected)$('#manual-readonly-text').textContent=`${names[selected.type]}包含手动参数栏无法表达的运动或弹性尺寸。可删除后重新用 AI 设计，或清除选择继续添加普通连接件。`;
  $('#save-connector').disabled=state.busy||aiOnlySelected;
  const available=state.stage==='connect'&&!!state.project;
  const sameSource=state.parametricContext?.source_id===state.project?.source_id;
  const sameRevision=state.parametricContext?.revision===state.project?.revision;
  const alignment=state.parametricContext?.alignment;
  const aligned=sameSource&&sameRevision&&alignment?.aligned===true;
  $('#connector-flow-note').textContent=parametric
    ?'描述开合与制造需求，AI 分析当前 A/B 的形状，建议结构、尺寸与位置。落点预检通过后可尝试生成，最终实体仍需检查。'
    :'确认分件后，在切面点选位置即生成当前类型的配对连接件；点已有标记可修改。';
  if(parametric){
    $('#parametric-source-note').textContent=!available?'请先完成当前整件分件，形成 A/B 零件。':state.parametricError?`来源校验失败：${state.parametricError}`:!state.parametricContext?'正在校验当前 A/B 的来源…':!sameSource||!sameRevision?'当前 A/B 已变化，正在刷新来源校验…':alignment?.warning||`已对齐当前配对零件：${state.project.source.label} · R${state.project.revision}`;
    $('#parametric-source-note').classList.toggle('warning',available&&!!state.parametricContext&&!aligned);
    $('#parametric-placement').textContent=state.parametricPlacement
      ?`位置偏好：${state.parametricPlacement.center_mm.map(value=>Number(value).toFixed(1)).join(', ')} mm。AI 会复核是否适合所选结构。`
      :'可直接让 AI 选择连接位置；也可在视口点击相对切面，指定希望安装的位置。';
    $('#ai-clear-anchor').hidden=!state.parametricPlacement;
    $('#ai-unknown-note').hidden=$('#ai-process').value!=='unknown'&&$('#ai-material').value!=='unknown';
    $('#ai-propose').disabled=state.busy||!available||!aligned;
    renderAIProposal();
  }
}
async function refreshParametricContext(){
  if(state.connectorFlow!=='parametric'||!state.project)return;
  const sourceId=state.project.source_id,revision=state.project.revision;
  state.parametricError=null;
  try{
    const context=await request('/api/parametric/context');
    if(state.connectorFlow==='parametric'&&state.project?.source_id===sourceId&&state.project.revision===revision){state.parametricContext=context;renderConnectorFlowState();}
  }catch(error){if(state.project?.source_id===sourceId){state.parametricContext=null;state.parametricError=error.message;renderConnectorFlowState();}}
}
function setConnectorFlow(flow){
  if(!['manual','parametric'].includes(flow))return;
  if(flow!==state.connectorFlow&&(state.motion.playing||!motionAtHome()))resetMotionPose();
  state.connectorFlow=flow;
  if(flow==='parametric')refreshParametricContext();
  renderConnectorFlowState();
  renderList();
  if(state.stage==='connect')$('#pointer-note').textContent=flow==='parametric'?'右侧先生成 AI 结构候选；点击切面可指定位置偏好':'点击任一切面放置连接件；拖动标记可改位置';
  if(embedded&&window.parent!==window&&document.referrer){
    try{window.parent.postMessage({type:'assembly:connector-flow',flow},new URL(document.referrer).origin);}catch{}
  }
  if(state.stage==='connect')notify(flow==='parametric'?'AI 会基于当前 A/B 推理连接形式和尺寸。描述需求后点击“分析 A/B 并提出方案”。':'已切换到自由点位；点击相对切面即可生成连接件。');
}
function writeFields(item){setType(['plug','dowel','snap','dovetail'].includes(item?.type)?item.type:'plug');$('#style').value=item?.style||'prism';$('#shape').value=item?.shape||'circle';$('#depth').value=item?.depth_mm??'';$('#size').value=item?.size_mm??'';$('#rotation').value=item?.rotation_deg??0;$('#size-tolerance').value=item?.size_tolerance_mm??item?.clearance_mm??.2;$('#depth-tolerance').value=item?.depth_tolerance_mm??item?.clearance_mm??.1;$('#bulge').value=item?.bulge_pct??15;$('#space').value=item?.space_pct??30;const size=item?.size_mm;$('#slide-length').min=size||2;$('#slide-length').value=item?.slide_length_mm??(size?Math.min(120,size*1.6).toFixed(1):'');$('#neck-ratio').value=item?.neck_ratio??.62;state.flip=item?.flip||false;$('#flip').textContent='↔ 翻转公母件：凸件在 '+(state.flip?'B':'A');}
function select(id,event){if(event?.shiftKey)state.selectedIds.add(id);else if(event?.ctrlKey||event?.metaKey)state.selectedIds.delete(id);else state.selectedIds=new Set([id]);state.selected=state.selectedIds.has(id)?id:[...state.selectedIds].at(-1)||null;const item=state.project.connectors.find(x=>x.id===state.selected);writeFields(item);renderList();renderConnectorFlowState();for(const marker of state.markers)marker.object.material.color.set(state.selectedIds.has(marker.id)?'#f16834':'#477f54');if(state.selectedIds.size>1)notify(`已选 ${state.selectedIds.size} 个连接件。Delete 删除，或继续 Shift/Ctrl 调整选择。`);else if(item)notify(state.connectorFlow==='parametric'?'已选现有连接件；右侧 AI 方案会生成新的结构，位置偏好需在视口单独点选。':aiOnlyFamilies.has(item.type)?`已选 ${names[item.type]}；该机构在手动参数栏只读，可删除后重新用 AI 设计。`:`已选择 ${names[item.type]||item.type}。改参数后点击“确认连接件”；右键标记可删除。`);else notify('已清除选择。');}
async function commit(items,success){
  if(state.busy)return false;
  const sourceId=state.project.source_id,revision=state.project.revision;
  busy(true);
  try{
    const project=await request('/api/manual/design',{source_id:sourceId,revision,connectors:items});
    if(state.project?.source_id!==sourceId||state.project.revision!==revision||project.source_id!==sourceId)throw new Error('模型来源或版本已变化，请刷新后再试；旧结果未覆盖当前视图');
    if(pendingMatches(project))pendingCaption.textContent='计算完成 · 正在载入正式连接件';
    renderProject(project);
    notify(`${success} · 已生成真实配对几何并保存 R${project.revision}。`);
    return true;
  }catch(error){
    clearPendingConnector();
    const at=success.startsWith('已添加')?` · 当前点 ${items.at(-1).center_mm.map(v=>v.toFixed(1)).join(', ')} mm`:'';
    notify(error.message+at,true);
    return false;
  }finally{busy(false);}
}
function pointerRay(event){const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);ray.setFromCamera(pointer,camera);}
function clearQuickPoint(){state.quickFirst=null;for(const object of [...quickPointRoot.children]){quickPointRoot.remove(object);object.geometry?.dispose();object.material?.dispose();}}
function clearParametricPlacement(){state.parametricPlacement=null;for(const object of [...parametricMarkerRoot.children]){parametricMarkerRoot.remove(object);object.geometry?.dispose();object.material?.dispose();}renderConnectorFlowState();}
function setParametricPlacement(face){clearParametricPlacement();state.parametricPlacement={center_mm:[...face.center_mm],normal:[...face.normal]};const marker=new THREE.Mesh(new THREE.SphereGeometry(.0022,16,12),new THREE.MeshStandardMaterial({color:'#ef8b35',emissive:'#d9631b',emissiveIntensity:.6,depthTest:false}));marker.position.copy(viewer(face.center_mm)).addScaledVector(viewer(face.normal).normalize(),.002);parametricMarkerRoot.add(marker);invalidateAIProposal();renderConnectorFlowState();notify(`已设位置偏好 ${face.center_mm.map(x=>x.toFixed(1)).join(', ')} mm；请重新分析，让 AI 将位置纳入结构设计。`);}
function quickPlaneAt(event){const whole=state.parts.get('whole');if(!whole)return;pointerRay(event);const hit=ray.intersectObject(whole,true)[0];if(!hit){notify('Shift + 点击模型表面选取切面定位点。',true);return;}if(!state.quickFirst){state.quickFirst=hit.point.clone();const marker=new THREE.Mesh(new THREE.SphereGeometry(.0018,12,8),new THREE.MeshBasicMaterial({color:'#e87928',depthTest:false}));marker.position.copy(hit.point);quickPointRoot.add(marker);notify('已选第一点。继续按住 Shift，点击模型上的第二点建立切面。');return;}const direction=hit.point.clone().sub(state.quickFirst),viewDirection=camera.getWorldDirection(new THREE.Vector3()).normalize();if(direction.length()<.002){notify('两点距离太近，请再选一个相隔至少 2 mm 的点。',true);return;}const normal=direction.cross(viewDirection).normalize();if(normal.lengthSq()<.01){notify('请从当前视角选取不重合的两点。',true);return;}const midpoint=state.quickFirst.clone().add(hit.point).multiplyScalar(.5);const center=engineering(midpoint);['cut-x','cut-y','cut-z'].forEach((id,i)=>{$('#'+id).value=center[i].toFixed(2);});setCutNormal([normal.x,-normal.z,normal.y]);$('#cut-axis').value='free';$('#cut-mode').value='plane';clearQuickPoint();updateCurveFields();recordCutState();notify('已用两点与当前视线建立平面切面；可继续拖手柄微调。');}
function cutFaceAt(event){pointerRay(event);const hits=[];for(const id of ['part_a','part_b']){const part=state.pickParts.get(id)||state.parts.get(id);if(!part)continue;part.updateMatrixWorld(true);const hit=ray.intersectObject(part,true)[0];if(hit)hits.push({id,hit});}hits.sort((a,b)=>a.hit.distance-b.hit.distance);if(!hits.length)return null;const {id,hit}=hits[0],point=hit.point.clone();if(id==='part_b')point.sub(explosionOffset());const normal=hit.face.normal.clone().transformDirection(hit.object.matrixWorld).normalize();if(id==='part_b')normal.negate();const face={center_mm:engineering(point),normal:[normal.x,-normal.z,normal.y].map(x=>Math.round(x*1000)/1000)};Object.defineProperty(face,'hitPartId',{value:id});return face;}
function nearMarker(event,radius=25){if(!motionAtHome())return null;const rect=renderer.domElement.getBoundingClientRect();let nearest=null;for(const pair of state.markerPairs)for(const marker of [pair.a,pair.b]){const p=marker.position.clone().project(camera);const x=(p.x+1)/2*rect.width+rect.left,y=(-p.y+1)/2*rect.height+rect.top;const distance=Math.hypot(event.clientX-x,event.clientY-y);if(distance<radius&&(!nearest||distance<nearest.distance))nearest={id:pair.id,distance};}return nearest;}
function previewMovedMarker(id,face){const pair=state.markerPairs.find(x=>x.id===id);if(!pair)return;const base=viewer(face.center_mm),direction=viewer(face.normal).normalize();pair.base.copy(base);pair.direction.copy(direction);pair.a.position.copy(base).addScaledVector(direction,.001);pair.b.position.copy(base).addScaledVector(direction,-.001).add(explosionOffset());pair.line.geometry.dispose();pair.line.geometry=new THREE.BufferGeometry().setFromPoints([pair.a.position,pair.b.position]);pair.line.computeLineDistances();}
async function addAt(event){if(state.busy)return;if(!motionAtHome()){notify('正在预览运动；请先点击“复位”回到装配位置，再选择切面。');return;}pointerRay(event);if(state.stage==='preview'){const hits=[];for(const [id,part] of state.parts){const hit=ray.intersectObject(part,true)[0];if(hit)hits.push({id,distance:hit.distance});}hits.sort((a,b)=>a.distance-b.distance);if(hits.length)selectPreviewPiece(hits[0].id);else notify('请点击想处理的切块，随后选择并回主体、独立件或丢弃。');return;}if(state.stage!=='connect'||state.view!=='exploded')return;const face=cutFaceAt(event);if(!face){notify('请点击两件零件相对的切面。',true);return;}if(state.connectorFlow==='parametric'){
  const sourceId=state.project.source_id,revision=state.project.revision;
  busy(true);notify('正在核对这个位置是否在 A/B 共同切面上…');
  try{
    const check=await request('/api/parametric/placement/check',{source_id:sourceId,revision,...face});
    if(state.stage!=='connect'||state.project?.source_id!==sourceId||state.project.revision!==revision)return;
    if(!check.valid){notify(check.reason||'这个位置不在 A/B 相对切面上，请换一个点。',true);return;}
    setParametricPlacement(face);
  }catch(error){notify(`连接位置校验失败：${error.message}`,true);}
  finally{busy(false);}
  return;
}const item={id:'c'+Math.random().toString(36).slice(2,10),...readFields(),...face};const items=[...state.project.connectors,item];showPendingConnector(face,item.id);notify(`待确认位置 ${face.center_mm.map(value=>value.toFixed(1)).join(', ')} mm · 正在计算配对实体，尚未生成连接件…`);if(await commit(items,'已添加 '+names[item.type]))select(item.id);}
async function removeNear(event){if(state.busy||!state.markerPairs.length)return;const nearest=nearMarker(event,35);if(!nearest){notify('在连接件标记附近右键可删除。');return;}const items=state.project.connectors.filter(x=>x.id!==nearest.id);await commit(items,'已移除连接件');if(state.selected===nearest.id){state.selected=null;writeFields(null);}}
renderer.domElement.addEventListener('pointerdown',e=>{down={x:e.clientX,y:e.clientY,button:e.button,pointerId:e.pointerId};if(e.button===0&&state.stage==='connect'&&state.view==='exploded'&&state.connectorFlow==='manual'&&!state.busy){const marker=nearMarker(e);if(marker){down.markerId=marker.id;down.readOnly=aiOnlyFamilies.has(state.project?.connectors?.find(item=>item.id===marker.id)?.type);if(!down.readOnly){controls.enabled=false;renderer.domElement.setPointerCapture(e.pointerId);}}}},true);
renderer.domElement.addEventListener('pointermove',e=>{if(!down?.markerId||down.readOnly||e.pointerId!==down.pointerId)return;if(Math.hypot(e.clientX-down.x,e.clientY-down.y)<5)return;down.moved=true;const face=cutFaceAt(e);if(face){down.candidate=face;previewMovedMarker(down.markerId,face);}},true);
renderer.domElement.addEventListener('pointerup',async e=>{if(!down||e.pointerId!==down.pointerId)return;const last=down;down=null;if(last.markerId){if(last.readOnly){if(Math.hypot(e.clientX-last.x,e.clientY-last.y)<=5)select(last.markerId,e);return;}controls.enabled=true;if(renderer.domElement.hasPointerCapture(e.pointerId))renderer.domElement.releasePointerCapture(e.pointerId);if(!last.moved){select(last.markerId,e);return;}if(!last.candidate){renderProject(state.project);notify('请把连接件拖到相对切面上。',true);return;}const items=state.project.connectors.map(item=>item.id===last.markerId?{...item,...last.candidate}:item);if(await commit(items,'已移动连接件'))select(last.markerId);else renderProject(state.project);return;}if(Math.hypot(e.clientX-last.x,e.clientY-last.y)>5)return;if(last.button===0&&state.stage==='cut'&&e.shiftKey)quickPlaneAt(e);else if(last.button===0)addAt(e);},true);
renderer.domElement.addEventListener('pointercancel',()=>{if(down?.markerId){controls.enabled=true;renderProject(state.project);}down=null;},true);
renderer.domElement.addEventListener('contextmenu',e=>{e.preventDefault();if(state.stage==='preview')addAt(e);else if(state.stage==='connect')removeNear(e);});
$$('[data-view]').forEach(el=>el.onclick=()=>view(el.dataset.view));$('#fit-view').onclick=fit;
$$('[data-type]').forEach(el=>el.onclick=()=>setType(el.dataset.type));
$$('[data-connector-flow]').forEach(button=>button.onclick=()=>setConnectorFlow(button.dataset.connectorFlow));
for(const id of ['ai-motion','ai-process','ai-material','ai-frequency','ai-removable','ai-notes']){
  $('#'+id).addEventListener(id==='ai-notes'?'input':'change',()=>{
    if(state.aiProposal){invalidateAIProposal();notify('设计需求已改变，请重新让 AI 分析当前 A/B。');}
    renderConnectorFlowState();
  });
}
$('#ai-clear-anchor').onclick=()=>{clearParametricPlacement();invalidateAIProposal();renderConnectorFlowState();notify('已清除位置偏好，AI 将自行寻找合适的连接位置。');};
$('#ai-propose').onclick=async()=>{
  if(state.busy||state.stage!=='connect'||!state.project)return;
  const context=state.parametricContext;
  if(context?.source_id!==state.project.source_id||context?.revision!==state.project.revision||!context.alignment?.aligned){
    notify('当前 A/B 的来源或版本尚未校验完成。',true);refreshParametricContext();return;
  }
  const payload={source_id:state.project.source_id,revision:state.project.revision,design_intent:{
    motion:$('#ai-motion').value,frequency:$('#ai-frequency').value,removable:$('#ai-removable').checked,
    material:$('#ai-material').value,process:$('#ai-process').value,notes:$('#ai-notes').value.trim()
  }};
  if(state.parametricPlacement)payload.anchor={...state.parametricPlacement};
  invalidateAIProposal();const token=state.aiToken;
  busy(true);notify('正在分析零件几何、连接运动与打印约束，并请 AI 提出结构候选…');
  try{
    const proposal=await request('/api/parametric/ai/propose',payload);
    if(token!==state.aiToken||state.project?.source_id!==payload.source_id||state.project.revision!==payload.revision)return;
    if(proposal.source_id!==payload.source_id||proposal.revision!==payload.revision)throw new Error('提案对应的模型版本不一致，请重新分析。');
    state.aiProposal=proposal;
    state.aiSelectedId=proposal.recommended_id||proposal.candidates?.[0]?.id||null;
    renderConnectorFlowState();
    const supported=(proposal.candidates||[]).filter(item=>item.geometry_supported===true).length;
    notify(`已得到 ${(proposal.candidates||[]).length} 个候选，其中 ${supported} 个通过落点预检、可尝试生成。请先查看理由、尺寸与风险，再选择结构。`);
  }catch(error){notify(`AI 结构分析失败：${error.message}`,true);}
  finally{busy(false);}
};
$('#parametric-build').onclick=async()=>{
  const candidate=selectedAICandidate(),proposal=state.aiProposal,project=state.project;
  if(state.busy||state.stage!=='connect'||!project||!proposal||!candidate)return;
  if(candidate.geometry_supported!==true){notify('这个结构目前只有概念提案，尚无可校验的实体几何内核。',true);return;}
  if(proposal.source_id!==project.source_id||proposal.revision!==project.revision){notify('模型已改变，请重新分析 A/B。',true);invalidateAIProposal();return;}
  const parameters={};
  for(const input of $$('#ai-parameter-fields [data-ai-parameter]')){
    const value=Number(input.value);
    if(input.value.trim()===''||!Number.isFinite(value)){notify(`请填写有效的 ${aiParameterLabels[input.dataset.aiParameter]||input.dataset.aiParameter}。`,true);input.focus();return;}
    if(value!==Number(candidate.parameters?.[input.dataset.aiParameter]))parameters[input.dataset.aiParameter]=value;
  }
  const payload={source_id:project.source_id,revision:project.revision,proposal_id:proposal.proposal_id,candidate_id:candidate.id};
  if(Object.keys(parameters).length)payload.overrides={parameters};
  busy(true);notify('正在按已选 AI 方案生成配对实体、复核切面位置和装配干涉…');
  try{
    const result=await request('/api/parametric/ai/generate',payload);
    if(!result.project)throw new Error('服务端未返回生成的配对零件。');
    state.selected=null;state.selectedIds.clear();renderProject(result.project);
    const replaced=Number(result.replaced_connector_count??result.validation?.replaced_connector_count);
    const replaceNote=Number.isInteger(replaced)&&replaced>0?`已替换 ${replaced} 个旧连接件，旧修订保留；`:'';
    if(replaceNote){$('#replacement-summary').textContent=`本次 AI 方案替换了 ${replaced} 个旧连接件；旧修订及其导出文件仍保留。`;$('#replacement-summary').hidden=false;}
    notify(`已生成 ${candidate.name||candidate.family_id}；${replaceNote}A/B 配对几何、参数及导出同步保存为 R${result.project.revision}。请进行试打印与实际开合验证。`);
  }catch(error){notify(`AI 连接结构生成失败：${error.message}`,true);}
  finally{busy(false);}
};
$('#size').addEventListener('input',()=>{const raw=$('#size').value.trim(),size=raw?Number(raw):null;$('#slide-length').min=size||2;if(state.type==='dovetail'){if(!size)$('#slide-length').value='';else if(!$('#slide-length').value||Number($('#slide-length').value)<size)$('#slide-length').value=Math.min(120,size*1.6).toFixed(1);}});
$('#manual-deselect').onclick=()=>{state.selected=null;state.selectedIds.clear();writeFields(null);renderList();renderConnectorFlowState();for(const marker of state.markers)marker.object.material.color.set('#477f54');notify('已清除只读机构选择；可以继续手动添加普通连接件。');};
$('#flip').onclick=()=>{state.flip=!state.flip;$('#flip').textContent='↔ 翻转公母件：凸件在 '+(state.flip?'B':'A');};
$('#save-connector').onclick=async()=>{if(!state.selected){notify('先点击切面添加连接件，或在左侧选择已有连接件。',true);return;}if(aiOnlyFamilies.has(state.project.connectors.find(x=>x.id===state.selected)?.type)){notify('该机构需在 AI 方案中重新设计；手动参数栏不包含它的全部尺寸与运动约束。',true);return;}const items=state.project.connectors.map(x=>x.id===state.selected?{...x,...readFields()}:x);await commit(items,'已更新连接件');};
async function deleteSelected(){if(state.busy||!state.selectedIds.size||!state.project)return;const count=state.selectedIds.size,items=state.project.connectors.filter(x=>!state.selectedIds.has(x.id));if(await commit(items,`已删除 ${count} 个连接件`)){state.selectedIds.clear();state.selected=null;writeFields(null);renderList();}}
$('#delete-selected').onclick=deleteSelected;
document.addEventListener('keydown',event=>{if(state.stage!=='connect'||event.target.closest('input,select,textarea,[contenteditable]'))return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='a'){event.preventDefault();state.selectedIds=new Set(state.project.connectors.map(x=>x.id));state.selected=[...state.selectedIds].at(-1)||null;renderList();for(const marker of state.markers)marker.object.material.color.set(state.selectedIds.has(marker.id)?'#f16834':'#477f54');notify(`已选择全部 ${state.selectedIds.size} 个连接件。`);}else if((event.key==='Delete'||event.key==='Backspace')&&state.selectedIds.size){event.preventDefault();deleteSelected();}else if(event.key==='Escape'){state.selectedIds.clear();state.selected=null;const hadAnchor=!!state.parametricPlacement;clearParametricPlacement();if(hadAnchor)invalidateAIProposal();renderList();for(const marker of state.markers)marker.object.material.color.set('#477f54');notify(state.connectorFlow==='parametric'?'已清除选择与位置偏好；位置改变后请重新分析。':'已清除选择；可点击新位置创建连接件。');}});
$('#cancel-edit').onclick=()=>{writeFields(state.project?.connectors.find(x=>x.id===state.selected));notify('已恢复上次保存的设置。');};
function setCutNormal(normal){const n=new THREE.Vector3(...normal).normalize();const tilt=Math.acos(THREE.MathUtils.clamp(n.z,-1,1))*180/Math.PI;let azimuth=Math.atan2(n.y,n.x)*180/Math.PI;if(Math.hypot(n.x,n.y)<1e-5)azimuth=Number($('#cut-azimuth').value)||0;$('#cut-tilt').value=tilt.toFixed(2);$('#cut-azimuth').value=azimuth.toFixed(2);}
const cutHistoryFields=['cut-mode','cut-axis','cut-x','cut-y','cut-z','cut-tilt','cut-azimuth','cut-amplitude','cut-wavelength'];
function cutSnapshot(){return Object.fromEntries(cutHistoryFields.map(id=>[id,$('#'+id).value]));}
function renderCutHistoryControls(){const ready=!state.busy&&state.stage==='cut'&&state.whole?.cut_ready!==false;$('#cut-undo').disabled=!ready||state.cutHistoryIndex<=0;$('#cut-redo').disabled=!ready||state.cutHistoryIndex>=state.cutHistory.length-1;}
function resetCutHistory(){state.cutHistory=[cutSnapshot()];state.cutHistoryIndex=0;renderCutHistoryControls();}
function recordCutState(){
  if(state.cutHistoryApplying||state.stage!=='cut'||!state.whole||state.busy)return;
  const snapshot=cutSnapshot();
  if(JSON.stringify(snapshot)===JSON.stringify(state.cutHistory[state.cutHistoryIndex]))return;
  state.cutHistory=state.cutHistory.slice(0,state.cutHistoryIndex+1);
  state.cutHistory.push(snapshot);
  if(state.cutHistory.length>50)state.cutHistory.shift();
  state.cutHistoryIndex=state.cutHistory.length-1;
  renderCutHistoryControls();
}
function applyCutHistory(index){
  if(state.busy||state.stage!=='cut'||index<0||index>=state.cutHistory.length)return;
  state.cutHistoryApplying=true;
  for(const [id,value] of Object.entries(state.cutHistory[index]))$('#'+id).value=value;
  state.cutHistoryIndex=index;
  updateCurveFields();
  state.cutHistoryApplying=false;
  renderCutHistoryControls();
}
function undoCut(){if(state.cutHistoryIndex>0){const previous=state.cutHistoryIndex;applyCutHistory(previous-1);notify(`已撤销切面调整（${state.cutHistoryIndex+1}/${state.cutHistory.length}）。`);}}
function redoCut(){if(state.cutHistoryIndex<state.cutHistory.length-1){applyCutHistory(state.cutHistoryIndex+1);notify(`已重做切面调整（${state.cutHistoryIndex+1}/${state.cutHistory.length}）。`);}}
function cutParameters(){const tilt=Number($('#cut-tilt').value)*Math.PI/180,azimuth=Number($('#cut-azimuth').value)*Math.PI/180;const normal=[Math.sin(tilt)*Math.cos(azimuth),Math.sin(tilt)*Math.sin(azimuth),Math.cos(tilt)];return {source_id:state.whole?.id,mode:$('#cut-mode').value,origin_mm:['cut-x','cut-y','cut-z'].map(id=>Number($('#'+id).value)),normal,amplitude_mm:Number($('#cut-amplitude').value),wavelength_mm:Number($('#cut-wavelength').value)};}
function disposeCutGuide(){for(const object of [...cutGuide.children]){cutGuide.remove(object);object.geometry?.dispose();if(Array.isArray(object.material))object.material.forEach(m=>m.dispose());else object.material?.dispose();}}
function showCutGuide(syncAnchor=true){disposeCutGuide();cutGuide.visible=state.stage==='cut'&&!!state.whole;if(!cutGuide.visible)return;const p=cutParameters(),origin=new THREE.Vector3(...p.origin_mm),n=new THREE.Vector3(...p.normal).normalize();$('#cut-normal-readout').textContent=`切面法线 (${p.normal.map(x=>x.toFixed(3)).join(', ')})`;if(syncAnchor){cutAnchor.position.copy(viewer(p.origin_mm));cutAnchor.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),viewer(p.normal).normalize());}const helper=Math.abs(n.x)<.85?new THREE.Vector3(1,0,0):new THREE.Vector3(0,1,0);const u=helper.clone().cross(n).normalize(),v=n.clone().cross(u).normalize();const bounds=state.whole.bounds_mm;const radius=Math.max(...bounds[1].map((x,i)=>x-bounds[0][i]))*.8+5;const divisions=p.mode==='plane'?1:36;const positions=[],indices=[];for(let i=0;i<=divisions;i++)for(let j=0;j<=divisions;j++){const x=(i/divisions*2-1)*radius,y=(j/divisions*2-1)*radius;const h=p.mode==='wave'?p.amplitude_mm*Math.sin(2*Math.PI*x/p.wavelength_mm):p.mode==='bowl'?p.amplitude_mm*((x/p.wavelength_mm)**2+(y/p.wavelength_mm)**2):0;const point=origin.clone().addScaledVector(u,x).addScaledVector(v,y).addScaledVector(n,h);positions.push(...viewer(point.toArray()).toArray());}for(let i=0;i<divisions;i++)for(let j=0;j<divisions;j++){const a=i*(divisions+1)+j,b=(i+1)*(divisions+1)+j,c=b+1,d=a+1;indices.push(a,b,c,a,c,d);}const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);geometry.computeVertexNormals();cutGuide.add(new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({color:'#f1a33f',transparent:true,opacity:.29,side:THREE.DoubleSide,depthWrite:false})));const edges=new THREE.EdgesGeometry(geometry,20);cutGuide.add(new THREE.LineSegments(edges,new THREE.LineBasicMaterial({color:'#c77729',transparent:true,opacity:.65})));}
function updateCurveFields(){const curved=$('#cut-mode').value!=='plane';$$('.curve-field').forEach(row=>row.style.display=curved?'flex':'none');showCutGuide();}
function setCutTool(mode){cutTransform.setMode(mode);cutTransform.setSpace(mode==='translate'?'world':'local');cutTransform.showX=true;cutTransform.showY=true;cutTransform.showZ=true;$$('[data-cut-tool]').forEach(el=>el.classList.toggle('active',el.dataset.cutTool===mode));$('#gizmo-hint').textContent=mode==='translate'?'拖红 X / 绿 Z / 蓝 Y 三轴平移；空白处转视角':'拖三色圆环绕轴旋转；空白处转视角';$('#pointer-note').textContent=mode==='translate'?'拖动窗口中的三轴箭头移动切割面，左侧中心坐标会同步更新':'拖动窗口中的三色圆环旋转切割面，左侧法线角度会同步更新';syncCutTransform();}
$$('[data-cut-tool]').forEach(el=>el.onclick=()=>setCutTool(el.dataset.cutTool));
$('#cut-undo').onclick=undoCut;
$('#cut-redo').onclick=redoCut;
document.addEventListener('keydown',event=>{
  if(state.stage!=='cut'||state.busy||!event.ctrlKey||event.altKey||event.shiftKey)return;
  const key=event.key.toLowerCase();
  if(key!=='z'&&key!=='y')return;
  event.preventDefault();
  if(event.target instanceof HTMLElement&&event.target.matches('input,select'))renderer.domElement.focus();
  if(key==='z')undoCut();else redoCut();
});
setCutTool('translate');
$('#cut-mode').onchange=updateCurveFields;updateCurveFields();
$('#cut-axis').onchange=()=>{const axis=$('#cut-axis').value;if(axis==='x')setCutNormal([1,0,0]);else if(axis==='y')setCutNormal([0,1,0]);else if(axis==='z')setCutNormal([0,0,1]);showCutGuide();};
for(const id of ['cut-x','cut-y','cut-z','cut-amplitude','cut-wavelength'])$('#'+id).addEventListener('input',()=>showCutGuide());
for(const id of ['cut-tilt','cut-azimuth'])$('#'+id).addEventListener('input',()=>{$('#cut-axis').value='free';showCutGuide();});
cutHistoryFields.forEach(id=>$('#'+id).addEventListener('change',recordCutState));
function centerCutOnSource(source,resetHistory=false){const bounds=source.bounds_mm;$('#cut-x').value=((bounds[0][0]+bounds[1][0])/2).toFixed(2);$('#cut-y').value=((bounds[0][1]+bounds[1][1])/2).toFixed(2);$('#cut-z').value=((bounds[0][2]+bounds[1][2])/2).toFixed(2);$('#cut-axis').value='z';setCutNormal([0,0,1]);showCutGuide();if(resetHistory)resetCutHistory();}
$('#edit-whole').onclick=()=>{if(state.whole){const first=!state.cutHistory.length;showWhole(state.whole);if(first)centerCutOnSource(state.whole,true);notify('继续调整整件切面，重新预览后再确认分件。');}};
$('#edit-cut').onclick=()=>{if(state.whole){showWhole(state.whole);notify('已返回切面编辑，之前的切割预览不会覆盖当前配对零件。');}};
$('#reset-cut').onclick=()=>{if(!state.whole)return;clearQuickPoint();$('#cut-mode').value='plane';centerCutOnSource(state.whole);updateCurveFields();recordCutState();notify('已将当前切面恢复到整件中心和 Z 向。');};
$('#flip-cut-plane').onclick=()=>{if(!state.whole||state.stage!=='cut')return;const normal=cutParameters().normal.map(value=>-value);setCutNormal(normal);$('#cut-axis').value='free';showCutGuide();recordCutState();notify('已翻转切面方向；预览中的上侧与下侧将互换。');};
$('#whole-sample').onclick=async()=>{busy(true);notify('正在生成整件示例…');try{const data=await request('/api/manual/cut/sample',{});showWhole(data.source);centerCutOnSource(data.source,true);notify('已载入整件示例。一刀会切到两根立柱，预览后可以只选一根独立。');}catch(error){notify(error.message,true);}finally{busy(false);}};
$('#whole-file').onchange=async()=>{
  const file=$('#whole-file').files[0];if(!file)return;
  const glb=file.name.toLowerCase().endsWith('.glb');
  if(!glb&&!file.name.toLowerCase().endsWith('.stl')){notify('整件模型只接受 GLB 或 STL。',true);return;}
  if(file.size>50*1024*1024){notify('整件模型单文件上限为 50 MB。',true);return;}
  busy(true);notify(`正在检查整件 ${glb?'GLB':'STL'}${glb?'，并尝试修复开口':''}…`);
  try{
    const payload={data:await data64(file),name:file.name};
    if(glb){payload.units=$('#glb-units').value;payload.up_axis=$('#glb-up-axis').value;}
    const data=await request('/api/manual/cut/upload',payload);
    showWhole(data.source);centerCutOnSource(data.source,true);
    const coordinateNote=glb?`（按 ${payload.units} / ${payload.up_axis}-up 导入）`:'';
    if(data.source.cut_ready===false){
      notify(`原始 GLB 已保真载入${coordinateNote}；正在尝试生成可切割的近似水密代理体。`);
      await generateProxy();
      return;
    }
    const notes=Array.isArray(data.source.repair_notes)?data.source.repair_notes:[];
    const capped=notes.some(note=>/filled|capped/.test(note));
    const repairNote=capped?'；检测到开口，已自动补面并验证闭合，请检查补面位置':notes.length?'；已自动校正网格并验证闭合':'';
    notify(`整件已载入${coordinateNote}${repairNote}。拖动切面手柄，或直接输入中心与方向，然后预览。`);
  }catch(error){notify(error.message,true);}finally{busy(false);}
};
$('#preview-cut').onclick=async()=>{if(!state.whole){notify('请先载入整件 GLB、STL 或示例。',true);return;}if(state.whole.cut_ready===false||state.viewingOriginal){notify('请先切换到可切割的水密代理体。',true);return;}busy(true);notify('正在布尔切割、封口并分析各切块…');try{const preview=await request('/api/manual/cut/preview',cutParameters());showPreview(preview);notify(`切出 ${preview.components.length} 块，断面已封口。选择要独立的切块，其余会并回主体。`);}catch(error){notify(error.message,true);}finally{busy(false);}};
$('#commit-cut').onclick=async()=>{if(!state.preview)return;if(!state.separate.size||state.separate.size+state.discard.size>=state.preview.components.length){notify('至少选一块独立，并留一块在主体；丢弃块不能占用全部剩余部分。',true);return;}busy(true);notify('正在合并主体、校验配对切面并生成可编辑零件…');try{const data=await request('/api/manual/cut/commit',{preview_id:state.preview.id,separate_ids:[...state.separate],discard_ids:[...state.discard],output_mode:$('#cut-output-mode').value,print_orientation:{part_a:$('#print-a').value,part_b:$('#print-b').value}});state.selected=null;state.selectedIds.clear();renderProject(data.project);notify(`已分件：${state.separate.size} 块独立，${state.discard.size} 块丢弃，其余并回主体；两侧断面闭合。现在点击切面布置连接件。`);}catch(error){notify(error.message,true);}finally{busy(false);}};
function filePicked(){const a=$('#file-a').files[0],b=$('#file-b').files[0];busy(false);if(a&&b)notify(`已选择 ${a.name} 和 ${b.name}，点击“载入这对零件”。`);}
$('#file-a').onchange=filePicked;$('#file-b').onchange=filePicked;
function data64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('读取模型文件失败'));reader.readAsDataURL(file);});}
$('#upload-pair').onclick=async()=>{const a=$('#file-a').files[0],b=$('#file-b').files[0];if(!a||!b)return;if(a.size>12*1024*1024||b.size>12*1024*1024){notify('每个 STL 文件上限为 12 MB。',true);return;}busy(true);notify('正在读取并校验两个 STL…');try{const data=await request('/api/manual/upload',{part_a:await data64(a),part_b:await data64(b),names:[a.name,b.name]});state.selected=null;renderProject(data.project);notify('已载入两件 STL。请确认它们保留共同装配坐标，随后点击切面放置连接件。');}catch(error){notify(error.message,true);}finally{busy(false);}};
$('#restore-sample').onclick=async()=>{busy(true);try{const data=await request('/api/manual/sample',{});state.selected=null;renderProject(data.project);notify('已恢复示例切面。点击蓝色零件上表面开始布置。');}catch(error){notify(error.message,true);}finally{busy(false);}};
setType('plug');
function hasCurrentPair(project){
  const ids=new Set((project?.parts||[]).map(part=>part.id));
  const sourceIds=new Set((project?.source?.parts||[]).map(part=>part.id));
  return !!project?.source_id&&Number.isInteger(project.revision)&&
    ['part_a','part_b'].every(id=>ids.has(id)&&sourceIds.has(id));
}
function shouldAutoOpenCut(project,wholeSource){
  const pairWholeSha=hasCurrentPair(project)?project.source.cut?.full_source_sha256:null;
  const wholeSha=wholeSource?.sha256;
  if(typeof pairWholeSha==='string'&&pairWholeSha&&typeof wholeSha==='string'&&wholeSha)return pairWholeSha!==wholeSha;
  return wholeSource?.cut_ready===false||!!wholeSource?.proxy?.approximate;
}
async function initialize(){
  let project=null;
  try{project=await request('/api/manual/project');renderProject(project);notify('可从左侧载入整件 GLB / STL 开始切割；当前配对零件也可直接点击切面布置连接件。');}
  catch(error){notify(error.message,true);}
  try{
    const data=await request('/api/manual/cut/source');
    if(data.source){
      if(shouldAutoOpenCut(project,data.source)){showWhole(data.source);centerCutOnSource(data.source,true);}
      else{state.whole=data.source;$('#whole-name').textContent=data.source.label;$('#whole-info').textContent=data.source.proxy?.approximate?'近似切割代理体 · 可重新调整切面':'已载入整件 · 可重新预览切割';$('#edit-whole').hidden=state.stage==='cut';}
    }
  }catch(error){notify(error.message,true);}
}
initialize();
