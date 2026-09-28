import {LoadingManager} from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {DRACOLoader} from 'three/addons/loaders/DRACOLoader.js';
import {KTX2Loader} from 'three/addons/loaders/KTX2Loader.js';
import {codecData} from './vendor/gltf-codec-data.js';
import {t} from './i18n.js';

const meshopt = {
  supported: typeof WebAssembly === 'object',
  async decodeGltfBufferAsync(...args) {
    const {MeshoptDecoder} = await import('three/addons/libs/meshopt_decoder.module.js');
    await MeshoptDecoder.ready;
    return MeshoptDecoder.decodeGltfBufferAsync(...args);
  },
};

// One self-contained loader contract for the editor, generated assets and
// delivery pages. Workers and WASM are loaded only when a model needs them.
export function createGLTFLoader(renderer, manager) {
  manager ||= new LoadingManager().setURLModifier(url => {
    if (!/^(blob:|data:)/.test(url)) throw new Error(t('gltf.error.mustEmbedAssets'));
    return url;
  });
  const urls = new Map();
  const decoderManager = new LoadingManager().setURLModifier(url => {
    const name = url.replace('studio-codec:', '');
    if (!Object.hasOwn(codecData, name)) throw new Error(t('gltf.error.unknownCodecAsset'));
    if (!urls.has(name)) {
      const bytes = Uint8Array.from(atob(codecData[name]), c => c.charCodeAt(0));
      urls.set(name, URL.createObjectURL(new Blob([bytes], {type:name.endsWith('.wasm')?'application/wasm':'text/javascript'})));
    }
    return urls.get(name);
  });
  const draco = new DRACOLoader(decoderManager).setDecoderPath({js:'studio-codec:draco.js',wasm:'studio-codec:draco.wasm'}).setWorkerLimit(2);
  // Use the model manager for KTX texture data and the same allowlist for its
  // bundled transcoder; no CDN requests and no model-controlled code loading.
  const textureManager = new LoadingManager().setURLModifier(url =>
    url.startsWith('studio-codec:') ? decoderManager.resolveURL(url) : manager.resolveURL(url));
  const ktx2 = new KTX2Loader(textureManager).setTranscoderPath('studio-codec:').setWorkerLimit(2).detectSupport(renderer);
  const loader = new GLTFLoader(manager).setDRACOLoader(draco).setKTX2Loader(ktx2).setMeshoptDecoder(meshopt);
  loader.disposeCodecs = () => {draco.dispose();ktx2.dispose();for (const url of urls.values()) URL.revokeObjectURL(url);urls.clear();};
  return loader;
}
