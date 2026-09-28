import assert from "node:assert/strict";
import test from "node:test";
import { decodeBase64 } from "../studio/app/binary.js";

test("large binary resources yield between chunks without corrupting bytes or padding", async () => {
  for (const extra of [0, 1, 2]) {
    const original = Buffer.alloc(3 * 1024 * 1024 + extra);
    for (let i = 0; i < original.length; i++) original[i] = i % 251;
    let yields = 0;
    const decoded = await decodeBase64(original.toString("base64"), async () => { yields++; });
    assert.deepEqual(Buffer.from(decoded), original);
    assert.ok(yields >= 3);
  }
});

test("fallback browser decoder retains binary zeros and full byte range", async () => {
  const native = Uint8Array.fromBase64;
  try {
    Uint8Array.fromBase64 = undefined;
    const original = Buffer.from(Array.from({ length: 256 }, (_, i) => i));
    assert.deepEqual(Buffer.from(await decodeBase64(original.toString("base64"))), original);
    assert.equal((await decodeBase64("")).byteLength, 0);
  } finally {
    if (native === undefined) delete Uint8Array.fromBase64;
    else Uint8Array.fromBase64 = native;
  }
});
