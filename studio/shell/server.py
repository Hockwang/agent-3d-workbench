"""studio.shell.server —— 本机 HTTP 服务：静态页 + JSON 接口 + SSE（SPEC.md §7）。

只监听 `127.0.0.1`；写操作（load/orient/arrange/export/check/send/prepare）单
飞并阻塞到完成再返回，内部直接调用 `print_prep.cli` 的 `cmd_*` 函数（不起子进
程跑命令行）；状态修订号 `rev` 在任何写操作开始、结束各加一，`GET /api/events`
用它驱动 SSE。

可以当子进程独立运行（`python studio/shell/server.py --job DIR --port N`，由
`studio.start_server()` 拉起），也可以被测试直接 `import` 后调用
`create_httpd()` 在进程内起一个绑定随机端口的实例。
"""

from __future__ import annotations

import argparse
import hmac
import http.server
import json
import mimetypes
import os
import secrets
import sys
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

import studio  # noqa: E402  （PRINT_PREP_HOME 解析 / session 文件读写，两侧共用）
from studio.paths import WEB_DIR  # noqa: E402
from studio.i18n import parse_accept_language, render, reset_language, set_language  # noqa: E402
from studio.shell.app_resources import stamp_language  # noqa: E402
from print_prep import cli  # noqa: E402
from print_prep import job  # noqa: E402
from print_prep import mesh_io  # noqa: E402
from print_prep import shape_table  # noqa: E402
from studio.core import recipes
from studio.core import recipe_progress
from studio.core import history  # noqa: E402
from studio.core import print_state
from studio.shell import tools_schema  # noqa: E402
from studio.core.editor import Workspace, EditorError  # noqa: E402
from studio.core import collaboration  # noqa: E402
from studio.core.tasks import Tasks
from studio.adapters import services  # noqa: E402  （仅用于枚举托管操作 id，不在这里调用任何一个）


def _hosted_task_operations() -> set[str]:
    """`studio_task#<operation>`（比如 image-to-3d）这类步骤要不要算"缺能力"，
    看的是有没有某个 adapter 结构上声明过这个操作，不是这个 provider 当下有没有
    填真实凭据——后者是 `studio_capabilities`/服务列表里 `configured` 字段已经
    在回答的、更窄的另一个问题。所以这里读服务目录（内置 + 用户保存）里每个
    条目声明过的全部 `operations`，不按 `configured` 过滤。

    `services.catalog()` 本身能因为一份读不动的本地连接配置（`connections.private.json`
    损坏）整体抛出（`EditorError`，见 `service_connections.read_store()`）——这个 provider
    是 `recipes.configure()` 注入进 `studio.core.recipes.load_recipes()` 的，那条路径没有
    per-recipe 的 try/except 兜底，一抛就是整批配方都装不出来。降级成"没有任何托管操作"，
    真正的错误仍然能在 `studio_capabilities`/服务设置面板里看到。"""
    ops: set[str] = set()
    try:
        entries = services.catalog()
    except Exception as exc:  # noqa: BLE001 -- 见上面的说明；任何异常都不该拖垮配方装载
        print(f"[studio.shell.server] _hosted_task_operations: services.catalog() failed: {exc!r}", file=sys.stderr)
        return ops
    for entry in entries:
        ops.update(entry.get("operations", ()))
    return ops


# studio.core.recipes 不直接 import studio.shell/studio.adapters（层规则）；这里把
# tools_schema.get_tools 和托管操作枚举都注入进去，让它能拿到当前完整工具列表和
# 服务目录做可用性校验。
recipes.configure(tools_schema.get_tools, _hosted_task_operations)

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_STATIC_ROOT = WEB_DIR

_STATIC_CONTENT_TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8"}


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _shapes_payload() -> dict[str, Any]:
    """`GET /api/shapes` 的响应体：直接读 `print_prep.shape_table`（按
    `VALID_LABELS` 顺序逐个 `lookup`），不在这里另抄一份朝向策略/层高/工艺数值。"""
    return {
        "ok": True,
        "print_submitted": False,
        "shapes": [shape_table.lookup(label) for label in shape_table.VALID_LABELS],
    }


def _recipe_user_dir() -> Path:
    """用户配方目录：`PRINT_PREP_HOME/recipes`（SPEC_RECIPES.md §1）。"""
    return studio.print_prep_home() / "recipes"


def _load_recipe_catalog() -> dict[str, Any]:
    """内置目录先读、用户目录后读（`studio.core.recipes.load_recipes` 本身不取默认
    路径，这里是唯一钉死"生产用哪两个目录"的地方，方便测试整体替换）。"""
    return recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, _recipe_user_dir())


def _recipes_payload() -> dict[str, Any]:
    """`GET /api/recipes` 的响应体（SPEC_RECIPES.md §3.2）。"""
    catalog = _load_recipe_catalog()
    return {
        "ok": True,
        "recipes": recipes.sorted_summaries(catalog),
        "rows": catalog["rows"],
        "problems": catalog["problems"],
    }


def _recipe_payload(recipe_id: Optional[str]) -> dict[str, Any]:
    """`GET /api/recipe?id=`：缺 `id` -> 400 `bad_arguments`；不认识的 `id` ->
    404 `unknown_recipe`（由 `recipes.RecipeError` 统一在 `_cli_call` 里映射）。"""
    if not recipe_id:
        raise cli.UserError(render("server.recipe_missing_id"), code="bad_arguments")
    catalog = _load_recipe_catalog()
    match = recipes.find_recipe(catalog, recipe_id)
    if match is None:
        raise recipes.RecipeError("unknown_recipe", render("server.unknown_recipe", recipe_id=recipe_id), status=404)
    return {"ok": True, "recipe": match}


def _cli_call(fn: Callable[[], dict[str, Any]]) -> tuple[int, dict[str, Any], Optional[dict[str, Any]]]:
    """跑一次 `fn()`（通常是某个 `cli.cmd_*` 调用），统一把 `CliError`/未预期
    异常转成 `(http_status, response_body, error_record)`；成功时
    `error_record` 为 `None`（调用方据此判断要不要清空 `last_error`）。"""
    try:
        result = fn()
        return 200, result, None
    except recipes.RecipeError as exc:
        body = {
            "ok": False,
            "error": {"code": exc.code, "message": str(exc), "params": getattr(exc, "params", {})},
            **exc.payload,
        }
        return exc.status, body, body["error"]
    except EditorError as exc:
        body = {"ok": False, "error": {"code": exc.code, "message": str(exc), "params": getattr(exc, "params", {})}}
        return (409 if exc.code == "revision_conflict" else 400), body, body["error"]
    except history.UndoConflict as exc:
        body: dict[str, Any] = {
            "ok": False,
            "error": {"code": exc.code, "message": str(exc), "params": getattr(exc, "params", {})},
        }
        return 409, body, dict(body["error"])
    except cli.CliError as exc:
        status = 400 if isinstance(exc, cli.UserError) else (502 if isinstance(exc, cli.EnvError) else 500)
        body: dict[str, Any] = {
            "ok": False,
            "error": {"code": exc.code, "message": str(exc), "params": getattr(exc, "params", {})},
        }
        body.update(exc.payload or {})
        return status, body, dict(body["error"])
    except Exception as exc:  # noqa: BLE001 —— 未预期异常也要落成 JSON，不能让 traceback 炸 HTTP 层
        body = {"ok": False, "error": {"code": "unexpected", "message": str(exc), "params": getattr(exc, "params", {})}}
        return 500, body, dict(body["error"])


