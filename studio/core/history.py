"""studio.core.history —— 操作记录 / 快照 / stale / 就绪度 / 持久化（SPEC_V05.md §2）。

`StudioBackend.run_write()`（`studio/shell/server.py`）在这一处统一记账：写操作开始前
（`fn()` 执行前）取一次 `job.json` 快照，写操作结束后再取一次，交给这里的
`HistoryStore.record()` 算 `summary`/`stale`/`step_actors` 并落盘持久化
（`<job>/studio_meta.json`，原子写，与 `print_prep.job.save_job` 同款写法）。

`selection`（人在视口里点中的零件）只在 `StudioBackend` 内存里，不经过这里；
`readiness`（就绪度）是纯函数 `compute_readiness()`，只读 `job.json` 的内容 +
"本次进程是否真的发送过"这一个布尔值，不需要额外状态。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Optional

from print_prep import job as job_mod
from studio.i18n import render

_MAX_HISTORY = 50

# 只有这两种写操作改的是"纯 job.json 状态"（不落别的文件），所以只有它们可撤销
# （SPEC_V05.md §2.3）。
_UNDOABLE_OPS = ("orient", "arrange")
# 撤销时从快照还原的 job.json 段落；排在它们后面的 export / check 按失效级联删掉。
_UNDO_RESTORED_STEPS = ("orient", "arrange")

# 路由层的 op 名 -> 它直接产出的 job.json 步骤名（STEP_ORDER 里的名字）。
# "load" 路由对应 "inspect" 步骤，单独在 `HistoryStore.record()` 里处理（它还要
# 清空 stale/step_actors，不能套用这张通用表）。
_OP_TO_STEP = {"orient": "orient", "arrange": "arrange", "export": "export", "check": "check"}


class UndoConflict(Exception):
    """SPEC_V05.md §2.3 的 409 情形：不是参数错（400）也不是环境错（502），是
    "当前没有可执行的撤销"这个状态冲突。`studio.shell.server._cli_call` 识别这个类型
    后映射成 HTTP 409，`code` 就是响应里 `error.code` 的值
    （`"not_latest"` / `"nothing_to_undo"`）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _iso_now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 每步的小摘要：只读 job.json 里该步骤自己的那一段数据，不依赖请求体/响应体。
# 两处复用：① 该步骤自己成功执行时的 history 摘要；② 该步骤被失效级联删掉时，
# 存进 `stale` 的"它被删之前长什么样"。
# ---------------------------------------------------------------------------


def _step_summary(step: str, data: dict[str, Any]) -> dict[str, Any]:
    if step == "orient":
        parts = data.get("parts") or {}
        overhang_after = sum(float(p.get("overhang_area_mm2") or 0.0) for p in parts.values())
        manual_parts = [name for name, p in parts.items() if p.get("strategy_used") == "manual"]
        return {
            "strategy": data.get("strategy"),
            "shape": data.get("shape"),
            "manual_parts": manual_parts,
            "overhang_mm2_after": round(overhang_after, 3),
        }
    if step == "arrange":
        return {"mode": data.get("mode"), "gap_mm": data.get("gap_mm"), "plates": len(data.get("plates") or [])}
    if step == "export":
        return {
            "shape": data.get("shape"),
            "process_preset": data.get("process_preset"),
            "plates": len(data.get("plates") or []),
        }
    if step == "check":
        return _check_summary(data)
    return {}


def _check_summary(check_data: dict[str, Any]) -> dict[str, Any]:
    plates_out: list[dict[str, Any]] = []
    grams_total = 0.0
    seconds_total = 0.0
    warnings_total = 0
    for r in check_data.get("plates") or []:
        warns = r.get("warnings") or []
        grams = r.get("grams")
        seconds = r.get("seconds")
        plates_out.append({"index": r.get("plate"), "grams": grams, "seconds": seconds, "warnings": len(warns)})
        if grams is not None:
            grams_total += float(grams)
        if seconds is not None:
            seconds_total += float(seconds)
        warnings_total += len(warns)
    return {
        "plates": plates_out,
        "grams_total": round(grams_total, 3),
        "seconds_total": seconds_total,
        "warnings_total": warnings_total,
    }


