from contextlib import asynccontextmanager
from pathlib import Path
import csv
import io
from typing import List

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from app.models import (
    LoginRequest,
    LoginResponse,
    VerifyRequest,
    VerifyResponse,
    PasswordRequest,
    PasswordResponse,
    ChatsResponse,
    SendMessageRequest,
    SendMediaRequest,
    SendVoiceRequest,
    SendStickerGifRequest,
    SendLocationRequest,
    SendContactMessageRequest,
    SendMessageResponse,
    SendMediaResponse,
    SendVoiceResponse,
    SendStickerGifResponse,
    SendLocationResponse,
    SendContactMessageResponse,
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
    MessageViewsResponse,
    MarkMessagesReadRequest,
    MarkMessagesReadResponse,
    PinMessageRequest,
    PinMessageResponse,
    MessageReactionRequest,
    MessageReactionResponse,
    ChatInfo,
    FolderChatsRequest,
    LeadSearchFolderRequest,
    LeadSearchFolderResponse,
    ArchiveChatRequest,
    CreateChatRequest,
    InviteUsersRequest,
    RemoveUsersRequest,
    UpdateParticipantPermissionsRequest,
    ArchiveChatResponse,
    FoldersResponse,
    FolderInfo,
    MessageInfo,
    ChatDetailsInfo,
    UpdateChatInfoRequest,
    UpdateChatPhotoRequest,
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
    UpdateChatPhotoResponse,
    CreateChatResponse,
    InviteUsersResponse,
    RemoveUsersResponse,
    UpdateParticipantPermissionsResponse,
    UserStatusResponse,
    ManageContactResponse,
    ManageBlockResponse,
    SendBotCommandRequest,
    SendBotCommandResponse,
    BotInlineButtonClickRequest,
    BotInlineButtonClickResponse,
    SubscribeChannelResponse,
    UnsubscribeChannelResponse,
    ChannelSearchResponse,
    JoinChannelResponse,
    ChannelCommentsStatusResponse,
    ChannelCommentsResponse,
    PublishChannelPostResponse,
    EditChannelPostResponse,
    DeleteChannelPostsResponse,
    CollectPostsRequest,
    CollectPostsResponse,
    CollectedPostItem,
    CollectCommentsRequest,
    CollectCommentsResponse,
    CollectedCommentItem,
    ChannelHealthResponse,
    DiscussionScoreResponse,
    BusinessFitResponse,
    CampaignScoreResponse,
    RankedChannelsResponse,
    RankedChannelItem,
    OpportunityPostsResponse,
    OpportunityPostItem,
    SessionInfo,
    SessionListResponse,
    SessionStatusResponse,
    DeleteSessionResponse,
    CompanyCreate,
    CompanyUpdate,
    CompanyInfo,
    CompanyResponse,
    CompanyListResponse,
    DeleteCompanyResponse,
    LeadCreate,
    LeadInfo,
    LeadResponse,
    LeadListResponse,
)
from app.storage import ChannelAnalyticsRepo, CompanyRepo, LeadRepo, SessionRepo
from app.telegram_client import MultiSessionManager
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
client_manager: MultiSessionManager | None = None
session_repo: SessionRepo | None = None
company_repo: CompanyRepo | None = None
lead_repo: LeadRepo | None = None
channel_analytics_repo: ChannelAnalyticsRepo | None = None
INDEX_HTML_PATH = Path(__file__).parent / "static" / "index.html"


