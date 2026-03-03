import asyncio
import inspect
import logging
import random
import re
import time
from contextlib import suppress
from typing import Any, Optional, TYPE_CHECKING

from app.warmup_config import WARMUP_MODES

if TYPE_CHECKING:
    from app.telegram_client import MultiSessionManager


logger = logging.getLogger(__name__)


class WarmupWorker:
    """Управляет фоновыми asyncio-задачами прогрева по job_id."""

    _FLOOD_WAIT_ERROR_NAME = "FloodWaitError"
    _SKIP_CHAT_ERROR_NAMES: set[str] = {
        "UserBannedInChannelError",
        "ChatWriteForbiddenError",
    }

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
        self._session_pause_until: dict[str, float] = {}

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

    def _pick_target_channel(self, job: dict, excluded_chats: Optional[set[str]] = None) -> Optional[str]:
        targets = self._normalize_target_channels(job)
        if excluded_chats:
            targets = [item for item in targets if item not in excluded_chats]
        if not targets:
            return None
        return random.choice(targets)

    @staticmethod
    def _current_monotonic_time() -> float:
        return time.monotonic()

    @staticmethod
    def _error_name(error: BaseException) -> str:
        return type(error).__name__

    @classmethod
    def _is_flood_wait_error(cls, error: BaseException) -> bool:
        return cls._error_name(error) == cls._FLOOD_WAIT_ERROR_NAME

    @classmethod
    def _is_skip_chat_error(cls, error: BaseException) -> bool:
        return cls._error_name(error) in cls._SKIP_CHAT_ERROR_NAMES

    @classmethod
    def _extract_flood_wait_seconds(cls, error: BaseException) -> int:
        if not cls._is_flood_wait_error(error):
            return 0

        raw_seconds = getattr(error, "seconds", 0)
        try:
            seconds = int(raw_seconds)
        except (TypeError, ValueError):
            return 0
        return max(0, seconds)

    @staticmethod
    def _mark_error_chat(error: BaseException, chat: str) -> None:
        if not chat:
            return
        try:
            setattr(error, "_warmup_chat", chat)
        except Exception:
            return

    def _get_error_chat(self, error: BaseException) -> str:
        raw_chat = str(getattr(error, "_warmup_chat", "") or "").strip()
        if not raw_chat:
            return ""
        return self._normalize_chat_identifier(raw_chat)

    def _get_session_pause_remaining(self, session_id: str) -> int:
        paused_until = self._session_pause_until.get(session_id)
        if paused_until is None:
            return 0

        remaining = int(paused_until - self._current_monotonic_time())
        if remaining <= 0:
            self._session_pause_until.pop(session_id, None)
            return 0
        return remaining

    def _pause_session_for_flood_wait(
        self,
        session_id: str,
        flood_wait_seconds: int,
    ) -> int:
        pause_seconds = max(1, int(flood_wait_seconds) + 60)
        current_pause_until = self._session_pause_until.get(session_id, 0.0)
        next_pause_until = self._current_monotonic_time() + pause_seconds
        self._session_pause_until[session_id] = max(current_pause_until, next_pause_until)
        return pause_seconds

    def _raise_known_iteration_errors(
        self,
        error: Exception,
        *,
        chat: str = "",
    ) -> None:
        if self._is_skip_chat_error(error):
            self._mark_error_chat(error, chat)
            raise error
        if self._is_flood_wait_error(error):
            raise error

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

    async def _run_action(
        self,
        action_type: str,
        session_id: str,
        job: dict,
        *,
        excluded_chats: Optional[set[str]] = None,
    ) -> None:
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

        handler_signature = inspect.signature(handler)
        if "excluded_chats" in handler_signature.parameters:
            await handler(session_id, job, excluded_chats=excluded_chats)
        else:
            await handler(session_id, job)

    async def warmup_read_messages(self, session_id: str, chat: str) -> int:
        """Открывает диалог и имитирует чтение до 15 последних сообщений."""
        try:
            return await self._run_warmup_read_messages(
                session_id=session_id,
                chat=chat,
                job_id="",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup read_messages: session_id=%s chat=%s error=%s",
                session_id,
                self._normalize_chat_identifier(chat),
                e,
            )
            return 0

    async def _warmup_read_messages(
        self,
        session_id: str,
        job: dict,
        excluded_chats: Optional[set[str]] = None,
    ) -> None:
        target_chat = self._pick_target_channel(job, excluded_chats=excluded_chats)
        if not target_chat:
            logger.debug(
                "Пропуск read_messages: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        await self._run_warmup_read_messages(
            session_id=session_id,
            chat=target_chat,
            job_id=self._get_job_id(job),
        )

    async def _run_warmup_read_messages(self, session_id: str, chat: str, job_id: str) -> int:
        telethon = self._load_telethon()
        if telethon is None:
            return 0

        client = await self._get_session_client(session_id, {"id": job_id} if job_id else {})
        if client is None:
            return 0

        functions = telethon["functions"]
        normalized_chat = self._normalize_chat_identifier(chat)
        chat_identifier = self._parse_chat_identifier(normalized_chat)

        try:
            peer = await client.get_input_entity(chat_identifier)
            response = await client(
                self._build_request(
                    functions.messages.GetHistoryRequest,
                    peer=peer,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=15,
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
                job_id,
                session_id,
                normalized_chat,
                len(messages),
            )
            return len(messages)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._raise_known_iteration_errors(e, chat=normalized_chat)
            logger.warning(
                "Ошибка warmup read_messages: job_id=%s session_id=%s chat=%s error=%s",
                job_id,
                session_id,
                normalized_chat,
                e,
            )
            return 0

    async def warmup_react_to_message(self, session_id: str, chat: str) -> bool:
        """Ставит случайную базовую реакцию на случайное входящее сообщение из последних."""
        try:
            return await self._run_warmup_react_to_message(
                session_id=session_id,
                chat=chat,
                job_id="",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup react_to_message: session_id=%s chat=%s error=%s",
                session_id,
                self._normalize_chat_identifier(chat),
                e,
            )
            return False

    async def _warmup_react_to_message(
        self,
        session_id: str,
        job: dict,
        excluded_chats: Optional[set[str]] = None,
    ) -> None:
        target_chat = self._pick_target_channel(job, excluded_chats=excluded_chats)
        if not target_chat:
            logger.debug(
                "Пропуск react_to_message: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        await self._run_warmup_react_to_message(
            session_id=session_id,
            chat=target_chat,
            job_id=self._get_job_id(job),
        )

    async def _run_warmup_react_to_message(self, session_id: str, chat: str, job_id: str) -> bool:
        telethon = self._load_telethon()
        if telethon is None:
            return False

        client = await self._get_session_client(session_id, {"id": job_id} if job_id else {})
        if client is None:
            return False

        functions = telethon["functions"]
        types = telethon.get("types")
        normalized_chat = self._normalize_chat_identifier(chat)
        chat_identifier = self._parse_chat_identifier(normalized_chat)

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
                    job_id,
                    session_id,
                    normalized_chat,
                )
                return False

            selected_message = random.choice(messages)
            selected_reaction = random.choice(self._BASE_REACTIONS)

            if hasattr(client, "send_reaction"):
                await client.send_reaction(peer, int(selected_message.id), reaction=selected_reaction)
            else:
                if types is None:
                    logger.warning(
                        "Ошибка warmup react_to_message: job_id=%s session_id=%s chat=%s error=%s",
                        job_id,
                        session_id,
                        normalized_chat,
                        "types не загружен",
                    )
                    return False
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
                job_id,
                session_id,
                normalized_chat,
                int(selected_message.id),
                selected_reaction,
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._raise_known_iteration_errors(e, chat=normalized_chat)
            logger.warning(
                "Ошибка warmup react_to_message: job_id=%s session_id=%s chat=%s error=%s",
                job_id,
                session_id,
                normalized_chat,
                e,
            )
            return False

    async def warmup_join_channel(self, session_id: str, channel: str) -> bool:
        """Подписывается на канал через JoinChannelRequest."""
        try:
            return await self._run_warmup_join_channel(
                session_id=session_id,
                channel=channel,
                job_id="",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup join_channel: session_id=%s channel=%s error=%s",
                session_id,
                self._normalize_chat_identifier(channel),
                e,
            )
            return False

    async def _warmup_join_channel(
        self,
        session_id: str,
        job: dict,
        excluded_chats: Optional[set[str]] = None,
    ) -> None:
        target_channel = self._pick_target_channel(job, excluded_chats=excluded_chats)
        if not target_channel:
            logger.debug(
                "Пропуск join_channel: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        await self._run_warmup_join_channel(
            session_id=session_id,
            channel=target_channel,
            job_id=self._get_job_id(job),
        )

    async def _run_warmup_join_channel(self, session_id: str, channel: str, job_id: str) -> bool:
        telethon = self._load_telethon()
        if telethon is None:
            return False

        client = await self._get_session_client(session_id, {"id": job_id} if job_id else {})
        if client is None:
            return False

        functions = telethon["functions"]
        RPCError = telethon["RPCError"]
        UserAlreadyParticipantError = telethon["UserAlreadyParticipantError"]
        normalized_channel = self._normalize_chat_identifier(channel)
        channel_identifier = self._parse_chat_identifier(normalized_channel)

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
                job_id,
                session_id,
                normalized_channel,
            )
            return True
        except asyncio.CancelledError:
            raise
        except UserAlreadyParticipantError:
            logger.debug(
                "Warmup join_channel: уже подписан, пропуск: job_id=%s session_id=%s channel=%s",
                job_id,
                session_id,
                normalized_channel,
            )
            return False
        except RPCError as e:
            if "already" in str(e).lower() and "participant" in str(e).lower():
                logger.debug(
                    "Warmup join_channel: уже подписан (RPC), пропуск: job_id=%s session_id=%s channel=%s",
                    job_id,
                    session_id,
                    normalized_channel,
                )
                return False
            self._raise_known_iteration_errors(e, chat=normalized_channel)
            logger.warning(
                "Ошибка warmup join_channel: job_id=%s session_id=%s channel=%s error=%s",
                job_id,
                session_id,
                normalized_channel,
                e,
            )
            return False
        except Exception as e:
            self._raise_known_iteration_errors(e, chat=normalized_channel)
            logger.warning(
                "Ошибка warmup join_channel: job_id=%s session_id=%s channel=%s error=%s",
                job_id,
                session_id,
                normalized_channel,
                e,
            )
            return False

    async def warmup_view_story(self, session_id: str, chat: str) -> bool:
        """Просматривает одну случайную сторис контакта/канала через GetStoriesRequest."""
        try:
            return await self._run_warmup_view_story(
                session_id=session_id,
                chat=chat,
                job_id="",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup view_story: session_id=%s chat=%s error=%s",
                session_id,
                self._normalize_chat_identifier(chat),
                e,
            )
            return False

    async def _warmup_view_story(
        self,
        session_id: str,
        job: dict,
        excluded_chats: Optional[set[str]] = None,
    ) -> None:
        target_chat = self._pick_target_channel(job, excluded_chats=excluded_chats)
        if not target_chat:
            logger.debug(
                "Пропуск view_story: job_id=%s нет target_channels",
                self._get_job_id(job),
            )
            return

        await self._run_warmup_view_story(
            session_id=session_id,
            chat=target_chat,
            job_id=self._get_job_id(job),
        )

    async def _run_warmup_view_story(self, session_id: str, chat: str, job_id: str) -> bool:
        telethon = self._load_telethon()
        if telethon is None:
            return False

        client = await self._get_session_client(session_id, {"id": job_id} if job_id else {})
        if client is None:
            return False

        functions = telethon["functions"]
        stories_functions = getattr(functions, "stories", None)
        if stories_functions is None:
            logger.debug(
                "Пропуск view_story: job_id=%s session_id=%s chat=%s нет stories API",
                job_id,
                session_id,
                chat,
            )
            return False

        normalized_chat = self._normalize_chat_identifier(chat)
        chat_identifier = self._parse_chat_identifier(normalized_chat)

        try:
            peer = await client.get_input_entity(chat_identifier)
            get_stories_cls = getattr(stories_functions, "GetStoriesRequest", None)
            get_peer_stories_cls = getattr(stories_functions, "GetPeerStoriesRequest", None)
            read_stories_cls = getattr(stories_functions, "ReadStoriesRequest", None)

            if get_stories_cls is None:
                logger.debug(
                    "Пропуск view_story: job_id=%s session_id=%s chat=%s нет GetStoriesRequest",
                    job_id,
                    session_id,
                    normalized_chat,
                )
                return False

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
                    job_id,
                    session_id,
                    normalized_chat,
                )
                return False

            selected_story_id = random.choice(story_ids)
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
                job_id,
                session_id,
                normalized_chat,
                selected_story_id,
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._raise_known_iteration_errors(e, chat=normalized_chat)
            logger.warning(
                "Ошибка warmup view_story: job_id=%s session_id=%s chat=%s error=%s",
                job_id,
                session_id,
                normalized_chat,
                e,
            )
            return False

    async def warmup_search_global(self, session_id: str) -> bool:
        """Выполняет глобальный поиск по случайному слову из встроенного словаря."""
        try:
            return await self._run_warmup_search_global(
                session_id=session_id,
                job_id="",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup search_global: session_id=%s error=%s",
                session_id,
                e,
            )
            return False

    async def _warmup_search_global(self, session_id: str, job: dict) -> None:
        await self._run_warmup_search_global(
            session_id=session_id,
            job_id=self._get_job_id(job),
        )

    async def _run_warmup_search_global(self, session_id: str, job_id: str) -> bool:
        telethon = self._load_telethon()
        if telethon is None:
            return False

        client = await self._get_session_client(session_id, {"id": job_id} if job_id else {})
        if client is None:
            return False

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
                job_id,
                session_id,
                search_query,
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._raise_known_iteration_errors(e)
            logger.warning(
                "Ошибка warmup search_global: job_id=%s session_id=%s query=%s error=%s",
                job_id,
                session_id,
                search_query,
                e,
            )
            return False

    async def warmup_update_status(self, session_id: str) -> bool:
        """Переключает статус аккаунта в online, затем обратно в offline."""
        try:
            return await self._run_warmup_update_status(
                session_id=session_id,
                job_id="",
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Ошибка warmup update_status: session_id=%s error=%s",
                session_id,
                e,
            )
            return False

    async def _warmup_update_status(self, session_id: str, job: dict) -> None:
        await self._run_warmup_update_status(
            session_id=session_id,
            job_id=self._get_job_id(job),
        )

    async def _run_warmup_update_status(self, session_id: str, job_id: str) -> bool:
        telethon = self._load_telethon()
        if telethon is None:
            return False

        client = await self._get_session_client(session_id, {"id": job_id} if job_id else {})
        if client is None:
            return False

        functions = telethon["functions"]

        try:
            await client.connect()

            await client(functions.account.UpdateStatusRequest(offline=False))
            online_duration_sec = random.randint(10, 30)
            await asyncio.sleep(online_duration_sec)
            await client(functions.account.UpdateStatusRequest(offline=True))

            logger.info(
                "Warmup update_status выполнен: job_id=%s session_id=%s online_seconds=%s",
                job_id,
                session_id,
                online_duration_sec,
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._raise_known_iteration_errors(e)
            logger.warning(
                "Ошибка warmup update_status: job_id=%s session_id=%s error=%s",
                job_id,
                session_id,
                e,
            )
            return False

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
                iteration_excluded_chats: set[str] = set()

                if account_sessions and enabled_actions:
                    available_sessions = [
                        session_id
                        for session_id in account_sessions
                        if self._get_session_pause_remaining(session_id) <= 0
                    ]
                    if available_sessions:
                        session_id = random.choice(available_sessions)
                        action_type = random.choice(enabled_actions)
                        try:
                            await self._run_action(
                                action_type,
                                session_id,
                                job,
                                excluded_chats=iteration_excluded_chats,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            if self._is_flood_wait_error(e):
                                flood_wait_seconds = self._extract_flood_wait_seconds(e)
                                pause_seconds = self._pause_session_for_flood_wait(
                                    session_id=session_id,
                                    flood_wait_seconds=flood_wait_seconds,
                                )
                                logger.warning(
                                    "FloodWait в warmup-действии: job_id=%s session_id=%s wait_seconds=%s pause_seconds=%s",
                                    job_id,
                                    session_id,
                                    flood_wait_seconds,
                                    pause_seconds,
                                )
                            elif self._is_skip_chat_error(e):
                                excluded_chat = self._get_error_chat(e)
                                if excluded_chat:
                                    iteration_excluded_chats.add(excluded_chat)
                                logger.warning(
                                    "Пропуск warmup-действия из-за ограничений чата: job_id=%s session_id=%s action=%s chat=%s error=%s",
                                    job_id,
                                    session_id,
                                    action_type,
                                    excluded_chat or "<unknown>",
                                    e,
                                )
                            else:
                                logger.warning(
                                    "Ошибка warmup-действия, переход к следующей итерации: job_id=%s session_id=%s action=%s error=%s",
                                    job_id,
                                    session_id,
                                    action_type,
                                    e,
                                )
                    else:
                        min_remaining = min(
                            self._get_session_pause_remaining(session_id)
                            for session_id in account_sessions
                        )
                        logger.debug(
                            "Пропуск итерации warmup-воркера: job_id=%s все session_id на паузе min_remaining=%s",
                            job_id,
                            min_remaining,
                        )
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
