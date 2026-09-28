import assert from "node:assert/strict";
import test from "node:test";

// Dynamic import of the real files (not the data: URL trick this used before
// tools.js/api.js gained a real `import ... from "./i18n.js"` — data: URL
// modules have no base URL, so relative imports can't resolve from one).
const { registerPageTools } = await import(new URL("../studio/web/tools.js", import.meta.url));
const { createApi } = await import(new URL("../studio/web/api.js", import.meta.url));
const tools = [{
  name: "studio_state", description: "Read the current state", readOnly: true,
  inputSchema: { type: "object", properties: {} }, method: "GET", path: "/api/state",
}];
const noApiCalls = { callPath() { throw new Error("Unexpected API call during registration"); } };
const unsupported = "\u6b64\u6d4f\u89c8\u5668\u4e0d\u652f\u6301\u9875\u9762\u5de5\u5177";
const registered = "\u5df2\u767b\u8bb0 1 \u4e2a";
const failed = "\u767b\u8bb0\u5931\u8d25\uff1a";

test("HTTP tools envelope reaches page registration and executes through the real API adapter", async () => {
  const savedFetch = globalThis.fetch;
  const definitions = [];
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push([path, options.method]);
    const payload = path === '/api/session' ? {token:'test-token',job:'test'} : path === "/api/tools"
      ? { ok: true, tools }
      : { ok: true, rev: 7, parts: [{ name: "body" }] };
    return new Response(JSON.stringify(payload), { status: 200 });
  };
  try {
    await withBrowser({ document: { modelContext: { registerTool(def) { definitions.push(def); } } } }, async () => {
      const api = createApi();
      assert.equal(await registerPageTools(await api.getTools(), api), registered);
      assert.equal(definitions.length, 1);
      const result = JSON.parse((await definitions[0].execute({})).content[0].text);
      assert.equal(result.parts[0].name, "body");
      assert.deepEqual(calls, [["/api/session", "GET"], ["/api/tools", "GET"], ["/api/state", "GET"]]);
    });
  } finally {
    globalThis.fetch = savedFetch;
  }
});

async function withBrowser(environment, run) {
  const saved = new Map(["document", "navigator"].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  try {
    for (const key of saved.keys()) {
      Object.defineProperty(globalThis, key, { value: environment[key], writable: true, configurable: true });
    }
    await run();
  } finally {
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
}

test("document-only registration discovers tools and preserves their schema", async () => {
  const definitions = [];
  const provider = { async registerTool(definition) { assert.equal(this, provider); definitions.push(definition); } };
  await withBrowser({ document: { modelContext: provider }, navigator: {} }, async () => {
    assert.equal(await registerPageTools(tools, noApiCalls), registered);
    assert.equal(definitions.length, 1);
    assert.equal(definitions[0].name, "studio_state");
    assert.equal(definitions[0].inputSchema, tools[0].inputSchema);
    assert.equal(definitions[0].annotations.readOnlyHint, true);
  });
});

test("legacy navigator registration works when document has no provider", async () => {
  const definitions = [];
  await withBrowser({ navigator: { modelContext: { registerTool(definition) { definitions.push(definition); } } } }, async () => {
    assert.equal(await registerPageTools(tools, noApiCalls), registered);
    assert.equal(definitions.length, 1);
  });
});

test("a document provider without supported methods does not hide navigator", async () => {
  let count = 0;
  await withBrowser({ document: { modelContext: {} }, navigator: { modelContext: { registerTool() { count += 1; } } } }, async () => {
    assert.equal(await registerPageTools(tools, noApiCalls), registered);
    assert.equal(count, 1);
  });
});

test("document registration takes precedence over navigator", async () => {
  const calls = [];
  await withBrowser({
    document: { modelContext: { registerTool() { calls.push("document"); } } },
    navigator: { modelContext: { registerTool() { calls.push("navigator"); } } },
  }, async () => {
    assert.equal(await registerPageTools(tools, noApiCalls), registered);
    assert.deepEqual(calls, ["document"]);
  });
});

test("async registration rejection reports failure without trying another provider", async () => {
  let navigatorCalls = 0;
  await withBrowser({
    document: { modelContext: { async registerTool() { throw new Error("registration rejected"); } } },
    navigator: { modelContext: { registerTool() { navigatorCalls += 1; } } },
  }, async () => {
    assert.equal(await registerPageTools(tools, noApiCalls), failed + "registration rejected");
    assert.equal(navigatorCalls, 0);
  });
});

test("provideContext compatibility awaits registration and reports rejection", async () => {
  let supplied;
  const provider = { async provideContext(context) { assert.equal(this, provider); supplied = context; } };
  await withBrowser({ navigator: { modelContext: provider } }, async () => {
    assert.ok((await registerPageTools(tools, noApiCalls)).startsWith(registered));
    assert.equal(supplied.tools[0].name, "studio_state");
    provider.provideContext = async () => { throw new Error("context rejected"); };
    assert.equal(await registerPageTools(tools, noApiCalls), failed + "context rejected");
  });
});

test("registered GET and POST execute handlers forward inputs and return API results", async () => {
  const definitions = [];
  const calls = [];
  const response = { ok: true, rev: 12 };
  const api = { async callPath(...args) { calls.push(args); return response; } };
  await withBrowser({ document: { modelContext: { registerTool(definition) { definitions.push(definition); } } } }, async () => {
    await registerPageTools([...tools, { name: "studio_arrange", method: "POST", path: "/api/arrange", readOnly: false }], api);
    assert.equal(definitions.length, 2);
    const readResult = await definitions[0].execute({ plate: 2, filter: { enabled: true }, missing: undefined, empty: null });
    const readUrl = new URL(calls[0][1], "http://localhost");
    assert.equal(calls[0][0], "GET");
    assert.equal(readUrl.pathname, "/api/state");
    assert.equal(readUrl.searchParams.get("plate"), "2");
    assert.equal(readUrl.searchParams.get("filter"), '{"enabled":true}');
    assert.equal(readUrl.searchParams.has("missing"), false);
    assert.equal(readUrl.searchParams.has("empty"), false);
    assert.deepEqual(JSON.parse(readResult.content[0].text), response);
    const body = { gap: 6, mode: "auto" };
    const writeResult = await definitions[1].execute(body);
    assert.deepEqual(calls[1], ["POST", "/api/arrange", body]);
    assert.equal(definitions[1].annotations.readOnlyHint, false);
    assert.deepEqual(JSON.parse(writeResult.content[0].text), response);
  });
});

test("unsupported browser reports a useful status without browser globals", async () => {
  await withBrowser({}, async () => {
    assert.ok((await registerPageTools(tools, noApiCalls)).startsWith(unsupported));
  });
});
