// One evaluator for the viewport, validation and baked export.
import * as THREE from 'three';
import jsep from './vendor/jsep.js';
import { KeyframeManager } from './vendor/motionforge/KeyframeManager.js';
import { t } from './i18n.js';

const functions = Object.fromEntries(['abs','ceil','floor','round','min','max','sqrt','pow','sin','cos','tan'].map(k => [k, Math[k]]));
const operators = { '+':(a,b)=>a+b, '-':(a,b)=>a-b, '*':(a,b)=>a*b, '/':(a,b)=>a/b, '%':(a,b)=>a%b, '**':(a,b)=>a**b };
const expressions = new Map();
export function evaluateFormula(source, params = {}) {
  if (typeof source !== 'string' || source.length > 512) throw Error(t('motionEngine.error.formulaTooLong'));
  let ast = expressions.get(source);
  if (!ast) { ast = jsep(source || '0'); if (expressions.size > 512) expressions.clear(); expressions.set(source, ast); }
  let count = 0;
  function visit(n) {
    if (++count > 128) throw Error(t('motionEngine.error.formulaTooComplex'));
    if (n.type === 'Literal' && typeof n.value === 'number') return n.value;
    if (n.type === 'Identifier' && n.name === 'PI') return Math.PI;
    if (n.type === 'Identifier' && Object.hasOwn(params, n.name) && typeof params[n.name] === 'number') return params[n.name];
    if (n.type === 'UnaryExpression' && ['+','-'].includes(n.operator)) return (n.operator === '-' ? -1 : 1) * visit(n.argument);
    if (n.type === 'BinaryExpression' && Object.hasOwn(operators, n.operator)) return operators[n.operator](visit(n.left), visit(n.right));
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && Object.hasOwn(functions, n.callee.name) && n.arguments.length <= 8) return functions[n.callee.name](...n.arguments.map(visit));
    throw Error(t('motionEngine.error.formulaDisallowed'));
  }
  const result = visit(ast); if (!Number.isFinite(result)) throw Error(t('motionEngine.error.formulaResultNotFinite')); return result;
}
class SafeManager extends KeyframeManager {
  evaluatePkfFormula(source, params) { try { return { value:evaluateFormula(source, params), error:null }; } catch(e) { return {value:0,error:e.message}; } }
}
const need = (ok, message) => { if (!ok) throw Error(message); };
const finite = value => typeof value === 'number' && Number.isFinite(value);
export const toGltf = new THREE.Matrix4().makeRotationX(-Math.PI / 2).premultiply(new THREE.Matrix4().makeScale(.001,.001,.001));
export const toStudio = toGltf.clone().invert();
export const objectMatrix = obj => new THREE.Matrix4().set(...obj.transform.flat());

