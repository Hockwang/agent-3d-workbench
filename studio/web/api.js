// api.js — 本机服务的 fetch 封装（真实后端，非 mock）。
// 契约见 SPEC.md §7 与 SPEC_V05.md §2：除 /api/session 外都带 X-Studio-Token；写请求另带 X-Studio-Actor（面板里点出来的是 human，页面工具是 ai）。

import { t, getLocale } from "./i18n.js";

export class ApiError extends Error {
  constructor(code, message, payload) {
    super(message || code || "unknown_error");
    this.code = code || "unknown_error";
    this.payload = payload || null;
  }
}

export function createApi() {
  let token = null;
  let job = null;
  const workspaceId = new URLSearchParams(globalThis.location?.search || '').get('workspace');
  let initializing;
  function ensureSession(){
    if(token)return Promise.resolve();
    return initializing ||= raw('GET','/api/session').then(s=>{token=s.token;job=s.job;return s;}).finally(()=>{initializing=null;});
  }

  async function raw(method, path, { json, headers, actor, retried } = {}) {
    if(path!=='/api/session'&&!token)await ensureSession();
    const h = Object.assign({}, headers);
    if (workspaceId) h['X-Studio-Workspace'] = workspaceId;
    if (token) h["X-Studio-Token"] = token;
    // The backend renders its messages per request from Accept-Language (studio/i18n.py);
    // send the panel's own locale so errors and summaries follow the language toggle.
    h["Accept-Language"] = getLocale();
    if (method !== "GET") h["X-Studio-Actor"] = actor || "human";
    let body;
    if (json !== undefined) {
      h["Content-Type"] = "application/json";
      body = JSON.stringify(json);
    }
    let res;
    try {
      res = await fetch(path, { method, headers: h, body });
    } catch (netErr) {
      throw new ApiError("network_error", t("api.error.networkUnreachable", { detail: netErr && netErr.message ? netErr.message : netErr }));
    }
    let text = "";
    try {
      text = await res.text();
    } catch (e) {
      text = "";
    }
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (e) {
        data = null;
      }
    }
    // 本机服务重启后令牌会换：拿旧令牌的请求会 403。重新取一次令牌再试一遍，页面不用刷新。
    if (res.status === 403 && path !== "/api/session" && !retried) {
      try {
        const fresh = await raw("GET", "/api/session");
        token = fresh.token;
        job = fresh.job;
      } catch (e) {
        /* 取不到新令牌就按原来的 403 报错 */
      }
      if (token) return raw(method, path, { json, headers, actor, retried: true });
    }
    if (!res.ok) {
      const err = (data && data.error) || {};
      throw new ApiError(err.code || "http_" + res.status, err.message || res.statusText || t("api.error.requestFailed"), data);
    }
    return data;
  }

  const api = {
    get workspaceId() { return workspaceId; },
    partChat: (body) => raw('POST', '/api/part-chat', { json: body }),
    openPartChat: async (url) => {
      if (!/^codex:\/\/threads\/[a-f0-9-]{36}$/.test(url)) throw new Error(t('api.error.invalidTaskLink'));
      globalThis.location.href = url;
    },
    collaboration: (body) => raw('POST', '/api/collaboration', { json: body }),
    async init() {
      const s = await raw("GET", "/api/session");
      token = s.token;
      job = s.job;
      return s;
    },
    get token() {
      return token;
    },
    get job() {
      return job;
    },
    // HTTP 返回 {ok, tools}；与 mock 一样，适配层只向登记器交付工具数组。
    getTools: async () => (await raw("GET", "/api/tools")).tools,
    getState: () => raw("GET", "/api/state"),
    observe: (body) => raw('POST', '/api/observe', { json: body }),
    evaluation: (body) => raw('POST', '/api/evaluation', { json: body }),
    getRecipes: () => raw("GET", "/api/recipes"),
    getRecipe: (id) => raw("GET", "/api/recipe?id=" + encodeURIComponent(id)),
    useRecipe: (id) => raw("POST", "/api/recipe/use", { json: { id } }),
    edit: (body) => raw("POST", "/api/edit", { json: body }),
    async assemblyProject(source = 'manual') {
      if (!['manual', 'presets', 'legacy'].includes(source)) {
        throw new ApiError('invalid_source', t('assembly.error.invalidWorkflow'));
      }
      return raw('GET', '/api/assembly/project?source=' + encodeURIComponent(source));
    },
    capabilities: () => raw("GET", "/api/capabilities"),
    services: (body) => raw("POST", "/api/services", { json: body }),
    tasks: (id) => raw("GET", "/api/tasks" + (id ? "?id=" + encodeURIComponent(id) : "")),
    task: (body) => raw("POST", "/api/task", { json: body }),
    async taskAsset(id, artifact, { presentation = false } = {}) {
      const res = await fetch(`/api/task-asset/${encodeURIComponent(id)}/${encodeURIComponent(artifact.id)}${presentation ? '?presentation=studio' : ''}`,
        { headers: { "X-Studio-Token": token } });
      if (!res.ok) throw new ApiError("artifact_error", t("api.error.artifactReadFailed"));
      return res.arrayBuffer();
    },
    async editorAsset(obj) {
      const response = await fetch(obj.asset_url, { headers: { "X-Studio-Token": token } });
      if (!response.ok) throw new ApiError("preview_error", t("api.error.meshReadFailed"));
      return response.arrayBuffer();
    },
    async cityResource(digest, name) {
      const response = await fetch(`/api/city-resource/${digest}/${encodeURIComponent(name)}`, {headers:{'X-Studio-Token':token}});
      if (!response.ok) throw new Error(t('api.error.cityResourceReadFailed', { name }));
      return response.arrayBuffer();
    },
    getPrinters: (filter) =>
      raw("GET", "/api/printers" + (filter ? "?filter=" + encodeURIComponent(filter) : "")),
    getShapes: () => raw("GET", "/api/shapes"),
    load: (body) => raw("POST", "/api/load", { json: body || {} }),
    orient: (body) => raw("POST", "/api/orient", { json: body || {} }),
    arrange: (body) => raw("POST", "/api/arrange", { json: body || {} }),
    exportProject: (body) => raw("POST", "/api/export", { json: body || {} }),
    check: (body) => raw("POST", "/api/check", { json: body || {} }),
    send: (body) => raw("POST", "/api/send", { json: body || {} }),
    prepare: (body) => raw("POST", "/api/prepare", { json: body || {} }),
    select: (parts) => raw("POST", "/api/select", { json: { parts: parts || [] } }),
    undo: (id) => raw("POST", "/api/undo", { json: id == null ? {} : { id } }),
    // 通用路径调用，供页面工具（WebMCP）复用同一套接口定义（§8）。
    callPath: (method, path, json) =>
      (method || "GET").toUpperCase() === "GET" ? raw("GET", path) : raw("POST", path, { json: json || {}, actor: "ai" }),
    partStlUrl: (name, rev) => `/api/part/${encodeURIComponent(name)}.stl?rev=${rev}`,
    upload(file, onProgress) {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name));
        if (token) xhr.setRequestHeader("X-Studio-Token", token);
        xhr.setRequestHeader("X-Studio-Actor", "human");
        xhr.upload.onprogress = (e) => {
          if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total);
        };
        xhr.onload = () => {
          let data = null;
          try {
            data = JSON.parse(xhr.responseText);
          } catch (e) {
            data = null;
          }
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(data);
          } else {
            const err = (data && data.error) || {};
            reject(new ApiError(err.code || "http_" + xhr.status, err.message || xhr.statusText || t("api.error.uploadFailed"), data));
          }
        };
        xhr.onerror = () => reject(new ApiError("network_error", t("api.error.uploadNetworkError")));
        xhr.send(file);
      });
    },
    // SSE 订阅；返回 {close()}。onOpen/onClose 用于驱动“断线降级轮询”。
    subscribeEvents(onRev, onOpen, onClose) {
      let es;
      try {
        es = new EventSource("/api/events");
      } catch (e) {
        onClose && onClose(e);
        return { close() {} };
      }
      es.onopen = () => onOpen && onOpen();
      es.onmessage = (ev) => {
        if (!ev.data) return;
        try {
          const d = JSON.parse(ev.data);
          if (d && typeof d.rev === "number") onRev(d.rev);
        } catch (e) {
          /* 保活注释行不是 JSON，忽略 */
        }
      };
      es.onerror = (e) => onClose && onClose(e);
      return {
        close() {
          try {
            es.close();
          } catch (e) {}
        },
      };
    },
  };

  return api;
}