tags_metadata = [
    {
        "name": "system",
        "description": "Системные эндпоинты и статус сервиса",
    },
    {
        "name": "auth",
        "description": "Авторизация по номеру телефона и 2FA",
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
        "name": "bots",
        "description": "Базовая работа с ботами",
    },
    {
        "name": "account",
        "description": "Управление текущим аккаунтом",
    },
    {
        "name": "companies",
        "description": "Настройка компаний для CRM",
    },
    {
        "name": "leads",
        "description": "Локальная база найденных Telegram-лидов",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    global client_manager, session_repo, company_repo, lead_repo, channel_analytics_repo

    # При старте приложения
    logger.info("Инициализация локального storage и MultiSessionManager...")
    session_repo = SessionRepo()
    company_repo = CompanyRepo()
    lead_repo = LeadRepo()
    channel_analytics_repo = ChannelAnalyticsRepo()
    client_manager = MultiSessionManager(
        session_repo=session_repo,
        channel_analytics_repo=channel_analytics_repo,
    )
    app.state.session_repo = session_repo
    app.state.company_repo = company_repo
    app.state.lead_repo = lead_repo
    app.state.channel_analytics_repo = channel_analytics_repo
    app.state.client_manager = client_manager
    
    yield
    
    # При остановке приложения
    logger.info("Отключение Telegram клиента...")
    if client_manager is not None:
        await client_manager.disconnect()


app = FastAPI(
    title="Telegram REST API",
    description="REST API для работы с Telegram через Telethon",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def crm_frontend():
    """Минимальный frontend для настройки компаний."""
    return HTMLResponse(INDEX_HTML_PATH.read_text(encoding="utf-8"))


@app.get("/api/status", tags=["system"])
async def api_status():
    """Статус API и локального storage."""
    authorized = client_manager.is_connected() if client_manager is not None else False
    storage_status = "unavailable"
    if session_repo is not None:
        try:
            session_repo.list_all()
            storage_status = "ok"
        except Exception as e:
            logger.warning("SQLite health-check failed: %s", e)

    return {
        "message": "Telegram REST API",
        "status": "running",
        "authorized": authorized,
        "storage": storage_status,
    }


@app.middleware("http")
async def bind_session_context(request, call_next):
    """Привязывает session_id из URL к текущему запросу."""
    if client_manager is None:
        return await call_next(request)

    original_session_id = client_manager.default_session_id
    path_parts = request.url.path.strip("/").split("/")
    if len(path_parts) >= 2 and path_parts[0] == "sessions" and path_parts[1]:
        client_manager.default_session_id = path_parts[1]

    try:
        return await call_next(request)
    finally:
        client_manager.default_session_id = original_session_id


@app.get(
    "/api/companies",
    response_model=CompanyListResponse,
    status_code=status.HTTP_200_OK,
    tags=["companies"],
)
async def list_companies():
    """Возвращает список компаний."""
    if company_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CompanyRepo не инициализирован",
        )
    rows = company_repo.list_all()
    companies = [CompanyInfo(**row) for row in rows]
    return CompanyListResponse(success=True, companies=companies, total=len(companies))


@app.post(
    "/api/companies",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["companies"],
)
async def create_company(request: CompanyCreate):
    """Создает компанию."""
    if company_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CompanyRepo не инициализирован",
        )
    row = company_repo.create(request.model_dump())
    return CompanyResponse(
        success=True,
        company=CompanyInfo(**row),
        message="Компания создана",
    )


@app.get(
    "/api/companies/{company_id}",
    response_model=CompanyResponse,
    status_code=status.HTTP_200_OK,
    tags=["companies"],
)
async def get_company(company_id: int):
    """Возвращает компанию по ID."""
    if company_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CompanyRepo не инициализирован",
        )
    row = company_repo.get(company_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания #{company_id} не найдена",
        )
    return CompanyResponse(
        success=True,
        company=CompanyInfo(**row),
        message="Компания найдена",
    )


@app.patch(
    "/api/companies/{company_id}",
    response_model=CompanyResponse,
    status_code=status.HTTP_200_OK,
    tags=["companies"],
)
async def update_company(company_id: int, request: CompanyUpdate):
    """Обновляет компанию."""
    if company_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CompanyRepo не инициализирован",
        )
    row = company_repo.update(
        company_id,
        request.model_dump(exclude_unset=True),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания #{company_id} не найдена",
        )
    return CompanyResponse(
        success=True,
        company=CompanyInfo(**row),
        message="Компания обновлена",
    )


@app.delete(
    "/api/companies/{company_id}",
    response_model=DeleteCompanyResponse,
    status_code=status.HTTP_200_OK,
    tags=["companies"],
)
async def delete_company(company_id: int):
    """Удаляет компанию."""
    if company_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CompanyRepo не инициализирован",
        )
    deleted = company_repo.delete(company_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания #{company_id} не найдена",
        )
    return DeleteCompanyResponse(
        success=True,
        company_id=company_id,
        message="Компания удалена",
    )


@app.get(
    "/api/leads",
    response_model=LeadListResponse,
    status_code=status.HTTP_200_OK,
    tags=["leads"],
)
async def list_leads(status_filter: str | None = Query(None, alias="status")):
    """Возвращает сохраненных Telegram-лидов."""
    if lead_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LeadRepo не инициализирован",
        )
    rows = lead_repo.list_all(status=status_filter)
    leads = [LeadInfo(**row) for row in rows]
    return LeadListResponse(success=True, leads=leads, total=len(leads))


@app.post(
    "/api/leads",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["leads"],
)
async def save_lead(request: LeadCreate):
    """Создает или обновляет Telegram-лида по url."""
    if lead_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LeadRepo не инициализирован",
        )
    row = lead_repo.upsert(request.model_dump())
    return LeadResponse(
        success=True,
        lead=LeadInfo(**row),
        message="Лид сохранен",
    )


