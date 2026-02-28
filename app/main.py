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
    FilterMessagesRequest,
    FilterMessagesResponse,
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
    CreateChatRequest,
    InviteUsersRequest,
    RemoveUsersRequest,
    ArchiveChatResponse,
    FoldersResponse,
    FolderInfo,
    MessageInfo,
    ChatDetailsInfo,
    UpdateChatInfoRequest,
    UserInfo,
    AccountInfo,
    ContactInfo,
    ParticipantInfo,
    UserStatusInfo,
    ManageContactRequest,
    ManageBlockRequest,
    UpdateUsernameRequest,
    UpdateNameRequest,
    UpdateAboutRequest,
    UpdateProfilePhotoRequest,
    SubscribeChannelRequest,
    PublishChannelPostRequest,
    EditChannelPostRequest,
    DeleteChannelPostsRequest,
    MessagesResponse,
    UserInfoResponse,
    AccountInfoResponse,
    ResetSessionsResponse,
    UpdateUsernameResponse,
    UpdateNameResponse,
    UpdateAboutResponse,
    UpdateProfilePhotoResponse,
    ContactsResponse,
    ChatParticipantsResponse,
    ChatAdminsResponse,
    ChatInfoResponse,
    UpdateChatInfoResponse,
    CreateChatResponse,
    InviteUsersResponse,
    RemoveUsersResponse,
    UserStatusResponse,
    ManageContactResponse,
    ManageBlockResponse,
    SubscribeChannelResponse,
    UnsubscribeChannelResponse,
    PublishChannelPostResponse,
    EditChannelPostResponse,
    DeleteChannelPostsResponse,
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
    {
        "name": "users",
        "description": "Работа с данными пользователей",
    },
    {
        "name": "channels",
        "description": "Работа с каналами",
    },
    {
        "name": "account",
        "description": "Управление текущим аккаунтом",
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
    "/chats/create",
    response_model=CreateChatResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def create_chat(request: CreateChatRequest):
    """
    Создает новую группу или канал.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.create_chat(
            type=request.type,
            title=request.title,
            about=request.about,
            user_identifiers=request.user_identifiers,
        )
        return CreateChatResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при создании чата/канала: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/chats/invite",
    response_model=InviteUsersResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def invite_users(request: InviteUsersRequest):
    """
    Приглашает пользователей в группу/супергруппу/канал.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.invite_users(
            chat_identifier=request.chat_identifier,
            user_identifiers=request.user_identifiers,
            fwd_limit=request.fwd_limit,
        )
        return InviteUsersResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при приглашении пользователей: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/chats/remove-users",
    response_model=RemoveUsersResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def remove_users(request: RemoveUsersRequest):
    """
    Исключает пользователей из группы/супергруппы.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.remove_users(
            chat_identifier=request.chat_identifier,
            user_identifiers=request.user_identifiers,
        )
        return RemoveUsersResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при исключении пользователей: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/chats/participants",
    response_model=ChatParticipantsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chat_participants(chat_identifier: str, limit: int = 100, search: str = ""):
    """
    Получает участников группы/супергруппы/канала.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.get_chat_participants(
            chat_identifier=chat_identifier,
            limit=limit,
            search=search,
        )
        participants = [ParticipantInfo(**p) for p in result["participants"]]
        return ChatParticipantsResponse(
            success=True,
            chat_id=result["chat_id"],
            chat_name=result.get("chat_name"),
            participants=participants,
            total=len(participants),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении участников чата: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/chats/admins",
    response_model=ChatAdminsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chat_admins(chat_identifier: str, limit: int = 100, search: str = ""):
    """
    Получает список администраторов группы/супергруппы/канала.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.get_chat_admins(
            chat_identifier=chat_identifier,
            limit=limit,
            search=search,
        )
        admins = [ParticipantInfo(**p) for p in result["admins"]]
        return ChatAdminsResponse(
            success=True,
            chat_id=result["chat_id"],
            chat_name=result.get("chat_name"),
            admins=admins,
            total=len(admins),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении администраторов чата: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/chats/info",
    response_model=ChatInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chat_info(chat_identifier: str):
    """
    Получает расширенную информацию о чате: описание, фото и базовые настройки.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        chat_data = await client_manager.get_chat_info(chat_identifier)
        return ChatInfoResponse(
            success=True,
            chat=ChatDetailsInfo(**chat_data),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении информации о чате: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/chats/info",
    response_model=UpdateChatInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def update_chat_info(request: UpdateChatInfoRequest):
    """
    Изменяет название и/или описание чата.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.update_chat_info(
            chat_identifier=request.chat_identifier,
            title=request.title,
            about=request.about,
        )
        return UpdateChatInfoResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении информации чата: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/users/info",
    response_model=UserInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_user_info(user_identifier: str):
    """
    Получает информацию о пользователе Telegram по username, ID или телефону.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        user_data = await client_manager.get_user_info(user_identifier)
        return UserInfoResponse(
            success=True,
            user=UserInfo(**user_data),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении информации о пользователе: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/users/contacts",
    response_model=ContactsResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_contacts(limit: int = 200):
    """
    Получает список контактов текущего аккаунта.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        contacts_data = await client_manager.get_contacts(limit=limit)
        contacts = [ContactInfo(**item) for item in contacts_data]
        return ContactsResponse(
            success=True,
            contacts=contacts,
            total=len(contacts),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении списка контактов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/users/contacts/manage",
    response_model=ManageContactResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def manage_contact(request: ManageContactRequest):
    """
    Добавляет или удаляет контакт.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.manage_contact(
            action=request.action,
            user_identifier=request.user_identifier,
            phone=request.phone,
            first_name=request.first_name,
            last_name=request.last_name,
        )
        return ManageContactResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении контакта: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/users/block",
    response_model=ManageBlockResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def manage_block(request: ManageBlockRequest):
    """
    Блокирует или разблокирует пользователя.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.manage_block(
            action=request.action,
            user_identifier=request.user_identifier,
        )
        return ManageBlockResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при блокировке/разблокировке пользователя: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/users/status",
    response_model=UserStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_user_status(user_identifier: str):
    """
    Получает текущий статус пользователя (онлайн/оффлайн и др.).
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        status_data = await client_manager.get_user_status(user_identifier)
        return UserStatusResponse(
            success=True,
            user_status=UserStatusInfo(**status_data),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении статуса пользователя: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/account/me",
    response_model=AccountInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def get_account_me():
    """
    Получает информацию о текущем авторизованном аккаунте.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        account_data = await client_manager.get_me_info()
        return AccountInfoResponse(
            success=True,
            account=AccountInfo(**account_data),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении информации о своем аккаунте: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/account/username",
    response_model=UpdateUsernameResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_username(request: UpdateUsernameRequest):
    """
    Изменяет username текущего аккаунта.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.update_username(request.username)
        return UpdateUsernameResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении username: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/account/name",
    response_model=UpdateNameResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_name(request: UpdateNameRequest):
    """
    Изменяет имя и фамилию текущего аккаунта.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.update_name(
            request.first_name,
            request.last_name,
        )
        return UpdateNameResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении имени/фамилии: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/account/about",
    response_model=UpdateAboutResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_about(request: UpdateAboutRequest):
    """
    Изменяет биографию (about) текущего аккаунта.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.update_about(request.about)
        return UpdateAboutResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении биографии: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/account/photo",
    response_model=UpdateProfilePhotoResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_photo(request: UpdateProfilePhotoRequest):
    """
    Изменяет фото профиля текущего аккаунта.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.update_profile_photo(request.photo_base64)
        return UpdateProfilePhotoResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении фото профиля: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/account/sessions/reset",
    response_model=ResetSessionsResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def reset_account_sessions():
    """
    Отключает все другие устройства (сессии), кроме текущей.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.reset_other_sessions()
        return ResetSessionsResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отключении других сессий: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/channels/subscribe",
    response_model=SubscribeChannelResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def subscribe_channel(request: SubscribeChannelRequest):
    """
    Подписывает текущий аккаунт на канал.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.subscribe_channel(request.channel_identifier)
        return SubscribeChannelResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при подписке на канал: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/channels/unsubscribe",
    response_model=UnsubscribeChannelResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def unsubscribe_channel(request: SubscribeChannelRequest):
    """
    Отписывает текущий аккаунт от канала.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.unsubscribe_channel(request.channel_identifier)
        return UnsubscribeChannelResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отписке от канала: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/channels/posts",
    response_model=MessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def get_channel_posts(channel_identifier: str, limit: int = 50):
    """
    Получает последние посты из канала.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.get_messages(channel_identifier, limit=limit)
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
        logger.error(f"Ошибка при получении постов канала: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/posts/publish",
    response_model=PublishChannelPostResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def publish_channel_post(request: PublishChannelPostRequest):
    """
    Публикует пост в канал.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.publish_channel_post(
            request.channel_identifier,
            request.message,
        )
        return PublishChannelPostResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при публикации поста в канал: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.patch(
    "/channels/posts/edit",
    response_model=EditChannelPostResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def edit_channel_post(request: EditChannelPostRequest):
    """
    Редактирует пост в канале.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.edit_channel_post(
            request.channel_identifier,
            request.message_id,
            request.message,
        )
        return EditChannelPostResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании поста канала: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/channels/posts",
    response_model=DeleteChannelPostsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def delete_channel_posts(request: DeleteChannelPostsRequest):
    """
    Удаляет один или несколько постов в канале.
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify"
        )

    try:
        result = await client_manager.delete_channel_posts(
            request.channel_identifier,
            request.message_ids,
        )
        return DeleteChannelPostsResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении постов канала: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
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
    "/messages/filter",
    response_model=FilterMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def filter_messages(request: FilterMessagesRequest):
    """
    Фильтрует сообщения в чате по типу (text/media/photo/video/document/audio/voice/sticker/service).
    """
    if not client_manager.is_connected():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /auth/login и /auth/verify",
        )

    try:
        result = await client_manager.filter_messages(
            request.chat_identifier,
            request.message_type,
            request.limit,
        )
        messages = [MessageInfo(**m) for m in result["messages"]]
        return FilterMessagesResponse(
            success=True,
            chat_id=result["chat_id"],
            chat_name=result.get("chat_name"),
            message_type=result["message_type"],
            messages=messages,
            total=len(messages),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при фильтрации сообщений: {e}")
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
