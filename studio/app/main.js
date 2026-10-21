import { App } from "@modelcontextprotocol/ext-apps";
import * as THREE from "three";
import { createWorkspace } from "../web/workspace.js";
import { presentationFor, safeAreaFor } from "./presentation.js";
import { createMcpApi, payload } from "./api.js";
import { decodeBase64 } from "./binary.js";
import { createSelectionContextSync } from "./selection-context.js";
import { t } from "../web/i18n.js";
import { browserEntry } from "../web/quick-access.js";

const $ = (id) => document.getElementById(id);
// The host owns the workspace dimensions. SDK autoResize measures max-content
// on every resize and reports it back, creating a resize feedback path.
const app = new App({ name: "3D Workbench", version: "0.9.0" }, {}, { autoResize: false });
const api = createMcpApi(app, $("print-prep-app").dataset.workspaceId);
const selectionContext = createSelectionContextSync(app);
let connected = false, closed = false, connection = null, poll = null, state = null;
let workspace = null, presentation = "card", geometryQueue = Promise.resolve();
let requestedEntry = browserEntry();
let presentationKey = "", cardFrame = null, cardSize = "";
let startupTimer = null, startupRequest = null, startupAttempts = 0;
const STARTUP_ATTEMPTS = 15;
function reportCardSize() {
  if (!connected || closed || presentation !== "card" || cardFrame !== null) return;
  cardFrame = requestAnimationFrame(() => {
    cardFrame = null;
    if (presentation !== "card" || closed) return;
    const width = Math.ceil(window.innerWidth), height = Math.ceil($("launch-card").getBoundingClientRect().height);
    const key = `${width}:${height}`;
    if (cardSize !== key) { cardSize = key; app.sendSizeChanged({ width, height }); }
  });
}
const cardObserver = new ResizeObserver(reportCardSize);
cardObserver.observe($("launch-card"));

function status(message, error = false) {
  $("launch-status").textContent = message;
  $("launch-status").classList.toggle("error", error);
  $("workspace-error").hidden = !error;
  $("workspace-error").querySelector('span').textContent = message;
}
function updateSummary(next) {
  state = next;
  const folder = state.workbench?.project_folder;
  $("launch-project").hidden = !folder;
  $("launch-project").textContent = folder ? t('entry.launchProject', { name: folder.replace(/[\\/]+$/, '').split(/[\\/]/).pop() }) : '';
  $("launch-project").title = folder || '';
  $("workspace-summary").textContent = state.workbench?.objects?.length
    ? t("main.summary.editObjects", { objects: state.workbench.objects.length, selected: state.workbench.selection.length })
    : state.parts?.length
    ? t("main.summary.parts", { parts: state.parts.length, passed: state.readiness?.passed ?? 0,
        platesSuffix: state.plates?.length ? t("main.summary.platesSuffix", { plates: state.plates.length }) : "" })
    : t("main.summary.empty");
}
function loadGeometry(part) {
  const load = async () => {
    const version = new URLSearchParams(part.stl_url.split("?")[1]).get("v");
    const uri = `print-prep://preview/${encodeURIComponent(part.name)}?v=${version}`;
    const result = await app.readServerResource({ uri: api.resourceUri(uri) }, { timeout: 120_000 });
    const data = JSON.parse(result.contents[0].text);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(await decodeBase64(data.positions)), 3));
    geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(await decodeBase64(data.indices)), 1));
    return geometry;
  };
  const promise = geometryQueue.then(load);
  geometryQueue = promise.catch(() => {});
  return promise;
}
function ensureWorkspace() {
  if (workspace || !api.workspaceId || !Array.isArray(state?.parts)) return;
  workspace = createWorkspace(api, {
    loadGeometry, onState: updateSummary,
    onSelectionContext: (snapshot) => selectionContext.update(snapshot),
    onAttachSelection: () => selectionContext.attach(),
  });
  if (state) workspace.setState(state);
  workspace.ready.catch((error) => status(error.message, true));
}
function applyHostContext(context = {}) {
  const key = JSON.stringify([connected, presentationFor(context), safeAreaFor(context), context.availableDisplayModes]);
  if (presentationKey === key) return;
  presentationKey = key;
  presentation = presentationFor(context);
  $("print-prep-app").dataset.presentation = presentation;
  $("launch-card").hidden = presentation !== "card";
  $("workspace").hidden = presentation !== "workspace";
  for (const [edge, value] of Object.entries(safeAreaFor(context))) {
    $("print-prep-app").style.setProperty(`--safe-${edge}`, `${value}px`);
  }
  $("open-workspace").disabled = !connected || !context.availableDisplayModes?.includes("fullscreen");
  if (connected && presentation === "workspace") ensureWorkspace();
  workspace?.setActive(connected && presentation === "workspace" && !document.hidden);
  if (presentation === "card") reportCardSize(); else cardSize = "";
}
$("open-workspace").onclick = async () => {
  $("open-workspace").disabled = true;
  try {
    const result = await app.requestDisplayMode({ mode: "fullscreen" });
    applyHostContext({ ...app.getHostContext(), displayMode: result.mode });
    if (result.mode !== "fullscreen") status(t("main.status.hostDidNotExpand"), true);
  } catch (error) { status(error.message, true); }
  finally { $("open-workspace").disabled = !connected || !app.getHostContext()?.availableDisplayModes?.includes("fullscreen"); }
};
function bindWorkspace(id) {
  if (!id) return;
  const wasBound = !!api.workspaceId;
  api.bindWorkspace(id);
  if (!wasBound && connected) status(t("main.status.taskBoundLoading"));
}

