// Frozen delivery pages can contain an older optional-storage feature probe.
// Make denied storage unavailable, without granting same-origin privileges or
// changing the saved artifact. New pages also guard the getter in i18n.js.
export function sandboxedHtml(html) {
  const compatibility = '<script>try{void window.localStorage}catch{try{Object.defineProperty(window,"localStorage",{value:undefined,configurable:true})}catch{}}</script>';
  return /<head\b[^>]*>/i.test(html)
    ? html.replace(/<head\b[^>]*>/i, head => head + compatibility)
    : compatibility + html;
}
