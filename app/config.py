import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# API credentials (получить на https://my.telegram.org/apps)
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")

# Прокси (опционально, для решения проблем с геолокацией)
# Формат: socks5://user:pass@host:port или http://user:pass@host:port
PROXY_URL = os.getenv("PROXY_URL", None)

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


def _parse_env_list(raw_value: str | None) -> list[str]:
    """Парсит список из env-переменной вида 'value-a,value-b'."""
    if not raw_value:
        return []

    return [item.strip() for item in raw_value.split(",") if item.strip()]


OPENROUTER_MODELS = _parse_env_list(os.getenv("OPENROUTER_MODELS")) or [
    "openrouter/free",
]


def _parse_positive_int(raw_value: str | None, default: int) -> int:
    try:
        parsed = int(str(raw_value or "").strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


OPENROUTER_RETRIES_PER_MODEL = _parse_positive_int(
    os.getenv("OPENROUTER_RETRIES_PER_MODEL"),
    2,
)


def _parse_cors_origins(raw_value: str | None) -> list[str]:
    """Парсит CORS origins из строки вида 'http://a,http://b'."""
    if not raw_value:
        return ["*"]

    origins = [origin.strip() for origin in raw_value.split(",") if origin.strip()]
    return origins or ["*"]


CORS_ALLOW_ORIGINS = _parse_cors_origins(os.getenv("CORS_ALLOW_ORIGINS"))
