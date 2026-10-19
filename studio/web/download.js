// Shared file delivery: MCP Apps ask the host; browser and Electron use their
// normal download manager. Never fall back to a blocked iframe anchor on error.
import {t} from './i18n.js';
export async function downloadFile(api, data, name, mime = 'application/octet-stream', reference) {
  const filename = String(name).split(/[\\/]/).pop() || 'download';
  if (api.downloadFile) {
    const result = await api.downloadFile(data, filename, mime, reference);
    if (result?.url && typeof document !== 'undefined') {
      const dialog=document.createElement('dialog'),title=document.createElement('h3'),text=document.createElement('p'),link=document.createElement('a'),close=document.createElement('button');
      dialog.className='download-receipt';dialog.setAttribute('aria-label',t('download.title'));
      title.textContent=filename;text.textContent=t('download.browserHint');
      link.href=result.url;link.target='_blank';link.rel='noopener';link.textContent=t('download.open');
      close.textContent=t('common.close');close.onclick=()=>dialog.close();
      dialog.append(title,text,link,close);dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();
    }
    return result;
  }
  const url = URL.createObjectURL(new Blob([data], { type: mime }));
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.append(link);
  try { link.click(); }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000); }
}

// Only existing, workspace-scoped APIs are used by the browser fallback page.
export async function readDownload(api, ref) {
  if (ref.kind === 'task') {
    const { task } = await api.tasks(ref.id);
    const artifact = task.artifacts.find(a => a.id === ref.artifact);
    if (!artifact) throw new Error('File not found');
    return { data: await api.taskAsset(task.id, artifact), name: artifact.name, mime: artifact.mime };
  }
  if (ref.kind === 'laser') {
    const result = await api.laser({ action:'artifact', id:ref.id, name:ref.artifact });
    return { data:Uint8Array.from(atob(result.base64), c=>c.charCodeAt(0)), name:result.name, mime:result.mime };
  }
  if (ref.kind === 'observation') {
    const report = await api.observe({ action:'read', id:ref.id, image:false, detail:true });
    return { data:JSON.stringify(report,null,2), name:'observation.json', mime:'application/json' };
  }
  throw new Error('Unsupported download');
}
