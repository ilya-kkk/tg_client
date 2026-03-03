import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.warmup_config import WARMUP_MODES


logger = logging.getLogger(__name__)


class WarmupWorker:
    """Управляет фоновыми asyncio-задачами прогрева по job_id."""

    def __init__(self) -> None:
        self._running: dict[str, asyncio.Task[Any]] = {}

    @property
    def running(self) -> dict[str, asyncio.Task[Any]]:
        return self._running

    @staticmethod
    def _get_job_id(job: dict) -> str:
        return str(job.get("id") or "").strip()

    def start(self, job: dict) -> None:
        """Запускает задачу прогрева для кампании, если она ещё не запущена."""
        job_id = self._get_job_id(job)
        if not job_id:
            return

        existing_task = self._running.get(job_id)
        if existing_task is not None and not existing_task.done():
            return

        if existing_task is not None and existing_task.done():
            self._running.pop(job_id, None)

        self._running[job_id] = asyncio.create_task(
            self._run_job(job),
            name=f"warmup-job-{job_id}",
        )

    async def stop(self, job_id: str) -> None:
        """Останавливает задачу конкретной кампании."""
        task = self._running.pop(job_id, None)
        if task is None:
            return

        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def stop_all(self) -> None:
        """Останавливает все запущенные задачи прогрева."""
        for job_id in list(self._running.keys()):
            await self.stop(job_id)

    async def _run_job(self, job: dict) -> None:
        """Минимальный цикл прогрева кампании."""
        job_id = self._get_job_id(job)
        mode = str(job.get("mode") or "normal")
        mode_config = WARMUP_MODES.get(mode) or WARMUP_MODES["normal"]
        sleep_seconds = max(5, int(mode_config["min_delay_sec"]))

        logger.info("Запущен warmup-воркер: job_id=%s mode=%s", job_id, mode)
        try:
            while True:
                await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            logger.info("Остановлен warmup-воркер: job_id=%s", job_id)
            raise