export function validateMotion(motion) {
  need(motion && motion.schema === 'studio-motion/v1', t('motionEngine.error.unsupportedFormat'));
  need(['joint','skin','gltf'].includes(motion.kind), t('motionEngine.error.invalidKind'));
  need(finite(motion.duration) && motion.duration > 0 && motion.duration <= 120, t('motionEngine.error.invalidDuration'));
  need(Number.isInteger(motion.fps) && motion.fps >= 1 && motion.fps <= 60, t('motionEngine.error.invalidFps'));
  need(['pkf','keyframes','clip'].includes(motion.mode), t('motionEngine.error.invalidMode'));
  if (motion.blend_asset != null) need(/^[a-f0-9]{64}$/.test(motion.blend_asset), t('motionEngine.error.invalidBlendAsset'));
  if (motion.kind === 'joint') {
    need(motion.asset == null && motion.blend_asset == null, t('motionEngine.error.jointCannotReferenceAsset'));
    need(motion.mode !== 'clip', t('motionEngine.error.jointModeRestriction'));
    const j = motion.joint;
    need(j && ['revolute','prismatic','fixed'].includes(j.type) && ['x','y','z'].includes(j.axis), t('motionEngine.error.invalidJointTypeOrAxis'));
    need(j.parent == null || (typeof j.parent === 'string' && j.parent.length > 0), t('motionEngine.error.invalidParentId'));
    need(Array.isArray(j.origin) && j.origin.length === 3 && j.origin.every(finite), t('motionEngine.error.invalidOrigin'));
    need(Array.isArray(j.limits) && j.limits.length === 2 && j.limits.every(finite) && j.limits[0] <= j.limits[1], t('motionEngine.error.invalidJointLimits'));
  } else {
    need(/^[a-f0-9]{64}$/.test(motion.asset), t('motionEngine.error.missingSkeletonAsset'));
    need(Number.isInteger(motion.clip ?? 0) && (motion.clip ?? 0) >= 0, t('motionEngine.error.invalidClipIndex'));
    need(finite(motion.speed ?? 1) && (motion.speed ?? 1) > 0 && (motion.speed ?? 1) <= 4, t('motionEngine.error.invalidSpeed'));
    need(finite(motion.start ?? 0) && (motion.start ?? 0) >= 0, t('motionEngine.error.invalidStartTime'));
  }
  if (motion.kind === 'gltf') need(motion.mode === 'clip' && !motion.steps?.length && !motion.keyframes?.length, t('motionEngine.error.gltfUsesSourceClip'));
  const params = {};
  need(Array.isArray(motion.parameters) && motion.parameters.length <= 64, t('motionEngine.error.tooManyParameters'));
  for (const p of motion.parameters) {
    need(/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(p.id) && !Object.hasOwn(params,p.id) && !['__proto__','constructor','prototype','PI'].includes(p.id) && !Object.hasOwn(functions,p.id), t('motionEngine.error.invalidOrDuplicateParamName'));
    need(finite(p.default), t('motionEngine.error.paramMustBeFinite')); params[p.id] = p.default;
  }
  need(Array.isArray(motion.steps) && motion.steps.length <= 1000, t('motionEngine.error.tooManySteps'));
  const ids = new Set();
  for (const s of motion.steps) {
    need(typeof s.id === 'string' && s.id.length > 0 && !ids.has(s.id), t('motionEngine.error.stepIdMustBeUnique')); ids.add(s.id);
    need(finite(s.t_start) && finite(s.t_end) && s.t_start >= 0 && s.t_end > s.t_start && s.t_end <= motion.duration, t('motionEngine.error.stepTimeOutOfRange'));
    need(['linear','ease-in','ease-out','ease-in-out'].includes(s.easing), t('motionEngine.error.invalidEasing'));
    const values = [evaluateFormula(s.value_start,params),evaluateFormula(s.value_end,params)];
    if (motion.kind === 'joint') need(values.every(v => v >= motion.joint.limits[0] && v <= motion.joint.limits[1]), t('motionEngine.error.stepExceedsJointLimits'));
    else need(typeof s.bone === 'string' && s.bone && ['x','y','z'].includes(s.axis), t('motionEngine.error.boneStepNeedsBoneAxis'));
  }
  need(Array.isArray(motion.keyframes) && motion.keyframes.length <= 7201, t('motionEngine.error.invalidKeyframesArray'));
  let last = -1;
  for (const k of motion.keyframes) {
    need(finite(k.time) && finite(k.value) && k.time - last >= .0001 && k.time >= 0 && k.time <= motion.duration, t('motionEngine.error.keyframesMustIncrease')); last = k.time;
    if (motion.kind === 'joint') need(k.value >= motion.joint.limits[0] && k.value <= motion.joint.limits[1], t('motionEngine.error.keyframeExceedsJointLimits'));
  }
  need(motion.kind !== 'skin' || motion.mode !== 'keyframes', t('motionEngine.error.skinModeRestriction'));
  return motion;
}

export function validateScene(objects) {
  const byId = new Map(objects.map(o => [o.id,o]));
  for (const obj of objects) {
    if (!obj.motion) continue;
    validateMotion(obj.motion);
    if (obj.motion.bound_asset) need(obj.motion.bound_asset === obj.asset, t('motionEngine.error.geometryChanged'));
    if (obj.motion.kind === 'joint' && obj.motion.bound_transform) need(JSON.stringify(obj.motion.bound_transform) === JSON.stringify(obj.transform), t('motionEngine.error.restTransformChanged'));
    for (const [id,binding] of Object.entries(obj.motion.bindings || {})) {
      const dependency = byId.get(id); need(dependency && binding.asset === dependency.asset && JSON.stringify(binding.transform) === JSON.stringify(dependency.transform), t('motionEngine.error.parentGeometryOrRestChanged'));
    }
    let current = obj, seen = new Set();
    while (current?.motion?.kind === 'joint') {
      need(!seen.has(current.id), t('motionEngine.error.jointCycle')); seen.add(current.id);
      const id = current.motion.joint.parent;
      if (!id) break;
      need(byId.has(id), t('motionEngine.error.parentJointMissing')); current = byId.get(id);
    }
  }
}

export function trackEvaluator(motion) {
  validateMotion(motion);
  const manager = new SafeManager();
  for (const p of motion.parameters) manager.addPkfParameter({...p,type:'number'});
  for (const step of motion.steps) manager.addPkfStep({...step, joint_def_id:motion.kind === 'skin' ? `${step.bone}/${step.axis}` : 'value'});
  if (motion.mode === 'keyframes') for (const k of motion.keyframes) {
    manager.setJointDef('value',{type:'revolute',currentValue:k.value}); manager.addKeyframe(k.time);
  }
  return time => {
    const values = {};
    if (motion.mode === 'keyframes') {
      manager.evaluateAllAt(time); values.value = manager.getJointDef('value')?.currentValue || 0;
    } else for (const result of manager.evaluatePkfAt(time)) {
      if (result.error) throw Error(result.error); values[result.joint_def_id] = result.value;
    }
    return values;
  };
}

