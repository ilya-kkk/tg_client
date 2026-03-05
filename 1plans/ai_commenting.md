## Страница «Нейрокомментарии» — автоматическая публикация AI-комментариев к новым постам

Цель: дать пользователю возможность создавать именованные задания («кампании»), в каждом из которых выбранные Telegram-аккаунты автоматически публикуют комментарии к новым постам в заданных каналах на основе пользовательского и системного промптов.

### 1. Модель данных (таблица `ai_comment_jobs`)

- [x] **Создать таблицу `ai_comment_jobs` в Supabase** со следующими полями:
  - `id` (uuid, PK, default gen_random_uuid())
  - `user_id` (uuid, FK → users.id, NOT NULL)
  - `name` (text, NOT NULL) — название кампании
  - `account_sessions` (text[], NOT NULL) — список `session_id` участвующих аккаунтов
  - `target_channels` (text[], NOT NULL) — список `@username` или `t.me/...` каналов
  - `user_prompt` (text, NOT NULL) — пользовательский промпт из UI
  - `system_prompt` (text, NOT NULL) — системный промпт для формирования комментария
  - `is_active` (bool, NOT NULL, default false) — тумблер вкл/выкл
  - `last_checked_at` (timestamptz, NULL) — отметка последней проверки новых постов
  - `created_at` (timestamptz, default now())
  - `updated_at` (timestamptz, default now())
- [x] **Создать таблицу `ai_comment_job_posts` в Supabase** для идемпотентности (чтобы не комментировать один пост дважды):
  - `id` (uuid, PK, default gen_random_uuid())
  - `job_id` (uuid, FK → ai_comment_jobs.id, NOT NULL)
  - `channel_id` (text, NOT NULL)
  - `message_id` (bigint, NOT NULL)
  - `comment_message_id` (bigint, NULL) — id отправленного комментария
  - `status` (text, NOT NULL) — `posted` | `skipped` | `failed`
  - `error` (text, NULL)
  - `created_at` (timestamptz, default now())
  - уникальный индекс: (`job_id`, `channel_id`, `message_id`)
- [x] **Добавить RLS-политики** на обе таблицы: пользователь видит и изменяет только свои строки (`user_id = auth.uid()` или через переданный `user_id`), доступ к `ai_comment_job_posts` только через связанные `job_id` пользователя.
- [x] **Создать индексы**:
  - по `user_id` в `ai_comment_jobs` для быстрой выборки кампаний;
  - по `job_id` и `created_at` в `ai_comment_job_posts` для быстрого просмотра истории.

### 2. Backend: Pydantic-схемы и CRUD

- [x] **Добавить Pydantic-схемы** в `app/models.py`:
  - `AiCommentJobCreate` — поля: `name`, `account_sessions: list[str]`, `target_channels: list[str]`, `user_prompt: str`, `system_prompt: str`
  - `AiCommentJobUpdate` — те же поля, все опциональные + опциональный `is_active: bool`
  - `AiCommentJobOut` — все поля включая `id`, `user_id`, `is_active`, `last_checked_at`, `created_at`, `updated_at`
  - `AiCommentJobPostOut` — история обработки постов (`channel_id`, `message_id`, `status`, `error`, `created_at`)
- [x] **Добавить эндпоинт `GET /users/{user_id}/ai-comment-jobs`** — список всех кампаний пользователя, возвращает `list[AiCommentJobOut]`
- [x] **Добавить эндпоинт `POST /users/{user_id}/ai-comment-jobs`** — создание новой кампании, принимает `AiCommentJobCreate`, возвращает `AiCommentJobOut`
- [x] **Добавить эндпоинт `PATCH /users/{user_id}/ai-comment-jobs/{job_id}`** — обновление кампании (редактирование или переключение `is_active`), принимает `AiCommentJobUpdate`, возвращает `AiCommentJobOut`
- [x] **Добавить эндпоинт `DELETE /users/{user_id}/ai-comment-jobs/{job_id}`** — удаление кампании, возвращает `{ "success": true }`
- [x] **Добавить эндпоинт `GET /users/{user_id}/ai-comment-jobs/{job_id}/history`** — история комментариев/ошибок по кампании, возвращает `list[AiCommentJobPostOut]`
- [x] **Добавить сервис OpenRouter** в `app/telegram_client.py` или отдельный модуль `app/ai_client.py`:
  - использовать `OPENROUTER_API_KEY` из `.env`;
  - задать список бесплатных моделей (например: `["meta-llama/llama-3.1-8b-instruct:free", "qwen/qwen-2.5-7b-instruct:free", "google/gemma-2-9b-it:free"]`);
  - реализовать `generate_comment_with_fallback(...)` с перебором моделей до получения валидного непустого ответа;
  - при ошибке/пустом ответе логировать причину и переходить к следующей модели;
  - если все модели не дали ответ — помечать запись в истории как `failed`, без падения воркера.

