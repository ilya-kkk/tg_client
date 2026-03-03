import asyncio

import pytest

import app.warmup_worker as warmup_worker_module
from app.warmup_config import WARMUP_MODES
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


def test_run_action_dispatches_to_corresponding_method(monkeypatch: pytest.MonkeyPatch):
    async def scenario():
        worker = WarmupWorker()
        called_with: dict[str, str] = {}

        async def fake_handler(session_id: str, job: dict):
            called_with["session_id"] = session_id
            called_with["job_id"] = job["id"]

        monkeypatch.setattr(worker, "_warmup_react_to_message", fake_handler)

        await worker._run_action(
            action_type="react_to_message",
            session_id="session-1",
            job={"id": "job-1"},
        )

        assert called_with == {"session_id": "session-1", "job_id": "job-1"}

    asyncio.run(scenario())


def test_run_job_randomly_chooses_session_action_and_delay(monkeypatch: pytest.MonkeyPatch):
    async def scenario():
        worker = WarmupWorker()
        job = {
            "id": "job-1",
            "mode": "cautious",
            "account_sessions": ["session-1", "session-2"],
            "enabled_actions": ["read_messages", "update_status"],
        }
        chosen_values = iter(["session-2", "update_status"])
        observed: dict[str, object] = {}
        sleep_calls: list[int] = []
        randint_calls: list[tuple[int, int]] = []

        def fake_choice(values: list[str]) -> str:
            return next(chosen_values)

        def fake_randint(min_value: int, max_value: int) -> int:
            randint_calls.append((min_value, max_value))
            return min_value + 7

        async def fake_run_action(action_type: str, session_id: str, current_job: dict) -> None:
            observed["action_type"] = action_type
            observed["session_id"] = session_id
            observed["job_id"] = current_job["id"]

        async def fake_sleep(seconds: int) -> None:
            sleep_calls.append(seconds)
            raise asyncio.CancelledError

        monkeypatch.setattr(warmup_worker_module.random, "choice", fake_choice)
        monkeypatch.setattr(warmup_worker_module.random, "randint", fake_randint)
        monkeypatch.setattr(worker, "_run_action", fake_run_action)
        monkeypatch.setattr(warmup_worker_module.asyncio, "sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await worker._run_job(job)

        expected_range = (
            WARMUP_MODES["cautious"]["min_delay_sec"],
            WARMUP_MODES["cautious"]["max_delay_sec"],
        )
        assert observed == {
            "action_type": "update_status",
            "session_id": "session-2",
            "job_id": "job-1",
        }
        assert randint_calls == [expected_range]
        assert sleep_calls == [expected_range[0] + 7]

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
