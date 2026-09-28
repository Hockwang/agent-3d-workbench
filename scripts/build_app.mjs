import { build } from "esbuild";
import { readFile, mkdir, writeFile, rename, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Script } from "node:vm";
import {codecNotices} from './codec_notices.mjs';

const root = fileURLToPath(new URL("../", import.meta.url));
const result = await build({
  entryPoints: [path.join(root, "studio/app/main.js")], bundle: true, write: false,
  minify: true, format: "iife", target: "es2022", legalComments: "inline",
  // r185 loaders initialize default module-relative URLs. Our loader replaces
  // every decoder path with a bundled resource; this base is never fetched.
  define: {'import.meta.url': JSON.stringify('https://studio.invalid/bundled/module.js')},
  alias: {
    "three/addons": path.join(root, "studio/web/vendor/addons"),
    three: path.join(root, "studio/web/vendor/three.module.js"),
  },
});
let css = (await Promise.all(["studio/web/vendor/ui/pico.css", "studio/web/style.css", "studio/web/flow.css", "studio/web/editor.css", "studio/web/recipes.css", "studio/web/tasks.css", "studio/web/observe.css", "studio/app/style.css", "studio/web/theme.css", "studio/web/workbench.css", "studio/web/studio-layout.css", "studio/web/evaluation.css", "studio/web/motion.css"]
  .map((file) => readFile(path.join(root, file), "utf8")))).join("\n");
for (const weight of [400, 500, 600]) {
  const font = await readFile(path.join(root, `studio/web/vendor/ui/plex-${weight}.woff2`));
  css = css.replace(`./vendor/ui/plex-${weight}.woff2`, `data:font/woff2;base64,${font.toString('base64')}`);
}
const source = await readFile(path.join(root, "studio/web/index.html"), "utf8");
const workspace = source.slice(source.indexOf('<div id="wb">'), source.lastIndexOf('<script type="module"'));
if (!workspace.startsWith('<div id="wb">')) throw new Error("Shared workspace HTML missing");
const notices = await codecNotices(root);
const html = (await readFile(path.join(root, "studio/app/index.html"), "utf8"))
  .replace('</head>', () => (notices + '</head>'))
  .replace("<!-- WORKSPACE_HTML -->", () => workspace)
  .replace("/* APP_CSS */", () => css)
  .replace("/* APP_JS */", () => result.outputFiles[0].text.replaceAll("</script", "<\\/script"));
// String replacement values would expand JavaScript's $&, $` and $' sequences.
// Parse the actual inline artifact, not just the bundler output.
new Script(html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>")));
await mkdir(path.join(root, "studio/app/dist"), { recursive: true });
// A running MCP server may read during a rebuild. Never expose partial HTML.
const target = path.join(root, "studio/app/dist/studio.html");
const temporary = `${target}.${process.pid}.tmp`;
try {
  await writeFile(temporary, html);
  await rename(temporary, target);
} finally {
  await rm(temporary, { force: true });
}
console.log(`Built self-contained Print Prep app: ${Buffer.byteLength(html)} bytes`);
