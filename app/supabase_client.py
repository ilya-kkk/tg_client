import os
from typing import Any, Dict, List, Optional

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


class SessionRepo:
    """Репозиторий сессий Telegram в таблице Supabase `telegram_sessions`."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
        self.table_name = "telegram_sessions"

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def list_all(self) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def upsert(
        self,
        session_id: str,
        phone: Optional[str] = None,
        string_session: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        is_authorized: Optional[bool] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"session_id": session_id}
        if phone is not None:
            payload["phone"] = phone
        if string_session is not None:
            payload["string_session"] = string_session
        if phone_code_hash is not None:
            payload["phone_code_hash"] = phone_code_hash
        if is_authorized is not None:
            payload["is_authorized"] = is_authorized

        response = (
            self.client.table(self.table_name)
            .upsert(payload, on_conflict="session_id")
            .execute()
        )
        if response.data:
            return response.data[0]
        return payload

    def delete(self, session_id: str) -> bool:
        # Supabase/PostgREST может вернуть пустой data для DELETE даже при успехе,
        # поэтому проверяем факт существования до и после удаления.
        existing = self.get(session_id)
        if existing is None:
            return False

        (
            self.client.table(self.table_name)
            .delete()
            .eq("session_id", session_id)
            .execute()
        )

        return self.get(session_id) is None

    def save_auth_state(
        self, session_id: str, phone: str, phone_code_hash: str
    ) -> Dict[str, Any]:
        return self.upsert(
            session_id=session_id,
            phone=phone,
            phone_code_hash=phone_code_hash,
            is_authorized=False,
        )

    def save_authorized(self, session_id: str, string_session: str) -> Dict[str, Any]:
        return self.upsert(
            session_id=session_id,
            string_session=string_session,
            phone_code_hash="",
            is_authorized=True,
        )


class ParsedChannelsRepo:
    """Репозиторий сохраненных результатов парсинга каналов."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
        self.table_name = "parsed_channels"

    def upsert_many(self, session_id: str, items: List[Dict[str, Any]]) -> int:
        if not items:
            return 0

        payload: List[Dict[str, Any]] = []
        for item in items:
            payload.append(
                {
                    "session_id": session_id,
                    "channel_id": str(item.get("channel_id") or "").strip(),
                    "title": item.get("title"),
                    "username": item.get("username"),
                    "link": item.get("link"),
                    "about": item.get("about"),
                    "participants_count": item.get("participants_count"),
                    "verified": item.get("verified"),
                    "scam": item.get("scam"),
                    "fake": item.get("fake"),
                    "found_by": item.get("found_by") or [],
                }
            )

        cleaned = [row for row in payload if row["channel_id"]]
        if not cleaned:
            return 0

        response = (
            self.client.table(self.table_name)
            .upsert(cleaned, on_conflict="session_id,channel_id")
            .execute()
        )
        return len(response.data or cleaned)

    def list(
        self,
        session_id: Optional[str] = None,
        query: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        request = self.client.table(self.table_name).select("*")
        if session_id:
            request = request.eq("session_id", session_id)

        search_query = (query or "").strip()
        if search_query:
            escaped = search_query.replace("%", "\\%")
            request = request.or_(
                f"title.ilike.%{escaped}%,username.ilike.%{escaped}%,about.ilike.%{escaped}%"
            )

        keyword_value = (keyword or "").strip()
        if keyword_value:
            request = request.contains("found_by", [keyword_value])

        end = max(offset, 0) + max(limit, 1) - 1
        response = (
            request.order("updated_at", desc=True)
            .range(max(offset, 0), end)
            .execute()
        )
        return response.data or []

    def delete(self, session_id: Optional[str] = None) -> int:
        request = self.client.table(self.table_name).delete()
        if session_id:
            request = request.eq("session_id", session_id)
        response = request.execute()
        return len(response.data or [])
