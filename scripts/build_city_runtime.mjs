// Build only the supported user-supplied Cubely source. Never run its npm scripts.
import {build} from 'esbuild';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url)),source=path.resolve(process.argv[2]),output=process.argv[3];
const host=path.join(root,'studio/city/runtime-host.js');
const sharedThree=Object.keys(await import(path.join(root,'studio/web/vendor/three.module.js')));
function once(text,from,to){if(!text.includes(from))throw Error('Cubely source contract changed: '+from.slice(0,100));return text.replace(from,to);}
function adapt(text,name){
  if(name==='engine.ts'){
    text=once(text,'export class GameEngine {','export class GameEngine {\n studioHost:any;\n studioStep(dt:number){this.filmDelta=dt;this.frame();this.filmDelta=undefined;}');
    text=once(text,'progress?: (done: number, total: number) => void,','progress?: (done: number, total: number) => void, host?:any,');
    text=once(text,'car,{scene,world,city});','car,{scene,world,city,host});');
    text=once(text,'prepared:{scene:THREE.Scene;world:RAPIER.World;city:City},','prepared:{scene:THREE.Scene;world:RAPIER.World;city:City;host?:any},');
    text=once(text,'this.scene=prepared.scene;','this.studioHost=prepared.host;this.scene=prepared.scene;');
    text=once(text,'this.renderer = new THREE.WebGLRenderer({','this.renderer = prepared.host?.renderer ?? new THREE.WebGLRenderer({');
    text=once(text,'this.resizeObserver.observe(canvas);','if(!this.studioHost)this.resizeObserver.observe(canvas);');
    text=once(text,'private bind() {','private bind() { if(this.studioHost)return;');
    text=text.replaceAll('this.raf = requestAnimationFrame(this.frame);','if(!this.studioHost)this.raf = requestAnimationFrame(this.frame);');
    text=text.replaceAll('this.renderer.render(this.scene, this.camera);','if(!this.studioHost)this.renderer.render(this.scene, this.camera);');
    text=once(text,'this.firstPerson &&\n','!this.studioHost && this.firstPerson &&\n');
    text=once(text,'this.renderer.dispose();','if(!this.studioHost)this.renderer.dispose();');
    text=once(text,'private resize() {','private resize() { if(this.studioHost)return;');
    text=once(text,'updateDisplayQuality() {','updateDisplayQuality() {if(this.studioHost)return;');
  }
  if(name==='living-city.ts'){
    text=once(text,'let gltf = this.templates.get(item.asset.id);','let gltf = (item as any).studioTemplate ?? this.templates.get(item.asset.id);');
    text=once(text,'const viewDistance=(item:Instance)=>','const viewDistance=(item:Instance)=>(item as any).studioPinned?0:');
    // Keep independent obstacle ownership for movable facilities.
    text=once(text,'if (!activity.water)\n        this.city.addInteractiveObstacle(','const studioObstacle = !activity.water ? this.city.addInteractiveObstacle(');
    text=once(text,'asset.dimensions[1],\n        );','asset.dimensions[1],\n        ) : undefined;');
    text=once(text,'this.instances.push({\n        id,','this.instances.push({\n        studioObstacle,\n        id,');
  }
  if(name==='hangzhou-city.ts'){
    text=once(text,'this.obstacle(world, x, z, radius, radius, height);',`const batches=this.staticColliders;this.staticColliders=undefined;
      const collider=this.obstacle(world, x, z, radius, radius, height);
      this.staticColliders=batches;return {collider,obstacle:this.obstacles[this.obstacles.length-1]};`);
    text=once(text,'    world.createCollider(\n      RAPIER.ColliderDesc.cuboid(localHx','    return world.createCollider(\n      RAPIER.ColliderDesc.cuboid(localHx');
  }
  if(name==='pedestrians.ts'){
    text=text.replace('if(!p.scenicActive){p.group.visible=false;','if(!p.scenicActive&&!(p as any).studioPinned&&!(p as any).studioEdited){p.group.visible=false;');
    text=once(text,"if(p.scenic&&!p.scenicActive&&p.state!=='hit'){","if(p.scenic&&!p.scenicActive&&p.state!=='hit'&&!(p as any).studioPinned){");
    text=once(text,'const viewDistance=Math.hypot(p.x-focus.x,p.z-focus.z);','const viewDistance=(p as any).studioPinned?0:Math.hypot(p.x-focus.x,p.z-focus.z);');
  }
  // Keep the runtime offline and scoped to this imported package. Storage is
  // per-preview memory; game progress cannot leak between Codex tasks.
  text=text.replace(/\bfetch\b/g,'cityFetch').replace(/\blocalStorage\b/g,'cityStorage')
    .replaceAll('new THREE.TextureLoader().load(', 'cityTexture(');
  return `import {cityFetch,cityStorage,cityTexture} from ${JSON.stringify(host)};\n`+text;
}
await build({entryPoints:[path.join(root,'studio/city/cubely-runtime.js')],outfile:output,bundle:true,format:'iife',globalName:'StudioCubelyRuntime',minify:true,target:'es2022',legalComments:'inline',
  define:{'import.meta.env':JSON.stringify({DEV:false,BASE_URL:'/'}),'import.meta.url':JSON.stringify('https://studio.invalid/city-runtime.js'),'indexedDB':'undefined'},
  alias:{'@cubely':path.join(source,'lib/sim'),'@dimforge/rapier3d-compat':path.join(source,'node_modules/@dimforge/rapier3d-compat/rapier.mjs'),
    three:path.join(root,'studio/web/vendor/three.module.js'),'three/addons':path.join(root,'studio/web/vendor/addons'),'three/examples/jsm':path.join(root,'studio/web/vendor/addons')},
  plugins:[{name:'cubely-studio-contract',setup(b){
    b.onResolve({filter:/(^three$|three\.(module|core)\.js$)/},()=>({path:'shared-three',namespace:'studio-host'}));
    b.onLoad({filter:/.*/,namespace:'studio-host'},()=>({contents:`const T=globalThis.__StudioCityTHREE;if(!T)throw Error('城市需要 Studio 渲染宿主');`+sharedThree.map(k=>`export const ${k}=T.${k};`).join('\n'),loader:'js'}));
    b.onResolve({filter:/^three\/(addons|examples\/jsm)\/loaders\/GLTFLoader\.js$/},()=>({path:path.join(root,'studio/city/gltf-loader.js')}));
    b.onLoad({filter:/\.ts$/},async args=>{
      if(!args.path.startsWith(source+path.sep))return;
      const text=(await readFile(args.path,'utf8')).replaceAll('\r\n','\n');
      return {contents:adapt(text,path.basename(args.path)),loader:'ts',resolveDir:path.dirname(args.path)};
    });
  }}]});
console.log('Built Cubely adapter from frozen source');
