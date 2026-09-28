import assert from "node:assert/strict";
import test from "node:test";
import { presentationFor, safeAreaFor } from "../studio/app/presentation.js";

test("conversation cards do not become editors until the host opens its side panel", () => {
  const context = { availableDisplayModes: ["inline", "fullscreen"], displayMode: "inline" };
  assert.equal(presentationFor(context), "card");
  assert.equal(presentationFor({ ...context, displayMode: "fullscreen" }), "workspace");
  // A host close notification must bring back the card without reopening.
  assert.equal(presentationFor(context), "card");
  assert.equal(presentationFor(), "card");
});

test("Codex standalone plugin surfaces already provide a workspace", () => {
  assert.equal(presentationFor({ availableDisplayModes: ["inline"], displayMode: "inline" }), "workspace");
});

test("host overlay insets reserve space and invalid insets cannot break layout", () => {
  assert.deepEqual(safeAreaFor({ safeAreaInsets: { bottom: 96, top: 8 } }), { top: 8, right: 0, bottom: 96, left: 0 });
  assert.deepEqual(safeAreaFor({ safeAreaInsets: { bottom: -5, right: Infinity, left: "bad" } }), { top: 0, right: 0, bottom: 0, left: 0 });
});
