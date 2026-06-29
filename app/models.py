from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class LoginRequest(BaseModel):
    """Запрос на авторизацию по номеру телефона"""
    phone: str = Field(..., description="Номер телефона в международном формате (например, +79991234567)")
    force_sms: bool = Field(False, description="⚠️ Устаревший параметр: Telegram больше не поддерживает принудительную отправку по SMS. Код будет отправлен в Telegram приложение.")
    
    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith('+'):
            raise ValueError('Номер телефона должен начинаться с +')
        if len(v) < 10:
            raise ValueError('Номер телефона слишком короткий')
        return v


class LoginResponse(BaseModel):
    """Ответ на запрос авторизации"""
    success: bool
    phone_code_hash: Optional[str] = None
    message: str


class VerifyRequest(BaseModel):
    """Запрос на подтверждение кода"""
    phone: str = Field(..., description="Номер телефона")
    code: str = Field(..., description="Код подтверждения из Telegram", min_length=5, max_length=10)
    
    @field_validator('code')
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError('Код должен содержать только цифры')
        return v


class VerifyResponse(BaseModel):
    """Ответ на подтверждение кода"""
    success: bool
    password_required: Optional[bool] = False
    message: str


class PasswordRequest(BaseModel):
    """Запрос на ввод пароля 2FA"""
    password: str = Field(..., description="Пароль двухфакторной аутентификации", min_length=1)


class PasswordResponse(BaseModel):
    """Ответ на ввод пароля"""
    success: bool
    message: str


class SessionInfo(BaseModel):
    """Информация о сессии"""
    session_id: str
    phone: Optional[str] = None
    is_authorized: bool
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Ответ со списком сессий"""
    success: bool
    sessions: List[SessionInfo]
    total: int


class SessionStatusResponse(BaseModel):
    """Ответ со статусом одной сессии"""
    success: bool
    session: Optional[SessionInfo] = None
    message: str


class DeleteSessionResponse(BaseModel):
    """Ответ на удаление сессии"""
    success: bool
    session_id: str
    message: str


class ChatInfo(BaseModel):
    """Информация о чате"""
    id: int
    name: str
    type: Optional[str] = None  # user, group, channel, supergroup
    username: Optional[str] = None
    unread_count: int = 0
    is_pinned: bool = False
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False


class ChatDetailsInfo(BaseModel):
    """Расширенная информация о чате"""
    id: int
    type: str
    name: str
    username: Optional[str] = None
    description: Optional[str] = None
    participants_count: Optional[int] = None
    has_photo: bool = False
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    is_megagroup: Optional[bool] = None
    is_broadcast: Optional[bool] = None


class ChatsResponse(BaseModel):
    """Ответ со списком чатов"""
    success: bool
    chats: List[ChatInfo]
    total: int


class SendMessageRequest(BaseModel):
    """Запрос на отправку сообщения"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    message: str = Field(..., description="Текст сообщения", min_length=1, max_length=4096)
    
    @field_validator('chat_identifier')
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('Идентификатор чата не может быть пустым')
        return v


