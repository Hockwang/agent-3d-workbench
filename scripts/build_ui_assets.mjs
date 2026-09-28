// Bundle only the UI primitives we use. No CDN or icon runtime in the viewer.
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
const root = new URL('../', import.meta.url);
const target = new URL('studio/web/vendor/ui/', root);
await mkdir(target, { recursive: true });
const pico = await readFile(new URL('node_modules/@picocss/pico/css/pico.min.css', root), 'utf8');
await writeFile(new URL('pico.css', target), `@layer pico {\n${pico}\n}`);
const names = ['clapperboard', 'box', 'layers', 'sliders-horizontal', 'wand-sparkles', 'scan-eye', 'printer', 'mouse-pointer-2', 'move', 'rotate-3d', 'scaling', 'maximize', 'undo-2', 'redo-2', 'save'];
const icons = {};
for (const name of names) {
  icons[name] = (await readFile(new URL(`node_modules/lucide-static/icons/${name}.svg`, root), 'utf8'))
    .replace(/<!--[^]*?-->/g, '').trim().replace('<svg', '<svg aria-hidden="true" focusable="false" class="ui-icon"');
}
await writeFile(new URL('icons.js', target), `// Generated from lucide-static; see LUCIDE-LICENSE.\nconst icons = ${JSON.stringify(icons)};\nexport const icon = name => icons[name] || '';\n`);
for (const weight of [400, 500, 600]) await copyFile(new URL(`node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-${weight}-normal.woff2`, root), new URL(`plex-${weight}.woff2`, target));
for (const [source, name] of [['@picocss/pico/LICENSE.md', 'PICO-LICENSE'], ['lucide-static/LICENSE', 'LUCIDE-LICENSE'], ['@fontsource/ibm-plex-sans/LICENSE', 'FONT-LICENSE']]) {
  await copyFile(new URL(`node_modules/${source}`, root), new URL(name, target));
}
console.log(`Bundled Pico CSS, ${names.length} Lucide icons and IBM Plex Sans locally`);
