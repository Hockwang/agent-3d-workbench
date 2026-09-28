import {GLTFLoader as Loader} from '../web/vendor/addons/loaders/GLTFLoader.js';
import {readAsset,invalidate} from './runtime-host.js';
export class GLTFLoader extends Loader {
  async loadAsync(url){const gltf=await this.parseAsync(await readAsset(url),'');invalidate();return gltf;}
}
