import { App } from "@modelcontextprotocol/ext-apps";
import * as THREE from "three";
import { createWorkspace } from "../web/workspace.js";
import { presentationFor, safeAreaFor } from "./presentation.js";
import { createMcpApi, payload } from "./api.js";
import { decodeBase64 } from "./binary.js";
import { createSelectionContextSync } from "./selection-context.js";
import { t } from "../web/i18n.js";

const $ = (id) => document.getElementById(id);
// The host owns the workspace dimensions. SDK autoResize measures max-content
// on every resize and reports it back, creating a resize feedback path.
const app = new App({ name: "3D Workbench", version: "0.8.6" }, {}, { autoResize: false });
const api = createMcpApi(app, $("print-prep-app").dataset.workspaceId);
const selectionContext = createSelectionContextSync(app);
let connected = false, closed = false, connection = null, poll = null, state = null;
let workspace = null, presentation = "card", geometryQueue = Promise.resolve();
let presentationKey = "", cardFrame = null, cardSize = "";
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
  if (workspace || !api.workspaceId) return;
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
  if (connected && presentation === 'workspace') ensureWorkspace();
  if (!wasBound && connected) status(t("main.status.taskBoundLoading"));
}
// Global/thread entrypoints can send tool input before a result is available.
// Bind only host-supplied identity; never guess a workspace from global state.
app.ontoolinput = ({ arguments: args }) => {
  try { bindWorkspace(args?.workspace_id); }
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
    const nonce = result._meta?.["studio/uiNonce"];
    if (typeof nonce === "string") api.setUiNonce(nonce);
    const next = payload(result);
    bindWorkspace(next.workspace_id);
    if (Array.isArray(next.parts)) { updateSummary(next); workspace?.setState(next); status(t("main.status.workspaceSynced")); }
  } catch (error) { status(error.message, true); }
};
app.onhostcontextchanged = () => applyHostContext(app.getHostContext());
document.addEventListener("visibilitychange", () => workspace?.setActive(connected && presentation === "workspace" && !document.hidden));
app.onteardown = async () => { closed = true; clearTimeout(poll); cardObserver.disconnect(); cancelAnimationFrame(cardFrame); workspace?.dispose(); await selectionContext.dispose(); return {}; };
app.onclose = () => {
  connected = false;
  presentationKey = '';
  workspace?.setActive(false);
  if (!closed) status(t("main.status.hostDisconnected"), true);
};
async function schedule() {
  if (closed) return;
  if (connected && api.workspaceId && !document.hidden && presentation === "card") {
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
    if (!workspace) updateSummary(await api.getState());
    status(t("main.status.workspaceSynced"));
  } else status(t("main.status.legacyEntryUnbound"), true);
  if (!closed) poll = setTimeout(schedule, 5000);
}).catch((error) => status(t("main.status.connectionIncomplete", { detail: error.message }), true));

$("workspace-retry").onclick = async () => {
  $("workspace-retry").disabled = true;
  try {
    await connectHost();
    if (closed) return;
    if (!api.workspaceId) { status(t("main.status.reconnectedWaitingBind"), true); return; }
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
window.addEventListener('error', event => status(event.message || t("main.status.uiLoadFailed"), true));
window.addEventListener('unhandledrejection', event => status(event.reason?.message || t("main.status.connectionFailedGeneric"), true));
