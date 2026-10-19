"""Local LightBurn 2.2 REST bridge. Import only; no machine motion or firing.

Pairing secrets never enter project artifacts, tool responses or the browser.
202 is only acceptance: completion requires the subscribed file_imported event
and a fresh project/layer snapshot. An empty project prevents accidental merge.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from studio.core.editor import EditorError


class LightBurn:
    URL = "http://127.0.0.1:19520"

    def __init__(self, credential=None):
        home = Path(os.environ.get("PRINT_PREP_HOME", "~/.print-prep")).expanduser()
        self.credential = Path(credential) if credential is not None else home / "connections/lightburn.json"

    def token(self):
        try:
            secret = json.loads(self.credential.read_text())["secret"]
        except (OSError, ValueError, KeyError):
            raise EditorError("请先在激光制作中连接 LightBurn，并接受应用内授权", code="lightburn_pairing") from None
        return hmac.new(secret.encode(), str(int(time.time() // 60)).encode(), hashlib.sha256).hexdigest()

    def request(self, path, body=None, headers=None, paired=True, stream=False, timeout=12):
        h = {"Authorization": "Bearer " + self.token()} if paired else {}
        h.update(headers or {})
        if isinstance(body, dict):
            h["Content-Type"] = "application/json"
            body = json.dumps(body).encode()
        req = urllib.request.Request(self.URL + path, data=body, headers=h)
        try:
            response = urllib.request.urlopen(req, timeout=timeout)
            if stream:
                return response
            with response:
                raw = response.read(4 * 1024 * 1024)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise EditorError(
                f"LightBurn 返回 {exc.code}；请检查版本、配对权限与当前窗口", code="lightburn_http"
            ) from None
        except (OSError, ValueError):
            raise EditorError(
                "无法读取 LightBurn；请打开支持 REST API 的版本并完成设备设置", code="lightburn_unavailable"
            ) from None

    def connect(self):
        result = self.request(
            "/api/connect",
            {"application_name": "Agent 3D Workbench · R1 Laser", "capabilities": ["state", "project", "upload"]},
            paired=False,
            timeout=40,
        )
        secret = result.get("secret")
        if result.get("status") != "ok" or not isinstance(secret, str) or not secret:
            raise EditorError("LightBurn 配对未获批准，请在应用窗口中接受连接", code="lightburn_pairing")
        self.credential.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.credential, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump({"secret": secret}, out)
        return self.status()

    def status(self):
        return {
            "paired": True,
            "project": self.request("/api/project"),
            "capabilities": ["state", "project", "upload"],
            "physical_cut_verified": False,
        }

    def preflight(self, expected=None):
        project = self.request("/api/project")
        if project.get("shape_count") != 0:
            raise EditorError(
                "LightBurn 当前工程已有图形，请先保存并新建空白工程，避免叠加板件", code="lightburn_nonempty"
            )
        snapshot = self.request("/api/events/poll")
        if snapshot.get("job", {}).get("state") not in (None, "idle"):
            raise EditorError("LightBurn 设备正在加工，请等待空闲", code="lightburn_busy")
        if expected:
            workspace = project.get("workspace", {})
            size = workspace.get("machine_size", {})
            sheet = expected["sheet_mm"]
            if any(
                not isinstance(size.get(axis), (int, float)) or size[axis] + 0.001 < length
                for axis, length in zip(("x", "y"), sheet)
            ):
                raise EditorError(
                    "LightBurn 画布小于排版材料，请在设备设置中调整工作区尺寸后重试", code="lightburn_workspace"
                )
            # For offline No Machine imports, validate the machine canvas only.
            # Retain the separate workpiece_size in the receipt; this does
            # not establish that a physical material or device is ready.
            offline = project.get("device", {}).get("laser", {}).get("controller") == "No Machine"
            material = workspace.get("workpiece_size", {})
            if (
                not offline
                and not workspace.get("machine_view")
                and any(
                    not isinstance(material.get(axis), (int, float)) or material[axis] + 0.001 < length
                    for axis, length in zip(("x", "y"), sheet)
                )
            ):
                raise EditorError("LightBurn 当前材料页小于排版材料，请先调整材料尺寸", code="lightburn_workspace")
        return project

    def import_svg(self, path, expected):
        before = self.preflight(expected)
        event = None
        # Opening and reading the initial comment establishes the subscription
        # before the upload. Poll snapshots do not carry import completion events.
        with self.request("/api/events", stream=True, timeout=25) as stream:
            first = stream.readline(65536)
            if not first.startswith(b":connected"):
                raise EditorError("LightBurn 导入事件未就绪", code="lightburn_events")
            self.request(
                "/api/file/upload",
                Path(path).read_bytes(),
                {
                    "Content-Type": "application/octet-stream",
                    "X-Filename": Path(path).name,
                    "X-Position-X": str(expected["bounds_mm"][0]),
                    "X-Position-Y": str(expected["bounds_mm"][1]),
                    "X-Origin": "bottom-left",
                    "X-Group-Shapes": "false",
                },
            )
            kind = ""
            data = []
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                raw = stream.readline(65536)
                if not raw:
                    break
                line = raw.decode().strip()
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif not line:
                    if kind == "file_imported" and data:
                        event = json.loads("\n".join(data))
                        break
                    kind = ""
                    data = []
        if not event or event.get("success") is not True:
            raise EditorError("LightBurn 未确认成功导入；请核对应用，不自动重发", code="lightburn_unverified")
        project = self.request("/api/project")
        layers = self.request("/api/layers")
        if not isinstance(project.get("shape_count"), int) or project["shape_count"] < expected["panels"]:
            raise EditorError("LightBurn 已回应导入，但板件数量未通过核验", code="lightburn_unverified")
        return {
            "status": "imported",
            "event": event,
            "project_before": before,
            "project": project,
            "layers": layers,
            "expected": expected,
            "geometry_scale": "SVG mm; verify displayed dimensions in LightBurn",
            "imported_at": time.time(),
            "power_speed": "not_configured",
            "physical_cut_verified": False,
        }
