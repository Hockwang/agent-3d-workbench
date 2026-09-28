// Bundled local worker: the browser and export use motion-engine.js verbatim.
import fs from 'node:fs/promises';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MechanicalMotion, SkinMotion, validateScene, toGltf, toStudio, objectMatrix, trackEvaluator } from './web/motion-engine.js';
import { ResultPackageExporter } from './web/vendor/motionforge/ResultPackageExporter.js';

function unpack(raw) {
  const bytes = Buffer.from(raw), length = bytes.readUInt32LE(12);
  const doc = JSON.parse(bytes.subarray(20,20+length).toString());
  const offset = 20+length; const bin = offset+8 <= bytes.length ? bytes.subarray(offset+8,offset+8+bytes.readUInt32LE(offset)) : Buffer.alloc(0);
  return {doc,bin};
}
function pack(doc,bin) {
  const json = Buffer.from(JSON.stringify(doc)); const j=Buffer.alloc(Math.ceil(json.length/4)*4,32); json.copy(j);
  const b=Buffer.alloc(Math.ceil(bin.length/4)*4); bin.copy(b);
  const raw=Buffer.alloc(12+8+j.length+8+b.length); raw.write('glTF');raw.writeUInt32LE(2,4);raw.writeUInt32LE(raw.length,8);
  raw.writeUInt32LE(j.length,12);raw.write('JSON',16);j.copy(raw,20);const i=20+j.length;raw.writeUInt32LE(b.length,i);raw.writeUInt32LE(0x004e4942,i+4);b.copy(raw,i+8);return raw;
}
function addAnimation(doc,bin,times,channels) {
  let chunks=[bin,Buffer.alloc((4-bin.length%4)%4)], size=chunks.reduce((n,b)=>n+b.length,0);
  doc.bufferViews ||= []; doc.accessors ||= [];
  const append=(array,type)=>{
    const bytes=Buffer.from(new Float32Array(array).buffer), view=doc.bufferViews.length;
    doc.bufferViews.push({buffer:0,byteOffset:size,byteLength:bytes.length});chunks.push(bytes);size+=bytes.length;
    const i=doc.accessors.length; const a={bufferView:view,componentType:5126,count:array.length/({SCALAR:1,VEC3:3,VEC4:4}[type]),type};
    if(type==='SCALAR'){a.min=[Math.min(...array)];a.max=[Math.max(...array)];}doc.accessors.push(a);return i;
  };
  const input=append(times,'SCALAR'), animation={name:'Studio motion',samplers:[],channels:[]};
  for(const c of channels){ const sampler=animation.samplers.length;animation.samplers.push({input,output:append(c.values,c.path==='rotation'?'VEC4':'VEC3'),interpolation:'LINEAR'});animation.channels.push({sampler,target:{node:c.node,path:c.path}});delete doc.nodes[c.node].matrix; }
  doc.animations=[animation];doc.buffers=[{byteLength:size}];return pack(doc,Buffer.concat(chunks));
}
function sampleTimes(duration,fps){const n=Math.ceil(duration*fps);return Array.from({length:n+1},(_,i)=>Math.min(i/fps,duration));}
async function exportGlb(request) {
  const raw=await fs.readFile(request.model),{doc,bin}=unpack(raw), objects=request.objects, duration=Math.max(...objects.filter(o=>o.motion).map(o=>o.motion.duration)), fps=request.fps || Math.max(...objects.filter(o=>o.motion).map(o=>o.motion.fps));
  const times=sampleTimes(duration,fps), channels=[];
  if(times.length * (objects.some(o=>['skin','gltf'].includes(o.motion?.kind)) ? doc.nodes.length : objects.length) > 500000) throw Error('烘焙采样量过大，请缩短片段、降低帧率或分对象导出');
  const addNode=(index)=>{const list=['translation','rotation','scale'].map(path=>({node:index,path,values:[]}));channels.push(...list);return (node)=>{list[0].values.push(...node.position.toArray());list[1].values.push(...node.quaternion.toArray());list[2].values.push(...node.scale.toArray());};};
  if(objects.some(o=>['skin','gltf'].includes(o.motion?.kind))) {
    if(objects.length!==1)throw Error('骨骼 GLB 导出请选择单个 rig；多对象请导出完整运动工程');
    // Parse only hierarchy and animation; render/export retains the untouched
    // original geometry, materials, skins and buffers from the source GLB.
    const lite=structuredClone(doc); delete lite.images;delete lite.textures;delete lite.materials;delete lite.meshes;delete lite.skins;
    for(const n of lite.nodes){delete n.mesh;delete n.skin;} delete lite.extensionsRequired;
    const packed=pack(lite,bin), gltf=await new GLTFLoader().parseAsync(packed.buffer.slice(packed.byteOffset,packed.byteOffset+packed.byteLength),'');
    const rig=new SkinMotion(gltf,objects[0].motion), targets=[];
    gltf.scene.traverse(node=>{const index=gltf.parser.associations.get(node)?.nodes;if(index!==undefined) targets.push([node,addNode(index)]);});
    for(const t of times){rig.seek(t);for(const [node,add] of targets)add(node);}rig.dispose();
    // Preserve the Studio placement while the raw rig stays in standard glTF.
    const matrix=toGltf.clone().multiply(objectMatrix(objects[0])).multiply(toStudio);
    const root=doc.nodes.length;doc.nodes.push({name:objects[0].id,matrix:matrix.toArray(),children:doc.scenes[doc.scene||0].nodes});doc.scenes[doc.scene||0].nodes=[root];
  } else {
    const runtime=new MechanicalMotion(objects), temp=new THREE.Object3D(), targets=[];
    for(const obj of objects){ const index=doc.nodes.findIndex(n=>n.name===obj.id);if(index<0)throw Error('导出模型对象身份不一致'); const n=doc.nodes[index],base=new THREE.Matrix4();if(n.matrix)base.fromArray(n.matrix);else base.compose(new THREE.Vector3(...(n.translation||[0,0,0])),new THREE.Quaternion(...(n.rotation||[0,0,0,1])),new THREE.Vector3(...(n.scale||[1,1,1])));targets.push([obj,index,base,addNode(index)]);}
    for(const t of times){runtime.seek(t);for(const [obj,index,base,add] of targets){runtime.delta(obj.id).multiply(base).decompose(temp.position,temp.quaternion,temp.scale);add(temp);}}
  }
  const output=addAnimation(doc,bin,times,channels);await fs.writeFile(request.output,output,{flag:'wx'});return {frames:times.length,fps,duration,channels:channels.length};
}
async function exportPackage(request){
  const objects=request.objects, runtime=new MechanicalMotion(objects);
  const parameters=[],steps=[], duration=Math.max(...objects.filter(o=>o.motion).map(o=>o.motion.duration));
  const times=new Set([0,duration]);
  for(const obj of objects){const m=obj.motion;if(!m)continue;const prefix='p_'+obj.id+'_', names=new Set(m.parameters.map(p=>p.id));
    parameters.push(...m.parameters.map(p=>({...p,id:prefix+p.id})));
    const rewrite=s=>s.replace(/[a-zA-Z_][a-zA-Z0-9_]*/g,word=>names.has(word)?prefix+word:word);
    if(m.mode==='pkf')steps.push(...m.steps.map(s=>({...s,id:obj.id+'_'+s.id,joint:obj.id,channel:m.joint.type==='revolute'?'rotate':'translate',axis:m.joint.axis,value_start:rewrite(s.value_start),value_end:rewrite(s.value_end)})));
    if(m.mode==='keyframes' && m.keyframes.length) {
      const keys=m.keyframes; const intervals=[];
      if(keys[0].time>0) intervals.push([{time:0,value:keys[0].value},keys[0]]);
      for(let i=0;i<keys.length-1;i++)intervals.push([keys[i],keys[i+1]]);
      if(keys.at(-1).time<m.duration)intervals.push([keys.at(-1),{time:m.duration,value:keys.at(-1).value}]);
      intervals.forEach(([a,b],i)=>steps.push({id:obj.id+'_key_'+i,joint:obj.id,channel:m.joint.type==='revolute'?'rotate':'translate',axis:m.joint.axis,t_start:a.time,t_end:b.time,value_start:String(a.value),value_end:String(b.value),easing:'linear'}));
    }
    for(const k of m.keyframes)times.add(k.time);
  }
  const evaluators=objects.filter(o=>o.motion).map(o=>[o.id,trackEvaluator(o.motion)]);
  const keyframes=sampleTimes(duration,request.fps||Math.max(...objects.filter(o=>o.motion).map(o=>o.motion.fps))).map(t=>({t,joint_values:Object.fromEntries(evaluators.map(([id,fn])=>[id,fn(t).value||0]))}));
  const definitions=runtime.manager.getAllJointDefs().map(d=>({...d,id:d.name,childId:d.name,parentId:runtime.root.getObjectByProperty('uuid',d.parentId)?.name||null,parentName:runtime.root.getObjectByProperty('uuid',d.parentId)?.name||null}));
  const model=await fs.readFile(request.model);
  class Exporter extends ResultPackageExporter{async serializeSceneToGlb(){return model;}downloadBlob(blob){this.blob=blob;}}
  const exporter=new Exporter();await exporter.exportZip({sourceFileName:'studio.glb',sourceFormat:'glb',sceneRoot:runtime.root,jointDefinitions:definitions,clips:[{clip_name:'Studio motion',duration,keyframes,reparent_events:[]}],pkfParameters:parameters,pkfSteps:steps,fps:request.fps||Math.max(...objects.filter(o=>o.motion).map(o=>o.motion.fps)),editorName:'3D Studio / MotionForge adapter'});
  await fs.writeFile(request.output,Buffer.from(await exporter.blob.arrayBuffer()),{flag:'wx'});return {duration,joints:definitions.length};
}
async function main(){
  const request=JSON.parse(await fs.readFile(process.argv[2],'utf8'));validateScene(request.objects);
  if(request.action==='validate'){const runtime=new MechanicalMotion(request.objects);return {valid:true,rest:Object.fromEntries([...runtime.rest].map(([id,m])=>[id,m.toArray()]))};}
  if(request.action==='glb')return exportGlb(request);
  if(request.action==='package')return exportPackage(request);
  throw Error('未知动作工作进程指令');
}
main().then(result=>process.stdout.write(JSON.stringify({ok:true,...result}))).catch(error=>{process.stderr.write(error.message);process.exitCode=1;});