### 3. Backend: фоновый воркер нейрокомментариев

- [x] **Добавить фоновый планировщик** (APScheduler или asyncio-таск) в `app/main.py`:
  - при старте приложения запускать цикл мониторинга активных кампаний;
  - раз в минуту выбирать из Supabase все записи `ai_comment_jobs`, где `is_active = true`;
  - для каждой кампании проверять новые посты в `target_channels` после `last_checked_at`.
- [x] **Реализовать метод `process_ai_comment_jobs`** в `app/telegram_client.py`:
  - получать новые посты по каждому каналу через Telethon;
  - проверять идемпотентность через `ai_comment_job_posts` (пропуск уже обработанных);
  - собирать вход в модель: `system_prompt` + `user_prompt` + текст нового поста;
  - вызывать `generate_comment_with_fallback(...)` и получать финальный текст комментария;
  - публиковать комментарий к посту от выбранного аккаунта (или по round-robin между `account_sessions`);
  - сохранять результат в `ai_comment_job_posts` со статусом `posted` / `failed`;
  - обновлять `last_checked_at` у кампании после успешного прохода.
- [x] **Обработать основные ошибки и ограничения**:
  - `FloodWait`, недоступный канал, отключённые комментарии у поста, отсутствие прав у аккаунта;
  - не останавливать весь воркер из-за ошибки одной кампании/одного канала;
  - добавить ограничение длины комментария и базовую очистку ответа модели.
- [x] **Обрабатывать включение/выключение через тумблер** — при `PATCH is_active=false` кампания перестаёт участвовать в минутном цикле без перезапуска приложения.

### 4. Frontend: страница «Нейрокомментарии»

- [x] **Создать страницу** `FrontEnd/app/(dashboard)/ai-commenting/page.tsx`:
  - заголовок «Нейрокомментарии»;
  - кнопка «+ Создать кампанию» в верхней части;
  - список карточек/строк кампаний: название слева, справа — иконка карандаша (редактировать), иконка корзины (удалить) и тумблер вкл/выкл;
  - состояния: loading-скелетон, empty-стейт («Нет кампаний. Создайте первую!»), error.
- [ ] **Добавить пункт «Нейрокомментарии»** в навигационный sidebar `FrontEnd/app/(dashboard)/layout.tsx` (или аналогичный компонент навигации).
- [ ] **Реализовать модальное окно создания/редактирования кампании** в интерфейсе как в разделе «Автореакции»:
  - поле «Название кампании» (text input);
  - мульти-селект «Аккаунты» — список активных сессий из `GET /sessions`, отображать `phone` или `first_name`;
  - мульти-селект «Каналы» — выбор каналов для мониторинга;
  - textarea «Пользовательский промпт»;
  - textarea «Системный промпт» (с предзаполненным шаблоном и возможностью редактирования);
  - кнопки «Сохранить» и «Отмена»;
  - при открытии на редактирование — предзаполнять все поля данными существующей кампании.
- [ ] **Реализовать логику тумблера**:
  - при переключении отправлять `PATCH .../ai-comment-jobs/{job_id}` с `{ "is_active": true/false }`;
  - показывать спиннер на тумблере во время запроса;
  - откатывать состояние при ошибке.
- [ ] **Реализовать удаление** с диалогом подтверждения (`window.confirm` или кастомный модал).
- [ ] **Добавить просмотр истории** в UI (drawer/модал): последние комментарии, статусы и ошибки по кампании.
- [ ] **Типизировать все API-ответы** через TypeScript `interface AiCommentJob { ... }` и `interface AiCommentJobPost { ... }`.
.