@app.get(
    "/sessions",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def list_sessions():
    """Возвращает список сохраненных сессий."""
    if session_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SessionRepo не инициализирован",
        )
    try:
        rows = session_repo.list_all()
        sessions = [SessionInfo(**row) for row in rows]
        return SessionListResponse(success=True, sessions=sessions, total=len(sessions))
    except Exception as e:
        logger.error(f"Ошибка при получении списка сессий: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/sessions/{session_id}",
    response_model=SessionStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def get_session_status(session_id: str):
    """Возвращает статус конкретной сессии."""
    if session_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SessionRepo не инициализирован",
        )
    try:
        row = session_repo.get(session_id)
        if row is None:
            return SessionStatusResponse(
                success=False,
                session=None,
                message=f"Сессия '{session_id}' не найдена",
            )
        return SessionStatusResponse(
            success=True,
            session=SessionInfo(**row),
            message="Сессия найдена",
        )
    except Exception as e:
        logger.error(f"Ошибка при получении статуса сессии: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/sessions/{session_id}",
    response_model=DeleteSessionResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def delete_session(session_id: str):
    """Удаляет сессию по session_id."""
    if session_repo is None or client_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис сессий не инициализирован",
        )
    try:
        cached_client = client_manager._clients.pop(session_id, None)
        if cached_client is not None:
            await cached_client.disconnect()

        auth_client = client_manager._auth_clients.pop(session_id, None)
        if auth_client is not None:
            await auth_client.disconnect()

        client_manager._authorized_sessions.discard(session_id)
        client_manager._auth_state.pop(session_id, None)

        deleted = session_repo.delete(session_id)
        if not deleted:
            return DeleteSessionResponse(
                success=False,
                session_id=session_id,
                message=f"Сессия '{session_id}' не найдена",
            )

        return DeleteSessionResponse(
            success=True,
            session_id=session_id,
            message="Сессия удалена",
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении сессии: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/sessions/{session_id}/auth/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def login(session_id: str, request: LoginRequest):
    """
    Отправляет код подтверждения на номер телефона.
    
    Номер телефона должен быть в международном формате (например, +79991234567).
    Код придет в приложение Telegram или по SMS (если указан force_sms=true).
    """
    try:
        result = await client_manager.send_code(
            session_id=session_id,
            phone=request.phone,
            force_sms=request.force_sms,
        )
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
    "/sessions/{session_id}/auth/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def verify(session_id: str, request: VerifyRequest):
    """
    Подтверждает код авторизации.
    
    Если требуется пароль двухфакторной аутентификации, вернется password_required=true.
    В этом случае используйте /sessions/{session_id}/auth/password для завершения авторизации.
    """
    try:
        result = await client_manager.sign_in(
            session_id=session_id,
            phone=request.phone,
            code=request.code,
        )
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
    "/sessions/{session_id}/auth/password",
    response_model=PasswordResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
)
async def password(session_id: str, request: PasswordRequest):
    """
    Вводит пароль двухфакторной аутентификации.
    
    Используйте этот endpoint только после того, как /sessions/{session_id}/auth/verify вернул password_required=true.
    """
    try:
        result = await client_manager.sign_in_password(
            session_id=session_id,
            password=request.password,
        )
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
    "/sessions/{session_id}/chats",
    response_model=ChatsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chats(session_id: str, limit: int = 100):
    """
    Получает список всех диалогов (чатов).
    
    Включает личные чаты, группы, супергруппы и каналы.
    
    Args:
        limit: Максимальное количество чатов (по умолчанию 100)
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )
    
    try:
        dialogs = await client_manager.get_dialogs(session_id=session_id, limit=limit)
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
    "/sessions/{session_id}/chats/folders",
    response_model=FoldersResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_folders(session_id: str):
    """
    Получает список всех доступных папок (dialog filters).
    
    Используйте этот endpoint, чтобы узнать названия ваших папок,
    а затем используйте /chats/folder для получения чатов из конкретной папки.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/folders/lead-search",
    response_model=LeadSearchFolderResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def upsert_lead_search_folder(session_id: str, request: LeadSearchFolderRequest):
    """
    Создает/обновляет Telegram-папку Lead Search 1 и добавляет туда каналы.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.upsert_lead_search_folder(
            channel_identifiers=request.channel_identifiers,
            folder_name=request.folder_name,
            session_id=session_id,
        )
        added = [ChatInfo(**chat) for chat in result["added"]]
        return LeadSearchFolderResponse(
            success=True,
            folder_name=result["folder_name"],
            folder_id=result["folder_id"],
            added=added,
            skipped=result["skipped"],
            total_added=len(added),
            message=result["message"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при обновлении папки лидов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/chats/folder",
    response_model=ChatsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chats_by_folder(session_id: str, request: FolderChatsRequest):
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
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/archive",
    response_model=ArchiveChatResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def archive_chat(session_id: str, request: ArchiveChatRequest):
    """
    Архивирует чат или возвращает его из архива.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/create",
    response_model=CreateChatResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def create_chat(session_id: str, request: CreateChatRequest):
    """
    Создает новую группу или канал.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/invite",
    response_model=InviteUsersResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def invite_users(session_id: str, request: InviteUsersRequest):
    """
    Приглашает пользователей в группу/супергруппу/канал.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/remove-users",
    response_model=RemoveUsersResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def remove_users(session_id: str, request: RemoveUsersRequest):
    """
    Исключает пользователей из группы/супергруппы.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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


@app.patch(
    "/sessions/{session_id}/chats/participants/permissions",
    response_model=UpdateParticipantPermissionsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def update_participant_permissions(session_id: str, request: UpdateParticipantPermissionsRequest):
    """
    Изменяет права участника в супергруппе (mute/unmute).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.update_participant_permissions(
            chat_identifier=request.chat_identifier,
            user_identifier=request.user_identifier,
            mute=request.mute,
            until_date=request.until_date,
        )
        return UpdateParticipantPermissionsResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении прав участника: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/sessions/{session_id}/chats/participants",
    response_model=ChatParticipantsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chat_participants(session_id: str, chat_identifier: str, limit: int = 100, search: str = ""):
    """
    Получает участников группы/супергруппы/канала.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/admins",
    response_model=ChatAdminsResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chat_admins(session_id: str, chat_identifier: str, limit: int = 100, search: str = ""):
    """
    Получает список администраторов группы/супергруппы/канала.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/info",
    response_model=ChatInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def get_chat_info(session_id: str, chat_identifier: str):
    """
    Получает расширенную информацию о чате: описание, фото и базовые настройки.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/chats/info",
    response_model=UpdateChatInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def update_chat_info(session_id: str, request: UpdateChatInfoRequest):
    """
    Изменяет название и/или описание чата.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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


