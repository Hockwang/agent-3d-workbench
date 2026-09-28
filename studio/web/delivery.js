import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createGLTFLoader } from './gltf-loader.js';
import { RenderLoop, resizeDrawingBuffer } from './render-loop.js';
import { t } from './i18n.js';
const data = JSON.parse(document.getElementById('project-data').textContent);
const title = document.querySelector('h1'); title.textContent = data.title;
const stage = document.getElementById('stage'), status = document.getElementById('status');
const scene = new THREE.Scene(); scene.background = new THREE.Color('#111821');
const camera = new THREE.PerspectiveCamera(45, 1, .001, 10000);
const renderer = new THREE.WebGLRenderer({ antialias: true }); stage.append(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x53647c, 2));
const key = new THREE.DirectionalLight(0xffffff, 2); key.position.set(3,5,4); scene.add(key);
const root = new THREE.Group(); scene.add(root);
const assetRoots = [], animationRecords = [];
let mixer, playing = false, mode = 'orbit', extent = 1, previous = 0;
const keys = new Set(), markers = [], collected = new Set();
const loop = new RenderLoop(({resize,resizing}) => {
  if (resize) resizeDrawingBuffer(renderer,camera,stage,resizing);
  const now = performance.now(), dt = Math.min((now - (previous || now))/1000,.05); previous = now;
  if (playing) mixer?.update(dt);
  if (mode === 'explore' && keys.size) {
    const direction = camera.getWorldDirection(new THREE.Vector3()); direction.y = 0; direction.normalize();
    const right = direction.clone().cross(new THREE.Vector3(0,1,0));
    const delta = new THREE.Vector3();
    if (keys.has('w')) delta.add(direction); if (keys.has('s')) delta.sub(direction);
    if (keys.has('d')) delta.add(right); if (keys.has('a')) delta.sub(right);
    delta.multiplyScalar(extent*.3*dt);camera.position.add(delta);controls.target.add(delta);
  }
  controls.update();renderer.render(scene,camera);return playing || keys.size > 0;
});
controls.addEventListener('change',()=>loop.invalidate());new ResizeObserver(()=>loop.resize()).observe(stage);
function fit() {
  const box = new THREE.Box3();
  for (const child of root.children) if (child.visible) box.union(new THREE.Box3().setFromObject(child));
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());extent=Math.max(box.getSize(new THREE.Vector3()).length(),.001);
  controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(1,.7,1).normalize().multiplyScalar(extent*1.5));
  camera.near=extent/10000;camera.far=extent*100;camera.updateProjectionMatrix();controls.update();loop.invalidate();
}
document.getElementById('fit').onclick=fit;
document.getElementById('explore').onclick=()=>{mode=mode==='orbit'?'explore':'orbit';document.getElementById('explore').textContent=mode==='explore'?t('delivery.explore.exit'):t('delivery.explore.enter');};
document.addEventListener('keydown',e=>{if(mode==='explore'&&'wasd'.includes(e.key.toLowerCase())){keys.add(e.key.toLowerCase());loop.invalidate();}});
document.addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));window.addEventListener('blur',()=>keys.clear());
document.addEventListener('visibilitychange',()=>{keys.clear();loop.setActive(!document.hidden);});
const raycaster=new THREE.Raycaster();let down;
renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];});
renderer.domElement.addEventListener('click',e=>{
  if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4)return;
  const r=renderer.domElement.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);
  const hit=raycaster.intersectObjects(markers)[0];if(!hit)return;
  collected.add(hit.object.userData.index);hit.object.material.color.set('#7cdda4');
  document.getElementById('detail').textContent=hit.object.userData.label;
  status.textContent=t('delivery.explore.progress',{done:collected.size,total:markers.length})+(collected.size===markers.length?t('delivery.explore.allDoneSuffix'):'');loop.invalidate();
});
function chooseAnimations(index) {
  if (mixer) {mixer.stopAllAction();mixer.uncacheRoot(mixer.getRoot());}
  playing=false;mixer=null;
  const clips=animationRecords.filter(x=>index<0||x.index===index);
  const select=document.getElementById('clip'), button=document.getElementById('play');
  select.replaceChildren();select.hidden=button.hidden=clips.length===0;button.textContent=t('delivery.action.play');
  for(const [i,entry] of clips.entries()){
    const option=document.createElement('option');option.value=i;option.textContent=entry.clip.name||t('delivery.clip.fallbackName',{n:i+1});select.append(option);
  }
  const choose=()=>{
    if(mixer){mixer.stopAllAction();mixer.uncacheRoot(mixer.getRoot());}
    const entry=clips[Number(select.value)];if(!entry)return;
    mixer=new THREE.AnimationMixer(entry.scene);mixer.clipAction(entry.clip).reset().play();loop.invalidate();
  };
  select.onchange=choose;if(clips.length)choose();
  button.onclick=()=>{playing=!playing;button.textContent=playing?t('delivery.action.pause'):t('delivery.action.play');loop.invalidate();};
}
(async()=>{
  const loader=createGLTFLoader(renderer);
  try {
  for(const asset of data.assets){
    const binary=atob(asset.data),bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
    const result=await loader.parseAsync(bytes.buffer,'');root.add(result.scene);assetRoots.push(result.scene);
    for (const clip of result.animations) animationRecords.push({clip,scene:result.scene,index:assetRoots.length-1});
  }
  } finally {loader.disposeCodecs();}
  fit();
  chooseAnimations(-1);
  const assetSelect=document.getElementById('asset');assetSelect.hidden=data.assets.length<2;
  for(const [index,asset] of data.assets.entries()){
    const option=document.createElement('option');option.value=index;option.textContent=asset.name||t('delivery.asset.fallbackName',{n:index+1});assetSelect.append(option);
  }
  assetSelect.onchange=()=>{
    const selected=Number(assetSelect.value);assetRoots.forEach((item,index)=>{item.visible=selected<0||selected===index;});
    markers.forEach(marker=>{marker.visible=selected<0;});chooseAnimations(selected);fit();
  };
  const box=new THREE.Box3().setFromObject(root),center=box.getCenter(new THREE.Vector3());
  for(const [index,item] of (data.hotspots||[]).entries()){
    const marker=new THREE.Mesh(new THREE.SphereGeometry(extent*.018,16,12),new THREE.MeshBasicMaterial({color:'#79b5ff',depthTest:false}));
    marker.position.fromArray(item.position||center.toArray());marker.userData={index,label:item.label};markers.push(marker);scene.add(marker);
  }
  status.textContent=markers.length?t('delivery.status.clickMarkersHint',{total:markers.length}):t('delivery.status.dragToOrbit');loop.resize();
})().catch(error=>{status.textContent=t('delivery.error.loadFailed',{detail:error.message});});
