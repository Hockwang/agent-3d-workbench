// tools.js — 把 /api/tools 的定义登记成页面 WebMCP 工具（SPEC.md §8）。
// 假定 tools_schema 里每项形如 {name, description, inputSchema, readOnly, method, path}；
// method/path 由服务端给出，指明这个工具具体对应哪一个 HTTP 接口。

import { t } from "./i18n.js";

function buildExecute(tool, api) {
  return async function execute(input) {
    const args = input || {};
    let result;
    try {
      const method = (tool.method || "GET").toUpperCase();
      if (method === "GET") {
        const qs = new URLSearchParams();
        for (const [k, v] of Object.entries(args)) {
          if (v === undefined || v === null) continue;
          qs.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
        }
        const q = qs.toString();
        result = await api.callPath("GET", tool.path + (q ? "?" + q : ""));
      } else {
        result = await api.callPath("POST", tool.path, args);
      }
    } catch (e) {
      result = { ok: false, error: { code: e.code || "tool_error", message: e.message || String(e) } };
    }
    return { content: [{ type: "text", text: JSON.stringify(result) }] };
  };
}

function buildToolDef(tool, api) {
  return {
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema || { type: "object", properties: {} },
    annotations: {
      readOnlyHint: !!tool.readOnly,
      destructiveHint: !tool.readOnly,
      openWorldHint: false,
    },
    execute: buildExecute(tool, api),
  };
}

/**
 * Prefer document.modelContext; support the legacy navigator API when needed.
 * 任何异常都会被吞掉并转成状态文案，不影响面板本身。
 * @returns {Promise<string>} 供状态栏显示的一句话
 */
export async function registerPageTools(tools, api) {
  try {
    const mc = [globalThis.document?.modelContext, globalThis.navigator?.modelContext]
      .find((provider) => typeof provider?.registerTool === "function"
        || typeof provider?.provideContext === "function");
    if (!mc) {
      return t("tools.unsupportedBrowser");
    }
    const defs = (tools || []).map((tool) => buildToolDef(tool, api));
    if (typeof mc.registerTool === "function") {
      for (const def of defs) await mc.registerTool(def);
      return t("tools.registered", { count: defs.length });
    }
    if (typeof mc.provideContext === "function") {
      await mc.provideContext({ tools: defs });
      return t("tools.registeredOnce", { count: defs.length });
    }
    return t("tools.unsupportedBrowser");
  } catch (e) {
    return t("tools.registrationFailed", { detail: e && e.message ? e.message : String(e) });
  }
}
