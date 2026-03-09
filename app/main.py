import asyncio
import os
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
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
    MarkMessagesReadRequest,
    MarkMessagesReadResponse,
    PinMessageRequest,
    PinMessageResponse,
    MessageReactionRequest,
    MessageReactionResponse,
    ChatInfo,
    FolderChatsRequest,
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
    PublishChannelPostResponse,
    EditChannelPostResponse,
    DeleteChannelPostsResponse,
    ChannelsSearchRequest,
    ChannelsSearchResultItem,
    ChannelsSearchResponse,
    SaveParsedChannelsRequest,
    SaveParsedChannelsResponse,
    ParsedChannelsListResponse,
    DeleteParsedChannelsResponse,
    ReactionJobCreate,
    ReactionJobUpdate,
    ReactionJobOut,
    AiCommentJobCreate,
    AiCommentJobUpdate,
    AiCommentJobOut,
    AiCommentJobPostOut,
    AiCommentJobHistoryPostPreviewOut,
    AiReplyJobCreate,
    AiReplyJobUpdate,
    AiReplyJobOut,
    AiReplyJobMessageOut,
    WarmupJobCreate,
    WarmupJobUpdate,
    WarmupJobOut,
    SessionInfo,
    SessionListResponse,
    SessionStatusResponse,
    DeleteSessionResponse,
)
from app.supabase_client import (
    SessionRepo,
    ParsedChannelsRepo,
    ReactionJobsRepo,
    AiCommentJobsRepo,
    AiReplyJobsRepo,
    WarmupJobsRepo,
)
from app.telegram_client import MultiSessionManager
import logging
from app.config import CORS_ALLOW_ORIGINS
from app.warmup_config import WARMUP_MODES
from app.warmup_worker import WarmupWorker

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
client_manager: MultiSessionManager | None = None
session_repo: SessionRepo | None = None
parsed_channels_repo: ParsedChannelsRepo | None = None
reaction_jobs_repo: ReactionJobsRepo | None = None
ai_comment_jobs_repo: AiCommentJobsRepo | None = None
ai_reply_jobs_repo: AiReplyJobsRepo | None = None
warmup_jobs_repo: WarmupJobsRepo | None = None
reaction_jobs_task: asyncio.Task | None = None
ai_comment_jobs_task: asyncio.Task | None = None
ai_reply_jobs_task: asyncio.Task | None = None
warmup_jobs_task: asyncio.Task | None = None
warmup_worker = WarmupWorker()
warmup_job_tasks = warmup_worker.running

WARMUP_MONITOR_INTERVAL_ENV = "WARMUP_MONITOR_INTERVAL_MINUTES"
DEFAULT_WARMUP_MONITOR_INTERVAL_MINUTES = 5
AI_COMMENT_JOBS_POLL_INTERVAL_SECONDS = 60
AI_REPLY_JOBS_POLL_INTERVAL_SECONDS = 60


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
]


async def reaction_jobs_worker() -> None:
    """Фоновый цикл, который раз в минуту обрабатывает новые сообщения по активным кампаниям."""
    poll_interval_seconds = 60
    while True:
        try:
            if reaction_jobs_repo is None or client_manager is None:
                await asyncio.sleep(poll_interval_seconds)
                continue

            active_jobs = reaction_jobs_repo.list_active()
            active_job_ids = {
                str(job.get("id") or "").strip()
                for job in active_jobs
                if str(job.get("id") or "").strip()
            }

            for job in active_jobs:
                await client_manager.process_reaction_job_poll(job)

            client_manager.cleanup_inactive_reaction_jobs(active_job_ids)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Ошибка в воркере авто-реакций: %s", e)

        await asyncio.sleep(poll_interval_seconds)

