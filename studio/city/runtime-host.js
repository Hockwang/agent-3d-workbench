import * as THREE from '../web/vendor/three.module.js';
let host;
const urls=new Set();
export const cityStorage=new Map();
cityStorage.getItem=k=>cityStorage.get(k)??null;
cityStorage.setItem=(k,v)=>cityStorage.set(k,String(v));
cityStorage.removeItem=k=>cityStorage.delete(k);
export function configure(value){host=value;cityStorage.clear();}
export function invalidate(){host?.invalidate?.();}
export function disposeHost(){for(const url of urls)URL.revokeObjectURL(url);urls.clear();host=null;cityStorage.clear();}
export async function readAsset(url){
  if(typeof url!=='string'||!url.startsWith('/')||url.startsWith('//')||url.includes('..')||url.startsWith('/api/'))throw Error('城市运行时仅访问导入包内资源');
  return host.read('public'+url);
}
export async function cityFetch(url,options={}){
  if(options.method&&options.method!=='GET')throw Error('城市外部生成服务未启用');
  try{return new Response(await readAsset(url),{status:200});}catch(error){host?.report?.(error.message);return new Response('',{status:404});}
}
export function cityTexture(url){
  const texture=new THREE.Texture();
  readAsset(url).then(raw=>new Promise((resolve,reject)=>{
    const blob=URL.createObjectURL(new Blob([raw]));urls.add(blob);
    const img=new Image();img.onload=()=>{texture.image=img;texture.needsUpdate=true;URL.revokeObjectURL(blob);urls.delete(blob);resolve();host?.invalidate?.();};
    img.onerror=()=>{URL.revokeObjectURL(blob);urls.delete(blob);reject(Error('城市贴图载入失败'));};img.src=blob;
  })).catch(e=>host?.report?.(e.message));return texture;
}
