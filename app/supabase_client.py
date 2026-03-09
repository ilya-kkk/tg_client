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


class ReactionJobsRepo:
    """Репозиторий кампаний авто-реакций."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
        self.table_name = "reaction_jobs"

    def list_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def list_active(self) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        return response.data or []

    def get_by_id(self, user_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def create(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = {**payload, "user_id": user_id}
        response = self.client.table(self.table_name).insert(data).execute()
        if response.data:
            return response.data[0]
        return data

    def update(self, user_id: str, job_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def delete(self, user_id: str, job_id: str) -> bool:
        existing = self.get_by_id(user_id=user_id, job_id=job_id)
        if existing is None:
            return False
        self.client.table(self.table_name).delete().eq("user_id", user_id).eq("id", job_id).execute()
        return self.get_by_id(user_id=user_id, job_id=job_id) is None


class AiCommentJobsRepo:
    """Репозиторий кампаний нейрокомментирования."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
        self.table_name = "ai_comment_jobs"

    def list_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def list_active(self) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("is_active", True)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def create(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = {**payload, "user_id": user_id}
        response = self.client.table(self.table_name).insert(data).execute()
        if response.data:
            return response.data[0]
        return data

    def get_by_id(self, user_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def get_by_id_for_worker(self, job_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def update(self, user_id: str, job_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def update_last_checked_at(self, job_id: str, last_checked_at: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .update({"last_checked_at": last_checked_at})
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def delete(self, user_id: str, job_id: str) -> bool:
        existing = self.get_by_id(user_id=user_id, job_id=job_id)
        if existing is None:
            return False
        self.client.table(self.table_name).delete().eq("user_id", user_id).eq("id", job_id).execute()
        return self.get_by_id(user_id=user_id, job_id=job_id) is None

    def list_history(self, user_id: str, job_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("ai_comment_job_posts")
            .select("channel_id,message_id,comment_message_id,comment_text,status,error,created_at")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_history_record(
        self,
        *,
        job_id: str,
        channel_id: str,
        message_id: int,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table("ai_comment_job_posts")
            .select(
                "job_id,channel_id,message_id,status,error,comment_message_id,comment_text,created_at"
            )
            .eq("job_id", job_id)
            .eq("channel_id", channel_id)
            .eq("message_id", int(message_id))
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def upsert_history_record(
        self,
        *,
        job_id: str,
        channel_id: str,
        message_id: int,
        status: str,
        error: Optional[str] = None,
        comment_message_id: Optional[int] = None,
        comment_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        normalized_channel_id = str(channel_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id не может быть пустым")
        if not normalized_channel_id:
            raise ValueError("channel_id не может быть пустым")

        payload: Dict[str, Any] = {
            "job_id": normalized_job_id,
            "channel_id": normalized_channel_id,
            "message_id": int(message_id),
            "status": str(status or "").strip(),
            "error": (error or None),
        }
        if comment_message_id is not None:
            payload["comment_message_id"] = int(comment_message_id)
        if comment_text is not None:
            payload["comment_text"] = str(comment_text).strip() or None

        response = (
            self.client.table("ai_comment_job_posts")
            .upsert(payload, on_conflict="job_id,channel_id,message_id")
            .execute()
        )
        if response.data:
            return response.data[0]
        return payload


class AiReplyJobsRepo:
    """Репозиторий кампаний нейроответов."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
        self.table_name = "ai_reply_jobs"

    def list_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def list_active(self) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("is_active", True)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def create(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = {**payload, "user_id": user_id}
        response = self.client.table(self.table_name).insert(data).execute()
        if response.data:
            return response.data[0]
        return data

    def get_by_id(self, user_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def get_by_id_for_worker(self, job_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def update(self, user_id: str, job_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def update_last_checked_at(self, job_id: str, last_checked_at: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .update({"last_checked_at": last_checked_at})
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def delete(self, user_id: str, job_id: str) -> bool:
        existing = self.get_by_id(user_id=user_id, job_id=job_id)
        if existing is None:
            return False
        self.client.table(self.table_name).delete().eq("user_id", user_id).eq("id", job_id).execute()
        return self.get_by_id(user_id=user_id, job_id=job_id) is None

    def list_history(self, user_id: str, job_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("ai_reply_job_messages")
            .select(
                "chat_id,chat_name,message_id,sender_id,message_text,message_date,matched_trigger,reply_message_id,reply_text,processed_session_id,status,error,created_at"
            )
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    def get_history_record(
        self,
        *,
        job_id: str,
        chat_id: str,
        message_id: int,
    ) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table("ai_reply_job_messages")
            .select(
                "job_id,chat_id,chat_name,message_id,sender_id,message_text,message_date,matched_trigger,reply_message_id,reply_text,processed_session_id,status,error,created_at"
            )
            .eq("job_id", job_id)
            .eq("chat_id", chat_id)
            .eq("message_id", int(message_id))
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def upsert_history_record(
        self,
        *,
        job_id: str,
        chat_id: str,
        message_id: int,
        status: str,
        chat_name: Optional[str] = None,
        sender_id: Optional[int] = None,
        message_text: Optional[str] = None,
        message_date: Optional[str] = None,
        matched_trigger: Optional[str] = None,
        reply_message_id: Optional[int] = None,
        reply_text: Optional[str] = None,
        processed_session_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_job_id = str(job_id or "").strip()
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id не может быть пустым")
        if not normalized_chat_id:
            raise ValueError("chat_id не может быть пустым")

        payload: Dict[str, Any] = {
            "job_id": normalized_job_id,
            "chat_id": normalized_chat_id,
            "message_id": int(message_id),
            "status": str(status or "").strip(),
            "error": (error or None),
        }
        if chat_name is not None:
            payload["chat_name"] = str(chat_name).strip() or None
        if sender_id is not None:
            payload["sender_id"] = int(sender_id)
        if message_text is not None:
            payload["message_text"] = str(message_text).strip() or None
        if message_date is not None:
            payload["message_date"] = str(message_date).strip() or None
        if matched_trigger is not None:
            payload["matched_trigger"] = str(matched_trigger).strip() or None
        if reply_message_id is not None:
            payload["reply_message_id"] = int(reply_message_id)
        if reply_text is not None:
            payload["reply_text"] = str(reply_text).strip() or None
        if processed_session_id is not None:
            payload["processed_session_id"] = str(processed_session_id).strip() or None

        response = (
            self.client.table("ai_reply_job_messages")
            .upsert(payload, on_conflict="job_id,chat_id,message_id")
            .execute()
        )
        if response.data:
            return response.data[0]
        return payload


class WarmupJobsRepo:
    """Репозиторий кампаний прогрева."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
        self.table_name = "warmup_jobs"

    def list_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return response.data or []

    def list_active(self) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        return response.data or []

    def create(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = {**payload, "user_id": user_id}
        response = self.client.table(self.table_name).insert(data).execute()
        if response.data:
            return response.data[0]
        return data

    def get_by_id(self, user_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def update(self, user_id: str, job_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .update(payload)
            .eq("user_id", user_id)
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def delete(self, user_id: str, job_id: str) -> bool:
        existing = self.get_by_id(user_id=user_id, job_id=job_id)
        if existing is None:
            return False
        self.client.table(self.table_name).delete().eq("user_id", user_id).eq("id", job_id).execute()
        return self.get_by_id(user_id=user_id, job_id=job_id) is None
