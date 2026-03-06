import asyncio
import base64
import binascii
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    FloodWaitError,
    RPCError
)
from telethon.tl import functions, types
from telethon.tl.types import (
    User,
    Chat,
    Channel,
    MessageMediaPhoto,
    MessageMediaDocument,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
)
from app.ai_client import OpenRouterClient
from app.config import API_ID, API_HASH
from app.supabase_client import AiCommentJobsRepo, SessionRepo

AUTH_REQUEST_TIMEOUT_SECONDS = 30
POPULAR_REACTIONS: List[str] = ["👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "💯", "🎉"]
AI_COMMENT_JOB_MESSAGES_LIMIT = 100
AI_COMMENT_TEXT_LIMIT = 1000
AI_COMMENT_FLOOD_WAIT_PADDING_SECONDS = 60
AI_COMMENT_COMMENTS_DISABLED_MARKERS = (
    "commenttodiscussionerror",
    "discussionmessageforbiddenerror",
    "msgidinvaliderror",
    "comments are disabled",
    "comments disabled",
    "commenting is not allowed",
    "discussion is disabled",
    "does not allow comments",
    "no linked discussion",
)
AI_COMMENT_ACCOUNT_NO_RIGHTS_MARKERS = (
    "chatwriteforbiddenerror",
    "chatadminrequirederror",
    "userbannedinchannelerror",
    "usernotparticipanterror",
    "channelprivateerror",
    "write forbidden",
    "not enough rights",
    "not enough permissions",
    "no rights",
    "permission denied",
    "not allowed to send",
)
AI_COMMENT_CHANNEL_UNAVAILABLE_MARKERS = (
    "channelinvaliderror",
    "channelpublicgroupnaerror",
    "usernameinvaliderror",
    "usernamenotoccupiederror",
    "invitehashexpirederror",
    "invitehashinvaliderror",
    "peeridinvaliderror",
    "cannot find any entity",
    "chat not found",
    "channel is unavailable",
    " is unavailable",
)
logger = logging.getLogger(__name__)


@dataclass
class ReactionListenerState:
    client: TelegramClient
    handler: Any
    session_id: str
    chat_identifier: str


class MultiSessionManager:
    """Менеджер Telethon с поддержкой нескольких сессий."""

    def __init__(
        self,
        session_repo: Optional[SessionRepo] = None,
        default_session_id: str = "default",
        openrouter_client: Optional[OpenRouterClient] = None,
    ):
        self.session_repo = session_repo
        self.default_session_id = default_session_id
        self.openrouter_client = openrouter_client or OpenRouterClient()
        self._clients: Dict[str, TelegramClient] = {}
        self._auth_clients: Dict[str, TelegramClient] = {}
        self._authorized_sessions: set[str] = set()
        self._auth_state: Dict[str, Dict[str, str]] = {}
        self._reaction_job_listeners: Dict[str, List[ReactionListenerState]] = {}
        self._reaction_job_signatures: Dict[str, str] = {}
        self._reaction_counters: Dict[str, int] = {}
        self._reaction_last_seen_ids: Dict[str, int] = {}
        self._ai_comment_job_round_robin_indexes: Dict[str, int] = {}
        self._ai_comment_session_pause_until: Dict[str, float] = {}

    def _get_session_repo(self) -> SessionRepo:
        if self.session_repo is None:
            self.session_repo = SessionRepo()
        return self.session_repo

    def _create_client(self, string_session: str = "") -> TelegramClient:
        if not API_ID or not API_HASH:
            raise ValueError("API_ID и API_HASH должны быть установлены")
        return TelegramClient(StringSession(string_session), int(API_ID), API_HASH)

    async def _ensure_auth_client(self, session_id: str) -> TelegramClient:
        client = self._auth_clients.get(session_id)
        if client:
            if not client.is_connected():
                await client.connect()
            return client

        client = self._create_client("")
        await client.connect()
        self._auth_clients[session_id] = client
        return client

    def _normalize_session_id(self, session_id: Optional[str]) -> str:
        value = (session_id or "").strip()
        if not value:
            return self.default_session_id
        return value

    async def get_client(self, session_id: str) -> TelegramClient:
        """Возвращает авторизованный клиент для session_id."""
        sid = self._normalize_session_id(session_id)

        cached = self._clients.get(sid)
        if cached:
            if not cached.is_connected():
                await cached.connect()
            if await cached.is_user_authorized():
                self._authorized_sessions.add(sid)
                return cached
            self._clients.pop(sid, None)
            self._authorized_sessions.discard(sid)
            await cached.disconnect()

        row = self._get_session_repo().get(sid) or {}
        string_session = row.get("string_session") or ""
        if not string_session:
            raise ValueError(f"Сессия '{sid}' не найдена или не авторизована")

        client = self._create_client(string_session)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise ValueError(f"Сессия '{sid}' не авторизована")

        self._clients[sid] = client
        self._authorized_sessions.add(sid)
        return client

    def _get_auth_state(self, session_id: str) -> Dict[str, str]:
        state = self._auth_state.get(session_id)
        if state is not None:
            return state

        row = self._get_session_repo().get(session_id)
        state = {
            "phone": (row or {}).get("phone") or "",
            "phone_code_hash": (row or {}).get("phone_code_hash") or "",
        }
        self._auth_state[session_id] = state
        return state

    @property
    def client(self) -> Optional[TelegramClient]:
        session_id = self.default_session_id
        return self._clients.get(session_id) or self._auth_clients.get(session_id)

    @client.setter
    def client(self, value: Optional[TelegramClient]) -> None:
        session_id = self.default_session_id
        if value is None:
            self._clients.pop(session_id, None)
            self._auth_clients.pop(session_id, None)
            self._authorized_sessions.discard(session_id)
            return
        self._clients[session_id] = value

    @property
    def phone(self) -> Optional[str]:
        state = self._get_auth_state(self.default_session_id)
        return state.get("phone") or None

    @phone.setter
    def phone(self, value: Optional[str]) -> None:
        session_id = self.default_session_id
        state = self._get_auth_state(session_id)
        state["phone"] = value or ""

    @property
    def phone_code_hash(self) -> Optional[str]:
        state = self._get_auth_state(self.default_session_id)
        return state.get("phone_code_hash") or None

    @phone_code_hash.setter
    def phone_code_hash(self, value: Optional[str]) -> None:
        session_id = self.default_session_id
        state = self._get_auth_state(session_id)
        state["phone_code_hash"] = value or ""

    @property
    def _is_connected(self) -> bool:
        return self.default_session_id in self._authorized_sessions

    @_is_connected.setter
    def _is_connected(self, value: bool) -> None:
        if value:
            self._authorized_sessions.add(self.default_session_id)
        else:
            self._authorized_sessions.discard(self.default_session_id)
    
    async def send_code(
        self,
        session_id: str,
        phone: Optional[str] = None,
        force_sms: bool = False,
    ) -> Dict[str, Any]:
        # Примечание: параметр force_sms игнорируется, так как Telegram больше не поддерживает эту функцию
        """
        Отправляет код подтверждения на телефон.
        
        Args:
            phone: Номер телефона в международном формате (например, +79991234567)
            force_sms: Если True, принудительно запросить код по SMS вместо Telegram приложения
        
        Returns:
            Словарь с phone_code_hash для дальнейшей авторизации
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if phone is None:
            # Backward compatibility: send_code(phone, force_sms=...)
            phone = session_id
            session_id = self.default_session_id
        session_id = self._normalize_session_id(session_id)
        phone = phone.strip()

        try:
            logger.info(f"Отправка кода на номер: {phone}")
            client = self._auth_clients.get(session_id)
            if client:
                await client.disconnect()

            client = await self._ensure_auth_client(session_id)
            self._clients.pop(session_id, None)
            state = self._get_auth_state(session_id)
            state["phone"] = phone
            
            # Примечание: force_sms больше не работает в Telegram API
            # Telegram сам решает, как отправить код (обычно через приложение)
            result = await client.send_code_request(phone)
            state["phone_code_hash"] = result.phone_code_hash
            self._get_session_repo().save_auth_state(
                session_id=session_id,
                phone=phone,
                phone_code_hash=result.phone_code_hash,
            )
            
            logger.info(f"Код успешно отправлен. Тип отправки: {result.type}")
            
            # Определяем тип отправки для сообщения
            code_type_str = str(result.type)
            if "sms" in code_type_str.lower() or "Sms" in code_type_str:
                code_type = "SMS"
                message = "Код отправлен по SMS на ваш номер телефона"
            elif "app" in code_type_str.lower():
                code_type = "Telegram приложение"
                message = "Код отправлен в Telegram приложение. Проверьте все устройства, где открыт Telegram (телефон, компьютер, веб-версия)"
            else:
                code_type = "Telegram"
                message = f"Код отправлен ({code_type_str})"
            
            return {
                "success": True,
                "phone_code_hash": result.phone_code_hash,
                "message": message
            }
        except PhoneNumberInvalidError:
            logger.error(f"Неверный номер телефона: {phone}")
            raise ValueError("Неверный номер телефона")
        except FloodWaitError as e:
            logger.error(f"Слишком много запросов. Ожидание: {e.seconds} секунд")
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            logger.error(f"Ошибка Telegram API: {e.message}")
            # Если ошибка AUTH_KEY, значит код уже был запрошен
            if "AUTH_KEY" in str(e.message):
                raise ValueError("Код уже был отправлен. Проверьте Telegram приложение для получения кода. Не запрашивайте код повторно.")
            raise ValueError(f"Ошибка Telegram API: {e.message}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке кода: {e}", exc_info=True)
            raise ValueError(f"Ошибка при отправке кода: {str(e)}")
    
    async def sign_in(
        self,
        session_id: str,
        phone: Optional[str] = None,
        code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Вход с кодом подтверждения.
        
        Args:
            phone: Номер телефона
            code: Код подтверждения из Telegram
        
        Returns:
            Статус авторизации
        """
        if code is None and phone is not None:
            # Backward compatibility: sign_in(phone, code)
            code = phone
            phone = session_id
            session_id = self.default_session_id
        session_id = self._normalize_session_id(session_id)
        if not phone or not code:
            raise ValueError("Нужно передать phone и code")

        state = self._get_auth_state(session_id)
        if not state.get("phone_code_hash"):
            raise ValueError("Сначала вызовите /sessions/{session_id}/auth/login")
        
        try:
            client = await self._ensure_auth_client(session_id)
            await asyncio.wait_for(
                client.sign_in(phone, code, phone_code_hash=state["phone_code_hash"]),
                timeout=AUTH_REQUEST_TIMEOUT_SECONDS,
            )
            self._clients[session_id] = client
            self._auth_clients.pop(session_id, None)
            self._authorized_sessions.add(session_id)
            state["phone_code_hash"] = ""
            await asyncio.to_thread(
                self._get_session_repo().save_authorized,
                session_id,
                client.session.save(),
            )
            
            return {
                "success": True,
                "message": "Авторизация успешна"
            }
        except asyncio.TimeoutError:
            raise ValueError(
                "Таймаут подтверждения кода. Проверьте интернет/прокси и повторите попытку."
            )
        except SessionPasswordNeededError:
            return {
                "success": False,
                "password_required": True,
                "message": "Требуется пароль двухфакторной аутентификации"
            }
        except PhoneCodeInvalidError:
            raise ValueError("Неверный код подтверждения")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")
    
    async def sign_in_password(
        self,
        session_id: str,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Вход с паролем двухфакторной аутентификации.
        
        Args:
            password: Пароль 2FA
        
        Returns:
            Статус авторизации
        """
        try:
            if password is None:
                # Backward compatibility: sign_in_password(password)
                password = session_id
                session_id = self.default_session_id
            session_id = self._normalize_session_id(session_id)
            if not password:
                raise ValueError("Пароль не может быть пустым")
            client = await self._ensure_auth_client(session_id)
            await client.sign_in(password=password)
            self._clients[session_id] = client
            self._auth_clients.pop(session_id, None)
            self._authorized_sessions.add(session_id)
            self._get_session_repo().save_authorized(session_id, client.session.save())
            
            return {
                "success": True,
                "message": "Авторизация успешна"
            }
        except RPCError as e:
            raise ValueError(f"Неверный пароль или ошибка: {e.message}")
    
    async def get_dialogs(self, session_id: str = "default", limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получает список всех диалогов (чатов).
        
        Args:
            limit: Максимальное количество диалогов
        
        Returns:
            Список словарей с информацией о чатах
        """
        session_id = self._normalize_session_id(session_id)
        client = await self.get_client(session_id)
        
        dialogs = []
        async for dialog in client.iter_dialogs(limit=limit):
            chat_info = {
                "id": dialog.id,
                "name": dialog.name,
                "type": None,
                "username": None,
                "unread_count": dialog.unread_count,
                "is_pinned": dialog.pinned,
                "is_verified": False,
                "is_scam": False,
                "is_fake": False
            }
            
            entity = dialog.entity
            
            if isinstance(entity, User):
                chat_info["type"] = "user"
                chat_info["username"] = entity.username
                chat_info["is_verified"] = entity.verified
                chat_info["is_scam"] = entity.scam
                chat_info["is_fake"] = entity.fake
            elif isinstance(entity, Chat):
                chat_info["type"] = "group"
            elif isinstance(entity, Channel):
                chat_info["type"] = "channel" if entity.broadcast else "supergroup"
                chat_info["username"] = entity.username
                chat_info["is_verified"] = entity.verified
                chat_info["is_scam"] = entity.scam
                chat_info["is_fake"] = entity.fake
            
            dialogs.append(chat_info)
        
        return dialogs

    async def get_chat_participants(
        self,
        chat_identifier: str,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Получает участников группы/супергруппы/канала.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            limit: Максимальное количество участников
            search: Поисковая строка по участникам (опционально)

        Returns:
            Словарь с информацией о чате и списком участников
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            if isinstance(entity, User):
                raise ValueError("Указанный идентификатор относится к личному чату, а не к группе/каналу")

            chat_id = getattr(entity, "id", 0)
            chat_name = getattr(entity, "title", None) or "Chat"
            search_value = (search or "").strip()

            users: List[User] = []

            # Для каналов/супергрупп используем общий механизм участников
            if isinstance(entity, Channel):
                users = await self.client.get_participants(
                    entity,
                    limit=limit,
                    search=search_value,
                )
            # Для базовых групп (Chat) берем участников через full chat
            elif isinstance(entity, Chat):
                full = await self.client(functions.messages.GetFullChatRequest(chat_id=entity.id))
                users_by_id = {u.id: u for u in (full.users or []) if isinstance(u, User)}
                participants = getattr(getattr(full.full_chat, "participants", None), "participants", []) or []
                for participant in participants:
                    user = users_by_id.get(getattr(participant, "user_id", 0))
                    if user is None:
                        continue
                    if search_value:
                        searchable = " ".join(
                            x for x in [user.username, user.first_name, user.last_name] if x
                        ).lower()
                        if search_value.lower() not in searchable:
                            continue
                    users.append(user)
                users = users[:limit]

            result_participants: List[Dict[str, Any]] = []
            for user in users:
                result_participants.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "is_bot": bool(getattr(user, "bot", False)),
                        "is_verified": bool(getattr(user, "verified", False)),
                        "is_scam": bool(getattr(user, "scam", False)),
                        "is_fake": bool(getattr(user, "fake", False)),
                        "is_premium": bool(getattr(user, "premium", False)),
                    }
                )

            return {
                "success": True,
                "chat_id": chat_id,
                "chat_name": chat_name,
                "participants": result_participants,
                "total": len(result_participants),
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден или недоступен: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_chat_admins(
        self,
        chat_identifier: str,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Получает список администраторов группы/супергруппы/канала.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            limit: Максимальное количество администраторов
            search: Поисковая строка по администраторам (опционально)

        Returns:
            Словарь с информацией о чате и списком администраторов
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            if isinstance(entity, User):
                raise ValueError("Указанный идентификатор относится к личному чату, а не к группе/каналу")

            chat_id = getattr(entity, "id", 0)
            chat_name = getattr(entity, "title", None) or "Chat"
            search_value = (search or "").strip().lower()
            users: List[User] = []

            if isinstance(entity, Channel):
                users = await self.client.get_participants(
                    entity,
                    filter=types.ChannelParticipantsAdmins(),
                    limit=limit,
                    search=search_value,
                )
            elif isinstance(entity, Chat):
                full = await self.client(functions.messages.GetFullChatRequest(chat_id=entity.id))
                users_by_id = {u.id: u for u in (full.users or []) if isinstance(u, User)}
                participants = getattr(getattr(full.full_chat, "participants", None), "participants", []) or []
                for participant in participants:
                    is_admin = isinstance(
                        participant,
                        (types.ChatParticipantAdmin, types.ChatParticipantCreator),
                    )
                    if not is_admin:
                        continue
                    user = users_by_id.get(getattr(participant, "user_id", 0))
                    if user is None:
                        continue
                    if search_value:
                        searchable = " ".join(
                            x for x in [user.username, user.first_name, user.last_name] if x
                        ).lower()
                        if search_value not in searchable:
                            continue
                    users.append(user)
                users = users[:limit]

            result_admins: List[Dict[str, Any]] = []
            for user in users:
                result_admins.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "is_bot": bool(getattr(user, "bot", False)),
                        "is_verified": bool(getattr(user, "verified", False)),
                        "is_scam": bool(getattr(user, "scam", False)),
                        "is_fake": bool(getattr(user, "fake", False)),
                        "is_premium": bool(getattr(user, "premium", False)),
                    }
                )

            return {
                "success": True,
                "chat_id": chat_id,
                "chat_name": chat_name,
                "admins": result_admins,
                "total": len(result_admins),
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден или недоступен: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_chat_info(self, chat_identifier: str) -> Dict[str, Any]:
        """
        Получает расширенную информацию о чате/группе/канале.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата

        Returns:
            Словарь с деталями чата
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)

            chat_type = "unknown"
            name = "Chat"
            username: Optional[str] = None
            description: Optional[str] = None
            participants_count: Optional[int] = None
            has_photo = bool(getattr(entity, "photo", None))
            is_verified = bool(getattr(entity, "verified", False))
            is_scam = bool(getattr(entity, "scam", False))
            is_fake = bool(getattr(entity, "fake", False))
            is_megagroup: Optional[bool] = None
            is_broadcast: Optional[bool] = None

            if isinstance(entity, User):
                chat_type = "user"
                name = " ".join(x for x in [entity.first_name, entity.last_name] if x).strip() or "User"
                username = entity.username
                description = None
            elif isinstance(entity, Channel):
                chat_type = "channel" if entity.broadcast else "supergroup"
                name = getattr(entity, "title", None) or "Channel"
                username = entity.username
                is_megagroup = bool(getattr(entity, "megagroup", False))
                is_broadcast = bool(getattr(entity, "broadcast", False))

                full = await self.client(functions.channels.GetFullChannelRequest(channel=entity))
                full_chat = getattr(full, "full_chat", None)
                if full_chat is not None:
                    description = getattr(full_chat, "about", None)
                    participants_count = getattr(full_chat, "participants_count", None)
            elif isinstance(entity, Chat):
                chat_type = "group"
                name = getattr(entity, "title", None) or "Group"
                full = await self.client(functions.messages.GetFullChatRequest(chat_id=entity.id))
                full_chat = getattr(full, "full_chat", None)
                if full_chat is not None:
                    description = getattr(full_chat, "about", None)
                    participants_count = getattr(full_chat, "participants_count", None)

            return {
                "id": getattr(entity, "id", 0),
                "type": chat_type,
                "name": name,
                "username": username,
                "description": description,
                "participants_count": participants_count,
                "has_photo": has_photo,
                "is_verified": is_verified,
                "is_scam": is_scam,
                "is_fake": is_fake,
                "is_megagroup": is_megagroup,
                "is_broadcast": is_broadcast,
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_chat_info(
        self,
        chat_identifier: str,
        title: Optional[str] = None,
        about: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Изменяет название и/или описание чата.

        Args:
            chat_identifier: Username/ID чата
            title: Новое название
            about: Новое описание

        Returns:
            Результат изменения
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        if title is None and about is None:
            raise ValueError("Нужно передать хотя бы одно поле: title или about")

        try:
            entity = await self.client.get_entity(chat_identifier)

            if isinstance(entity, Chat):
                if title is not None:
                    await self.client(
                        functions.messages.EditChatTitleRequest(
                            chat_id=entity.id,
                            title=title,
                        )
                    )
                if about is not None:
                    raise ValueError("Описание (about) нельзя изменить для обычной группы, только для супергруппы/канала")
            elif isinstance(entity, Channel):
                if title is not None:
                    await self.client(
                        functions.channels.EditTitleRequest(
                            channel=entity,
                            title=title,
                        )
                    )
                if about is not None:
                    await self.client(
                        functions.channels.EditAboutRequest(
                            channel=entity,
                            about=about,
                        )
                    )
            else:
                raise ValueError("Указанный chat_identifier не является группой/каналом")

            chat_info = await self.get_chat_info(chat_identifier)
            return {
                "success": True,
                "chat_id": chat_info.get("id"),
                "title": chat_info.get("name"),
                "about": chat_info.get("description"),
                "message": "Параметры чата обновлены",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка изменения чата: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_chat_photo(self, chat_identifier: str, photo_base64: str) -> Dict[str, Any]:
        """
        Устанавливает фото чата (группа/супергруппа/канал).

        Args:
            chat_identifier: Username/ID чата
            photo_base64: Фото в base64

        Returns:
            Результат установки фото
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)

            b64_value = photo_base64.strip()
            if b64_value.startswith("data:") and "," in b64_value:
                b64_value = b64_value.split(",", 1)[1]

            photo_bytes = base64.b64decode(b64_value, validate=True)
            if not photo_bytes:
                raise ValueError("Пустые данные фото")

            uploaded = await self.client.upload_file(photo_bytes, file_name="chat_photo.jpg")
            input_photo = types.InputChatUploadedPhoto(file=uploaded)

            if isinstance(entity, Chat):
                await self.client(
                    functions.messages.EditChatPhotoRequest(
                        chat_id=entity.id,
                        photo=input_photo,
                    )
                )
            elif isinstance(entity, Channel):
                await self.client(
                    functions.channels.EditPhotoRequest(
                        channel=entity,
                        photo=input_photo,
                    )
                )
            else:
                raise ValueError("Указанный chat_identifier не является группой/каналом")

            return {
                "success": True,
                "chat_id": getattr(entity, "id", None),
                "message": "Фото чата обновлено",
            }
        except binascii.Error:
            raise ValueError("Некорректный формат base64 для photo_base64")
        except ValueError as e:
            raise ValueError(f"Ошибка обновления фото чата: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def create_chat(
        self,
        type: str,
        title: str,
        about: Optional[str] = None,
        user_identifiers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Создает группу или канал.

        Args:
            type: group или channel
            title: Название
            about: Описание (для channel)
            user_identifiers: Участники для группы

        Returns:
            Результат создания
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        type_value = type.strip().lower()
        if type_value not in {"group", "channel"}:
            raise ValueError("type должен быть 'group' или 'channel'")

        try:
            if type_value == "group":
                users_input = user_identifiers or []
                if not users_input:
                    raise ValueError("Для создания группы нужно передать хотя бы одного пользователя в user_identifiers")

                entities = []
                for user_identifier in users_input:
                    entities.append(await self.client.get_input_entity(user_identifier))

                updates = await self.client(
                    functions.messages.CreateChatRequest(
                        users=entities,
                        title=title,
                    )
                )
            else:
                updates = await self.client(
                    functions.channels.CreateChannelRequest(
                        title=title,
                        about=about or "",
                        megagroup=False,
                    )
                )

            chat_id: Optional[int] = None
            chat_title = title
            chat_username: Optional[str] = None

            for item in getattr(updates, "chats", []) or []:
                chat_id = getattr(item, "id", chat_id)
                chat_title = getattr(item, "title", chat_title) or chat_title
                chat_username = getattr(item, "username", chat_username)
                if chat_id is not None:
                    break

            return {
                "success": True,
                "chat_id": chat_id,
                "type": type_value,
                "title": chat_title,
                "username": chat_username,
                "message": "Группа создана" if type_value == "group" else "Канал создан",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка создания чата: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def invite_users(
        self,
        chat_identifier: str,
        user_identifiers: List[str],
        fwd_limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Приглашает пользователей в группу/супергруппу/канал.

        Args:
            chat_identifier: Username/ID чата
            user_identifiers: Список пользователей для приглашения
            fwd_limit: Лимит истории для обычной группы

        Returns:
            Результат приглашения
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            chat_entity = await self.client.get_entity(chat_identifier)
            user_entities = [await self.client.get_input_entity(uid) for uid in user_identifiers]

            if isinstance(chat_entity, Chat):
                # Для обычных групп добавляем по одному пользователю.
                for user in user_entities:
                    await self.client(
                        functions.messages.AddChatUserRequest(
                            chat_id=chat_entity.id,
                            user_id=user,
                            fwd_limit=fwd_limit,
                        )
                    )
            elif isinstance(chat_entity, Channel):
                # Для супергрупп и каналов.
                await self.client(
                    functions.channels.InviteToChannelRequest(
                        channel=chat_entity,
                        users=user_entities,
                    )
                )
            else:
                raise ValueError("Указанный chat_identifier не является группой/каналом")

            return {
                "success": True,
                "chat_id": getattr(chat_entity, "id", None),
                "invited_count": len(user_entities),
                "message": "Пользователи приглашены",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка приглашения: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def remove_users(
        self,
        chat_identifier: str,
        user_identifiers: List[str],
    ) -> Dict[str, Any]:
        """
        Исключает пользователей из группы/супергруппы.

        Args:
            chat_identifier: Username/ID группы
            user_identifiers: Пользователи для исключения

        Returns:
            Результат исключения
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            chat_entity = await self.client.get_entity(chat_identifier)
            if isinstance(chat_entity, User):
                raise ValueError("chat_identifier должен указывать на группу или супергруппу")
            if isinstance(chat_entity, Channel) and bool(getattr(chat_entity, "broadcast", False)):
                raise ValueError("Нельзя исключать пользователей из обычного канала (broadcast)")

            user_entities = [await self.client.get_entity(uid) for uid in user_identifiers]
            removed_count = 0
            for user in user_entities:
                await self.client.kick_participant(chat_entity, user)
                removed_count += 1

            return {
                "success": True,
                "chat_id": getattr(chat_entity, "id", None),
                "removed_count": removed_count,
                "message": "Пользователи исключены",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка исключения: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_participant_permissions(
        self,
        chat_identifier: str,
        user_identifier: str,
        mute: bool,
        until_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Изменяет права участника в супергруппе (mute/unmute).

        Args:
            chat_identifier: Username/ID супергруппы
            user_identifier: Username/ID пользователя
            mute: True - ограничить отправку сообщений, False - снять ограничения
            until_date: Дата окончания ограничения в ISO-формате (опционально)

        Returns:
            Результат изменения прав
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            chat_entity = await self.client.get_entity(chat_identifier)
            if not isinstance(chat_entity, Channel) or not bool(getattr(chat_entity, "megagroup", False)):
                raise ValueError("Изменение прав поддерживается только для супергрупп")

            user_entity = await self.client.get_entity(user_identifier)
            until_dt: Optional[datetime] = None
            if until_date:
                raw_value = until_date.replace("Z", "+00:00")
                try:
                    until_dt = datetime.fromisoformat(raw_value)
                except ValueError:
                    raise ValueError("until_date должен быть в ISO-формате")

            banned_rights = types.ChatBannedRights(
                until_date=until_dt,
                send_messages=mute,
                send_media=mute,
                send_stickers=mute,
                send_gifs=mute,
                send_games=mute,
                send_inline=mute,
                embed_links=mute,
                send_polls=mute,
                change_info=mute,
                invite_users=mute,
                pin_messages=mute,
            )

            await self.client(
                functions.channels.EditBannedRequest(
                    channel=chat_entity,
                    participant=user_entity,
                    banned_rights=banned_rights,
                )
            )

            return {
                "success": True,
                "chat_id": getattr(chat_entity, "id", None),
                "user_id": getattr(user_entity, "id", None),
                "muted": mute,
                "until_date": until_dt.isoformat() if until_dt else None,
                "message": "Права участника обновлены",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка изменения прав участника: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_message(
        self,
        session_id: str = "default",
        chat_identifier: Optional[str] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отправляет сообщение в чат.
        
        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message: Текст сообщения
        
        Returns:
            Информация об отправленном сообщении
        """
        if message is None and chat_identifier is not None:
            # Backward compatibility: send_message(chat_identifier, message)
            message = chat_identifier
            chat_identifier = session_id
            session_id = self.default_session_id
        if not chat_identifier or message is None:
            raise ValueError("Нужно передать chat_identifier и message")
        session_id = self._normalize_session_id(session_id)
        client = await self.get_client(session_id)
        
        try:
            sent_message = await client.send_message(chat_identifier, message)
            
            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": sent_message.peer_id.channel_id if hasattr(sent_message.peer_id, 'channel_id') else sent_message.peer_id.user_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Сообщение отправлено"
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много сообщений. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_media(
        self,
        chat_identifier: str,
        file_base64: str,
        file_name: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отправляет медиафайл в чат (фото/видео/аудио/документ).

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            file_base64: Файл в base64 (можно data URL)
            file_name: Имя файла с расширением
            caption: Подпись к медиа

        Returns:
            Информация об отправленном сообщении
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            b64_value = file_base64.strip()
            if b64_value.startswith("data:") and "," in b64_value:
                b64_value = b64_value.split(",", 1)[1]

            file_bytes = base64.b64decode(b64_value, validate=True)
            if not file_bytes:
                raise ValueError("Пустые данные файла")

            uploaded = await self.client.upload_file(file_bytes, file_name=file_name.strip())
            sent_message = await self.client.send_file(
                chat_identifier,
                uploaded,
                caption=caption or None,
            )

            chat_id: Optional[int] = None
            peer = getattr(sent_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": chat_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Медиафайл отправлен",
            }
        except binascii.Error:
            raise ValueError("Некорректный формат base64 для file_base64")
        except ValueError as e:
            raise ValueError(f"Ошибка отправки медиа: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_voice(
        self,
        chat_identifier: str,
        voice_base64: str,
        file_name: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отправляет голосовое сообщение в чат.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            voice_base64: Голосовое сообщение в base64
            file_name: Имя файла (например, voice.ogg)
            caption: Подпись к голосовому (опционально)

        Returns:
            Информация об отправленном сообщении
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            b64_value = voice_base64.strip()
            if b64_value.startswith("data:") and "," in b64_value:
                b64_value = b64_value.split(",", 1)[1]

            file_bytes = base64.b64decode(b64_value, validate=True)
            if not file_bytes:
                raise ValueError("Пустые данные голосового сообщения")

            uploaded = await self.client.upload_file(file_bytes, file_name=file_name.strip())
            sent_message = await self.client.send_file(
                chat_identifier,
                uploaded,
                voice_note=True,
                caption=caption or None,
            )

            chat_id: Optional[int] = None
            peer = getattr(sent_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": chat_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Голосовое сообщение отправлено",
            }
        except binascii.Error:
            raise ValueError("Некорректный формат base64 для voice_base64")
        except ValueError as e:
            raise ValueError(f"Ошибка отправки голосового сообщения: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_sticker_gif(
        self,
        chat_identifier: str,
        media_kind: str,
        file_base64: str,
        file_name: str,
        emoji: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отправляет стикер или GIF в чат.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        kind = media_kind.strip().lower()
        if kind not in {"sticker", "gif"}:
            raise ValueError("media_kind должен быть 'sticker' или 'gif'")

        try:
            b64_value = file_base64.strip()
            if b64_value.startswith("data:") and "," in b64_value:
                b64_value = b64_value.split(",", 1)[1]

            file_bytes = base64.b64decode(b64_value, validate=True)
            if not file_bytes:
                raise ValueError("Пустые данные файла")

            uploaded = await self.client.upload_file(file_bytes, file_name=file_name.strip())

            send_kwargs: Dict[str, Any] = {
                "caption": caption or None,
                "force_document": False,
            }
            if kind == "sticker":
                send_kwargs["attributes"] = [
                    types.DocumentAttributeSticker(
                        alt=emoji or "",
                        stickerset=types.InputStickerSetEmpty(),
                        mask=False,
                    )
                ]
            elif kind == "gif":
                send_kwargs["supports_streaming"] = True

            sent_message = await self.client.send_file(chat_identifier, uploaded, **send_kwargs)

            chat_id: Optional[int] = None
            peer = getattr(sent_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": chat_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Стикер отправлен" if kind == "sticker" else "GIF отправлен",
            }
        except binascii.Error:
            raise ValueError("Некорректный формат base64 для file_base64")
        except ValueError as e:
            raise ValueError(f"Ошибка отправки медиа: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_location(
        self,
        chat_identifier: str,
        latitude: float,
        longitude: float,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отправляет геолокацию в чат.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            media = types.InputMediaGeoPoint(
                geo_point=types.InputGeoPoint(
                    lat=latitude,
                    long=longitude,
                    accuracy_radius=None,
                )
            )
            sent_message = await self.client.send_message(
                chat_identifier,
                message=caption or "",
                file=media,
            )

            chat_id: Optional[int] = None
            peer = getattr(sent_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": chat_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Геолокация отправлена",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка отправки геолокации: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_contact_message(
        self,
        chat_identifier: str,
        phone_number: str,
        first_name: str,
        last_name: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отправляет контакт в чат.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            media = types.InputMediaContact(
                phone_number=phone_number,
                first_name=first_name,
                last_name=last_name or "",
                vcard="",
            )
            sent_message = await self.client.send_message(
                chat_identifier,
                message=caption or "",
                file=media,
            )

            chat_id: Optional[int] = None
            peer = getattr(sent_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": chat_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Контакт отправлен",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка отправки контакта: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def edit_message(self, chat_identifier: str, message_id: int, message: str) -> Dict[str, Any]:
        """
        Редактирует ранее отправленное сообщение в чате.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message_id: ID сообщения для редактирования
            message: Новый текст сообщения

        Returns:
            Информация об отредактированном сообщении
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            edited_message = await self.client.edit_message(entity, message_id, message)

            chat_id: Optional[int] = None
            peer = getattr(edited_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": edited_message.id,
                "chat_id": chat_id,
                "date": edited_message.date.isoformat() if edited_message.date else None,
                "message": "Сообщение отредактировано"
            }
        except ValueError as e:
            raise ValueError(f"Чат или сообщение не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def delete_messages(
        self, chat_identifier: str, message_ids: List[int], revoke: bool = True
    ) -> Dict[str, Any]:
        """
        Удаляет одно или несколько сообщений в чате.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message_ids: Список ID сообщений для удаления
            revoke: True удаляет для всех (если доступно), False только у себя

        Returns:
            Результат удаления сообщений
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            await self.client.delete_messages(entity, message_ids, revoke=revoke)

            mode = "для всех" if revoke else "только у себя"
            return {
                "success": True,
                "deleted_count": len(message_ids),
                "message": f"Сообщения удалены ({mode})",
            }
        except ValueError as e:
            raise ValueError(f"Чат или сообщения не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def forward_messages(
        self,
        from_chat_identifier: str,
        to_chat_identifier: str,
        message_ids: List[int],
    ) -> Dict[str, Any]:
        """
        Пересылает сообщения из одного чата в другой.

        Args:
            from_chat_identifier: Источник сообщений (username или ID)
            to_chat_identifier: Чат назначения (username или ID)
            message_ids: Список ID сообщений для пересылки

        Returns:
            Результат пересылки сообщений
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            from_entity = await self.client.get_entity(from_chat_identifier)
            to_entity = await self.client.get_entity(to_chat_identifier)

            forwarded = await self.client.forward_messages(
                to_entity,
                message_ids,
                from_entity,
            )

            if not isinstance(forwarded, list):
                forwarded = [forwarded]

            forwarded_ids = [msg.id for msg in forwarded if msg is not None]

            return {
                "success": True,
                "forwarded_count": len(forwarded_ids),
                "message_ids": forwarded_ids,
                "message": "Сообщения пересланы",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка чатов или сообщений: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def reply_message(
        self, chat_identifier: str, reply_to_message_id: int, message: str
    ) -> Dict[str, Any]:
        """
        Отправляет ответ на конкретное сообщение в чате.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            reply_to_message_id: ID сообщения, на которое отвечаем
            message: Текст ответа

        Returns:
            Информация об отправленном reply-сообщении
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            sent_message = await self.client.send_message(
                chat_identifier,
                message,
                reply_to=reply_to_message_id,
            )

            chat_id: Optional[int] = None
            peer = getattr(sent_message, "peer_id", None)
            if peer is not None:
                if hasattr(peer, "channel_id"):
                    chat_id = peer.channel_id
                elif hasattr(peer, "chat_id"):
                    chat_id = peer.chat_id
                elif hasattr(peer, "user_id"):
                    chat_id = peer.user_id

            return {
                "success": True,
                "message_id": sent_message.id,
                "chat_id": chat_id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "reply_to_message_id": reply_to_message_id,
                "message": "Ответ отправлен",
            }
        except ValueError as e:
            raise ValueError(f"Чат или исходное сообщение не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")
    
    async def get_messages(self, chat_identifier: str, limit: int = 50) -> Dict[str, Any]:
        """
        Получает последние сообщения из указанного чата.
        
        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            limit: Максимальное количество сообщений
        
        Returns:
            Словарь с информацией о чате и списком сообщений
        """
        if not self.client:
            await self.get_client(self.default_session_id)
        
        if not self._is_connected:
            raise ValueError("Необходима авторизация")
        
        try:
            # Получаем сущность чата (User / Chat / Channel)
            entity = await self.client.get_entity(chat_identifier)
            chat_id, chat_name = self._extract_chat_meta(entity)

            # Получаем сообщения
            messages = await self.client.get_messages(entity, limit=limit)
            result_messages = [self._serialize_message_info(msg, chat_id) for msg in messages]
            
            return {
                "chat_id": chat_id if chat_id is not None else 0,
                "chat_name": chat_name,
                "messages": result_messages,
            }
        except ValueError as e:
            # Ошибки разрешения чата и подобное
            raise ValueError(f"Чат не найден или ошибка: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    @staticmethod
    def _extract_chat_meta(entity: Any) -> tuple[Optional[int], Optional[str]]:
        chat_id: Optional[int] = None
        chat_name: Optional[str] = None

        if isinstance(entity, User):
            chat_id = entity.id
            chat_name = (entity.first_name or "") or "User"
            if entity.last_name:
                chat_name = f"{chat_name} {entity.last_name}".strip()
        elif isinstance(entity, (Chat, Channel)):
            chat_id = entity.id
            chat_name = getattr(entity, "title", None) or "Chat"
        else:
            chat_id = getattr(entity, "id", None)

        return chat_id, chat_name

    @staticmethod
    def _serialize_message_info(message: Any, fallback_chat_id: Optional[int]) -> Dict[str, Any]:
        sender_id: Optional[int] = None
        if hasattr(message, "sender_id") and message.sender_id is not None:
            try:
                sender_id = int(message.sender_id)
            except (TypeError, ValueError):
                sender_id = None
        elif hasattr(message, "from_id") and message.from_id is not None:
            from_id = message.from_id
            if isinstance(from_id, types.PeerUser):
                sender_id = from_id.user_id
            elif isinstance(from_id, types.PeerChat):
                sender_id = from_id.chat_id
            elif isinstance(from_id, types.PeerChannel):
                sender_id = from_id.channel_id

        message_chat_id: Optional[int] = fallback_chat_id
        if hasattr(message, "peer_id") and message.peer_id is not None:
            peer = message.peer_id
            if hasattr(peer, "channel_id"):
                message_chat_id = peer.channel_id
            elif hasattr(peer, "chat_id"):
                message_chat_id = peer.chat_id
            elif hasattr(peer, "user_id"):
                message_chat_id = peer.user_id

        has_media = bool(getattr(message, "media", None))
        media_type: Optional[str] = None
        if has_media and message.media is not None:
            if isinstance(message.media, MessageMediaPhoto):
                media_type = "photo"
            elif isinstance(message.media, MessageMediaDocument):
                doc = message.media.document
                attrs = getattr(doc, "attributes", []) or []
                for attr in attrs:
                    if isinstance(attr, DocumentAttributeVideo):
                        media_type = "video"
                        break
                    if isinstance(attr, DocumentAttributeAudio):
                        media_type = "voice" if getattr(attr, "voice", False) else "audio"
                        break
                    if isinstance(attr, DocumentAttributeSticker):
                        media_type = "sticker"
                        break
                if media_type is None:
                    media_type = "document"
            else:
                media_type = "other"

        return {
            "id": message.id,
            "chat_id": message_chat_id if message_chat_id is not None else (fallback_chat_id or 0),
            "sender_id": sender_id,
            "text": message.message or "",
            "date": message.date.isoformat() if message.date else "",
            "is_out": bool(getattr(message, "out", False)),
            "has_media": has_media,
            "media_type": media_type,
            "media_id": message.id if has_media else None,
        }

    async def get_message_by_id_for_sessions(
        self,
        session_ids: List[str],
        chat_identifier: str,
        message_id: int,
    ) -> Dict[str, Any]:
        normalized_session_ids = self._normalize_string_list(session_ids)
        if not normalized_session_ids:
            raise ValueError("У кампании нет доступных account_sessions для загрузки поста")

        parsed_chat_identifier = self._parse_chat_identifier(chat_identifier)
        collected_errors: List[str] = []

        for session_id in normalized_session_ids:
            try:
                client = await self.get_client(session_id)
                entity = await client.get_entity(parsed_chat_identifier)
                chat_id, chat_name = self._extract_chat_meta(entity)
                message = await client.get_messages(entity, ids=int(message_id))
                if isinstance(message, list):
                    message = message[0] if message else None
                if message is None:
                    collected_errors.append(f"session '{session_id}': пост не найден")
                    continue

                return {
                    "session_id": session_id,
                    "channel_id": self._normalize_chat_identifier(chat_identifier),
                    "chat_name": chat_name,
                    "post": self._serialize_message_info(message, chat_id),
                }
            except Exception as e:
                logger.warning(
                    "Не удалось получить пост из истории нейрокомментариев: session_id=%s channel=%s message_id=%s error=%s",
                    session_id,
                    chat_identifier,
                    message_id,
                    e,
                )
                collected_errors.append(f"session '{session_id}': {e}")

        if collected_errors:
            raise ValueError("Не удалось загрузить пост. " + "; ".join(collected_errors))

        raise ValueError("Не удалось загрузить пост")

    async def search_messages(
        self, chat_identifier: str, query: str, limit: int = 50
    ) -> Dict[str, Any]:
        """
        Ищет сообщения в указанном чате по текстовому запросу.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            query: Поисковая строка
            limit: Максимальное количество найденных сообщений

        Returns:
            Словарь с информацией о чате и найденных сообщениях
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)

            chat_id: Optional[int] = None
            chat_name: Optional[str] = None
            if isinstance(entity, User):
                chat_id = entity.id
                chat_name = (entity.first_name or "") or "User"
                if entity.last_name:
                    chat_name = f"{chat_name} {entity.last_name}".strip()
            elif isinstance(entity, (Chat, Channel)):
                chat_id = entity.id
                chat_name = getattr(entity, "title", None) or "Chat"
            else:
                chat_id = getattr(entity, "id", None)

            messages = await self.client.get_messages(entity, search=query, limit=limit)

            result_messages: List[Dict[str, Any]] = []
            for msg in messages:
                sender_id: Optional[int] = None
                if hasattr(msg, "sender_id") and msg.sender_id is not None:
                    try:
                        sender_id = int(msg.sender_id)
                    except (TypeError, ValueError):
                        sender_id = None

                msg_chat_id: Optional[int] = chat_id
                if hasattr(msg, "peer_id") and msg.peer_id is not None:
                    peer = msg.peer_id
                    if hasattr(peer, "channel_id"):
                        msg_chat_id = peer.channel_id
                    elif hasattr(peer, "chat_id"):
                        msg_chat_id = peer.chat_id
                    elif hasattr(peer, "user_id"):
                        msg_chat_id = peer.user_id

                has_media = bool(getattr(msg, "media", None))
                media_type: Optional[str] = None
                if has_media and msg.media is not None:
                    if isinstance(msg.media, MessageMediaPhoto):
                        media_type = "photo"
                    elif isinstance(msg.media, MessageMediaDocument):
                        doc = msg.media.document
                        attrs = getattr(doc, "attributes", []) or []
                        for attr in attrs:
                            if isinstance(attr, DocumentAttributeVideo):
                                media_type = "video"
                                break
                            if isinstance(attr, DocumentAttributeAudio):
                                media_type = "voice" if getattr(attr, "voice", False) else "audio"
                                break
                            if isinstance(attr, DocumentAttributeSticker):
                                media_type = "sticker"
                                break
                        if media_type is None:
                            media_type = "document"
                    else:
                        media_type = "other"

                result_messages.append(
                    {
                        "id": msg.id,
                        "chat_id": msg_chat_id if msg_chat_id is not None else (chat_id or 0),
                        "sender_id": sender_id,
                        "text": msg.message or "",
                        "date": msg.date.isoformat() if msg.date else "",
                        "is_out": bool(getattr(msg, "out", False)),
                        "has_media": has_media,
                        "media_type": media_type,
                        "media_id": msg.id if has_media else None,
                    }
                )

            return {
                "chat_id": chat_id if chat_id is not None else 0,
                "chat_name": chat_name,
                "query": query,
                "messages": result_messages,
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден или ошибка поиска: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def filter_messages(
        self, chat_identifier: str, message_type: str, limit: int = 100
    ) -> Dict[str, Any]:
        """
        Фильтрует сообщения по типу в указанном чате.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message_type: Тип сообщений (text, media, photo, video, document, audio, voice, sticker, gif, service)
            limit: Максимальное количество сообщений для анализа

        Returns:
            Словарь с информацией о чате и отфильтрованными сообщениями
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            base_result = await self.get_messages(chat_identifier, limit=limit)
            messages = base_result["messages"]

            def is_match(msg: Dict[str, Any]) -> bool:
                has_media = bool(msg.get("has_media", False))
                media_type = (msg.get("media_type") or "").lower()
                text = (msg.get("text") or "").strip()

                if message_type == "text":
                    return (not has_media) and bool(text)
                if message_type == "media":
                    return has_media
                if message_type == "service":
                    return (not has_media) and (not text)
                if message_type == "gif":
                    return media_type == "gif"
                return media_type == message_type

            filtered_messages = [msg for msg in messages if is_match(msg)]

            return {
                "chat_id": base_result["chat_id"],
                "chat_name": base_result.get("chat_name"),
                "message_type": message_type,
                "messages": filtered_messages,
            }
        except ValueError as e:
            raise ValueError(f"Ошибка фильтрации сообщений: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def mark_messages_read(
        self, chat_identifier: str, max_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Отмечает сообщения в чате как прочитанные.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            max_id: Максимальный ID сообщения для read ack (опционально)

        Returns:
            Результат выполнения отметки как прочитанных
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            await self.client.send_read_acknowledge(entity, max_id=max_id)

            chat_id = getattr(entity, "id", None)
            return {
                "success": True,
                "chat_id": chat_id,
                "max_id": max_id,
                "message": "Сообщения отмечены как прочитанные",
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def pin_message(
        self,
        chat_identifier: str,
        message_id: int,
        unpin: bool = False,
        notify: bool = False,
    ) -> Dict[str, Any]:
        """
        Закрепляет или открепляет сообщение в чате.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message_id: ID сообщения
            unpin: True для открепления, False для закрепления
            notify: Отправлять уведомление участникам (для закрепления)

        Returns:
            Результат операции
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            await self.client.pin_message(
                entity,
                message_id,
                notify=notify,
                pm_oneside=False,
                unpin=unpin,
            )

            action = "unpin" if unpin else "pin"
            action_text = "Сообщение откреплено" if unpin else "Сообщение закреплено"
            return {
                "success": True,
                "chat_id": getattr(entity, "id", None),
                "message_id": message_id,
                "action": action,
                "message": action_text,
            }
        except ValueError as e:
            raise ValueError(f"Чат или сообщение не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def set_message_reaction(
        self,
        chat_identifier: str,
        message_id: int,
        reaction: Optional[str] = None,
        big: bool = False,
    ) -> Dict[str, Any]:
        """
        Устанавливает или снимает реакцию на сообщение.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message_id: ID сообщения
            reaction: Emoji реакции. None для снятия реакции.
            big: Большая анимация реакции, если поддерживается

        Returns:
            Результат установки/снятия реакции
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            await self.client.send_reaction(
                entity,
                message_id,
                reaction=reaction,
                big=big,
            )

            return {
                "success": True,
                "chat_id": getattr(entity, "id", None),
                "message_id": message_id,
                "reaction": reaction,
                "message": "Реакция снята" if reaction is None else "Реакция установлена",
            }
        except ValueError as e:
            raise ValueError(f"Чат или сообщение не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def download_media(self, chat_identifier: str, message_id: int) -> Dict[str, Any]:
        """
        Скачивает медиа по ID сообщения в чате.
        
        Args:
            chat_identifier: Username чата (@username) или ID чата
            message_id: ID сообщения (тот же, что возвращается как media_id)
        
        Returns:
            Словарь с байтами файла, именем и content-type
        """
        if not self.client:
            await self.get_client(self.default_session_id)
        
        if not self._is_connected:
            raise ValueError("Необходима авторизация")
        
        try:
            # Находим чат и сообщение
            entity = await self.client.get_entity(chat_identifier)
            msg = await self.client.get_messages(entity, ids=message_id)
            if not msg:
                raise ValueError("Сообщение не найдено")
            
            if not getattr(msg, "media", None):
                raise ValueError("У сообщения нет медиа")
            
            # Определяем content-type и имя файла
            content_type = "application/octet-stream"
            filename: str = f"media_{message_id}"
            
            if isinstance(msg.media, MessageMediaPhoto):
                content_type = "image/jpeg"
                filename += ".jpg"
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                if getattr(doc, "mime_type", None):
                    content_type = doc.mime_type
                # Пытаемся вытащить оригинальное имя файла
                for attr in getattr(doc, "attributes", []) or []:
                    if isinstance(attr, DocumentAttributeSticker):
                        # стикеры могут быть webp / tgs / webm
                        if content_type == "application/octet-stream":
                            content_type = "image/webp"
                        if not filename.endswith(".webp"):
                            filename = f"sticker_{message_id}.webp"
                    if hasattr(attr, "file_name"):
                        filename = attr.file_name
                        break
            
            # Скачиваем в память
            data: bytes = await self.client.download_media(msg, file=bytes)
            if not data:
                raise ValueError("Не удалось скачать медиа")
            
            return {
                "filename": filename,
                "content_type": content_type,
                "data": data,
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def archive_chat(self, chat_identifier: str, archive: bool = True) -> Dict[str, Any]:
        """
        Архивирует чат или возвращает его из архива.

        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            archive: True - архивировать, False - вернуть из архива

        Returns:
            Результат операции архивирования
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            folder_id = 1 if archive else 0
            await self.client.edit_folder(entity, folder=folder_id)

            return {
                "success": True,
                "chat_id": getattr(entity, "id", None),
                "archived": archive,
                "message": "Чат архивирован" if archive else "Чат возвращен из архива",
            }
        except ValueError as e:
            raise ValueError(f"Чат не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_user_info(self, user_identifier: str) -> Dict[str, Any]:
        """
        Получает информацию о пользователе Telegram.

        Args:
            user_identifier: Username пользователя (@username), phone или user ID

        Returns:
            Словарь с полями пользователя
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(user_identifier)
            if not isinstance(entity, User):
                raise ValueError("Указанный идентификатор не принадлежит пользователю")

            status = getattr(entity, "status", None)
            status_value: Optional[str] = None
            if status is not None:
                status_value = status.__class__.__name__.replace("UserStatus", "").lower()

            return {
                "id": entity.id,
                "username": entity.username,
                "first_name": entity.first_name,
                "last_name": entity.last_name,
                "phone": entity.phone,
                "is_bot": bool(getattr(entity, "bot", False)),
                "is_verified": bool(getattr(entity, "verified", False)),
                "is_scam": bool(getattr(entity, "scam", False)),
                "is_fake": bool(getattr(entity, "fake", False)),
                "is_premium": bool(getattr(entity, "premium", False)),
                "status": status_value,
            }
        except ValueError as e:
            raise ValueError(f"Пользователь не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_contacts(self, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Получает список контактов текущего аккаунта.

        Args:
            limit: Максимальное количество контактов

        Returns:
            Список словарей с информацией о контактах
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            users = await self.client.get_contacts()
            contacts: List[Dict[str, Any]] = []

            for user in users[:limit]:
                contacts.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "phone": user.phone,
                        "is_bot": bool(getattr(user, "bot", False)),
                        "is_verified": bool(getattr(user, "verified", False)),
                        "is_premium": bool(getattr(user, "premium", False)),
                    }
                )

            return contacts
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_user_status(self, user_identifier: str) -> Dict[str, Any]:
        """
        Получает статус пользователя (online/offline/recently и т.д.).

        Args:
            user_identifier: Username пользователя (@username), phone или user ID

        Returns:
            Словарь со статусом пользователя
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(user_identifier)
            if not isinstance(entity, User):
                raise ValueError("Указанный идентификатор не принадлежит пользователю")

            status_obj = getattr(entity, "status", None)
            status_value = "unknown"
            was_online: Optional[str] = None
            expires: Optional[str] = None

            if status_obj is not None:
                status_value = status_obj.__class__.__name__.replace("UserStatus", "").lower()
                was_online_dt = getattr(status_obj, "was_online", None)
                expires_dt = getattr(status_obj, "expires", None)
                if was_online_dt is not None:
                    was_online = was_online_dt.isoformat()
                if expires_dt is not None:
                    expires = expires_dt.isoformat()

            return {
                "user_id": entity.id,
                "status": status_value,
                "was_online": was_online,
                "expires": expires,
            }
        except ValueError as e:
            raise ValueError(f"Пользователь не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_me_info(self) -> Dict[str, Any]:
        """
        Получает информацию о текущем авторизованном аккаунте.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            me = await self.client.get_me()
            if not me:
                raise ValueError("Не удалось получить данные аккаунта")

            return {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "phone": me.phone,
                "is_bot": bool(getattr(me, "bot", False)),
                "is_verified": bool(getattr(me, "verified", False)),
                "is_premium": bool(getattr(me, "premium", False)),
            }
        except ValueError:
            raise
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_username(self, username: str) -> Dict[str, Any]:
        """
        Изменяет username текущего аккаунта.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            updated_user = await self.client(
                functions.account.UpdateUsernameRequest(username=username)
            )
            return {
                "success": True,
                "username": updated_user.username or username,
                "message": "Username обновлен",
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_name(self, first_name: str, last_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Изменяет имя и фамилию текущего аккаунта.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            updated_user = await self.client(
                functions.account.UpdateProfileRequest(
                    first_name=first_name,
                    last_name=last_name or "",
                )
            )
            return {
                "success": True,
                "first_name": updated_user.first_name or first_name,
                "last_name": updated_user.last_name,
                "message": "Имя и фамилия обновлены",
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_about(self, about: str) -> Dict[str, Any]:
        """
        Изменяет биографию (about) текущего аккаунта.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            updated_user = await self.client(
                functions.account.UpdateProfileRequest(about=about)
            )
            return {
                "success": True,
                "about": about,
                "message": "Биография обновлена",
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def update_profile_photo(self, photo_base64: str) -> Dict[str, Any]:
        """
        Изменяет фото профиля текущего аккаунта.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            b64_value = photo_base64.strip()
            if b64_value.startswith("data:") and "," in b64_value:
                b64_value = b64_value.split(",", 1)[1]

            photo_bytes = base64.b64decode(b64_value, validate=True)
            if not photo_bytes:
                raise ValueError("Пустые данные фото")

            uploaded = await self.client.upload_file(photo_bytes, file_name="profile.jpg")
            await self.client(functions.photos.UploadProfilePhotoRequest(file=uploaded))
            return {
                "success": True,
                "message": "Фото профиля обновлено",
            }
        except binascii.Error:
            raise ValueError("Некорректный формат base64 для photo_base64")
        except ValueError:
            raise
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def reset_other_sessions(self) -> Dict[str, Any]:
        """
        Отключает все остальные устройства (сессии), кроме текущей.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            await self.client(functions.auth.ResetAuthorizationsRequest())
            return {
                "success": True,
                "message": "Другие сессии отключены",
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def manage_contact(
        self,
        action: str,
        user_identifier: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Добавляет или удаляет контакт.

        Args:
            action: add/remove
            user_identifier: username/id/phone для работы с контактом
            phone: номер телефона для добавления по телефону
            first_name: имя контакта при добавлении
            last_name: фамилия контакта при добавлении

        Returns:
            Результат операции
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        action = action.lower()
        if action not in {"add", "remove"}:
            raise ValueError("action должен быть 'add' или 'remove'")

        try:
            if action == "add":
                if phone:
                    contact = types.InputPhoneContact(
                        client_id=int(time.time() * 1000),
                        phone=phone,
                        first_name=first_name or "Contact",
                        last_name=last_name or "",
                    )
                    await self.client(functions.contacts.ImportContactsRequest([contact]))
                elif user_identifier:
                    await self.client.add_contact(
                        user_identifier,
                        first_name=first_name or "Contact",
                        last_name=last_name or "",
                        phone=phone or "",
                    )
                else:
                    raise ValueError("Для add нужно передать phone или user_identifier")

                return {
                    "success": True,
                    "action": "add",
                    "message": "Контакт добавлен",
                }

            if not user_identifier:
                raise ValueError("Для remove нужно передать user_identifier")

            entity = await self.client.get_entity(user_identifier)
            await self.client.delete_contacts(entity)
            return {
                "success": True,
                "action": "remove",
                "message": "Контакт удален",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка операции с контактом: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def manage_block(self, action: str, user_identifier: str) -> Dict[str, Any]:
        """
        Блокирует или разблокирует пользователя.

        Args:
            action: block/unblock
            user_identifier: username/id/phone пользователя

        Returns:
            Результат операции
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        action = action.lower()
        if action not in {"block", "unblock"}:
            raise ValueError("action должен быть 'block' или 'unblock'")

        try:
            entity = await self.client.get_input_entity(user_identifier)
            if action == "block":
                await self.client(functions.contacts.BlockRequest(id=entity))
            else:
                await self.client(functions.contacts.UnblockRequest(id=entity))

            user_id = getattr(entity, "user_id", None)
            return {
                "success": True,
                "action": action,
                "user_id": user_id,
                "message": "Пользователь заблокирован" if action == "block" else "Пользователь разблокирован",
            }
        except ValueError as e:
            raise ValueError(f"Пользователь не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def send_bot_command(self, bot_identifier: str, command: str) -> Dict[str, Any]:
        """
        Отправляет команду боту.

        Args:
            bot_identifier: Username/ID бота
            command: Команда (например, /start)

        Returns:
            Результат отправки команды
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            bot_entity = await self.client.get_entity(bot_identifier)
            if not isinstance(bot_entity, User) or not bool(getattr(bot_entity, "bot", False)):
                raise ValueError("Указанный идентификатор не принадлежит боту")

            sent_message = await self.client.send_message(bot_entity, command)
            return {
                "success": True,
                "bot_id": bot_entity.id,
                "message_id": sent_message.id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Команда отправлена боту",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка отправки команды боту: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def click_inline_button(
        self,
        chat_identifier: str,
        message_id: int,
        row: int,
        col: int,
    ) -> Dict[str, Any]:
        """
        Нажимает inline-кнопку в сообщении.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(chat_identifier)
            msg = await self.client.get_messages(entity, ids=message_id)
            if not msg:
                raise ValueError("Сообщение не найдено")

            buttons = getattr(msg, "buttons", None)
            if not buttons:
                raise ValueError("В сообщении нет inline-кнопок")
            if row >= len(buttons):
                raise ValueError("Некорректный индекс row")
            if col >= len(buttons[row]):
                raise ValueError("Некорректный индекс col")

            click_result = await msg.click(row, col)

            result_text: Optional[str] = None
            if click_result is not None:
                result_text = str(click_result)

            return {
                "success": True,
                "message_id": message_id,
                "row": row,
                "col": col,
                "result": result_text,
                "message": "Inline-кнопка нажата",
            }
        except ValueError as e:
            raise ValueError(f"Ошибка нажатия inline-кнопки: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def search_channels(
        self,
        keywords: List[str],
        limit_per_keyword: int = 20,
        language: Optional[str] = None,
        include_about: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Ищет Telegram-каналы по списку ключевых слов.
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        normalized_keywords = [item.strip() for item in keywords if item and item.strip()]
        if not normalized_keywords:
            raise ValueError("Нужно передать хотя бы одно ключевое слово")

        if limit_per_keyword < 1:
            raise ValueError("limit_per_keyword должен быть больше 0")

        result_map: Dict[str, Dict[str, Any]] = {}
        language_filter = (language or "").strip().lower()

        for keyword in normalized_keywords:
            try:
                response = await self.client(
                    functions.contacts.SearchRequest(
                        q=keyword,
                        limit=limit_per_keyword,
                    )
                )
            except FloodWaitError as e:
                raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
            except RPCError as e:
                raise ValueError(f"Ошибка Telegram API при поиске '{keyword}': {e.message}")

            chats = getattr(response, "chats", []) or []
            for entity in chats:
                if not isinstance(entity, Channel):
                    continue
                if not bool(getattr(entity, "broadcast", False)):
                    continue

                title_value = (getattr(entity, "title", None) or "").strip()
                username_value = getattr(entity, "username", None)
                about_value: Optional[str] = None
                participants_count: Optional[int] = None

                if include_about:
                    try:
                        full = await self.client(
                            functions.channels.GetFullChannelRequest(channel=entity)
                        )
                        full_chat = getattr(full, "full_chat", None)
                        if full_chat is not None:
                            about_value = getattr(full_chat, "about", None)
                            participants_count = getattr(full_chat, "participants_count", None)
                    except FloodWaitError as e:
                        raise ValueError(
                            f"Слишком много запросов. Попробуйте через {e.seconds} секунд"
                        )
                    except RPCError:
                        # Для некоторых каналов детали могут быть недоступны.
                        about_value = None
                        participants_count = None

                if language_filter:
                    haystack = " ".join(
                        x for x in [title_value, about_value or ""] if x
                    ).lower()
                    if haystack and language_filter not in haystack:
                        continue

                channel_id = str(getattr(entity, "id", ""))
                if not channel_id:
                    continue

                dedupe_key = (
                    f"username:{username_value.lower()}"
                    if username_value
                    else f"channel_id:{channel_id}"
                )
                if dedupe_key not in result_map:
                    result_map[dedupe_key] = {
                        "channel_id": channel_id,
                        "title": title_value or channel_id,
                        "username": username_value,
                        "link": f"https://t.me/{username_value}" if username_value else None,
                        "about": about_value,
                        "participants_count": participants_count,
                        "verified": getattr(entity, "verified", None),
                        "scam": getattr(entity, "scam", None),
                        "fake": getattr(entity, "fake", None),
                        "found_by": [keyword],
                    }
                    continue

                existing = result_map[dedupe_key]
                if keyword not in existing["found_by"]:
                    existing["found_by"].append(keyword)
                if not existing.get("about") and about_value:
                    existing["about"] = about_value
                if existing.get("participants_count") is None and participants_count is not None:
                    existing["participants_count"] = participants_count

        return list(result_map.values())

    async def subscribe_channel(self, channel_identifier: str) -> Dict[str, Any]:
        """
        Подписывает текущий аккаунт на канал.

        Args:
            channel_identifier: Username канала (@channel) или ID канала

        Returns:
            Результат подписки
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(channel_identifier)
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            await self.client(functions.channels.JoinChannelRequest(channel=entity))
            return {
                "success": True,
                "channel_id": entity.id,
                "message": "Подписка на канал выполнена",
            }
        except ValueError as e:
            raise ValueError(f"Канал не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def unsubscribe_channel(self, channel_identifier: str) -> Dict[str, Any]:
        """
        Отписывает текущий аккаунт от канала.

        Args:
            channel_identifier: Username канала (@channel) или ID канала

        Returns:
            Результат отписки
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(channel_identifier)
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            await self.client(functions.channels.LeaveChannelRequest(channel=entity))
            return {
                "success": True,
                "channel_id": entity.id,
                "message": "Отписка от канала выполнена",
            }
        except ValueError as e:
            raise ValueError(f"Канал не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def publish_channel_post(self, channel_identifier: str, message: str) -> Dict[str, Any]:
        """
        Публикует пост в канал.

        Args:
            channel_identifier: Username канала (@channel) или ID канала
            message: Текст поста

        Returns:
            Результат публикации поста
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(channel_identifier)
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            sent_message = await self.client.send_message(entity, message)
            return {
                "success": True,
                "channel_id": entity.id,
                "message_id": sent_message.id,
                "date": sent_message.date.isoformat() if sent_message.date else None,
                "message": "Пост опубликован",
            }
        except ValueError as e:
            raise ValueError(f"Канал не найден или публикация недоступна: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def edit_channel_post(
        self, channel_identifier: str, message_id: int, message: str
    ) -> Dict[str, Any]:
        """
        Редактирует пост в канале.

        Args:
            channel_identifier: Username канала (@channel) или ID канала
            message_id: ID поста
            message: Новый текст поста

        Returns:
            Результат редактирования поста
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(channel_identifier)
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            edited = await self.client.edit_message(entity, message_id, message)
            return {
                "success": True,
                "channel_id": entity.id,
                "message_id": edited.id,
                "date": edited.date.isoformat() if edited.date else None,
                "message": "Пост отредактирован",
            }
        except ValueError as e:
            raise ValueError(f"Канал или пост не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def delete_channel_posts(
        self, channel_identifier: str, message_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Удаляет посты в канале.

        Args:
            channel_identifier: Username канала (@channel) или ID канала
            message_ids: Список ID постов

        Returns:
            Результат удаления постов
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(channel_identifier)
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            await self.client.delete_messages(entity, message_ids)
            return {
                "success": True,
                "channel_id": entity.id,
                "deleted_count": len(message_ids),
                "message": "Посты удалены",
            }
        except ValueError as e:
            raise ValueError(f"Канал или посты не найдены: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")
    
    async def get_dialogs_by_folder(self, folder_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получает список чатов из указанной папки.
        
        Args:
            folder_name: Название папки (например, "Работа", "Личное")
            limit: Максимальное количество чатов
        
        Returns:
            Список словарей с информацией о чатах из папки
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.client:
            await self.get_client(self.default_session_id)
        
        if not self._is_connected:
            raise ValueError("Необходима авторизация")
        
        try:
            # Получаем список всех папок (dialog filters)
            logger.info(f"Получение списка папок для поиска '{folder_name}'...")
            filters_result = await self.client(functions.messages.GetDialogFiltersRequest())
            
            # Логируем структуру ответа для отладки
            logger.debug(f"Тип результата: {type(filters_result)}")
            logger.debug(f"Атрибуты результата: {dir(filters_result)}")
            
            # Ищем папку по названию и сохраняем сам объект фильтра
            folder_filter_obj = None  # Будем хранить сам объект DialogFilter
            available_folders = []
            
            # Проверяем разные варианты структуры ответа
            filters_list = None
            
            # Вариант 1: filters_result.filters
            if hasattr(filters_result, 'filters'):
                filters_list = filters_result.filters
                logger.debug(f"Найдено атрибут 'filters': {len(filters_list) if filters_list else 0} элементов")
            
            # Вариант 2: если результат - это список
            elif isinstance(filters_result, list):
                filters_list = filters_result
                logger.debug(f"Результат - это список: {len(filters_list)} элементов")
            
            # Вариант 3: если есть другие атрибуты
            else:
                # Пробуем найти список фильтров в других атрибутах
                for attr in dir(filters_result):
                    if not attr.startswith('_'):
                        try:
                            attr_value = getattr(filters_result, attr, None)
                            if isinstance(attr_value, list):
                                filters_list = attr_value
                                logger.debug(f"Найден список в атрибуте '{attr}': {len(filters_list)} элементов")
                                break
                        except:
                            pass
            
            if filters_list:
                logger.info(f"Найдено {len(filters_list)} папок/фильтров")
                for idx, dialog_filter in enumerate(filters_list):
                    logger.debug(f"Фильтр #{idx}: тип={type(dialog_filter).__name__}")
                    
                    # Пробуем получить название разными способами
                    filter_title = None
                    
                    # Вариант 1: атрибут title
                    if hasattr(dialog_filter, 'title'):
                        filter_title = dialog_filter.title
                        logger.debug(f"  Название (title): '{filter_title}'")
                    
                    # Вариант 2: может быть в других атрибутах
                    if not filter_title:
                        for attr in ['name', 'title', 'Title']:
                            if hasattr(dialog_filter, attr):
                                filter_title = getattr(dialog_filter, attr)
                                logger.debug(f"  Название ({attr}): '{filter_title}'")
                                break
                    
                    # Получаем ID папки
                    if hasattr(dialog_filter, 'id'):
                        filter_id = dialog_filter.id
                    elif hasattr(dialog_filter, 'Id'):
                        filter_id = getattr(dialog_filter, 'Id')
                    else:
                        filter_id = None
                    
                    if filter_title:
                        available_folders.append(filter_title)
                        logger.debug(f"  Доступная папка: '{filter_title}' (ID: {filter_id})")
                        
                        # Сравниваем названия (без учета регистра)
                        if filter_title.lower() == folder_name.lower():
                            folder_filter_obj = dialog_filter  # Сохраняем сам объект фильтра
                            logger.info(f"✓ Найдена папка '{filter_title}' с ID: {filter_id}")
                            break
            else:
                logger.warning("Не удалось найти список папок в ответе от API")
                logger.debug(f"Тип результата: {type(filters_result)}")
                logger.debug(f"Атрибуты: {[a for a in dir(filters_result) if not a.startswith('_')]}")
            
            if folder_filter_obj is None:
                available_folders_str = ", ".join(available_folders) if available_folders else "нет доступных папок"
                logger.warning(f"Папка '{folder_name}' не найдена. Доступные: {available_folders_str}")
                raise ValueError(
                    f"Папка '{folder_name}' не найдена. "
                    f"Доступные папки: {available_folders_str}"
                )
            
            # Получаем чаты из папки
            # Используем информацию из DialogFilter для фильтрации диалогов
            logger.info(f"Получение чатов из папки '{folder_name}'...")
            dialogs = []
            
            # Получаем список всех диалогов
            logger.info("Получение всех диалогов для фильтрации...")
            all_dialogs = []
            async for dialog in self.client.iter_dialogs(limit=1000):  # Получаем больше, чтобы найти все
                all_dialogs.append(dialog)
            
            logger.info(f"Получено {len(all_dialogs)} диалогов для фильтрации")
            
            # Получаем список include_peers из фильтра папки
            include_peers = []
            if hasattr(folder_filter_obj, 'include_peers'):
                include_peers = folder_filter_obj.include_peers
                logger.info(f"В папке '{folder_name}' указано {len(include_peers)} чатов в include_peers")
            
            # Если есть include_peers, фильтруем по ним
            if include_peers:
                # Создаем множество ID чатов из include_peers
                included_chat_ids = set()
                for peer in include_peers:
                    if isinstance(peer, types.InputPeerUser):
                        included_chat_ids.add(peer.user_id)
                    elif isinstance(peer, types.InputPeerChat):
                        included_chat_ids.add(peer.chat_id)
                    elif isinstance(peer, types.InputPeerChannel):
                        included_chat_ids.add(peer.channel_id)
                
                logger.info(f"Фильтруем диалоги по {len(included_chat_ids)} ID чатов")
                
                # Фильтруем диалоги
                filtered_dialogs = []
                for dialog in all_dialogs:
                    entity = dialog.entity
                    entity_id = None
                    
                    if isinstance(entity, User):
                        entity_id = entity.id
                    elif isinstance(entity, Chat):
                        entity_id = -entity.id  # Группы имеют отрицательный ID
                    elif isinstance(entity, Channel):
                        entity_id = entity.id
                    
                    # Проверяем, входит ли чат в папку
                    if entity_id in included_chat_ids:
                        filtered_dialogs.append(dialog)
                        if len(filtered_dialogs) >= limit:
                            break
                
                all_dialogs = filtered_dialogs
                logger.info(f"После фильтрации осталось {len(all_dialogs)} диалогов")
            else:
                logger.warning("В папке нет include_peers, возвращаем все диалоги")
                all_dialogs = all_dialogs[:limit]
            
            # Формируем результат
            for dialog in all_dialogs[:limit]:
                chat_info = {
                    "id": dialog.id,
                    "name": dialog.name,
                    "type": None,
                    "username": None,
                    "unread_count": dialog.unread_count,
                    "is_pinned": dialog.pinned,
                    "is_verified": False,
                    "is_scam": False,
                    "is_fake": False
                }
                
                entity = dialog.entity
                
                if isinstance(entity, User):
                    chat_info["type"] = "user"
                    chat_info["username"] = entity.username
                    chat_info["is_verified"] = entity.verified
                    chat_info["is_scam"] = entity.scam
                    chat_info["is_fake"] = entity.fake
                elif isinstance(entity, Chat):
                    chat_info["type"] = "group"
                elif isinstance(entity, Channel):
                    chat_info["type"] = "channel" if entity.broadcast else "supergroup"
                    chat_info["username"] = entity.username
                    chat_info["is_verified"] = entity.verified
                    chat_info["is_scam"] = entity.scam
                    chat_info["is_fake"] = entity.fake
                
                dialogs.append(chat_info)
            
            logger.info(f"Найдено {len(dialogs)} чатов в папке '{folder_name}'")
            return dialogs
            
        except ValueError:
            # Пробрасываем ValueError дальше (например, папка не найдена)
            raise
        except RPCError as e:
            logger.error(f"Ошибка Telegram API при получении чатов из папки: {e.message}")
            raise ValueError(f"Ошибка Telegram API: {e.message}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении чатов из папки: {e}", exc_info=True)
            raise ValueError(f"Ошибка при получении чатов из папки: {str(e)}")
    
    async def get_folders_list(self) -> List[Dict[str, Any]]:
        """
        Получает список всех доступных папок (dialog filters).
        
        Returns:
            Список словарей с информацией о папках
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.client:
            await self.get_client(self.default_session_id)
        
        if not self._is_connected:
            raise ValueError("Необходима авторизация")
        
        try:
            logger.info("Получение списка всех папок...")
            filters_result = await self.client(functions.messages.GetDialogFiltersRequest())
            
            folders = []
            filters_list = None
            
            # Проверяем разные варианты структуры ответа
            if hasattr(filters_result, 'filters'):
                filters_list = filters_result.filters
            elif isinstance(filters_result, list):
                filters_list = filters_result
            else:
                # Пробуем найти список фильтров в других атрибутах
                for attr in dir(filters_result):
                    if not attr.startswith('_'):
                        try:
                            attr_value = getattr(filters_result, attr, None)
                            if isinstance(attr_value, list):
                                filters_list = attr_value
                                break
                        except:
                            pass
            
            if filters_list:
                logger.info(f"Найдено {len(filters_list)} папок/фильтров")
                for dialog_filter in filters_list:
                    filter_title = None
                    filter_id = None
                    
                    # Получаем название
                    if hasattr(dialog_filter, 'title'):
                        filter_title = dialog_filter.title
                    else:
                        for attr in ['name', 'title', 'Title']:
                            if hasattr(dialog_filter, attr):
                                filter_title = getattr(dialog_filter, attr)
                                break
                    
                    # Если название пустое, используем ID как название
                    if not filter_title:
                        filter_title = f"Папка {dialog_filter.id if hasattr(dialog_filter, 'id') else 'Без названия'}"
                    
                    # Получаем ID
                    if hasattr(dialog_filter, 'id'):
                        filter_id = dialog_filter.id
                    
                    folders.append({
                        "name": filter_title,
                        "id": filter_id
                    })
            
            logger.info(f"Возвращаем {len(folders)} папок")
            return folders
            
        except RPCError as e:
            logger.error(f"Ошибка Telegram API при получении списка папок: {e.message}")
            raise ValueError(f"Ошибка Telegram API: {e.message}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении списка папок: {e}", exc_info=True)
            raise ValueError(f"Ошибка при получении списка папок: {str(e)}")
    
    async def disconnect(self):
        """Отключает клиент"""
        for job_id in list(self._reaction_job_listeners.keys()):
            await self.stop_reaction_job_listeners(job_id)
        for client in list(self._clients.values()):
            await client.disconnect()
        for client in list(self._auth_clients.values()):
            await client.disconnect()
        self._clients.clear()
        self._auth_clients.clear()
        self._authorized_sessions.clear()
        self._ai_comment_job_round_robin_indexes.clear()
        self._ai_comment_session_pause_until.clear()
    
    def is_connected(self, session_id: Optional[str] = None) -> bool:
        """Проверяет, авторизована ли сессия."""
        sid = self._normalize_session_id(session_id)
        if sid in self._authorized_sessions:
            return True

        row = self._get_session_repo().get(sid) or {}
        is_authorized = bool(row.get("is_authorized"))
        string_session = (row.get("string_session") or "").strip()
        if is_authorized and string_session:
            self._authorized_sessions.add(sid)
            return True

        return False

    def _normalize_chat_identifier(self, value: str) -> str:
        chat = (value or "").strip()
        if chat.startswith("https://t.me/"):
            chat = "@" + chat.removeprefix("https://t.me/").split("?")[0].strip("/")
        elif chat.startswith("http://t.me/"):
            chat = "@" + chat.removeprefix("http://t.me/").split("?")[0].strip("/")
        elif chat.startswith("t.me/"):
            chat = "@" + chat.removeprefix("t.me/").split("?")[0].strip("/")
        return chat

    def _parse_chat_identifier(self, value: str) -> Union[str, int]:
        normalized = self._normalize_chat_identifier(value)
        if re.fullmatch(r"-?\d+", normalized):
            return int(normalized)
        return normalized

    def _normalize_chat_identifier_for_reactions(self, value: str) -> str:
        return self._normalize_chat_identifier(value)

    def _parse_chat_identifier_for_reactions(self, value: str) -> Union[str, int]:
        return self._parse_chat_identifier(value)

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [text for item in value if (text := str(item or "").strip())]

    @staticmethod
    def _normalize_datetime_value(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return None
            if raw_value.endswith("Z"):
                raw_value = raw_value[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(raw_value)
            except ValueError:
                return None
        else:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _current_monotonic_time() -> float:
        return time.monotonic()

    @staticmethod
    def _error_name(error: BaseException) -> str:
        return type(error).__name__

    @classmethod
    def _extract_flood_wait_seconds(cls, error: BaseException) -> int:
        if cls._error_name(error) != "FloodWaitError":
            return 0

        raw_seconds = getattr(error, "seconds", 0)
        try:
            seconds = int(raw_seconds)
        except (TypeError, ValueError):
            return 0
        return max(0, seconds)

    @classmethod
    def _build_ai_comment_error_signature(cls, error: BaseException) -> str:
        parts: List[str] = [cls._error_name(error)]
        raw_message = getattr(error, "message", None)
        if isinstance(raw_message, str) and raw_message.strip():
            parts.append(raw_message.strip())

        rendered = str(error).strip()
        if rendered and rendered not in parts:
            parts.append(rendered)

        return " | ".join(parts).casefold()

    @classmethod
    def _classify_ai_comment_error(cls, error: BaseException) -> str:
        if cls._error_name(error) == "FloodWaitError":
            return "flood_wait"

        signature = cls._build_ai_comment_error_signature(error)
        if any(marker in signature for marker in AI_COMMENT_COMMENTS_DISABLED_MARKERS):
            return "comments_disabled"
        if any(marker in signature for marker in AI_COMMENT_ACCOUNT_NO_RIGHTS_MARKERS):
            return "account_no_rights"
        if any(marker in signature for marker in AI_COMMENT_CHANNEL_UNAVAILABLE_MARKERS):
            return "channel_unavailable"
        return "generic"

    def _get_ai_comment_session_pause_remaining(self, session_id: str) -> int:
        paused_until = self._ai_comment_session_pause_until.get(session_id)
        if paused_until is None:
            return 0

        remaining = int(paused_until - self._current_monotonic_time())
        if remaining <= 0:
            self._ai_comment_session_pause_until.pop(session_id, None)
            return 0
        return remaining

    def _pause_ai_comment_session(self, session_id: str, flood_wait_seconds: int) -> int:
        pause_seconds = max(1, int(flood_wait_seconds)) + AI_COMMENT_FLOOD_WAIT_PADDING_SECONDS
        current_pause_until = self._ai_comment_session_pause_until.get(session_id, 0.0)
        next_pause_until = self._current_monotonic_time() + pause_seconds
        self._ai_comment_session_pause_until[session_id] = max(current_pause_until, next_pause_until)
        return pause_seconds

    def _filter_available_ai_comment_sessions(
        self,
        session_ids: List[str],
        *,
        job_id: str,
        channel_id: str = "",
        message_id: Optional[int] = None,
    ) -> List[str]:
        available_sessions: List[str] = []
        for session_id in session_ids:
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue

            pause_remaining = self._get_ai_comment_session_pause_remaining(normalized_session_id)
            if pause_remaining > 0:
                logger.info(
                    "Пропуск session нейрокомментариев из-за активной паузы: job_id=%s session_id=%s channel=%s message_id=%s pause_remaining=%s",
                    job_id,
                    normalized_session_id,
                    channel_id,
                    message_id,
                    pause_remaining,
                )
                continue

            available_sessions.append(normalized_session_id)

        return available_sessions

    @classmethod
    def _format_ai_comment_publish_error(
        cls,
        *,
        error: BaseException,
        session_id: str,
        channel_id: str,
        message_id: int,
    ) -> str:
        error_kind = cls._classify_ai_comment_error(error)
        if error_kind == "flood_wait":
            wait_seconds = cls._extract_flood_wait_seconds(error)
            return (
                f"FloodWait для session '{session_id}' при публикации комментария "
                f"в канале '{channel_id}' к посту {message_id}: подождите {wait_seconds} сек."
            )
        if error_kind == "comments_disabled":
            return f"У поста {message_id} в канале '{channel_id}' отключены комментарии или нет linked discussion"
        if error_kind == "account_no_rights":
            return f"У session '{session_id}' нет прав на публикацию комментария в канале '{channel_id}'"
        if error_kind == "channel_unavailable":
            return f"Канал '{channel_id}' недоступен для session '{session_id}'"
        return f"Не удалось опубликовать комментарий от session '{session_id}': {error}"

    @staticmethod
    def _record_ai_comment_failure(
        repo: AiCommentJobsRepo,
        *,
        job_id: str,
        channel_id: str,
        message_id: int,
        error_message: str,
    ) -> None:
        try:
            repo.upsert_history_record(
                job_id=job_id,
                channel_id=channel_id,
                message_id=message_id,
                status="failed",
                error=error_message,
            )
        except Exception as repo_error:
            logger.error(
                "Не удалось записать failed-статус в ai_comment_job_posts: job_id=%s channel_id=%s message_id=%s error=%s",
                job_id,
                channel_id,
                message_id,
                repo_error,
            )

    @staticmethod
    def _extract_ai_comment_post_text(message: Any) -> str:
        for attr_name in ("raw_text", "message", "text"):
            value = getattr(message, attr_name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _normalize_ai_comment_text(text: str, limit: int = AI_COMMENT_TEXT_LIMIT) -> str:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\ufeff", "")
        normalized = re.sub(r"[\u200b\u200c\u200d]", "", normalized)
        normalized = normalized.strip()
        normalized = re.sub(r"^```(?:[\w+-]+)?\s*", "", normalized)
        normalized = re.sub(r"\s*```$", "", normalized)
        normalized = re.sub(
            r"^(?:комментарий|коммент|comment|reply|response|ответ)\s*[:\-]\s*",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
        normalized = "\n".join(line for line in normalized_lines if line).strip()
        normalized = normalized.strip("\"'`").strip()
        if len(normalized) <= limit:
            return normalized

        truncated = normalized[:limit].rstrip()
        if "\n" not in truncated:
            last_space_index = truncated.rfind(" ")
            if last_space_index >= max(0, limit - 80):
                truncated = truncated[:last_space_index].rstrip()
        return truncated.rstrip(" ,;:-")

    def _get_ai_comment_session_order(self, job_id: str, session_ids: List[str]) -> List[str]:
        normalized_session_ids = self._filter_available_ai_comment_sessions(
            session_ids,
            job_id=job_id,
        )
        if not job_id or not normalized_session_ids:
            return normalized_session_ids

        start_index = self._ai_comment_job_round_robin_indexes.get(job_id, 0) % len(normalized_session_ids)
        ordered_sessions = normalized_session_ids[start_index:] + normalized_session_ids[:start_index]
        self._ai_comment_job_round_robin_indexes[job_id] = (start_index + 1) % len(normalized_session_ids)
        return ordered_sessions

    def _clear_ai_comment_job_runtime_state(self, job_id: str) -> None:
        self._ai_comment_job_round_robin_indexes.pop(job_id, None)

    def _refresh_ai_comment_job(self, repo: AiCommentJobsRepo, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            return None

        try:
            return repo.get_by_id_for_worker(job_id)
        except Exception as e:
            logger.warning(
                "Не удалось перечитать состояние кампании нейрокомментариев, продолжаем с текущим снимком: job_id=%s error=%s",
                job_id,
                e,
            )
            return job

    async def _collect_ai_comment_job_fresh_posts(
        self,
        job: Dict[str, Any],
    ) -> Dict[str, Any]:
        job_id = str(job.get("id") or "").strip()
        if not job_id or not bool(job.get("is_active")):
            return {
                "fresh_posts": [],
                "successful_channels": 0,
                "failed_channels": [],
                "checkpoint_to_store": None,
                "initialize_checkpoint": False,
            }

        session_ids = self._normalize_string_list(job.get("account_sessions"))
        target_channels = [
            self._normalize_chat_identifier(channel)
            for channel in self._normalize_string_list(job.get("target_channels"))
        ]

        if not session_ids or not target_channels:
            logger.warning(
                "Пропуск мониторинга нейрокомментариев: job_id=%s нет account_sessions или target_channels",
                job_id,
            )
            return {
                "fresh_posts": [],
                "successful_channels": 0,
                "failed_channels": [],
                "checkpoint_to_store": None,
                "initialize_checkpoint": False,
            }

        stored_last_checked_at = self._normalize_datetime_value(job.get("last_checked_at"))
        initialize_checkpoint = stored_last_checked_at is None
        effective_last_checked_at = stored_last_checked_at or datetime.now(timezone.utc)
        newest_fresh_post_at: Optional[datetime] = stored_last_checked_at
        fresh_posts: List[Dict[str, Any]] = []
        successful_channels = 0
        failed_channels: List[str] = []

        for channel_identifier in target_channels:
            client, entity, session_id, parsed_channel_identifier = await self._resolve_ai_comment_channel(
                job_id=job_id,
                session_ids=session_ids,
                channel_identifier=channel_identifier,
            )
            if client is None or entity is None or session_id is None or parsed_channel_identifier is None:
                failed_channels.append(channel_identifier)
                continue

            try:
                messages = await client.get_messages(
                    entity,
                    limit=1 if initialize_checkpoint else AI_COMMENT_JOB_MESSAGES_LIMIT,
                )
                successful_channels += 1
            except FloodWaitError as e:
                pause_seconds = self._pause_ai_comment_session(
                    session_id,
                    self._extract_flood_wait_seconds(e),
                )
                logger.warning(
                    "FloodWait при чтении постов канала: job_id=%s session_id=%s channel=%s wait=%s pause=%s",
                    job_id,
                    session_id,
                    parsed_channel_identifier,
                    e.seconds,
                    pause_seconds,
                )
                failed_channels.append(channel_identifier)
                continue
            except (ValueError, RPCError) as e:
                error_kind = self._classify_ai_comment_error(e)
                logger.warning(
                    "Не удалось получить посты канала: job_id=%s session_id=%s channel=%s kind=%s error=%s",
                    job_id,
                    session_id,
                    parsed_channel_identifier,
                    error_kind,
                    e,
                )
                failed_channels.append(channel_identifier)
                continue
            except Exception as e:
                error_kind = self._classify_ai_comment_error(e)
                logger.warning(
                    "Неожиданная ошибка чтения постов канала: job_id=%s session_id=%s channel=%s kind=%s error=%s",
                    job_id,
                    session_id,
                    parsed_channel_identifier,
                    error_kind,
                    e,
                )
                failed_channels.append(channel_identifier)
                continue

            if initialize_checkpoint:
                continue

            channel_fresh_posts: List[Dict[str, Any]] = []
            for message in messages or []:
                message_id = getattr(message, "id", None)
                message_date = self._normalize_datetime_value(getattr(message, "date", None))
                if message_id is None or message_date is None or message_date <= effective_last_checked_at:
                    continue

                channel_fresh_posts.append(
                    {
                        "channel_id": str(parsed_channel_identifier),
                        "message_id": int(message_id),
                        "date": message_date.isoformat(),
                        "session_id": session_id,
                        "post_text": self._extract_ai_comment_post_text(message),
                    }
                )
                if newest_fresh_post_at is None or message_date > newest_fresh_post_at:
                    newest_fresh_post_at = message_date

            if channel_fresh_posts:
                channel_fresh_posts.sort(key=lambda item: item["message_id"])
                fresh_posts.extend(channel_fresh_posts)
                logger.info(
                    "Найдены новые посты для кампании нейрокомментариев: job_id=%s channel=%s count=%s",
                    job_id,
                    parsed_channel_identifier,
                    len(channel_fresh_posts),
                )

        checkpoint_to_store: Optional[datetime] = None
        if successful_channels > 0:
            if initialize_checkpoint:
                checkpoint_to_store = effective_last_checked_at
            elif newest_fresh_post_at is not None:
                checkpoint_to_store = newest_fresh_post_at

        return {
            "fresh_posts": fresh_posts,
            "successful_channels": successful_channels,
            "failed_channels": failed_channels,
            "checkpoint_to_store": checkpoint_to_store,
            "initialize_checkpoint": initialize_checkpoint,
        }

    async def _resolve_ai_comment_channel(
        self,
        *,
        job_id: str,
        session_ids: List[str],
        channel_identifier: str,
    ) -> tuple[Optional[TelegramClient], Any, Optional[str], Optional[Union[str, int]]]:
        parsed_channel_identifier = self._parse_chat_identifier(channel_identifier)
        if isinstance(parsed_channel_identifier, str) and not parsed_channel_identifier.strip():
            return None, None, None, None

        available_session_ids = self._filter_available_ai_comment_sessions(
            session_ids,
            job_id=job_id,
            channel_id=channel_identifier,
        )
        for session_id in available_session_ids:
            try:
                client = await self.get_client(session_id)
            except Exception as e:
                logger.warning(
                    "Пропуск session при мониторинге нейрокомментариев: job_id=%s session_id=%s error=%s",
                    job_id,
                    session_id,
                    e,
                )
                continue

            try:
                entity = await client.get_entity(parsed_channel_identifier)
                return client, entity, session_id, parsed_channel_identifier
            except FloodWaitError as e:
                pause_seconds = self._pause_ai_comment_session(
                    session_id,
                    self._extract_flood_wait_seconds(e),
                )
                logger.warning(
                    "FloodWait при получении entity канала: job_id=%s session_id=%s channel=%s wait=%s pause=%s",
                    job_id,
                    session_id,
                    parsed_channel_identifier,
                    e.seconds,
                    pause_seconds,
                )
            except (ValueError, RPCError) as e:
                error_kind = self._classify_ai_comment_error(e)
                logger.warning(
                    "Не удалось получить entity канала: job_id=%s session_id=%s channel=%s kind=%s error=%s",
                    job_id,
                    session_id,
                    parsed_channel_identifier,
                    error_kind,
                    e,
                )
            except Exception as e:
                error_kind = self._classify_ai_comment_error(e)
                logger.warning(
                    "Неожиданная ошибка получения entity канала: job_id=%s session_id=%s channel=%s kind=%s error=%s",
                    job_id,
                    session_id,
                    parsed_channel_identifier,
                    error_kind,
                    e,
                )

        return None, None, None, parsed_channel_identifier

    async def poll_ai_comment_job_channels(
        self,
        job: Dict[str, Any],
        *,
        ai_comment_jobs_repo: Optional[AiCommentJobsRepo] = None,
    ) -> List[Dict[str, Any]]:
        job_id = str(job.get("id") or "").strip()
        poll_result = await self._collect_ai_comment_job_fresh_posts(job)
        fresh_posts = [
            {
                "channel_id": post["channel_id"],
                "message_id": post["message_id"],
                "date": post["date"],
                "session_id": post["session_id"],
            }
            for post in poll_result["fresh_posts"]
        ]

        if poll_result["successful_channels"] == 0:
            return fresh_posts

        if poll_result["failed_channels"]:
            logger.warning(
                "Не обновляем last_checked_at из-за ошибок чтения каналов: job_id=%s failed_channels=%s",
                job_id,
                ",".join(poll_result["failed_channels"]),
            )
            return fresh_posts

        if ai_comment_jobs_repo is None:
            return fresh_posts

        checkpoint_to_store = poll_result["checkpoint_to_store"]
        if checkpoint_to_store is None:
            return fresh_posts

        ai_comment_jobs_repo.update_last_checked_at(
            job_id=job_id,
            last_checked_at=checkpoint_to_store.isoformat(),
        )
        job["last_checked_at"] = checkpoint_to_store.isoformat()

        if poll_result["initialize_checkpoint"]:
            logger.info(
                "Инициализирован checkpoint кампании нейрокомментариев: job_id=%s last_checked_at=%s",
                job_id,
                checkpoint_to_store.isoformat(),
            )

        return fresh_posts

    async def _publish_ai_comment(
        self,
        *,
        job_id: str,
        session_ids: List[str],
        channel_id: str,
        message_id: int,
        comment_text: str,
    ) -> Dict[str, Any]:
        ordered_session_ids = self._get_ai_comment_session_order(job_id, session_ids)
        parsed_channel_identifier = self._parse_chat_identifier(channel_id)
        errors: List[str] = []

        if not ordered_session_ids:
            return {
                "success": False,
                "error": "Нет доступных account_sessions: все сессии временно на паузе после FloodWait или невалидны",
            }

        for session_id in ordered_session_ids:
            try:
                client = await self.get_client(session_id)
                entity = await client.get_entity(parsed_channel_identifier)
                sent_message = await client.send_message(
                    entity,
                    comment_text,
                    comment_to=message_id,
                )
                return {
                    "success": True,
                    "session_id": session_id,
                    "comment_message_id": getattr(sent_message, "id", None),
                }
            except FloodWaitError as e:
                pause_seconds = self._pause_ai_comment_session(
                    session_id,
                    self._extract_flood_wait_seconds(e),
                )
                error_message = self._format_ai_comment_publish_error(
                    error=e,
                    session_id=session_id,
                    channel_id=channel_id,
                    message_id=message_id,
                )
                logger.warning(
                    "FloodWait при публикации нейрокомментария: job_id=%s session_id=%s channel=%s message_id=%s wait=%s pause=%s",
                    job_id,
                    session_id,
                    channel_id,
                    message_id,
                    e.seconds,
                    pause_seconds,
                )
                errors.append(error_message)
            except (ValueError, RPCError) as e:
                error_kind = self._classify_ai_comment_error(e)
                error_message = self._format_ai_comment_publish_error(
                    error=e,
                    session_id=session_id,
                    channel_id=channel_id,
                    message_id=message_id,
                )
                logger.warning(
                    "Не удалось опубликовать нейрокомментарий: job_id=%s session_id=%s channel=%s message_id=%s kind=%s error=%s",
                    job_id,
                    session_id,
                    channel_id,
                    message_id,
                    error_kind,
                    e,
                )
                errors.append(error_message)
                if error_kind in {"comments_disabled", "channel_unavailable"}:
                    break
            except Exception as e:
                error_kind = self._classify_ai_comment_error(e)
                error_message = self._format_ai_comment_publish_error(
                    error=e,
                    session_id=session_id,
                    channel_id=channel_id,
                    message_id=message_id,
                )
                logger.warning(
                    "Неожиданная ошибка публикации нейрокомментария: job_id=%s session_id=%s channel=%s message_id=%s kind=%s error=%s",
                    job_id,
                    session_id,
                    channel_id,
                    message_id,
                    error_kind,
                    e,
                )
                errors.append(error_message)
                if error_kind in {"comments_disabled", "channel_unavailable"}:
                    break

        return {
            "success": False,
            "error": "; ".join(errors) if errors else "Не удалось опубликовать комментарий",
        }

    async def process_ai_comment_jobs(
        self,
        job: Dict[str, Any],
        *,
        ai_comment_jobs_repo: Optional[AiCommentJobsRepo] = None,
    ) -> List[Dict[str, Any]]:
        repo = ai_comment_jobs_repo or AiCommentJobsRepo()
        current_job = self._refresh_ai_comment_job(repo, job)
        if current_job is None:
            self._clear_ai_comment_job_runtime_state(str(job.get("id") or "").strip())
            return []
        if current_job is not job:
            job.clear()
            job.update(current_job)

        job_id = str(job.get("id") or "").strip()
        if not job_id or not bool(job.get("is_active")):
            self._clear_ai_comment_job_runtime_state(job_id)
            return []

        session_ids = self._normalize_string_list(job.get("account_sessions"))
        if not session_ids:
            logger.warning(
                "Пропуск обработки нейрокомментариев: job_id=%s отсутствуют account_sessions",
                job_id,
            )
            self._clear_ai_comment_job_runtime_state(job_id)
            return []

        poll_result = await self._collect_ai_comment_job_fresh_posts(job)
        fresh_posts = poll_result["fresh_posts"]
        processed_posts: List[Dict[str, Any]] = []
        stopped_early = False

        for post in fresh_posts:
            channel_id = str(post["channel_id"])
            message_id = int(post["message_id"])

            try:
                current_job = self._refresh_ai_comment_job(repo, job)
                if current_job is None or not bool(current_job.get("is_active")):
                    logger.info(
                        "Останавливаем обработку кампании нейрокомментариев в текущем минутном цикле: job_id=%s",
                        job_id,
                    )
                    self._clear_ai_comment_job_runtime_state(job_id)
                    stopped_early = True
                    break

                if current_job is not job:
                    job.clear()
                    job.update(current_job)
                session_ids = self._normalize_string_list(job.get("account_sessions"))
                if not session_ids:
                    logger.warning(
                        "Останавливаем обработку нейрокомментариев: job_id=%s после обновления пропали account_sessions",
                        job_id,
                    )
                    self._clear_ai_comment_job_runtime_state(job_id)
                    stopped_early = True
                    break

                existing_record = repo.get_history_record(
                    job_id=job_id,
                    channel_id=channel_id,
                    message_id=message_id,
                )
                if existing_record is not None:
                    logger.info(
                        "Пропуск уже обработанного поста нейрокомментариев: job_id=%s channel_id=%s message_id=%s status=%s",
                        job_id,
                        channel_id,
                        message_id,
                        existing_record.get("status"),
                    )
                    processed_posts.append(
                        {
                            "channel_id": channel_id,
                            "message_id": message_id,
                            "status": "skipped",
                        }
                    )
                    continue

                generated_comment = await self.generate_ai_comment_with_fallback(
                    job_id=job_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    system_prompt=str(job.get("system_prompt") or ""),
                    user_prompt=str(job.get("user_prompt") or ""),
                    post_text=str(post.get("post_text") or ""),
                    ai_comment_jobs_repo=repo,
                )
                if not generated_comment:
                    processed_posts.append(
                        {
                            "channel_id": channel_id,
                            "message_id": message_id,
                            "status": "failed",
                        }
                    )
                    continue

                normalized_comment = self._normalize_ai_comment_text(generated_comment)
                if not normalized_comment:
                    error_message = "Сгенерированный комментарий пуст после очистки"
                    self._record_ai_comment_failure(
                        repo,
                        job_id=job_id,
                        channel_id=channel_id,
                        message_id=message_id,
                        error_message=error_message,
                    )
                    processed_posts.append(
                        {
                            "channel_id": channel_id,
                            "message_id": message_id,
                            "status": "failed",
                            "error": error_message,
                        }
                    )
                    continue

                publish_result = await self._publish_ai_comment(
                    job_id=job_id,
                    session_ids=session_ids,
                    channel_id=channel_id,
                    message_id=message_id,
                    comment_text=normalized_comment,
                )

                if publish_result["success"]:
                    repo.upsert_history_record(
                        job_id=job_id,
                        channel_id=channel_id,
                        message_id=message_id,
                        status="posted",
                        comment_message_id=publish_result.get("comment_message_id"),
                        comment_text=normalized_comment,
                    )
                    processed_posts.append(
                        {
                            "channel_id": channel_id,
                            "message_id": message_id,
                            "status": "posted",
                            "session_id": publish_result.get("session_id"),
                            "comment_message_id": publish_result.get("comment_message_id"),
                        }
                    )
                    continue

                self._record_ai_comment_failure(
                    repo,
                    job_id=job_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    error_message=publish_result["error"],
                )
                processed_posts.append(
                    {
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "status": "failed",
                        "error": publish_result["error"],
                    }
                )
            except Exception as e:
                error_message = f"Ошибка обработки поста нейрокомментариев: {e}"
                logger.exception(
                    "Неожиданная ошибка обработки поста нейрокомментариев: job_id=%s channel_id=%s message_id=%s error=%s",
                    job_id,
                    channel_id,
                    message_id,
                    e,
                )
                self._record_ai_comment_failure(
                    repo,
                    job_id=job_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    error_message=error_message,
                )
                processed_posts.append(
                    {
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "status": "failed",
                        "error": error_message,
                    }
                )

        if stopped_early:
            return processed_posts

        if poll_result["successful_channels"] > 0 and not poll_result["failed_channels"]:
            checkpoint_to_store = poll_result["checkpoint_to_store"]
            if checkpoint_to_store is not None:
                repo.update_last_checked_at(
                    job_id=job_id,
                    last_checked_at=checkpoint_to_store.isoformat(),
                )
                job["last_checked_at"] = checkpoint_to_store.isoformat()

                if poll_result["initialize_checkpoint"]:
                    logger.info(
                        "Инициализирован checkpoint кампании нейрокомментариев: job_id=%s last_checked_at=%s",
                        job_id,
                        checkpoint_to_store.isoformat(),
                    )
        elif poll_result["failed_channels"]:
            logger.warning(
                "Не обновляем last_checked_at после process_ai_comment_jobs из-за ошибок чтения каналов: job_id=%s failed_channels=%s",
                job_id,
                ",".join(poll_result["failed_channels"]),
            )

        return processed_posts

    async def generate_ai_comment_with_fallback(
        self,
        *,
        job_id: str,
        channel_id: str,
        message_id: int,
        system_prompt: str,
        user_prompt: str,
        post_text: str,
        ai_comment_jobs_repo: Optional[AiCommentJobsRepo] = None,
        fallback_models: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Генерирует комментарий через OpenRouter с fallback по моделям.
        Если ни одна модель не дала валидный ответ, фиксирует статус failed в истории.
        """
        try:
            generated = await self.openrouter_client.generate_comment_with_fallback(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                post_text=post_text,
                models=fallback_models,
            )
        except Exception as e:
            logger.exception(
                "Неожиданная ошибка генерации комментария: job_id=%s channel_id=%s message_id=%s error=%s",
                job_id,
                channel_id,
                message_id,
                e,
            )
            generated = None

        if generated:
            return generated

        error_message = "Не удалось сгенерировать комментарий: все fallback-модели вернули ошибку или пустой ответ"
        logger.warning(
            "Генерация комментария не удалась: job_id=%s channel_id=%s message_id=%s",
            job_id,
            channel_id,
            message_id,
        )

        if ai_comment_jobs_repo is not None:
            try:
                ai_comment_jobs_repo.upsert_history_record(
                    job_id=job_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    status="failed",
                    error=error_message,
                )
            except Exception as e:
                logger.error(
                    "Не удалось записать failed-статус в ai_comment_job_posts: job_id=%s channel_id=%s message_id=%s error=%s",
                    job_id,
                    channel_id,
                    message_id,
                    e,
                )

        return None

    def _build_reaction_job_signature(self, job: Dict[str, Any]) -> str:
        session_part = ",".join(sorted(job.get("account_sessions") or []))
        chats = [self._normalize_chat_identifier_for_reactions(chat) for chat in (job.get("target_chats") or [])]
        chat_part = ",".join(sorted(chats))
        reaction_part = ",".join(job.get("reactions") or [])
        frequency = str(job.get("message_frequency") or "")
        is_active = str(bool(job.get("is_active")))
        return f"{session_part}|{chat_part}|{reaction_part}|{frequency}|{is_active}"

    def _should_react(self, counter_key: str, message_frequency: str) -> bool:
        next_counter = self._reaction_counters.get(counter_key, 0) + 1
        self._reaction_counters[counter_key] = next_counter

        if message_frequency == "every":
            return True
        if message_frequency == "1/2":
            return next_counter % 2 == 0
        if message_frequency == "1/3":
            return next_counter % 3 == 0
        if message_frequency == "2/3":
            return next_counter % 3 in {1, 2}
        return False

    def _clear_reaction_job_runtime_state(self, job_id: str) -> None:
        self._reaction_job_signatures.pop(job_id, None)
        prefix = f"{job_id}:"
        for key in list(self._reaction_counters.keys()):
            if key.startswith(prefix):
                self._reaction_counters.pop(key, None)
        for key in list(self._reaction_last_seen_ids.keys()):
            if key.startswith(prefix):
                self._reaction_last_seen_ids.pop(key, None)

    def cleanup_inactive_reaction_jobs(self, active_job_ids: set[str]) -> None:
        known_job_ids = set(self._reaction_job_signatures.keys())
        known_job_ids.update(key.split(":", 1)[0] for key in self._reaction_counters.keys())
        known_job_ids.update(key.split(":", 1)[0] for key in self._reaction_last_seen_ids.keys())

        for job_id in known_job_ids:
            if job_id and job_id not in active_job_ids:
                self._clear_reaction_job_runtime_state(job_id)

    async def _send_reaction_to_message(
        self,
        *,
        client: TelegramClient,
        entity: Any,
        emoji: str,
        message_id: int,
        job_id: str,
        session_id: str,
        chat_identifier: Union[str, int],
    ) -> bool:
        try:
            if hasattr(client, "send_reaction"):
                await client.send_reaction(entity, message_id, reaction=emoji)
            else:
                await client(
                    functions.messages.SendReactionRequest(
                        peer=entity,
                        msg_id=message_id,
                        reaction=[types.ReactionEmoji(emoticon=emoji)],
                        big=False,
                        add_to_recent=False,
                    )
                )
            return True
        except FloodWaitError as e:
            await asyncio.sleep(max(1, e.seconds))
            return False
        except (ValueError, RPCError) as e:
            logger.warning(
                "Не удалось отправить реакцию: job_id=%s session_id=%s chat=%s message_id=%s error=%s",
                job_id,
                session_id,
                chat_identifier,
                message_id,
                e,
            )
            return False
        except Exception as e:
            logger.warning(
                "Неожиданная ошибка отправки реакции: job_id=%s session_id=%s chat=%s message_id=%s error=%s",
                job_id,
                session_id,
                chat_identifier,
                message_id,
                e,
            )
            return False

    async def stop_reaction_job_listeners(self, job_id: str) -> None:
        listeners = self._reaction_job_listeners.pop(job_id, [])
        for listener in listeners:
            try:
                listener.client.remove_event_handler(listener.handler)
            except Exception:
                # Хендлер уже мог быть удален в другом контексте.
                continue
        self._clear_reaction_job_runtime_state(job_id)

    async def process_reaction_job_poll(self, job: Dict[str, Any]) -> None:
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            return

        if not bool(job.get("is_active")):
            self._clear_reaction_job_runtime_state(job_id)
            return

        signature = self._build_reaction_job_signature(job)
        if self._reaction_job_signatures.get(job_id) != signature:
            self._clear_reaction_job_runtime_state(job_id)
            self._reaction_job_signatures[job_id] = signature

        reactions = [str(item).strip() for item in (job.get("reactions") or []) if str(item).strip()]
        message_frequency = str(job.get("message_frequency") or "every")
        session_ids = [str(item).strip() for item in (job.get("account_sessions") or []) if str(item).strip()]
        target_chats = [str(item).strip() for item in (job.get("target_chats") or []) if str(item).strip()]

        if not reactions or not session_ids or not target_chats:
            return

        for session_id in session_ids:
            try:
                client = await self.get_client(session_id)
            except Exception as e:
                logger.warning(
                    "Пропуск session в poll-реакциях: job_id=%s session_id=%s error=%s",
                    job_id,
                    session_id,
                    e,
                )
                continue

            for chat_identifier in target_chats:
                parsed_chat_identifier = self._parse_chat_identifier_for_reactions(chat_identifier)
                if isinstance(parsed_chat_identifier, str) and not parsed_chat_identifier.strip():
                    continue

                state_key = f"{job_id}:{session_id}:{parsed_chat_identifier}"

                try:
                    entity = await client.get_entity(parsed_chat_identifier)
                except Exception as e:
                    logger.warning(
                        "Не удалось получить entity чата в poll-реакциях: job_id=%s session_id=%s chat=%s error=%s",
                        job_id,
                        session_id,
                        parsed_chat_identifier,
                        e,
                    )
                    continue

                last_seen = self._reaction_last_seen_ids.get(state_key)
                try:
                    if last_seen is None:
                        latest = await client.get_messages(entity, limit=1)
                        if latest:
                            self._reaction_last_seen_ids[state_key] = max(int(latest[0].id), 0)
                        continue

                    messages = await client.get_messages(entity, min_id=last_seen, limit=50)
                except Exception as e:
                    logger.warning(
                        "Не удалось получить новые сообщения в poll-реакциях: job_id=%s session_id=%s chat=%s error=%s",
                        job_id,
                        session_id,
                        parsed_chat_identifier,
                        e,
                    )
                    continue

                if not messages:
                    continue

                fresh_messages = [
                    message for message in messages
                    if getattr(message, "id", None) is not None and int(message.id) > last_seen
                ]
                if not fresh_messages:
                    continue

                fresh_messages.sort(key=lambda message: int(message.id))
                newest_id = last_seen

                for message in fresh_messages:
                    message_id = int(message.id)
                    newest_id = max(newest_id, message_id)
                    if getattr(message, "out", False):
                        continue
                    if not self._should_react(state_key, message_frequency):
                        continue

                    emoji = random.choice(reactions)
                    sent = await self._send_reaction_to_message(
                        client=client,
                        entity=entity,
                        emoji=emoji,
                        message_id=message_id,
                        job_id=job_id,
                        session_id=session_id,
                        chat_identifier=parsed_chat_identifier,
                    )
                    if sent:
                        logger.info(
                            "Поставлена реакция в poll-режиме: job_id=%s session_id=%s chat=%s message_id=%s emoji=%s",
                            job_id,
                            session_id,
                            parsed_chat_identifier,
                            message_id,
                            emoji,
                        )

                self._reaction_last_seen_ids[state_key] = newest_id

    async def react_to_new_messages(
        self,
        job_id: str,
        session_id: str,
        chat_identifier: str,
        reactions: List[str],
        message_frequency: str,
    ) -> Optional[ReactionListenerState]:
        if not reactions:
            return None

        parsed_chat_identifier = self._parse_chat_identifier_for_reactions(chat_identifier)
        if (isinstance(parsed_chat_identifier, str) and not parsed_chat_identifier.strip()):
            return None

        try:
            client = await self.get_client(session_id)
            entity = await client.get_entity(parsed_chat_identifier)
        except ValueError as e:
            logger.warning(
                "Не удалось получить чат для реакций: session_id=%s chat_identifier=%s error=%s",
                session_id,
                chat_identifier,
                e,
            )
            return None
        except Exception as e:
            logger.warning(
                "Ошибка инициализации listener для реакций: session_id=%s chat_identifier=%s error=%s",
                session_id,
                chat_identifier,
                e,
            )
            return None

        counter_key = f"{job_id}:{session_id}:{parsed_chat_identifier}"

        async def _handler(event: events.NewMessage.Event) -> None:
            if not self._should_react(counter_key, message_frequency):
                return
            emoji = random.choice(reactions)
            try:
                logger.info(
                    "Сработал listener авто-реакции: job_id=%s session_id=%s chat=%s message_id=%s",
                    job_id,
                    session_id,
                    parsed_chat_identifier,
                    event.message.id,
                )
                if hasattr(client, "send_reaction"):
                    await client.send_reaction(entity, event.message.id, reaction=emoji)
                else:
                    await client(
                        functions.messages.SendReactionRequest(
                            peer=entity,
                            msg_id=event.message.id,
                            reaction=[types.ReactionEmoji(emoticon=emoji)],
                            big=False,
                            add_to_recent=False,
                        )
                    )
            except FloodWaitError as e:
                await asyncio.sleep(max(1, e.seconds))
            except (ValueError, RPCError) as e:
                logger.warning(
                    "Не удалось отправить реакцию: job_id=%s session_id=%s chat=%s message_id=%s error=%s",
                    job_id,
                    session_id,
                    parsed_chat_identifier,
                    event.message.id,
                    e,
                )
                return
            except Exception as e:
                logger.warning(
                    "Неожиданная ошибка отправки реакции: job_id=%s session_id=%s chat=%s message_id=%s error=%s",
                    job_id,
                    session_id,
                    parsed_chat_identifier,
                    event.message.id,
                    e,
                )
                return

        client.add_event_handler(_handler, events.NewMessage(chats=entity))
        return ReactionListenerState(
            client=client,
            handler=_handler,
            session_id=session_id,
            chat_identifier=str(parsed_chat_identifier),
        )

    async def ensure_reaction_job_listeners(self, job: Dict[str, Any]) -> None:
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            return

        if not bool(job.get("is_active")):
            await self.stop_reaction_job_listeners(job_id)
            return

        signature = self._build_reaction_job_signature(job)
        if self._reaction_job_signatures.get(job_id) == signature and job_id in self._reaction_job_listeners:
            return

        await self.stop_reaction_job_listeners(job_id)
        reactions = [str(item).strip() for item in (job.get("reactions") or []) if str(item).strip()]
        message_frequency = str(job.get("message_frequency") or "every")
        session_ids = [str(item).strip() for item in (job.get("account_sessions") or []) if str(item).strip()]
        target_chats = [str(item).strip() for item in (job.get("target_chats") or []) if str(item).strip()]

        if not reactions or not session_ids or not target_chats:
            return

        created: List[ReactionListenerState] = []
        for session_id in session_ids:
            for chat_identifier in target_chats:
                listener = await self.react_to_new_messages(
                    job_id=job_id,
                    session_id=session_id,
                    chat_identifier=chat_identifier,
                    reactions=reactions,
                    message_frequency=message_frequency,
                )
                if listener is not None:
                    created.append(listener)

        if created:
            self._reaction_job_listeners[job_id] = created
            self._reaction_job_signatures[job_id] = signature
            logger.info(
                "Запущены listener'ы авто-реакций: job_id=%s listeners=%s sessions=%s chats=%s",
                job_id,
                len(created),
                len(session_ids),
                len(target_chats),
            )
        else:
            logger.warning(
                "Не удалось создать listener'ы авто-реакций: job_id=%s sessions=%s chats=%s",
                job_id,
                len(session_ids),
                len(target_chats),
            )
    
