import { createApi } from "./api.js";
import { createMockApi } from "./mock.js";
import { createWorkspace } from "./workspace.js";
import { browserEntry } from "./quick-access.js";
const mock = new URLSearchParams(location.search).get("mock") === "1";
const workspace = createWorkspace(mock ? createMockApi() : createApi(), { mock });
if (!mock) {
  const entry = browserEntry(location.search);
  workspace.ready.then(() => {
    if (entry.taskId) return workspace.openResult(entry.taskId);
    workspace.setMode(entry.mode);
  }).catch(error => {
    const message = document.getElementById('recipe-error');
    message.textContent = error.message; message.hidden = false;
  });
}
document.addEventListener("visibilitychange", () => workspace.setActive(!document.hidden));
window.addEventListener("pagehide", () => workspace.dispose(), { once: true });
