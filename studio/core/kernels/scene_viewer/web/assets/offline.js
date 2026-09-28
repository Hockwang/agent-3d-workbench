// Only the selected, hash-bound bundle is available to this sandboxed viewer.
const bundle = JSON.parse(document.getElementById('assembly-data').textContent);
const urls = new Map();
export function assetUrl(key) {
  if (urls.has(key)) return urls.get(key);
  const item = bundle.assets[key];
  if (!item) throw new Error(`未打包的资源：${key}`);
  const bytes = Uint8Array.from(atob(item.data), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: item.mime }));
  urls.set(key, url);
  return url;
}
export async function readResource(key) {
  const value = bundle.resources[key];
  if (!value) throw new Error(`未打包的场景：${key}`);
  return structuredClone(value);
}
addEventListener('pagehide', () => { for (const url of urls.values()) URL.revokeObjectURL(url); });
