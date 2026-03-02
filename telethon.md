## Telethon: идеи для расширения API

## Текущий формат API

- API работает в мультисессионном режиме.
- Все рабочие методы выполняются через префикс:
  - `/sessions/{session_id}/...`
- Управление сессиями вынесено в отдельные маршруты:
  - `GET /sessions`
  - `GET /sessions/{session_id}`
  - `DELETE /sessions/{session_id}`
- QR-авторизация удалена из API.

## Выполнено в проекте

### Авторизация и базовые функции
- [x] Авторизация по номеру телефона (`/sessions/{session_id}/auth/login`, `/sessions/{session_id}/auth/verify`, `/sessions/{session_id}/auth/password`)
- [x] Получение списка чатов (`/sessions/{session_id}/chats`)
- [x] Получение списка папок чатов (`/sessions/{session_id}/chats/folders`)
- [x] Получение чатов из конкретной папки (`/sessions/{session_id}/chats/folder`)

### Сообщения и медиа
- [x] Отправка текстовых сообщений (`/sessions/{session_id}/messages/send`)
- [x] Получение истории сообщений из чата (`/sessions/{session_id}/messages`)
- [x] Получение расширенной информации о сообщениях (id, sender_id, date, media_type, media_id)
- [x] Скачивание медиафайлов из сообщений (`/sessions/{session_id}/messages/media`)

### 1. Работа с медиафайлами
- [x] Отправка фото, видео, аудио, документов (`/sessions/{session_id}/messages/send-media`, `POST`)
- [x] Скачивание медиафайлов
- [x] Отправка голосовых сообщений (`/sessions/{session_id}/messages/send-voice`, `POST`)
- [x] Отправка стикеров и GIF (`/sessions/{session_id}/messages/send-sticker-gif`, `POST`)
- [x] Отправка геолокации и контактов (`/sessions/{session_id}/messages/send-location`, `POST`; `/sessions/{session_id}/messages/send-contact`, `POST`)

### 2. Работа с сообщениями
- [x] Получение истории сообщений из чата
- [x] Редактирование сообщений (`/sessions/{session_id}/messages/edit`, `PATCH`)
- [x] Удаление сообщений (для себя / для всех) (`/sessions/{session_id}/messages/delete`, `DELETE`)
- [x] Пересылка сообщений (`/sessions/{session_id}/messages/forward`, `POST`)
- [x] Ответ на сообщения (reply) (`/sessions/{session_id}/messages/reply`, `POST`)
- [x] Реакции на сообщения (`/sessions/{session_id}/messages/reaction`, `POST`)
- [x] Поиск по сообщениям (`/sessions/{session_id}/messages/search`, `POST`)
- [x] Получение подробной информации о сообщении

### 3. Работа с чатами и каналами
- [x] Создание групп и каналов (`/sessions/{session_id}/chats/create`, `POST`)
- [x] Приглашение пользователей в группу (`/sessions/{session_id}/chats/invite`, `POST`)
- [x] Исключение пользователей из группы (`/sessions/{session_id}/chats/remove-users`, `POST`)
- [x] Получение участников группы / канала (`/sessions/{session_id}/chats/participants`, `GET`)
- [x] Получение списка администраторов (`/sessions/{session_id}/chats/admins`, `GET`)
- [x] Изменение прав участников (`/sessions/{session_id}/chats/participants/permissions`, `PATCH`)
- [x] Получение информации о чате (описание, фото, настройки) (`/sessions/{session_id}/chats/info`, `GET`)
- [x] Изменение названия и описания чата (`/sessions/{session_id}/chats/info`, `PATCH`)
- [x] Установка фото чата (`/sessions/{session_id}/chats/photo`, `PATCH`)

### 4. Работа с пользователями
- [x] Получение информации о пользователе (`/sessions/{session_id}/users/info`, `GET`)
- [x] Блокировка / разблокировка пользователей (`/sessions/{session_id}/users/block`, `POST`)
- [x] Получение списка контактов (`/sessions/{session_id}/users/contacts`, `GET`)
- [x] Добавление / удаление контактов (`/sessions/{session_id}/users/contacts/manage`, `POST`)
- [x] Получение статуса пользователя (онлайн, последний раз в сети) (`/sessions/{session_id}/users/status`, `GET`)

