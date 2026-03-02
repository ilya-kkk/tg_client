import os
from typing import Optional

from supabase import Client, create_client


_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """Возвращает singleton-клиент Supabase."""
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_KEY", "").strip()

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL и SUPABASE_KEY должны быть установлены")

    _supabase_client = create_client(supabase_url, supabase_key)
    return _supabase_client
