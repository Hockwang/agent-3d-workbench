import {createApi} from './api.js';
import {downloadFile,readDownload} from './download.js';
import {t} from './i18n.js';
const params=new URLSearchParams(location.search),api=createApi(),status=document.getElementById('status'),save=document.getElementById('save');
document.querySelector('h1').textContent=t('download.title');
save.textContent=t('download.retry');
const back=document.getElementById('back');back.textContent=t('download.back');
back.href='/?'+new URLSearchParams({workspace:params.get('workspace')||'',mode:params.get('kind')==='laser'?'laser':'tasks'});
let file;
async function prepare(){
  save.disabled=true;status.textContent=t('download.loading');
  try{
    if(!params.get('workspace')||!params.get('id'))throw new Error(t('download.invalid'));
    await api.init();
    file ||= await readDownload(api,{kind:params.get('kind'),id:params.get('id'),artifact:params.get('artifact')});
    document.getElementById('filename').textContent=file.name.split(/[\\/]/).pop();
    status.textContent=t('download.ready');
  }catch(error){status.textContent=error.message;}
  finally{save.disabled=false;}
}
save.onclick=async()=>{
  if(!file){await prepare();return;}
  try{await downloadFile(api,file.data,file.name,file.mime);status.textContent=t('download.sent');}
  catch(error){status.textContent=error.message;}
};
prepare();
