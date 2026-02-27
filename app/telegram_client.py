import asyncio
import base64
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from telethon import TelegramClient
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
from app.config import API_ID, API_HASH, SESSIONS_DIR, SESSION_NAME


class TelegramClientManager:
    """Менеджер для управления Telethon клиентом"""
    
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.phone_code_hash: Optional[str] = None
        self.phone: Optional[str] = None
        self._is_connected = False
        self._qr_login_token: Optional[bytes] = None
        self._qr_expires_at: Optional[int] = None
    
    async def init_client(self) -> bool:
        """
        Инициализирует клиент и проверяет существующую сессию.
        Возвращает True если авторизация успешна, False если нужна авторизация.
        """
        if not API_ID or not API_HASH:
            raise ValueError("API_ID и API_HASH должны быть установлены")
        
        session_path = SESSIONS_DIR / SESSION_NAME
        
        self.client = TelegramClient(
            str(session_path),
            int(API_ID),
            API_HASH
        )
        
        await self.client.connect()
        
        if await self.client.is_user_authorized():
            self._is_connected = True
            return True
        
        return False
    
    async def send_code(self, phone: str, force_sms: bool = False) -> Dict[str, Any]:
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
        
        if not self.client:
            await self.init_client()
        
        try:
            logger.info(f"Отправка кода на номер: {phone}")
            self.phone = phone
            
            # Примечание: force_sms больше не работает в Telegram API
            # Telegram сам решает, как отправить код (обычно через приложение)
            result = await self.client.send_code_request(phone)
            self.phone_code_hash = result.phone_code_hash
            
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
    
    async def sign_in(self, phone: str, code: str) -> Dict[str, Any]:
        """
        Вход с кодом подтверждения.
        
        Args:
            phone: Номер телефона
            code: Код подтверждения из Telegram
        
        Returns:
            Статус авторизации
        """
        if not self.client:
            await self.init_client()
        
        if not self.phone_code_hash:
            raise ValueError("Сначала вызовите /auth/login")
        
        try:
            await self.client.sign_in(phone, code, phone_code_hash=self.phone_code_hash)
            self._is_connected = True
            self.phone_code_hash = None
            
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
    
    async def sign_in_password(self, password: str) -> Dict[str, Any]:
        """
        Вход с паролем двухфакторной аутентификации.
        
        Args:
            password: Пароль 2FA
        
        Returns:
            Статус авторизации
        """
        if not self.client:
            await self.init_client()
        
        try:
            await self.client.sign_in(password=password)
            self._is_connected = True
            
            return {
                "success": True,
                "message": "Авторизация успешна"
            }
        except RPCError as e:
            raise ValueError(f"Неверный пароль или ошибка: {e.message}")
    
    async def get_dialogs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получает список всех диалогов (чатов).
        
        Args:
            limit: Максимальное количество диалогов
        
        Returns:
            Список словарей с информацией о чатах
        """
        if not self.client:
            await self.init_client()
        
        if not self._is_connected:
            raise ValueError("Необходима авторизация")
        
        dialogs = []
        async for dialog in self.client.iter_dialogs(limit=limit):
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
    
    async def send_message(self, chat_identifier: str, message: str) -> Dict[str, Any]:
        """
        Отправляет сообщение в чат.
        
        Args:
            chat_identifier: Username чата (например, @username) или ID чата
            message: Текст сообщения
        
        Returns:
            Информация об отправленном сообщении
        """
        if not self.client:
            await self.init_client()
        
        if not self._is_connected:
            raise ValueError("Необходима авторизация")
        
        try:
            sent_message = await self.client.send_message(chat_identifier, message)
            
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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()
        
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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()
        
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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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

    async def subscribe_channel(self, channel_identifier: str) -> Dict[str, Any]:
        """
        Подписывает текущий аккаунт на канал.

        Args:
            channel_identifier: Username канала (@channel) или ID канала

        Returns:
            Результат подписки
        """
        if not self.client:
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()

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
            await self.init_client()
        
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
            await self.init_client()
        
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
        if self.client:
            await self.client.disconnect()
            self._is_connected = False
    
    def is_connected(self) -> bool:
        """Проверяет, авторизован ли клиент"""
        return self._is_connected
    
    async def generate_qr_code(self) -> Dict[str, Any]:
        """
        Генерирует QR-код для авторизации через сканирование.
        
        Returns:
            Словарь с QR-кодом URL и данными для отображения
        """
        import logging
        import time
        logger = logging.getLogger(__name__)
        
        if not self.client:
            await self.init_client()
        
        try:
            logger.info("Генерация QR-кода для авторизации...")
            
            # Вызываем exportLoginToken
            result = await self.client(functions.auth.ExportLoginTokenRequest(
                api_id=int(API_ID),
                api_hash=API_HASH,
                except_ids=[]
            ))
            
            # Проверяем тип результата
            if isinstance(result, types.auth.LoginToken):
                # Успешно получили токен
                token = result.token
                expires = result.expires
                
                # Обрабатываем expires (может быть int или datetime)
                if isinstance(expires, datetime):
                    # Если это datetime, вычисляем разницу в секундах
                    # Используем timestamp для корректного сравнения с timezone
                    expires_timestamp = int(expires.timestamp())
                    current_timestamp = int(time.time())
                    expires_seconds = expires_timestamp - current_timestamp
                else:
                    # Если это int (количество секунд)
                    expires_seconds = int(expires)
                    expires_timestamp = int(time.time()) + expires_seconds
                
                self._qr_login_token = token
                self._qr_expires_at = expires_timestamp
                
                # Кодируем токен в base64url
                token_b64 = base64.urlsafe_b64encode(token).decode('utf-8').rstrip('=')
                
                # Создаем URL для QR-кода
                qr_url = f"tg://login?token={token_b64}"
                
                logger.info(f"QR-код сгенерирован. Истекает через {expires_seconds} секунд")
                
                return {
                    "success": True,
                    "qr_url": qr_url,
                    "qr_code_data": token_b64,
                    "expires_in": expires_seconds,
                    "message": f"QR-код сгенерирован. Отсканируйте его в Telegram приложении. Действителен {expires_seconds} секунд."
                }
            elif isinstance(result, types.auth.LoginTokenSuccess):
                # Уже авторизован!
                logger.info("Уже авторизован через QR-код")
                self._is_connected = True
                return {
                    "success": True,
                    "authorized": True,
                    "message": "Авторизация успешна через QR-код"
                }
            else:
                logger.error(f"Неожиданный тип результата: {type(result)}")
                raise ValueError(f"Неожиданный ответ от сервера: {type(result)}")
                
        except RPCError as e:
            logger.error(f"Ошибка Telegram API при генерации QR-кода: {e.message}")
            raise ValueError(f"Ошибка Telegram API: {e.message}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при генерации QR-кода: {e}", exc_info=True)
            raise ValueError(f"Ошибка при генерации QR-кода: {str(e)}")
    
    async def check_qr_status(self) -> Dict[str, Any]:
        """
        Проверяет статус QR-кода авторизации.
        Должен вызываться периодически после генерации QR-кода.
        
        Returns:
            Статус авторизации
        """
        import logging
        import time
        logger = logging.getLogger(__name__)
        
        if not self.client:
            await self.init_client()
        
        # Сначала проверяем, не авторизованы ли мы уже
        # Переподключаемся для обновления состояния
        if self.client:
            await self.client.disconnect()
            await self.client.connect()
        
        if await self.client.is_user_authorized():
            logger.info("Клиент уже авторизован")
            self._is_connected = True
            self._qr_login_token = None
            self._qr_expires_at = None
            return {
                "success": True,
                "authorized": True,
                "message": "Авторизация успешна через QR-код"
            }
        
        if not self._qr_login_token:
            raise ValueError("Сначала вызовите /auth/qr/generate")
        
        # Проверяем, не истек ли токен
        if self._qr_expires_at and int(time.time()) >= self._qr_expires_at:
            raise ValueError("QR-код истек. Сгенерируйте новый через /auth/qr/generate")
        
        try:
            # Вызываем exportLoginToken снова для проверки статуса
            result = await self.client(functions.auth.ExportLoginTokenRequest(
                api_id=int(API_ID),
                api_hash=API_HASH,
                except_ids=[]
            ))
            
            if isinstance(result, types.auth.LoginTokenSuccess):
                # Успешная авторизация!
                logger.info("QR-код авторизация успешна")
                # Проверяем авторизацию еще раз для уверенности
                if await self.client.is_user_authorized():
                    # Сохраняем сессию явно
                    await self.client.disconnect()
                    await self.client.connect()
                    # Проверяем еще раз после переподключения
                    if await self.client.is_user_authorized():
                        self._is_connected = True
                        self._qr_login_token = None
                        self._qr_expires_at = None
                        
                        return {
                            "success": True,
                            "authorized": True,
                            "message": "Авторизация успешна через QR-код"
                        }
                else:
                    logger.warning("LoginTokenSuccess получен, но is_user_authorized() вернул False")
                    return {
                        "success": False,
                        "authorized": False,
                        "message": "QR-код принят, но авторизация еще не завершена. Попробуйте еще раз через несколько секунд."
                    }
            elif isinstance(result, types.auth.LoginTokenMigrateTo):
                # Нужно мигрировать на другой DC
                logger.info(f"Миграция на DC {result.dc_id}")
                token = result.token
                
                # Импортируем токен на новый DC
                import_result = await self.client(functions.auth.ImportLoginTokenRequest(token))
                
                if isinstance(import_result, types.auth.LoginTokenSuccess):
                    logger.info("Миграция и авторизация успешны")
                    # Сохраняем сессию явно
                    await self.client.disconnect()
                    await self.client.connect()
                    # Проверяем авторизацию
                    if await self.client.is_user_authorized():
                        self._is_connected = True
                        self._qr_login_token = None
                        self._qr_expires_at = None
                        
                        return {
                            "success": True,
                            "authorized": True,
                            "message": "Авторизация успешна через QR-код (после миграции)"
                        }
                    else:
                        logger.warning("ImportLoginToken успешен, но is_user_authorized() вернул False")
                        return {
                            "success": False,
                            "authorized": False,
                            "message": "Миграция завершена, но авторизация еще не завершена. Попробуйте еще раз."
                        }
                else:
                    raise ValueError(f"Ошибка при импорте токена: {type(import_result)}")
            elif isinstance(result, types.auth.LoginToken):
                # Токен еще не принят, но проверяем авторизацию на всякий случай
                if await self.client.is_user_authorized():
                    logger.info("Обнаружена авторизация при проверке статуса")
                    self._is_connected = True
                    self._qr_login_token = None
                    self._qr_expires_at = None
                    return {
                        "success": True,
                        "authorized": True,
                        "message": "Авторизация успешна через QR-код"
                    }
                else:
                    return {
                        "success": False,
                        "authorized": False,
                        "message": "QR-код еще не отсканирован. Продолжайте сканирование."
                    }
            else:
                raise ValueError(f"Неожиданный ответ: {type(result)}")
                
        except RPCError as e:
            error_msg = str(e.message)
            if "AUTH_TOKEN_EXPIRED" in error_msg:
                raise ValueError("QR-код истек. Сгенерируйте новый через /auth/qr/generate")
            elif "AUTH_TOKEN_INVALID" in error_msg:
                raise ValueError("QR-код недействителен. Сгенерируйте новый")
            elif "AUTH_TOKEN_ALREADY_ACCEPTED" in error_msg:
                # Токен уже принят, проверяем авторизацию
                logger.info("Токен уже принят, проверяем авторизацию")
                # Переподключаемся для обновления состояния
                await self.client.disconnect()
                await self.client.connect()
                if await self.client.is_user_authorized():
                    self._is_connected = True
                    self._qr_login_token = None
                    self._qr_expires_at = None
                    return {
                        "success": True,
                        "authorized": True,
                        "message": "Авторизация успешна"
                    }
                else:
                    # Возможно, нужно подождать немного
                    logger.warning("Токен принят, но авторизация еще не завершена")
                    return {
                        "success": False,
                        "authorized": False,
                        "message": "QR-код принят, но авторизация еще не завершена. Попробуйте еще раз через несколько секунд."
                    }
            else:
                logger.error(f"Ошибка Telegram API: {e.message}")
                raise ValueError(f"Ошибка Telegram API: {e.message}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при проверке QR-кода: {e}", exc_info=True)
            raise ValueError(f"Ошибка при проверке QR-кода: {str(e)}")


# Глобальный экземпляр менеджера
client_manager = TelegramClientManager()