class StudioBackend:
    """One instance per job directory. Owns state and concurrency: the write
    lock, `rev`/`busy`/`last_error` bookkeeping, the SSE condition variable,
    and the history/recipe/editor/tasks subsystem instances. It does not
    itself implement `print_prep.cli.cmd_*` calls or `/api/state` response
    assembly — those are delegated to `studio.core.print_state` (pure
    functions, no locks); the `api_*`/`build_state` methods here are thin
    wrappers that acquire/release locks around that delegation and record
    the resulting side effects (`sent`, `_delivered`, history, `rev`).

    一个 job 目录对应一个后端实例，持有 `job.json` 之外的全部易变状态；
    `options` 改成每次从 `job.json` 现算，见
    `studio.core.print_state.compute_options`，天然跟着 orient/arrange/export
    的失效级联走。"""

    def __init__(self, job_dir: Path, token: str):
        self.job_dir = Path(job_dir)
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.token = token
        self._cond = threading.Condition()
        self._write_lock = threading.Lock()
        self.rev = 0
        self.busy: Optional[dict[str, Any]] = None
        self.last_error: Optional[dict[str, Any]] = None
        self.sent: Optional[dict[str, Any]] = None
        self._inspect_rev = 0
        self._center_cache: dict[str, Any] = {"sig": None, "centers": {}}
        # SPEC_V05.md §2：操作记录/就绪度/选区。`history_store` 落盘到
        # `<job>/studio_meta.json`；`selection` 只在内存（"没选中时 parts 为
        # []"）；`_delivered` = 本次服务进程里是否真的（非 dry-run）send 成功过，
        # 只有它决定 readiness 的 "deliver" 是 pass 还是 todo。
        self.history_store = history.HistoryStore(self.job_dir)
        self.selection: dict[str, Any] = {"parts": [], "by": None, "at": None}
        self._delivered = False
        self._recipe_catalog = None
        self.editor = Workspace(self.job_dir / "workbench")
        self.tasks = Tasks(self.job_dir / "tasks")
        from studio.core.observation import Observations

        self.observations = Observations(self.tasks)
        from studio.adapters.evaluation import Evaluations

        self.evaluations = Evaluations(self.tasks)

    def api_task(self, body, actor):
        action = body.get("action")
        if action == "upload":
            from studio.core.uploads import upload

            return upload(self.job_dir / "task-inputs", body)
        if action == "open":
            import sys
            import subprocess

            path, _ = self.tasks.artifact(body.get("id"), body.get("artifact_id"))
            if path.suffix.lower() not in (".blend", ".step", ".stp", ".glb", ".stl", ".png", ".jpg", ".html", ".svg"):
                raise EditorError(render("server.task_open_unsupported_type"))
            if sys.platform == "win32":
                os.startfile(str(path))  # no Popen equivalent; opens with the OS default handler
            else:
                command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
                subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "opened": str(path)}
        if action == "start":
            if body.get("from_selection"):
                if body.get("inputs"):
                    raise EditorError(render("server.task_from_selection_conflict"))
                selected = self.editor.state()["selection"]
                if not selected:
                    raise EditorError(render("server.task_select_first"))
                result = self.editor.execute(
                    {
                        "action": "export",
                        "expected_revision": body.get("expected_revision"),
                        "params": {"format": "glb", "ids": selected},
                    },
                    actor,
                )
                body = {**body, "inputs": [result["path"]]}
            result = self.tasks.start(body, actor)
            try:
                self._record_recipe_task(result["task"])
            except Exception as exc:
                result["recipe_warning"] = render("server.recipe_record_not_updated_task", error=str(exc))
            return result
        if action == "rebuild":
            result = self.tasks.rebuild(body, actor)
            try:
                self._record_recipe_task(result["task"])
            except Exception as exc:
                result["recipe_warning"] = render("server.recipe_record_not_updated_task", error=str(exc))
            return result
        if action == "cancel":
            return self.tasks.cancel(body.get("id"))
        if action == "resume":
            return self.tasks.resume(body.get("id"))
        if action == "import":
            path, item = self.tasks.artifact(body.get("id"), body.get("artifact_id"))
            return self.editor.execute(
                {
                    "action": "replace" if body.get("replace_ids") else "import",
                    "expected_revision": body.get("expected_revision"),
                    **({"expected_versions": body["expected_versions"]} if "expected_versions" in body else {}),
                    "params": {
                        "files": [str(path)],
                        **({"ids": body["replace_ids"]} if body.get("replace_ids") else {}),
                    },
                },
                actor,
            )
        raise EditorError(render("server.task_bad_action"))

    # ---------------------------------------------------------------- rev/SSE
    def current_rev(self) -> int:
        with self._cond:
            return self.rev

    def wait_for_rev_change(self, last_seen: int, timeout: float) -> tuple[bool, int]:
        with self._cond:
            changed = self._cond.wait_for(lambda: self.rev != last_seen, timeout=timeout)
            return changed, self.rev

    def mark_inspect_rev(self, rev: int) -> None:
        with self._cond:
            self._inspect_rev = rev

    # ---------------------------------------------------------------- 写操作单飞
    def run_write(
        self,
        op_name: str,
        fn: Callable[[], dict[str, Any]],
        actor: str = "ai",
        request_body: Optional[dict[str, Any]] = None,
        skip_history: Optional[Callable[[dict[str, Any]], bool]] = None,
    ) -> tuple[int, dict[str, Any]]:
        """写操作单飞 + rev/busy/last_error 记账（SPEC.md §7）：拿不到写锁立即
        返回 409，不排队等待；拿到之后阻塞到 `fn()` 完成再返回。SPEC_V05.md
        §2.2/§2.5：这里也是唯一记 history 的地方——`fn()` 执行前后各拍一次
        `job.json` 快照交给 `history_store.record()` 算 summary/stale/
        step_actors，成功后把整份持久化落盘。

        `_inspect_rev` 同样在这里、按 `inspected`（下方，`before_job`/`after_job`
        的 `inspect` 字段是否变了）统一更新——不是只在 `op_name == "load"` 时才
        更新：`prepare` 会重新跑 inspect（可能换了输入），`undo` 也可能把 `inspect`
        撤回到更早的版本，两者都必须让 `_inspect_rev` 跟着刷新，否则前端会拿着
        一个过期的 `inspect_rev` 误判"模型没换"。"""
        if not self._write_lock.acquire(blocking=False):
            with self._cond:
                busy = dict(self.busy) if self.busy else None
            return 409, {
                "ok": False,
                "error": {"code": "busy", "message": render("server.busy"), "params": {}},
                "busy": busy,
            }
        try:
            with self._cond:
                self.busy = {"op": op_name, "since": _iso_now(), "actor": actor}
                self.rev += 1
                self._cond.notify_all()
            before_job = job.load_job(self.job_dir)
            editor_selection_before = list(self.editor.doc["selection"]) if op_name == "edit" else []
            stop_watch = threading.Event()
            watcher = threading.Thread(target=self._watch_job_json, args=(stop_watch,), daemon=True)
            watcher.start()
            try:
                status, body, error_record = _cli_call(fn)
            finally:
                stop_watch.set()
                watcher.join(timeout=2.0)
            after_job = job.load_job(self.job_dir)
            with self._cond:
                if op_name != "edit" and not (error_record is None and skip_history and skip_history(body)):
                    self.history_store.record(op_name, actor, error_record, request_body, body, before_job, after_job)
                self.last_error = {"op": op_name, **error_record} if error_record else None
                self.busy = None
                self.rev += 1
                inspected = before_job.get("inspect") != after_job.get("inspect")
                if error_record is None and inspected:
                    self.mark_inspect_rev(self.rev)
                if inspected or (error_record is None and op_name in ("load", "prepare")):
                    self.selection = {"parts": [], "by": None, "at": None}
                prepared_and_opened = (
                    error_record is None
                    and op_name == "prepare"
                    and any(step.get("step") == "open" for step in body.get("steps", []))
                )
                changed_plan = inspected or (
                    error_record is None and op_name in ("load", "prepare", "orient", "arrange", "export", "undo")
                )
                if changed_plan and not prepared_and_opened:
                    self.sent = None
                    self._delivered = False
                if error_record is None and op_name == "edit":
                    try:
                        self._record_recipe_edit(request_body or {}, body, editor_selection_before)
                    except Exception as exc:
                        # Editing has already succeeded; a recipe failure cannot undo it.
                        body["recipe_warning"] = str(exc)
                self._cond.notify_all()
            self.history_store.save()
            return status, body
        finally:
            self._write_lock.release()

    def _watch_job_json(self, stop: threading.Event, interval_s: float = 0.4) -> None:
        """写操作进行中盯着 job.json：每落一步（inspect/orient/arrange/export…）就推一次 rev，
        面板不用等「一键准备」整条跑完才出画面。job.json 是原子写的，读到的总是完整内容。"""
        path = self.job_dir / "job.json"

        def stamp() -> Optional[int]:
            try:
                return path.stat().st_mtime_ns
            except OSError:
                return None

        last = stamp()
        while not stop.wait(interval_s):
            cur = stamp()
            if cur != last:
                last = cur
                with self._cond:
                    self.rev += 1
                    self._cond.notify_all()

    def call_readonly(self, fn: Callable[[], dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        status, body, _err = _cli_call(fn)
        return status, body

    # ---------------------------------------------------------------- 写接口实现
    # 下面这几个 `api_*` 都是 `studio.core.print_state` 对应函数的薄封装：
    # 那边负责把 body 拼成 `argparse.Namespace` 再调 `print_prep.cli.cmd_*`
    # （纯函数，无锁）；这里只补一件事——记副作用要用的实例状态（`sent`/
    # `_delivered`），因为那两个字段的写入受 `self._cond` 保护，不能下沉到
    # 无锁的 core 层。
    def api_load(self, body: dict[str, Any]) -> dict[str, Any]:
        return print_state.api_load(self.job_dir, body)

    def api_orient(self, body: dict[str, Any]) -> dict[str, Any]:
        return print_state.api_orient(self.job_dir, body)

    def api_arrange(self, body: dict[str, Any]) -> dict[str, Any]:
        return print_state.api_arrange(self.job_dir, body)

    def api_export(self, body: dict[str, Any]) -> dict[str, Any]:
        return print_state.api_export(self.job_dir, body)

    def api_check(self, body: dict[str, Any]) -> dict[str, Any]:
        return print_state.api_check(self.job_dir, body)

    def api_send(self, body: dict[str, Any]) -> dict[str, Any]:
        result, dry_run = print_state.api_send(self.job_dir, body)
        self._record_sent(result, dry_run)
        return result

    def api_select(self, body: dict[str, Any], actor: str) -> tuple[int, dict[str, Any]]:
        """SPEC_V05.md §2.3：不占写锁、不进 history，只更新内存里的 `selection`
        并把 `rev` 加一（SSE 照常推）。"""
        parts = body.get("parts")
        if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
            return 400, {
                "ok": False,
                "error": {"code": "bad_arguments", "message": render("server.select_bad_parts"), "params": {}},
            }
        data = job.load_job(self.job_dir)
        known = {p["name"] for p in (data.get("inspect") or {}).get("parts", [])}
        unknown = [p for p in parts if p not in known]
        if unknown:
            return 400, {
                "ok": False,
                "error": {
                    "code": "unknown_part",
                    "message": render("server.select_unknown_part", unknown=unknown),
                    "params": {},
                },
            }
        with self._cond:
            self.selection = {"parts": list(parts), "by": actor, "at": _iso_now()}
            self.rev += 1
            self._cond.notify_all()
            selection = dict(self.selection)
        return 200, {"ok": True, "print_submitted": False, "selection": selection}

    def api_undo(self, body: dict[str, Any]) -> dict[str, Any]:
        target_id = body.get("id")
        if target_id is not None:
            target_id = print_state.to_int(target_id, "id")
        return self.history_store.perform_undo(self.job_dir, target_id)

    def _get_active_recipe(self) -> Optional[dict[str, Any]]:
        with self._cond:
            return self.history_store.public_active_recipe()

    def _set_active_recipe(self, value: Optional[dict[str, Any]]) -> None:
        with self._cond:
            self.history_store.set_active_recipe(value)

    def api_recipe_use(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        """SPEC_RECIPES.md §3.2 `POST /api/recipe/use`：不作废任何流水线步骤、
        不改 `job.json`，只切换"跟着哪条配方走"这一个状态。响应体里的
        `already_active` 供 `Handler.do_POST` 传给 `run_write` 的
        `skip_history` 钩子判断要不要跳过记 history（幂等重复调用）。"""
        raw_id = body.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raise cli.UserError(render("server.recipe_id_type"), code="bad_arguments")

        current = self._get_active_recipe()

        if raw_id is None:
            already = current is None
            prior_id = current.get("id") if current else None
            title: Optional[str] = None
            if current:
                # 停用这个动作本身（`_set_active_recipe(None)`）绝不能因为查
                # 标题失败而做不成——目录扫不了/配方已被删都只是丢了标题，不
                # 该连"停用"都跟着失败（盲审 1d）。
                try:
                    catalog = self._recipe_catalog = _load_recipe_catalog()
                    match = recipes.find_recipe(catalog, prior_id)
                    title = match["title"] if match else None
                except Exception:  # noqa: BLE001 —— 见上面的注释
                    title = None
            self._set_active_recipe(None)
            # summary 里的 id/title 要带上"被停用的是哪个配方"（盲审 6）：改前
            # 恒为 id=None，配方已被删时标题也是 None，前端就会显示成空的
            # 「停用配方「」」；prior_id 在查标题失败时至少还能显示配方 id。
            return {
                "ok": True,
                "command": "recipe_use",
                "job": str(self.job_dir.resolve()),
                "print_submitted": False,
                "action": "stop",
                "id": prior_id,
                "title": title,
                "already_active": already,
            }

        catalog = self._recipe_catalog = _load_recipe_catalog()
        match = recipes.find_recipe(catalog, raw_id)
        if match is None:
            raise recipes.RecipeError("unknown_recipe", render("server.unknown_recipe", recipe_id=raw_id), status=404)
        if match["availability"] != "ready":
            raise recipes.RecipeError(
                "recipe_unavailable",
                render("server.recipe_unavailable", recipe_id=raw_id, missing_tools=match["missing_tools"]),
                status=409,
                payload={"missing_tools": match["missing_tools"]},
            )

        already = bool(
            current and current.get("id") == raw_id and current.get("content_digest") == match["content_digest"]
        )
        if not already:
            self._set_active_recipe(
                {
                    "id": raw_id,
                    "started_at": _iso_now(),
                    "by": actor,
                    "content_digest": match["content_digest"],
                    "editor_progress": recipe_progress.initial(self.editor.doc),
                }
            )
        return {
            "ok": True,
            "command": "recipe_use",
            "job": str(self.job_dir.resolve()),
            "print_submitted": False,
            "action": "start",
            "id": raw_id,
            "title": match["title"],
            "already_active": already,
        }

    def _build_recipe_state(
        self,
        active_recipe: Optional[dict[str, Any]],
        readiness: dict[str, Any],
        stale: dict[str, Any],
        busy: Optional[dict[str, Any]],
        workbench: dict[str, Any],
        data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """SPEC_RECIPES.md §3.3：没在用配方时为 `null`。读回时该 `id` 已经不
        存在或不再 `ready` -> 当作没在用（不清持久化的值，只是这一刻不展示；
        配方目录之后又变回 `ready` 会自己重新出现，不用用户手动切一次）。"""
        if not active_recipe:
            return None
        catalog = self.recipe_catalog()
        match = recipes.find_recipe(catalog, active_recipe.get("id"))
        if match is None or match["availability"] != "ready":
            return None
        if active_recipe.get("content_digest") and active_recipe["content_digest"] != match["content_digest"]:
            return None
        root = recipes.BUILTIN_RECIPES_DIR if match["source"] == "builtin" else _recipe_user_dir()
        directory = root / match["id"]
        if not recipes._is_plain_dir(directory) or not all(
            recipes._is_plain_file(directory / n) for n in ("recipe.json", "guide.md")
        ):
            return None
        view = recipes.compute_recipe_view(
            match, readiness_items=readiness["items"], stale=stale, busy=busy, print_data=data
        )
        if match.get("workspace") == "edit":
            view = recipe_progress.view(match, active_recipe, workbench, busy)
        elif match.get("workspace") == "tasks":
            from studio.core.task_recipe_progress import view as task_recipe_view

            view = task_recipe_view(match, active_recipe, self.tasks, self.observations)
        return {
            "id": match["id"],
            "title": match["title"],
            "source": match["source"],
            "version": match["version"],
            "started_at": active_recipe.get("started_at"),
            "by": active_recipe.get("by"),
            "steps": view["steps"],
            "next": view["next"],
            "done": view["done"],
            "total": view["total"],
            # SPEC_RECIPES.md §3.3（小补丁）：原样带出 recipe.json 的 one_shot
            # （没有则 null），面板靠它决定要不要显示「一键走完」。
            "one_shot": match.get("one_shot"),
            "workspace": match.get("workspace", "print"),
            "task_template": match.get("task_template"),
            **{
                k: view[k]
                for k in ("task_id", "task_title", "report_sha256", "scope_note", "observation_id")
                if k in view
            },
        }

    def recipe_catalog(self, refresh=False):
        if refresh or self._recipe_catalog is None:
            self._recipe_catalog = _load_recipe_catalog()
        return self._recipe_catalog

    def api_recipes(self):
        catalog = self.recipe_catalog(refresh=True)
        return {
            "ok": True,
            "recipes": recipes.sorted_summaries(catalog),
            "rows": catalog["rows"],
            "problems": catalog["problems"],
        }

    def _record_recipe_edit(self, request, result, selection_before):
        active = self._get_active_recipe()
        if not active:
            return
        match = recipes.find_recipe(self.recipe_catalog(), active["id"])
        if match and match.get("workspace") == "edit" and active.get("content_digest") == match.get("content_digest"):
            recipe_progress.record(match, active, self.editor.doc, request, result, selection_before)
            self._set_active_recipe(active)

    def _record_recipe_task(self, task):
        """Mirrors `_record_recipe_edit` for `workspace: "tasks"` recipes
        (SPEC_RECIPES.md's `studio.core.task_recipe_progress`): called right
        after `api_task`'s `start`/`rebuild` succeeds, never for any other
        task action."""
        active = self._get_active_recipe()
        if not active:
            return
        match = recipes.find_recipe(self.recipe_catalog(), active["id"])
        if match and match.get("workspace") == "tasks" and active.get("content_digest") == match["content_digest"]:
            from studio.core.task_recipe_progress import record_task

            record_task(match, active, task)
            self._set_active_recipe(active)

    def api_observe(self, body, actor):
        """Wraps `Observations.execute` so a `workspace: "tasks"` recipe's
        `appearance` check (`studio.core.task_recipe_progress`) can follow a
        `studio_observe` call the same way `_record_recipe_edit` follows a
        `studio_edit` call — without `studio.core.observation` importing
        anything about recipes itself."""
        result = self.observations.execute(body, actor)
        try:
            if body.get("action") == "start":
                active = self._get_active_recipe()
                progress = (active or {}).get("task_progress") or {}
                if progress.get("task_id"):
                    task = self.tasks.state(progress["task_id"])
                    scene = next((a for a in task["artifacts"] if a["name"] == "scene.glb"), None)
                    if scene and (
                        scene["path"] in body.get("inputs", []) or task["id"] in body.get("source_tasks", [])
                    ):
                        progress["observation_id"] = result["task"]["id"]
                        self._set_active_recipe(active)
            if body.get("action") in ("review", "focus"):
                active = self._get_active_recipe()
                if active and active.get("task_progress"):
                    from studio.core.task_recipe_progress import record_observation

                    record_observation(active, self.tasks, result)
                    self._set_active_recipe(active)
        except Exception as exc:
            result["recipe_warning"] = render("server.recipe_record_not_updated_observe", error=str(exc))
        return result

    def api_prepare(self, body: dict[str, Any]) -> dict[str, Any]:
        result = print_state.api_prepare(self.job_dir, body)
        for step in result.get("steps", []):
            if step.get("step") == "open":
                # `cmd_prepare` 的 open 步骤（SPEC.md §3.8/print_prep/cli.py
                # `cmd_prepare`）恒以 `dry_run=False` 调 `cmd_open`。
                self._record_sent(step["result"], dry_run=False)
        return result

    def _record_sent(self, open_result: dict[str, Any], dry_run: bool) -> None:
        with self._cond:
            self.sent = {
                "plates": [o.get("plate") for o in open_result.get("opened", [])],
                "launched": open_result.get("launched"),
                "loaded": open_result.get("loaded", "unverified"),
                "was_running_before": open_result.get("was_running_before"),
                "at": _iso_now(),
            }
            # SPEC_V05.md §2.2 readiness.deliver: "本次服务进程里成功 send 过
            # （非 dry-run）"——dry-run 的发送不算数。
            if not dry_run:
                self._delivered = True

    # ---------------------------------------------------------------- /api/state
    def build_state(self) -> dict[str, Any]:
        with self._cond:
            rev = self.rev
            busy = dict(self.busy) if self.busy else None
            last_error = dict(self.last_error) if self.last_error else None
            sent = dict(self.sent) if self.sent else None
            inspect_rev = self._inspect_rev
            selection = dict(self.selection)
            delivered = self._delivered
            history_list = self.history_store.public_history()
            step_actors = self.history_store.public_step_actors()
            stale = self.history_store.public_stale()

        # `data`/`readiness` 只算一次——recipe 装配（下面，仍留在这一层，因为
        # 它要碰 `self.editor`/`self.recipe_catalog()`，那些不是 print_state
        # 该知道的东西）和 `print_state.build_state()` 都要用同一份快照，不然
        # 两处可能读到 job.json 前后两个不同版本。
        data = job.load_job(self.job_dir)
        readiness = history.compute_readiness(data, delivered)
        workbench = self.editor.state()
        try:
            recipe_out = self._build_recipe_state(self._get_active_recipe(), readiness, stale, busy, workbench, data)
        except Exception:
            recipe_out = None  # A broken third-party recipe must not break the workspace.

        return print_state.build_state(
            self.job_dir,
            data=data,
            readiness=readiness,
            rev=rev,
            busy=busy,
            last_error=last_error,
            sent=sent,
            inspect_rev=inspect_rev,
            selection=selection,
            history_list=history_list,
            step_actors=step_actors,
            stale=stale,
            workbench=workbench,
            recipe=recipe_out,
            evaluation_focus=self.evaluations.focus(),
            source_centers=self._source_centers,
        )

    def _source_centers(self, inspect_parts: list[dict[str, Any]]) -> dict[str, Optional[list[float]]]:
        """`parts[].source_center_mm`：算一次后缓存，只有 `inspect` 重新跑过
        （落盘的 STL 路径集合变了）才重算，避免每次 `/api/state` 轮询都重新
        载入全部零件的网格。缓存与加锁留在这里——实际的网格载入/中心点计算
        是纯函数，见 `studio.core.print_state.compute_source_centers`。"""
        sig = tuple(p["stl_path"] for p in inspect_parts)
        with self._cond:
            if self._center_cache.get("sig") == sig:
                return self._center_cache["centers"]
        centers = print_state.compute_source_centers(inspect_parts)
        with self._cond:
            self._center_cache = {"sig": sig, "centers": centers}
        return centers


class _ThreadingServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _is_part_stl_path(path: str) -> bool:
    """`/api/part/<name>.stl` — shared by `Handler.do_GET`'s cookie-auth
    decision and its GET prefix-route table, so both stay in sync."""
    return path.startswith("/api/part/") and path.endswith(".stl")


class Handler(http.server.BaseHTTPRequestHandler):
    """HTTP/host plumbing only: this class owns request parsing, the
    Host/Origin/Sec-Fetch-Site/token checks, the GET/POST route tables, SSE,
    and static-file serving. It never touches `print_prep`/domain state
    directly — every handler method is a thin translation from "HTTP request"
    to a call on `StudioBackend` (which in turn may delegate to
    `studio.core.print_state`), and back to an HTTP response.

    默认 `protocol_version = "HTTP/1.0"`（不开 keep-alive）：本机面板请求量
    很小，每条请求独立开关连接换来"响应帧永远精确、不用操心跨请求的连接复用
    状态"，比 HTTP/1.1 keep-alive 简单可靠。"""

    # -------------------------------------------------------------- 工具方法
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 覆写基类签名
        pass  # 保持测试输出干净；真出问题看 studio.log（stderr 已被 Popen 重定向到它）

    def _send_json(self, status: int, obj: dict[str, Any], extra_headers: Optional[dict[str, str]] = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.actual_port  # type: ignore[attr-defined]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _cookie_token(self) -> Optional[str]:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("studio_token="):
                return part[len("studio_token=") :]
        return None

    def _token_ok(self, allow_cookie: bool = False) -> bool:
        """SPEC_V05.md §2.6：默认只认请求头 `X-Studio-Token`。`allow_cookie=True`
        只给 `GET /api/events` 与 `GET /api/part/*.stl` 用——这两处由浏览器自己
        发请求（EventSource、three.js 的加载器），带不了自定义请求头。
        写接口绝不能认 cookie：`SameSite=Strict` 按「站点」算、端口不算，本机别的
        端口上的网页发来的 POST 会带上这个 cookie，认了就等于没有跨站防护。"""
        supplied = self.headers.get("X-Studio-Token") or (self._cookie_token() if allow_cookie else "") or ""
        backend: StudioBackend = self.server.backend  # type: ignore[attr-defined]
        return bool(supplied) and hmac.compare_digest(supplied, backend.token)

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.actual_port  # type: ignore[attr-defined]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _fetch_site_ok(self) -> bool:
        """SPEC_V05.md §2.6：`Sec-Fetch-Site` 存在且不是 `same-origin`/`none`
        （比如 `cross-site`、`same-site`）就拒绝——这是比 `Origin` 头更细的同源
        信号，浏览器几乎总会带上它。"""
        site = self.headers.get("Sec-Fetch-Site")
        if site is None:
            return True
        return site in ("same-origin", "none")

    def _actor(self) -> str:
        """SPEC_V05.md §2.1：`X-Studio-Actor` 取值 `human`/`ai`，缺省或非法值一
        律按 `ai` 记。"""
        raw = (self.headers.get("X-Studio-Actor") or "").strip().lower()
        return raw if raw in ("human", "ai") else "ai"

    def _read_json_body(self) -> Optional[dict[str, Any]]:
        length_header = self.headers.get("Content-Length")
        try:
            n = int(length_header) if length_header else 0
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "bad_json", "message": render("server.bad_json_syntax", exc=exc), "params": {}},
                },
            )
            return None
        if not isinstance(data, dict):
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "bad_json", "message": render("server.bad_json_not_object"), "params": {}},
                },
            )
            return None
        return data

    # ================================================================
    # Route map — every HTTP endpoint this server exposes, in one place.
    # (New to this file? Start here before reading `do_GET`/`do_POST`.)
    #
    # Auth is checked in this order, before any route lookup runs:
    #   1. `Host` header must resolve to 127.0.0.1/localhost on the actual
    #      listening port (`_host_ok`) — else 400 `bad_host`.
    #   2. `GET /api/session` is the one path that skips token auth (it is
    #      what *hands out* the token): it only needs same-origin
    #      Origin/Sec-Fetch-Site (`_origin_ok` + `_fetch_site_ok`).
    #   3. Every other `/api/*` GET requires `X-Studio-Token`, or — for
    #      `/api/events` and `/api/part/*.stl` only — the `studio_token`
    #      cookie (those two are fetched by the browser itself, which can't
    #      attach a custom header): `_token_ok(allow_cookie=...)`.
    #   4. Every POST requires same-origin Origin/Sec-Fetch-Site *and*
    #      `X-Studio-Token` unconditionally — no cookie fallback, since
    #      `SameSite=Strict` is scoped to the site (not the port), so
    #      accepting it on writes would defeat the CSRF check entirely.
    #   5. Paths outside `/api/*` are never token-checked; they are static
    #      files served from `studio/web/` (`_serve_static`).
    #
    # GET
    #   /api/session                        -- token issue + Set-Cookie (see above)
    #   /api/tools /api/workspace-snapshot /api/recipes /api/capabilities
    #   /api/tasks /api/recipe /api/state /api/events /api/printers /api/shapes
    #                                        -- exact matches, `_GET_EXACT_ROUTES`
    #   /api/task-asset/<task_id>/<artifact_id>
    #   /api/city-resource/<digest>/<name>
    #   /api/editor-asset/<id>.glb
    #   /api/part/<name>.stl                -- prefix matches, `_GET_PREFIX_ROUTES`
    #   (anything else under /api/)          -- 404
    #   (anything else)                      -- static file from `studio/web/`
    #
    # POST
    #   /api/upload                          -- raw body (not JSON), needs `?name=`
    #   /api/select /api/collaboration /api/part-chat /api/edit /api/motion
    #   /api/branch-merge /api/evaluation /api/observe /api/task /api/services
    #   /api/recipe/use                      -- exact matches, `_POST_EXACT_ROUTES`
    #   /api/load /api/orient /api/arrange /api/export /api/check /api/send
    #   /api/prepare /api/undo               -- single-flighted through
    #                                            `StudioBackend.run_write`, see
    #                                            `_WRITE_ROUTES`/`_WRITE_ROUTE_MAP`
    #   (anything else)                      -- 404
    # ================================================================

    # -------------------------------------------------------------- GET
    _GET_EXACT_ROUTES: dict[str, str] = {
        "/api/tools": "_get_tools",
        "/api/workspace-snapshot": "_get_workspace_snapshot",
        "/api/recipes": "_get_recipes",
        "/api/capabilities": "_get_capabilities",
        "/api/tasks": "_get_tasks",
        "/api/recipe": "_get_recipe",
        "/api/state": "_get_state",
        "/api/events": "_get_events",
        "/api/printers": "_get_printers",
        "/api/shapes": "_get_shapes",
    }

    # Tried in order once the exact-match table misses. Each predicate takes
    # the raw request path; the matching handler is called as
    # `(backend, path, query)`.
    _GET_PREFIX_ROUTES: tuple[tuple[Callable[[str], bool], str], ...] = (
        (lambda path: path.startswith("/api/task-asset/"), "_get_task_asset"),
        (lambda path: path.startswith("/api/city-resource/"), "_get_city_resource"),
        (lambda path: path.startswith("/api/editor-asset/") and path.endswith(".glb"), "_get_editor_asset"),
        (_is_part_stl_path, "_handle_part"),
    )

    def do_GET(self) -> None:  # noqa: N802 - http.server 的约定命名
        """Per-request language plumbing lives here, wrapping `_dispatch_get`
        (the actual routing logic): `Accept-Language` decides the language
        `EditorError.coded()` renders in for the duration of this one
        request, then the context reverts so it can never leak into the next
        request handled by this thread."""
        token = set_language(parse_accept_language(self.headers.get("Accept-Language")))
        try:
            self._dispatch_get()
        finally:
            reset_language(token)

    def _dispatch_get(self) -> None:
        collaboration.SESSION.set(self.headers.get("X-Studio-Workspace"))
        if not self._host_ok():
            self._send_json(
                400, {"ok": False, "error": {"code": "bad_host", "message": render("server.bad_host"), "params": {}}}
            )
            return
        backend: StudioBackend = self.server.backend  # type: ignore[attr-defined]
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/session":
            self._get_session(backend)
            return

        # SPEC_V05.md §2.6：`/api/session` 之外的其余 GET /api/* 都要求令牌（静
        # 态文件不要求，下面 `path` 不以 "/api/" 开头时不会走到这里）。
        cookie_allowed = path == "/api/events" or _is_part_stl_path(path)
        if path.startswith("/api/") and not (self._fetch_site_ok() and self._token_ok(allow_cookie=cookie_allowed)):
            self._send_json(
                403,
                {"ok": False, "error": {"code": "forbidden", "message": render("server.missing_token"), "params": {}}},
            )
            return

        handler_name = self._GET_EXACT_ROUTES.get(path)
        if handler_name is not None:
            getattr(self, handler_name)(backend, query)
            return
        for matches, prefix_handler_name in self._GET_PREFIX_ROUTES:
            if matches(path):
                getattr(self, prefix_handler_name)(backend, path, query)
                return
        if path.startswith("/api/"):
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {
                        "code": "not_found",
                        "message": render("server.route_not_found", path=path),
                        "params": {},
                    },
                },
            )
            return
        self._serve_static(path)

    def _get_session(self, backend: StudioBackend) -> None:
        if not self._origin_ok() or not self._fetch_site_ok():
            self._send_json(
                403,
                {"ok": False, "error": {"code": "bad_origin", "message": render("server.bad_origin"), "params": {}}},
            )
            return
        cookie = f"studio_token={backend.token}; HttpOnly; SameSite=Strict; Path=/"
        self._send_json(
            200,
            {
                "ok": True,
                "token": backend.token,
                "url": f"http://127.0.0.1:{self.server.actual_port}",  # type: ignore[attr-defined]
                "job": str(backend.job_dir.resolve()),
            },
            extra_headers={"Set-Cookie": cookie},
        )

    def _get_tools(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        self._send_json(200, {"ok": True, "tools": tools_schema.get_tools()})

    def _get_workspace_snapshot(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        import copy

        with backend.editor.lock:
            self._send_json(200, {"ok": True, "document": copy.deepcopy(backend.editor.doc)})

    def _get_recipes(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        status, resp = backend.call_readonly(backend.api_recipes)
        self._send_json(status, resp)

    def _get_capabilities(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        self._send_json(200, backend.tasks.capabilities())

    def _get_tasks(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        task_id = (query.get("id") or [None])[0]
        status, result = backend.call_readonly(
            lambda: {
                "ok": True,
                "observation_focus": backend.observations.focus(),
                **(
                    {"task": backend.tasks.state(task_id, include_log=True)}
                    if task_id
                    else {"tasks": backend.tasks.list()}
                ),
            }
        )
        self._send_json(status, result)

    def _get_task_asset(self, backend: StudioBackend, path: str, query: dict[str, list[str]]) -> None:
        try:
            task_id, artifact_id = path.removeprefix("/api/task-asset/").split("/")
            asset, info = backend.tasks.artifact(task_id, artifact_id)
            raw = asset.read_bytes()
            if query.get("presentation") == ["studio"] and info["mime"] == "text/html":
                from studio.core.viewer_presentation import studio_presentation

                raw = studio_presentation(raw)
            self.send_response(200)
            self.send_header("Content-Type", info["mime"])
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Security-Policy", "sandbox")
            self.end_headers()
            self.wfile.write(raw)
        except (EditorError, ValueError) as exc:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "artifact_error", "message": str(exc), "params": getattr(exc, "params", {})},
                },
            )

    def _get_recipe(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        status, resp = backend.call_readonly(lambda: _recipe_payload((query.get("id") or [None])[0]))
        self._send_json(status, resp)

    def _get_state(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        status, result = backend.call_readonly(backend.build_state)
        self._send_json(status, result)

    def _get_events(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        self._stream_events(backend)

    def _get_printers(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        filter_str = (query.get("filter") or [None])[0]
        status, resp = backend.call_readonly(lambda: cli.cmd_printers(argparse.Namespace(filter=filter_str)))
        self._send_json(status, resp)

    def _get_shapes(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        status, resp = backend.call_readonly(_shapes_payload)
        self._send_json(status, resp)

    def _get_city_resource(self, backend: StudioBackend, path: str, query: dict[str, list[str]]) -> None:
        from studio.core.city import resource

        try:
            digest, name = path.removeprefix("/api/city-resource/").split("/", 1)
            raw = resource(backend.editor, digest, urllib.parse.unquote(name))
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (EditorError, ValueError, KeyError) as exc:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "city_resource", "message": str(exc), "params": getattr(exc, "params", {})},
                },
            )

    def _get_editor_asset(self, backend: StudioBackend, path: str, query: dict[str, list[str]]) -> None:
        try:
            raw = backend.editor.asset_bytes(path[len("/api/editor-asset/") : -4])
        except EditorError as exc:
            self._send_json(
                404,
                {"ok": False, "error": {"code": exc.code, "message": str(exc), "params": getattr(exc, "params", {})}},
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "model/gltf-binary")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_part(self, backend: StudioBackend, path: str, query: dict[str, list[str]]) -> None:
        prefix, suffix = "/api/part/", ".stl"
        encoded = path[len(prefix) : -len(suffix)]
        name = urllib.parse.unquote(encoded)
        data = job.load_job(backend.job_dir)
        inspect_data = data.get("inspect")
        stl_path: Optional[Path] = None
        if inspect_data:
            for p in inspect_data["parts"]:
                if p["name"] == name:
                    stl_path = Path(p["stl_path"])
                    break
        if stl_path is None or not stl_path.is_file():
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {"code": "not_found", "message": render("server.part_not_found", name=name), "params": {}},
                },
            )
            return
        raw = stl_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "model/stl")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        candidate = (_STATIC_ROOT / rel).resolve()
        try:
            candidate.relative_to(_STATIC_ROOT)
        except ValueError:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not candidate.is_file():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ext = candidate.suffix.lower()
        content_type = (
            _STATIC_CONTENT_TYPES.get(ext) or mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        )
        raw = candidate.read_bytes()
        if rel == "index.html":
            raw = stamp_language(raw)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _stream_events(self, backend: StudioBackend) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        last_seen = backend.current_rev()
        try:
            while True:
                changed, current = backend.wait_for_rev_change(last_seen, timeout=15.0)
                if changed:
                    last_seen = current
                    chunk = f"data: {json.dumps({'rev': current})}\n\n".encode("utf-8")
                else:
                    chunk = b": keep-alive\n\n"
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    # -------------------------------------------------------------- POST
    _WRITE_ROUTES = ("load", "orient", "arrange", "export", "check", "send", "prepare", "undo")
    # Precomputed once at class-definition time (was rebuilt on every request
    # before this refactor; `_WRITE_ROUTES` never changes at runtime).
    _WRITE_ROUTE_MAP: dict[str, str] = {f"/api/{name}": name for name in _WRITE_ROUTES}

    _POST_EXACT_ROUTES: dict[str, str] = {
        "/api/select": "_post_select",
        "/api/collaboration": "_post_collaboration",
        "/api/part-chat": "_post_part_chat",
        "/api/edit": "_post_edit",
        "/api/motion": "_post_motion",
        "/api/branch-merge": "_post_branch_merge",
        "/api/evaluation": "_post_evaluation",
        "/api/observe": "_post_observe",
        "/api/task": "_post_task",
        "/api/services": "_post_services",
        "/api/recipe/use": "_post_recipe_use",
    }

    def do_POST(self) -> None:  # noqa: N802
        """See `do_GET` — same per-request language wrapper around `_dispatch_post`."""
        token = set_language(parse_accept_language(self.headers.get("Accept-Language")))
        try:
            self._dispatch_post()
        finally:
            reset_language(token)

    def _dispatch_post(self) -> None:
        collaboration.SESSION.set(self.headers.get("X-Studio-Workspace"))
        if not self._host_ok():
            self._send_json(
                400, {"ok": False, "error": {"code": "bad_host", "message": render("server.bad_host"), "params": {}}}
            )
            return
        # 写请求：别的来源（含本机其他端口上的网页）一律拒绝；命令行与 stdio MCP 不带这两个头，照常放行。
        if not self._origin_ok() or not self._fetch_site_ok():
            self._send_json(
                403,
                {"ok": False, "error": {"code": "bad_origin", "message": render("server.bad_origin"), "params": {}}},
            )
            return
        if not self._token_ok():
            self._send_json(
                403,
                {
                    "ok": False,
                    "error": {"code": "forbidden", "message": render("server.missing_studio_token"), "params": {}},
                },
            )
            return
        backend: StudioBackend = self.server.backend  # type: ignore[attr-defined]
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/upload":
            self._handle_upload(backend, query)
            return

        handler_name = self._POST_EXACT_ROUTES.get(path)
        op_name = None if handler_name is not None else self._WRITE_ROUTE_MAP.get(path)
        if handler_name is None and op_name is None:
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {
                        "code": "not_found",
                        "message": render("server.route_not_found", path=path),
                        "params": {},
                    },
                },
            )
            return

        # Every remaining route reads a JSON body — but only after we know the
        # path is actually recognised, so an unknown path 404s without ever
        # touching (and possibly rejecting) the request body.
        body = self._read_json_body()
        if body is None:
            return  # `_read_json_body` 已经发送了错误响应

        if handler_name is not None:
            getattr(self, handler_name)(backend, body)
            return

        method = getattr(backend, f"api_{op_name}")
        status, result = backend.run_write(op_name, lambda: method(body), actor=self._actor(), request_body=body)
        self._send_json(status, result)

    def _post_select(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        """SPEC_V05.md §2.3：不占写锁、不进 history，绕开 `run_write`。"""
        status, result = backend.api_select(body, self._actor())
        self._send_json(status, result)

    def _post_collaboration(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        status, result = backend.call_readonly(lambda: collaboration.control(backend.editor, body))
        self._send_json(status, result)

    def _post_part_chat(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        from studio.shell.part_chat import handle

        status, result = backend.call_readonly(lambda: handle(backend.editor, body, self._actor()))
        self._send_json(status, result)

    def _post_edit(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        self._run_edit(backend, body)

    def _post_motion(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        self._run_edit(backend, {**body, "action": "motion_" + str(body.get("action", ""))})

    def _run_edit(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        actor = self._actor()
        status, result = backend.run_write(
            "edit", lambda: backend.editor.execute(body, actor), actor=actor, request_body=body
        )
        self._send_json(status, result)

    def _post_branch_merge(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        from studio.core.branches import merge

        actor = self._actor()
        status, result = backend.run_write(
            "edit", lambda: merge(backend.editor, body, actor), actor=actor, request_body={"action": "branch_merge"}
        )
        self._send_json(status, result)

    def _post_evaluation(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        actor = self._actor()
        status, result = backend.call_readonly(lambda: backend.evaluations.execute(body, actor))
        self._send_json(status, result)

    def _post_observe(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        actor = self._actor()
        if body.get("action") == "read":
            status, result = backend.call_readonly(lambda: backend.api_observe(body, actor))
        else:
            status, result = backend.run_write(
                "observe",
                lambda: backend.api_observe(body, actor),
                actor=actor,
                request_body={"action": body.get("action")},
                skip_history=lambda _: True,
            )
        self._send_json(status, result)

    def _post_task(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        actor = self._actor()
        importing = body.get("action") == "import"
        status, result = backend.run_write(
            "edit" if importing else "task",
            lambda: backend.api_task(body, actor),
            actor=actor,
            request_body={"action": "import", "params": {}} if importing else {"action": body.get("action")},
            skip_history=lambda _: not importing,
        )
        self._send_json(status, result)

    def _post_services(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        from studio.adapters.service_connections import execute

        # Configuration has its own atomic lock and no project/history entry.
        status, result = backend.call_readonly(lambda: execute(body))
        self._send_json(status, result)

    def _post_recipe_use(self, backend: StudioBackend, body: dict[str, Any]) -> None:
        actor = self._actor()
        status, result = backend.run_write(
            "recipe",
            lambda: backend.api_recipe_use(body, actor),
            actor=actor,
            request_body=body,
            skip_history=lambda result: bool(result.get("already_active")),
        )
        self._send_json(status, result)

    def _handle_upload(self, backend: StudioBackend, query: dict[str, list[str]]) -> None:
        name = (query.get("name") or [None])[0]
        if not name:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "bad_arguments", "message": render("server.upload_missing_name"), "params": {}},
                },
            )
            return
        safe_name = Path(urllib.parse.unquote(name)).name
        if not safe_name or safe_name in (".", ".."):
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "bad_arguments", "message": render("server.upload_bad_filename"), "params": {}},
                },
            )
            return
        ext = Path(safe_name).suffix.lower()
        if ext not in mesh_io.SUPPORTED_EXTENSIONS:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {
                        "code": "unsupported_extension",
                        "message": render("server.upload_unsupported_extension", ext=ext),
                        "params": {},
                    },
                },
            )
            return
        length_header = self.headers.get("Content-Length")
        if not length_header:
            self._send_json(
                411,
                {
                    "ok": False,
                    "error": {
                        "code": "length_required",
                        "message": render("server.upload_missing_content_length"),
                        "params": {},
                    },
                },
            )
            return
        try:
            n = int(length_header)
        except ValueError:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {
                        "code": "bad_arguments",
                        "message": render("server.upload_bad_content_length"),
                        "params": {},
                    },
                },
            )
            return
        if n > MAX_UPLOAD_BYTES:
            self._drain(n)
            self._send_json(
                413,
                {
                    "ok": False,
                    "error": {
                        "code": "too_large",
                        "message": render("server.upload_too_large", max_bytes=MAX_UPLOAD_BYTES),
                        "params": {},
                    },
                },
            )
            return
        raw = self.rfile.read(n)
        uploads_dir = backend.job_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dest = uploads_dir / safe_name
        dest.write_bytes(raw)
        self._send_json(200, {"ok": True, "path": str(dest.resolve())})

    def _drain(self, n: int) -> None:
        """超限时仍要把请求体读空，否则这条连接上下一次请求解析会错位。"""
        remaining = n
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 1 << 20))
            if not chunk:
                break
            remaining -= len(chunk)


