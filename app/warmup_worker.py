import asyncio
import inspect
import logging
import random
import re
from contextlib import suppress
from typing import Any, Optional, TYPE_CHECKING

from app.warmup_config import WARMUP_MODES

if TYPE_CHECKING:
    from app.telegram_client import MultiSessionManager


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

    _BASE_REACTIONS: tuple[str, ...] = (
        "👍",
        "❤️",
        "🔥",
        "👏",
        "🤔",
        "🎉",
        "😁",
        "🥰",
        "💯",
        "👌",
    )

    _SEARCH_TERMS: tuple[str, ...] = (
        "news",
        "music",
        "books",
        "movies",
        "travel",
        "food",
        "fitness",
        "health",
        "science",
        "technology",
        "python",
        "javascript",
        "design",
        "art",
        "history",
        "language",
        "education",
        "business",
        "finance",
        "startup",
        "marketing",
        "sport",
        "football",
        "basketball",
        "chess",
        "gaming",
        "photography",
        "nature",
        "animals",
        "cars",
        "fashion",
        "style",
        "lifestyle",
        "recipes",
        "coffee",
        "tea",
        "productivity",
        "career",
        "remote",
        "ai",
        "machine learning",
        "cybersecurity",
        "cloud",
        "devops",
        "mobile",
        "android",
        "ios",
        "crypto",
        "economy",
        "culture",
    )

    def __init__(self, client_manager: Optional["MultiSessionManager"] = None) -> None:
        self._running: dict[str, asyncio.Task[Any]] = {}
        self._client_manager = client_manager

    @property
    def running(self) -> dict[str, asyncio.Task[Any]]:
        return self._running

    def set_client_manager(self, client_manager: Optional["MultiSessionManager"]) -> None:
        self._client_manager = client_manager

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

    @staticmethod
    def _normalize_chat_identifier(value: str) -> str:
        chat = (value or "").strip()
        if chat.startswith("https://t.me/"):
            chat = "@" + chat.removeprefix("https://t.me/").split("?")[0].strip("/")
        elif chat.startswith("http://t.me/"):
            chat = "@" + chat.removeprefix("http://t.me/").split("?")[0].strip("/")
        elif chat.startswith("t.me/"):
            chat = "@" + chat.removeprefix("t.me/").split("?")[0].strip("/")
        return chat

    def _normalize_target_channels(self, job: dict) -> list[str]:
        raw = self._normalize_str_list(job.get("target_channels"))
        return [self._normalize_chat_identifier(item) for item in raw if self._normalize_chat_identifier(item)]

    def _pick_target_channel(self, job: dict) -> Optional[str]:
        targets = self._normalize_target_channels(job)
        if not targets:
            return None
        return random.choice(targets)

    @staticmethod
    def _parse_chat_identifier(value: str) -> str | int:
        normalized = (value or "").strip()
        if re.fullmatch(r"-?\d+", normalized):
            return int(normalized)
        return normalized

    @staticmethod
    def _build_request(request_cls: Any, **kwargs: Any) -> Any:
        signature = inspect.signature(request_cls.__init__)
        accepted = {
            name
            for name in signature.parameters.keys()
            if name not in {"self", "args", "kwargs"}
        }
        filtered_kwargs = {key: value for key, value in kwargs.items() if key in accepted}
        return request_cls(**filtered_kwargs)

    @staticmethod
    def _load_telethon() -> Optional[dict[str, Any]]:
        try:
            from telethon.errors import RPCError, UserAlreadyParticipantError
            from telethon.tl import functions, types
        except Exception:
            logger.warning("Telethon недоступен: warmup-действия пропущены")
            return None

        return {
            "RPCError": RPCError,
            "UserAlreadyParticipantError": UserAlreadyParticipantError,
            "functions": functions,
            "types": types,
        }

    async def _get_session_client(self, session_id: str, job: dict) -> Any:
        if self._client_manager is None:
            logger.debug(
                "Warmup-клиент не инициализирован: job_id=%s session_id=%s",
                self._get_job_id(job),
                session_id,
            )
            return None

        try:
            return await self._client_manager.get_client(session_id)
        except Exception as e:
            logger.warning(
                "Не удалось получить клиента для warmup-действия: job_id=%s session_id=%s error=%s",
                self._get_job_id(job),
                session_id,
                e,
            )
            return None

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

    async def _warmup_read_messages(self, session_id: str, job: dict) -> None:
        telethon = self._load_telethon()
        if telethon is None:
            return

        target_chat = self._pick_target_channel(job)
        if not target_chat:
            logger.debug(
                "Пропуск read_messages: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        client = await self._get_session_client(session_id, job)
        if client is None:
            return

        functions = telethon["functions"]
        chat_identifier = self._parse_chat_identifier(target_chat)

        try:
            peer = await client.get_input_entity(chat_identifier)
            history_limit = random.randint(3, 15)
            response = await client(
                self._build_request(
                    functions.messages.GetHistoryRequest,
                    peer=peer,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=history_limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
            messages = list(getattr(response, "messages", []) or [])[:15]
            for _ in messages:
                await asyncio.sleep(random.uniform(0.5, 2.0))

            logger.info(
                "Warmup read_messages выполнен: job_id=%s session_id=%s chat=%s read_count=%s",
                self._get_job_id(job),
                session_id,
                target_chat,
                len(messages),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup read_messages: job_id=%s session_id=%s chat=%s error=%s",
                self._get_job_id(job),
                session_id,
                target_chat,
                e,
            )

    async def _warmup_react_to_message(self, session_id: str, job: dict) -> None:
        telethon = self._load_telethon()
        if telethon is None:
            return

        target_chat = self._pick_target_channel(job)
        if not target_chat:
            logger.debug(
                "Пропуск react_to_message: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        client = await self._get_session_client(session_id, job)
        if client is None:
            return

        functions = telethon["functions"]
        types = telethon["types"]
        chat_identifier = self._parse_chat_identifier(target_chat)

        try:
            peer = await client.get_input_entity(chat_identifier)
            response = await client(
                self._build_request(
                    functions.messages.GetHistoryRequest,
                    peer=peer,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=20,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
            messages = [
                message
                for message in (getattr(response, "messages", []) or [])
                if getattr(message, "id", None) is not None and not getattr(message, "out", False)
            ]
            if not messages:
                logger.debug(
                    "Пропуск react_to_message: job_id=%s session_id=%s chat=%s нет подходящих сообщений",
                    self._get_job_id(job),
                    session_id,
                    target_chat,
                )
                return

            selected_message = random.choice(messages)
            selected_reaction = random.choice(self._BASE_REACTIONS)

            if hasattr(client, "send_reaction"):
                await client.send_reaction(peer, int(selected_message.id), reaction=selected_reaction)
            else:
                await client(
                    self._build_request(
                        functions.messages.SendReactionRequest,
                        peer=peer,
                        msg_id=int(selected_message.id),
                        reaction=[types.ReactionEmoji(emoticon=selected_reaction)],
                        big=False,
                        add_to_recent=False,
                    )
                )

            logger.info(
                "Warmup react_to_message выполнен: job_id=%s session_id=%s chat=%s message_id=%s reaction=%s",
                self._get_job_id(job),
                session_id,
                target_chat,
                int(selected_message.id),
                selected_reaction,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup react_to_message: job_id=%s session_id=%s chat=%s error=%s",
                self._get_job_id(job),
                session_id,
                target_chat,
                e,
            )

    async def _warmup_join_channel(self, session_id: str, job: dict) -> None:
        telethon = self._load_telethon()
        if telethon is None:
            return

        target_channel = self._pick_target_channel(job)
        if not target_channel:
            logger.debug(
                "Пропуск join_channel: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        client = await self._get_session_client(session_id, job)
        if client is None:
            return

        functions = telethon["functions"]
        RPCError = telethon["RPCError"]
        UserAlreadyParticipantError = telethon["UserAlreadyParticipantError"]
        channel_identifier = self._parse_chat_identifier(target_channel)

        try:
            entity = await client.get_input_entity(channel_identifier)
            await client(
                self._build_request(
                    functions.channels.JoinChannelRequest,
                    channel=entity,
                )
            )
            logger.info(
                "Warmup join_channel выполнен: job_id=%s session_id=%s channel=%s",
                self._get_job_id(job),
                session_id,
                target_channel,
            )
        except asyncio.CancelledError:
            raise
        except UserAlreadyParticipantError:
            logger.debug(
                "Warmup join_channel: уже подписан, пропуск: job_id=%s session_id=%s channel=%s",
                self._get_job_id(job),
                session_id,
                target_channel,
            )
        except RPCError as e:
            if "already" in str(e).lower() and "participant" in str(e).lower():
                logger.debug(
                    "Warmup join_channel: уже подписан (RPC), пропуск: job_id=%s session_id=%s channel=%s",
                    self._get_job_id(job),
                    session_id,
                    target_channel,
                )
                return
            logger.warning(
                "Ошибка warmup join_channel: job_id=%s session_id=%s channel=%s error=%s",
                self._get_job_id(job),
                session_id,
                target_channel,
                e,
            )
        except Exception as e:
            logger.warning(
                "Ошибка warmup join_channel: job_id=%s session_id=%s channel=%s error=%s",
                self._get_job_id(job),
                session_id,
                target_channel,
                e,
            )

    async def _warmup_view_story(self, session_id: str, job: dict) -> None:
        telethon = self._load_telethon()
        if telethon is None:
            return

        target_chat = self._pick_target_channel(job)
        if not target_chat:
            logger.debug(
                "Пропуск view_story: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        client = await self._get_session_client(session_id, job)
        if client is None:
            return

        functions = telethon["functions"]
        chat_identifier = self._parse_chat_identifier(target_chat)

        try:
            peer = await client.get_input_entity(chat_identifier)
            get_peer_stories_cls = getattr(functions.stories, "GetPeerStoriesRequest", None)
            get_stories_cls = getattr(functions.stories, "GetStoriesRequest", None)
            read_stories_cls = getattr(functions.stories, "ReadStoriesRequest", None)

            story_ids: list[int] = []
            if get_peer_stories_cls is not None:
                peer_stories = await client(self._build_request(get_peer_stories_cls, peer=peer))
                stories_obj = getattr(peer_stories, "stories", None)
                stories = getattr(stories_obj, "stories", None) if stories_obj is not None else None
                if stories:
                    story_ids = [
                        int(item.id)
                        for item in stories
                        if getattr(item, "id", None) is not None
                    ]

            if not story_ids:
                logger.debug(
                    "Warmup view_story: сторис не найдены: job_id=%s session_id=%s chat=%s",
                    self._get_job_id(job),
                    session_id,
                    target_chat,
                )
                return

            selected_story_id = random.choice(story_ids)
            if get_stories_cls is not None:
                await client(
                    self._build_request(
                        get_stories_cls,
                        peer=peer,
                        id=[selected_story_id],
                    )
                )

            if read_stories_cls is not None:
                await client(
                    self._build_request(
                        read_stories_cls,
                        peer=peer,
                        max_id=selected_story_id,
                    )
                )

            logger.info(
                "Warmup view_story выполнен: job_id=%s session_id=%s chat=%s story_id=%s",
                self._get_job_id(job),
                session_id,
                target_chat,
                selected_story_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup view_story: job_id=%s session_id=%s chat=%s error=%s",
                self._get_job_id(job),
                session_id,
                target_chat,
                e,
            )

    async def _warmup_search_global(self, session_id: str, job: dict) -> None:
        telethon = self._load_telethon()
        if telethon is None:
            return

        client = await self._get_session_client(session_id, job)
        if client is None:
            return

        functions = telethon["functions"]
        types = telethon["types"]
        search_query = random.choice(self._SEARCH_TERMS)

        try:
            await client(
                self._build_request(
                    functions.messages.SearchGlobalRequest,
                    q=search_query,
                    filter=types.InputMessagesFilterEmpty(),
                    min_date=0,
                    max_date=0,
                    offset_rate=0,
                    offset_peer=types.InputPeerEmpty(),
                    offset_id=0,
                    limit=20,
                    folder_id=None,
                )
            )

            logger.info(
                "Warmup search_global выполнен: job_id=%s session_id=%s query=%s",
                self._get_job_id(job),
                session_id,
                search_query,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup search_global: job_id=%s session_id=%s query=%s error=%s",
                self._get_job_id(job),
                session_id,
                search_query,
                e,
            )

    async def _warmup_update_status(self, session_id: str, job: dict) -> None:
        telethon = self._load_telethon()
        if telethon is None:
            return

        client = await self._get_session_client(session_id, job)
        if client is None:
            return

        functions = telethon["functions"]

        try:
            if not client.is_connected():
                await client.connect()

            await client(functions.account.UpdateStatusRequest(offline=False))
            online_duration_sec = random.randint(10, 30)
            await asyncio.sleep(online_duration_sec)
            await client(functions.account.UpdateStatusRequest(offline=True))

            logger.info(
                "Warmup update_status выполнен: job_id=%s session_id=%s online_seconds=%s",
                self._get_job_id(job),
                session_id,
                online_duration_sec,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup update_status: job_id=%s session_id=%s error=%s",
                self._get_job_id(job),
                session_id,
                e,
            )

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
