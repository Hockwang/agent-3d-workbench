"""A task survives HTTP restarts; owns its child process group and cancellation."""

from pathlib import Path
import hashlib
import json
import mimetypes
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studio.core.editor import _atomic
from studio.i18n import render


def _terminate_child(child, sig):
    """`start_new_session=True` (POSIX-only) puts the child in its own process
    group so killing the group also kills anything it spawned in turn (e.g. a
    Blender subprocess's own children); `os.killpg` doesn't exist on Windows
    at all, so fall back to signalling just the child process there."""
    if hasattr(os, "killpg"):
        os.killpg(child.pid, sig)
    elif sig == signal.SIGKILL:
        child.kill()
    else:
        child.terminate()


def run(folder):
    request = json.loads((folder / "request.json").read_text())
    state = json.loads((folder / "state.json").read_text())
    started = time.monotonic()

    def save(**changes):
        state.update(changes, heartbeat=time.time(), elapsed_seconds=time.monotonic() - started)
        _atomic(folder / "state.json", json.dumps(state, ensure_ascii=False).encode())

    child = None
    try:

        def check_implementation():
            if request.get("implementation_sha256"):
                from studio.core.tasks import implementation_digest

                if request["implementation_sha256"] != implementation_digest():
                    raise RuntimeError(render("task_worker.implementation_changed"))

        check_implementation()
        bootstrap = str(Path(__file__).with_name("task_bootstrap.py"))
        command = (
            [request["executable"], "--background", "--factory-startup", "--python", bootstrap, "--", str(folder)]
            if request["engine"] == "blender"
            else [request["executable"], bootstrap, str(folder)]
        )
        save(status="running", started=time.time())
        sources = []
        frozen = {x["path"]: x["sha256"] for x in request.get("frozen_inputs", [])}
        for filename in request["inputs"]:
            path = Path(filename)
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if filename in frozen and digest != frozen[filename]:
                raise RuntimeError(render("task_worker.frozen_source_checksum_failed"))
            sources.append({"path": str(path), "bytes": path.stat().st_size, "sha256": digest})
            save()
        save(inputs=sources)
        with (folder / "run.log").open("wb") as log:
            child = subprocess.Popen(
                command, cwd=folder, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True
            )
            while child.poll() is None:
                if (folder / "cancel").exists() or time.monotonic() - started > request["timeout_seconds"]:
                    _terminate_child(child, signal.SIGTERM)
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        _terminate_child(child, signal.SIGKILL)
                        child.wait()
                    save(
                        status="cancelled" if (folder / "cancel").exists() else "failed",
                        error=render("task_worker.cancelled")
                        if (folder / "cancel").exists()
                        else render("task_worker.timed_out"),
                    )
                    return
                save()
                time.sleep(0.25)
        if child.returncode != 0 or not (folder / "success.json").exists():
            raise RuntimeError(render("task_worker.process_did_not_complete", returncode=child.returncode))
        check_implementation()
        for filename, digest in frozen.items():
            with Path(filename).open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                    raise RuntimeError(render("task_worker.frozen_source_changed_during_build"))
        artifacts = []
        root = (folder / "output").resolve()
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            if path.stat().st_size > 1024**3:
                raise RuntimeError(render("task_worker.artifact_over_1gb"))
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            name = path.relative_to(root).as_posix()
            metadata = {}
            if path.suffix.lower() == ".glb":
                import struct

                with path.open("rb") as source:
                    header = source.read(20)
                    if (
                        len(header) != 20
                        or header[:4] != b"glTF"
                        or header[16:20] != b"JSON"
                        or struct.unpack_from("<I", header, 4)[0] != 2
                        or struct.unpack_from("<I", header, 8)[0] != path.stat().st_size
                    ):
                        raise RuntimeError(render("task_worker.glb_readback_failed"))
                    length = struct.unpack_from("<I", header, 12)[0]
                    if length > 64 * 1024 * 1024:
                        raise RuntimeError(render("task_worker.glb_json_over_limit"))
                    doc = json.loads(source.read(length))
                    metadata = {
                        "animations": len(doc.get("animations", [])),
                        "skins": len(doc.get("skins", [])),
                        "meshes": len(doc.get("meshes", [])),
                    }
            artifacts.append(
                {
                    "id": hashlib.sha256(name.encode()).hexdigest()[:16],
                    "name": name,
                    "path": str(path),
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                    "mime": mimetypes.guess_type(name)[0] or "application/octet-stream",
                    **metadata,
                }
            )
            save()
        if not artifacts:
            raise RuntimeError(render("task_worker.no_artifacts_delivered"))
        from studio.core.result_manifest import read_manifest

        result = read_manifest(root, artifacts)
        save(status="completed", artifacts=artifacts, finished=time.time(), **({"result": result} if result else {}))
    except BaseException as exc:
        if child and child.poll() is None:
            _terminate_child(child, signal.SIGKILL)
            child.wait()
        save(status="failed", error=str(exc), finished=time.time())


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
