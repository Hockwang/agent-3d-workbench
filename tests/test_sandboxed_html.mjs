import test from 'node:test';
import assert from 'node:assert/strict';
import { runInNewContext } from 'node:vm';
import { sandboxedHtml } from '../studio/web/sandboxed-html.js';

test('old frozen pages can detect unavailable storage in an opaque-origin iframe', () => {
  const html = '<!doctype html><html><head></head><body><script>oldViewer()</script></body></html>';
  const presented = sandboxedHtml(html);
  const window = {};
  Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new Error('SecurityError'); } });
  runInNewContext(presented.match(/<script>(.*?)<\/script>/s)[1], { window });
  assert.equal(typeof window.localStorage, 'undefined');
  assert.ok(presented.startsWith('<!doctype html>'));
  assert.ok(presented.endsWith('<body><script>oldViewer()</script></body></html>'));
  assert.equal(html.includes('Object.defineProperty'), false, 'saved evidence stays unchanged');
});

test('normal browser storage is never replaced', () => {
  const storage = { getItem() { return 'zh-CN'; } }, window = { localStorage: storage };
  const presented = sandboxedHtml('<body>result</body>');
  runInNewContext(presented.match(/<script>(.*?)<\/script>/s)[1], { window });
  assert.equal(window.localStorage, storage);
});
