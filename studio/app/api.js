// MCP transport for the shared workspace. No localhost fetches from the iframe.
import { decodeBase64 } from "./binary.js";
import { uploadFile } from '../web/upload.js';
import { t } from "../web/i18n.js";
export function payload(result) {
  const value = result.structuredContent ?? JSON.parse(result.content.find((c) => c.type === "text").text);
  if (result.isError || value.ok === false) {
    const error = new Error(value.error?.message || t("mcpApi.error.operationFailed"));
    error.code = value.error?.code || "tool_error";
    throw error;
  }
  return value;
}

export function createMcpApi(app, initialWorkspace = '') {
  let workspaceId = initialWorkspace;
  // Minted by the server per-workspace and handed to this app only through
  // studio_open's tool-result metadata (see main.js's `ontoolresult`), never
  // through content the host model can read. Attached to every studio_ui_action
  // and studio_part_chat call so the server can record actor="human" for calls
  // that really came from this UI; omitted (not sent as null) until it arrives,
  // which the server treats as actor="ai", never as a denial.
  let uiNonce = null;
  const scopedUri = (uri) => workspaceId ? `${uri}${uri.includes('?') ? '&' : '?'}workspace=${encodeURIComponent(workspaceId)}` : uri;
  const call = async (name, args = {}) => payload(await app.callServerTool(
    { name, arguments: workspaceId ? { ...args, workspace_id: workspaceId } : args }, { timeout: 1_800_000 },
  ));
  // Re-mints the nonce by calling studio_open again for the same workspace. Used both
  // proactively (main.js's retry path, after a host reconnect) and reactively below
  // (a stale nonce surfaces as human_required). studio_open always stamps `_meta`,
  // even on an error result, so this reads the raw tool result rather than `call()`,
  // which would throw on isError before we could reach `_meta`.
  const refreshNonce = async () => {
    const result = await app.callServerTool(
      { name: "studio_open", arguments: workspaceId ? { workspace_id: workspaceId } : {} }, { timeout: 30_000 },
    );
    const nonce = result?._meta?.["studio/uiNonce"];
    if (typeof nonce === "string") uiNonce = nonce;
    return nonce;
  };
  // Wraps a studio_ui_action / studio_part_chat call so a stale nonce (server
  // restart, or a host replaying an old studio_open result) self-heals once:
  // on human_required, refresh the nonce and retry the same call exactly once.
  // A second failure (still human_required or anything else) is not retried
  // again and propagates as-is, so this never loops.
  const withNonceRecovery = (fn) => async (...callArgs) => {
    try {
      return await fn(...callArgs);
    } catch (error) {
      if (error?.code !== "human_required") throw error;
      await refreshNonce();
      return await fn(...callArgs);
    }
  };
  const writeOnce = (name, args = {}) => call("studio_ui_action", {
    name,
    arguments: workspaceId ? { ...args, workspace_id: workspaceId } : args,
    ...(uiNonce ? { ui_nonce: uiNonce } : {}),
  });
  const write = withNonceRecovery(writeOnce);
  const partChatOnce = (body) => call('studio_part_chat', uiNonce ? { ...body, ui_nonce: uiNonce } : body);
  return {
    get workspaceId() { return workspaceId; },
    bindWorkspace(id) {
      if (workspaceId && workspaceId !== id) throw new Error(t('mcpApi.error.wrongWorkspace'));
      workspaceId = id;
    },
    setUiNonce(nonce) { uiNonce = nonce; },
    refreshNonce,
    resourceUri: scopedUri,
    init: async () => {},
    getState: () => call("studio_get_state"),
    getRecipes: () => call("studio_list_recipes"),
    getRecipe: (id) => call("studio_get_recipe", { id }),
    useRecipe: (id) => write("studio_use_recipe", { id }),
    edit: (body) => write("studio_edit", body),
    collaboration: (body) => call('studio_workspaces', body),
    partChat: withNonceRecovery(partChatOnce),
    async openPartChat(url) {
      if (!/^codex:\/\/threads\/[a-f0-9-]{36}$/.test(url)) throw new Error(t('api.error.invalidTaskLink'));
      const result = await app.openLink({ url });
      if (result?.isError) throw new Error(t('mcpApi.error.codexDidNotOpenTask'));
    },
    async requestMotionRig(prompt) {
      const result = await app.sendMessage({ role:'user', content:[{type:'text',text:prompt}] });
      if (result.isError) throw new Error(t('mcpApi.error.codexRigRejected'));
      return t('mcpApi.status.rigRequestSent');
    },
    capabilities: () => call("studio_capabilities"),
    services: (body) => write("studio_services", body),
    tasks: (id) => call("studio_tasks", id ? { id } : {}),
    observe: (body) => write('studio_observe', { ...body, image: false, detail: true }),
    evaluation: (body) => write('studio_evaluation', body),
    task: (body) => write("studio_task", body),
    upload: (file, onProgress) => uploadFile((body) => write('studio_task', body), file, onProgress),
    async taskAsset(id, artifact, { presentation = false } = {}) {
      const result = await app.readServerResource({ uri: scopedUri(`print-prep://task/${id}/${artifact.id}${presentation ? '?presentation=studio' : ''}`) }, { timeout: 120_000 });
      return decodeBase64(result.contents[0].blob);
    },
    async editorAsset(obj) {
      const result = await app.readServerResource({ uri: scopedUri(`print-prep://editor/${obj.asset}`) }, { timeout: 120_000 });
      return decodeBase64(result.contents[0].blob);
    },
    async cityResource(digest, name) {
      const result = await app.readServerResource({uri: scopedUri(`print-prep://city/${digest}/${encodeURIComponent(name)}`)}, {timeout:120_000});
      return decodeBase64(result.contents[0].blob);
    },
    getPrinters: () => call("studio_list_printers"),
    getShapes: async () => {
      const result = await app.readServerResource({ uri: scopedUri("print-prep://catalog/shapes") });
      return JSON.parse(result.contents[0].text);
    },
    load: (body) => write("studio_load", body),
    orient: (body) => write("studio_orient", body),
    arrange: (body) => write("studio_arrange", body),
    exportProject: (body) => write("studio_export", body),
    check: (body) => write("studio_check", body),
    send: (body) => write("studio_send_to_bambu", body),
    prepare: (body) => write("studio_prepare", body),
    select: (parts) => write("studio_select", { parts }),
    undo: (id) => write("studio_undo", id == null ? {} : { id }),
  };
}
