# Repository Guidelines

## Project Structure & Module Organization
- `app/` contains the API implementation:
- `app/main.py` defines FastAPI routes and lifecycle hooks.
- `app/telegram_client.py` wraps Telethon logic (auth, chats, messages, media).
- `app/storage.py` stores Telegram sessions and CRM companies in local SQLite.
- `app/models.py` stores Pydantic request/response schemas.
- `app/config.py` loads environment configuration and database path.
- `app/static/index.html` contains the minimal company settings UI.
- `data/` stores local SQLite data at runtime (gitignored).
- `docker-compose.yml` defines the local `tg_api` service.
- `requirements.txt` and `Dockerfile` define Python dependencies and container runtime.

## Build, Test, and Development Commands
- Install dependencies: `pip install -r requirements.txt`
- Run API locally (dev): `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Run API in Docker: `docker compose up --build tg_api`
- Stop services: `docker compose down`

Open API docs after startup: `http://localhost:8000/docs`.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and type hints for public functions.
- Keep modules snake_case (`telegram_client.py`), classes PascalCase (`TelegramClientManager`), functions/variables snake_case.
- Prefer explicit Pydantic models for all API payloads.
- Keep route handlers in `main.py`; move Telegram business logic into `telegram_client.py`.
- Use clear, actionable logging messages via `logging` (already configured in `main.py`).

## Testing Guidelines
- No automated test suite is committed yet; add tests with `pytest` under `tests/`.
- Name files `test_*.py` and mirror module structure (example: `tests/test_telegram_client.py`).
- For API tests, use FastAPI `TestClient` and mock Telethon/network calls.
- Before opening a PR, at minimum run local startup and smoke-test key endpoints (`/`, `/api/status`, `/api/companies`, `/sessions/{session_id}/auth/login`, `/sessions/{session_id}/chats`).

## Commit & Pull Request Guidelines
- Current history uses short, imperative commit messages (example: `add GET messages/media`, `upd get messages`).
- Prefer: `<verb> <scope>` in lowercase, one logical change per commit.
- PRs should include:
- clear summary of behavior changes,
- related issue/task reference,
- manual verification steps (commands + endpoints tested),
- screenshots or sample responses when API behavior/output changes.

## Security & Configuration Tips
- Never commit `.env`, API credentials, or local SQLite data.
- Keep `API_ID`, `API_HASH`, and optional `PROXY_URL` in environment variables.
- Use `.env.example` as the baseline when introducing new config keys.
