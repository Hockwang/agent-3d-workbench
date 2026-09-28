import {build} from 'esbuild';
await build({entryPoints:['studio/motion-cli.mjs'],bundle:true,platform:'node',format:'cjs',target:'node20',outfile:'studio/app/dist/motion-cli.cjs',minify:true,legalComments:'inline'});
console.log('Built shared motion export worker');