@app.patch(
    "/sessions/{session_id}/chats/photo",
    response_model=UpdateChatPhotoResponse,
    status_code=status.HTTP_200_OK,
    tags=["chats"],
)
async def update_chat_photo(session_id: str, request: UpdateChatPhotoRequest):
    """
    Устанавливает фото чата.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.update_chat_photo(
            chat_identifier=request.chat_identifier,
            photo_base64=request.photo_base64,
        )
        return UpdateChatPhotoResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при установке фото чата: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/sessions/{session_id}/users/info",
    response_model=UserInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_user_info(session_id: str, user_identifier: str):
    """
    Получает информацию о пользователе Telegram по username, ID или телефону.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/users/contacts",
    response_model=ContactsResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_contacts(session_id: str, limit: int = 200):
    """
    Получает список контактов текущего аккаунта.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/users/contacts/manage",
    response_model=ManageContactResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def manage_contact(session_id: str, request: ManageContactRequest):
    """
    Добавляет или удаляет контакт.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/users/block",
    response_model=ManageBlockResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def manage_block(session_id: str, request: ManageBlockRequest):
    """
    Блокирует или разблокирует пользователя.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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


@app.post(
    "/sessions/{session_id}/bots/command",
    response_model=SendBotCommandResponse,
    status_code=status.HTTP_200_OK,
    tags=["bots"],
)
async def send_bot_command(session_id: str, request: SendBotCommandRequest):
    """
    Отправляет команду боту (например, /start).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.send_bot_command(
            bot_identifier=request.bot_identifier,
            command=request.command,
        )
        return SendBotCommandResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке команды боту: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/bots/buttons/click",
    response_model=BotInlineButtonClickResponse,
    status_code=status.HTTP_200_OK,
    tags=["bots"],
)
async def click_bot_inline_button(session_id: str, request: BotInlineButtonClickRequest):
    """
    Нажимает inline-кнопку в сообщении бота.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.click_inline_button(
            chat_identifier=request.chat_identifier,
            message_id=request.message_id,
            row=request.row,
            col=request.col,
        )
        return BotInlineButtonClickResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при нажатии inline-кнопки: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/sessions/{session_id}/users/status",
    response_model=UserStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_user_status(session_id: str, user_identifier: str):
    """
    Получает текущий статус пользователя (онлайн/оффлайн и др.).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/account/me",
    response_model=AccountInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def get_account_me(session_id: str):
    """
    Получает информацию о текущем авторизованном аккаунте.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/account/username",
    response_model=UpdateUsernameResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_username(session_id: str, request: UpdateUsernameRequest):
    """
    Изменяет username текущего аккаунта.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/account/name",
    response_model=UpdateNameResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_name(session_id: str, request: UpdateNameRequest):
    """
    Изменяет имя и фамилию текущего аккаунта.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/account/about",
    response_model=UpdateAboutResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_about(session_id: str, request: UpdateAboutRequest):
    """
    Изменяет биографию (about) текущего аккаунта.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/account/photo",
    response_model=UpdateProfilePhotoResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def update_account_photo(session_id: str, request: UpdateProfilePhotoRequest):
    """
    Изменяет фото профиля текущего аккаунта.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/account/sessions/reset",
    response_model=ResetSessionsResponse,
    status_code=status.HTTP_200_OK,
    tags=["account"],
)
async def reset_account_sessions(session_id: str):
    """
    Отключает все другие устройства (сессии), кроме текущей.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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


