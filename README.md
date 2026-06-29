# Telegram CRM API

Minimal local CRM shell plus a Telethon-backed REST API for Telegram research.

## What Is Included

- FastAPI backend with Swagger at `http://localhost:80/docs`.
- Minimal company settings UI at `http://localhost:80/`.
- Local SQLite storage in `data/app.db`.
- Multi-session Telegram auth via Telethon `StringSession`.
- All services are orchestrated by one Docker Compose file.
- Optional PostgreSQL + Adminer + N8N services via Compose profile `all`.

## Requirements

- Python 3.11+
- Telegram `API_ID` and `API_HASH` from `https://my.telegram.org/apps`

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here
DATABASE_PATH=data/app.db
```

## Run Locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

- CRM UI: `http://localhost:8000` (если стартовали без прокси)
- API status: `http://localhost:8000/api/status`
- Swagger: `http://localhost:8000/docs`

## Run In Docker

```bash
docker compose up --build
```

- API is available at `http://localhost:80/`
- API status: `http://localhost:80/api/status`
- Swagger: `http://localhost:80/docs`

Data is stored in named Docker volume `tg_crm_data`.

Run full stack (PostgreSQL + Adminer + N8N) with:

```bash
docker compose --profile all up --build
```

## Company API

```bash
curl http://localhost:80/api/companies

curl -X POST http://localhost:80/api/companies \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme","website":"https://example.com","telegram_chat":"@acme"}'
```

## Telegram Session Flow

Use a stable `session_id` for each Telegram account.

```bash
curl -X POST "http://localhost:80/sessions/main/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+79991234567"}'

curl -X POST "http://localhost:80/sessions/main/auth/verify" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+79991234567","code":"12345"}'
```

If Telegram asks for 2FA:

```bash
curl -X POST "http://localhost:80/sessions/main/auth/password" \
  -H "Content-Type: application/json" \
  -d '{"password":"your_2fa_password"}'
```

Useful research endpoints:

- `GET /sessions/{session_id}/chats?limit=100`
- `GET /sessions/{session_id}/messages?chat_identifier=@chat&limit=50`
- `POST /sessions/{session_id}/messages/search`
- `GET /sessions/{session_id}/messages/media?chat_identifier=@chat&message_id=123`

## Security Notes

- Do not commit `.env` or `data/app.db`.
- Do not expose this API publicly without auth in front of it.
- Treat Telegram verification codes and 2FA passwords as secrets.
