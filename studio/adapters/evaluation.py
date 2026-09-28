"""Native workbench adapter for the optional, key-gated Assembly Evaluation
Dashboard API.

The dashboard owns batches, metrics and review history. This module stores only
connection preferences, focus and exported evidence in the current local job.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from studio.core.editor import EditorError, _atomic
from studio.i18n import render

SOURCE_COMMIT = "ebd731c125e5cc79dfff20f815a91e4120aa1e8b"
READS = {
    "health": "/api/health",
    "batches": "/api/result-batches",
    "analyses": "/api/analysis-views",
    "dimensions": "/api/result-dimensions",
    "issue_tags": "/api/review-issue-tags",
    "test_sets": "/api/test-sets",
    "cases": "/api/cases",
    "bad_cases": "/api/bad-cases",
    "batch": "/api/result-batches/{id}",
    "analysis": "/api/analysis-views/{id}",
    "case": "/api/case-runs/{id}",
    "comparison": "/api/analysis-views/{id}/comparisons/{group_id}",
    "review_data": "/api/analysis-views/{id}/review-data",
    "reports": "/api/analysis-views/{id}/reports",
    "report": "/api/analysis-reports/{id}",
    "analysis_job": "/api/analysis-jobs/{id}",
    "diagnostic": "/api/case-runs/{id}/diagnostic-context",
    "nodes": "/api/case-runs/{id}/nodes",
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def compact(resource, value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if resource == "analysis":
        result.pop("batch_analytics", None)
        result.pop("batches", None)
        score = dict(result.get("release_scorecard") or {})
        score["conditions"] = [
            {k: v for k, v in c.items() if k not in {"slices", "category_slices", "case_results"}}
            for c in score.get("conditions", [])
        ]
        result["release_scorecard"] = score
    elif resource == "report":
        result = {
            k: v
            for k, v in result.items()
            if k
            in {
                "report_id",
                "snapshot_id",
                "analysis_view_id",
                "status",
                "review_status",
                "title",
                "error_message",
                "markdown_text",
            }
        }
    return result


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value) or value in {".", ".."}:
        raise EditorError.coded("evaluation.invalid_record_id")
    return urllib.parse.quote(value, safe="")


def connection(value):
    url = str(value.get("base_url") or "").strip().rstrip("/")
    p = urllib.parse.urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise EditorError.coded("evaluation.connection_url_invalid")
    if any(c.isspace() or ord(c) < 32 for c in url) or ".." in p.path.split("/") or "%" in p.path:
        raise EditorError.coded("evaluation.connection_path_invalid")
    if p.path.endswith("/api"):
        url = url[:-4]
    auth_env = str(value.get("auth_env") or "")
    if auth_env and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", auth_env):
        raise EditorError.coded("evaluation.auth_env_invalid")
    return {"base_url": url, "auth_env": auth_env}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, settings):
        self.settings = connection(settings)

    def request(self, path, method="GET", data=None, *, binary=False, limit=20 * 1024 * 1024, content_type=None):
        # Only application-owned endpoint builders can call this transport.
        if not path.startswith(("/api/", "/viewer/")) or ".." in path.split("/") or "\\" in path:
            raise EditorError.coded("evaluation.client_path_invalid")
        headers = {"Accept": "*/*" if binary else "application/json"}
        name = self.settings["auth_env"]
        if name:
            token = os.environ.get(name)
            if not token:
                raise EditorError.coded("evaluation.missing_env_var", name=name)
            headers["Authorization"] = "Bearer " + token
        raw = None
        if data is not None:
            raw = data if content_type else json.dumps(data, allow_nan=False).encode()
            headers["Content-Type"] = content_type or "application/json"
        req = urllib.request.Request(self.settings["base_url"] + path, data=raw, headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=90) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise EditorError.coded("evaluation.response_too_large")
            return raw if binary else json.loads(raw)
        except urllib.error.HTTPError as exc:
            # Redirects never forward credentials to another host. Do not include
            # signed URLs, auth headers or arbitrary upstream HTML in errors.
            raise EditorError.coded("evaluation.platform_http_error", status=exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise EditorError.coded("evaluation.connection_failed") from None
        except (ValueError, UnicodeError):
            raise EditorError.coded("evaluation.invalid_json_response") from None

    def read(self, resource, id=None, group_id=None):
        if resource not in READS:
            raise EditorError.coded("evaluation.unsupported_resource")
        path = READS[resource]
        if "{id}" in path:
            path = path.replace("{id}", identifier(id))
        if "{group_id}" in path:
            path = path.replace("{group_id}", identifier(group_id))
        return self.request(path)

    def inspect(self, files):
        if not isinstance(files, list) or not 1 <= len(files) <= 8:
            raise EditorError.coded("evaluation.zip_count_invalid")
        paths = [Path(p).expanduser() for p in files]
        if any(not p.is_absolute() or not p.is_file() or p.suffix.lower() != ".zip" for p in paths):
            raise EditorError.coded("evaluation.zip_path_invalid")
        if sum(p.stat().st_size for p in paths) > 90 * 1024 * 1024:
            raise EditorError.coded("evaluation.zip_total_too_large")
        boundary = "workbench-" + uuid.uuid4().hex
        chunks = []
        for i, p in enumerate(paths):
            chunks.extend(
                [
                    f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="result-{i}.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode(),
                    p.read_bytes(),
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode())
        return self.request(
            "/api/intake-inspections",
            "POST",
            b"".join(chunks),
            content_type="multipart/form-data; boundary=" + boundary,
        )


class Evaluations:
    def __init__(self, tasks):
        self.tasks = tasks
        self.root = tasks.root.parent / "evaluation"
        self.lock = threading.RLock()

    def settings(self):
        path = self.root / "connection.json"
        return json.loads(path.read_text()) if path.exists() else None

    def focus(self):
        path = self.root / "focus.json"
        return json.loads(path.read_text()) if path.exists() else None

    def _save(self, name, value):
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic(self.root / name, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

    def execute(self, body, actor="ai"):
        with self.lock:
            try:
                return self._execute(body, actor)
            except EditorError:
                raise
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise EditorError(str(exc)) from None

    def _execute(self, b, actor):
        action = b.get("action", "status")
        if action == "status":
            drafts = self.root / "suggestions.json"
            return {
                "ok": True,
                "connection": self.settings(),
                "focus": self.focus(),
                "source_commit": SOURCE_COMMIT,
                "suggestions": json.loads(drafts.read_text()) if drafts.exists() else {},
            }
        if action == "connect":
            settings = connection(b)
            health = Client(settings).read("health")
            if not isinstance(health, dict) or health.get("status") != "ok":
                raise EditorError.coded("evaluation.health_check_failed")
            if self.settings() != settings:
                self._save("suggestions.json", {})
            self._save("connection.json", settings)
            self._save("focus.json", None)
            return {"ok": True, "connection": settings, "health": health}
        settings = self.settings()
        if not settings:
            raise EditorError.coded("evaluation.not_connected")
        c = Client(settings)
        if action == "catalog":
            return {"ok": True, **{r: c.read(r) for r in ("batches", "analyses", "dimensions", "issue_tags")}}
        if action == "read":
            resource = b.get("resource") or "analysis"
            focus = self.focus() or {}
            rid = b.get("id") or focus.get("case_run_id" if resource == "case" else "analysis_id")
            result = c.read(resource, rid, b.get("group_id"))
            sha = fingerprint(result)
            if resource == "analysis":
                result = dict(result)
                rows = result.get("matrix", [])
                offset, limit = b.get("offset", 0), b.get("limit", 50)
                if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
                    raise EditorError.coded("evaluation.invalid_offset_or_limit")
                result.update(matrix=rows[offset : offset + limit], total_rows=len(rows), offset=offset)
            return {
                "ok": True,
                "data": result if b.get("detail") else compact(resource, result),
                "sha256": sha,
                "resource": resource,
                "id": rid,
            }
        if action == "focus":
            view = c.read("analysis", b.get("id"))
            selected = b.get("case_run_id")
            row_index = next(
                (
                    i
                    for i, row in enumerate(view["matrix"])
                    if any(cell.get("case_run_id") == selected for cell in row["cells"].values())
                ),
                None,
            )
            if selected and row_index is None:
                raise EditorError.coded("evaluation.case_run_not_in_analysis")
            focus = {
                "analysis_id": b["id"],
                "case_run_id": selected,
                "row_offset": (row_index or 0) // 25 * 25,
                "by": actor,
                "at": time.time(),
            }
            self._save("focus.json", focus)
            return {"ok": True, "focus": focus}
        if action == "inspect":
            result = c.inspect(b.get("files"))
        elif action == "intake":
            payload = b.get("intake") or {}
            if not payload.get("package_sha256s") or not payload.get("factors"):
                raise EditorError.coded("evaluation.intake_incomplete")
            result = c.request("/api/intake-batches", "POST", payload)
        elif action == "create_analysis":
            ids = b.get("batch_ids", [])
            if not isinstance(ids, list) or not 1 <= len(ids) <= 8:
                raise EditorError.coded("evaluation.batch_count_invalid")
            for value in ids:
                identifier(value)
            result = c.request(
                "/api/analysis-views",
                "POST",
                {
                    "name": b.get("name", render("evaluation.default_comparison_name")),
                    "result_batch_ids": ids,
                    "comparison_factor": b.get("comparison_factor"),
                },
            )
        elif action in {"review", "compare_review"}:
            resource = "case" if action == "review" else "comparison"
            current = c.read(resource, b.get("id"), b.get("group_id"))
            if not b.get("expected_sha256") or fingerprint(current) != b["expected_sha256"]:
                raise EditorError.coded("stale_evidence")
            payload = dict(b.get("review") or {})
            if actor != "human":
                # Upstream treats every human_reviews row as HUMAN evidence,
                # regardless of reviewer text. Keep AI proposals out of that gate.
                path = self.root / "suggestions.json"
                proposals = json.loads(path.read_text()) if path.exists() else {}
                key = action + ":" + str(b.get("id")) + ":" + str(b.get("group_id") or "")
                proposals[key] = {
                    "action": action,
                    "id": b.get("id"),
                    "group_id": b.get("group_id"),
                    "expected_sha256": b["expected_sha256"],
                    "review": payload,
                    "at": time.time(),
                }
                self._save("suggestions.json", proposals)
                return {
                    "ok": True,
                    "saved_as": "ai_suggestion",
                    "submitted_to_platform": False,
                    "message": render("evaluation.ai_suggestion_saved"),
                }
            payload["reviewer"] = "codex-human" if actor == "human" else "codex-ai"
            if action == "review":
                if not str(payload.get("note", "")).strip():
                    raise EditorError.coded("evaluation.review_note_required")
                path = "/api/case-runs/" + identifier(b["id"]) + "/review"
            else:
                path = "/api/analysis-views/" + identifier(b["id"]) + "/comparisons/" + identifier(b.get("group_id"))
            result = c.request(path, "PUT", payload)
        elif action == "evaluate":
            # Platform's existing async job; no duplicated local metric engine.
            result = c.request("/api/analysis-views/" + identifier(b.get("id")) + "/analysis-jobs", "POST", {})
        elif action == "report":
            # The initial integration only creates deterministic, frozen reports.
            result = c.request(
                "/api/analysis-views/" + identifier(b.get("id")) + "/reports",
                "POST",
                {"title": b.get("name", ""), "use_llm": False, "audience": "evaluation"},
            )
            result = {k: v for k, v in result.items() if k not in {"snapshot", "deterministic", "llm", "markdown_text"}}
        elif action == "preview":
            ids = b.get("case_run_ids") or [b.get("id")]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
                raise EditorError.coded("evaluation.preview_count_invalid")
            evidence = []
            for rid in ids:
                item = c.read("case", rid)
                if not item.get("viewer_path"):
                    raise EditorError.coded("evaluation.case_not_materialized")
                evidence.append(
                    {"id": rid, "sha256": fingerprint(item), "artifact_sha256": item.get("review_artifact_sha256")}
                )
            from studio.adapters.platform_preview import script

            return self.tasks.start(
                {
                    "engine": "python",
                    "script": script(),
                    "params": {"connection": settings, "evidence": evidence},
                    "title": render("evaluation.preview_title", id=ids[0]),
                    "timeout_seconds": 300,
                    "render_preview": False,
                },
                actor,
            )
        elif action == "export":
            resource = b.get("resource", "review_data")
            rid = identifier(b.get("id"))
            paths = {
                "review_data": f"/api/analysis-views/{rid}/review-data.csv",
                "report": f"/api/analysis-reports/{rid}/markdown",
            }
            if resource not in paths:
                raise EditorError.coded("evaluation.export_resource_invalid")
            raw = c.request(paths[resource], binary=True)
            folder = self.root / "exports"
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / (str(uuid.uuid4()) + (".csv" if resource == "review_data" else ".md"))
            dest.write_bytes(raw)
            return {"ok": True, "path": str(dest), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        else:
            raise EditorError.coded("evaluation.unsupported_action")
        # An audit trail records who initiated each write, not credentials or data.
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "actions.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"action": action, "id": b.get("id"), "actor": actor, "at": time.time()}, ensure_ascii=False)
                + "\n"
            )
        return {"ok": True, "data": result}