### 5. Работа с каналами
- [x] Подписка на канал (`/sessions/{session_id}/channels/subscribe`, `POST`)
- [x] Отписка от канала (`/sessions/{session_id}/channels/unsubscribe`, `POST`)
- [x] Получение постов из канала (`/sessions/{session_id}/channels/posts`, `GET`)
- [x] Публикация постов в канал (`/sessions/{session_id}/channels/posts/publish`, `POST`)
- [x] Редактирование постов (`/sessions/{session_id}/channels/posts/edit`, `PATCH`)
- [x] Удаление постов (`/sessions/{session_id}/channels/posts`, `DELETE`)
- [NO] Получение статистики канала (для администраторов) — не реализовано: Telethon-статистика доступна только при админ-правах и не для всех каналов (ограничения Telegram по типу/размеру канала).

### 6. Работа с ботами
- [x] Отправка команд боту (`/sessions/{session_id}/bots/command`, `POST`)
- [x] Работа с inline‑кнопками (`/sessions/{session_id}/bots/buttons/click`, `POST`)
- [NO] Обработка callback‑запросов — не реализовано через REST: callback-обновления приходят асинхронно и требуют постоянного event loop/подписки (WebSocket/SSE/long polling).

### 7. Продвинутые функции
- [x] Работа с папками чатов (folders)
- [x] Закрепление / открепление сообщений (`/sessions/{session_id}/messages/pin`, `POST`)
- [x] Отметка сообщений как прочитанных (`/sessions/{session_id}/messages/read`, `POST`)
- [x] Архивирование чатов (`/sessions/{session_id}/chats/archive`, `POST`)
- [NO] Получение уведомлений о новых сообщениях (event handlers) — не реализовано через REST: нужен постоянный канал доставки (WebSocket/SSE/long polling), а не одноразовый HTTP-запрос.
- [x] Фильтрация сообщений по типу (текст, медиа, сервисные и т.д.) (`/sessions/{session_id}/messages/filter`, `POST`)
- [x] Работа с форвардами (`/sessions/{session_id}/messages/forward`, `POST`)
- [NO] Получение истории редактирования сообщения — не реализовано: Telegram/Telethon не предоставляет публичный API для полной истории всех версий сообщения.

### 8. Управление аккаунтом
- [x] Изменение имени и фамилии (`/sessions/{session_id}/account/name`, `PATCH`)
- [x] Изменение `username` (`/sessions/{session_id}/account/username`, `PATCH`)
- [x] Изменение биографии (about) (`/sessions/{session_id}/account/about`, `PATCH`)
- [x] Изменение фото профиля (`/sessions/{session_id}/account/photo`, `PATCH`)
- [x] Получение информации о своём аккаунте (`/sessions/{session_id}/account/me`, `GET`)
- [x] Управление сессиями (отключение других устройств) (`/sessions/{session_id}/account/sessions/reset`, `POST`)

### 9. Работа с файлами
- [NO] Загрузка файлов на серверы Telegram — не реализовано как отдельный REST-эндпоинт: загрузка сейчас выполняется только в составе операций отправки медиа (`/sessions/{session_id}/messages/send-media` и др.).
- [x] Скачивание файлов с серверов Telegram
- [NO] Работа с большими файлами (chunked upload)

### 10. События и уведомления
- [NO] Обработка новых сообщений в реальном времени — не реализовано через REST: требуется постоянный канал доставки обновлений (WebSocket/SSE/long polling), а не одноразовый HTTP-запрос.
- [NO] Обработка редактирования сообщений — не реализовано через REST: события редактирования приходят асинхронно и требуют постоянной подписки (WebSocket/SSE/long polling).
- [NO] Обработка удаления сообщений — не реализовано через REST: события удаления приходят асинхронно и требуют постоянной подписки (WebSocket/SSE/long polling).
- [NO] Отслеживание новых участников в группах — не реализовано через REST: события вступления приходят асинхронно и требуют постоянной подписки (WebSocket/SSE/long polling).
- [NO] Отслеживание изменений в чатах (смена названия, аватарки, прав и т.д.) — не реализовано через REST: такие обновления приходят асинхронно и требуют постоянной подписки (WebSocket/SSE/long polling).
