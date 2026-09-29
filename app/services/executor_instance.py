"""Cross-process singleton lock for the CreatorHub execution engine.

The API and worker still live in one process today.  This lock prevents a
second CreatorHub process (for example another uvicorn instance on a different
port) from starting a second MonitorEngine against the same runtime.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from ..runtime_paths import runtime_subdir


class ExecutorInstanceBusy(RuntimeError):
    """Raised when another process already owns the execution-engine lock."""


class ExecutorInstanceLock:
    def __init__(self, runtime_dir: str | Path | None = None,
                 filename: str = "executor.lock") -> None:
        self.path = runtime_subdir("locks", configured=runtime_dir) / filename
        self._file: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def acquire(self) -> "ExecutorInstanceLock":
        if self._file is not None:
            return self

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)

            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise ExecutorInstanceBusy(
                        f"CreatorHub execution engine is already running; lock={self.path}"
                    ) from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise ExecutorInstanceBusy(
                        f"CreatorHub execution engine is already running; lock={self.path}"
                    ) from exc
        except Exception:
            handle.close()
            raise

        self._file = handle
        return self

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        self._file = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "ExecutorInstanceLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
