import asyncio
import base64
import binascii
import hashlib
import re
import time
from datetime import datetime, timedelta
from statistics import mean, median, pstdev
from typing import Optional, List, Dict, Any
from urllib.parse import parse_qs, urlparse
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    FloodWaitError,
    RPCError,
    InviteHashEmptyError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    InviteRequestSentError,
    UserAlreadyParticipantError,
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
from app.config import API_ID, API_HASH
from app.storage import SessionRepo
from app.storage import ChannelAnalyticsRepo


class MultiSessionManager:
    """Менеджер Telethon с поддержкой нескольких сессий."""

    def __init__(
        self,
        session_repo: Optional[SessionRepo] = None,
        channel_analytics_repo: Optional[ChannelAnalyticsRepo] = None,
        default_session_id: str = "default",
    ):
        self.session_repo = session_repo
        self.default_session_id = default_session_id
        self.channel_analytics_repo = channel_analytics_repo
        self._clients: Dict[str, TelegramClient] = {}
        self._auth_clients: Dict[str, TelegramClient] = {}
        self._authorized_sessions: set[str] = set()
        self._auth_state: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_iso(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _coerce_channel_username(entity: Channel, channel_identifier: str) -> str:
        username = getattr(entity, "username", None)
        if username:
            return str(username).lstrip("@")
        normalized_id = MultiSessionManager._channel_api_id(entity)
        if normalized_id:
            return str(normalized_id)
        return channel_identifier.lstrip("@").strip() or "unknown"

    @staticmethod
    def _build_channel_url(channel_username: str) -> Optional[str]:
        if not channel_username:
            return None
        if channel_username.startswith("-100") or channel_username.lstrip("-").isdigit():
            return None
        return f"https://t.me/{channel_username}"

    @staticmethod
    def _build_post_url(channel_identifier: str, message_id: int) -> Optional[str]:
        if not channel_identifier:
            return None
        if channel_identifier.startswith("-100") or channel_identifier.lstrip("-").isdigit():
            return None
        return f"https://t.me/{channel_identifier.strip('/')}/{int(message_id)}"

    @staticmethod
    def _contains_http(text: Optional[str]) -> bool:
        if not text:
            return False
        return bool(re.search(r"https?://|t\.me/", text, flags=re.IGNORECASE))

    @staticmethod
    def _count_keywords(text: str, keywords: List[str]) -> List[str]:
        lowered = (text or "").lower()
        return [kw for kw in keywords if kw in lowered]

    @staticmethod
    def _score_threshold(value: float, mapping: List[tuple[float, float]]) -> float:
        """Возвращает score по убывающим порогам [(min_value, score)]"""
        for threshold, score in mapping:
            if value >= threshold:
                return score
        return mapping[-1][1]

    @staticmethod
    def _hash_text(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

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

    async def _get_session_client(self, session_id: Optional[str]) -> TelegramClient:
        sid = self._normalize_session_id(session_id)
        return await self.get_client(sid)

    @staticmethod
    def _channel_api_id(entity: Any) -> int:
        entity_id = int(getattr(entity, "id", 0) or 0)
        if isinstance(entity, Channel):
            return int(f"-100{entity_id}")
        return entity_id

    @staticmethod
    def _extract_invite_hash(channel_identifier: str) -> Optional[str]:
        value = channel_identifier.strip()
        if not value:
            return None

        parsed = urlparse(value if "://" in value else f"https://{value}")
        if parsed.scheme == "tg" and parsed.netloc == "join":
            invite = parse_qs(parsed.query).get("invite", [""])[0].strip()
            return invite or None

        path = parsed.path.strip("/")
        if parsed.netloc in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
            parts = [part for part in path.split("/") if part]
            if not parts:
                return None
            if parts[0].startswith("+"):
                return parts[0][1:] or None
            if parts[0] == "joinchat" and len(parts) > 1:
                return parts[1] or None

        if value.startswith("+"):
            return value[1:] or None
        if "joinchat/" in value:
            return value.rsplit("joinchat/", 1)[-1].split("/", 1)[0] or None

        return None

    @staticmethod
    def _normalize_channel_identifier(channel_identifier: str) -> str:
        value = channel_identifier.strip()
        parsed = urlparse(value if "://" in value else f"https://{value}")
        if parsed.netloc in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if parts and parts[0] not in {"c", "s", "joinchat"} and not parts[0].startswith("+"):
                return f"@{parts[0]}"
        return value

    @staticmethod
    def _message_media_type(msg: Any) -> Optional[str]:
        if not getattr(msg, "media", None):
            return None
        if isinstance(msg.media, MessageMediaPhoto):
            return "photo"
        if isinstance(msg.media, MessageMediaDocument):
            doc = msg.media.document
            attrs = getattr(doc, "attributes", []) or []
            for attr in attrs:
                if isinstance(attr, DocumentAttributeVideo):
                    return "video"
                if isinstance(attr, DocumentAttributeAudio):
                    return "voice" if getattr(attr, "voice", False) else "audio"
                if isinstance(attr, DocumentAttributeSticker):
                    return "sticker"
            return "document"
        return "other"

    def _message_to_dict(self, msg: Any, fallback_chat_id: Optional[int] = None) -> Dict[str, Any]:
        sender_id = self._extract_sender_id(msg)

        msg_chat_id: Optional[int] = fallback_chat_id
        if getattr(msg, "peer_id", None) is not None:
            peer = msg.peer_id
            if hasattr(peer, "channel_id"):
                msg_chat_id = int(f"-100{peer.channel_id}")
            elif hasattr(peer, "chat_id"):
                msg_chat_id = peer.chat_id
            elif hasattr(peer, "user_id"):
                msg_chat_id = peer.user_id

        has_media = bool(getattr(msg, "media", None))
        return {
            "id": getattr(msg, "id", 0),
            "chat_id": msg_chat_id if msg_chat_id is not None else 0,
            "sender_id": sender_id,
            "text": getattr(msg, "message", None) or "",
            "date": msg.date.isoformat() if getattr(msg, "date", None) else "",
            "is_out": bool(getattr(msg, "out", False)),
            "has_media": has_media,
            "media_type": self._message_media_type(msg),
            "media_id": msg.id if has_media else None,
        }

    def _extract_sender_id(self, obj: Any) -> Optional[int]:
        sender_id: Optional[int] = None
        if getattr(obj, "sender_id", None) is not None:
            try:
                sender_id = int(obj.sender_id)
            except (TypeError, ValueError):
                sender_id = None
        elif getattr(obj, "from_id", None) is not None:
            from_id = obj.from_id
            if isinstance(from_id, types.PeerUser):
                sender_id = self._safe_int(from_id.user_id)
            elif isinstance(from_id, types.PeerChat):
                sender_id = self._safe_int(from_id.chat_id)
            elif isinstance(from_id, types.PeerChannel):
                sender_id = self._safe_int(from_id.channel_id)
        return sender_id

    @staticmethod
    def _count_post_reactions(msg: Any) -> int:
        reactions = getattr(msg, "reactions", None)
        if not reactions:
            return 0
        total = 0
        for item in getattr(reactions, "results", []) or []:
            total += int(getattr(item, "count", 0) or 0)
        return total

    @staticmethod
    def _is_ad_like(text: Optional[str]) -> bool:
        lowered = (text or "").lower()
        ad_signals = [
            "реклама",
            "купите",
            "подпишитесь",
            "заказать",
            "спецпредложение",
            "акция",
            "распродажа",
            "скидк",
            "бонус",
            "платный",
            "тариф",
            "продаю",
            "продам",
            "скидка",
        ]
        return any(signal in lowered for signal in ad_signals)

    @staticmethod
    def _is_spam_like_comment(text: str) -> bool:
        lowered = (text or "").lower()
        if not lowered.strip():
            return True
        spam_signals = [
            "подписывайся",
            "подпишись",
            "купить",
            "заказать",
            "аккаунт",
            "перейди",
            "скид",
            "https://",
            "http://",
            "сайт",
            "бот",
        ]
        if any(signal in lowered for signal in spam_signals):
            return True
        links = len(re.findall(r"https?://", lowered))
        return links >= 2

    @staticmethod
    def _normalize_comment_text(text: Optional[str]) -> str:
        if not text:
            return ""
        text = text.replace("\n", " ").strip()
        return " ".join(text.split())[:800]

    @staticmethod
    def _channel_result(entity: Channel) -> Dict[str, Any]:
        return {
            "id": MultiSessionManager._channel_api_id(entity),
            "name": getattr(entity, "title", None) or "Channel",
            "type": "channel" if getattr(entity, "broadcast", False) else "supergroup",
            "username": getattr(entity, "username", None),
            "participants_count": getattr(entity, "participants_count", None),
            "is_verified": bool(getattr(entity, "verified", False)),
            "is_scam": bool(getattr(entity, "scam", False)),
            "is_fake": bool(getattr(entity, "fake", False)),
            "is_private": not bool(getattr(entity, "username", None)),
            "join_request": bool(getattr(entity, "join_request", False)),
        }

    @staticmethod
    def _dialog_filters_from_result(filters_result: Any) -> List[Any]:
        if hasattr(filters_result, "filters"):
            return list(filters_result.filters or [])
        if isinstance(filters_result, list):
            return filters_result
        return []

    @staticmethod
    def _dialog_filter_title(dialog_filter: Any) -> str:
        title = getattr(dialog_filter, "title", "") or ""
        return getattr(title, "text", title) or ""

    @staticmethod
    def _input_peer_key(peer: Any) -> tuple[str, int]:
        if isinstance(peer, types.InputPeerChannel):
            return ("channel", int(peer.channel_id))
        if isinstance(peer, types.InputPeerChat):
            return ("chat", int(peer.chat_id))
        if isinstance(peer, types.InputPeerUser):
            return ("user", int(peer.user_id))
        return (peer.__class__.__name__, int(getattr(peer, "id", 0) or 0))

    @staticmethod
    def _chat_info_from_entity(entity: Any) -> Dict[str, Any]:
        if isinstance(entity, Channel):
            return {
                "id": MultiSessionManager._channel_api_id(entity),
                "name": getattr(entity, "title", None) or "Channel",
                "type": "channel" if getattr(entity, "broadcast", False) else "supergroup",
                "username": getattr(entity, "username", None),
                "unread_count": 0,
                "is_pinned": False,
                "is_verified": bool(getattr(entity, "verified", False)),
                "is_scam": bool(getattr(entity, "scam", False)),
                "is_fake": bool(getattr(entity, "fake", False)),
            }
        if isinstance(entity, Chat):
            return {
                "id": int(getattr(entity, "id", 0) or 0),
                "name": getattr(entity, "title", None) or "Group",
                "type": "group",
                "username": None,
                "unread_count": 0,
                "is_pinned": False,
                "is_verified": False,
                "is_scam": False,
                "is_fake": False,
            }
        return {
            "id": int(getattr(entity, "id", 0) or 0),
            "name": getattr(entity, "username", None) or "Chat",
            "type": None,
            "username": getattr(entity, "username", None),
            "unread_count": 0,
            "is_pinned": False,
            "is_verified": False,
            "is_scam": False,
            "is_fake": False,
        }

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
            await client.sign_in(phone, code, phone_code_hash=state["phone_code_hash"])
            self._clients[session_id] = client
            self._auth_clients.pop(session_id, None)
            self._authorized_sessions.add(session_id)
            state["phone_code_hash"] = ""
            self._get_session_repo().save_authorized(session_id, client.session.save())
            
            return {
                "success": True,
                "message": "Авторизация успешна"
            }
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
            
            # Определяем ID и название чата
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
            
            # Получаем сообщения
            messages = await self.client.get_messages(entity, limit=limit)
            
            result_messages: List[Dict[str, Any]] = []
            for msg in messages:
                # Определяем sender_id
                sender_id: Optional[int] = None
                if hasattr(msg, "sender_id") and msg.sender_id is not None:
                    # В новых версиях Telethon sender_id обычно int
                    try:
                        sender_id = int(msg.sender_id)
                    except (TypeError, ValueError):
                        sender_id = None
                elif hasattr(msg, "from_id") and msg.from_id is not None:
                    from_id = msg.from_id
                    if isinstance(from_id, types.PeerUser):
                        sender_id = from_id.user_id
                    elif isinstance(from_id, types.PeerChat):
                        sender_id = from_id.chat_id
                    elif isinstance(from_id, types.PeerChannel):
                        sender_id = from_id.channel_id
                
                # Определяем chat_id из peer_id (на случай, если сверху не удалось)
                msg_chat_id: Optional[int] = chat_id
                if hasattr(msg, "peer_id") and msg.peer_id is not None:
                    peer = msg.peer_id
                    if hasattr(peer, "channel_id"):
                        msg_chat_id = peer.channel_id
                    elif hasattr(peer, "chat_id"):
                        msg_chat_id = peer.chat_id
                    elif hasattr(peer, "user_id"):
                        msg_chat_id = peer.user_id
                
                # Информация о медиа
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
                        # Для скачивания медиа достаточно ID сообщения и chat_id
                        "media_id": msg.id if has_media else None,
                    }
                )
            
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

    async def get_message_views(self, channel_identifier: str, message_id: int) -> Dict[str, Any]:
        """
        Возвращает количество просмотров сообщения в канале.

        Args:
            channel_identifier: Username канала (например, @channel) или ID канала
            message_id: ID сообщения (поста) в канале

        Returns:
            Словарь с количеством просмотров
        """
        if not self.client:
            await self.get_client(self.default_session_id)

        if not self._is_connected:
            raise ValueError("Необходима авторизация")

        try:
            entity = await self.client.get_entity(self._normalize_channel_identifier(channel_identifier))
            if not isinstance(entity, Channel):
                raise ValueError("Переданный идентификатор должен ссылаться на канал или супергруппу")

            message = await self.client.get_messages(entity, ids=message_id)
            if isinstance(message, list):
                message = message[0] if message else None
            if not message:
                raise ValueError("Сообщение не найдено")

            views = getattr(message, "views", None)
            return {
                "success": True,
                "chat_id": getattr(entity, "id", None),
                "message_id": message.id,
                "views": views,
                "message": "Количество просмотров получено",
            }
        except ValueError as e:
            raise ValueError(f"Канал или сообщение не найдены: {e}")
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
        query: str,
        limit: int = 20,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ищет публичные каналы и супергруппы через Telegram global search."""
        client = await self._get_session_client(session_id)
        query_value = query.strip()
        if not query_value:
            raise ValueError("query не может быть пустым")

        try:
            result = await client(functions.contacts.SearchRequest(q=query_value, limit=limit))
            channels = [
                self._channel_result(chat)
                for chat in getattr(result, "chats", []) or []
                if isinstance(chat, Channel)
            ]
            return {
                "success": True,
                "query": query_value,
                "channels": channels,
                "total": len(channels),
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def join_channel(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Входит в публичный канал или отправляет заявку по private invite link."""
        client = await self._get_session_client(session_id)
        value = channel_identifier.strip()
        if not value:
            raise ValueError("channel_identifier не может быть пустым")

        invite_hash = self._extract_invite_hash(value)
        if invite_hash:
            checked: Any = None
            try:
                checked = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
                if isinstance(checked, types.ChatInviteAlready):
                    chat = checked.chat
                    return {
                        "success": True,
                        "status": "already_joined",
                        "channel_id": self._channel_api_id(chat),
                        "title": getattr(chat, "title", None),
                        "username": getattr(chat, "username", None),
                        "participants_count": getattr(chat, "participants_count", None),
                        "request_needed": False,
                        "message": "Аккаунт уже в канале/чате",
                    }

                imported = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
                chat = next(
                    (chat for chat in getattr(imported, "chats", []) or [] if isinstance(chat, (Channel, Chat))),
                    None,
                )
                return {
                    "success": True,
                    "status": "joined",
                    "channel_id": self._channel_api_id(chat) if chat else None,
                    "title": getattr(chat, "title", None) if chat else getattr(checked, "title", None),
                    "username": getattr(chat, "username", None) if chat else None,
                    "participants_count": getattr(chat, "participants_count", None)
                    if chat
                    else getattr(checked, "participants_count", None),
                    "request_needed": False,
                    "message": "Вход по invite link выполнен",
                }
            except InviteRequestSentError:
                return {
                    "success": True,
                    "status": "request_sent",
                    "channel_id": None,
                    "title": getattr(checked, "title", None),
                    "username": None,
                    "participants_count": getattr(checked, "participants_count", None),
                    "request_needed": True,
                    "message": "Заявка на вступление отправлена",
                }
            except (InviteHashEmptyError, InviteHashExpiredError, InviteHashInvalidError) as e:
                raise ValueError(f"Некорректная или устаревшая invite link: {e}")
            except FloodWaitError as e:
                raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
            except RPCError as e:
                raise ValueError(f"Ошибка Telegram API: {e.message}")

        try:
            entity = await client.get_entity(self._normalize_channel_identifier(value))
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            try:
                await client(functions.channels.JoinChannelRequest(channel=entity))
                status = "joined"
                message = "Подписка на канал выполнена"
            except UserAlreadyParticipantError:
                status = "already_joined"
                message = "Аккаунт уже подписан на канал"
            except InviteRequestSentError:
                status = "request_sent"
                message = "Заявка на вступление отправлена"

            return {
                "success": True,
                "status": status,
                "channel_id": self._channel_api_id(entity),
                "title": getattr(entity, "title", None),
                "username": getattr(entity, "username", None),
                "participants_count": getattr(entity, "participants_count", None),
                "request_needed": status == "request_sent",
                "message": message,
            }
        except ValueError as e:
            raise ValueError(f"Канал не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_channel_comments_status(
        self,
        channel_identifier: str,
        message_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Проверяет, есть ли discussion group и комментарии у конкретного поста."""
        client = await self._get_session_client(session_id)
        try:
            entity = await client.get_entity(self._normalize_channel_identifier(channel_identifier))
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            full = await client(functions.channels.GetFullChannelRequest(channel=entity))
            full_chat = getattr(full, "full_chat", None)
            linked_chat_id = getattr(full_chat, "linked_chat_id", None)
            linked_chat_name: Optional[str] = None
            if linked_chat_id:
                for chat in getattr(full, "chats", []) or []:
                    if getattr(chat, "id", None) == linked_chat_id:
                        linked_chat_name = getattr(chat, "title", None)
                        break

            comments_count = 0
            has_comments = False
            if message_id is not None:
                msg = await client.get_messages(entity, ids=message_id)
                if not msg:
                    raise ValueError("Пост не найден")
                replies = getattr(msg, "replies", None)
                comments_count = int(getattr(replies, "replies", 0) or 0) if replies else 0
                has_comments = bool(
                    replies
                    and (
                        bool(getattr(replies, "comments", False))
                        or comments_count > 0
                    )
                )
            else:
                has_comments = bool(linked_chat_id)

            return {
                "success": True,
                "channel_id": self._channel_api_id(entity),
                "channel_name": getattr(entity, "title", None),
                "linked_chat_id": linked_chat_id,
                "linked_chat_name": linked_chat_name,
                "has_discussion_group": bool(linked_chat_id),
                "message_id": message_id,
                "has_comments": has_comments,
                "comments_count": comments_count,
                "message": "Комментарии включены" if has_comments else "Комментарии не найдены",
            }
        except ValueError as e:
            raise ValueError(f"Канал или пост не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def get_post_comments(
        self,
        channel_identifier: str,
        message_id: int,
        limit: int = 50,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Возвращает комментарии/ответы к посту канала."""
        client = await self._get_session_client(session_id)
        try:
            entity = await client.get_entity(self._normalize_channel_identifier(channel_identifier))
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            result = await client(
                functions.messages.GetRepliesRequest(
                    peer=entity,
                    msg_id=message_id,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
            comments = [
                self._message_to_dict(msg, fallback_chat_id=self._channel_api_id(entity))
                for msg in getattr(result, "messages", []) or []
                if getattr(msg, "id", None)
            ]
            return {
                "success": True,
                "channel_id": self._channel_api_id(entity),
                "channel_name": getattr(entity, "title", None),
                "message_id": message_id,
                "comments": comments,
                "total": len(comments),
            }
        except ValueError as e:
            raise ValueError(f"Канал или пост не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def collect_channel_posts(
        self,
        channel_identifier: str,
        limit: int = 50,
        exclude_forwards: bool = True,
        exclude_ads: bool = True,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Собирает последние посты канала и сохраняет их в analytics-репозиторий."""
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        client = await self._get_session_client(session_id)
        if not channel_identifier.strip():
            raise ValueError("channel_id не может быть пустым")

        try:
            entity = await client.get_entity(self._normalize_channel_identifier(channel_identifier))
            if not isinstance(entity, Channel):
                raise ValueError("Переданный идентификатор должен быть каналом")

            channel_id = self._channel_api_id(entity)
            channel_username = self._coerce_channel_username(entity, str(channel_identifier))
            full = await client(functions.channels.GetFullChannelRequest(channel=entity))
            full_chat = getattr(full, "full_chat", None)
            participants_count = self._safe_int(
                getattr(full_chat, "participants_count", None),
                0,
            )
            title = getattr(entity, "title", None)
            about = getattr(full_chat, "about", None)
            monetization_signals = self._collect_monetization_signals(
                " ".join([str(title or ""), str(about or ""), str(channel_identifier or "")])
            )
            self.channel_analytics_repo.upsert_channel_profile(
                channel_username=channel_username,
                title=title,
                url=self._build_channel_url(channel_username),
                niche=None,
                monetization_signals=monetization_signals if monetization_signals else None,
                subscribers_count=participants_count,
            )

            messages = await client.get_messages(entity, limit=limit)
            normalized_posts: List[Dict[str, Any]] = []
            for msg in messages:
                if exclude_forwards and bool(getattr(msg, "forward", None)):
                    continue

                text = getattr(msg, "message", None) or ""
                is_ad_like = self._is_ad_like(text)
                if exclude_ads and is_ad_like:
                    continue

                date_value = self._safe_iso(getattr(msg, "date", None))
                msg_id = self._safe_int(getattr(msg, "id", 0))
                views = self._safe_int(getattr(msg, "views", 0))
                forwards = self._safe_int(getattr(msg, "forwards", 0))
                replies = getattr(msg, "replies", None)
                replies_count = self._safe_int(getattr(replies, "replies", 0))
                reactions_count = self._count_post_reactions(msg)
                has_media = bool(getattr(msg, "media", None))
                post_url = self._build_post_url(channel_username, msg_id)
                is_forward = bool(
                    getattr(msg, "forward", None)
                    or getattr(msg, "fwd_from", None)
                )

                normalized_posts.append(
                    {
                        "channel_id": channel_id,
                        "channel_username": channel_username,
                        "message_id": msg_id,
                        "post_url": post_url,
                        "date": date_value,
                        "text": text,
                        "views": views,
                        "forwards": forwards,
                        "replies_count": replies_count,
                        "reactions_count": reactions_count,
                        "has_media": has_media,
                        "has_link": self._contains_http(text),
                        "is_forward": is_forward,
                        "is_ad_like": is_ad_like,
                    }
                )

            saved = self.channel_analytics_repo.upsert_channel_posts(
                channel_username=channel_username,
                posts=normalized_posts,
            )

            return {
                "success": True,
                "channel_id": channel_id,
                "channel_username": channel_username,
                "posts_analyzed": saved,
                "posts": normalized_posts,
                "message": f"Собрано и сохранено {saved} постов",
            }
        except ValueError as e:
            raise ValueError(f"Канал не найден: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    async def collect_channel_comments(
        self,
        channel_identifier: str,
        posts_limit: int = 20,
        comments_per_post: int = 50,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Собирает комментарии к последним постам и сохраняет их в analytics-репозиторий."""
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        client = await self._get_session_client(session_id)
        if not channel_identifier.strip():
            raise ValueError("channel_id не может быть пустым")

        try:
            entity = await client.get_entity(self._normalize_channel_identifier(channel_identifier))
            if not isinstance(entity, Channel):
                raise ValueError("Переданный идентификатор должен быть каналом")

            channel_id = self._channel_api_id(entity)
            channel_username = self._coerce_channel_username(entity, str(channel_identifier))
            posts = await client.get_messages(entity, limit=posts_limit)
            normalized_comments: List[Dict[str, Any]] = []
            posts_considered = 0

            for msg in posts:
                msg_id = self._safe_int(getattr(msg, "id", 0))
                if not msg_id:
                    continue
                if getattr(msg, "replies", None) is None or not getattr(msg.replies, "replies", None):
                    continue

                result = await client(
                    functions.messages.GetRepliesRequest(
                        peer=entity,
                        msg_id=msg_id,
                        offset_id=0,
                        offset_date=None,
                        add_offset=0,
                        limit=comments_per_post,
                        max_id=0,
                        min_id=0,
                        hash=0,
                    )
                )
                replies = getattr(result, "messages", []) or []
                if not replies:
                    continue

                posts_considered += 1
                for comment in replies:
                    comment_id = self._safe_int(comment.id, 0)
                    if comment_id <= 0:
                        continue
                    sender_id = self._extract_sender_id(comment)
                    sender_hash = self._hash_text(str(sender_id)) if sender_id is not None else None
                    is_author_reply = bool(
                        isinstance(getattr(comment, "from_id", None), types.PeerChannel)
                        and getattr(comment.from_id, "channel_id", None) == getattr(entity, "id", None)
                    )
                    commenter_username = None
                    raw_commenter = getattr(comment, "sender", None)
                    if raw_commenter is not None:
                        commenter_username = getattr(raw_commenter, "username", None)
                    if not commenter_username:
                        commenter_username = getattr(comment, "post_author", None)
                    if commenter_username:
                        commenter_username = str(commenter_username).strip() or None

                    normalized_comments.append(
                        {
                            "channel_id": channel_id,
                            "post_message_id": msg_id,
                            "comment_id": comment_id,
                            "comment_text": self._normalize_comment_text(
                                getattr(comment, "message", None)
                            ),
                            "comment_date": self._safe_iso(getattr(comment, "date", None)),
                            "commenter_id_hash": sender_hash,
                            "commenter_username": commenter_username,
                            "is_author_reply": is_author_reply,
                            "is_spam_like": self._is_spam_like_comment(
                                getattr(comment, "message", None) or ""
                            ),
                        }
                    )

            saved = self.channel_analytics_repo.upsert_channel_comments(
                channel_username=channel_username,
                comments=[
                    {
                        "post_message_id": item["post_message_id"],
                        "comment_id": item["comment_id"],
                        "comment_text": item["comment_text"],
                        "comment_date": item["comment_date"],
                        "commenter_id_hash": item["commenter_id_hash"],
                        "commenter_username": item["commenter_username"],
                        "is_author_reply": item["is_author_reply"],
                        "is_spam_like": item["is_spam_like"],
                    }
                    for item in normalized_comments
                ],
            )
            # Нормализуем комментарии после сохранения (без служебных полей)
            normalized_comments = [self._map_comment_payload(item) for item in normalized_comments]

            return {
                "success": True,
                "channel_id": channel_id,
                "channel_username": channel_username,
                "posts_considered": posts_considered,
                "total_comments": saved,
                "comments": normalized_comments,
                "message": f"Собрано и сохранено {saved} комментариев из {posts_considered} постов",
            }
        except ValueError as e:
            raise ValueError(f"Канал или комментарии недоступны: {e}")
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")

    def _map_comment_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "channel_id": item.get("channel_id"),
            "post_message_id": item.get("post_message_id"),
            "comment_id": item.get("comment_id"),
            "comment_text": item.get("comment_text"),
            "comment_date": item.get("comment_date"),
            "commenter_id_hash": item.get("commenter_id_hash"),
            "commenter_username": item.get("commenter_username"),
            "is_author_reply": bool(item.get("is_author_reply")),
            "is_spam_like": bool(item.get("is_spam_like")),
        }

    @staticmethod
    def _collect_monetization_signals(text: str) -> str:
        signals = [
            "курс",
            "консультация",
            "наставничество",
            "клуб",
            "закрытый клуб",
            "подписка",
            "платный канал",
            "марафон",
            "вебинар",
            "созвон",
            "оплата",
            "тариф",
            "купить",
            "записаться",
            "разбор",
            "getcourse",
            "бот",
            "mini app",
            "сайт",
            "воронка",
            "лид-магнит",
        ]
        found = MultiSessionManager._count_keywords(text, signals)
        if not found:
            return ""
        return ", ".join(found)

    @staticmethod
    def _collect_niche_signals(text: str) -> List[str]:
        niches = [
            "онлайн-школы",
            "getcourse",
            "продюсеры",
            "инфобизнес",
            "telegram-монетизация",
            "telegram ads",
            "ai для бизнеса",
            "английский",
            "карьера",
            "подготовка к собеседованиям",
            "продажи",
            "фитнес",
            "нутрициология",
            "психология",
            "личный бренд",
        ]
        return MultiSessionManager._count_keywords(text, niches)

    @staticmethod
    def _collect_pain_markers(text: str) -> List[str]:
        pain_markers = [
            "запуск",
            "дорогой трафик",
            "мало лидов",
            "падает конверсия",
            "нет системности",
            "не хватает кураторов",
            "сложно удерживать учеников",
            "низкая доходимость",
            "надо автоматизировать",
            "как внедрить нейросети",
            "как сделать подписку",
            "как монетизировать аудиторию",
            "как увеличить ltv",
            "как поднять retention",
            "регулярная выручка",
            "mrr",
        ]
        return MultiSessionManager._count_keywords(text, pain_markers)

    @staticmethod
    def _parse_date_utc(value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    def _median(self, values: List[float]) -> float:
        if not values:
            return 0.0
        try:
            return float(median(values))
        except Exception:
            return 0.0

    def _mean(self, values: List[float]) -> float:
        if not values:
            return 0.0
        try:
            return float(mean(values))
        except Exception:
            return 0.0

    def _std(self, values: List[float]) -> float:
        if not values:
            return 0.0
        if len(values) < 2:
            return 0.0
        try:
            return float(pstdev(values))
        except Exception:
            return 0.0

    async def _refresh_channel_profile(self, channel_identifier: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        client = await self._get_session_client(session_id)
        entity = await client.get_entity(self._normalize_channel_identifier(channel_identifier))
        if not isinstance(entity, Channel):
            raise ValueError("Указанный идентификатор не является каналом")

        full = await client(functions.channels.GetFullChannelRequest(channel=entity))
        full_chat = getattr(full, "full_chat", None)
        return {
            "entity": entity,
            "channel_id": self._channel_api_id(entity),
            "channel_username": self._coerce_channel_username(entity, channel_identifier),
            "participants_count": self._safe_int(getattr(full_chat, "participants_count", 0), 0),
            "title": getattr(entity, "title", None),
            "username": getattr(entity, "username", None),
            "about": getattr(full_chat, "about", None),
            "full_chat": full_chat,
        }

    async def score_channel_health(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        profile = await self._refresh_channel_profile(channel_identifier, session_id=session_id)
        channel_username = profile["channel_username"]
        channel_id = profile["channel_id"]
        posts = self.channel_analytics_repo.list_channel_posts(channel_username=channel_username, limit=200)

        if not posts:
            return {
                "success": False,
                "channel_id": channel_id,
                "channel_username": channel_username,
                "subscribers_count": profile["participants_count"],
                "posts_analyzed": 0,
                "median_views_30": 0.0,
                "avg_views_30": 0.0,
                "view_rate": 0.0,
                "posts_per_week": 0.0,
                "views_cv": 0.0,
                "median_reactions": 0.0,
                "reaction_rate": 0.0,
                "median_forwards": 0.0,
                "forward_rate": 0.0,
                "last_post_at": None,
                "channel_health_score": 0.0,
                "message": "Недостаточно данных. Сначала соберите посты.",
            }

        now = datetime.utcnow()
        cutoff_30 = now - timedelta(days=30)
        last_30_days_posts = [
            post for post in posts
            if self._parse_date_utc(post.get("date")) and self._parse_date_utc(post.get("date")) >= cutoff_30
        ]
        if not last_30_days_posts:
            last_30_days_posts = posts[:min(len(posts), 30)]

        views = [self._safe_float(post.get("views")) for post in last_30_days_posts]
        forwards = [self._safe_float(post.get("forwards")) for post in last_30_days_posts]
        reactions = [self._safe_float(post.get("reactions_count")) for post in last_30_days_posts]
        posts_analyzed = len(last_30_days_posts)

        median_views = self._median(views)
        avg_views = self._mean(views)
        subscribers_count = profile["participants_count"]
        view_rate = 0.0 if not subscribers_count else (median_views / subscribers_count * 100)
        posts_per_week = self._safe_float(len(last_30_days_posts)) / 4.3
        cv = 0.0
        if avg_views > 0:
            cv = self._std(views) / avg_views
        median_reactions = self._median(reactions)
        reaction_rate = 0.0 if median_views <= 0 else (median_reactions / median_views * 100)
        median_forwards = self._median(forwards)
        forward_rate = 0.0 if median_views <= 0 else (median_forwards / median_views * 100)
        last_post_dt = self._parse_date_utc(last_30_days_posts[0].get("date"))

        view_rate_score = self._score_threshold(
            view_rate,
            [
                (20.0, 10.0),
                (10.0, 8.0),
                (5.0, 6.0),
                (2.0, 4.0),
                (0.01, 1.0),
            ],
        )
        posts_freq_score = self._score_threshold(
            posts_per_week,
            [
                (7.0, 10.0),
                (4.0, 8.0),
                (2.0, 6.0),
                (1.0, 4.0),
                (0.1, 2.0),
            ],
        )
        reaction_score = self._score_threshold(
            reaction_rate,
            [
                (10.0, 10.0),
                (6.0, 8.0),
                (3.0, 6.0),
                (1.0, 4.0),
                (0.01, 1.0),
            ],
        )
        forward_score = self._score_threshold(
            forward_rate,
            [
                (5.0, 10.0),
                (2.0, 8.0),
                (1.0, 6.0),
                (0.5, 4.0),
                (0.1, 2.0),
            ],
        )
        consistency_score = 0.0 if cv <= 0 else self._score_threshold(
            max(0.0, 100.0 - cv * 20.0),
            [
                (80.0, 10.0),
                (60.0, 8.0),
                (40.0, 6.0),
                (20.0, 4.0),
                (0.0, 2.0),
            ],
        )
        channel_health_score = (
            view_rate_score * 0.35
            + posts_freq_score * 0.25
            + reaction_score * 0.2
            + forward_score * 0.15
            + consistency_score * 0.05
        )

        payload = {
            "subscribers_count": subscribers_count,
            "posts_analyzed": posts_analyzed,
            "median_views_30": median_views,
            "avg_views_30": avg_views,
            "view_rate": view_rate,
            "posts_per_week": posts_per_week,
            "views_cv": cv,
            "median_reactions": median_reactions,
            "reaction_rate": reaction_rate,
            "median_forwards": median_forwards,
            "forward_rate": forward_rate,
            "last_post_at": self._safe_iso(last_post_dt),
        }
        self.channel_analytics_repo.upsert_channel_metrics(channel_username, payload)
        payload.update(
            {
                "success": True,
                "channel_id": channel_id,
                "channel_username": channel_username,
                "channel_health_score": round(channel_health_score, 2),
                "message": "Channel health пересчитан",
            }
        )
        return payload

    async def score_channel_discussion(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        profile = await self._refresh_channel_profile(channel_identifier, session_id=session_id)
        channel_username = profile["channel_username"]
        channel_id = profile["channel_id"]
        posts = self.channel_analytics_repo.list_channel_posts(channel_username=channel_username, limit=200)
        comments = self.channel_analytics_repo.list_channel_comments(channel_username=channel_username, limit=2000)

        comments_enabled = False
        try:
            comments_status = await self.get_channel_comments_status(
                channel_identifier,
                session_id=session_id,
            )
            comments_enabled = bool(comments_status.get("has_comments"))
        except Exception:
            comments_enabled = False

        if not posts:
            return {
                "success": False,
                "channel_id": channel_id,
                "channel_username": channel_username,
                "comments_enabled": comments_enabled,
                "posts_with_comments": 0,
                "median_comments_30": 0.0,
                "avg_comments_30": 0.0,
                "comment_rate": 0.0,
                "unique_commenters_30": 0,
                "author_replies_count": 0,
                "author_reply_rate": 0.0,
                "spam_comments_count": 0,
                "spam_ratio": 0.0,
                "discussion_score": 0.0,
                "message": "Недостаточно данных. Сначала соберите посты и комментарии.",
            }

        now = datetime.utcnow()
        cutoff_30 = now - timedelta(days=30)
        recent_posts = [
            post for post in posts
            if self._parse_date_utc(post.get("date")) and self._parse_date_utc(post.get("date")) >= cutoff_30
        ]
        if not recent_posts:
            recent_posts = posts[:min(len(posts), 30)]
        if not recent_posts:
            recent_posts = posts

        recent_post_ids = {
            self._safe_int(post.get("message_id"))
            for post in recent_posts
            if self._safe_int(post.get("message_id"), 0) > 0
        }
        post_comment_counts = []
        comments_by_post: Dict[int, List[Dict[str, Any]]] = {}
        relevant_comments = []
        for comment in comments:
            pid = self._safe_int(comment.get("post_message_id"))
            if pid in recent_post_ids:
                relevant_comments.append(comment)
                comments_by_post.setdefault(pid, []).append(comment)

        for post in recent_posts:
            pid = self._safe_int(post.get("message_id"))
            post_comment_counts.append(len(comments_by_post.get(pid, [])))

        posts_with_comments = len([count for count in post_comment_counts if count > 0])
        median_comments_30 = self._median([float(v) for v in post_comment_counts]) if post_comment_counts else 0.0
        avg_comments_30 = self._mean([float(v) for v in post_comment_counts]) if post_comment_counts else 0.0

        if not relevant_comments:
            comment_count = 0
            unique_commenters = 0
            author_reply_count = 0
            spam_count = 0
            comment_rate = 0.0
            author_reply_rate = 0.0
            spam_ratio = 0.0
            discussion_score = 0.0
        else:
            unique_commenters = len(
                {
                    item.get("commenter_id_hash")
                    for item in relevant_comments
                    if item.get("commenter_id_hash")
                }
            )
            author_reply_count = len(
                {
                    self._safe_int(item.get("post_message_id"))
                    for item in relevant_comments
                    if bool(item.get("is_author_reply"))
                }
            )
            spam_count = len([item for item in relevant_comments if bool(item.get("is_spam_like"))])
            total_comments = len(relevant_comments)
            metrics_payload = self.channel_analytics_repo.get_channel_metrics(channel_username) or {}
            median_views_30 = self._safe_float(metrics_payload.get("median_views"))

            comment_rate = 0.0 if median_views_30 <= 0 else (median_comments_30 / median_views_30 * 100)
            author_reply_rate = 0.0 if posts_with_comments <= 0 else (author_reply_count / posts_with_comments * 100)
            spam_ratio = 0.0 if total_comments <= 0 else (spam_count / total_comments * 100)

            comment_rate_score = self._score_threshold(
                comment_rate,
                [
                    (1.0, 10.0),
                    (0.3, 8.0),
                    (0.1, 5.0),
                    (0.01, 2.0),
                    (0.0, 0.0),
                ],
            )
            reply_score = self._score_threshold(
                author_reply_rate,
                [
                    (30.0, 10.0),
                    (15.0, 8.0),
                    (5.0, 6.0),
                    (1.0, 3.0),
                    (0.0, 1.0),
                ],
            )
            unique_ratio = min(10.0, unique_commenters / max(1, posts_with_comments) * 2.0)
            spam_score = max(0.0, 10.0 - spam_ratio)
            discussion_score = (
                comment_rate_score * 0.55
                + reply_score * 0.25
                + unique_ratio * 0.1
                + spam_score * 0.1
            )

            if not comments_enabled:
                discussion_score = 0.0

        payload = {
            "success": True,
            "channel_id": channel_id,
            "channel_username": channel_username,
            "comments_enabled": comments_enabled,
            "posts_with_comments": posts_with_comments,
            "median_comments_30": median_comments_30,
            "avg_comments_30": avg_comments_30,
            "comment_rate": self._safe_float(comment_rate),
            "unique_commenters_30": unique_commenters,
            "author_replies_count": author_reply_count,
            "author_reply_rate": self._safe_float(author_reply_rate),
            "spam_comments_count": spam_count,
            "spam_ratio": self._safe_float(spam_ratio),
            "discussion_score": self._safe_float(round(discussion_score, 2)),
            "message": "Discussion score пересчитан",
        }
        self.channel_analytics_repo.upsert_discussion_metrics(
            channel_username=channel_username,
            payload={
                "posts_with_comments": posts_with_comments,
                "median_comments_30": median_comments_30,
                "avg_comments_30": avg_comments_30,
                "comment_rate": self._safe_float(comment_rate),
                "unique_commenters_30": unique_commenters,
                "author_replies_count": author_reply_count,
                "author_reply_rate": self._safe_float(author_reply_rate),
                "spam_ratio": self._safe_float(spam_ratio),
                "discussion_score": self._safe_float(discussion_score),
                "comments_enabled": comments_enabled,
            },
        )
        return payload

    async def score_business_fit(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        profile = await self._refresh_channel_profile(channel_identifier, session_id=session_id)
        channel_username = profile["channel_username"]
        channel_id = profile["channel_id"]

        posts = self.channel_analytics_repo.list_channel_posts(channel_username=channel_username, limit=200)
        post_text = " ".join([str(item.get("text") or "") for item in posts[:30]])
        channel_text = " ".join(
            filter(
                None,
                [
                    str(profile.get("title") or ""),
                    str(profile.get("username") or ""),
                    str(profile.get("about") or ""),
                    post_text,
                ],
            )
        )

        niche_matches = self._collect_niche_signals(channel_text)
        monetization_matches = self._collect_monetization_signals(channel_text).split(", ") if channel_text else []
        pain_markers = self._collect_pain_markers(channel_text.lower())

        niche_fit_score = min(10.0, float(len(set(niche_matches)) * 2.0))
        monetization_signal_score = min(10.0, float(len(set(monetization_matches)) * 1.5))
        pain_markers_score = min(10.0, float(len(set(pain_markers)) * 1.5))

        ai_product_potential_score = min(
            10.0,
            niche_fit_score * 0.45 + monetization_signal_score * 0.3 + pain_markers_score * 0.25,
        )

        suggested_ai_product = None
        if "онлайн-школы" in niche_matches or "продажи" in niche_matches:
            suggested_ai_product = "AI-ассистент для лид-ответов и обработки комментариев"
        elif "фитнес" in niche_matches:
            suggested_ai_product = "AI-бот прогрева и персональной коммуникации"
        elif "карьера" in niche_matches or "английский" in niche_matches:
            suggested_ai_product = "AI-тренажер для ответа на частые вопросы и отбора лидов"
        elif "психология" in niche_matches:
            suggested_ai_product = "AI-скрипт прогрева для психологических ниш"

        if monetization_matches:
            monetization_preview = ", ".join(sorted(set(monetization_matches))[:3])
            reason = (
                f"Ниша: {', '.join(niche_matches) or 'неявная'}, "
                f"монетизация: {monetization_preview}, "
                f"pain-маркеры: {len(pain_markers)}"
            )
        else:
            reason = "Нужны доп.сигналы по монетизации и нише"

        business_fit_score = min(
            10.0,
            (niche_fit_score * 0.45)
            + (monetization_signal_score * 0.35)
            + (pain_markers_score * 0.2),
        )

        self.channel_analytics_repo.upsert_campaign_score(
            channel_username=channel_username,
            payload={
                "niche_fit_score": niche_fit_score,
                "monetization_signal_score": monetization_signal_score,
                "audience_attention_score": 0.0,
                "discussion_score": 0.0,
                "business_fit_score": business_fit_score,
                "campaign_score": 0.0,
                "recommended_action": "manual_review",
                "reason": reason,
                "suggested_ai_product": suggested_ai_product,
            },
        )

        return {
            "success": True,
            "channel_id": channel_id,
            "channel_username": channel_username,
            "niche_fit_score": niche_fit_score,
            "monetization_signal_score": monetization_signal_score,
            "pain_markers_score": pain_markers_score,
            "ai_product_potential_score": ai_product_potential_score,
            "business_fit_score": business_fit_score,
            "reason": reason,
            "suggested_ai_product": suggested_ai_product,
        }

    async def score_campaign(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        health = await self.score_channel_health(channel_identifier, session_id=session_id)
        discussion = await self.score_channel_discussion(channel_identifier, session_id=session_id)
        business = await self.score_business_fit(channel_identifier, session_id=session_id)

        view_rate = self._safe_float(health.get("view_rate"))
        median_views = self._safe_float(health.get("median_views_30"))
        comments_enabled = bool(discussion.get("comments_enabled"))
        comment_rate = self._safe_float(discussion.get("comment_rate"))
        posts_analyzed = self._safe_int(health.get("posts_analyzed"), 0)

        profile = await self._refresh_channel_profile(channel_identifier, session_id=session_id)
        channel_username = profile["channel_username"]
        channel_id = profile["channel_id"]
        metrics = self.channel_analytics_repo.get_channel_metrics(channel_username=channel_username) or {}

        view_rate_score = self._score_threshold(
            view_rate,
            [
                (20.0, 10.0),
                (10.0, 8.0),
                (5.0, 6.0),
                (2.0, 4.0),
                (0.01, 1.0),
            ],
        )
        median_views_score = self._score_threshold(
            median_views,
            [
                (5000.0, 10.0),
                (1000.0, 8.0),
                (300.0, 6.0),
                (100.0, 4.0),
                (0.01, 1.0),
            ],
        )
        comments_enabled_score = 10.0 if comments_enabled else 0.0
        comment_rate_score = self._score_threshold(
            comment_rate,
            [
                (1.0, 10.0),
                (0.3, 8.0),
                (0.1, 5.0),
                (0.01, 2.0),
                (0.0, 0.0),
            ],
        )

        niche_fit_score = self._safe_float(business.get("niche_fit_score"))
        monetization_signal_score = self._safe_float(business.get("monetization_signal_score"))
        campaign_score = (
            view_rate_score * 0.20
            + median_views_score * 0.15
            + comments_enabled_score * 0.15
            + comment_rate_score * 0.15
            + niche_fit_score * 0.20
            + monetization_signal_score * 0.15
        )
        campaign_score = round(campaign_score, 2)
        campaign_score_float = campaign_score

        recommendation = "manual_review"
        if (campaign_score >= 8.0 and comments_enabled and median_views >= 100 and niche_fit_score >= 7.0):
            recommendation = "test_now"
        elif campaign_score >= 6.5 and campaign_score < 8.0:
            recommendation = "watch"

        if (
            campaign_score < 6.5
            or not comments_enabled
            or niche_fit_score < 5.0
            or posts_analyzed < 3
            or self._safe_float(metrics.get("avg_views")) == 0
        ):
            recommendation = "skip" if campaign_score < 6.5 or not comments_enabled else "watch"

        if recommendation == "watch" and (health.get("success") is False or discussion.get("success") is False):
            recommendation = "manual_review"

        reason = (
            f"lead-score: vr={view_rate_score:.1f}, mv={median_views_score:.1f}, "
            f"c_en={comments_enabled_score:.1f}, cr={comment_rate_score:.1f}, "
            f"niche={niche_fit_score:.1f}, monet={monetization_signal_score:.1f}"
        )

        self.channel_analytics_repo.upsert_campaign_score(
            channel_username=channel_username,
            payload={
                "niche_fit_score": niche_fit_score,
                "monetization_signal_score": monetization_signal_score,
                "audience_attention_score": median_views_score,
                "discussion_score": self._safe_float(discussion.get("discussion_score")),
                "business_fit_score": self._safe_float(business.get("business_fit_score")),
                "campaign_score": campaign_score,
                "recommended_action": recommendation,
                "reason": reason,
                "suggested_ai_product": business.get("suggested_ai_product"),
            },
        )

        return {
            "success": True,
            "channel_id": channel_id,
            "channel_username": channel_username,
            "lead_score": campaign_score_float,
            "campaign_score": campaign_score_float,
            "recommended_action": recommendation,
            "reason": reason,
            "niche_fit_score": niche_fit_score,
            "monetization_signal_score": monetization_signal_score,
            "audience_attention_score": median_views_score,
            "comments_enabled_score": comments_enabled_score,
            "comment_rate_score": comment_rate_score,
            "median_views_score": median_views_score,
            "view_rate_score": view_rate_score,
            "discussion_score": self._safe_float(discussion.get("discussion_score")),
            "business_fit_score": self._safe_float(business.get("business_fit_score")),
        }

    async def refresh_channel_metrics(self, channel_identifier: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        collect_posts = await self.collect_channel_posts(
            channel_identifier=channel_identifier,
            limit=60,
            session_id=session_id,
        )
        collect_comments = await self.collect_channel_comments(
            channel_identifier=channel_identifier,
            posts_limit=25,
            comments_per_post=60,
            session_id=session_id,
        )
        health = await self.score_channel_health(channel_identifier=channel_identifier, session_id=session_id)
        discussion = await self.score_channel_discussion(channel_identifier=channel_identifier, session_id=session_id)
        business = await self.score_business_fit(channel_identifier=channel_identifier, session_id=session_id)
        campaign = await self.score_campaign(channel_identifier=channel_identifier, session_id=session_id)
        opportunities = await self.opportunity_posts(
            channel_identifier=channel_identifier,
            limit=20,
            session_id=session_id,
        )

        return {
            "success": True,
            "channel_id": collect_posts["channel_id"],
            "channel_username": collect_posts["channel_username"],
            "posts_collected": collect_posts["posts_analyzed"],
            "comments_collected": collect_comments["total_comments"],
            "health": health,
            "discussion": discussion,
            "business": business,
            "campaign": campaign,
            "opportunities_count": opportunities["total"],
            "message": "Полный пересчёт метрик завершен",
        }

    async def opportunity_posts(
        self,
        channel_identifier: str,
        limit: int = 20,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.channel_analytics_repo is None:
            raise ValueError("ChannelAnalyticsRepo не инициализирован")

        profile = await self._refresh_channel_profile(channel_identifier, session_id=session_id)
        channel_username = profile["channel_username"]
        channel_id = profile["channel_id"]
        posts = self.channel_analytics_repo.list_channel_posts(channel_username=channel_username, limit=200)
        comments = self.channel_analytics_repo.list_channel_comments(channel_username=channel_username, limit=5000)

        if not posts:
            return {
                "success": False,
                "channel_id": channel_id,
                "channel_username": channel_username,
                "posts": [],
                "total": 0,
                "message": "Недостаточно данных. Сначала соберите посты.",
            }

        posts_comment_map: Dict[int, List[Dict[str, Any]]] = {}
        for comment in comments:
            posts_comment_map.setdefault(self._safe_int(comment.get("post_message_id")), []).append(comment)

        now = datetime.utcnow()
        scored_posts: List[Dict[str, Any]] = []
        for post in posts[: max(limit * 3, 1)]:
            msg_id = self._safe_int(post.get("message_id"))
            text = str(post.get("text") or "")
            post_date = self._parse_date_utc(post.get("date"))
            post_comments = posts_comment_map.get(msg_id, [])
            comments_count = len(post_comments)

            recency_days = 30.0
            if post_date:
                recency_days = max(1.0, (now - post_date).days + 1)
            recency_score = max(0.0, 10.0 - recency_days / 3.0)

            relevance_score = 0.0
            pain_markers = self._collect_pain_markers(text.lower())
            niche_terms = self._collect_niche_signals((profile.get("title") or "") + " " + text.lower())
            ai_terms = self._collect_monetization_signals((profile.get("about") or "") + " " + text.lower()).split(", ")
            relevance_score = min(
                10.0,
                len(set(niche_terms)) * 1.8 + (2.0 if set(ai_terms) & {"ai", "искусственный"} else 0.0) + 1.0,
            )

            views = max(0.0, self._safe_float(post.get("views"), 0.0))
            views_score = self._score_threshold(
                views,
                [
                    (5000.0, 10.0),
                    (1000.0, 8.0),
                    (300.0, 6.0),
                    (100.0, 4.0),
                    (0.01, 1.0),
                ],
            )
            comment_score = self._score_threshold(
                comments_count,
                [
                    (50.0, 10.0),
                    (20.0, 8.0),
                    (10.0, 6.0),
                    (5.0, 4.0),
                    (0.0, 1.0),
                ],
            )
            spam_ratio = 0.0
            spam_count = len([c for c in post_comments if bool(c.get("is_spam_like"))])
            if comments_count > 0:
                spam_ratio = spam_count / comments_count * 100.0
            spam_score = max(0.0, 10.0 - spam_ratio)
            post_relevance_score = min(10.0, (relevance_score + views_score + comment_score + recency_score) / 4.0)
            opportunity_score = round(
                post_relevance_score * 0.55
                + (10.0 - min(10.0, spam_ratio)) * 0.2
                + views_score * 0.2
                + (6.0 if pain_markers else 1.0) * 0.05,
                2,
            )

            suggested_angle = "Выпустить полезный комментарий с практическим кейсом в этой теме."
            if pain_markers:
                suggested_angle = (
                    f"Ответь по pain-point: {pain_markers[0].strip()} с конкретным шагом внедрения AI."
                )
            elif niche_terms:
                suggested_angle = f"Подстройся под нишу: {niche_terms[0]} и предложи мини-аудит в комменте."

            scored_posts.append(
                {
                    "channel_id": channel_id,
                    "channel_username": channel_username,
                    "post_url": post.get("post_url"),
                    "message_id": msg_id,
                    "date": post.get("date"),
                    "text_preview": text[:220] if text else None,
                    "views": self._safe_int(post.get("views"), 0),
                    "comments_count": comments_count,
                    "reactions_count": self._safe_int(post.get("reactions_count"), 0),
                    "post_relevance_score": round(post_relevance_score, 2),
                    "pain_markers": ", ".join(sorted(set(pain_markers))) or None,
                    "opportunity_score": opportunity_score,
                    "suggested_angle": suggested_angle,
                }
            )

        scored_posts.sort(key=lambda item: item["opportunity_score"], reverse=True)
        top_posts = scored_posts[: limit]
        self.channel_analytics_repo.upsert_opportunity_posts(channel_username=channel_username, posts=top_posts)

        return {
            "success": True,
            "channel_id": channel_id,
            "channel_username": channel_username,
            "posts": top_posts,
            "total": len(top_posts),
        }

    async def subscribe_channel(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Подписывает текущий аккаунт на канал.

        Args:
            channel_identifier: Username канала (@channel) или ID канала

        Returns:
            Результат подписки
        """
        result = await self.join_channel(channel_identifier, session_id=session_id)
        return {
            "success": result["success"],
            "channel_id": result.get("channel_id"),
            "message": result["message"],
        }

    async def unsubscribe_channel(
        self,
        channel_identifier: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Отписывает текущий аккаунт от канала.

        Args:
            channel_identifier: Username канала (@channel) или ID канала

        Returns:
            Результат отписки
        """
        client = await self._get_session_client(session_id)

        try:
            entity = await client.get_entity(self._normalize_channel_identifier(channel_identifier))
            if not isinstance(entity, Channel):
                raise ValueError("Указанный идентификатор не является каналом")

            await client(functions.channels.LeaveChannelRequest(channel=entity))
            return {
                "success": True,
                "channel_id": self._channel_api_id(entity),
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

    async def upsert_lead_search_folder(
        self,
        channel_identifiers: List[str],
        folder_name: str = "Lead Search 1",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Создает или обновляет Telegram-папку и добавляет туда каналы."""
        client = await self._get_session_client(session_id)
        target_folder_name = folder_name.strip() or "Lead Search 1"

        try:
            filters_result = await client(functions.messages.GetDialogFiltersRequest())
            filters = self._dialog_filters_from_result(filters_result)
            existing_filter = None
            used_ids: set[int] = set()
            for dialog_filter in filters:
                filter_id = getattr(dialog_filter, "id", None)
                if isinstance(filter_id, int):
                    used_ids.add(filter_id)
                if self._dialog_filter_title(dialog_filter).lower() == target_folder_name.lower():
                    existing_filter = dialog_filter

            if existing_filter is not None:
                folder_id = int(existing_filter.id)
                pinned_peers = list(getattr(existing_filter, "pinned_peers", []) or [])
                include_peers = list(getattr(existing_filter, "include_peers", []) or [])
                exclude_peers = list(getattr(existing_filter, "exclude_peers", []) or [])
                contacts = getattr(existing_filter, "contacts", None)
                non_contacts = getattr(existing_filter, "non_contacts", None)
                groups = getattr(existing_filter, "groups", None)
                broadcasts = getattr(existing_filter, "broadcasts", None)
                bots = getattr(existing_filter, "bots", None)
                exclude_muted = getattr(existing_filter, "exclude_muted", None)
                exclude_read = getattr(existing_filter, "exclude_read", None)
                exclude_archived = getattr(existing_filter, "exclude_archived", None)
                emoticon = getattr(existing_filter, "emoticon", None)
            else:
                folder_id = next((candidate for candidate in range(2, 101) if candidate not in used_ids), 2)
                pinned_peers = []
                include_peers = []
                exclude_peers = []
                contacts = None
                non_contacts = None
                groups = None
                broadcasts = True
                bots = None
                exclude_muted = None
                exclude_read = None
                exclude_archived = None
                emoticon = None

            existing_peer_keys = {self._input_peer_key(peer) for peer in include_peers}
            added: List[Dict[str, Any]] = []
            skipped: List[str] = []

            for identifier in channel_identifiers:
                try:
                    entity = await client.get_entity(self._normalize_channel_identifier(identifier))
                    if not isinstance(entity, Channel):
                        skipped.append(identifier)
                        continue
                    input_peer = await client.get_input_entity(entity)
                    peer_key = self._input_peer_key(input_peer)
                    if peer_key not in existing_peer_keys:
                        include_peers.append(input_peer)
                        existing_peer_keys.add(peer_key)
                    added.append(self._chat_info_from_entity(entity))
                except Exception:
                    skipped.append(identifier)

            if not added and existing_filter is None:
                raise ValueError("Не найдено ни одного доступного канала для новой папки")

            dialog_filter = types.DialogFilter(
                id=folder_id,
                title=target_folder_name,
                pinned_peers=pinned_peers,
                include_peers=include_peers,
                exclude_peers=exclude_peers,
                contacts=contacts,
                non_contacts=non_contacts,
                groups=groups,
                broadcasts=broadcasts,
                bots=bots,
                exclude_muted=exclude_muted,
                exclude_read=exclude_read,
                exclude_archived=exclude_archived,
                emoticon=emoticon,
            )
            await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=dialog_filter))
            return {
                "success": True,
                "folder_name": target_folder_name,
                "folder_id": folder_id,
                "added": added,
                "skipped": skipped,
                "total_added": len(added),
                "message": "Папка обновлена",
            }
        except FloodWaitError as e:
            raise ValueError(f"Слишком много запросов. Попробуйте через {e.seconds} секунд")
        except RPCError as e:
            raise ValueError(f"Ошибка Telegram API: {e.message}")
        except Exception as e:
            raise ValueError(f"Ошибка обновления папки: {str(e)}")
    
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
        for client in list(self._clients.values()):
            await client.disconnect()
        for client in list(self._auth_clients.values()):
            await client.disconnect()
        self._clients.clear()
        self._auth_clients.clear()
        self._authorized_sessions.clear()
    
    def is_connected(self, session_id: Optional[str] = None) -> bool:
        """Проверяет, авторизована ли сессия."""
        sid = self._normalize_session_id(session_id)
        if sid in self._authorized_sessions:
            return True

        row = self._get_session_repo().get(sid)
        if row and row.get("is_authorized") and row.get("string_session"):
            self._authorized_sessions.add(sid)
            return True

        return False
    