def create_httpd(
    job_dir: Path, port: int = studio.DEFAULT_PORT, token: Optional[str] = None
) -> tuple[_ThreadingServer, int, StudioBackend]:
    """建一个绑定好的 `_ThreadingServer`；`port=0` 让操作系统挑一个空闲端口
    （测试用），非 0 时按 SPEC.md §7"被占则顺延找空闲端口"逐个尝试。"""
    token = token or secrets.token_hex(24)
    backend = StudioBackend(Path(job_dir), token)
    if port == 0:
        httpd = _ThreadingServer(("127.0.0.1", 0), Handler)
    else:
        p = port
        while True:
            try:
                httpd = _ThreadingServer(("127.0.0.1", p), Handler)
                break
            except OSError:
                p += 1
    actual_port = httpd.server_address[1]
    httpd.backend = backend  # type: ignore[attr-defined]
    httpd.actual_port = actual_port  # type: ignore[attr-defined]
    return httpd, actual_port, backend


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="studio.shell.server")
    parser.add_argument("--job", default=None)
    parser.add_argument("--port", type=int, default=studio.DEFAULT_PORT)
    args = parser.parse_args(argv)

    job_dir = Path(args.job).expanduser() if args.job else studio.default_job_dir()
    job_dir.mkdir(parents=True, exist_ok=True)
    httpd, port, backend = create_httpd(job_dir, port=args.port)

    info = {
        "pid": os.getpid(),
        "port": port,
        "token": backend.token,
        "job": str(job_dir.resolve()),
        "url": f"http://127.0.0.1:{port}",
        "started": _iso_now(),
    }
    session_path = studio.session_file_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(info, ensure_ascii=False, indent=1))
    os.chmod(session_path, 0o600)

    print(f"print-prep studio listening on {info['url']} (job={job_dir})", file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if session_path.exists() and json.loads(session_path.read_text()).get("pid") == os.getpid():
                session_path.unlink()
        except (OSError, json.JSONDecodeError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