class SendMediaRequest(BaseModel):
    """Запрос на отправку медиафайла"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    file_base64: str = Field(..., description="Файл в base64 (можно с data URL префиксом)")
    file_name: str = Field(..., description="Имя файла с расширением (например, photo.jpg)")
    caption: Optional[str] = Field(None, description="Подпись к медиа", max_length=1024)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Идентификатор чата не может быть пустым")
        return value

    @field_validator("file_base64", "file_name")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("caption")
    @classmethod
    def validate_caption(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class SendMessageResponse(BaseModel):
    """Ответ на отправку сообщения"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class SendMediaResponse(BaseModel):
    """Ответ на отправку медиафайла"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class SendVoiceRequest(BaseModel):
    """Запрос на отправку голосового сообщения"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    voice_base64: str = Field(..., description="Голосовое сообщение в base64 (обычно .ogg/.opus)")
    file_name: str = Field(..., description="Имя файла (например, voice.ogg)")
    caption: Optional[str] = Field(None, description="Подпись к голосовому (опционально)", max_length=1024)

    @field_validator("chat_identifier", "voice_base64", "file_name")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("caption")
    @classmethod
    def validate_caption(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class SendVoiceResponse(BaseModel):
    """Ответ на отправку голосового сообщения"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class SendStickerGifRequest(BaseModel):
    """Запрос на отправку стикера или GIF"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    media_kind: str = Field(..., description="Тип медиа: sticker или gif")
    file_base64: str = Field(..., description="Файл в base64")
    file_name: str = Field(..., description="Имя файла (например, sticker.webp или animation.gif)")
    emoji: Optional[str] = Field(None, description="Emoji для стикера (опционально)", max_length=16)
    caption: Optional[str] = Field(None, description="Подпись (обычно для gif)", max_length=1024)

    @field_validator("chat_identifier", "file_base64", "file_name")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("media_kind")
    @classmethod
    def validate_media_kind(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"sticker", "gif"}:
            raise ValueError("media_kind должен быть 'sticker' или 'gif'")
        return value

    @field_validator("emoji", "caption")
    @classmethod
    def validate_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class SendStickerGifResponse(BaseModel):
    """Ответ на отправку стикера/GIF"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class SendLocationRequest(BaseModel):
    """Запрос на отправку геолокации"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    latitude: float = Field(..., description="Широта", ge=-90.0, le=90.0)
    longitude: float = Field(..., description="Долгота", ge=-180.0, le=180.0)
    caption: Optional[str] = Field(None, description="Подпись к геолокации (опционально)", max_length=1024)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("chat_identifier не может быть пустым")
        return value

    @field_validator("caption")
    @classmethod
    def validate_caption(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class SendLocationResponse(BaseModel):
    """Ответ на отправку геолокации"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class SendContactMessageRequest(BaseModel):
    """Запрос на отправку контакта сообщением"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    phone_number: str = Field(..., description="Телефон контакта")
    first_name: str = Field(..., description="Имя контакта", min_length=1, max_length=64)
    last_name: Optional[str] = Field(None, description="Фамилия контакта", max_length=64)
    caption: Optional[str] = Field(None, description="Подпись к контакту (опционально)", max_length=1024)

    @field_validator("chat_identifier", "phone_number", "first_name")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("last_name", "caption")
    @classmethod
    def validate_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class SendContactMessageResponse(BaseModel):
    """Ответ на отправку контакта"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class EditMessageRequest(BaseModel):
    """Запрос на редактирование сообщения"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    message_id: int = Field(..., description="ID сообщения для редактирования", gt=0)
    message: str = Field(..., description="Новый текст сообщения", min_length=1, max_length=4096)

    @field_validator('chat_identifier')
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('Идентификатор чата не может быть пустым')
        return v


class EditMessageResponse(BaseModel):
    """Ответ на редактирование сообщения"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class DeleteMessagesRequest(BaseModel):
    """Запрос на удаление сообщений"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    message_ids: List[int] = Field(..., description="Список ID сообщений для удаления", min_length=1)
    revoke: bool = Field(
        True,
        description="True: удалить для всех (если доступно), False: удалить только у себя",
    )

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids(cls, v: List[int]) -> List[int]:
        if any(message_id <= 0 for message_id in v):
            raise ValueError("Все ID сообщений должны быть положительными")
        return v


class DeleteMessagesResponse(BaseModel):
    """Ответ на удаление сообщений"""
    success: bool
    deleted_count: int
    message: str


class ForwardMessagesRequest(BaseModel):
    """Запрос на пересылку сообщений"""
    from_chat_identifier: str = Field(..., description="Источник: username (@username) или ID чата")
    to_chat_identifier: str = Field(..., description="Назначение: username (@username) или ID чата")
    message_ids: List[int] = Field(..., description="Список ID сообщений для пересылки", min_length=1)

    @field_validator("from_chat_identifier", "to_chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids(cls, v: List[int]) -> List[int]:
        if any(message_id <= 0 for message_id in v):
            raise ValueError("Все ID сообщений должны быть положительными")
        return v


class ForwardMessagesResponse(BaseModel):
    """Ответ на пересылку сообщений"""
    success: bool
    forwarded_count: int
    message_ids: List[int]
    message: str


class ReplyMessageRequest(BaseModel):
    """Запрос на ответ на сообщение"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    reply_to_message_id: int = Field(..., description="ID сообщения, на которое отвечаем", gt=0)
    message: str = Field(..., description="Текст ответа", min_length=1, max_length=4096)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v


class ReplyMessageResponse(BaseModel):
    """Ответ на отправку reply-сообщения"""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    date: Optional[str] = None
    reply_to_message_id: int
    message: str


class SearchMessagesRequest(BaseModel):
    """Запрос на поиск сообщений в чате"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    query: str = Field(..., description="Поисковый запрос", min_length=1, max_length=256)
    limit: int = Field(50, description="Максимальное количество найденных сообщений", ge=1, le=200)

    @field_validator("chat_identifier", "query")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Поле не может быть пустым")
        return v


class MarkMessagesReadRequest(BaseModel):
    """Запрос на отметку сообщений как прочитанных"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    max_id: Optional[int] = Field(
        None,
        description="Максимальный ID сообщения для отметки как прочитанное. Если не указан, отмечаются все непрочитанные.",
        gt=0,
    )

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v


class PinMessageRequest(BaseModel):
    """Запрос на закрепление/открепление сообщения"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    message_id: int = Field(..., description="ID сообщения", gt=0)
    unpin: bool = Field(False, description="True: открепить сообщение, False: закрепить сообщение")
    notify: bool = Field(False, description="Отправлять уведомление участникам при закреплении")

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v


class MessageReactionRequest(BaseModel):
    """Запрос на установку/снятие реакции на сообщение"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    message_id: int = Field(..., description="ID сообщения", gt=0)
    reaction: Optional[str] = Field(
        None,
        description="Emoji реакции (например, 👍). Не указывайте для снятия реакции.",
        max_length=16,
    )
    big: bool = Field(False, description="Большая анимация реакции, если поддерживается")

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v

    @field_validator("reaction")
    @classmethod
    def validate_reaction(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None


class FilterMessagesRequest(BaseModel):
    """Запрос на фильтрацию сообщений по типу"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    message_type: str = Field(
        ...,
        description="Тип сообщений: text, media, photo, video, document, audio, voice, sticker, gif, service",
    )
    limit: int = Field(100, description="Максимальное количество сообщений для анализа", ge=1, le=500)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v

    @field_validator("message_type")
    @classmethod
    def validate_message_type(cls, v: str) -> str:
        allowed = {"text", "media", "photo", "video", "document", "audio", "voice", "sticker", "gif", "service"}
        value = v.strip().lower()
        if value not in allowed:
            raise ValueError(f"Неподдерживаемый тип сообщения. Доступно: {', '.join(sorted(allowed))}")
        return value


class ErrorResponse(BaseModel):
    """Ответ об ошибке"""
    success: bool = False
    error: str
    detail: Optional[str] = None


class FolderChatsRequest(BaseModel):
    """Запрос на получение чатов из папки"""
    folder_name: str = Field(..., description="Название папки (например, 'Работа', 'Личное')", min_length=1)
    limit: int = Field(100, description="Максимальное количество чатов", ge=1, le=1000)
    
    @field_validator('folder_name')
    @classmethod
    def validate_folder_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('Название папки не может быть пустым')
        return v


class LeadSearchFolderRequest(BaseModel):
    """Запрос на добавление каналов в Telegram-папку"""
    channel_identifiers: List[str] = Field(..., description="Username/ID/link каналов", min_length=1)
    folder_name: str = Field("Lead Search 1", description="Название папки", min_length=1, max_length=64)

    @field_validator("channel_identifiers")
    @classmethod
    def validate_channel_identifiers(cls, v: List[str]) -> List[str]:
        cleaned = [x.strip() for x in v if x and x.strip()]
        if not cleaned:
            raise ValueError("Нужно передать хотя бы один канал")
        return cleaned

    @field_validator("folder_name")
    @classmethod
    def validate_folder_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("folder_name не может быть пустым")
        return value


class LeadSearchFolderResponse(BaseModel):
    """Ответ на обновление Telegram-папки лидов"""
    success: bool
    folder_name: str
    folder_id: int
    added: List[ChatInfo]
    skipped: List[str]
    total_added: int
    message: str


class ArchiveChatRequest(BaseModel):
    """Запрос на архивирование/разархивирование чата"""
    chat_identifier: str = Field(..., description="Username чата (@username) или ID чата")
    archive: bool = Field(True, description="True: архивировать чат, False: вернуть из архива")

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Идентификатор чата не может быть пустым")
        return v


class CreateChatRequest(BaseModel):
    """Запрос на создание группы или канала"""
    type: str = Field(..., description="Тип: group или channel")
    title: str = Field(..., description="Название группы/канала", min_length=1, max_length=255)
    about: Optional[str] = Field(None, description="Описание канала (для type=channel)", max_length=255)
    user_identifiers: List[str] = Field(
        default_factory=list,
        description="Список пользователей для добавления в группу (для type=group)",
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"group", "channel"}:
            raise ValueError("type должен быть 'group' или 'channel'")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("title не может быть пустым")
        return value

    @field_validator("about")
    @classmethod
    def validate_about(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None

    @field_validator("user_identifiers")
    @classmethod
    def validate_user_identifiers(cls, v: List[str]) -> List[str]:
        cleaned = [x.strip() for x in v if x and x.strip()]
        return cleaned


class FolderInfo(BaseModel):
    """Информация о папке"""
    name: str
    id: Optional[int] = None


class FoldersResponse(BaseModel):
    """Ответ со списком папок"""
    success: bool
    folders: List[FolderInfo]
    total: int


class MessageInfo(BaseModel):
    """Информация о сообщении"""
    id: int
    chat_id: int
    sender_id: Optional[int] = None
    text: str
    date: str
    is_out: bool = False
    has_media: bool = False
    media_type: Optional[str] = None  # photo, video, document, audio, voice, sticker, gif, etc.
    media_id: Optional[int] = None  # ID сообщения, по которому можно скачать медиа


class UserInfo(BaseModel):
    """Информация о пользователе"""
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    is_bot: bool = False
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    is_premium: bool = False
    status: Optional[str] = None


class AccountInfo(BaseModel):
    """Информация о текущем аккаунте"""
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    is_bot: bool = False
    is_verified: bool = False
    is_premium: bool = False


class ContactInfo(BaseModel):
    """Информация о контакте"""
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    is_bot: bool = False
    is_verified: bool = False
    is_premium: bool = False


class ParticipantInfo(BaseModel):
    """Информация об участнике чата/канала"""
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_bot: bool = False
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    is_premium: bool = False


class UserStatusInfo(BaseModel):
    """Статус пользователя"""
    user_id: int
    status: str
    was_online: Optional[str] = None
    expires: Optional[str] = None


class ManageContactRequest(BaseModel):
    """Запрос на добавление или удаление контакта"""
    action: str = Field(..., description="Действие: add или remove")
    user_identifier: Optional[str] = Field(
        None,
        description="Username/ID/phone пользователя. Для remove обязательно.",
    )
    phone: Optional[str] = Field(
        None,
        description="Телефон для добавления контакта (если добавляем по номеру).",
    )
    first_name: Optional[str] = Field(None, description="Имя контакта для добавления")
    last_name: Optional[str] = Field(None, description="Фамилия контакта для добавления")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"add", "remove"}:
            raise ValueError("action должен быть 'add' или 'remove'")
        return value

    @field_validator("user_identifier", "phone", "first_name", "last_name")
    @classmethod
    def trim_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class ManageBlockRequest(BaseModel):
    """Запрос на блокировку/разблокировку пользователя"""
    action: str = Field(..., description="Действие: block или unblock")
    user_identifier: str = Field(..., description="Username/ID/phone пользователя")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"block", "unblock"}:
            raise ValueError("action должен быть 'block' или 'unblock'")
        return value

    @field_validator("user_identifier")
    @classmethod
    def validate_user_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("user_identifier не может быть пустым")
        return value


class UpdateUsernameRequest(BaseModel):
    """Запрос на изменение username текущего аккаунта"""
    username: str = Field(..., description="Новый username (без @)", min_length=5, max_length=32)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        value = v.strip()
        if value.startswith("@"):
            value = value[1:]
        if not value:
            raise ValueError("username не может быть пустым")
        return value


class UpdateNameRequest(BaseModel):
    """Запрос на изменение имени и фамилии"""
    first_name: str = Field(..., description="Новое имя", min_length=1, max_length=64)
    last_name: Optional[str] = Field(None, description="Новая фамилия", max_length=64)

    @field_validator("first_name", "last_name")
    @classmethod
    def trim_names(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class UpdateAboutRequest(BaseModel):
    """Запрос на изменение биографии (about)"""
    about: str = Field(..., description="Новая биография", min_length=1, max_length=70)

    @field_validator("about")
    @classmethod
    def validate_about(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("about не может быть пустым")
        return value


class UpdateProfilePhotoRequest(BaseModel):
    """Запрос на изменение фото профиля"""
    photo_base64: str = Field(..., description="Фото в base64 (можно с data URL префиксом)")

    @field_validator("photo_base64")
    @classmethod
    def validate_photo_base64(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("photo_base64 не может быть пустым")
        return value


class SubscribeChannelRequest(BaseModel):
    """Запрос на подписку на канал"""
    channel_identifier: str = Field(
        ...,
        description="Username/ID канала, public link или private invite link",
    )

    @field_validator("channel_identifier")
    @classmethod
    def validate_channel_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("channel_identifier не может быть пустым")
        return value


class PublishChannelPostRequest(BaseModel):
    """Запрос на публикацию поста в канал"""
    channel_identifier: str = Field(..., description="Username канала (@channel) или ID канала")
    message: str = Field(..., description="Текст поста", min_length=1, max_length=4096)

    @field_validator("channel_identifier")
    @classmethod
    def validate_channel_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("channel_identifier не может быть пустым")
        return value


class EditChannelPostRequest(BaseModel):
    """Запрос на редактирование поста в канале"""
    channel_identifier: str = Field(..., description="Username канала (@channel) или ID канала")
    message_id: int = Field(..., description="ID поста", gt=0)
    message: str = Field(..., description="Новый текст поста", min_length=1, max_length=4096)

    @field_validator("channel_identifier")
    @classmethod
    def validate_channel_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("channel_identifier не может быть пустым")
        return value


class DeleteChannelPostsRequest(BaseModel):
    """Запрос на удаление постов в канале"""
    channel_identifier: str = Field(..., description="Username канала (@channel) или ID канала")
    message_ids: List[int] = Field(..., description="Список ID постов для удаления", min_length=1)

    @field_validator("channel_identifier")
    @classmethod
    def validate_channel_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("channel_identifier не может быть пустым")
        return value

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids(cls, v: List[int]) -> List[int]:
        if any(message_id <= 0 for message_id in v):
            raise ValueError("Все message_ids должны быть положительными")
        return v


class MessagesResponse(BaseModel):
    """Ответ со списком сообщений чата"""
    success: bool
    chat_id: int
    chat_name: Optional[str] = None
    messages: List[MessageInfo]
    total: int


class SearchMessagesResponse(BaseModel):
    """Ответ с результатами поиска сообщений"""
    success: bool
    chat_id: int
    chat_name: Optional[str] = None
    query: str
    messages: List[MessageInfo]
    total: int


class MarkMessagesReadResponse(BaseModel):
    """Ответ на отметку сообщений как прочитанных"""
    success: bool
    chat_id: Optional[int] = None
    max_id: Optional[int] = None
    message: str


class PinMessageResponse(BaseModel):
    """Ответ на закрепление/открепление сообщения"""
    success: bool
    chat_id: Optional[int] = None
    message_id: int
    action: str
    message: str


class MessageReactionResponse(BaseModel):
    """Ответ на установку/снятие реакции"""
    success: bool
    chat_id: Optional[int] = None
    message_id: int
    reaction: Optional[str] = None
    message: str


class MessageViewsResponse(BaseModel):
    """Ответ с количеством просмотров сообщения"""
    success: bool
    chat_id: int
    message_id: int
    views: Optional[int] = None
    message: str


class ArchiveChatResponse(BaseModel):
    """Ответ на архивирование/разархивирование чата"""
    success: bool
    chat_id: Optional[int] = None
    archived: bool
    message: str


class FilterMessagesResponse(BaseModel):
    """Ответ с отфильтрованными сообщениями"""
    success: bool
    chat_id: int
    chat_name: Optional[str] = None
    message_type: str
    messages: List[MessageInfo]
    total: int


class UserInfoResponse(BaseModel):
    """Ответ с информацией о пользователе"""
    success: bool
    user: UserInfo


class ContactsResponse(BaseModel):
    """Ответ со списком контактов"""
    success: bool
    contacts: List[ContactInfo]
    total: int


class ChatParticipantsResponse(BaseModel):
    """Ответ со списком участников чата/канала"""
    success: bool
    chat_id: int
    chat_name: Optional[str] = None
    participants: List[ParticipantInfo]
    total: int


class ChatAdminsResponse(BaseModel):
    """Ответ со списком администраторов чата/канала"""
    success: bool
    chat_id: int
    chat_name: Optional[str] = None
    admins: List[ParticipantInfo]
    total: int


class ChatInfoResponse(BaseModel):
    """Ответ с расширенной информацией о чате"""
    success: bool
    chat: ChatDetailsInfo


class UpdateChatInfoRequest(BaseModel):
    """Запрос на изменение названия и/или описания чата"""
    chat_identifier: str = Field(..., description="Username/ID группы, супергруппы или канала")
    title: Optional[str] = Field(None, description="Новое название чата", max_length=255)
    about: Optional[str] = Field(None, description="Новое описание чата", max_length=255)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("chat_identifier не может быть пустым")
        return value

    @field_validator("title", "about")
    @classmethod
    def validate_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class UpdateChatInfoResponse(BaseModel):
    """Ответ на изменение названия/описания чата"""
    success: bool
    chat_id: Optional[int] = None
    title: Optional[str] = None
    about: Optional[str] = None
    message: str


class UpdateChatPhotoRequest(BaseModel):
    """Запрос на установку фото чата"""
    chat_identifier: str = Field(..., description="Username/ID группы, супергруппы или канала")
    photo_base64: str = Field(..., description="Фото в base64 (можно с data URL префиксом)")

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("chat_identifier не может быть пустым")
        return value

    @field_validator("photo_base64")
    @classmethod
    def validate_photo_base64(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("photo_base64 не может быть пустым")
        return value


class UpdateChatPhotoResponse(BaseModel):
    """Ответ на установку фото чата"""
    success: bool
    chat_id: Optional[int] = None
    message: str


class CreateChatResponse(BaseModel):
    """Ответ на создание группы/канала"""
    success: bool
    chat_id: Optional[int] = None
    type: str
    title: str
    username: Optional[str] = None
    message: str


class InviteUsersRequest(BaseModel):
    """Запрос на приглашение пользователей в группу/канал"""
    chat_identifier: str = Field(..., description="Username/ID группы или канала")
    user_identifiers: List[str] = Field(..., description="Список пользователей для приглашения", min_length=1)
    fwd_limit: int = Field(10, description="Лимит пересылаемой истории для обычной группы", ge=0, le=300)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("chat_identifier не может быть пустым")
        return value

    @field_validator("user_identifiers")
    @classmethod
    def validate_user_identifiers(cls, v: List[str]) -> List[str]:
        values = [x.strip() for x in v if x and x.strip()]
        if not values:
            raise ValueError("user_identifiers не может быть пустым")
        return values


class InviteUsersResponse(BaseModel):
    """Ответ на приглашение пользователей"""
    success: bool
    chat_id: Optional[int] = None
    invited_count: int
    message: str


class RemoveUsersRequest(BaseModel):
    """Запрос на исключение пользователей из группы/супергруппы"""
    chat_identifier: str = Field(..., description="Username/ID группы или супергруппы")
    user_identifiers: List[str] = Field(..., description="Список пользователей для исключения", min_length=1)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("chat_identifier не может быть пустым")
        return value

    @field_validator("user_identifiers")
    @classmethod
    def validate_user_identifiers(cls, v: List[str]) -> List[str]:
        values = [x.strip() for x in v if x and x.strip()]
        if not values:
            raise ValueError("user_identifiers не может быть пустым")
        return values


class RemoveUsersResponse(BaseModel):
    """Ответ на исключение пользователей"""
    success: bool
    chat_id: Optional[int] = None
    removed_count: int
    message: str


class UpdateParticipantPermissionsRequest(BaseModel):
    """Запрос на изменение прав участника (mute/unmute)"""
    chat_identifier: str = Field(..., description="Username/ID супергруппы")
    user_identifier: str = Field(..., description="Username/ID пользователя")
    mute: bool = Field(..., description="True: ограничить отправку сообщений, False: снять ограничения")
    until_date: Optional[str] = Field(
        None,
        description="Дата окончания ограничения в ISO-формате (например, 2026-12-31T23:59:59). Если не указана, ограничения бессрочные.",
    )

    @field_validator("chat_identifier", "user_identifier")
    @classmethod
    def validate_identifiers(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Идентификатор не может быть пустым")
        return value

    @field_validator("until_date")
    @classmethod
    def validate_until_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class UpdateParticipantPermissionsResponse(BaseModel):
    """Ответ на изменение прав участника"""
    success: bool
    chat_id: Optional[int] = None
    user_id: Optional[int] = None
    muted: bool
    until_date: Optional[str] = None
    message: str


class UserStatusResponse(BaseModel):
    """Ответ со статусом пользователя"""
    success: bool
    user_status: UserStatusInfo


class AccountInfoResponse(BaseModel):
    """Ответ с информацией о текущем аккаунте"""
    success: bool
    account: AccountInfo


class ResetSessionsResponse(BaseModel):
    """Ответ на отключение других сессий"""
    success: bool
    message: str


class UpdateUsernameResponse(BaseModel):
    """Ответ на изменение username"""
    success: bool
    username: str
    message: str


class UpdateNameResponse(BaseModel):
    """Ответ на изменение имени и фамилии"""
    success: bool
    first_name: str
    last_name: Optional[str] = None
    message: str


class UpdateAboutResponse(BaseModel):
    """Ответ на изменение биографии"""
    success: bool
    about: str
    message: str


class UpdateProfilePhotoResponse(BaseModel):
    """Ответ на изменение фото профиля"""
    success: bool
    message: str


class ManageContactResponse(BaseModel):
    """Ответ на добавление/удаление контакта"""
    success: bool
    action: str
    message: str


class ManageBlockResponse(BaseModel):
    """Ответ на блокировку/разблокировку пользователя"""
    success: bool
    action: str
    user_id: Optional[int] = None
    message: str


class SendBotCommandRequest(BaseModel):
    """Запрос на отправку команды боту"""
    bot_identifier: str = Field(..., description="Username/ID бота")
    command: str = Field(..., description="Команда (например, /start)", min_length=2, max_length=256)

    @field_validator("bot_identifier")
    @classmethod
    def validate_bot_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("bot_identifier не может быть пустым")
        return value

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        value = v.strip()
        if not value.startswith("/"):
            raise ValueError("command должна начинаться с '/'")
        return value


class SendBotCommandResponse(BaseModel):
    """Ответ на отправку команды боту"""
    success: bool
    bot_id: Optional[int] = None
    message_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class BotInlineButtonClickRequest(BaseModel):
    """Запрос на нажатие inline-кнопки в сообщении"""
    chat_identifier: str = Field(..., description="Username/ID чата или бота")
    message_id: int = Field(..., description="ID сообщения с inline-кнопками", gt=0)
    row: int = Field(..., description="Индекс строки кнопки (с 0)", ge=0)
    col: int = Field(..., description="Индекс колонки кнопки (с 0)", ge=0)

    @field_validator("chat_identifier")
    @classmethod
    def validate_chat_identifier(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("chat_identifier не может быть пустым")
        return value


class BotInlineButtonClickResponse(BaseModel):
    """Ответ на нажатие inline-кнопки"""
    success: bool
    message_id: int
    row: int
    col: int
    result: Optional[str] = None
    message: str


class SubscribeChannelResponse(BaseModel):
    """Ответ на подписку на канал"""
    success: bool
    channel_id: Optional[int] = None
    message: str


class UnsubscribeChannelResponse(BaseModel):
    """Ответ на отписку от канала"""
    success: bool
    channel_id: Optional[int] = None
    message: str


class ChannelSearchResult(BaseModel):
    """Найденный канал/супергруппа"""
    id: int
    name: str
    type: str
    username: Optional[str] = None
    participants_count: Optional[int] = None
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    is_private: bool = False
    join_request: bool = False


class ChannelSearchResponse(BaseModel):
    """Ответ поиска каналов"""
    success: bool
    query: str
    channels: List[ChannelSearchResult]
    total: int


class JoinChannelResponse(BaseModel):
    """Ответ на вход в канал или заявку"""
    success: bool
    status: str
    channel_id: Optional[int] = None
    title: Optional[str] = None
    username: Optional[str] = None
    participants_count: Optional[int] = None
    request_needed: bool = False
    message: str


class ChannelCommentsStatusResponse(BaseModel):
    """Ответ со статусом комментариев канала или поста"""
    success: bool
    channel_id: Optional[int] = None
    channel_name: Optional[str] = None
    linked_chat_id: Optional[int] = None
    linked_chat_name: Optional[str] = None
    has_discussion_group: bool = False
    message_id: Optional[int] = None
    has_comments: bool = False
    comments_count: int = 0
    message: str


class ChannelCommentsResponse(BaseModel):
    """Ответ со списком комментариев к посту"""
    success: bool
    channel_id: int
    channel_name: Optional[str] = None
    message_id: int
    comments: List[MessageInfo]
    total: int


class CollectPostsRequest(BaseModel):
    """Параметры сбора постов канала для аналитики."""

    limit: int = Field(50, ge=1, le=300)
    exclude_forwards: bool = True
    exclude_ads: bool = True


class CollectedPostItem(BaseModel):
    """Запись собранного поста."""

    channel_id: int
    channel_username: str
    message_id: int
    post_url: Optional[str] = None
    date: Optional[str] = None
    text: Optional[str] = None
    views: int = 0
    forwards: int = 0
    replies_count: int = 0
    reactions_count: int = 0
    has_media: bool = False
    has_link: bool = False
    is_forward: bool = False
    is_ad_like: bool = False


class CollectPostsResponse(BaseModel):
    """Ответ после сборки постов канала."""

    success: bool
    channel_id: int
    channel_username: str
    posts_analyzed: int
    posts: List[CollectedPostItem]
    message: str


class CollectCommentsRequest(BaseModel):
    """Параметры сбора комментариев к постам."""

    posts_limit: int = Field(20, ge=1, le=120)
    comments_per_post: int = Field(50, ge=1, le=200)


class CollectedCommentItem(BaseModel):
    """Запись собранного комментария."""

    channel_id: int
    post_message_id: int
    comment_id: int
    comment_text: str
    comment_date: Optional[str] = None
    commenter_id_hash: Optional[str] = None
    commenter_username: Optional[str] = None
    is_author_reply: bool = False
    is_spam_like: bool = False


class CollectCommentsResponse(BaseModel):
    """Ответ после сбора комментариев."""

    success: bool
    channel_id: int
    channel_username: str
    posts_considered: int
    total_comments: int
    comments: List[CollectedCommentItem]
    message: str


class ChannelHealthResponse(BaseModel):
    """Итоговое health-оценивание канала."""

    success: bool
    channel_id: int
    channel_username: str
    subscribers_count: Optional[int] = None
    posts_analyzed: int
    median_views_30: float
    avg_views_30: float
    view_rate: float
    posts_per_week: float
    views_cv: float
    median_reactions: float
    reaction_rate: float
    median_forwards: float
    forward_rate: float
    last_post_at: Optional[str] = None
    channel_health_score: float


class DiscussionScoreResponse(BaseModel):
    """Итоговое discussion-оценивание канала."""

    success: bool
    channel_id: int
    channel_username: str
    comments_enabled: bool
    posts_with_comments: int
    median_comments_30: float
    avg_comments_30: float
    comment_rate: float
    unique_commenters_30: int
    author_replies_count: int
    author_reply_rate: float
    spam_comments_count: int
    spam_ratio: float
    discussion_score: float


class BusinessFitResponse(BaseModel):
    """Итоговое business-fit оценивание канала."""

    success: bool
    channel_id: int
    channel_username: str
    niche_fit_score: float
    monetization_signal_score: float
    pain_markers_score: float
    ai_product_potential_score: float
    business_fit_score: float
    reason: str
    suggested_ai_product: Optional[str] = None


class CampaignScoreResponse(BaseModel):
    """Итоговый score для запуска комментариев и кампании."""

    success: bool
    channel_id: int
    channel_username: str
    lead_score: float
    campaign_score: float
    recommended_action: str
    reason: str
    niche_fit_score: float
    monetization_signal_score: float
    audience_attention_score: float
    comments_enabled_score: float
    comment_rate_score: float
    median_views_score: float
    view_rate_score: float
    discussion_score: float
    business_fit_score: float


class RankedChannelItem(BaseModel):
    """Позиция в ранжированном списке каналов."""

    title: Optional[str] = None
    username: Optional[str] = None
    url: Optional[str] = None
    subscribers_count: Optional[int] = None
    median_views_30: Optional[float] = None
    view_rate: Optional[float] = None
    posts_per_week: Optional[float] = None
    comments_enabled: bool = False
    median_comments_30: Optional[float] = None
    comment_rate: Optional[float] = None
    unique_commenters_30: Optional[int] = None
    niche: Optional[str] = None
    monetization_signals: Optional[str] = None
    lead_score: float
    campaign_score: float
    recommended_action: Optional[str] = None
    reason: Optional[str] = None
    last_post_at: Optional[str] = None


class RankedChannelsResponse(BaseModel):
    """Список отсортированных каналов."""

    success: bool
    channels: List[RankedChannelItem]
    total: int


class OpportunityPostItem(BaseModel):
    """Предложение для кампании на уровне поста."""

    post_url: Optional[str] = None
    message_id: int
    date: Optional[str] = None
    text_preview: Optional[str] = None
    views: int = 0
    comments_count: int = 0
    reactions_count: int = 0
    post_relevance_score: float = 0.0
    pain_markers: Optional[str] = None
    opportunity_score: float = 0.0
    suggested_angle: Optional[str] = None


class OpportunityPostsResponse(BaseModel):
    """Список лучших постов для захода в канал."""

    success: bool
    channel_id: int
    channel_username: str
    posts: List[OpportunityPostItem]
    total: int


class PublishChannelPostResponse(BaseModel):
    """Ответ на публикацию поста"""
    success: bool
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class EditChannelPostResponse(BaseModel):
    """Ответ на редактирование поста"""
    success: bool
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    date: Optional[str] = None
    message: str


class DeleteChannelPostsResponse(BaseModel):
    """Ответ на удаление постов"""
    success: bool
    channel_id: Optional[int] = None
    deleted_count: int
    message: str


class CompanyCreate(BaseModel):
    """Запрос на создание компании"""
    name: str = Field(..., description="Название компании", min_length=1, max_length=200)
    website: Optional[str] = Field(None, description="Сайт компании", max_length=500)
    telegram_chat: Optional[str] = Field(
        None,
        description="Username или ID Telegram-чата компании",
        max_length=200,
    )
    description: Optional[str] = Field(None, description="Краткое описание", max_length=2000)
    notes: Optional[str] = Field(None, description="Внутренние заметки", max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Название компании не может быть пустым")
        return value

    @field_validator("website", "telegram_chat", "description", "notes")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class CompanyUpdate(BaseModel):
    """Запрос на обновление компании"""
    name: Optional[str] = Field(None, description="Название компании", min_length=1, max_length=200)
    website: Optional[str] = Field(None, description="Сайт компании", max_length=500)
    telegram_chat: Optional[str] = Field(
        None,
        description="Username или ID Telegram-чата компании",
        max_length=200,
    )
    description: Optional[str] = Field(None, description="Краткое описание", max_length=2000)
    notes: Optional[str] = Field(None, description="Внутренние заметки", max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        if not value:
            raise ValueError("Название компании не может быть пустым")
        return value

    @field_validator("website", "telegram_chat", "description", "notes")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class CompanyInfo(BaseModel):
    """Информация о компании"""
    id: int
    name: str
    website: Optional[str] = None
    telegram_chat: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CompanyResponse(BaseModel):
    """Ответ с одной компанией"""
    success: bool
    company: CompanyInfo
    message: str


class CompanyListResponse(BaseModel):
    """Ответ со списком компаний"""
    success: bool
    companies: List[CompanyInfo]
    total: int


class DeleteCompanyResponse(BaseModel):
    """Ответ на удаление компании"""
    success: bool
    company_id: int
    message: str


class LeadCreate(BaseModel):
    """Запрос на сохранение найденного Telegram-лида"""
    title: str = Field(..., description="Название канала", min_length=1, max_length=300)
    username: Optional[str] = Field(None, description="Username без @ или с @", max_length=200)
    url: str = Field(..., description="Ссылка t.me", min_length=1, max_length=500)
    niche: Optional[str] = Field(None, description="Тематика / ниша", max_length=500)
    subscribers: Optional[int] = Field(None, description="Количество подписчиков, если видно", ge=0)
    is_public: bool = Field(True, description="Открытый канал")
    has_comments: bool = Field(False, description="Есть комментарии")
    monetization_signals: Optional[str] = Field(None, description="Признаки монетизации", max_length=3000)
    lead_score: int = Field(..., description="Lead score 1-10", ge=1, le=10)
    reason: Optional[str] = Field(None, description="Почему канал может быть лидом", max_length=3000)
    suggested_ai_product: Optional[str] = Field(None, description="Идея AI-продукта", max_length=3000)
    status: str = Field("new", description="new, maybe, subscribed, skipped", max_length=32)
    subscribed: bool = Field(False, description="Подписались ли на канал")
    folder: Optional[str] = Field(None, description="Папка Telegram", max_length=64)

    @field_validator("title", "url", "status")
    @classmethod
    def strip_required_text(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        if value.startswith("@"):
            value = value[1:]
        return value or None

    @field_validator(
        "niche",
        "monetization_signals",
        "reason",
        "suggested_ai_product",
        "folder",
    )
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        return value or None


class LeadInfo(BaseModel):
    """Сохраненный Telegram-лид"""
    id: int
    title: str
    username: Optional[str] = None
    url: str
    niche: Optional[str] = None
    subscribers: Optional[int] = None
    is_public: bool
    has_comments: bool
    monetization_signals: Optional[str] = None
    lead_score: int
    reason: Optional[str] = None
    suggested_ai_product: Optional[str] = None
    status: str
    subscribed: bool
    folder: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LeadResponse(BaseModel):
    """Ответ с одним лидом"""
    success: bool
    lead: LeadInfo
    message: str


class LeadListResponse(BaseModel):
    """Ответ со списком лидов"""
    success: bool
    leads: List[LeadInfo]
    total: int