export class MechanicalMotion {
  constructor(objects) {
    validateScene(objects); this.root = new THREE.Group(); this.nodes = new Map(); this.rest = new Map(); this.evaluators = new Map(); this.manager = new SafeManager();
    for (const obj of objects) {
      const node = new THREE.Object3D(); node.name = obj.id;
      toGltf.clone().multiply(objectMatrix(obj)).decompose(node.position,node.quaternion,node.scale);
      // A kinematic frame has metre units and no mesh scaling. Keep the full
      // mesh rest matrix outside FK; applying its delta preserves scale/shear.
      node.scale.setScalar(1); node.updateMatrix(); this.rest.set(obj.id,node.matrix.clone());
      this.root.add(node); this.nodes.set(obj.id,node);
      if (obj.motion?.kind === 'joint') this.evaluators.set(obj.id,trackEvaluator(obj.motion));
    }
    this.root.updateMatrixWorld(true);
    for (const obj of objects) if (obj.motion?.kind === 'joint') {
      const j = obj.motion.joint, node = this.nodes.get(obj.id);
      this.manager.setJointDef(node.uuid,{name:obj.id,type:j.type,axis:j.axis,origin:{x:j.origin[0],y:j.origin[1],z:j.origin[2]},limits:{min:j.limits[0],max:j.limits[1]},parentId:this.nodes.get(j.parent)?.uuid || null,currentValue:0});
    }
    this.manager.applyAllJointDrives(this.root);
  }
  delta(id) { return this.nodes.get(id).matrixWorld.clone().multiply(this.rest.get(id).clone().invert()); }
  studioMatrix(obj) { return toStudio.clone().multiply(this.delta(obj.id)).multiply(toGltf).multiply(objectMatrix(obj)); }
  seek(time) {
    for (const [id, evaluate] of this.evaluators) this.manager.setJointValue(this.nodes.get(id).uuid,evaluate(time).value || 0);
    this.manager.applyAllJointDrives(this.root); this.root.updateMatrixWorld(true);
    return this.nodes;
  }
}

export function defaultMotion() {
  return {schema:'studio-motion/v1',kind:'joint',duration:4,fps:30,mode:'pkf',joint:{type:'revolute',axis:'z',origin:[0,0,0],parent:null,limits:[-180,180]},
    parameters:[{id:'amplitude',default:45,unit:'deg',desc:t('motionEngine.defaultMotion.amplitudeDesc')}],steps:[{id:'move',t_start:0,t_end:2,value_start:'0',value_end:'amplitude',easing:'ease-in-out'},{id:'return',t_start:2,t_end:4,value_start:'amplitude',value_end:'0',easing:'ease-in-out'}],keyframes:[]};
}

// Bone channels use the original glTF node name and local XYZ axes, in degrees.
// The imported scene and animations are retained; seeking never edits the asset.
export class SkinMotion {
  constructor(gltf, motion) {
    validateMotion(motion); this.gltf = gltf; this.motion = motion;
    this.rest = new Map(); this.names = new Map(); this.evaluate = trackEvaluator(motion);
    gltf.scene.traverse(node => {
      this.rest.set(node, {p:node.position.clone(),q:node.quaternion.clone(),s:node.scale.clone()});
      const originalName = gltf.parser?.json?.nodes?.[gltf.parser.associations.get(node)?.nodes]?.name;
      const name = originalName || node.name;
      if (name) { const list = this.names.get(name) || []; list.push(node); this.names.set(name,list); }
    });
    for (const step of motion.steps) need(this.names.get(step.bone)?.length === 1, t('motionEngine.error.boneMissingOrDuplicate', { bone: step.bone }));
    if (motion.mode === 'clip') {
      const clip = gltf.animations[motion.clip || 0]; need(clip, t('motionEngine.error.clipNotFound'));
      need((motion.start || 0) + motion.duration * (motion.speed || 1) <= clip.duration + 1e-4, t('motionEngine.error.editDurationExceedsClip'));
      this.mixer = new THREE.AnimationMixer(gltf.scene);
      this.action = this.mixer.clipAction(clip); this.action.setLoop(THREE.LoopOnce,1); this.action.clampWhenFinished = true; this.action.play();
    }
  }
  seek(time) {
    for (const [node,rest] of this.rest) { node.position.copy(rest.p); node.quaternion.copy(rest.q); node.scale.copy(rest.s); }
    if (this.mixer) { this.action.reset().play(); this.mixer.setTime((this.motion.start || 0) + Math.max(0,Math.min(this.motion.duration,time)) * (this.motion.speed || 1)); }
    else {
      const rotations = new Map();
      for (const [key,value] of Object.entries(this.evaluate(time))) {
        const slash = key.lastIndexOf('/'), name = key.slice(0,slash), axis = key.slice(slash+1);
        const angles = rotations.get(name) || {x:0,y:0,z:0}; angles[axis] = value * Math.PI / 180; rotations.set(name,angles);
      }
      for (const [name,a] of rotations) this.names.get(name)[0].quaternion.multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(a.x,a.y,a.z,'XYZ')));
    }
    this.gltf.scene.updateMatrixWorld(true);
  }
  dispose() {
    this.mixer?.stopAllAction(); this.mixer?.uncacheRoot(this.gltf.scene);
    for (const [node, rest] of this.rest) { node.position.copy(rest.p); node.quaternion.copy(rest.q); node.scale.copy(rest.s); }
    this.gltf.scene.updateMatrixWorld(true);
  }
}
