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
