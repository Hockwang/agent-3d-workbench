// mock.js — “?mock=1” 下的假后端，供离线自测面板用。
// 不连真实服务；状态全在内存里，写操作只改这份内存并原样落回 /api/state 的形状（SPEC.md §7）。

import { ApiError } from "./api.js";

const JOB_DIR = "/mock/job";

function clone(v) {
  return JSON.parse(JSON.stringify(v));
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function basename(p) {
  const parts = String(p).replace(/\\/g, "/").split("/").filter(Boolean);
  const last = parts[parts.length - 1] || p;
  return last.replace(/\.[^.]+$/, "");
}

function nowIso() {
  return new Date().toISOString();
}

const PRINTERS = [
  {
    name: "Bambu Lab P1S 0.4 nozzle",
    printer_model: "Bambu Lab P1S",
    nozzle_mm: 0.4,
    bed_mm: [256, 256, 250],
    exclude_areas: [[0, 0, 18, 28]],
    default_process: "0.20mm Standard @BBL P1S",
    default_filament: "Bambu PLA Basic @BBL P1S 0.4 nozzle",
  },
  {
    name: "Bambu Lab X1 Carbon 0.4 nozzle",
    printer_model: "Bambu Lab X1 Carbon",
    nozzle_mm: 0.4,
    bed_mm: [256, 256, 256],
    exclude_areas: [],
    default_process: "0.20mm Standard @BBL X1C",
    default_filament: "Bambu PLA Basic @BBL X1C 0.4 nozzle",
  },
];

// 数值须与 print_prep/shape_table.py 一致（mock 没有后端可读，只能内置一份拷贝）。
const SHAPES = [
  { label: "generic", orient_strategy: "support", layer_height_mm: 0.2, process_overrides: {} },
  {
    label: "figurine",
    orient_strategy: "upright",
    layer_height_mm: 0.16,
    process_overrides: {
      enable_support: "1",
      support_type: "tree(auto)",
      support_on_build_plate_only: "0",
      brim_type: "outer_only",
      brim_width: "3",
    },
  },
  { label: "relief", orient_strategy: "flat", layer_height_mm: 0.16, process_overrides: { enable_support: "0" } },
  {
    label: "mechanical",
    orient_strategy: "flat",
    layer_height_mm: 0.2,
    process_overrides: {
      wall_loops: "4",
      sparse_infill_density: "20%",
      enable_support: "1",
      support_type: "normal(auto)",
      support_on_build_plate_only: "1",
    },
  },
];

const TOOLS = [
  {
    name: "studio_get_state",
    description: "只读：读取当前面板状态（零件、朝向、排盘、导出、试切、发送记录）。本工具不会向打印机发送任何东西。",
    inputSchema: { type: "object", properties: {} },
    readOnly: true,
    method: "GET",
    path: "/api/state",
  },
  {
    name: "studio_list_printers",
    description: "只读：列出可用打印机预设。本工具不会向打印机发送任何东西。",
    inputSchema: { type: "object", properties: { filter: { type: "string" } } },
    readOnly: true,
    method: "GET",
    path: "/api/printers",
  },
  {
    name: "studio_load",
    description: "载入一批模型文件并统计几何信息。本工具不会向打印机发送任何东西。",
    inputSchema: {
      type: "object",
      properties: {
        files: { type: "array", items: { type: "string" } },
        printer: { type: "string" },
        scale: { type: "number" },
        target_max_mm: { type: "number" },
        merge: { type: "boolean" },
      },
      required: ["files"],
    },
    readOnly: false,
    method: "POST",
    path: "/api/load",
  },
  {
    name: "studio_orient",
    description: "为已载入的零件选朝向。本工具不会向打印机发送任何东西。",
    inputSchema: {
      type: "object",
      properties: {
        strategy: { type: "string", enum: ["auto", "flat", "support", "upright"] },
        shape: { type: "string", enum: ["generic", "figurine", "relief", "mechanical"] },
        set: { type: "object" },
      },
    },
    readOnly: false,
    method: "POST",
    path: "/api/orient",
  },
  {
    name: "studio_arrange",
    description: "按朝向结果排盘。本工具不会向打印机发送任何东西。",
    inputSchema: {
      type: "object",
      properties: {
        mode: { type: "string", enum: ["single", "per_part", "auto"] },
        gap: { type: "number" },
      },
    },
    readOnly: false,
    method: "POST",
    path: "/api/arrange",
  },
  {
    name: "studio_export",
    description: "写出几何 3MF 并生成 Bambu Studio 工程文件。本工具不会向打印机发送任何东西。",
    inputSchema: {
      type: "object",
      properties: {
        shape: { type: "string" },
        process: { type: "string" },
        filament: { type: "string" },
        set: { type: "object" },
        no_project: { type: "boolean" },
      },
    },
    readOnly: false,
    method: "POST",
    path: "/api/export",
  },
  {
    name: "studio_check",
    description: "无头试切估算克数与时长。本工具不会向打印机发送任何东西。",
    inputSchema: { type: "object", properties: { plate: { type: "integer" } } },
    readOnly: false,
    method: "POST",
    path: "/api/check",
  },
  {
    name: "studio_send_to_bambu",
    description:
      "在 Bambu Studio 图形界面里打开工程文件，停在那里等人确认。loaded 恒为 unverified，不得声称已载入；不会向打印机发送任何东西。",
    inputSchema: {
      type: "object",
      properties: { plate: { type: "integer" }, all: { type: "boolean" }, dry_run: { type: "boolean" } },
    },
    readOnly: false,
    method: "POST",
    path: "/api/send",
  },
  {
    name: "studio_prepare",
    description: "一次跑完载入到导出（可选加试切、发送）。本工具不会向打印机发送任何东西。",
    inputSchema: { type: "object", properties: {}, additionalProperties: true },
    readOnly: false,
    method: "POST",
    path: "/api/prepare",
  },
];

function seededExtents(seed) {
  // 演示用固定几何，不需要真随机；只要几组零件尺寸不同即可。
  const table = {
    body: [60, 40, 120],
    lid: [60, 40, 10],
  };
  return table[seed] || [50, 50, 50];
}

function buildInitialState() {
  const bodyExtents = seededExtents("body");
  const lidExtents = seededExtents("lid");
  const printer = PRINTERS[0];
  const state = {
    ok: true,
    rev: 12,
    print_submitted: false,
    busy: null,
    last_error: null,
    job: JOB_DIR,
    printer: {
      name: printer.name,
      bed_mm: printer.bed_mm,
      exclude_areas: printer.exclude_areas,
      margin_mm: 5,
    },
    options: { shape: "generic", strategy: "auto", mode: "auto", gap: 4 },
    steps: { inspect: true, orient: true, arrange: true, export: true, check: true },
    warnings: [],
    parts: [
      {
        name: "body",
        faces: 994890,
        vertices: 497447,
        extents_mm: bodyExtents,
        volume_cm3: 88.1,
        watertight: true,
        components: 1,
        fits_bed: true,
        suggested_scale: null,
        source_center_mm: [0, 0, 60],
        stl_url: "/mock/body.stl",
        orient: {
          print_up: [0, 0, 1],
          strategy_used: "upright",
          contact_area_mm2: 310.2,
          overhang_area_mm2: 1520.0,
          height_mm: 120.0,
          upright_rejected: false,
          upright_rejected_reason: null,
          warnings: [],
          top_candidates: [
            { print_up: [0, 0, 1], contact_area_mm2: 310.2, overhang_area_mm2: 1520.0, height_mm: 120.0 },
            { print_up: [1, 0, 0], contact_area_mm2: 2400.0, overhang_area_mm2: 860.0, height_mm: 60.0 },
            { print_up: [0, 0, -1], contact_area_mm2: 2400.0, overhang_area_mm2: 2100.0, height_mm: 120.0 },
          ],
        },
      },
      {
        name: "lid",
        faces: 12000,
        vertices: 6002,
        extents_mm: lidExtents,
        volume_cm3: 6.4,
        watertight: true,
        components: 1,
        fits_bed: true,
        suggested_scale: null,
        source_center_mm: [90, 0, 5],
        stl_url: "/mock/lid.stl",
        orient: {
          print_up: [0, 0, 1],
          strategy_used: "flat",
          contact_area_mm2: 2400.0,
          overhang_area_mm2: 0.0,
          height_mm: 10.0,
          upright_rejected: false,
          upright_rejected_reason: null,
          warnings: [],
          top_candidates: [
            { print_up: [0, 0, 1], contact_area_mm2: 2400.0, overhang_area_mm2: 0.0, height_mm: 10.0 },
            { print_up: [0, 0, -1], contact_area_mm2: 2400.0, overhang_area_mm2: 0.0, height_mm: 10.0 },
            { print_up: [1, 0, 0], contact_area_mm2: 600.0, overhang_area_mm2: 1800.0, height_mm: 40.0 },
          ],
        },
      },
    ],
    plates: [
      {
        index: 1,
        parts: ["body", "lid"],
        placements: [
          {
            part: "body",
            T: [
              [1, 0, 0, 70],
              [0, 1, 0, 70],
              [0, 0, 1, 60],
              [0, 0, 0, 1],
            ],
            x_mm: 70,
            y_mm: 70,
            footprint_mm: [60, 40],
          },
          {
            part: "lid",
            T: [
              [1, 0, 0, 150],
              [0, 1, 0, 70],
              [0, 0, 1, 5],
              [0, 0, 0, 1],
            ],
            x_mm: 150,
            y_mm: 70,
            footprint_mm: [60, 40],
          },
        ],
      },
    ],
    export: {
      process_preset: "0.16mm Optimal @BBL P1S 0.4 nozzle",
      filament_preset: "Bambu PLA Basic @BBL P1S 0.4 nozzle",
      overrides: {},
      plates: [
        {
          index: 1,
          project_3mf: JOB_DIR + "/plates/plate_01.project.3mf",
          geometry_3mf: JOB_DIR + "/plates/plate_01.geometry.3mf",
          bambu_moved_objects: false,
          unmatched_parts: [],
        },
      ],
      notes: [],
    },
    check: {
      plates: [{ index: 1, grams: 21.4, seconds: 3120, warnings: [], returncode: 0 }],
    },
    sent: null,
  };
  return state;
}

export function createMockApi() {
  let state = buildInitialState();

  function bump(n) {
    state.rev += n || 1;
  }

  function requireStep(step, message) {
    if (!state.steps[step]) {
      throw new ApiError("bad_arguments", message);
    }
  }

  function invalidateFrom(step) {
    const order = ["inspect", "orient", "arrange", "export", "check"];
    const i = order.indexOf(step);
    for (let k = i + 1; k < order.length; k++) state.steps[order[k]] = false;
    if (i + 1 <= order.indexOf("arrange")) state.plates = null;
    if (i + 1 <= order.indexOf("export")) {
      state.export = null;
      state.sent = null;
    }
    if (i + 1 <= order.indexOf("check")) state.check = null;
  }

  async function doLoad(body) {
    const files = (body && body.files) || [];
    if (!files.length) throw new ApiError("bad_arguments", "未提供任何文件路径");
    bump(1);
    await delay(350);
    const printerName = (body && body.printer) || state.printer.name;
    const printer = PRINTERS.find((p) => p.name === printerName) || PRINTERS[0];
    state.printer = {
      name: printer.name,
      bed_mm: printer.bed_mm,
      exclude_areas: printer.exclude_areas,
      margin_mm: 5,
    };
    const merge = !!(body && body.merge);
    const names = merge ? ["merged"] : files.map((f) => basename(f));
    const seen = new Map();
    state.parts = names.map((raw, idx) => {
      let name = raw;
      const n = (seen.get(raw) || 0) + 1;
      seen.set(raw, n);
      if (n > 1) name = raw + "_" + n;
      const ext = seededExtents(name) || [40 + idx * 5, 40, 40];
      return {
        name,
        faces: 8000 + idx * 1500,
        vertices: 4000 + idx * 750,
        extents_mm: ext,
        volume_cm3: (ext[0] * ext[1] * ext[2]) / 2000,
        watertight: true,
        components: 1,
        fits_bed: true,
        suggested_scale: null,
        source_center_mm: [idx * 90, 0, ext[2] / 2],
        stl_url: "/mock/" + name + ".stl",
        orient: null,
      };
    });
    state.warnings = [];
    state.steps = { inspect: true, orient: false, arrange: false, export: false, check: false };
    state.plates = null;
    state.export = null;
    state.check = null;
    state.sent = null;
    bump(1);
  }

  async function doOrient(body) {
    requireStep("inspect", "尚未载入模型，无法选朝向");
    bump(1);
    await delay(300);
    const strategy = (body && body.strategy) || state.options.strategy || "auto";
    const shape = (body && body.shape) || state.options.shape || "generic";
    const manual = (body && body.set) || {};
    state.options.strategy = strategy;
    state.options.shape = shape;
    for (const part of state.parts) {
      let up = [0, 0, 1];
      let used = strategy === "auto" ? "support" : strategy;
      if (manual[part.name]) {
        const v = manual[part.name];
        const len = Math.hypot(v[0], v[1], v[2]);
        if (!len) throw new ApiError("bad_arguments", "orient --set 不能是零向量：" + part.name);
        up = [v[0] / len, v[1] / len, v[2] / len];
        used = "manual";
      }
      const contact = 2400 * Math.abs(up[2]) + 300;
      part.orient = {
        print_up: up,
        strategy_used: used,
        contact_area_mm2: Number(contact.toFixed(1)),
        overhang_area_mm2: Number((1800 - contact * 0.4).toFixed(1)),
        height_mm: part.extents_mm[2],
        upright_rejected: false,
        upright_rejected_reason: null,
        warnings: contact < 20 ? ["unstable_contact"] : [],
        top_candidates: [
          { print_up: up, contact_area_mm2: Number(contact.toFixed(1)), overhang_area_mm2: 1500.0, height_mm: part.extents_mm[2] },
          { print_up: [0, 0, -1], contact_area_mm2: 2400.0, overhang_area_mm2: 900.0, height_mm: part.extents_mm[2] },
          { print_up: [1, 0, 0], contact_area_mm2: 600.0, overhang_area_mm2: 2000.0, height_mm: part.extents_mm[0] },
        ],
      };
    }
    state.steps.orient = true;
    invalidateFrom("orient");
    bump(1);
  }

  async function doArrange(body) {
    requireStep("orient", "尚未选朝向，无法排盘");
    bump(1);
    await delay(300);
    const mode = (body && body.mode) || state.options.mode || "auto";
    const gap = body && typeof body.gap === "number" ? body.gap : state.options.gap || 4;
    if (gap < 0) throw new ApiError("bad_arguments", "--gap 不能为负数");
    state.options.mode = mode;
    state.options.gap = gap;
    const bed = state.printer.bed_mm;
    const margin = state.printer.margin_mm;
    let x = margin + 40;
    let y = margin + 40;
    const rowH = 60 + gap;
    const plates = [];
    let placements = [];
    let idx = 1;
    for (const part of state.parts) {
      const fp = [part.extents_mm[0], part.extents_mm[1]];
      if (mode === "per_part" && placements.length) {
        plates.push({ index: idx++, parts: placements.map((p) => p.part), placements });
        placements = [];
        x = margin + 40;
        y = margin + 40;
      } else if (x + fp[0] > bed[0] - margin) {
        x = margin + 40;
        y += rowH;
      }
      if (mode === "single" && y + fp[1] > bed[1] - margin) {
        throw new ApiError("bad_arguments", "单盘放不下全部零件，改用 auto 需要 2 盘");
      }
      placements.push({
        part: part.name,
        T: [
          [1, 0, 0, x],
          [0, 1, 0, y],
          [0, 0, 1, part.extents_mm[2] / 2],
          [0, 0, 0, 1],
        ],
        x_mm: x,
        y_mm: y,
        footprint_mm: fp,
      });
      x += fp[0] + gap;
    }
    if (placements.length) plates.push({ index: idx++, parts: placements.map((p) => p.part), placements });
    state.plates = plates;
    state.steps.arrange = true;
    invalidateFrom("arrange");
    bump(1);
  }

  async function doExport(body) {
    requireStep("arrange", "尚未排盘，无法导出");
    bump(1);
    await delay(500);
    const shape = (body && body.shape) || state.options.shape || "generic";
    const overrides = (body && body.set) || {};
    const noProject = !!(body && body.no_project);
    state.export = {
      process_preset: (body && body.process) || "0.16mm Optimal @BBL P1S 0.4 nozzle",
      filament_preset: (body && body.filament) || "Bambu PLA Basic @BBL P1S 0.4 nozzle",
      overrides,
      plates: state.plates.map((pl) => ({
        index: pl.index,
        project_3mf: noProject ? null : `${state.job}/plates/plate_${String(pl.index).padStart(2, "0")}.project.3mf`,
        geometry_3mf: `${state.job}/plates/plate_${String(pl.index).padStart(2, "0")}.geometry.3mf`,
        bambu_moved_objects: false,
        unmatched_parts: [],
      })),
      notes: noProject ? ["--no-project：只写了几何 3MF"] : [],
    };
    state.steps.export = true;
    invalidateFrom("export");
    bump(1);
  }

  async function doCheck(body) {
    requireStep("export", "尚未导出，无法试切");
    bump(1);
    await delay(600);
    const plateFilter = body && body.plate;
    const plates = (state.export.plates || [])
      .filter((p) => !plateFilter || p.index === plateFilter)
      .map((p) => ({
        index: p.index,
        grams: Number((15 + p.index * 6.3).toFixed(2)),
        seconds: 2400 + p.index * 900,
        warnings: [],
        returncode: 0,
      }));
    state.check = { plates };
    state.steps.check = true;
    bump(1);
  }

  async function doSend(body) {
    requireStep("export", "尚未导出，无法发送");
    bump(1);
    await delay(400);
    const dryRun = !!(body && body.dry_run);
    const all = !!(body && body.all);
    const plateIdx = (body && body.plate) || 1;
    const plates = all ? state.export.plates.map((p) => p.index) : [plateIdx];
    state.sent = {
      plates,
      launched: !dryRun,
      loaded: "unverified",
      was_running_before: false,
      at: nowIso(),
    };
    bump(1);
  }

  const api = {
    async init() {
      return { token: "mock-token", url: location.href, job: state.job };
    },
    get token() {
      return "mock-token";
    },
    get job() {
      return state.job;
    },
    async getTools() {
      return clone(TOOLS);
    },
    async getState() {
      return clone(state);
    },
    async getPrinters(filter) {
      let list = PRINTERS;
      if (filter) list = list.filter((p) => p.name.toLowerCase().includes(String(filter).toLowerCase()));
      return { printers: clone(list) };
    },
    async getShapes() {
      return { ok: true, print_submitted: false, shapes: clone(SHAPES) };
    },
    async load(body) {
      try {
        await doLoad(body);
        state.last_error = null;
      } catch (e) {
        state.last_error = { op: "load", code: e.code, message: e.message };
        throw e;
      }
      return clone(state);
    },
    async orient(body) {
      try {
        await doOrient(body);
        state.last_error = null;
      } catch (e) {
        state.last_error = { op: "orient", code: e.code, message: e.message };
        throw e;
      }
      return clone(state);
    },
    async arrange(body) {
      try {
        await doArrange(body);
        state.last_error = null;
      } catch (e) {
        state.last_error = { op: "arrange", code: e.code, message: e.message };
        throw e;
      }
      return clone(state);
    },
    async exportProject(body) {
      try {
        await doExport(body);
        state.last_error = null;
      } catch (e) {
        state.last_error = { op: "export", code: e.code, message: e.message };
        throw e;
      }
      return clone(state);
    },
    async check(body) {
      try {
        await doCheck(body);
        state.last_error = null;
      } catch (e) {
        state.last_error = { op: "check", code: e.code, message: e.message };
        throw e;
      }
      return clone(state);
    },
    async send(body) {
      try {
        await doSend(body);
        state.last_error = null;
      } catch (e) {
        state.last_error = { op: "send", code: e.code, message: e.message };
        throw e;
      }
      return clone(state);
    },
    async prepare(body) {
      body = body || {};
      await doLoad({ files: body.files, printer: body.printer, scale: body.scale, target_max_mm: body.target_max_mm, merge: body.merge });
      await doOrient({ strategy: body.strategy, shape: body.shape, set: body.orient_set });
      await doArrange({ mode: body.mode, gap: body.gap });
      await doExport({ shape: body.shape, process: body.process, filament: body.filament, set: body.export_set, no_project: body.no_project });
      if (body.check) await doCheck({ plate: body.plate });
      if (body.send) await doSend({ plate: body.plate, all: body.all, dry_run: body.dry_run });
      state.last_error = null;
      return clone(state);
    },
    async upload(file) {
      await delay(200);
      return { ok: true, path: "/mock/uploads/" + file.name };
    },
    async callPath(method, path, json) {
      // 页面工具（WebMCP）在 mock 下按路径分发到上面的同一套方法。
      const m = (method || "GET").toUpperCase();
      if (m === "GET" && path.startsWith("/api/state")) return this.getState();
      if (m === "GET" && path.startsWith("/api/printers")) return this.getPrinters((json && json.filter) || null);
      if (m === "POST" && path.startsWith("/api/load")) return this.load(json);
      if (m === "POST" && path.startsWith("/api/orient")) return this.orient(json);
      if (m === "POST" && path.startsWith("/api/arrange")) return this.arrange(json);
      if (m === "POST" && path.startsWith("/api/export")) return this.exportProject(json);
      if (m === "POST" && path.startsWith("/api/check")) return this.check(json);
      if (m === "POST" && path.startsWith("/api/send")) return this.send(json);
      if (m === "POST" && path.startsWith("/api/prepare")) return this.prepare(json);
      throw new ApiError("bad_arguments", "演示模式不支持的路径：" + path);
    },
    partStlUrl(name, rev) {
      return "/mock/" + name + ".stl?rev=" + rev;
    },
    subscribeEvents() {
      // 演示模式没有真实 SSE：写操作后由调用方直接刷新，无需订阅。
      return { close() {} };
    },
  };
  attachV05(api, () => state);
  return api;
}

// ---------------------------------------------------------------------------
// v0.5：记录 / 谁做的 / 前面改了后面作废 / 共享选区 / 撤销。
// 形状照 SPEC_V05.md §2；演示模式下包在上面那套写操作外面，不改它们本身。
// ---------------------------------------------------------------------------
function attachV05(api, getState) {
  const meta = { history: [], step_actors: {}, stale: {}, selection: { parts: [], by: null, at: null }, nextId: 1 };
  const ORDER = ["inspect", "orient", "arrange", "export", "check"];
  const nowIso = () => new Date().toISOString();

  function overhangSum(st) {
    let total = 0;
    let any = false;
    for (const p of st.parts || []) {
      if (p.orient && typeof p.orient.overhang_area_mm2 === "number") {
        total += p.orient.overhang_area_mm2;
        any = true;
      }
    }
    return any ? total : null;
  }
  function checkSummary(st) {
    const plates = ((st.check && st.check.plates) || []).map((p) => ({ index: p.index, grams: p.grams, seconds: p.seconds, warnings: (p.warnings || []).length }));
    return {
      plates,
      grams_total: plates.reduce((a, p) => a + (p.grams || 0), 0),
      seconds_total: plates.reduce((a, p) => a + (p.seconds || 0), 0),
      warnings_total: plates.reduce((a, p) => a + p.warnings, 0),
    };
  }
  function staleSummary(step, st) {
    if (step === "arrange") return { plates: (st.plates || []).length };
    if (step === "export") return { shape: st.options && st.options.shape, process_preset: st.export && st.export.process_preset };
    if (step === "check") return checkSummary(st);
    return {};
  }
  function snapshot(st) {
    return clone({ steps: st.steps, options: st.options, plates: st.plates, orient: (st.parts || []).map((p) => [p.name, p.orient || null]), full: st });
  }
  function push(entry) {
    meta.history.unshift(Object.assign({ id: meta.nextId++, at: nowIso(), undone: false }, entry));
    if (meta.history.length > 50) meta.history.length = 50;
  }
  function record(op, actor, before, body, ok, errorCode) {
    const st = getState();
    if (!ok) {
      push({ actor, op, ok: false, undoable: false, summary: { error: errorCode || "error" } });
      return;
    }
    for (const k of ORDER) {
      if (before.steps[k] && !st.steps[k] && k !== "inspect" && k !== "orient") meta.stale[k] = staleSummary(k, before.full);
      if (st.steps[k]) delete meta.stale[k];
      if (!st.steps[k]) delete meta.step_actors[k];
    }
    const produced = { load: ["inspect"], orient: ["orient"], arrange: ["arrange"], exportProject: ["export"], check: ["check"], prepare: ORDER }[op] || [];
    for (const k of produced) if (st.steps[k]) meta.step_actors[k] = actor;
    let summary = {};
    const b = body || {};
    if (op === "load") {
      meta.stale = {};
      for (const h of meta.history) h.undoable = false;
      summary = { parts: (st.parts || []).length, files: (b.files || []).map((f) => String(f).split("/").pop()) };
    } else if (op === "orient") {
      summary = { strategy: st.options.strategy, shape: st.options.shape, manual_parts: Object.keys(b.set || {}), overhang_mm2_before: overhangSum(before.full), overhang_mm2_after: overhangSum(st) };
    } else if (op === "arrange") summary = { mode: st.options.mode, gap_mm: st.options.gap, plates: (st.plates || []).length };
    else if (op === "exportProject") summary = { shape: st.options.shape, process_preset: st.export && st.export.process_preset, plates: ((st.export && st.export.plates) || []).length };
    else if (op === "check") summary = checkSummary(st);
    else if (op === "send") summary = { plates: (st.sent && st.sent.plates) || [], dry_run: !!b.dry_run };
    else if (op === "prepare") summary = { steps: ORDER.filter((k) => st.steps[k]) };
    const opName = op === "exportProject" ? "export" : op;
    push({ actor, op: opName, ok: true, undoable: opName === "orient" || opName === "arrange", summary, _before: before });
  }

  for (const op of ["load", "orient", "arrange", "exportProject", "check", "send", "prepare"]) {
    const original = api[op].bind(api);
    api[op] = async (body, actor) => {
      const who = actor === "ai" ? "ai" : "human";
      const before = snapshot(getState());
      try {
        await original(body);
      } catch (e) {
        record(op, who, before, body, false, e && e.code);
        throw e;
      }
      record(op, who, before, body, true);
      return api.getState();
    };
  }

  const rawGetState = api.getState.bind(api);
  api.getState = async () => {
    const st = await rawGetState();
    return Object.assign(st, {
      selection: clone(meta.selection),
      step_actors: clone(meta.step_actors),
      stale: clone(meta.stale),
      history: meta.history.map((h) => { const c = Object.assign({}, h); delete c._before; return clone(c); }),
    });
  };

  api.select = async (parts, actor) => {
    const st = getState();
    const names = parts || [];
    const known = new Set((st.parts || []).map((p) => p.name));
    const unknown = names.filter((n) => !known.has(n));
    if (unknown.length) throw new ApiError("unknown_part", "没有这些零件：" + unknown.join("、"));
    meta.selection = { parts: names, by: actor === "ai" ? "ai" : "human", at: nowIso() };
    st.rev += 1;
    return { ok: true, selection: clone(meta.selection) };
  };

  api.undo = async (id, actor) => {
    const target = meta.history.find((h) => h.undoable && !h.undone);
    if (!target) throw new ApiError("nothing_to_undo", "没有可以撤销的操作");
    if (id != null && id !== target.id) throw new ApiError("not_latest", "只能撤销最近一次可撤销的操作");
    const st = getState();
    const was = snapshot(st);
    const before = target._before;
    st.options = clone(before.options);
    st.plates = clone(before.plates);
    const orientByName = new Map(before.orient);
    for (const p of st.parts || []) p.orient = clone(orientByName.get(p.name) || null);
    st.steps.orient = before.steps.orient;
    st.steps.arrange = before.steps.arrange;
    st.steps.export = false;
    st.steps.check = false;
    st.export = null;
    st.check = null;
    st.sent = null;
    st.rev += 2;
    target.undone = true;
    for (const k of ["arrange", "export", "check"]) {
      if (was.steps[k] && !st.steps[k]) meta.stale[k] = staleSummary(k, was.full);
      if (!st.steps[k]) delete meta.step_actors[k];
    }
    if (!st.steps.orient) delete meta.step_actors.orient;
    push({ actor: actor === "ai" ? "ai" : "human", op: "undo", ok: true, undoable: false, summary: { target_id: target.id, target_op: target.op } });
    return api.getState();
  };

  api.callPath = async (method, path, json) => {
    const m = (method || "GET").toUpperCase();
    if (m === "GET" && path.startsWith("/api/state")) return api.getState();
    if (m === "GET" && path.startsWith("/api/printers")) return api.getPrinters((json && json.filter) || null);
    const route = { "/api/load": "load", "/api/orient": "orient", "/api/arrange": "arrange", "/api/export": "exportProject", "/api/check": "check", "/api/send": "send", "/api/prepare": "prepare" };
    if (m === "POST" && path.startsWith("/api/select")) return api.select((json && json.parts) || [], "ai");
    if (m === "POST" && path.startsWith("/api/undo")) return api.undo(json && json.id, "ai");
    for (const [prefix, name] of Object.entries(route)) if (m === "POST" && path.startsWith(prefix)) return api[name](json, "ai");
    throw new ApiError("bad_arguments", "演示模式不支持的路径：" + path);
  };

  // 演示数据一上来就是整条流程跑完的样子；补几条记录，让「谁做的」和「记录」有内容可看。
  const st0 = getState();
  if (st0.steps && st0.steps.inspect) {
    const t0 = Date.now() - 9 * 60000;
    const seed = [
      ["human", "load", { parts: (st0.parts || []).length, files: ["demo_kit.glb"] }],
      ["ai", "orient", { strategy: st0.options.strategy, shape: st0.options.shape, manual_parts: [], overhang_mm2_before: null, overhang_mm2_after: overhangSum(st0) }],
      ["ai", "arrange", { mode: st0.options.mode, gap_mm: st0.options.gap, plates: (st0.plates || []).length }],
      ["ai", "export", { shape: st0.options.shape, process_preset: st0.export && st0.export.process_preset, plates: ((st0.export && st0.export.plates) || []).length }],
      ["ai", "check", checkSummary(st0)],
    ];
    seed.forEach(([actor, op, summary], i) => {
      meta.history.unshift({ id: meta.nextId++, at: new Date(t0 + i * 90000).toISOString(), actor, op, ok: true, undoable: false, undone: false, summary });
    });
    meta.step_actors = { inspect: "human", orient: "ai", arrange: "ai", export: "ai", check: "ai" };
  }
}
