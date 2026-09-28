"""Plain (non-fixture) helpers shared by several test modules.

Pytest fixtures used across modules live in ``tests/conftest.py`` instead, where
pytest can inject them without an explicit import. Everything here is a regular
function, context manager, or class that a test calls directly.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh

from studio.core import collaboration as c
from studio.core.scene_assets import pack, unpack


def wait(tasks, task_id):
    for _ in range(200):
        state = tasks.state(task_id, include_log=True)
        if state["status"] not in ("queued", "running", "cancelling"):
            return state
        time.sleep(0.05)
    raise AssertionError("task did not terminate")


def act(w, action, **params):
    return w.execute({"action": action, "params": params, "expected_revision": w.state()["revision"]}, "human")


def scene_call(w, a, p=None, **kw):
    return w.execute(dict(action=a, params=p or {}, expected_revision=w.doc["revision"], **kw))


def source(tmp_path, *, rig=False, animated=False):
    mesh = trimesh.creation.box([0.4, 0.3, 1.8])
    doc, binary = unpack(trimesh.Scene(mesh).export(file_type="glb"))
    binary = bytearray(binary)

    def add(array, kind, component, count, **extras):
        binary.extend(b"\0" * (-len(binary) % 4))
        raw = array.tobytes()
        index = len(doc["bufferViews"])
        doc["bufferViews"].append(dict(buffer=0, byteOffset=len(binary), byteLength=len(raw)))
        binary.extend(raw)
        a = len(doc["accessors"])
        doc["accessors"].append(dict(bufferView=index, type=kind, componentType=component, count=count, **extras))
        return a

    target = next(i for i, n in enumerate(doc["nodes"]) if "mesh" in n)
    if rig:
        bone = len(doc["nodes"])
        doc["nodes"].append({"name": "RootBone"})
        doc["scenes"][0]["nodes"].append(bone)
        doc["skins"] = [{"joints": [bone]}]
        doc["nodes"][target]["skin"] = 0
        primitive = doc["meshes"][0]["primitives"][0]
        n = doc["accessors"][primitive["attributes"]["POSITION"]]["count"]
        primitive["attributes"]["JOINTS_0"] = add(np.zeros((n, 4), dtype="<u2"), "VEC4", 5123, n)
        weights = np.zeros((n, 4), dtype="<f4")
        weights[:, 0] = 1
        primitive["attributes"]["WEIGHTS_0"] = add(weights, "VEC4", 5126, n)
        target = bone
    if rig or animated:
        inp = add(np.array([0, 1], dtype="<f4"), "SCALAR", 5126, 2, min=[0], max=[1])
        out = add(np.array([[0, 0, 0], [0, 0.1, 0]], dtype="<f4"), "VEC3", 5126, 2)
        doc["animations"] = [
            {
                "name": "Move",
                "samplers": [{"input": inp, "output": out, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": target, "path": "translation"}}],
            }
        ]
    doc["buffers"][0]["byteLength"] = len(binary)
    path = tmp_path / f"source-{rig}-{animated}.glb"
    path.write_bytes(pack(doc, bytes(binary)))
    return path


def container_input(tmp_path):
    m = trimesh.creation.box([100, 80, 65])
    m.apply_translation([0, 0, 32.5])
    path = tmp_path / "source.stl"
    m.export(path)
    return path


@contextmanager
def session(key):
    token = c.SESSION.set(key)
    try:
        yield
    finally:
        c.SESSION.reset(token)


async def mcp_call(client, name, workspace_id, **arguments):
    result = await client.call_tool(name, {"workspace_id": workspace_id, **arguments})
    payload = result.structured_content or json.loads(result.content[0].text)
    assert not result.is_error, payload
    return payload


class Client:
    """薄薄一层 `urllib` 封装：`get/post` 返回 `(status, json_or_None)`。"""

    def __init__(self, base: str, token: str):
        self.base = base
        self.token = token

    def get(self, path: str, headers: Optional[dict[str, str]] = None, token: Any = ...) -> tuple[int, Any]:
        # SPEC_V05.md §2.6：`/api/session` 之外的 GET /api/* 现在也要求令牌，跟
        # `.post()` 一样默认带上 `self.token`；测试想验证"没带令牌会被拒"时传
        # `token=None`。
        h = dict(headers or {})
        use_token = self.token if token is ... else token
        if use_token and "X-Studio-Token" not in h:
            h["X-Studio-Token"] = use_token
        req = urllib.request.Request(self.base + path, headers=h, method="GET")
        return self._send(req)

    def post(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        token: Optional[str] = ...,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, Any]:
        h = dict(headers or {})
        h["Content-Type"] = "application/json"
        use_token = self.token if token is ... else token
        if use_token:
            h["X-Studio-Token"] = use_token
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, headers=h, method="POST")
        return self._send(req)

    def raw_bytes(self, path: str, data: bytes, headers: Optional[dict[str, str]] = None) -> tuple[int, Any]:
        h = dict(headers or {})
        if self.token:
            h["X-Studio-Token"] = self.token
        req = urllib.request.Request(self.base + path, data=data, headers=h, method="POST")
        return self._send(req)

    @staticmethod
    def _send(req: urllib.request.Request) -> tuple[int, Any]:
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                if not raw:
                    return resp.status, None
                try:
                    return resp.status, json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return resp.status, raw  # 非 JSON 响应（比如零件 STL 二进制），原样返回字节
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw.decode("utf-8", errors="replace")


def content_json(result: Any) -> dict[str, Any]:
    """`CallToolResult.content` 是一串 content block；我们的实现恒返回单个
    `TextContent`，text 是 JSON 原文。"""
    assert result.content, "call_tool 没有返回任何 content"
    text = result.content[0].text
    return json.loads(text)


MCP_SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "studio" / "shell" / "mcp_server.py"
