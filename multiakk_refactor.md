## Мультисессионный рефакторинг с Supabase

### 1. Инфраструктура Supabase
- [x] **Создать таблицу `telegram_sessions` в Supabase**
  - [x] Поля: `session_id`, `phone`, `string_session`, `phone_code_hash`, `is_authorized`, `created_at`, `updated_at`.
  - [x] Включить RLS, по необходимости добавить политики.
- [x] **Проверить/настроить Supabase-переменные окружения**
  - [x] Добавить в `.env` и `.env.example` переменные `SUPABASE_URL`, `SUPABASE_KEY`.
- [x] **Обновить зависимости**
  - [x] Добавить Python SDK для Supabase в `requirements.txt`.

### 2. Клиент Supabase и репозиторий сессий
- [x] **Создать модуль `app/supabase_client.py`**
  - [x] Инициализировать Supabase-клиент (используя `SUPABASE_URL` и `SUPABASE_KEY`).
- [x] **Реализовать `SessionRepo`**
  - [x] `get(session_id)` — получить одну сессию.
  - [x] `list_all()` — вернуть список всех сессий.
  - [x] `upsert(session_id, ...)` — создать/обновить запись.
  - [x] `delete(session_id)` — удалить сессию.
  - [x] `save_auth_state(session_id, phone, phone_code_hash)` — сохранить состояние после отправки кода.
  - [x] `save_authorized(session_id, string_session)` — сохранить авторизованную StringSession.

### 3. Обновление конфигурации приложения
- [x] **Обновить `app/config.py`**
  - [x] Добавить чтение `SUPABASE_URL` и `SUPABASE_KEY` из окружения.
  - Удалить/перестать использовать `SESSIONS_DIR` и `SESSION_NAME` (файловые сессии).

### 4. Рефакторинг `TelegramClientManager` → мультисессии
- **Переписать `app/telegram_client.py` под `MultiSessionManager`**
  - Убрать глобальные поля одной сессии: `self.client`, `self.phone_code_hash`, `self.phone`, `_qr_*`.
  - Добавить кэши:
    - `self._clients: Dict[str, TelegramClient]` — авторизованные клиенты по `session_id`.
    - `self._auth_clients: Dict[str, TelegramClient]` — временные клиенты в процессе авторизации.
  - Подключить `SessionRepo` для чтения/записи сессий в Supabase.
- **Реализовать ключевые методы мультисессий**
  - `get_client(session_id)` — получить/создать Telethon-клиент по StringSession из Supabase.
  - `send_code(session_id, phone)` — создать временный клиент, отправить код, сохранить `phone_code_hash` и `phone` в БД.
  - `sign_in(session_id, phone, code)` — завершить авторизацию, сохранить `client.session.save()` в Supabase.
  - `sign_in_password(session_id, password)` — обработка двухфакторки, обновление StringSession в БД.
  - Обновить остальные методы (`get_dialogs`, `send_message`, и т.д.), чтобы первым аргументом принимали `session_id` и внутри использовали `get_client(session_id)`.
- **Удалить/отключить старую логику**
  - Убрать `init_client()`, QR-методы (`generate_qr_code`, `check_qr_status`).
  - Убрать глобальный `client_manager = TelegramClientManager()` и заменить инициализацией `MultiSessionManager` с `SessionRepo`.

### 5. Обновление моделей (`app/models.py`)
- **Удалить неиспользуемые QR-модели**
  - `QRCodeGenerateResponse`, `QRCodeStatusResponse`.
- **Добавить модели для управления сессиями**
  - `SessionInfo` — данные по одной сессии (`session_id`, `phone`, `is_authorized`, `created_at`, `updated_at`).
  - `SessionListResponse` — список сессий (`success`, `sessions`, `total`).
  - `SessionStatusResponse` — статус одной сессии.
  - `DeleteSessionResponse` — результат удаления сессии.

### 6. Рефакторинг маршрутов FastAPI (`app/main.py`)
- **Инициализация в `lifespan`**
  - Создать экземпляры `SessionRepo` и `MultiSessionManager` при запуске приложения.
  - Убрать вызовы `init_client()` и проверки глобальной авторизации.
- **Перенести все рабочие ручки под `/sessions/{session_id}`**
  - Авторизация:
    - `POST /sessions/{session_id}/auth/login` — отправка кода.
    - `POST /sessions/{session_id}/auth/verify` — подтверждение кода.
    - `POST /sessions/{session_id}/auth/password` — ввод 2FA-пароля.
  - Управление сессиями:
    - `GET /sessions` — список всех сессий.
    - `GET /sessions/{session_id}` — статус конкретной сессии.
    - `DELETE /sessions/{session_id}` — удаление сессии.
  - Остальные эндпоинты:
    - Перенести под `/sessions/{session_id}/...` (например, `/chats`, `/messages/send`, `/users/info`, `/account/me` и др.).
    - В сигнатурах добавить параметр `session_id: str` и прокидывать его в методы `MultiSessionManager`.
- **Удалить старые маршруты, не подходящие под мультисессии**
  - `/auth/login`, `/auth/verify`, `/auth/password` без session_id.
  - Все QR-ручки: `/auth/qr/generate`, `/auth/qr/status`, `/auth/qr/image`.
- **Оставить/обновить системные маршруты**
  - `GET /` — health-check (можно добавить информацию о доступности Supabase).

### 7. Чистка и финальные правки
- **Убрать неиспользуемый код и импорты**
  - Удалить `qrcode` и связанные с ним участки кода.
  - Убедиться, что `sessions/` больше нигде не используется в коде.
- **Обновить документацию**
  - Обновить `README.md` / `telethon.md` с новой схемой авторизации и примерами запросов с `session_id`.
- **Проверка и тестирование**
  - Протестировать полный цикл:
    - Создание новой сессии: `login → verify → password (если нужно)`.
    - Вызов нескольких рабочих ручек с одним `session_id`.
    - Создание второй сессии и параллельная работа двух аккаунтов.
  - Проверить корректность записи/обновления строк в `telegram_sessions` в Supabase.
