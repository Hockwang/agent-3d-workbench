import {readFile} from 'node:fs/promises';
import path from 'node:path';
export async function codecNotices(root) {
  const files={};
  for (const name of ['CODECS-NOTICES.txt','THREE-LICENSE.txt','DRACO-LICENSE.txt','BASIS-LICENSE.txt',
    'MESHOPT-LICENSE.txt','KTX-PARSE-LICENSE.txt','ZSTDDEC-LICENSE.txt']) {
    files[name]=await readFile(path.join(root,'studio/web/vendor',name),'utf8');
  }
  // Keep complete notices inside standalone exported HTML, not just the repo.
  return '<script type="application/json" id="gltf-codec-licenses">'+JSON.stringify(files).replaceAll('<','\\u003c')+'</script>';
}
