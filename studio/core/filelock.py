"""studio.core.filelock —— 跨平台的整文件互斥锁。

`fcntl`（POSIX）在 Windows 上根本不存在——在 MCP/HTTP 服务启动路径上对它做
模块级 `import` 会在 Windows 上直接 `ImportError`，把整个服务拉不起来。这个
模块把三处用锁文件做跨进程互斥的调用点（`studio/core/workspaces.py`、
`studio/adapters/service_connections.py`、`studio/shell/part_chat.py`）汇到
一份实现上，按平台分派：

- **POSIX**：`fcntl.flock`，建议式（advisory）整文件锁——只对同样调用
  `flock()` 的进程互斥，不阻止绕过它的直接读写；`LOCK_EX`/`LOCK_SH` 分别是
  独占/共享，进程持有的文件描述符一关（或进程退出）锁就自动释放。
- **Windows**：`msvcrt.locking`，强制式（mandatory）锁，但语义窄得多——它锁的
  是从当前文件位置开始的 `nbytes` 字节区间，不是"整个文件"；这里固定锁偏移 0
  处的 1 个字节作为互斥标记，不要求文件里真的有这个字节（Windows 允许锁定
  超出文件末尾的区间，这是实现锁文件的标准写法）。`LK_LOCK` 在拿不到锁时会
  抛 `OSError` 而不是阻塞，所以这里用短轮询模拟 `fcntl.flock` 的阻塞语义；
  `exclusive=False`（共享锁）在 `msvcrt` 里没有对应原语，退化为独占锁。

调用方都只是把整份文件当临界区用（"进到 with 块之前别的进程别动它"），两种
实现在这个粒度上等价；不要把这个模块当字节级 range lock 用。
"""

from __future__ import annotations

import time
from typing import Any

try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on POSIX only
    msvcrt = None  # type: ignore[assignment]

# An int fd, or any file-like object with a `.fileno()` method — the same
# `FileDescriptorLike` shape `fcntl.flock`/`os.open` already accept.
FileLike = Any

_WIN_LOCK_BYTES = 1
_WIN_RETRY_S = 0.05


def _fd(fileobj: FileLike) -> int:
    return fileobj if isinstance(fileobj, int) else fileobj.fileno()


def lock(fileobj: FileLike, *, exclusive: bool = True) -> None:
    """阻塞式加锁；`fileobj` 可以是已打开文件对象或裸文件描述符（int）。"""
    if fcntl is not None:
        fcntl.flock(fileobj, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return
    if msvcrt is not None:
        fd = _fd(fileobj)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, _WIN_LOCK_BYTES)
                return
            except OSError:
                time.sleep(_WIN_RETRY_S)
    raise RuntimeError("no file locking primitive available on this platform")


def unlock(fileobj: FileLike) -> None:
    """释放 `lock()` 加的锁；进程退出/文件描述符关闭时两种实现也都会自动释放，
    这个函数只是给需要显式提前释放的调用方用。"""
    if fcntl is not None:
        fcntl.flock(fileobj, fcntl.LOCK_UN)
        return
    if msvcrt is not None:
        msvcrt.locking(_fd(fileobj), msvcrt.LK_UNLCK, _WIN_LOCK_BYTES)
        return
    raise RuntimeError("no file locking primitive available on this platform")
