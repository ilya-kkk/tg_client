import os
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL и SUPABASE_KEY должны быть заданы в окружении")

REST_BASE_URL = SUPABASE_URL.rstrip("/") + "/rest/v1"

supabase_client = httpx.Client(
    base_url=REST_BASE_URL,
    headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    },
    timeout=10.0,
)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=4, max_length=128)


class LoginResponse(BaseModel):
    success: bool
    message: str


app = FastAPI(title="Logic API", description="Простой backend для авторизации пользователя")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


TEST_USERNAME = "admin"
TEST_PASSWORD = "admin1234"


@app.on_event("startup")
def ensure_test_user() -> None:
    """Создаёт тестового пользователя в таблице users, если его ещё нет."""
    try:
        resp = supabase_client.get(
            "/users",
            params={
                "select": "id",
                "username": f"eq.{TEST_USERNAME}",
                "limit": "1",
            },
        )
        resp.raise_for_status()
        data: List[Dict[str, Any]] = resp.json()
        if data:
            # Обновляем пароль на тестовый (в dev‑режиме храним его в базе в открытом виде)
            user_id = data[0]["id"]
            update_resp = supabase_client.patch(
                "/users",
                params={"id": f"eq.{user_id}"},
                json={"password_hash": TEST_PASSWORD},
                headers={"Prefer": "return=minimal"},
            )
            update_resp.raise_for_status()
            return

        insert_resp = supabase_client.post(
            "/users",
            json={"username": TEST_USERNAME, "password_hash": TEST_PASSWORD},
            headers={"Prefer": "return=minimal"},
        )
        insert_resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        # Пусть приложение всё равно стартует, но логин будет падать
        print(f"Не удалось убедиться в наличии тестового пользователя: {exc}")


@app.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    """Проверяет логин/пароль по таблице users в Supabase."""
    try:
        resp = supabase_client.get(
            "/users",
            params={
                "select": "id,username,password_hash",
                "username": f"eq.{payload.username}",
                "limit": "1",
            },
        )
        resp.raise_for_status()
        rows: List[Dict[str, Any]] = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ошибка доступа к базе: {exc}")

    if not rows:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    user = rows[0]
    # В dev‑режиме сравниваем пароль как обычный текст
    if payload.password != user["password_hash"]:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    return LoginResponse(success=True, message="Успешный вход")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

