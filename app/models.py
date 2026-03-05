from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal


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
    channel_identifier: str = Field(..., description="Username канала (@channel) или ID канала")

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


class ChannelsSearchRequest(BaseModel):
    """Запрос на поиск Telegram-каналов по ключевым словам."""
    keywords: List[str] = Field(
        ...,
        description="Ключевые слова/фразы для поиска каналов",
        min_length=1,
    )
    limit_per_keyword: int = Field(
        20,
        description="Лимит результатов на одно ключевое слово",
        ge=1,
        le=100,
    )
    language: Optional[str] = Field(
        None,
        description="Опциональный язык поиска (например: ru, en)",
        max_length=12,
    )
    include_about: bool = Field(
        True,
        description="Подтягивать описание канала (about), если доступно",
    )

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, v: List[str]) -> List[str]:
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Нужно передать хотя бы одно ключевое слово")
        return values

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip().lower()
        return value or None


class ChannelsSearchResultItem(BaseModel):
    """Нормализованный результат найденного Telegram-канала."""
    channel_id: str = Field(..., description="ID канала (peer/channel id)")
    title: str
    username: Optional[str] = None
    link: Optional[str] = None
    about: Optional[str] = None
    participants_count: Optional[int] = None
    verified: Optional[bool] = None
    scam: Optional[bool] = None
    fake: Optional[bool] = None
    found_by: List[str] = Field(
        default_factory=list,
        description="Список ключевых слов, по которым найден канал",
    )


class ChannelsSearchResponse(BaseModel):
    """Ответ на поиск Telegram-каналов."""
    items: List[ChannelsSearchResultItem]
    total: int


class SaveParsedChannelsRequest(BaseModel):
    """Запрос на сохранение найденных каналов в базу."""
    items: List[ChannelsSearchResultItem] = Field(..., min_length=1)


class ParsedChannelsListResponse(BaseModel):
    """Ответ со списком сохраненных каналов."""
    success: bool
    items: List[ChannelsSearchResultItem]
    total: int


class SaveParsedChannelsResponse(BaseModel):
    """Ответ на сохранение пачки каналов в базу."""
    success: bool
    saved: int
    message: str


class DeleteParsedChannelsResponse(BaseModel):
    """Ответ на очистку сохраненных каналов."""
    success: bool
    deleted: int
    message: str


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


class ReactionJobCreate(BaseModel):
    """Запрос на создание кампании автореакций."""
    name: str = Field(..., min_length=1, max_length=120)
    account_sessions: List[str] = Field(..., min_length=1)
    reactions: List[str] = Field(..., min_length=1, max_length=10)
    message_frequency: Literal["every", "1/2", "1/3", "2/3"]
    target_chats: List[str] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Название кампании не может быть пустым")
        return value

    @field_validator("account_sessions", "target_chats")
    @classmethod
    def validate_non_empty_items(cls, v: List[str]) -> List[str]:
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Список не может быть пустым")
        return values

    @field_validator("reactions")
    @classmethod
    def validate_reactions(cls, v: List[str]) -> List[str]:
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Нужно указать хотя бы одну реакцию")
        if len(values) > 10:
            raise ValueError("Можно указать не более 10 реакций")
        return values


