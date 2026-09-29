import asyncio

from app.services.scheduler_runtime import (
    PeriodicScheduler,
    SchedulerGroup,
    SchedulerStage,
)


def test_scheduler_groups_run_independently_when_scan_is_slow():
    async def scenario():
        scan_started = asyncio.Event()
        release_scan = asyncio.Event()
        write_ran = asyncio.Event()

        async def slow_scan():
            scan_started.set()
            await release_scan.wait()

        async def write_once():
            write_ran.set()

        scheduler = PeriodicScheduler((
            SchedulerGroup("scan", 1.0, (SchedulerStage("slow", slow_scan),)),
            SchedulerGroup("writes", 1.0, (SchedulerStage("write", write_once),)),
        ))
        scheduler.start()
        try:
            await asyncio.wait_for(scan_started.wait(), 0.5)
            await asyncio.wait_for(write_ran.wait(), 0.5)
            status = scheduler.status()
            assert status["scan"]["alive"] is True
            assert status["writes"]["alive"] is True
        finally:
            release_scan.set()
            await scheduler.stop()

    asyncio.run(scenario())


def test_stage_failure_does_not_skip_later_stage():
    async def scenario():
        later_ran = asyncio.Event()

        async def broken():
            raise RuntimeError("fixture")

        async def later():
            later_ran.set()

        scheduler = PeriodicScheduler((
            SchedulerGroup("scan", 1.0, (
                SchedulerStage("broken", broken),
                SchedulerStage("later", later),
            )),
        ))
        scheduler.start()
        try:
            await asyncio.wait_for(later_ran.wait(), 0.5)
            status = scheduler.status()["scan"]
            assert "broken" in status["last_error"]
        finally:
            await scheduler.stop()

    asyncio.run(scenario())


def test_stage_timeout_is_contained_within_group():
    async def scenario():
        later_ran = asyncio.Event()

        async def hangs():
            await asyncio.sleep(1)

        async def later():
            later_ran.set()

        scheduler = PeriodicScheduler((
            SchedulerGroup("maintenance", 1.0, (
                SchedulerStage("hang", hangs, timeout_seconds=0.02),
                SchedulerStage("later", later),
            )),
        ))
        scheduler.start()
        try:
            await asyncio.wait_for(later_ran.wait(), 0.5)
            assert scheduler.status()["maintenance"]["alive"] is True
        finally:
            await scheduler.stop()

    asyncio.run(scenario())
