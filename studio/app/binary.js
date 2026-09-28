// MCP transports binary resources as base64. Avoid per-byte callbacks over a
// whole model: that can monopolize the UI thread for seconds on large meshes.
export async function decodeBase64(text, yieldControl = () => new Promise(resolve => setTimeout(resolve, 0))) {
  const padding = text.endsWith("==") ? 2 : text.endsWith("=") ? 1 : 0;
  const bytes = new Uint8Array(text.length / 4 * 3 - padding);
  const chunkSize = 1024 * 1024; // divisible by 4: every slice is valid base64
  let offset = 0;
  for (let start = 0; start < text.length; start += chunkSize) {
    const chunk = text.slice(start, start + chunkSize);
    if (typeof Uint8Array.fromBase64 === "function") {
      const decoded = Uint8Array.fromBase64(chunk);
      bytes.set(decoded, offset); offset += decoded.length;
    } else {
      const decoded = atob(chunk);
      for (let i = 0; i < decoded.length; i++) bytes[offset++] = decoded.charCodeAt(i);
    }
    if (start + chunkSize < text.length) await yieldControl();
  }
  return bytes.buffer;
}
