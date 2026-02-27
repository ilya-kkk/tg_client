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


class SendMessageResponse(BaseModel):
    """Ответ на отправку сообщения"""
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


class ErrorResponse(BaseModel):
    """Ответ об ошибке"""
    success: bool = False
    error: str
    detail: Optional[str] = None


class QRCodeGenerateResponse(BaseModel):
    """Ответ на генерацию QR-кода"""
    success: bool
    qr_url: Optional[str] = None
    qr_code_data: Optional[str] = None
    expires_in: Optional[int] = None
    authorized: Optional[bool] = False
    message: str


class QRCodeStatusResponse(BaseModel):
    """Ответ на проверку статуса QR-кода"""
    success: bool
    authorized: bool
    message: str


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
