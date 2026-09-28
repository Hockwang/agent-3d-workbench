"""print_prep.job —— job.json 的读写、跨步骤失效级联与文件哈希。

流水线是 inspect -> orient -> arrange -> export -> check（open 不产生会被后续
步骤消费的状态，不参与失效级联）。重复执行同一步会覆盖该步产物，并把 job.json
里排在它后面的所有步骤的记录删掉（SPEC.md §3 通用契约）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

STEP_ORDER = ("inspect", "orient", "arrange", "export", "check")


def job_json_path(job_dir: Path) -> Path:
    """job.json 在工作目录里的固定位置。"""
    return Path(job_dir) / "job.json"


def load_job(job_dir: Path) -> dict[str, Any]:
    """读 job.json；工作目录还没跑过任何一步时文件不存在，返回空字典。"""
    path = job_json_path(job_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_job(job_dir: Path, data: dict[str, Any]) -> None:
    """写 job.json（整份覆盖，缩进 1 方便肉眼 diff）。"""
    path = job_json_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：面板服务会在写操作进行中读 job.json，不能让它读到半截内容。
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def invalidate_from(data: dict[str, Any], step: str) -> dict[str, Any]:
    """把 `step` 自身以及流水线里排在它后面的所有步骤的记录从 job.json 里删掉
    （原地修改并返回同一个 dict，方便链式调用）。"""
    if step not in STEP_ORDER:
        return data
    idx = STEP_ORDER.index(step)
    for later in STEP_ORDER[idx:]:
        data.pop(later, None)
    return data


def sha256_file(path: Path) -> str:
    """流式计算文件 sha256，不把大网格文件整份读进内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """给已经在内存里的字节串算 sha256（geometry 3MF 这类小文件用这个更省一次落盘）。"""
    return hashlib.sha256(data).hexdigest()
