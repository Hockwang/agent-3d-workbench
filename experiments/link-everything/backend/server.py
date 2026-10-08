from __future__ import annotations
import argparse
import json
import mimetypes
import os
import re
import hashlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import current_project, generate
from backend import presets, manual, cutting, parametric_bridge, parametric_ai

LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.json(
                200,
                dict(
                    ok=True,
                    service="connection-design",
                    engine="Manifold parametric templates",
                    llm=bool(
                        os.environ.get("CONNECTION_DESIGN_ONEAPI_BASE_URL")
                        and (os.environ.get("CONNECTION_DESIGN_ONEAPI_KEY") or os.environ.get("LUX3D_ONE_API_KEY"))
                    ),
                    llm_model="gpt-6-sol",
                ),
            )
        if path == "/api/project":
            with LOCK:
                result = current_project()
            return self.json(200, result)
        if path == "/api/presets":
            return self.json(200, presets.catalog())
        if path == "/api/presets/project":
            with LOCK:
                result = presets.current_project()
            return self.json(200, result)
        if path == "/api/parametric/context":
            with LOCK:
                result = parametric_bridge.current()
            return self.json(200, result)
        if path == "/api/manual/project":
            with LOCK:
                result = manual.current_project()
            return self.json(200, result)
        if path == "/api/manual/cut/source":
            with LOCK:
                result = cutting.current()
            return self.json(200, result)
        if path.startswith("/api/"):
            return self.json(404, dict(error="unknown endpoint"))
        if path.startswith("/outputs/"):
            root = ROOT / "outputs"
            relative = path[len("/outputs/") :]
        else:
            root = ROOT / "frontend"
            relative = path.lstrip("/") or "index.html"
        file = (root / relative).resolve()
        if not file.is_relative_to(root.resolve()) or not file.is_file():
            return self.json(404, dict(error="file not found"))
        raw = file.read_bytes()
        mime = {"glb": "model/gltf-binary", "stl": "model/stl"}.get(
            file.suffix[1:], mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in (
            "/api/design",
            "/api/reset",
            "/api/media",
            "/api/presets/design",
            "/api/parametric/design",
            "/api/parametric/ai/propose",
            "/api/parametric/ai/generate",
            "/api/parametric/placement/check",
            "/api/manual/placement/check",
            "/api/manual/design",
            "/api/manual/upload",
            "/api/manual/sample",
            "/api/manual/cut/sample",
            "/api/manual/cut/upload",
            "/api/manual/cut/solidify",
            "/api/manual/cut/preview",
            "/api/manual/cut/commit",
        ):
            return self.json(404, dict(error="unknown endpoint"))
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.json(403, dict(error="cross-origin mutation rejected"))
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if path == "/api/media":
                if not 0 < size <= 64 * 1024 * 1024:
                    return self.json(413, dict(error="video must be between 1 byte and 64 MB"))
                name = parse_qs(urlparse(self.path).query).get("filename", [""])[0]
                if not re.fullmatch(r"connection-demo-r[0-9]{1,8}(?:-[A-Za-z0-9_-]{1,40})?\.webm", name):
                    return self.json(400, dict(error="invalid video filename"))
                if self.headers.get("Content-Type", "").split(";")[0] != "video/webm":
                    return self.json(415, dict(error="video/webm required"))
                raw = self.rfile.read(size)
                if len(raw) != size or not raw.startswith(bytes.fromhex("1a45dfa3")):
                    return self.json(400, dict(error="invalid or incomplete WebM container"))
                folder = ROOT / "outputs" / "media"
                folder.mkdir(parents=True, exist_ok=True)
                output = folder / name
                if output.exists():
                    return self.json(409, dict(error="media already exists; use a unique filename"))
                output.write_bytes(raw)
                return self.json(
                    201,
                    dict(
                        url="/outputs/media/" + name,
                        bytes=len(raw),
                        absolute_path=str(output),
                        sha256=hashlib.sha256(raw).hexdigest(),
                    ),
                )
            # A 50 MiB whole-model upload expands to about 66.7 MiB in the
            # JSON/base64 transport. Keep the two-part STL endpoint's limit.
            limit = (
                68 * 1024 * 1024
                if path == "/api/manual/cut/upload"
                else 36 * 1024 * 1024
                if path == "/api/manual/upload"
                else 16384
            )
            if size <= 0 or size > limit:
                return self.json(413, dict(error="request too large"))
            payload = json.loads(self.rfile.read(size) or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            if path == "/api/presets/design":
                with LOCK:
                    result = presets.generate(payload)
                return self.json(200, result)
            if path == "/api/parametric/ai/propose":
                with LOCK:
                    frozen = parametric_ai.snapshot(payload)
                return self.json(200, parametric_ai.propose(frozen))
            if path == "/api/parametric/ai/generate":
                with LOCK:
                    result = parametric_ai.generate(payload)
                return self.json(200, result)
            if path == "/api/parametric/design":
                with LOCK:
                    result = parametric_bridge.design(payload)
                return self.json(200, result)
            if path in ("/api/parametric/placement/check", "/api/manual/placement/check"):
                with LOCK:
                    result = parametric_bridge.check_placement(payload)
                return self.json(200, result)
            if path == "/api/manual/design":
                with LOCK:
                    result = manual.generate(payload)
                return self.json(200, result)
            if path == "/api/manual/upload":
                with LOCK:
                    result = manual.upload(payload)
                return self.json(200, result)
            if path == "/api/manual/sample":
                with LOCK:
                    result = manual.restore_sample()
                return self.json(200, result)
            if path == "/api/manual/cut/sample":
                with LOCK:
                    result = cutting.sample(payload)
                return self.json(200, result)
            if path == "/api/manual/cut/upload":
                with LOCK:
                    result = cutting.upload(payload)
                return self.json(200, result)
            if path == "/api/manual/cut/solidify":
                with LOCK:
                    result = cutting.solidify(payload)
                return self.json(200, result)
            if path == "/api/manual/cut/preview":
                with LOCK:
                    result = cutting.preview(payload)
                return self.json(200, result)
            if path == "/api/manual/cut/commit":
                with LOCK:
                    result = cutting.commit(payload)
                return self.json(200, result)
            with LOCK:
                result = generate(payload, reset=path == "/api/reset")
            return self.json(200, result)
        except parametric_ai.AIUnavailable as error:
            return self.json(503, dict(error=str(error)))
        except FileNotFoundError:
            return self.json(404, dict(error="AI proposal not found; regenerate the proposal"))
        except RuntimeError as error:
            return self.json(409, dict(error=str(error)))
        except (ValueError, TypeError) as error:
            return self.json(400, dict(error=str(error)))
        except Exception as error:
            import traceback

            traceback.print_exc()
            return self.json(500, dict(error=str(error)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    current_project()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Connection design demo: http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()
