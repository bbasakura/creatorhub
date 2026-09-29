import tempfile
from pathlib import Path

import pytest

from app.services.executor_instance import ExecutorInstanceBusy, ExecutorInstanceLock


def test_executor_instance_lock_is_exclusive_and_reusable():
    with tempfile.TemporaryDirectory() as directory:
        runtime = Path(directory) / "runtime"
        first = ExecutorInstanceLock(runtime)
        second = ExecutorInstanceLock(runtime)

        first.acquire()
        assert first.acquired is True
        with pytest.raises(ExecutorInstanceBusy):
            second.acquire()

        first.release()
        assert first.acquired is False
        second.acquire()
        assert second.acquired is True
        second.release()


def test_executor_instance_lock_acquire_is_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        lock = ExecutorInstanceLock(Path(directory) / "runtime")
        assert lock.acquire() is lock
        assert lock.acquire() is lock
        lock.release()
        lock.release()
