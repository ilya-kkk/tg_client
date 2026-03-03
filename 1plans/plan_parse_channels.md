## Страница «Парсер каналов» — поиск и сбор Telegram-каналов по ключевым словам

Цель: по заданным ключевым словам находить релевантные Telegram-каналы, собирать базовую информацию и отдавать её в UI/на экспорт (CSV/txt).

### 1. Модель данных результата (минимально полезный набор)
- [x] **Определить структуру результата канала** (что возвращаем наружу):
  - `channel_id` (int | str) — id/peer
  - `title` (string)
  - `username` (string | null) — `@...`, если есть
  - `link` (string | null) — `https://t.me/<username>`, если есть
  - `about` (string | null) — описание (если доступно)
  - `participants_count` (int | null) — если доступно
  - `verified` (bool | null) — если доступно
  - `scam/fake` (bool | null) — если доступно
  - `found_by` (string) — ключевое слово, по которому найден
- [x] **Продумать стратегию дедупликации результатов**:
  - один и тот же канал может прийти по разным словам;
  - объединять результаты по `channel_id` или `username`;
  - хранить список всех ключевых слов в `found_by[]` (или вынести связи в отдельную таблицу).

### 2. Backend: поиск каналов по ключевым словам
- [x] **Добавить Pydantic-схемы** в `app/models.py`:
  - `ChannelsSearchRequest { keywords: string[]; limit_per_keyword?: int; language?: string | null; include_about?: bool; }`
  - `ChannelsSearchResultItem` (поля из секции 1)
  - `ChannelsSearchResponse { items: ChannelsSearchResultItem[]; total: int }`
- [x] **Реализовать метод Telethon-обёртки** в `app/telegram_client.py`:
  - `search_channels(keywords, limit_per_keyword, ...)`:
    - выполняет глобальный поиск (Telethon) по каждому ключевому слову;
    - фильтрует только **каналы** (не группы/пользователи);
    - по возможности подтягивает `about` и `participants_count`;
    - нормализует результаты в структуру `ChannelsSearchResultItem`;
    - объединяет дубликаты (по `channel_id` или `username`).
- [x] **Добавить роут в `app/main.py`**:
  - `POST /sessions/{session_id}/channels/search`;
  - валидирует входящий `ChannelsSearchRequest`;
  - вызывает метод клиента и возвращает `ChannelsSearchResponse`.
- [x] **Учесть ограничения и безопасность**:
  - задать дефолтный `limit_per_keyword` (например, 20) и верхний предел (например, 100);
  - при необходимости добавить поддержку пагинации (`offset` или cursor);
  - обрабатывать ошибки Telethon: FloodWait, приватные сущности, отсутствие прав.

### 3. Backend: сохранение результатов парсинга (опционально, для «базы»)
- [x] **Спроектировать схему хранения** (например, Supabase):
  - таблица `parsed_channels` (уникальный `channel_id` или `username`);
  - поля: `title`, `username`, `about`, `participants_count`, `verified`, `scam`, `last_seen_at`;
  - поле/таблица для источников: `found_by` (jsonb-массив) и/или отдельная таблица `parsed_channel_keywords`.
- [x] **Добавить эндпоинты для работы с базой**:
  - `POST /sessions/{session_id}/channels/parsed` — сохранить пачку результатов;
  - `GET /sessions/{session_id}/channels/parsed` — выдавать список с фильтрами/поиском по базе;
  - `DELETE /sessions/{session_id}/channels/parsed` — очищать записи (по сессии или глобально).

### 4. Frontend: страница парсера каналов
- [x] **Создать страницу** `FrontEnd/app/(dashboard)/channels-parser/page.tsx` (или другой роут):
  - поле ввода ключевых слов (textarea, по одному слову/фразе на строку);
  - настройки: `limit_per_keyword`, переключатель «тянуть описание»;
  - кнопка «Запустить поиск»;
  - вывод результатов таблицей/карточками: `title`, `@username`, `participants`, `found_by`;
  - состояния: loading / empty / error.
- [x] **Реализовать экспорт результатов**:
  - кнопка «Скачать CSV» (колонки: title, username, link, participants, found_by);
  - кнопка «Сохранить в txt только `@username`».
