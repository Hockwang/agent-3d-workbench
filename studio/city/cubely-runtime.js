import * as THREE from '../web/vendor/three.module.js';
import RAPIER from '@dimforge/rapier3d-compat';
import {GameEngine} from '@cubely/engine.ts';
import {DEFAULT_SETTINGS} from '@cubely/config.ts';
import {CharacterActor} from '@cubely/character-assets.ts';
import {configure,disposeHost} from './runtime-host.js';
import {GLTFLoader} from '../web/vendor/addons/loaders/GLTFLoader.js';

const matrix=a=>new THREE.Matrix4().set(...a.flat());
const rows=m=>Array.from({length:4},(_,r)=>Array.from({length:4},(_,c)=>m.elements[c*4+r]));
const toStudio=new THREE.Matrix4().makeRotationX(Math.PI/2).scale(new THREE.Vector3(1000,1000,1000));
const toWorld=toStudio.clone().invert();
const release=root=>{root.traverse(n=>{n.geometry?.dispose();for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){for(const v of Object.values(m))if(v?.isTexture)v.dispose();m.dispose();}});};

export async function create(host){
  configure(host);
  const runtime=new Runtime(host);
  try{await runtime.init();return runtime;}catch(error){runtime.dispose();throw error;}
}
class Runtime {
  constructor(host){this.host=host;this.records=new Map();this.applied=new Map();this.owned=new Map();this.running=false;this.disposed=false;this.last=performance.now();this.errors=[];this.rendererState={toneMapping:host.renderer.toneMapping,exposure:host.renderer.toneMappingExposure,shadows:host.renderer.shadowMap.enabled};}
  async init(){
    this.engine=await GameEngine.create(this.host.renderer.domElement,{...DEFAULT_SETTINGS,volume:0,quality:'low'},stats=>{this.stats=stats;},(done,total)=>this.host.progress?.(`人物 ${done}/${total}`),this.host);
    const e=this.engine;
    const until=performance.now()+90000;
    while(!e.living.ready){if(performance.now()>until)throw Error('城市场景初始化超时');await new Promise(r=>setTimeout(r,50));}
    e.setPaused(true);e.clearInput();
    this.scene=e.scene;this.camera=e.camera;this.camera.up.set(0,1,0);
    for(const item of e.living.instances){
      item.root.updateMatrixWorld(true);
      const norm=new THREE.Matrix4().makeScale(item.asset.scale,item.asset.scale,item.asset.scale);
      norm.setPosition(new THREE.Vector3().fromArray(item.asset.center).multiplyScalar(-item.asset.scale));
      const world=item.root.matrixWorld.clone().multiply(norm);
      const row={id:'facility_'+item.id,kind:'facility',name:item.asset.name,url:item.asset.url,matrix:rows(world),source_clip:item.asset.clip};
      this.records.set(row.id,{row,item,normalization:norm,base:item.root.matrix.clone(),interaction:new THREE.Vector3(item.ix,item.root.position.y,item.iz),asset:{...item.asset},activity:structuredClone(item.activity)});
      item.root.userData.cityInstance=row.id;
    }
    const choices=e.characters.manifest.models.filter((_,i)=>i!==e.characters.driverIndex);
    for(const p of e.crowd.people){
      const asset=p.actor?.asset??choices[p.scenic.character%choices.length];p.group.updateMatrixWorld(true);
      const norm=new THREE.Matrix4().makeScale(asset.scale,asset.scale,asset.scale);
      // CharacterActor grounds its cloned skin; raw GLBs retain their mesh
      // origin. Freeze the same foot-level convention for local editing.
      const template=e.characters.templates[e.characters.manifest.models.findIndex(a=>a.id===asset.id)].scene;
      template.updateMatrixWorld(true);template.traverse(n=>n.skeleton?.update());
      const floor=new THREE.Box3().setFromObject(template,true).min.y*asset.scale;
      if(!Number.isFinite(floor))throw Error('人物源坐标无法校准');
      norm.setPosition(0,-floor,0);
      const row={id:'person_'+p.id,kind:'person',name:`人物 ${p.id} · ${asset.id}`,url:asset.url,matrix:rows(p.group.matrixWorld.clone().multiply(norm)),bones:asset.bones,source_clip:asset.sourceClip};
      p.group.userData.cityInstance=row.id;
      this.records.set(row.id,{row,item:p,normalization:norm,base:p.group.matrix.clone(),asset:{...asset},route:new THREE.Vector3(p.targetX,p.group.position.y,p.targetZ)});
    }
    this.catalog=[...this.records.values()].map(r=>r.row);
    await this.host.register(this.catalog);
    this.overview();
    this.host.progress?.(`${this.catalog.length} 个人物与设施 · 城市已就绪`);
  }
  overview(){this.setRunning(false);this.target=this.engine.car.group.position.clone();this.camera.position.copy(this.target).add(new THREE.Vector3(45,65,-65));this.camera.lookAt(this.target);return this.target;}
  pick(ray){
    const roots=[...this.records.values()].map(r=>r.row.kind==='person'?r.item.group:r.item.root).filter(o=>o.visible);
    let obj=ray.intersectObjects(roots,true)[0]?.object;
    while(obj&&!obj.userData.cityInstance)obj=obj.parent;
    return obj?.userData.cityInstance;
  }
  async focus(id){
    this.setRunning(false);
    const r=this.records.get(id);if(!r)return;
    for(const record of this.records.values())record.item.studioPinned=record===r;
    let root;
    if(r.row.kind==='facility'){
      if(!r.item.model)await this.engine.living.load(r.item,this.engine.time+1000);
      if(!r.item.model)throw Error('设施模型未能载入');
      root=r.item.root;root.visible=true;
    }else{
      r.item.scenicActive=true;this.engine.crowd.updateVisibility(r.item.group.position);
      root=r.item.group;root.visible=true;
    }
    const box=new THREE.Box3().setFromObject(root),center=box.getCenter(new THREE.Vector3()),d=Math.max(2,box.getSize(new THREE.Vector3()).length());
    this.camera.position.copy(center).add(new THREE.Vector3(d*.8,d*.45,-d));this.camera.lookAt(center);
    this.target=center;this.host.invalidate();return center.toArray();
  }
  setRunning(value){this.running=!!value;this.engine.setPaused(!this.running);this.engine.clearInput();this.last=performance.now();this.host.invalidate();}
  input(code,value){if(!this.running)return;const key={KeyW:'w',KeyS:'s',KeyA:'a',KeyD:'d',Space:'horn'}[code];if(key)this.engine.setTouchInput({...this.engine.input,[key]:value});else if(value){if(code==='KeyE')this.engine.toggleDoor();if(code==='KeyF')this.engine.interact();if(code==='KeyC')this.engine.toggleCamera();if(code==='KeyR')this.engine.recover();}}
  setEditing(objects){for(const obj of objects){if(obj.city_link){const root=this.rootFor(obj.city_link.instance);if(root&&(!this.running||!obj.visible))root.visible=false;}}}
  frame(){
    const now=performance.now(),dt=Math.min(.05,(now-this.last)/1000);this.last=now;
    if(this.running)this.engine.studioStep(dt);
    else {
      this.engine.city.updateVisibility(this.camera.position.x,this.camera.position.z);
      this.engine.living.update(0,this.engine.time+now/1000,this.camera.position.x,this.camera.position.z,false);
      this.engine.crowd.updateVisibility(this.camera.position);
    }
    return this.running;
  }
  async update(objects,selection){
    const byInstance=new Map(objects.filter(o=>o.city_link).map(o=>[o.city_link.instance,o]));
    for(const [id,r] of this.records){
      const obj=byInstance.get(id),stamp=obj?JSON.stringify([obj.scene.asset,obj.transform,obj.visible]):'';
      r.item.studioPinned=!!obj&&selection.includes(obj.id);
      if(this.applied.get(id)===stamp)continue;
      // Undo removing a checkout restores its frozen source and placement.
      if(!obj&&!this.applied.has(id))continue;
      const desired=obj?toWorld.clone().multiply(matrix(obj.transform)).multiply(toStudio):matrix(r.row.matrix);
      const local=desired.clone().multiply(r.normalization.clone().invert());
      const delta=local.clone().multiply(r.base.clone().invert());
      let gltf;
      if(!obj||this.owned.get(id)?.asset!==obj.scene.asset){
        const raw=obj?await this.host.editorAsset(obj.scene.asset):await this.host.read('public'+r.row.url);
        gltf=await new GLTFLoader().parseAsync(raw,'');
        if(this.disposed){release(gltf.scene);return;}
      }
      if(r.row.kind==='person')this.person(r,obj,local,gltf);
      else await this.facility(r,obj,local,delta,gltf);
      this.applied.set(id,stamp);
      this.host.invalidate();
    }
  }
  person(r,obj,local,gltf){
    const p=r.item;
    let next;
    if(gltf)next=new CharacterActor(gltf,r.asset,this.engine.characters.generatedGaits);
    // Candidate construction may fail; no visible object is changed before it succeeds.
    if(next){
      p.actor?.model.removeFromParent();p.actor?.dispose();
      const old=this.owned.get(r.row.id);if(old)release(old.gltf.scene);
      p.actor=next;p.group.add(next.model);this.owned.set(r.row.id,{asset:obj?.scene.asset,gltf});
    }
    local.decompose(p.group.position,p.group.quaternion,p.group.scale);p.group.updateMatrixWorld(true);
    p.x=p.initialX=p.group.position.x;p.z=p.initialZ=p.group.position.z;
    const target=r.route.clone().applyMatrix4(local.clone().multiply(r.base.clone().invert()));
    p.targetX=target.x;p.targetZ=target.z;p.escape=undefined;p.social=undefined;p.state='daily';p.vx=p.vz=0;p.studioEdited=!!obj;
    for(const body of p.rag||[])this.engine.world.removeRigidBody(body);p.rag=[];p.body.setEnabled(true);
    if(p.scenic){p.scenic.x=p.x;p.scenic.z=p.z;p.scenic.targetX=target.x;p.scenic.targetZ=target.z;}
    p.body.setTranslation({x:p.x,y:p.group.position.y+1,z:p.z},true);p.body.setNextKinematicTranslation({x:p.x,y:p.group.position.y+1,z:p.z});
    const collider=p.body.collider(0);if(collider){const s=p.group.scale;collider.setShape(new RAPIER.Capsule(.48*Math.abs(s.y),.28*Math.max(Math.abs(s.x),Math.abs(s.z))));}
    p.group.visible=obj?.visible!==false;
    for(const child of p.group.children)child.visible=child===p.actor?.model;
  }
  async facility(r,obj,local,delta,gltf){
    const item=r.item,activity=structuredClone(r.activity);
    if(!local.equals(r.base))activity.cruise=undefined;
    // Use the city's own loader for clip corrections, cycling and passengers.
    const candidate={...item,activity,root:new THREE.Group(),model:undefined,mixer:undefined,action:undefined,passengers:undefined,contactNode:undefined,
      studioTemplate:gltf??item.studioTemplate};
    local.decompose(candidate.root.position,candidate.root.quaternion,candidate.root.scale);
    await this.engine.living.load(candidate,this.engine.time);
    if(this.disposed){candidate.mixer?.stopAllAction();candidate.passengers?.dispose();if(gltf)release(gltf.scene);return;}
    if(!candidate.model){if(gltf)release(gltf.scene);throw Error('设施候选无法绑定原行为；保留当前版本');}
    candidate.root.updateMatrixWorld(true);
    const box=new THREE.Box3().setFromObject(candidate.root),center=box.getCenter(new THREE.Vector3()),half=box.getSize(new THREE.Vector3()).multiplyScalar(.5);
    if(![...center,...half].every(Number.isFinite)||half.length()===0){candidate.mixer?.stopAllAction();candidate.passengers?.dispose();if(gltf)release(gltf.scene);throw Error('设施碰撞包络无效');}
    // Prepare the new collision before replacing any visible/runtime state.
    const oldObstacle=item.studioObstacle,city=this.engine.city,world=this.engine.world;
    const previous=oldObstacle?.obstacle;
    const sameBounds=previous&&[center.x-previous.x,center.z-previous.z,half.x-previous.hx,half.z-previous.hz,box.min.y-(previous.base||0),2*half.y-previous.height].every(v=>Math.abs(v)<1e-6);
    const collider=oldObstacle&&!sameBounds?world.createCollider(RAPIER.ColliderDesc.cuboid(Math.max(.05,half.x),Math.max(.05,half.y),Math.max(.05,half.z)).setTranslation(center.x,center.y,center.z)):null;
    item.mixer?.stopAllAction();item.model?.removeFromParent();
    item.passengers?.group.removeFromParent();item.passengers?.dispose();
    if(gltf){const old=this.owned.get(r.row.id);if(old)release(old.gltf.scene);this.owned.set(r.row.id,{asset:obj?.scene.asset,gltf});}
    for(const key of ['activity','model','mixer','action','passengers','contactNode','studioTemplate'])item[key]=candidate[key];
    item.root.position.copy(candidate.root.position);item.root.quaternion.copy(candidate.root.quaternion);item.root.scale.copy(candidate.root.scale);
    item.root.add(item.model);if(item.passengers)item.root.add(item.passengers.group);item.root.updateMatrixWorld(true);
    const interaction=r.interaction.clone().applyMatrix4(delta);item.x=item.root.position.x;item.z=item.root.position.z;item.ix=interaction.x;item.iz=interaction.z;
    item.marker.position.copy(interaction);item.marker.position.y+=.045;
    if(collider){
      world.removeCollider(oldObstacle.collider,true);
      // Keep array identity: CameraCollision and other readers retain this array.
      const i=city.obstacles.indexOf(oldObstacle.obstacle);if(i>=0)city.obstacles.splice(i,1);
      const obstacle={x:center.x,z:center.z,hx:half.x,hz:half.z,localHx:half.x,localHz:half.z,height:2*half.y,base:box.min.y,yaw:0};
      city.obstacles.push(obstacle);city.spatial.clear();
      for(const o of city.obstacles)for(let x=Math.floor((o.x-o.hx)/40);x<=Math.floor((o.x+o.hx)/40);x++)for(let z=Math.floor((o.z-o.hz)/40);z<=Math.floor((o.z+o.hz)/40);z++){const key=`${x}:${z}`;if(!city.spatial.has(key))city.spatial.set(key,[]);city.spatial.get(key).push(o);}
      item.studioObstacle={collider,obstacle};
      for(const p of this.engine.crowd.people){p.escape=undefined;p.replanAt=0;if(!city.clearPath(p.x,p.z,p.targetX,p.targetZ,.35)){p.targetX=p.x;p.targetZ=p.z;}}
      this.engine.summon?.cancel('场景已修改，请重新规划路线');
    }
    item.root.visible=obj?.visible!==false;
  }
  rootFor(id){const r=this.records.get(id);return r&&(r.row.kind==='person'?r.item.group:r.item.root);}
  metrics(){return {people:this.engine.crowd.people.length,facilities:this.engine.living.instances.length,colliders:this.engine.world.colliders.len(),drawCalls:this.host.renderer.info.render.calls,triangles:this.host.renderer.info.render.triangles,geometries:this.host.renderer.info.memory.geometries,textures:this.host.renderer.info.memory.textures,running:this.running};}
  dispose(){this.disposed=true;this.engine?.dispose();for(const item of this.owned.values())release(item.gltf.scene);this.owned.clear();const r=this.host.renderer;r.toneMapping=this.rendererState.toneMapping;r.toneMappingExposure=this.rendererState.exposure;r.shadowMap.enabled=this.rendererState.shadows;disposeHost();}
}