function waitForThread() {
  // A replayed pending response must never replace an already restored scene.
  if (state || closed) return;
  $("workspace-startup").hidden = false;
  const message = t(startupAttempts < STARTUP_ATTEMPTS ? 'main.status.threadInitializing' : 'main.status.threadNeedsMessage');
  $("startup-message").textContent = message;
  status(message);
  clearTimeout(startupTimer); startupTimer = null;
  if (connected && !document.hidden && startupAttempts < STARTUP_ATTEMPTS) {
    startupTimer = setTimeout(() => { startupTimer = null; return initializeWorkspace(); }, 2000);
  }
}

function acceptOpenResult(result) {
  if (closed) return;
  const next = payload(result);
  bindWorkspace(next.workspace_id);
  const nonce = result._meta?.["studio/uiNonce"];
  if (typeof nonce === "string") api.setUiNonce(nonce);
  if (next.startup?.status === 'waiting_for_thread') { waitForThread(); return; }
  if (!Array.isArray(next.parts)) return;
  // Only an explicitly requested destination bypasses the model chooser.
  next.workspace_mode = requestedEntry.taskId ? 'tasks' : requestedEntry.mode;
  if (requestedEntry.taskId) next.focus_task_id = requestedEntry.taskId;
  clearTimeout(startupTimer); startupTimer = null;
  $("workspace-startup").hidden = true;
  updateSummary(next);
  if (connected && presentation === 'workspace') ensureWorkspace();
  workspace?.setState(next);
  workspace?.setActive(connected && presentation === 'workspace' && !document.hidden);
  status(t("main.status.workspaceSynced"));
}

