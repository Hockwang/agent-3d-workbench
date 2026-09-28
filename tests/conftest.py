"""Shared pytest fixtures: an in-process CLI runner (no forking), small mesh-building
helpers, and the local-server / stdio-MCP test doubles several test modules need."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest
import trimesh

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from mcp import ClientSession, StdioServerParameters, stdio_client  # noqa: E402

import studio  # noqa: E402
from print_prep.cli import main as cli_main  # noqa: E402
from studio.shell.server import create_httpd  # noqa: E402
from tests.helpers import Client, MCP_SERVER_SCRIPT  # noqa: E402


def run_cli(args: list[str], capsys) -> tuple[int, dict, str]:
    """跑一次 CLI，返回 (退出码, stdout 解析出的 JSON, stderr 原文)；
    顺带断言 stdout 只有一个 JSON 对象（SPEC.md §3 通用契约）。"""
    exit_code = cli_main(args)
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    assert stdout, "stdout 必须有内容"
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout 必须只有一个 JSON 对象，实际: {stdout!r}"
    payload = json.loads(lines[0])
    return exit_code, payload, captured.err


def write_box_stl(directory: Path, name: str, extents) -> Path:
    """造一个盒子，存成 STL，返回路径。"""
    mesh = trimesh.creation.box(extents=list(extents))
    path = directory / f"{name}.stl"
    mesh.export(path, file_type="stl")
    return path


# --- CLI ---------------------------------------------------------------------


@pytest.fixture
def run(capsys):
    """`run(["inspect", "--job", ...])` 的简写。"""

    def _run(args: list[str]):
        return run_cli(args, capsys)

    return _run


# --- test isolation (autouse) -------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path, monkeypatch):
    """Keep every test away from the developer's real files.

    The code reads three user-level roots: ``PRINT_PREP_HOME`` (default ``~/.print-prep``,
    workspaces / recipes / session file), ``WORKBENCH_SERVICE_CONFIG`` (default
    ``~/.config/codex-3d/services.json``, BYOK service connections) and ``CODEX_HOME``
    (default ``~/.codex``, read by the Codex bridge). Every test gets its own copies under
    ``tmp_path`` so a test that forgets to set them can neither read nor write the real
    ones. A test may still override any of these with its own ``monkeypatch.setenv``.
    """
    root = tmp_path / "_user_state"
    monkeypatch.setenv("PRINT_PREP_HOME", str(root / "print-prep"))
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(root / "codex-3d" / "services.json"))
    monkeypatch.setenv("CODEX_HOME", str(root / "codex"))
    monkeypatch.delenv("PRINT_PREP_WORKSPACES_HOME", raising=False)
    monkeypatch.delenv("PRINT_PREP_WORKSPACE_ID", raising=False)
    # The existing test suite was written against the (until now, only) hardcoded
    # Chinese error strings; pin STUDIO_LANG so `studio.i18n.get_language()`'s
    # env-default fallback keeps matching them everywhere a test doesn't send its
    # own Accept-Language / doesn't otherwise care. New i18n-specific tests should
    # assert on the stable `code` (and `params`), not on rendered text, and can
    # still override the language explicitly via `monkeypatch.setenv("STUDIO_LANG", ...)`
    # or the `Accept-Language` header.
    monkeypatch.setenv("STUDIO_LANG", "zh-CN")


# --- local HTTP server test double (studio/shell/server.py) -------------------------


@pytest.fixture
def studio_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("PRINT_PREP_HOME", str(home))
    job_dir = tmp_path / "job"
    httpd, port, backend = create_httpd(job_dir, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{port}", backend.token)
    try:
        yield {"client": client, "backend": backend, "job_dir": job_dir, "port": port, "home": home}
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# --- stdio MCP server test double (studio/shell/mcp_server.py) ----------------------


@pytest.fixture
def mcp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("PRINT_PREP_HOME", str(home))
    yield home
    # 不管测试内部有没有显式 stop，收尾都兜底停一次，不留下后台进程。
    studio.stop_server()
    for path in (home / "workspaces").glob("*"):
        studio.stop_server(home=path)


@pytest.fixture
async def mcp_session(mcp_home):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_SCRIPT)],
        # `env=` replaces the subprocess's whole environment rather than extending the
        # parent's, so the top-level `_isolate_user_state` fixture's STUDIO_LANG pin
        # (see its docstring) does not reach this subprocess unless repeated here too.
        env={"PRINT_PREP_HOME": str(mcp_home), "PRINT_PREP_WORKSPACE_ID": "test-workspace", "STUDIO_LANG": "zh-CN"},
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch):
    """Fail fast if a test tries to reach a non-loopback host.

    Hosted-service adapters are exercised through monkeypatched transports; nothing in the suite
    is allowed to hit the real network. Loopback stays open because the HTTP/MCP server tests talk
    to servers they start themselves. Tests that really need the network can override this fixture.
    """
    import http.client

    allowed = {"127.0.0.1", "localhost", "::1"}
    original = http.client.HTTPConnection.connect

    def guarded_connect(self):
        host = (self.host or "").strip("[]")
        if host not in allowed:
            raise RuntimeError(f"test tried to open a real network connection to {host!r}")
        return original(self)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", guarded_connect)