@app.get(
    "/sessions/{session_id}/channels/search",
    response_model=ChannelSearchResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def search_channels(session_id: str, query: str, limit: int = 20):
    """
    Ищет публичные каналы и супергруппы в Telegram.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.search_channels(
            query=query,
            limit=limit,
            session_id=session_id,
        )
        return ChannelSearchResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при поиске каналов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/channels/join",
    response_model=JoinChannelResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def join_channel(session_id: str, request: SubscribeChannelRequest):
    """
    Входит в публичный канал или отправляет заявку по private invite link.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.join_channel(
            request.channel_identifier,
            session_id=session_id,
        )
        return JoinChannelResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при входе в канал: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/sessions/{session_id}/channels/comments/status",
    response_model=ChannelCommentsStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def get_channel_comments_status(
    session_id: str,
    channel_identifier: str,
    message_id: int | None = None,
):
    """
    Проверяет, включены ли комментарии у канала или конкретного поста.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.get_channel_comments_status(
            channel_identifier=channel_identifier,
            message_id=message_id,
            session_id=session_id,
        )
        return ChannelCommentsStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при проверке комментариев: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get(
    "/sessions/{session_id}/channels/posts/comments",
    response_model=ChannelCommentsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def get_post_comments(
    session_id: str,
    channel_identifier: str,
    message_id: int,
    limit: int = 50,
):
    """
    Получает комментарии к конкретному посту канала.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.get_post_comments(
            channel_identifier=channel_identifier,
            message_id=message_id,
            limit=limit,
            session_id=session_id,
        )
        comments = [MessageInfo(**m) for m in result["comments"]]
        return ChannelCommentsResponse(
            success=True,
            channel_id=result["channel_id"],
            channel_name=result.get("channel_name"),
            message_id=result["message_id"],
            comments=comments,
            total=len(comments),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при получении комментариев: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/channels/subscribe",
    response_model=SubscribeChannelResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def subscribe_channel(session_id: str, request: SubscribeChannelRequest):
    """
    Подписывает текущий аккаунт на канал.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.subscribe_channel(
            request.channel_identifier,
            session_id=session_id,
        )
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
    "/sessions/{session_id}/channels/unsubscribe",
    response_model=UnsubscribeChannelResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def unsubscribe_channel(session_id: str, request: SubscribeChannelRequest):
    """
    Отписывает текущий аккаунт от канала.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.unsubscribe_channel(
            request.channel_identifier,
            session_id=session_id,
        )
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
    "/sessions/{session_id}/channels/posts",
    response_model=MessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def get_channel_posts(session_id: str, channel_identifier: str, limit: int = 50):
    """
    Получает последние посты из канала.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/channels/posts/publish",
    response_model=PublishChannelPostResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def publish_channel_post(session_id: str, request: PublishChannelPostRequest):
    """
    Публикует пост в канал.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/channels/posts/edit",
    response_model=EditChannelPostResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def edit_channel_post(session_id: str, request: EditChannelPostRequest):
    """
    Редактирует пост в канале.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/channels/posts",
    response_model=DeleteChannelPostsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def delete_channel_posts(session_id: str, request: DeleteChannelPostsRequest):
    """
    Удаляет один или несколько постов в канале.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/channels/{channel_id}/collect-posts",
    response_model=CollectPostsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def collect_channel_posts(
    channel_id: str,
    request: CollectPostsRequest,
    session_id: str | None = Query(None),
):
    """
    Собирает посты канала, сохраняет метрики для аналитики и обновляет профиль.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )
    if not channel_analytics_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ChannelAnalyticsRepo не инициализирован",
        )

    try:
        result = await client_manager.collect_channel_posts(
            channel_identifier=channel_id,
            limit=request.limit,
            exclude_forwards=request.exclude_forwards,
            exclude_ads=request.exclude_ads,
            session_id=active_session_id,
        )
        posts = [CollectedPostItem(**item) for item in result["posts"]]
        return CollectPostsResponse(
            success=True,
            channel_id=result["channel_id"],
            channel_username=result["channel_username"],
            posts_analyzed=result["posts_analyzed"],
            posts=posts,
            message=result["message"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при сборе постов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/{channel_id}/collect-comments",
    response_model=CollectCommentsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def collect_channel_comments(
    channel_id: str,
    request: CollectCommentsRequest,
    session_id: str | None = Query(None),
):
    """
    Собирает комментарии к последним постам канала для аналитики.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )
    if not channel_analytics_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ChannelAnalyticsRepo не инициализирован",
        )

    try:
        result = await client_manager.collect_channel_comments(
            channel_identifier=channel_id,
            posts_limit=request.posts_limit,
            comments_per_post=request.comments_per_post,
            session_id=active_session_id,
        )
        comments = [CollectedCommentItem(**item) for item in result["comments"]]
        return CollectCommentsResponse(
            success=True,
            channel_id=result["channel_id"],
            channel_username=result["channel_username"],
            posts_considered=result["posts_considered"],
            total_comments=result["total_comments"],
            comments=comments,
            message=result["message"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при сборе комментариев: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/{channel_id}/refresh-metrics",
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def refresh_channel_metrics(channel_id: str, session_id: str | None = Query(None)):
    """
    Полный пересчёт метрик: сбор постов, комментариев, health, discussion,
    business fit и campaign score.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )
    if not channel_analytics_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ChannelAnalyticsRepo не инициализирован",
        )

    try:
        result = await client_manager.refresh_channel_metrics(
            channel_identifier=channel_id,
            session_id=active_session_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при пересчёте метрик: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/{channel_id}/score-health",
    response_model=ChannelHealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def score_channel_health(channel_id: str, session_id: str | None = Query(None)):
    """
    Считает метрики просмотра и вовлечения для канала.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )

    try:
        result = await client_manager.score_channel_health(
            channel_identifier=channel_id,
            session_id=active_session_id,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Недостаточно данных"),
            )
        return ChannelHealthResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при расчёте channel health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/{channel_id}/score-discussion",
    response_model=DiscussionScoreResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def score_channel_discussion(channel_id: str, session_id: str | None = Query(None)):
    """
    Считает метрики комментариев и обсуждаемости канала.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )

    try:
        result = await client_manager.score_channel_discussion(
            channel_identifier=channel_id,
            session_id=active_session_id,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Недостаточно данных"),
            )
        return DiscussionScoreResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при расчёте discussion score: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/{channel_id}/score-business-fit",
    response_model=BusinessFitResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def score_business_fit(channel_id: str, session_id: str | None = Query(None)):
    """
    Оценивает нишу, монетизацию и pain markers в канале.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )

    try:
        result = await client_manager.score_business_fit(
            channel_identifier=channel_id,
            session_id=active_session_id,
        )
        return BusinessFitResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при расчёте business fit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/channels/{channel_id}/score-campaign",
    response_model=CampaignScoreResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def score_campaign(channel_id: str, session_id: str | None = Query(None)):
    """
    Считает итоговый campaign score и рекомендует действие.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )

    try:
        result = await client_manager.score_campaign(
            channel_identifier=channel_id,
            session_id=active_session_id,
        )
        return CampaignScoreResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при расчёте campaign score: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/channels/ranked",
    response_model=RankedChannelsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def get_ranked_channels(
    sort: str = Query("campaign_score"),
    min_score: float = Query(0.0, ge=0.0),
    recommended_action: str | None = None,
):
    """
    Возвращает ранжированный список каналов по campaign_score и параметрам фильтра.
    """
    if not client_manager or not channel_analytics_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics repository не инициализирован",
        )

    try:
        rows = channel_analytics_repo.list_ranked_channels(
            min_score=min_score,
            sort=sort,
            recommended_action=recommended_action,
        )
        channels: List[RankedChannelItem] = [
            RankedChannelItem(
                title=row.get("title"),
                username=row.get("channel_username"),
                url=row.get("url"),
                subscribers_count=row.get("subscribers_count"),
                median_views_30=row.get("median_views"),
                view_rate=row.get("view_rate"),
                posts_per_week=row.get("posts_per_week"),
                comments_enabled=bool(row.get("comments_enabled")),
                median_comments_30=row.get("median_comments"),
                comment_rate=row.get("comment_rate"),
                unique_commenters_30=row.get("unique_commenters"),
                niche=row.get("niche"),
                monetization_signals=row.get("monetization_signals"),
                lead_score=float(row.get("campaign_score") or 0.0),
                campaign_score=float(row.get("campaign_score") or 0.0),
                recommended_action=row.get("recommended_action"),
                reason=row.get("reason"),
                last_post_at=row.get("last_post_at"),
            )
            for row in rows
        ]
        return RankedChannelsResponse(
            success=True,
            channels=channels,
            total=len(channels),
        )
    except Exception as e:
        logger.error(f"Ошибка при выдаче ranked channels: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/channels/{channel_id}/opportunity-posts",
    response_model=OpportunityPostsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def get_opportunity_posts(channel_id: str, session_id: str | None = Query(None)):
    """
    Возвращает список постов канала с лучшей вероятностью для захода комментариями.
    """
    active_session_id = session_id or client_manager.default_session_id
    if not client_manager or not client_manager.is_connected(active_session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )

    try:
        result = await client_manager.opportunity_posts(
            channel_identifier=channel_id,
            session_id=active_session_id,
        )
        posts = [OpportunityPostItem(**item) for item in result["posts"]]
        return OpportunityPostsResponse(
            success=True,
            channel_id=result["channel_id"],
            channel_username=result["channel_username"],
            posts=posts,
            total=result["total"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка получения opportunity posts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/channels/export-campaign-analysis",
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def export_campaign_analysis(
    min_score: float = Query(0.0, ge=0.0),
    format: str = Query("csv"),
    recommended_action: str | None = None,
):
    """
    Экспортирует ранжированный список в CSV.
    """
    if not client_manager or not channel_analytics_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics repository не инициализирован",
        )
    if format.lower() != "csv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживается только format=csv",
        )

    try:
        rows = channel_analytics_repo.list_ranked_channels(
            min_score=min_score,
            sort="campaign_score",
            recommended_action=recommended_action,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        header = [
            "title",
            "username",
            "url",
            "subscribers_count",
            "median_views_30",
            "view_rate",
            "posts_per_week",
            "comments_enabled",
            "median_comments_30",
            "comment_rate",
            "unique_commenters_30",
            "niche",
            "monetization_signals",
            "campaign_score",
            "recommended_action",
            "reason",
            "suggested_ai_product",
        ]
        writer.writerow(header)
        for row in rows:
            writer.writerow(
                [
                    row.get("title"),
                    row.get("channel_username"),
                    row.get("url"),
                    row.get("subscribers_count") or 0,
                    row.get("median_views") or 0,
                    row.get("view_rate") or 0,
                    row.get("posts_per_week") or 0,
                    int(bool(row.get("comments_enabled"))),
                    row.get("median_comments") or 0,
                    row.get("comment_rate") or 0,
                    row.get("unique_commenters") or 0,
                    row.get("niche"),
                    row.get("monetization_signals"),
                    row.get("campaign_score") or 0,
                    row.get("recommended_action"),
                    row.get("reason"),
                    row.get("suggested_ai_product"),
                ]
            )

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=campaign_analysis.csv"
            },
        )
    except Exception as e:
        logger.error(f"Ошибка экспорта campaign analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/sessions/{session_id}/messages/send",
    response_model=SendMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_message(session_id: str, request: SendMessageRequest):
    """
    Отправляет сообщение в чат.
    
    chat_identifier может быть:
    - Username чата (например, @username)
    - ID чата (число)
    
    message - текст сообщения (до 4096 символов).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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


