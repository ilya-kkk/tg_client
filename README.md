# Telegram REST API

REST API для работы с Telegram через Telethon в мультисессионном режиме.

## Что умеет API

- Авторизация по номеру телефона (код + 2FA).
- Работа с несколькими Telegram-аккаунтами через `session_id`.
- Хранение сессий в Supabase (`telegram_sessions`), а не в локальных `.session` файлах.
- Работа с чатами, сообщениями, каналами, пользователями, ботами и аккаунтом.

## Требования

- Python 3.8+
- `API_ID` и `API_HASH` от Telegram (`https://my.telegram.org/apps`)
- Supabase проект с таблицей `telegram_sessions`

## Установка

```bash
pip install -r requirements.txt
```

## Переменные окружения

```env
API_ID=ваш_api_id
API_HASH=ваш_api_hash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<service_role_or_anon_key>
```

## Supabase schema

Перед запуском API примените SQL-скрипты из `scripts/supabase` по порядку:

1. `001_create_telegram_sessions.sql`
2. `002_create_parsed_channels.sql`
3. `003_create_reaction_jobs.sql`
4. `004_create_warmup_jobs.sql`
5. `005_add_warmup_jobs_user_id_index.sql`
6. `006_fix_warmup_jobs_user_fk.sql`
7. `007_create_ai_comment_jobs.sql`
8. `008_create_ai_comment_job_posts.sql`
9. `009_add_ai_comment_jobs_rls.sql`
10. `010_add_ai_comment_job_indexes.sql`

Если уже получили ошибку `PGRST205` для `public.warmup_jobs`, выполните минимум `004_create_warmup_jobs.sql` и `006_fix_warmup_jobs_user_fk.sql` в SQL Editor Supabase.

## Запуск

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Схема мультисессий

Для всех рабочих вызовов используется путь с `session_id`:

- `POST /sessions/{session_id}/auth/login`
- `POST /sessions/{session_id}/auth/verify`
- `POST /sessions/{session_id}/auth/password`
- `GET /sessions/{session_id}/...` для остальных операций

Одна сессия = один Telegram-аккаунт.

## Примеры

### 1. Отправить код авторизации

```bash
curl -X POST "http://localhost:8000/sessions/work_account/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+79991234567"}'
```

### 2. Подтвердить код

```bash
curl -X POST "http://localhost:8000/sessions/work_account/auth/verify" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+79991234567", "code": "12345"}'
```

### 3. Ввести 2FA пароль (если нужен)

```bash
curl -X POST "http://localhost:8000/sessions/work_account/auth/password" \
  -H "Content-Type: application/json" \
  -d '{"password": "your_2fa_password"}'
```

### 4. Получить чаты

```bash
curl -X GET "http://localhost:8000/sessions/work_account/chats?limit=50"
```

### 5. Отправить сообщение

```bash
curl -X POST "http://localhost:8000/sessions/work_account/messages/send" \
  -H "Content-Type: application/json" \
  -d '{"chat_identifier": "@username", "message": "Привет"}'
```

### 6. Список/статус/удаление сессий

```bash
curl -X GET "http://localhost:8000/sessions"
curl -X GET "http://localhost:8000/sessions/work_account"
curl -X DELETE "http://localhost:8000/sessions/work_account"
```

## Основные endpoints

### Системные

- `GET /` — health-check API и доступность Supabase.

### Управление сессиями

- `GET /sessions`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}`

### Авторизация

- `POST /sessions/{session_id}/auth/login`
- `POST /sessions/{session_id}/auth/verify`
- `POST /sessions/{session_id}/auth/password`

### Чаты

- `GET /sessions/{session_id}/chats`
- `GET /sessions/{session_id}/chats/folders`
- `POST /sessions/{session_id}/chats/folder`
- `POST /sessions/{session_id}/chats/archive`
- `POST /sessions/{session_id}/chats/create`
- `POST /sessions/{session_id}/chats/invite`
- `POST /sessions/{session_id}/chats/remove-users`
- `PATCH /sessions/{session_id}/chats/participants/permissions`
- `GET /sessions/{session_id}/chats/participants`
- `GET /sessions/{session_id}/chats/admins`
- `GET /sessions/{session_id}/chats/info`
- `PATCH /sessions/{session_id}/chats/info`
- `PATCH /sessions/{session_id}/chats/photo`

### Сообщения

- `POST /sessions/{session_id}/messages/send`
- `POST /sessions/{session_id}/messages/send-media`
- `POST /sessions/{session_id}/messages/send-voice`
- `POST /sessions/{session_id}/messages/send-sticker-gif`
- `POST /sessions/{session_id}/messages/send-location`
- `POST /sessions/{session_id}/messages/send-contact`
- `PATCH /sessions/{session_id}/messages/edit`
- `DELETE /sessions/{session_id}/messages/delete`
- `POST /sessions/{session_id}/messages/forward`
- `POST /sessions/{session_id}/messages/reply`
- `POST /sessions/{session_id}/messages/search`
- `POST /sessions/{session_id}/messages/filter`
- `POST /sessions/{session_id}/messages/read`
- `POST /sessions/{session_id}/messages/pin`
- `POST /sessions/{session_id}/messages/reaction`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/messages/media`

### Пользователи

- `GET /sessions/{session_id}/users/info`
- `GET /sessions/{session_id}/users/contacts`
- `POST /sessions/{session_id}/users/contacts/manage`
- `POST /sessions/{session_id}/users/block`
- `GET /sessions/{session_id}/users/status`

### Каналы

- `POST /sessions/{session_id}/channels/subscribe`
- `POST /sessions/{session_id}/channels/unsubscribe`
- `GET /sessions/{session_id}/channels/posts`
- `POST /sessions/{session_id}/channels/posts/publish`
- `PATCH /sessions/{session_id}/channels/posts/edit`
- `DELETE /sessions/{session_id}/channels/posts`

### Боты

- `POST /sessions/{session_id}/bots/command`
- `POST /sessions/{session_id}/bots/buttons/click`

### Аккаунт

- `GET /sessions/{session_id}/account/me`
- `PATCH /sessions/{session_id}/account/username`
- `PATCH /sessions/{session_id}/account/name`
- `PATCH /sessions/{session_id}/account/about`
- `PATCH /sessions/{session_id}/account/photo`
- `POST /sessions/{session_id}/account/sessions/reset`

## Безопасность

- Не коммитьте `.env`, ключи Supabase и Telegram credentials.
- Используйте HTTPS в продакшене.
- Не логируйте коды подтверждения и 2FA-пароли.