async def ai_comment_jobs_worker() -> None:
    """Фоновый цикл, который раз в минуту запускает обработку активных кампаний нейрокомментирования."""
    while True:
        try:
            if ai_comment_jobs_repo is None or client_manager is None:
                await asyncio.sleep(AI_COMMENT_JOBS_POLL_INTERVAL_SECONDS)
                continue

            active_jobs = ai_comment_jobs_repo.list_active()
            for job in active_jobs:
                try:
                    await client_manager.process_ai_comment_jobs(
                        job,
                        ai_comment_jobs_repo=ai_comment_jobs_repo,
                    )
                except Exception as e:
                    logger.error(
                        "Ошибка обработки кампании нейрокомментариев: job_id=%s error=%s",
                        job.get("id"),
                        e,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Ошибка в воркере нейрокомментариев: %s", e)

        await asyncio.sleep(AI_COMMENT_JOBS_POLL_INTERVAL_SECONDS)


async def ai_reply_jobs_worker() -> None:
    """Фоновый цикл, который раз в минуту обрабатывает активные кампании нейроответов."""
    while True:
        try:
            if ai_reply_jobs_repo is None or client_manager is None:
                await asyncio.sleep(AI_REPLY_JOBS_POLL_INTERVAL_SECONDS)
                continue

            active_jobs = ai_reply_jobs_repo.list_active()
            active_job_ids = {
                str(job.get("id") or "").strip()
                for job in active_jobs
                if str(job.get("id") or "").strip()
            }

            for job in active_jobs:
                try:
                    await client_manager.process_ai_reply_jobs(
                        job,
                        ai_reply_jobs_repo=ai_reply_jobs_repo,
                    )
                except Exception as e:
                    logger.error(
                        "Ошибка обработки кампании нейроответов: job_id=%s error=%s",
                        job.get("id"),
                        e,
                    )

            client_manager.cleanup_inactive_ai_reply_jobs(active_job_ids)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Ошибка в воркере нейроответов: %s", e)

        await asyncio.sleep(AI_REPLY_JOBS_POLL_INTERVAL_SECONDS)


def get_warmup_monitor_interval_seconds() -> int:
    raw_value = os.getenv(
        WARMUP_MONITOR_INTERVAL_ENV,
        str(DEFAULT_WARMUP_MONITOR_INTERVAL_MINUTES),
    ).strip()
    try:
        minutes = int(raw_value)
    except ValueError:
        logger.warning(
            "Некорректное значение %s='%s', используется значение по умолчанию %s минут",
            WARMUP_MONITOR_INTERVAL_ENV,
            raw_value,
            DEFAULT_WARMUP_MONITOR_INTERVAL_MINUTES,
        )
        minutes = DEFAULT_WARMUP_MONITOR_INTERVAL_MINUTES

    return max(1, minutes) * 60


def _get_warmup_job_id(job: dict) -> str:
    return str(job.get("id") or "").strip()


def ensure_warmup_job_worker_started(job: dict) -> None:
    job_id = _get_warmup_job_id(job)
    if not job_id:
        return

    warmup_worker.start(job)


async def stop_warmup_job_worker(job_id: str) -> None:
    await warmup_worker.stop(job_id)


async def stop_all_warmup_job_workers() -> None:
    await warmup_worker.stop_all()


async def sync_warmup_job_workers(active_jobs: list[dict]) -> None:
    active_job_ids: set[str] = set()

    for job in active_jobs:
        job_id = _get_warmup_job_id(job)
        if not job_id:
            continue

        active_job_ids.add(job_id)
        ensure_warmup_job_worker_started(job)

    for job_id in list(warmup_job_tasks.keys()):
        if job_id not in active_job_ids:
            await stop_warmup_job_worker(job_id)


async def warmup_jobs_worker() -> None:
    """Фоновый планировщик, который следит за активными warmup-кампаниями."""
    poll_interval_seconds = get_warmup_monitor_interval_seconds()

    while True:
        try:
            if warmup_jobs_repo is None:
                await asyncio.sleep(poll_interval_seconds)
                continue

            active_jobs = warmup_jobs_repo.list_active()
            await sync_warmup_job_workers(active_jobs)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Ошибка в воркере warmup-кампаний: %s", e)

        await asyncio.sleep(poll_interval_seconds)


def get_mode_average_actions_per_day(mode: str) -> int:
    mode_config = WARMUP_MODES.get(mode)
    if mode_config is None:
        raise ValueError(f"Конфигурация режима '{mode}' не найдена")

    min_actions, max_actions = mode_config["actions_per_day_range"]
    return (min_actions + max_actions) // 2


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    global client_manager, session_repo, parsed_channels_repo, reaction_jobs_repo, ai_comment_jobs_repo, ai_reply_jobs_repo, warmup_jobs_repo, reaction_jobs_task, ai_comment_jobs_task, ai_reply_jobs_task, warmup_jobs_task

    # При старте приложения
    logger.info("Инициализация SessionRepo и MultiSessionManager...")
    session_repo = SessionRepo()
    parsed_channels_repo = ParsedChannelsRepo()
    reaction_jobs_repo = ReactionJobsRepo()
    ai_comment_jobs_repo = AiCommentJobsRepo()
    ai_reply_jobs_repo = AiReplyJobsRepo()
    warmup_jobs_repo = WarmupJobsRepo()
    client_manager = MultiSessionManager(session_repo=session_repo)
    app.state.session_repo = session_repo
    app.state.parsed_channels_repo = parsed_channels_repo
    app.state.reaction_jobs_repo = reaction_jobs_repo
    app.state.ai_comment_jobs_repo = ai_comment_jobs_repo
    app.state.ai_reply_jobs_repo = ai_reply_jobs_repo
    app.state.warmup_jobs_repo = warmup_jobs_repo
    app.state.client_manager = client_manager
    warmup_worker.set_client_manager(client_manager)
    warmup_job_tasks.clear()
    reaction_jobs_task = asyncio.create_task(reaction_jobs_worker())
    ai_comment_jobs_task = asyncio.create_task(ai_comment_jobs_worker())
    ai_reply_jobs_task = asyncio.create_task(ai_reply_jobs_worker())
    warmup_jobs_task = asyncio.create_task(warmup_jobs_worker())
    
    yield
    
    # При остановке приложения
    logger.info("Отключение Telegram клиента...")
    if reaction_jobs_task is not None:
        reaction_jobs_task.cancel()
        try:
            await reaction_jobs_task
        except asyncio.CancelledError:
            pass
        reaction_jobs_task = None
    if ai_comment_jobs_task is not None:
        ai_comment_jobs_task.cancel()
        try:
            await ai_comment_jobs_task
        except asyncio.CancelledError:
            pass
        ai_comment_jobs_task = None
    if ai_reply_jobs_task is not None:
        ai_reply_jobs_task.cancel()
        try:
            await ai_reply_jobs_task
        except asyncio.CancelledError:
            pass
        ai_reply_jobs_task = None
    if warmup_jobs_task is not None:
        warmup_jobs_task.cancel()
        try:
            await warmup_jobs_task
        except asyncio.CancelledError:
            pass
        warmup_jobs_task = None
    await stop_all_warmup_job_workers()
    warmup_worker.set_client_manager(None)
    if client_manager is not None:
        await client_manager.disconnect()


app = FastAPI(
    title="Telegram REST API",
    description="REST API для работы с Telegram через Telethon",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials="*" not in CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["system"])
async def root():
    """Корневой endpoint"""
    authorized = client_manager.is_connected() if client_manager is not None else False
    supabase_status = "unavailable"
    if session_repo is not None:
        try:
            # Быстрый запрос для проверки доступности Supabase.
            session_repo.list_all()
            supabase_status = "ok"
        except Exception as e:
            logger.warning("Supabase health-check failed: %s", e)

    return {
        "message": "Telegram REST API",
        "status": "running",
        "authorized": authorized,
        "supabase": supabase_status,
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
    "/sessions/{session_id}/channels/search",
    response_model=ChannelsSearchResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def search_channels(session_id: str, request: ChannelsSearchRequest):
    """
    Ищет Telegram-каналы по ключевым словам.
    """
    if not client_manager.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация. Используйте /sessions/{session_id}/auth/login и /sessions/{session_id}/auth/verify"
        )

    max_limit = 100
    safe_limit = min(request.limit_per_keyword, max_limit)

    try:
        items = await client_manager.search_channels(
            keywords=request.keywords,
            limit_per_keyword=safe_limit,
            language=request.language,
            include_about=request.include_about,
        )
        return ChannelsSearchResponse(
            items=[ChannelsSearchResultItem(**item) for item in items],
            total=len(items),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Ошибка при поиске каналов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/sessions/{session_id}/channels/parsed",
    response_model=SaveParsedChannelsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def save_parsed_channels(session_id: str, request: SaveParsedChannelsRequest):
    """
    Сохраняет найденные каналы в базу.
    """
    if parsed_channels_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище parsed-каналов не инициализировано",
        )

    try:
        saved = parsed_channels_repo.upsert_many(
            session_id=session_id,
            items=[item.model_dump() for item in request.items],
        )
        return SaveParsedChannelsResponse(
            success=True,
            saved=saved,
            message="Результаты парсинга сохранены",
        )
    except Exception as e:
        logger.error(f"Ошибка при сохранении parsed-каналов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/sessions/{session_id}/channels/parsed",
    response_model=ParsedChannelsListResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def list_parsed_channels(
    session_id: str,
    query: str = "",
    keyword: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """
    Возвращает сохраненные каналы с фильтрацией.
    """
    if parsed_channels_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище parsed-каналов не инициализировано",
        )

    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)

    try:
        rows = parsed_channels_repo.list(
            session_id=session_id,
            query=query,
            keyword=keyword,
            limit=safe_limit,
            offset=safe_offset,
        )
        items = [
            ChannelsSearchResultItem(
                channel_id=str(row.get("channel_id", "")),
                title=row.get("title") or "",
                username=row.get("username"),
                link=row.get("link"),
                about=row.get("about"),
                participants_count=row.get("participants_count"),
                verified=row.get("verified"),
                scam=row.get("scam"),
                fake=row.get("fake"),
                found_by=row.get("found_by") or [],
            )
            for row in rows
            if row.get("channel_id") and row.get("title")
        ]
        return ParsedChannelsListResponse(success=True, items=items, total=len(items))
    except Exception as e:
        logger.error(f"Ошибка при получении parsed-каналов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/sessions/{session_id}/channels/parsed",
    response_model=DeleteParsedChannelsResponse,
    status_code=status.HTTP_200_OK,
    tags=["channels"],
)
async def delete_parsed_channels(session_id: str, global_delete: bool = False):
    """
    Удаляет parsed-каналы: либо только текущей сессии, либо глобально.
    """
    if parsed_channels_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище parsed-каналов не инициализировано",
        )

    try:
        deleted = parsed_channels_repo.delete(
            session_id=None if global_delete else session_id
        )
        return DeleteParsedChannelsResponse(
            success=True,
            deleted=deleted,
            message="Записи parsed-каналов удалены",
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении parsed-каналов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/reaction-jobs",
    response_model=list[ReactionJobOut],
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def list_reaction_jobs(user_id: str):
    if reaction_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище reaction_jobs не инициализировано",
        )
    try:
        rows = reaction_jobs_repo.list_by_user(user_id)
        return [ReactionJobOut(**row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении reaction_jobs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/ai-comment-jobs",
    response_model=list[AiCommentJobOut],
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def list_ai_comment_jobs(user_id: str):
    if ai_comment_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_comment_jobs не инициализировано",
        )
    try:
        rows = ai_comment_jobs_repo.list_by_user(user_id)
        return [AiCommentJobOut(**row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении ai_comment_jobs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/users/{user_id}/ai-comment-jobs",
    response_model=AiCommentJobOut,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
)
async def create_ai_comment_job(user_id: str, request: AiCommentJobCreate):
    if ai_comment_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_comment_jobs не инициализировано",
        )
    try:
        payload = request.model_dump()
        payload.setdefault("is_active", False)
        row = ai_comment_jobs_repo.create(user_id=user_id, payload=payload)
        return AiCommentJobOut(**row)
    except Exception as e:
        logger.error("Ошибка при создании ai_comment_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.patch(
    "/users/{user_id}/ai-comment-jobs/{job_id}",
    response_model=AiCommentJobOut,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def update_ai_comment_job(user_id: str, job_id: str, request: AiCommentJobUpdate):
    if ai_comment_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_comment_jobs не инициализировано",
        )
    payload = request.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не переданы данные для обновления",
        )

    try:
        row = ai_comment_jobs_repo.update(user_id=user_id, job_id=job_id, payload=payload)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        return AiCommentJobOut(**row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при обновлении ai_comment_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/users/{user_id}/ai-comment-jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def delete_ai_comment_job(user_id: str, job_id: str):
    if ai_comment_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_comment_jobs не инициализировано",
        )
    try:
        deleted = ai_comment_jobs_repo.delete(user_id=user_id, job_id=job_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при удалении ai_comment_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/ai-comment-jobs/{job_id}/history",
    response_model=list[AiCommentJobPostOut],
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_ai_comment_job_history(user_id: str, job_id: str):
    if ai_comment_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_comment_jobs не инициализировано",
        )

    try:
        if ai_comment_jobs_repo.get_by_id(user_id=user_id, job_id=job_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        rows = ai_comment_jobs_repo.list_history(user_id=user_id, job_id=job_id)
        return [AiCommentJobPostOut(**row) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при получении истории ai_comment_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/ai-comment-jobs/{job_id}/history/post-preview",
    response_model=AiCommentJobHistoryPostPreviewOut,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_ai_comment_job_history_post_preview(
    user_id: str,
    job_id: str,
    channel_id: str = Query(..., min_length=1),
    message_id: int = Query(..., gt=0),
):
    if ai_comment_jobs_repo is None or client_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="История ai_comment_jobs недоступна",
        )

    try:
        job = ai_comment_jobs_repo.get_by_id(user_id=user_id, job_id=job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )

        history_record = ai_comment_jobs_repo.get_history_record(
            job_id=job_id,
            channel_id=channel_id,
            message_id=message_id,
        )
        if history_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Запись истории не найдена",
            )

        result = await client_manager.get_message_by_id_for_sessions(
            session_ids=job.get("account_sessions") or [],
            chat_identifier=channel_id,
            message_id=message_id,
        )
        return AiCommentJobHistoryPostPreviewOut(**result)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Ошибка при загрузке поста из истории ai_comment_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/ai-reply-jobs",
    response_model=list[AiReplyJobOut],
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def list_ai_reply_jobs(user_id: str):
    if ai_reply_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_reply_jobs не инициализировано",
        )
    try:
        rows = ai_reply_jobs_repo.list_by_user(user_id)
        return [AiReplyJobOut(**row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении ai_reply_jobs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/users/{user_id}/ai-reply-jobs",
    response_model=AiReplyJobOut,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
)
async def create_ai_reply_job(user_id: str, request: AiReplyJobCreate):
    if ai_reply_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_reply_jobs не инициализировано",
        )
    try:
        payload = request.model_dump()
        payload.setdefault("is_active", False)
        row = ai_reply_jobs_repo.create(user_id=user_id, payload=payload)
        return AiReplyJobOut(**row)
    except Exception as e:
        logger.error("Ошибка при создании ai_reply_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.patch(
    "/users/{user_id}/ai-reply-jobs/{job_id}",
    response_model=AiReplyJobOut,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def update_ai_reply_job(user_id: str, job_id: str, request: AiReplyJobUpdate):
    if ai_reply_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_reply_jobs не инициализировано",
        )
    payload = request.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не переданы данные для обновления",
        )

    try:
        row = ai_reply_jobs_repo.update(user_id=user_id, job_id=job_id, payload=payload)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        return AiReplyJobOut(**row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при обновлении ai_reply_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/users/{user_id}/ai-reply-jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def delete_ai_reply_job(user_id: str, job_id: str):
    if ai_reply_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_reply_jobs не инициализировано",
        )
    try:
        deleted = ai_reply_jobs_repo.delete(user_id=user_id, job_id=job_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при удалении ai_reply_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/ai-reply-jobs/{job_id}/history",
    response_model=list[AiReplyJobMessageOut],
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_ai_reply_job_history(user_id: str, job_id: str):
    if ai_reply_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище ai_reply_jobs не инициализировано",
        )

    try:
        if ai_reply_jobs_repo.get_by_id(user_id=user_id, job_id=job_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        rows = ai_reply_jobs_repo.list_history(user_id=user_id, job_id=job_id)
        return [AiReplyJobMessageOut(**row) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при получении истории ai_reply_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.get(
    "/users/{user_id}/warmup-jobs",
    response_model=list[WarmupJobOut],
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def list_warmup_jobs(user_id: str):
    if warmup_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище warmup_jobs не инициализировано",
        )
    try:
        rows = warmup_jobs_repo.list_by_user(user_id)
        return [WarmupJobOut(**row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении warmup_jobs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/users/{user_id}/warmup-jobs",
    response_model=WarmupJobOut,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
)
async def create_warmup_job(user_id: str, request: WarmupJobCreate):
    if warmup_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище warmup_jobs не инициализировано",
        )
    try:
        payload = request.model_dump()
        payload["actions_per_day"] = get_mode_average_actions_per_day(request.mode)
        payload.setdefault("is_active", False)
        row = warmup_jobs_repo.create(user_id=user_id, payload=payload)
        return WarmupJobOut(**row)
    except ValueError as e:
        logger.error("Ошибка конфигурации warmup mode: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )
    except Exception as e:
        logger.error("Ошибка при создании warmup_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.patch(
    "/users/{user_id}/warmup-jobs/{job_id}",
    response_model=WarmupJobOut,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def update_warmup_job(user_id: str, job_id: str, request: WarmupJobUpdate):
    if warmup_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище warmup_jobs не инициализировано",
        )
    payload = request.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не переданы данные для обновления",
        )

    try:
        if "mode" in payload:
            payload["actions_per_day"] = get_mode_average_actions_per_day(str(payload["mode"]))

        row = warmup_jobs_repo.update(user_id=user_id, job_id=job_id, payload=payload)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )

        if payload.get("is_active") is False:
            await stop_warmup_job_worker(_get_warmup_job_id(row) or job_id)

        return WarmupJobOut(**row)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Ошибка конфигурации warmup mode: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )
    except Exception as e:
        logger.error("Ошибка при обновлении warmup_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/users/{user_id}/warmup-jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def delete_warmup_job(user_id: str, job_id: str):
    if warmup_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище warmup_jobs не инициализировано",
        )
    try:
        deleted = warmup_jobs_repo.delete(user_id=user_id, job_id=job_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при удалении warmup_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.post(
    "/users/{user_id}/reaction-jobs",
    response_model=ReactionJobOut,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
)
async def create_reaction_job(user_id: str, request: ReactionJobCreate):
    if reaction_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище reaction_jobs не инициализировано",
        )
    try:
        payload = request.model_dump()
        payload.setdefault("is_active", True)
        row = reaction_jobs_repo.create(user_id=user_id, payload=payload)
        if client_manager is not None and row.get("is_active"):
            await client_manager.process_reaction_job_poll(row)
        return ReactionJobOut(**row)
    except Exception as e:
        logger.error("Ошибка при создании reaction_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.patch(
    "/users/{user_id}/reaction-jobs/{job_id}",
    response_model=ReactionJobOut,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def update_reaction_job(user_id: str, job_id: str, request: ReactionJobUpdate):
    if reaction_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище reaction_jobs не инициализировано",
        )
    payload = request.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не переданы данные для обновления",
        )

    try:
        row = reaction_jobs_repo.update(user_id=user_id, job_id=job_id, payload=payload)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )

        if client_manager is not None:
            if row.get("is_active"):
                await client_manager.process_reaction_job_poll(row)
            else:
                await client_manager.stop_reaction_job_listeners(str(row.get("id")))

        return ReactionJobOut(**row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при обновлении reaction_job: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@app.delete(
    "/users/{user_id}/reaction-jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def delete_reaction_job(user_id: str, job_id: str):
    if reaction_jobs_repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище reaction_jobs не инициализировано",
        )
    try:
        deleted = reaction_jobs_repo.delete(user_id=user_id, job_id=job_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Кампания не найдена",
            )
        if client_manager is not None:
            await client_manager.stop_reaction_job_listeners(job_id)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ошибка при удалении reaction_job: %s", e)
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
