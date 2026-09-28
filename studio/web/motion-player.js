import {MechanicalMotion,SkinMotion} from './motion-engine.js';
export class MotionPlayer {
  constructor(viewport,onTime,onError){this.viewport=viewport;this.onTime=onTime;this.onError=onError;this.time=0;this.playing=false;this.loop=true;this.active=false;this.skins=new Map();}
  setState(state){
    this.state=state;
    const stamp=JSON.stringify(state.objects.map(o=>[o.id,o.asset,o.transform,o.motion]));
    if(this.stamp===stamp)return; this.stamp=stamp;
    const assets=JSON.stringify(state.objects.map(o=>[o.id,o.scene?.asset||o.motion?.asset||o.asset]));
    if (this.assets && this.assets!==assets) { this.playing=false; this.time=0; }
    this.assets=assets;
    this.clearSkins();
    try{this.runtime=new MechanicalMotion(state.objects);this.duration=Math.max(0,...state.objects.map(o=>o.motion?.duration||0));this.time=Math.min(this.time,this.duration);this.error=null;}
    catch(error){this.runtime=null;this.playing=false;this.error=error;this.onError(error);}
    this.seek(this.time);
  }
  clearSkins(){for(const entry of this.skins.values())entry.runtime.dispose();this.skins.clear();}
  seek(time){this.time=Math.max(0,Math.min(this.duration||0,time));this.draw();this.onTime(this.time,this.duration||0,this.playing);this.viewport.loop.invalidate();}
  draw(){
    if(!this.active||!this.runtime||!this.state)return;
    try{
      this.runtime.seek(this.time);
      for(const obj of this.state.objects){
        const entry=this.viewport.entries.get(obj.id);if(!entry?.root||entry.loading||entry.failed)continue;
        if(['skin','gltf'].includes(obj.motion?.kind)){
          if(!entry.gltf||!entry.skin)continue;
          let skin=this.skins.get(obj.id);
          if(skin?.gltf!==entry.gltf){skin?.runtime.dispose();skin={gltf:entry.gltf,runtime:new SkinMotion(entry.gltf,obj.motion)};this.skins.set(obj.id,skin);}
          skin.runtime.seek(this.time);
        } else if (!entry.skin) { entry.root.matrix.copy(this.runtime.studioMatrix(obj));entry.root.matrix.decompose(entry.root.position,entry.root.quaternion,entry.root.scale);entry.root.updateMatrixWorld(true); }
      }
      this.viewport.helpers.forEach(h=>h.update?.());
    }catch(error){this.playing=false;this.runtime=null;this.error=error;this.onError(error);}
  }
  tick(){
    const now=performance.now();
    if(this.playing&&this.active){
      const elapsed=this.last?Math.min((now-this.last)/1000,.1):0;
      this.time+=elapsed;
      if(this.time>=this.duration){if(this.loop&&this.duration)this.time%=this.duration;else{this.time=this.duration;this.playing=false;}}
      this.draw();this.onTime(this.time,this.duration,this.playing);
    }
    this.last=now;return this.playing&&this.active;
  }
  play(){if(!this.runtime||!this.duration)return;this.playing=!this.playing;this.last=0;if(this.time>=this.duration)this.time=0;this.viewport.loop.invalidate();this.onTime(this.time,this.duration,this.playing);}
  setActive(value){this.active=value;if(!value){this.playing=false;this.clearSkins();}this.last=0;this.draw();}
  dispose(){this.clearSkins();this.playing=false;}
}