class ReactionJobUpdate(BaseModel):
    """Запрос на обновление кампании автореакций."""
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    account_sessions: Optional[List[str]] = Field(None, min_length=1)
    reactions: Optional[List[str]] = Field(None, min_length=1, max_length=10)
    message_frequency: Optional[Literal["every", "1/2", "1/3", "2/3"]] = None
    target_chats: Optional[List[str]] = Field(None, min_length=1)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("Название кампании не может быть пустым")
        return value

    @field_validator("account_sessions", "target_chats")
    @classmethod
    def validate_optional_non_empty_items(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Список не может быть пустым")
        return values

    @field_validator("reactions")
    @classmethod
    def validate_optional_reactions(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Нужно указать хотя бы одну реакцию")
        if len(values) > 10:
            raise ValueError("Можно указать не более 10 реакций")
        return values


class ReactionJobOut(BaseModel):
    """Выходная модель кампании автореакций."""
    id: str
    user_id: str
    name: str
    account_sessions: List[str]
    reactions: List[str]
    message_frequency: Literal["every", "1/2", "1/3", "2/3"]
    target_chats: List[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AiCommentJobCreate(BaseModel):
    """Запрос на создание кампании нейрокомментирования."""
    name: str = Field(..., min_length=1, max_length=120)
    account_sessions: list[str] = Field(..., min_length=1)
    target_channels: list[str] = Field(..., min_length=1)
    user_prompt: str = Field(..., min_length=1)
    system_prompt: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Название кампании не может быть пустым")
        return value

    @field_validator("account_sessions", "target_channels")
    @classmethod
    def validate_non_empty_items(cls, v: list[str]) -> list[str]:
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Список не может быть пустым")
        return values

    @field_validator("user_prompt", "system_prompt")
    @classmethod
    def validate_prompts(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Промпт не может быть пустым")
        return value


class AiCommentJobUpdate(BaseModel):
    """Запрос на обновление кампании нейрокомментирования."""
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    account_sessions: Optional[list[str]] = Field(None, min_length=1)
    target_channels: Optional[list[str]] = Field(None, min_length=1)
    user_prompt: Optional[str] = Field(None, min_length=1)
    system_prompt: Optional[str] = Field(None, min_length=1)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("Название кампании не может быть пустым")
        return value

    @field_validator("account_sessions", "target_channels")
    @classmethod
    def validate_optional_non_empty_items(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Список не может быть пустым")
        return values

    @field_validator("user_prompt", "system_prompt")
    @classmethod
    def validate_optional_prompts(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("Промпт не может быть пустым")
        return value


class AiCommentJobOut(BaseModel):
    """Выходная модель кампании нейрокомментирования."""
    id: str
    user_id: str
    name: str
    account_sessions: list[str]
    target_channels: list[str]
    user_prompt: str
    system_prompt: str
    is_active: bool
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AiCommentJobPostOut(BaseModel):
    """Выходная модель истории обработки постов в кампании нейрокомментирования."""
    channel_id: str
    message_id: int
    status: Literal["posted", "skipped", "failed"]
    error: Optional[str] = None
    created_at: datetime


class WarmupJobCreate(BaseModel):
    """Запрос на создание кампании прогрева."""
    name: str = Field(..., min_length=1, max_length=120)
    account_sessions: list[str] = Field(..., min_length=1)
    mode: Literal["cautious", "normal", "aggressive"]
    enabled_actions: list[str] = Field(..., min_length=1)
    target_channels: list[str] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("Название кампании не может быть пустым")
        return value

    @field_validator("account_sessions", "enabled_actions", "target_channels")
    @classmethod
    def validate_non_empty_items(cls, v: list[str]) -> list[str]:
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Список не может быть пустым")
        return values


class WarmupJobUpdate(BaseModel):
    """Запрос на обновление кампании прогрева."""
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    account_sessions: Optional[list[str]] = Field(None, min_length=1)
    mode: Optional[Literal["cautious", "normal", "aggressive"]] = None
    enabled_actions: Optional[list[str]] = Field(None, min_length=1)
    target_channels: Optional[list[str]] = Field(None, min_length=1)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        if not value:
            raise ValueError("Название кампании не может быть пустым")
        return value

    @field_validator("account_sessions", "enabled_actions", "target_channels")
    @classmethod
    def validate_optional_non_empty_items(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        values = [item.strip() for item in v if item and item.strip()]
        if not values:
            raise ValueError("Список не может быть пустым")
        return values


class WarmupJobOut(BaseModel):
    """Выходная модель кампании прогрева."""
    id: str
    user_id: str
    name: str
    account_sessions: list[str]
    mode: Literal["cautious", "normal", "aggressive"]
    actions_per_day: int
    enabled_actions: list[str]
    target_channels: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
