// Copy the pinned Three.js codecs and embed their runtime data for offline use.
import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const source=path.join(root,'node_modules/three/examples/jsm');
const target=path.join(root,'studio/web/vendor/addons');
for(const name of ['loaders/DRACOLoader.js','loaders/KTX2Loader.js','utils/WorkerPool.js',
  'libs/ktx-parse.module.js','libs/zstddec.module.js','libs/meshopt_decoder.module.js','math/ColorSpaces.js']){
  await mkdir(path.dirname(path.join(target,name)),{recursive:true});
  await copyFile(path.join(source,name),path.join(target,name));
}
const entries={};
for(const [name,file] of Object.entries({
  'draco.js':'draco/gltf/draco_wasm_wrapper.js','draco.wasm':'draco/gltf/draco_decoder.wasm',
  'basis_transcoder.js':'basis/basis_transcoder.js','basis_transcoder.wasm':'basis/basis_transcoder.wasm'})){
  entries[name]=(await readFile(path.join(source,'libs',file))).toString('base64');
}
await writeFile(path.join(root,'studio/web/vendor/gltf-codec-data.js'),
  '// Generated from three@0.185.0; Draco / Basis Universal: Apache-2.0. See CODECS-NOTICES.txt.\nexport const codecData = '+JSON.stringify(entries)+';\n');
console.log('Built offline glTF codecs');