function initializeWorkspace() {
  if (closed || !connected || !api.workspaceId) return Promise.resolve();
  if (startupRequest) return startupRequest;
  clearTimeout(startupTimer); startupTimer = null;
  startupAttempts++;
  const args = {workspace_id: api.workspaceId, mode: requestedEntry.mode};
  if (requestedEntry.taskId) args.task_id = requestedEntry.taskId;
  startupRequest = app.callServerTool({name: 'studio_open', arguments: args}, {timeout: 30_000})
    .then(result => { if (connected) acceptOpenResult(result); })
    .catch(error => {
      if (closed || !connected) return;
      $("workspace-startup").hidden = true;
      status(error.message, true);
    })
    .finally(() => { startupRequest = null; });
  return startupRequest;
}
// Global/thread entrypoints can send tool input before a result is available.
// Bind only host-supplied identity; never guess a workspace from global state.
app.ontoolinput = ({ arguments: args }) => {
  try {
    requestedEntry = browserEntry(new URLSearchParams({ mode: args?.mode || '', task: args?.task_id || '' }).toString());
    bindWorkspace(args?.workspace_id);
    if (connected && !state) void initializeWorkspace();
  }
  catch (error) { status(error.message, true); }
};
app.ontoolresult = (result) => {
  try {
    // studio_open's result carries a per-workspace nonce in `_meta` (never in
    // content/structuredContent, which the host model can read) that
    // authenticates this UI's own studio_ui_action / studio_part_chat calls as
    // actor="human". Only studio_open attaches it; other tool results leave
    // `_meta["studio/uiNonce"]` absent and this is a no-op for them. If this
    // never fires on a given host (unverified whether `_meta` reaches the
    // iframe everywhere), or the nonce goes stale (server restart, or a host
    // replaying an old studio_open result), api.js's write()/partChat() self-heal
    // on human_required by re-minting the nonce once; the retry button below
    // also re-mints it proactively on every reconnect.
    acceptOpenResult(result);
  } catch (error) { status(error.message, true); }
};
app.onhostcontextchanged = () => applyHostContext(app.getHostContext());
document.addEventListener("visibilitychange", () => {
  workspace?.setActive(connected && presentation === "workspace" && !document.hidden);
  if (document.hidden) { clearTimeout(startupTimer); startupTimer = null; }
  else if (!state && !$("workspace-startup").hidden) waitForThread();
});
app.onteardown = async () => { closed = true; clearTimeout(poll); clearTimeout(startupTimer); cardObserver.disconnect(); cancelAnimationFrame(cardFrame); workspace?.dispose(); await selectionContext.dispose(); return {}; };
app.onclose = () => {
  connected = false;
  clearTimeout(startupTimer); startupTimer = null;
  presentationKey = '';
  workspace?.setActive(false);
  if (!closed) status(t("main.status.hostDisconnected"), true);
};
async function schedule() {
  if (closed) return;
  if (connected && api.workspaceId && state && !document.hidden && presentation === "card") {
    try { updateSummary(await api.getState()); status(t("main.status.workspaceSynced")); }
    catch (error) { status(error.message, true); }
  }
  if (!closed) poll = setTimeout(schedule, 5000);
}
function connectHost() {
  if (connected || closed) return Promise.resolve();
  if (connection) return connection;
  connection = app.connect(undefined, { timeout: 15_000 }).then(async () => {
    if (closed) return;
    await selectionContext.clear();
    if (closed) return;
    connected = true;
    applyHostContext(app.getHostContext());
  }).finally(() => { connection = null; });
  return connection;
}
connectHost().then(async () => {
  if (closed) return;
  if (api.workspaceId) {
    await initializeWorkspace();
  } else status(t("main.status.legacyEntryUnbound"), true);
  if (!closed) poll = setTimeout(schedule, 5000);
}).catch((error) => status(t("main.status.connectionIncomplete", { detail: error.message }), true));

$("workspace-retry").onclick = async () => {
  $("workspace-retry").disabled = true;
  try {
    await connectHost();
    if (closed) return;
    if (!api.workspaceId) { status(t("main.status.reconnectedWaitingBind"), true); return; }
    if (!state) {
      startupAttempts = 0; await initializeWorkspace();
      if (!closed && !poll) poll = setTimeout(schedule, 5000);
      return;
    }
    // Re-mint the nonce on every reconnect: a stale one otherwise only surfaces
    // later, as a failed write. Best-effort — if this itself fails, the state
    // resync below still runs, and write()/partChat() retry once on their own.
    await api.refreshNonce().catch(() => {});
    const next = await api.getState(); updateSummary(next);
    ensureWorkspace(); workspace?.setState(next); status(t("main.status.workspaceSynced"));
    if (!poll) poll = setTimeout(schedule, 5000);
  } catch (error) { status(t("main.status.reconnectFailed", { detail: error.message }), true); }
  finally { $("workspace-retry").disabled = false; }
};
$("startup-retry").onclick = () => $("workspace-retry").onclick();
window.addEventListener('error', event => status(event.message || t("main.status.uiLoadFailed"), true));
window.addEventListener('unhandledrejection', event => status(event.reason?.message || t("main.status.connectionFailedGeneric"), true));
