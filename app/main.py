from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
import io
import qrcode
from app.models import (
    LoginRequest,
    LoginResponse,
    VerifyRequest,
    VerifyResponse,
    PasswordRequest,
    PasswordResponse,
    ChatsResponse,
    SendMessageRequest,
    SendMessageResponse,
    EditMessageRequest,
    EditMessageResponse,
    DeleteMessagesRequest,
    DeleteMessagesResponse,
    ForwardMessagesRequest,
    ForwardMessagesResponse,
    ReplyMessageRequest,
    ReplyMessageResponse,
    SearchMessagesRequest,
    SearchMessagesResponse,
    MarkMessagesReadRequest,
    MarkMessagesReadResponse,
    PinMessageRequest,
    PinMessageResponse,
    MessageReactionRequest,
    MessageReactionResponse,
    ErrorResponse,
    ChatInfo,
    QRCodeGenerateResponse,
    QRCodeStatusResponse,
    FolderChatsRequest,
    ArchiveChatRequest,
    ArchiveChatResponse,
    FoldersResponse,
    FolderInfo,
    MessageInfo,
    MessagesResponse,
)
from app.telegram_client import client_manager
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


tags_metadata = [
    {
        "name": "system",
        "description": "Системные эндпоинты и статус сервиса",
    },
    {
        "name": "auth",
        "description": "Авторизация по номеру телефона, 2FA и QR-код",
    },
    {
        "name": "chats",
        "description": "Работа с чатами и папками (folders)",
    },
    {
        "name": "messages",
        "description": "Отправка и получение сообщений",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # При старте приложения
    try:
        logger.info("Инициализация Telegram клиента...")
        is_authorized = await client_manager.init_client()
        if is_authorized:
            logger.info("Клиент авторизован с существующей сессией")
        else:
            logger.info("Требуется авторизация через API")
    except Exception as e:
        logger.error(f"Ошибка инициализации клиента: {e}")
    
    yield
    
    # При остановке приложения
    logger.info("Отключение Telegram клиента...")
    await client_manager.disconnect()


app = FastAPI(
    title="Telegram REST API",
    description="REST API для работы с Telegram через Telethon",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
)


@app.get("/", tags=["system"])
async def root():
    """Корневой endpoint"""
    return {
        "message": "Telegram REST API",
        "status": "running",
        "authorized": client_manager.is_connected()
    }


@app.post(
    "/auth/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def login(request: LoginRequest):
    """
    Отправляет код подтверждения на номер телефона.
    
    Номер телефона должен быть в международном формате (например, +79991234567).
    Код придет в приложение Telegram или по SMS (если указан force_sms=true).
    """
    try:
        result = await client_manager.send_code(request.phone, force_sms=request.force_sms)
        return LoginResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке кода: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/auth/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def verify(request: VerifyRequest):
    """
    Подтверждает код авторизации.
    
    Если требуется пароль двухфакторной аутентификации, вернется password_required=true.
    В этом случае используйте /auth/password для завершения авторизации.
    """
    try:
        result = await client_manager.sign_in(request.phone, request.code)
        return VerifyResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при подтверждении кода: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/auth/password",
    response_model=PasswordResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def password(request: PasswordRequest):
    """
    Вводит пароль двухфакторной аутентификации.
    
    Используйте этот endpoint только после того, как /auth/verify вернул password_required=true.
    """
    try:
        result = await client_manager.sign_in_password(request.password)
        return PasswordResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при вводе пароля: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/chats",
    response_model=ChatsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chats(limit: int = 100):
    """
    Получает список всех диалогов (чатов).
    
    Включает личные чаты, группы, супергруппы и каналы.
    
    Args:
        limit: Максимальное количество чатов (по умолчанию 100)
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )
    
    try:
        dialogs = await client_manager.get_dialogs(limit=limit)
        chats = [ChatInfo(**dialog) for dialog in dialogs]
        
        return ChatsResponse(
            success=True,
            chats=chats,
            total=len(chats)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении списка чатов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/chats/folders",
    response_model=FoldersResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_folders():
    """
    Получает список всех доступных папок (dialog filters).
    
    Используйте этот endpoint, чтобы узнать названия ваших папок,
    а затем используйте /chats/folder для получения чатов из конкретной папки.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )
    
    try:
        folders = await client_manager.get_folders_list()
        folder_infos = [FolderInfo(**folder) for folder in folders]
        
        return FoldersResponse(
            success=True,
            folders=folder_infos,
            total=len(folder_infos)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении списка папок: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/chats/folder",
    response_model=ChatsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chats_by_folder(request: FolderChatsRequest):
    """
    Получает список чатов из указанной папки.
    
    Папки (folders) - это пользовательские фильтры диалогов в Telegram,
    которые можно создать в настройках приложения.
    
    Сначала используйте GET /chats/folders, чтобы узнать названия ваших папок.
    
    Args:
        request: Запрос с названием папки и лимитом чатов
    
    Примеры названий папок:
    - "Работа"
    - "Личное"
    - "Важное"
    - "1"
    - и другие папки, созданные пользователем
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )
    
    try:
        dialogs = await client_manager.get_dialogs_by_folder(
            folder_name=request.folder_name,
            limit=request.limit
        )
        chats = [ChatInfo(**dialog) for dialog in dialogs]
        
        return ChatsResponse(
            success=True,
            chats=chats,
            total=len(chats)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении чатов из папки: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/chats/archive",
    response_model=ArchiveChatResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def archive_chat(request: ArchiveChatRequest):
    """
    Архивирует чат или возвращает его из архива.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.archive_chat(
            request.chat_identifier,
            request.archive,
        )
        return ArchiveChatResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при архивировании чата: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/auth/qr/generate",
    response_model=QRCodeGenerateResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def generate_qr_code():
    """
    Генерирует QR-код для авторизации через сканирование.
    
    Отсканируйте QR-код в Telegram приложении (Настройки -> Устройства -> Сканировать QR-код).
    После сканирования используйте /auth/qr/status для проверки статуса авторизации.
    """
    try:
        result = await client_manager.generate_qr_code()
        return QRCodeGenerateResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при генерации QR-кода: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/auth/qr/status",
    response_model=QRCodeStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def check_qr_status():
    """
    Проверяет статус QR-кода авторизации.
    
    Вызывайте этот endpoint периодически после генерации QR-кода,
    чтобы узнать, был ли он отсканирован и авторизация завершена.
    """
    try:
        result = await client_manager.check_qr_status()
        return QRCodeStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса QR-кода: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get("/auth/qr/image", tags=["auth"])
async def get_qr_code_image():
    """
    Генерирует и возвращает изображение QR-кода для авторизации.
    
    Сначала вызовите /auth/qr/generate, затем этот endpoint для получения изображения.
    Или просто вызовите этот endpoint - он автоматически сгенерирует QR-код.
    """
    try:
        # Генерируем QR-код (если уже есть, метод вернет существующий или создаст новый)
        qr_data = await client_manager.generate_qr_code()
        qr_url = qr_data.get("qr_url")
        
        if not qr_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось получить QR-код URL"
            )
        
        # Создаем QR-код изображение
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Конвертируем в bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        return Response(content=img_byte_arr.getvalue(), media_type="image/png")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при генерации изображения QR-кода: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/messages/send",
    response_model=SendMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_message(request: SendMessageRequest):
    """
    Отправляет сообщение в чат.
    
    chat_identifier может быть:
    - Username чата (например, @username)
    - ID чата (число)
    
    message - текст сообщения (до 4096 символов).
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )
    
    try:
        result = await client_manager.send_message(
            request.chat_identifier,
            request.message
        )
        return SendMessageResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/messages/edit",
    response_model=EditMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def edit_message(request: EditMessageRequest):
    """
    Редактирует ранее отправленное сообщение в чате.

    chat_identifier может быть:
    - Username чата (например, @username)
    - ID чата (число)
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.edit_message(
            request.chat_identifier,
            request.message_id,
            request.message,
        )
        return EditMessageResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.delete(
    "/messages/delete",
    response_model=DeleteMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def delete_messages(request: DeleteMessagesRequest):
    """
    Удаляет одно или несколько сообщений в чате.

    revoke:
    - True: попытка удалить сообщения для всех участников
    - False: удалить только у текущего аккаунта
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.delete_messages(
            request.chat_identifier,
            request.message_ids,
            request.revoke,
        )
        return DeleteMessagesResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщений: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/messages/forward",
    response_model=ForwardMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def forward_messages(request: ForwardMessagesRequest):
    """
    Пересылает сообщения из одного чата в другой.

    from_chat_identifier - источник сообщений.
    to_chat_identifier - чат назначения.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.forward_messages(
            request.from_chat_identifier,
            request.to_chat_identifier,
            request.message_ids,
        )
        return ForwardMessagesResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщений: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/messages/reply",
    response_model=ReplyMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def reply_message(request: ReplyMessageRequest):
    """
    Отправляет сообщение-ответ на конкретное сообщение в чате.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.reply_message(
            request.chat_identifier,
            request.reply_to_message_id,
            request.message,
        )
        return ReplyMessageResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа на сообщение: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/messages/search",
    response_model=SearchMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def search_messages(request: SearchMessagesRequest):
    """
    Ищет сообщения в указанном чате по текстовому запросу.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )

    try:
        result = await client_manager.search_messages(
            request.chat_identifier,
            request.query,
            request.limit,
        )
        messages = [MessageInfo(**m) for m in result["messages"]]
        return SearchMessagesResponse(
            success=True,
            chat_id=result["chat_id"],
            chat_name=result.get("chat_name"),
            query=result["query"],
            messages=messages,
            total=len(messages),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при поиске сообщений: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/messages/read",
    response_model=MarkMessagesReadResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def mark_messages_read(request: MarkMessagesReadRequest):
    """
    Отмечает сообщения в чате как прочитанные.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )

    try:
        result = await client_manager.mark_messages_read(
            request.chat_identifier,
            request.max_id,
        )
        return MarkMessagesReadResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при отметке сообщений как прочитанных: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/messages/pin",
    response_model=PinMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def pin_message(request: PinMessageRequest):
    """
    Закрепляет или открепляет сообщение в чате.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )

    try:
        result = await client_manager.pin_message(
            request.chat_identifier,
            request.message_id,
            request.unpin,
            request.notify,
        )
        return PinMessageResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при закреплении/откреплении сообщения: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/messages/reaction",
    response_model=MessageReactionResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def set_message_reaction(request: MessageReactionRequest):
    """
    Устанавливает или снимает реакцию на сообщение.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )

    try:
        result = await client_manager.set_message_reaction(
            request.chat_identifier,
            request.message_id,
            request.reaction,
            request.big,
        )
        return MessageReactionResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при установке реакции: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/messages",
    response_model=MessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def get_messages(chat_identifier: str, limit: int = 50):
    """
    Получает последние сообщения из указанного чата.
    
    chat_identifier может быть:
    - Username чата (например, @username)
    - ID чата (число)
    
    limit - максимальное количество сообщений (по умолчанию 50).
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )
    
    try:
        result = await client_manager.get_messages(chat_identifier, limit=limit)
        messages = [MessageInfo(**m) for m in result["messages"]]
        
        return MessagesResponse(
            success=True,
            chat_id=result["chat_id"],
            chat_name=result.get("chat_name"),
            messages=messages,
            total=len(messages),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/messages/media",
    tags=["messages"],
)
async def download_message_media(chat_identifier: str, message_id: int):
    """
    Скачивает медиа по ID сообщения.
    
    Используйте media_id из ответа /messages для message_id.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )
    
    try:
        result = await client_manager.download_media(chat_identifier, message_id)
        headers = {
            "Content-Disposition": f'attachment; filename="{result["filename"]}"'
        }
        return Response(
            content=result["data"],
            media_type=result["content_type"],
            headers=headers,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при скачивании медиа: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Глобальный обработчик исключений"""
    logger.error(f"Необработанное исключение: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": "Внутренняя ошибка сервера",
            "detail": str(exc)
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