def _compute_stale(before_job: dict[str, Any], after_job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """这次写操作新增的 stale 项：`before_job` 里有、`after_job` 里因为失效级联
    被删掉的步骤，值是它被删之前（也就是 `before_job` 里）的摘要。调用方负责
    跟已有的 `stale` 字典合并，以及把"这次又重新跑过"的步骤从里面摘掉。"""
    out: dict[str, dict[str, Any]] = {}
    for step in job_mod.STEP_ORDER:
        if step in before_job and step not in after_job:
            out[step] = _step_summary(step, before_job[step])
    return out


def _steps_produced(op: str, result_body: dict[str, Any]) -> list[str]:
    """这次成功的写操作实际产出了 job.json 里的哪些步骤（用来更新
    `step_actors`）。"""
    if op in _OP_TO_STEP:
        return [_OP_TO_STEP[op]]
    if op == "prepare":
        return [s.get("step") for s in (result_body or {}).get("steps", []) if s.get("step") in job_mod.STEP_ORDER]
    if op == "undo":
        return []  # 撤销不「产出」步骤：还原回来的段落仍算原来那个人做的，见 HistoryStore.record()
    return []  # "send" 不产出 job.json 里的任何步骤


def _build_summary(
    op: str,
    *,
    ok: bool,
    error_code: Optional[str],
    request_body: dict[str, Any],
    result_body: dict[str, Any],
    before_job: dict[str, Any],
    after_job: dict[str, Any],
) -> dict[str, Any]:
    """SPEC_V05.md §2.2 `history[].summary`：按操作给小而稳定的数字。失败的操作
    也记一条，`summary` 固定为 `{"error": 错误码}`。"""
    if not ok:
        return {"error": error_code or "error"}
    if op == "load":
        files = [os.path.basename(str(f)) for f in (request_body or {}).get("files") or []]
        parts_n = len((after_job.get("inspect") or {}).get("parts") or [])
        return {"parts": parts_n, "files": files}
    if op == "orient":
        summary = _step_summary("orient", after_job.get("orient") or {})
        before_orient = before_job.get("orient")
        summary["overhang_mm2_before"] = (
            round(sum(float(p.get("overhang_area_mm2") or 0.0) for p in (before_orient.get("parts") or {}).values()), 3)
            if before_orient
            else None
        )
        return summary
    if op in ("arrange", "export"):
        return _step_summary(op, after_job.get(op) or {})
    if op == "check":
        return _step_summary("check", after_job.get("check") or {})
    if op == "send":
        plates = [o.get("plate") for o in (result_body or {}).get("opened") or []]
        return {"plates": plates, "dry_run": bool((request_body or {}).get("dry_run", False))}
    if op == "prepare":
        return {"steps": [s.get("step") for s in (result_body or {}).get("steps") or []]}
    if op == "recipe":
        return {k: (result_body or {}).get(k) for k in ("action", "id", "title")}
    if op == "undo":
        return {"target_id": (result_body or {}).get("target_id"), "target_op": (result_body or {}).get("target_op")}
    return {}


class HistoryStore:
    """一个 job 目录对应一个实例；`history`/`step_actors`/`stale`/撤销快照落盘到
    `<job>/studio_meta.json`（`selection` 不在这里，只在 `StudioBackend` 内存）。
    调用方（`StudioBackend`）负责用它自己的 `self._cond` 把 `record()`/
    `perform_undo()` 对内存态的修改跟并发的 `GET /api/state` 读取序列化好——这
    个类本身不做线程同步。
    """

    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.history: list[dict[str, Any]] = []
        self.step_actors: dict[str, str] = {}
        self.stale: dict[str, dict[str, Any]] = {}
        self._undo_snapshots: dict[int, dict[str, Any]] = {}
        self.active_recipe = None
        self._next_id = 1
        self._load()

    # ------------------------------------------------------------ 持久化
    def _meta_path(self) -> Path:
        return self.job_dir / "studio_meta.json"

    def _load(self) -> None:
        path = self._meta_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return  # 文件坏了就当没有记录，服务照常起来
        active = raw.get("active_recipe")
        self.active_recipe = active if isinstance(active, dict) and active.get("id") else None
        self.history = raw.get("history") or []
        self.step_actors = raw.get("step_actors") or {}
        self.stale = raw.get("stale") or {}
        try:
            self._undo_snapshots = {int(k): v for k, v in (raw.get("undo_snapshots") or {}).items()}
        except (TypeError, ValueError, AttributeError):
            self._undo_snapshots = {}
            for entry in self.history if isinstance(self.history, list) else []:
                if isinstance(entry, dict):
                    entry["undoable"] = False
        if not isinstance(self.history, list):
            self.history = []
        if not isinstance(self.step_actors, dict):
            self.step_actors = {}
        if not isinstance(self.stale, dict):
            self.stale = {}
        self._next_id = raw.get("next_id") or (max((e.get("id", 0) for e in self.history), default=0) + 1)

    def save(self) -> None:
        """把当前内存态整份落盘（原子写）。`undo_snapshots` 不在 SPEC_V05.md §2.5
        明确列出的三个字段里，但撤销要在服务重启后仍然可用就必须带上它——否则
        `history[].undoable: true` 会在重启后变成一句谎话。"""
        path = self._meta_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_recipe": self.active_recipe,
            "next_id": self._next_id,
            "history": self.history,
            "step_actors": self.step_actors,
            "stale": self.stale,
            "undo_snapshots": {str(k): v for k, v in self._undo_snapshots.items()},
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
        os.replace(tmp, path)

    # ------------------------------------------------------------ 只读投影
    def public_history(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.history)

    def public_step_actors(self) -> dict[str, str]:
        return dict(self.step_actors)

    def public_stale(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self.stale)

    # ------------------------------------------------------------ 记账
    def public_active_recipe(self) -> Optional[dict[str, Any]]:
        return copy.deepcopy(self.active_recipe) if self.active_recipe else None

    def set_active_recipe(self, value: Optional[dict[str, Any]]) -> None:
        """SPEC_RECIPES.md §3.3：只存 `id`/`started_at`/`by` 三个字段；
        `value=None` 表示停用。调用方（`StudioBackend`）负责用它自己的
        `self._cond` 做线程同步，这个方法本身不加锁。"""
        self.active_recipe = copy.deepcopy(value) if value else None

    def record(
        self,
        op: str,
        actor: str,
        error: Optional[dict[str, Any]],
        request_body: Optional[dict[str, Any]],
        result_body: Optional[dict[str, Any]],
        before_job: dict[str, Any],
        after_job: dict[str, Any],
    ) -> dict[str, Any]:
        """插入一条新的 history 记录，并按 SPEC_V05.md §2.2/§2.5 更新
        `step_actors`/`stale`（`load` 成功时整个清空并让此前记录一律不可撤销）。
        返回新插入的记录（深拷贝，调用方可以随便处理不会污染内部状态）。"""
        ok = error is None
        error_code = error.get("code") if error else None
        summary = _build_summary(
            op,
            ok=ok,
            error_code=error_code,
            request_body=request_body or {},
            result_body=result_body or {},
            before_job=before_job,
            after_job=after_job,
        )
        undoable = ok and op in _UNDOABLE_OPS

        entry_id = self._next_id
        self._next_id += 1
        entry: dict[str, Any] = {
            "id": entry_id,
            "at": _iso_now(),
            "actor": actor,
            "op": op,
            "ok": ok,
            "undoable": undoable,
            "undone": False,
            "summary": summary,
        }
        if undoable:
            step = _OP_TO_STEP[op]
            # 撤销要同时还原 orient / arrange 两段（SPEC_V05.md §2.3）：重新选朝向会把分盘级联删掉，
            # 只还原 orient 一段的话分盘就回不来了。这两段都只在 job.json 里，从同一份快照还原是自洽的。
            self._undo_snapshots[entry_id] = {
                "step": step,
                "prior_job": {k: copy.deepcopy(before_job.get(k)) for k in _UNDO_RESTORED_STEPS},
                "prior_actors": {k: self.step_actors.get(k) for k in _UNDO_RESTORED_STEPS},
            }

        self.history.insert(0, entry)
        if len(self.history) > _MAX_HISTORY:
            for evicted in self.history[_MAX_HISTORY:]:
                self._undo_snapshots.pop(evicted.get("id"), None)
            self.history = self.history[:_MAX_HISTORY]

        inspected = before_job.get("inspect") != after_job.get("inspect")
        # prepare starts with inspect, even when a later export/check fails.
        # Snapshots from the previous model must never be applied to this one.
        new_model = inspected or (ok and op in ("load", "prepare"))
        if ok or inspected:
            if new_model:
                self.stale = {}
                self.step_actors = {step: actor for step in job_mod.STEP_ORDER if step in after_job}
                self._undo_snapshots.clear()
                for other in self.history[1:]:
                    other["undoable"] = False
            else:
                for step in job_mod.STEP_ORDER:
                    if step not in after_job:
                        self.step_actors.pop(step, None)
                for step in _steps_produced(op, result_body or {}):
                    self.step_actors[step] = actor
                if op == "undo":
                    restored = getattr(self, "_pending_restored_actors", None) or {}
                    for step, who in restored.items():
                        if step in after_job and who:
                            self.step_actors[step] = who
                    self._pending_restored_actors = None
                new_stale = _compute_stale(before_job, after_job)
                if op == "undo":
                    # 撤销是用户明说的动作，不是失效级联：被它拿掉的 orient / arrange 不算「要重做」。
                    for key in _UNDO_RESTORED_STEPS:
                        new_stale.pop(key, None)
                self.stale.update(new_stale)
                for step in job_mod.STEP_ORDER:
                    if step in after_job:
                        self.stale.pop(step, None)

        return copy.deepcopy(entry)

    # ------------------------------------------------------------ 撤销
    def perform_undo(self, job_dir: Path, target_id: Optional[int]) -> dict[str, Any]:
        """SPEC_V05.md §2.3：还原最近一条"可撤销且还没撤销"的记录（或校验
        `target_id` 就是那一条），把 `job.json` 里对应的步骤还原成快照，并按
        `STEP_ORDER` 失效级联删掉排在它后面的步骤。成功时返回的字典就是
        `POST /api/undo` 的响应体（`run_write` 会原样发回，也会被当作
        `result_body` 传给 `record()` 去抽 `target_id`/`target_op`）。"""
        candidates = [e for e in self.history if e.get("undoable") and not e.get("undone")]
        if not candidates:
            raise UndoConflict("nothing_to_undo", render("history.nothing_to_undo"))
        latest = candidates[0]  # history 新的在前
        if target_id is not None and latest["id"] != target_id:
            raise UndoConflict("not_latest", render("history.not_latest", target_id=target_id, latest_id=latest["id"]))

        entry_id = latest["id"]
        snapshot = self._undo_snapshots.get(entry_id)
        if snapshot is None:
            # 理论上不该发生——undoable 蕴含记 record() 时一定存过快照；只是防御。
            raise UndoConflict("nothing_to_undo", render("history.undo_snapshot_missing"))
        step = snapshot["step"]

        data = job_mod.load_job(job_dir)
        prior_job = snapshot.get("prior_job")
        if prior_job is None:  # 旧格式的快照（只存了被撤销的那一段）
            prior_job = {step: snapshot.get("prior_job_step")}
        for key in _UNDO_RESTORED_STEPS:
            if key not in prior_job:
                continue
            if prior_job[key] is None:
                data.pop(key, None)
            else:
                data[key] = copy.deepcopy(prior_job[key])
        job_mod.invalidate_from(data, "export")
        job_mod.save_job(job_dir, data)
        self._pending_restored_actors = dict(snapshot.get("prior_actors") or {})

        latest["undone"] = True
        latest["undoable"] = False

        return {
            "ok": True,
            "command": "undo",
            "job": str(Path(job_dir).resolve()),
            "print_submitted": False,
            "target_id": entry_id,
            "target_op": step,
        }


# ---------------------------------------------------------------------------
# 就绪度：纯函数，只读 job.json 的内容 + "本次进程是否真的 send 过（非
# dry-run）"这一个布尔值（SPEC_V05.md §2.2 readiness）。
# ---------------------------------------------------------------------------


def compute_readiness(data: dict[str, Any], delivered: bool) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    inspect_data = data.get("inspect")
    if not inspect_data:
        items.append({"key": "model", "status": "todo", "detail": ""})
    else:
        parts = inspect_data.get("parts") or []
        bad_parts = [p for p in parts if not p.get("watertight") or not p.get("fits_bed")]
        inspect_warnings = inspect_data.get("warnings") or []
        if bad_parts or inspect_warnings:
            reasons = []
            if bad_parts:
                reasons.append(render("history.readiness_bad_parts", count=len(bad_parts)))
            if inspect_warnings:
                reasons.append(render("history.readiness_warnings", count=len(inspect_warnings)))
            items.append(
                {"key": "model", "status": "warn", "detail": render("history.readiness_separator").join(reasons)}
            )
        else:
            items.append(
                {"key": "model", "status": "pass", "detail": render("history.readiness_model_pass", count=len(parts))}
            )

    orient_data = data.get("orient")
    if not orient_data:
        items.append({"key": "orient", "status": "todo", "detail": ""})
    else:
        n_warn = sum(1 for p in (orient_data.get("parts") or {}).values() if p.get("warnings"))
        if n_warn:
            items.append(
                {"key": "orient", "status": "warn", "detail": render("history.readiness_orient_warn", count=n_warn)}
            )
        else:
            items.append({"key": "orient", "status": "pass", "detail": ""})

    arrange_data = data.get("arrange")
    items.append({"key": "arrange", "status": "pass" if arrange_data else "todo", "detail": ""})

    export_data = data.get("export")
    if not export_data:
        items.append({"key": "export", "status": "todo", "detail": ""})
    else:
        n_warn = sum(
            1 for p in (export_data.get("plates") or []) if p.get("unmatched_parts") or p.get("used_slice_fallback")
        )
        if n_warn:
            items.append(
                {"key": "export", "status": "warn", "detail": render("history.readiness_export_warn", count=n_warn)}
            )
        else:
            items.append({"key": "export", "status": "pass", "detail": ""})

    check_data = data.get("check")
    if not check_data:
        items.append({"key": "check", "status": "todo", "detail": ""})
    else:
        plates = check_data.get("plates") or []
        n_warn = sum(len(p.get("warnings") or []) for p in plates)
        n_warn += sum(1 for p in plates if p.get("returncode") not in (0, None) and not p.get("warnings"))
        if n_warn:
            items.append(
                {"key": "check", "status": "warn", "detail": render("history.readiness_warnings", count=n_warn)}
            )
        else:
            items.append({"key": "check", "status": "pass", "detail": ""})

    items.append({"key": "deliver", "status": "pass" if delivered else "todo", "detail": ""})

    passed = sum(1 for it in items if it["status"] == "pass")
    return {"passed": passed, "total": len(items), "items": items}
