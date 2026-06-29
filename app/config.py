import os
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("API_ID") or os.getenv("TELEGRAM_CLIENT_API_ID", "")
API_HASH = os.getenv("API_HASH") or os.getenv("TELEGRAM_CLIENT_API_HASH", "")

PROXY_URL = os.getenv("PROXY_URL", None)

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/app.db")
