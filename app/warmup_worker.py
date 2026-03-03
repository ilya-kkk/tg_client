import asyncio
import logging
import random
from contextlib import suppress
from typing import Any

from app.warmup_config import WARMUP_MODES


logger = logging.getLogger(__name__)


class WarmupWorker:
    """Управляет фоновыми asyncio-задачами прогрева по job_id."""

    _ACTION_METHODS: dict[str, str] = {
        "read_messages": "_warmup_read_messages",
        "react_to_message": "_warmup_react_to_message",
        "join_channel": "_warmup_join_channel",
        "view_story": "_warmup_view_story",
        "search_global": "_warmup_search_global",
        "update_status": "_warmup_update_status",
    }

    def __init__(self) -> None:
        self._running: dict[str, asyncio.Task[Any]] = {}

    @property
    def running(self) -> dict[str, asyncio.Task[Any]]:
        return self._running

    @staticmethod
    def _get_job_id(job: dict) -> str:
        return str(job.get("id") or "").strip()

    @staticmethod
    def _normalize_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            item_str = str(item).strip()
            if item_str:
                normalized.append(item_str)
        return normalized

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

    async def _run_action(self, action_type: str, session_id: str, job: dict) -> None:
        method_name = self._ACTION_METHODS.get(action_type)
        if method_name is None:
            logger.warning(
                "Неизвестный тип warmup-действия, пропуск: job_id=%s action=%s",
                self._get_job_id(job),
                action_type,
            )
            return

        handler = getattr(self, method_name, None)
        if handler is None:
            logger.warning(
                "Не найден обработчик warmup-действия, пропуск: job_id=%s action=%s method=%s",
                self._get_job_id(job),
                action_type,
                method_name,
            )
            return

        await handler(session_id, job)

    async def _log_not_implemented_action(
        self,
        action_type: str,
        session_id: str,
        job: dict,
    ) -> None:
        logger.debug(
            "Warmup-действие пока не реализовано: job_id=%s session_id=%s action=%s",
            self._get_job_id(job),
            session_id,
            action_type,
        )

    async def _warmup_read_messages(self, session_id: str, job: dict) -> None:
        await self._log_not_implemented_action("read_messages", session_id, job)

    async def _warmup_react_to_message(self, session_id: str, job: dict) -> None:
        await self._log_not_implemented_action("react_to_message", session_id, job)

    async def _warmup_join_channel(self, session_id: str, job: dict) -> None:
        await self._log_not_implemented_action("join_channel", session_id, job)

    async def _warmup_view_story(self, session_id: str, job: dict) -> None:
        await self._log_not_implemented_action("view_story", session_id, job)

    async def _warmup_search_global(self, session_id: str, job: dict) -> None:
        await self._log_not_implemented_action("search_global", session_id, job)

    async def _warmup_update_status(self, session_id: str, job: dict) -> None:
        await self._log_not_implemented_action("update_status", session_id, job)

    async def _run_job(self, job: dict) -> None:
        """Основной цикл прогрева кампании."""
        job_id = self._get_job_id(job)
        mode = str(job.get("mode") or "normal").strip().lower()
        mode_config = WARMUP_MODES.get(mode) or WARMUP_MODES["normal"]
        min_delay_sec = max(1, int(mode_config["min_delay_sec"]))
        max_delay_sec = max(min_delay_sec, int(mode_config["max_delay_sec"]))

        logger.info("Запущен warmup-воркер: job_id=%s mode=%s", job_id, mode)
        try:
            while True:
                account_sessions = self._normalize_str_list(job.get("account_sessions"))
                enabled_actions = self._normalize_str_list(job.get("enabled_actions"))

                if account_sessions and enabled_actions:
                    session_id = random.choice(account_sessions)
                    action_type = random.choice(enabled_actions)
                    await self._run_action(action_type, session_id, job)
                else:
                    logger.debug(
                        "Пропуск итерации warmup-воркера: job_id=%s отсутствуют account_sessions или enabled_actions",
                        job_id,
                    )

                delay_sec = random.randint(min_delay_sec, max_delay_sec)
                await asyncio.sleep(delay_sec)
        except asyncio.CancelledError:
            logger.info("Остановлен warmup-воркер: job_id=%s", job_id)
            raise
