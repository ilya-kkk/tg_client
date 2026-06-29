---
name: telegram-crm-api
description: Use this skill when an agent must use the local Telegram CRM FastAPI service with curl: authenticate Telegram sessions, search public channels, inspect posts/comments, collect channel analytics (health/discussion/business/campaign), get message view counts, join approved public channels, put them into a Telegram folder, and save lead rows to local SQLite.
---

# Telegram CRM API Curl Runbook

Use curl against the local API.

По умолчанию для `docker compose`:

```bash
BASE_URL="http://127.0.0.1:80"
SESSION_ID="default"
FOLDER_NAME="Lead Search 1"
```

Если запускаешь API локально через `uvicorn`:

```bash
BASE_URL="http://127.0.0.1:8000"
```

Если запускаешь через `docker compose`, интерфейс и API доступны через прокси на:

```bash
BASE_URL="http://127.0.0.1:80"
```

Полезные точки доступа:

- UI/Docs: `http://127.0.0.1/`
- OpenAPI: `http://127.0.0.1/openapi.json`
- Docs: `http://127.0.0.1/docs`
- API статус: `http://127.0.0.1/api/status`

Логи:

```bash
docker logs -f tg_crm_api
docker logs -f tg_crm_api_proxy
```

Check service health first:

```bash
curl -sS "$BASE_URL/api/status"
```

Перезапуск всех сервисов через один compose:

```bash
cd /home/user/tg_client
docker compose down
docker compose up -d --build
```

Полный стек (PostgreSQL + n8n + Adminer) — через профиль `all`:

```bash
docker compose --profile all up -d --build
```

If the API is down, start it from `/home/user/tg_client`:

```bash
setsid .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  > /tmp/tg_crm_uvicorn.log 2>&1 < /dev/null &
```

## Session

List saved Telegram sessions:

```bash
curl -sS "$BASE_URL/sessions"
```

Check a session:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID"
```

Start login only if no authorized session exists:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+79991234567"}'
```

Verify the code from the user:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/auth/verify" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+79991234567","code":"12345"}'
```

Submit 2FA password only if `password_required` is true:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/auth/password" \
  -H "Content-Type: application/json" \
  -d '{"password":"telegram_2fa_password"}'
```

Never guess codes or passwords.

## Channel Search

Search public Telegram channels:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/channels/search?query=telegram&limit=10"
curl -sS "$BASE_URL/sessions/$SESSION_ID/channels/search?query=%D0%BE%D0%BD%D0%BB%D0%B0%D0%B9%D0%BD%20%D1%88%D0%BA%D0%BE%D0%BB%D0%B0&limit=20"
```

The response contains:

```json
{
  "success": true,
  "query": "telegram",
  "channels": [
    {
      "id": -1001005640892,
      "name": "Telegram News",
      "type": "channel",
      "username": "telegram",
      "participants_count": 10000000,
      "is_private": false,
      "join_request": false
    }
  ],
  "total": 1
}
```

Treat `participants_count` as subscribers when visible.

## Channel Analytics Pipeline

Run the full scoring pipeline for one channel:

```bash
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/refresh-metrics"
```

Collect only posts:

```bash
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/collect-posts" \
  -H "Content-Type: application/json" \
  -d '{"limit":50,"exclude_forwards":true,"exclude_ads":true}'
```

Collect only comments for fresh posts:

```bash
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/collect-comments" \
  -H "Content-Type: application/json" \
  -d '{"posts_limit":20,"comments_per_post":50}'
```

Score blocks:

```bash
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/score-health"
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/score-discussion"
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/score-business-fit"
curl -sS -X POST "$BASE_URL/channels/@lazyproducer/score-campaign"
```

Top channels and best posts:

```bash
curl -sS "$BASE_URL/channels/ranked?sort=campaign_score&min_score=7"
curl -sS "$BASE_URL/channels/@lazyproducer/opportunity-posts"
```

Export campaign analysis:

```bash
curl -sS "$BASE_URL/channels/export-campaign-analysis?format=csv&min_score=6.5&recommended_action=test_now"
```

## Channel Inspection

Read recent posts:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/channels/posts?channel_identifier=@lazyproducer&limit=20"
```

Get chat/channel info:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/chats/info?chat_identifier=@lazyproducer"
```

Search posts for monetization signals:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/messages/search" \
  -H "Content-Type: application/json" \
  -d '{"chat_identifier":"@lazyproducer","query":"курс","limit":20}'

curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/messages/search" \
  -H "Content-Type: application/json" \
  -d '{"chat_identifier":"@lazyproducer","query":"консультация","limit":20}'

curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/messages/search" \
  -H "Content-Type: application/json" \
  -d '{"chat_identifier":"@lazyproducer","query":"клуб","limit":20}'
```

