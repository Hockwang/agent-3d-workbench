// Bounded chunks keep file selection usable through both HTTP and MCP Apps.
import { t } from './i18n.js';
export async function uploadFile(task, file, onProgress) {
  if (!file.size || file.size > 500 * 1024 * 1024) throw new Error(t('upload.error.fileSizeInvalid'));
  let upload_id, result;
  for (let offset = 0; offset < file.size; offset += 512 * 1024) {
    const bytes = new Uint8Array(await file.slice(offset, offset + 512 * 1024).arrayBuffer());
    let binary = '';
    for (let start = 0; start < bytes.length; start += 8192) binary += String.fromCharCode(...bytes.subarray(start, start + 8192));
    result = await task({ action: 'upload', name: file.name, size: file.size, offset, data_base64: btoa(binary), ...(upload_id ? { upload_id } : {}) });
    upload_id = result.upload_id; onProgress?.(result.received / file.size);
  }
  if (!result.complete || !result.path) throw new Error(t('upload.error.incompleteReceive'));
  return result;
}
