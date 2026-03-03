import asyncio

from app.warmup_worker import WarmupWorker


def test_start_creates_task_and_does_not_duplicate_running_job():
    async def scenario():
        worker = WarmupWorker()
        try:
            worker.start({"id": "job-1", "mode": "normal"})
            first_task = worker.running["job-1"]

            worker.start({"id": "job-1", "mode": "normal"})
            second_task = worker.running["job-1"]

            assert first_task is second_task
            assert not first_task.done()
        finally:
            await worker.stop_all()

    asyncio.run(scenario())


def test_stop_cancels_and_removes_task():
    async def scenario():
        worker = WarmupWorker()
        worker.start({"id": "job-1", "mode": "normal"})
        task = worker.running["job-1"]

        await worker.stop("job-1")

        assert "job-1" not in worker.running
        assert task.cancelled()

    asyncio.run(scenario())


def test_stop_all_cancels_all_tasks():
    async def scenario():
        worker = WarmupWorker()
        worker.start({"id": "job-1", "mode": "normal"})
        worker.start({"id": "job-2", "mode": "cautious"})
        tasks = list(worker.running.values())

        await worker.stop_all()

        assert worker.running == {}
        assert all(task.cancelled() for task in tasks)

    asyncio.run(scenario())