@app.post(
    "/sessions/{session_id}/messages/send-media",
    response_model=SendMediaResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_media(session_id: str, request: SendMediaRequest):
    """
    Отправляет медиафайл в чат (фото/видео/аудио/документ).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.send_media(
            chat_identifier=request.chat_identifier,
            file_base64=request.file_base64,
            file_name=request.file_name,
            caption=request.caption,
        )
        return SendMediaResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке медиа: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/messages/send-voice",
    response_model=SendVoiceResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_voice(session_id: str, request: SendVoiceRequest):
    """
    Отправляет голосовое сообщение в чат.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.send_voice(
            chat_identifier=request.chat_identifier,
            voice_base64=request.voice_base64,
            file_name=request.file_name,
            caption=request.caption,
        )
        return SendVoiceResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке голосового сообщения: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/messages/send-sticker-gif",
    response_model=SendStickerGifResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_sticker_gif(session_id: str, request: SendStickerGifRequest):
    """
    Отправляет стикер или GIF в чат.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.send_sticker_gif(
            chat_identifier=request.chat_identifier,
            media_kind=request.media_kind,
            file_base64=request.file_base64,
            file_name=request.file_name,
            emoji=request.emoji,
            caption=request.caption,
        )
        return SendStickerGifResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке стикера/GIF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/messages/send-location",
    response_model=SendLocationResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_location(session_id: str, request: SendLocationRequest):
    """
    Отправляет геолокацию в чат.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.send_location(
            chat_identifier=request.chat_identifier,
            latitude=request.latitude,
            longitude=request.longitude,
            caption=request.caption,
        )
        return SendLocationResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке геолокации: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.post(
    "/sessions/{session_id}/messages/send-contact",
    response_model=SendContactMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def send_contact_message(session_id: str, request: SendContactMessageRequest):
    """
    Отправляет контакт в чат.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    try:
        result = await client_manager.send_contact_message(
            chat_identifier=request.chat_identifier,
            phone_number=request.phone_number,
            first_name=request.first_name,
            last_name=request.last_name,
            caption=request.caption,
        )
        return SendContactMessageResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке контакта: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.patch(
    "/sessions/{session_id}/messages/edit",
    response_model=EditMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def edit_message(session_id: str, request: EditMessageRequest):
    """
    Редактирует ранее отправленное сообщение в чате.

    chat_identifier может быть:
    - Username чата (например, @username)
    - ID чата (число)
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/messages/delete",
    response_model=DeleteMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def delete_messages(session_id: str, request: DeleteMessagesRequest):
    """
    Удаляет одно или несколько сообщений в чате.

    revoke:
    - True: попытка удалить сообщения для всех участников
    - False: удалить только у текущего аккаунта
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/messages/forward",
    response_model=ForwardMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def forward_messages(session_id: str, request: ForwardMessagesRequest):
    """
    Пересылает сообщения из одного чата в другой.

    from_chat_identifier - источник сообщений.
    to_chat_identifier - чат назначения.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/messages/reply",
    response_model=ReplyMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def reply_message(session_id: str, request: ReplyMessageRequest):
    """
    Отправляет сообщение-ответ на конкретное сообщение в чате.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
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
    "/sessions/{session_id}/messages/search",
    response_model=SearchMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def search_messages(session_id: str, request: SearchMessagesRequest):
    """
    Ищет сообщения в указанном чате по текстовому запросу.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
    "/sessions/{session_id}/messages/filter",
    response_model=FilterMessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def filter_messages(session_id: str, request: FilterMessagesRequest):
    """
    Фильтрует сообщения в чате по типу (text/media/photo/video/document/audio/voice/sticker/service).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
    "/sessions/{session_id}/messages/read",
    response_model=MarkMessagesReadResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def mark_messages_read(session_id: str, request: MarkMessagesReadRequest):
    """
    Отмечает сообщения в чате как прочитанные.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
    "/sessions/{session_id}/messages/pin",
    response_model=PinMessageResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def pin_message(session_id: str, request: PinMessageRequest):
    """
    Закрепляет или открепляет сообщение в чате.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
    "/sessions/{session_id}/messages/reaction",
    response_model=MessageReactionResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def set_message_reaction(session_id: str, request: MessageReactionRequest):
    """
    Устанавливает или снимает реакцию на сообщение.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
    "/sessions/{session_id}/messages/views",
    response_model=MessageViewsResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def get_message_views(session_id: str, channel_identifier: str, message_id: int):
    """
    Возвращает число просмотров сообщения в канале.

    channel_identifier может быть:
    - Username канала (например, @channel)
    - ID канала/супергруппы
    - Ссылка t.me/...
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
        )

    try:
        result = await client_manager.get_message_views(channel_identifier, message_id)
        return MessageViewsResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при получении просмотров сообщения: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/sessions/{session_id}/messages",
    response_model=MessagesResponse,
    status_code=status.HTTP_200_OK,
    tags=["messages"],
)
async def get_messages(session_id: str, chat_identifier: str, limit: int = 50):
    """
    Получает последние сообщения из указанного чата.
    
    chat_identifier может быть:
    - Username чата (например, @username)
    - ID чата (число)
    
    limit - максимальное количество сообщений (по умолчанию 50).
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
    "/sessions/{session_id}/messages/media",
    tags=["messages"],
)
async def download_message_media(session_id: str, chat_identifier: str, message_id: int):
    """
    Скачивает медиа по ID сообщения.
    
    Используйте media_id из ответа /messages для message_id.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify",
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
