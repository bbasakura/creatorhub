"""Process-local runtime context for extension routers.

Extension modules must not import ``app.main`` to reach mutable globals. The
FastAPI lifespan binds the current browser/engine here, and routers resolve the
runtime through this small dependency boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeContext:
    browser: Any
    engine: Any


_runtime: RuntimeContext | None = None


def bind_runtime(*, browser: Any, engine: Any) -> None:
    global _runtime
    _runtime = RuntimeContext(browser=browser, engine=engine)


def clear_runtime() -> None:
    global _runtime
    _runtime = None


def get_runtime() -> RuntimeContext | None:
    return _runtime
