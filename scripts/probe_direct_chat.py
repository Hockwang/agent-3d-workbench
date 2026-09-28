"""Explicitly create ONE verification fork; an existing receipt prevents reruns."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.shell.codex_bridge import CodexBridge, BridgeError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--before-turn", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    adapter = {"executable": str(Path(args.executable).resolve(strict=True))}
    if args.verify_only:
        receipt = json.loads(args.receipt.read_text())
        if receipt["parent_id"] != args.parent:
            raise BridgeError("收据不属于指定父任务")
        with CodexBridge(adapter) as client:
            child = client.read(receipt["child_id"])
            if child.get("forkedFromId") != args.parent or child["cwd"] != receipt["cwd"]:
                raise BridgeError("分支来源或目录不一致")
            print(
                json.dumps(
                    {k: child.get(k) for k in ("id", "name", "cwd", "forkedFromId", "ephemeral", "status")},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return
    # Exclusive creation: never retry a possibly successful fork automatically.
    with args.receipt.open("x", encoding="utf-8") as file:
        receipt = {"parent_id": args.parent, "status": "preflight"}

        def save():
            file.seek(0)
            json.dump(receipt, file, ensure_ascii=False, indent=2)
            file.truncate()
            file.flush()
            import os

            os.fsync(file.fileno())

        save()
        try:
            with CodexBridge(adapter) as client:
                parent = client.read(args.parent)
                receipt.update(cwd=parent["cwd"], before_turn_id=args.before_turn, status="creating")
                save()

                def remember(child):
                    receipt.update(
                        status="created",
                        child_id=child["id"],
                        forked_from_id=child.get("forkedFromId"),
                        child_cwd=child["cwd"],
                    )
                    save()

                # Pin the history boundary when probing a currently active task.
                child = client._rpc(
                    "thread/fork",
                    {
                        "threadId": args.parent,
                        "excludeTurns": True,
                        "deferGoalContinuation": True,
                        "beforeTurnId": args.before_turn,
                    },
                    remember,
                )["thread"]
                remember(child)
                if child.get("forkedFromId") != args.parent or child["cwd"] != parent["cwd"]:
                    raise BridgeError("返回的父任务或目录不一致，保留 child_id 供检查")
                client.rename(child["id"], "直建分支验证 · 零件工作台")
            # Persistence after the creating App Server has exited.
            with CodexBridge(adapter) as client:
                after = client.read(receipt["child_id"])
                receipt.update(
                    status="persisted",
                    child_title=after.get("name"),
                    child_status=after.get("status"),
                    ephemeral=after.get("ephemeral"),
                )
                save()
        except Exception as error:
            receipt.update(
                error=str(error), outcome_unknown=(receipt["status"] == "creating" and not receipt.get("child_id"))
            )
            save()
            raise
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