Check whether channel comments exist:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/channels/comments/status?channel_identifier=@lazyproducer"
```

Check comments for a specific post:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/channels/comments/status?channel_identifier=@lazyproducer&message_id=1484"
```

Read comments for a post:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/channels/posts/comments?channel_identifier=@lazyproducer&message_id=1484&limit=50"
```

Get message views in a channel post:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/messages/views?channel_identifier=@lazyproducer&message_id=1484"
```

Expected response:

```json
{
  "success": true,
  "chat_id": -1001234567890,
  "message_id": 1484,
  "views": 420,
  "message": "Количество просмотров получено"
}
```

Download media only when needed:

```bash
curl -OJ "$BASE_URL/sessions/$SESSION_ID/messages/media?chat_identifier=@lazyproducer&message_id=1484"
```

## Joining Channels

Only join public channels that the user/task has approved or that scored 7+ under the task rules. Do not join private invite links without explicit confirmation.

Join a public channel:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/channels/join" \
  -H "Content-Type: application/json" \
  -d '{"channel_identifier":"@some_public_channel"}'
```

The same endpoint accepts public links and private invite links, but avoid private links unless explicitly approved:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/channels/join" \
  -H "Content-Type: application/json" \
  -d '{"channel_identifier":"https://t.me/some_public_channel"}'
```

Possible `status` values:

- `joined`
- `already_joined`
- `request_sent`

## Telegram Folder

Add already-joined public channels to the `Lead Search 1` folder:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/folders/lead-search" \
  -H "Content-Type: application/json" \
  -d '{"folder_name":"Lead Search 1","channel_identifiers":["@lazyproducer","@MaximKruchkov"]}'
```

List folders:

```bash
curl -sS "$BASE_URL/sessions/$SESSION_ID/chats/folders"
```

Read chats from a folder:

```bash
curl -sS -X POST "$BASE_URL/sessions/$SESSION_ID/chats/folder" \
  -H "Content-Type: application/json" \
  -d '{"folder_name":"Lead Search 1","limit":100}'
```

## Lead Database

Save an evaluated channel to local SQLite:

```bash
curl -sS -X POST "$BASE_URL/api/leads" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Ленивый продюсер. Блог.",
    "username": "lazyproducer",
    "url": "https://t.me/lazyproducer",
    "niche": "продюсирование / онлайн-школы",
    "subscribers": 15000,
    "is_public": true,
    "has_comments": true,
    "monetization_signals": "посты про запуски, продукт, консультации",
    "lead_score": 8,
    "reason": "автор пишет для владельцев экспертных продуктов, есть аудитория и регулярная боль запусков",
    "suggested_ai_product": "AI-ассистент запуска: упаковка оффера, прогрев, контент-план и аналитика в Telegram",
    "status": "subscribed",
    "subscribed": true,
    "folder": "Lead Search 1"
  }'
```

For score 5-6, save as `maybe` and do not subscribe automatically:

```bash
curl -sS -X POST "$BASE_URL/api/leads" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Maybe Channel",
    "username": "maybe_channel",
    "url": "https://t.me/maybe_channel",
    "niche": "AI для бизнеса",
    "lead_score": 6,
    "status": "maybe",
    "subscribed": false
  }'
```

List all saved leads:

```bash
curl -sS "$BASE_URL/api/leads"
```

List maybe leads:

```bash
curl -sS "$BASE_URL/api/leads?status=maybe"
```

## Company CRM

Use companies only for account/client setup, not for individual Telegram leads:

```bash
curl -sS "$BASE_URL/api/companies"

curl -sS -X POST "$BASE_URL/api/companies" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme","website":"https://example.com","telegram_chat":"@acme"}'
```

## Safety Rules

Prefer read-only calls while researching.

Mutating calls:

- `POST /sessions/{session_id}/channels/join`
- `POST /sessions/{session_id}/folders/lead-search`
- `POST /sessions/{session_id}/messages/send`
- `PATCH /sessions/{session_id}/messages/edit`
- `DELETE /sessions/{session_id}/messages/delete`
- `POST /sessions/{session_id}/messages/reaction`
- `POST /sessions/{session_id}/chats/invite`
- `POST /sessions/{session_id}/users/block`
- `POST /sessions/{session_id}/channels/posts/publish`

Do not write comments, DM authors, send bulk messages, join private channels, or submit private join requests unless the user explicitly asks.

## Errors

- `401`: session is not authorized. Run the auth flow.
- `400`: Telegram rejected the request. Read `detail`.
- Flood wait: stop and wait for the specified seconds.
- Missing `API_ID`/`API_HASH`: configure `/home/user/tg_client/.env` and restart the API.

## Web UI and Logs

- UI/API root: `http://127.0.0.1:80/`
- Docs: `http://127.0.0.1:80/docs`
- Container logs:

```bash
docker logs -f tg_crm_api
docker logs -f tg_crm_api_proxy
```
