import asyncio

from app import main


def test_sync_warmup_job_workers_starts_workers_for_active_jobs():
    async def scenario():
        main.warmup_job_tasks.clear()
        try:
            await main.sync_warmup_job_workers(
                [
                    {"id": "job-1", "mode": "normal"},
                    {"id": "job-2", "mode": "cautious"},
                ]
            )
            assert set(main.warmup_job_tasks.keys()) == {"job-1", "job-2"}
            assert all(not task.done() for task in main.warmup_job_tasks.values())
        finally:
            await main.stop_all_warmup_job_workers()
            main.warmup_job_tasks.clear()

    asyncio.run(scenario())


def test_sync_warmup_job_workers_does_not_duplicate_running_worker():
    async def scenario():
        main.warmup_job_tasks.clear()
        try:
            await main.sync_warmup_job_workers([{"id": "job-1", "mode": "normal"}])
            first_task = main.warmup_job_tasks["job-1"]

            await main.sync_warmup_job_workers([{"id": "job-1", "mode": "normal"}])
            second_task = main.warmup_job_tasks["job-1"]

            assert first_task is second_task
        finally:
            await main.stop_all_warmup_job_workers()
            main.warmup_job_tasks.clear()

    asyncio.run(scenario())


def test_sync_warmup_job_workers_stops_inactive_workers():
    async def scenario():
        main.warmup_job_tasks.clear()
        try:
            await main.sync_warmup_job_workers(
                [
                    {"id": "job-1", "mode": "normal"},
                    {"id": "job-2", "mode": "aggressive"},
                ]
            )
            removed_task = main.warmup_job_tasks["job-2"]

            await main.sync_warmup_job_workers([{"id": "job-1", "mode": "normal"}])

            assert set(main.warmup_job_tasks.keys()) == {"job-1"}
            assert removed_task.cancelled()
        finally:
            await main.stop_all_warmup_job_workers()
            main.warmup_job_tasks.clear()

    asyncio.run(scenario())
