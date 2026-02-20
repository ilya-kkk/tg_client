# Telegram REST API

REST API для работы с Telegram через Telethon. Позволяет авторизоваться в Telegram, получать список чатов и отправлять сообщения через HTTP API.

## Возможности

- 🔐 Авторизация по номеру телефона с кодом подтверждения
- 🔑 Поддержка двухфакторной аутентификации (2FA)
- 💬 Получение списка всех чатов (лички, группы, каналы)
- 📨 Отправка сообщений в чаты по username или ID
- 💾 Автоматическое сохранение сессии (не нужно авторизоваться каждый раз)

## Требования

- Python 3.8+
- API ID и API Hash от Telegram (получить на https://my.telegram.org/apps)

## Установка

1. Клонируйте репозиторий или скачайте файлы проекта

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Получите API credentials:
   - Перейдите на https://my.telegram.org/apps
   - Войдите с вашим номером телефона
   - Создайте приложение и получите `api_id` и `api_hash`

4. Настройте переменные окружения:
```bash
export API_ID="ваш_api_id"
export API_HASH="ваш_api_hash"
```

Или создайте файл `.env` в корне проекта:
```
API_ID=ваш_api_id
API_HASH=ваш_api_hash
```

## Запуск

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API будет доступен по адресу: http://localhost:8000

Документация API (Swagger UI): http://localhost:8000/docs

## Использование API

### 1. Авторизация

#### Шаг 1: Отправка номера телефона
```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+79991234567"}'
```

Ответ:
```json
{
  "success": true,
  "phone_code_hash": "abc123...",
  "message": "Код отправлен в Telegram"
}
```

#### Шаг 2: Подтверждение кода
```bash
curl -X POST "http://localhost:8000/auth/verify" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+79991234567",
    "code": "12345"
  }'
```

Ответ (если 2FA не требуется):
```json
{
  "success": true,
  "password_required": false,
  "message": "Авторизация успешна"
}
```

Ответ (если требуется 2FA):
```json
{
  "success": false,
  "password_required": true,
  "message": "Требуется пароль двухфакторной аутентификации"
}
```

#### Шаг 3: Ввод пароля 2FA (если требуется)
```bash
curl -X POST "http://localhost:8000/auth/password" \
  -H "Content-Type: application/json" \
  -d '{"password": "ваш_2fa_пароль"}'
```

### 2. Получение списка чатов

```bash
curl -X GET "http://localhost:8000/chats?limit=50"
```

Ответ:
```json
{
  "success": true,
  "chats": [
    {
      "id": 123456789,
      "name": "Имя чата",
      "type": "user",
      "username": "username",
      "unread_count": 5,
      "is_pinned": false,
      "is_verified": false,
      "is_scam": false,
      "is_fake": false
    }
  ],
  "total": 1
}
```

Типы чатов:
- `user` - личный чат
- `group` - группа
- `supergroup` - супергруппа
- `channel` - канал

### 3. Отправка сообщения

Отправка по username:
```bash
curl -X POST "http://localhost:8000/messages/send" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_identifier": "@username",
    "message": "Привет! Это тестовое сообщение"
  }'
```

Отправка по ID чата:
```bash
curl -X POST "http://localhost:8000/messages/send" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_identifier": "123456789",
    "message": "Привет! Это тестовое сообщение"
  }'
```

Ответ:
```json
{
  "success": true,
  "message_id": 123,
  "chat_id": 123456789,
  "date": "2026-02-20T14:30:00",
  "message": "Сообщение отправлено"
}
```

## Структура проекта

```
tg_client/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI приложение с эндпоинтами
│   ├── models.py            # Pydantic модели для валидации
│   ├── telegram_client.py   # Обёртка над Telethon клиентом
│   └── config.py            # Конфигурация
├── sessions/                # Файлы сессий Telethon (создаются автоматически)
├── requirements.txt         # Зависимости Python
└── README.md               # Документация
```

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Статус API и информация об авторизации |
| POST | `/auth/login` | Отправка номера телефона для авторизации |
| POST | `/auth/verify` | Подтверждение кода авторизации |
| POST | `/auth/password` | Ввод пароля 2FA |
| GET | `/chats` | Получение списка чатов |
| POST | `/messages/send` | Отправка сообщения |

## Обработка ошибок

API возвращает стандартные HTTP коды статуса:

- `200` - Успешный запрос
- `400` - Неверные данные запроса
- `401` - Требуется авторизация
- `404` - Ресурс не найден
- `500` - Внутренняя ошибка сервера

Пример ответа с ошибкой:
```json
{
  "detail": "Неверный код подтверждения"
}
```

## Безопасность

⚠️ **Важно:**
- Файлы сессий хранятся локально в директории `sessions/`
- Не коммитьте файлы сессий в git (добавьте `sessions/` в `.gitignore`)
- Храните `API_ID` и `API_HASH` в переменных окружения, не в коде
- Используйте HTTPS в продакшене
- Не логируйте номера телефонов и коды подтверждения

## Ограничения Telegram

- Telegram может ограничивать частоту запросов (rate limiting)
- При превышении лимита API вернет ошибку с указанием времени ожидания
- Для массовой рассылки используйте официальный Bot API

## Разработка

Для разработки с автоперезагрузкой:
```bash
uvicorn app.main:app --reload
```

Для продакшена используйте:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Лицензия

MIT

## Поддержка

При возникновении проблем проверьте:
1. Правильность `API_ID` и `API_HASH`
2. Формат номера телефона (должен начинаться с `+`)
3. Логи приложения для деталей ошибок
4. Документацию Telethon: https://docs.telethon.dev/
