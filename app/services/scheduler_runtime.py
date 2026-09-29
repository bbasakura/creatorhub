"""Small in-process periodic scheduler for the modular monolith.

It intentionally does not introduce a distributed queue.  Independent groups
prevent slow read/scan work from delaying durable write queues while the
existing account locks and risk controller remain authoritative.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Iterable


Operation = Callable[[], object | Awaitable[object]]


@dataclass(frozen=True)
class SchedulerStage:
    name: str
    operation: Operation
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class SchedulerGroup:
    name: str
    interval_seconds: float
    stages: tuple[SchedulerStage, ...]


class PeriodicScheduler:
    def __init__(self, groups: Iterable[SchedulerGroup], *, logger=None) -> None:
        self.groups = tuple(groups)
        self.logger = logger
        self._tasks: dict[str, asyncio.Task] = {}
        self._status: dict[str, dict] = {
            group.name: {
                "alive": False,
                "stage": "stopped",
                "iterations": 0,
                "last_heartbeat_at": None,
                "last_finished_at": None,
                "last_error": "",
            }
            for group in self.groups
        }

    def start(self) -> None:
        if self._tasks:
            return
        for group in self.groups:
            self._tasks[group.name] = asyncio.create_task(
                self._run_group(group), name=f"creatorhub:{group.name}")

    async def wait(self) -> None:
        if not self._tasks:
            self.start()
        await asyncio.gather(*self._tasks.values())

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for status in self._status.values():
            status["alive"] = False
            status["stage"] = "stopped"
            status["last_heartbeat_at"] = datetime.utcnow()

    def status(self, *, now: datetime | None = None) -> dict[str, dict]:
        current = now or datetime.utcnow()
        result: dict[str, dict] = {}
        for name, raw in self._status.items():
            heartbeat = raw.get("last_heartbeat_at")
            result[name] = {
                **raw,
                "last_heartbeat_at": (
                    heartbeat.isoformat() + "Z" if heartbeat else None),
                "last_finished_at": (
                    raw["last_finished_at"].isoformat() + "Z"
                    if raw.get("last_finished_at") else None),
                "heartbeat_age_seconds": (
                    max(0.0, (current - heartbeat).total_seconds())
                    if heartbeat else None),
            }
        return result

    async def _run_group(self, group: SchedulerGroup) -> None:
        status = self._status[group.name]
        status["alive"] = True
        try:
            while True:
                started = asyncio.get_running_loop().time()
                status["last_error"] = ""
                for stage in group.stages:
                    status["stage"] = stage.name
                    status["last_heartbeat_at"] = datetime.utcnow()
                    try:
                        value = stage.operation()
                        if inspect.isawaitable(value):
                            if stage.timeout_seconds and stage.timeout_seconds > 0:
                                await asyncio.wait_for(value, timeout=stage.timeout_seconds)
                            else:
                                await value
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        status["last_error"] = f"{stage.name}: {exc!r}"[:1000]
                        if self.logger is not None:
                            self.logger.exception(
                                "scheduler group=%s stage=%s failed: %s",
                                group.name, stage.name, exc)
                    finally:
                        status["last_heartbeat_at"] = datetime.utcnow()
                status["iterations"] += 1
                status["last_finished_at"] = datetime.utcnow()
                status["stage"] = "sleep"
                status["last_heartbeat_at"] = datetime.utcnow()
                elapsed = asyncio.get_running_loop().time() - started
                await asyncio.sleep(max(0.05, group.interval_seconds - elapsed))
        finally:
            status["alive"] = False
            status["stage"] = "stopped"
            status["last_heartbeat_at"] = datetime.utcnow()
