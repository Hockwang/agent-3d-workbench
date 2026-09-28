#!/usr/bin/env python3
"""No-POST connection probe. Default: no credentials, no config/network mutation."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.core.editor import EditorError
from studio.adapters.services import config
from studio.adapters.service_diagnostics import probe_assembly


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-prodtest", action="store_true", help="只对本次诊断使用方案 0 内网 HTTP 路由")
    parser.add_argument(
        "--with-auth", action="store_true", help="使用已配置的网关凭据；内网 HTTP 另需配置 allow_insecure_http=true"
    )
    args = parser.parse_args()
    spec = config()["assembly"]
    if args.internal_prodtest:
        spec = {**spec, "transport": "assembly-prodtest-http"}
    try:
        result = probe_assembly(spec, use_credentials=args.with_auth)
    except EditorError as exc:
        result = {
            "network_reachable": False,
            "authentication": "not_checked",
            "generation": "not_tested",
            "detail": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return (
        0
        if (result["authentication"] == "accepted_read_only" if args.with_auth else result["network_reachable"])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
