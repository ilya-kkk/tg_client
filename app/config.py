import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# API credentials (получить на https://my.telegram.org/apps)
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")

# Прокси (опционально, для решения проблем с геолокацией)
# Формат: socks5://user:pass@host:port или http://user:pass@host:port
PROXY_URL = os.getenv("PROXY_URL", None)

# Директория для сессий
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# Имя файла сессии
SESSION_NAME = "telegram_session"
