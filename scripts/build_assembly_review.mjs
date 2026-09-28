import { build } from 'esbuild';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const base = path.join(root, 'studio/core/kernels/scene_viewer/web');
const result = await build({ entryPoints: [path.join(base, 'assets/viewer.js')], bundle: true, write: false, minify: true, format: 'iife', target: 'es2022',
  alias: { 'three/addons': path.join(root, 'studio/web/vendor/addons'), three: path.join(root, 'studio/web/vendor/three.module.js') } });
let html = await readFile(path.join(base, 'index.html'), 'utf8');
let css = await readFile(path.join(base, 'assets/viewer.css'), 'utf8') + '\n' + await readFile(path.join(root, 'studio/web/theme.css'), 'utf8') + '\n' + await readFile(path.join(base, 'assets/workbench.css'), 'utf8');
for (const weight of [400, 500, 600]) {
  const font = await readFile(path.join(root, `studio/web/vendor/ui/plex-${weight}.woff2`));
  css = css.replace(`./vendor/ui/plex-${weight}.woff2`, `data:font/woff2;base64,${font.toString('base64')}`);
}
html = html.replace(/<script type="importmap">[\s\S]*?<\/script>/, '')
  .replace('<link rel="stylesheet" href="assets/viewer.css" />', () => `<style>${css}</style>`)
  .replace('<script type="module" src="assets/viewer.js"></script>', () => `<script type="application/json" id="assembly-data">__ASSEMBLY_REVIEW_DATA__</script><script>${result.outputFiles[0].text.replaceAll('</script', '<\\/script')}</script>`);
await writeFile(path.join(root, 'studio/app/dist/assembly-review.html'), html);
console.log('Built offline assembly review template', Buffer.byteLength(html));
