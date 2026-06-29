import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import DATABASE_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteStorage:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                create table if not exists telegram_sessions (
                    session_id text primary key,
                    phone text,
                    string_session text,
                    phone_code_hash text,
                    is_authorized integer not null default 0,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists companies (
                    id integer primary key autoincrement,
                    name text not null,
                    website text,
                    telegram_chat text,
                    description text,
                    notes text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists leads (
                    id integer primary key autoincrement,
                    title text not null,
                    username text,
                    url text not null unique,
                    niche text,
                    subscribers integer,
                    is_public integer not null default 1,
                    has_comments integer not null default 0,
                    monetization_signals text,
                    lead_score integer not null,
                    reason text,
                    suggested_ai_product text,
                    status text not null default 'new',
                    subscribed integer not null default 0,
                    folder text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists channel_posts (
                    channel_username text not null,
                    channel_id integer,
                    message_id integer not null,
                    post_url text,
                    date text,
                    text text,
                    views integer,
                    forwards integer,
                    replies_count integer,
                    reactions_count integer,
                    has_media integer not null default 0,
                    has_link integer not null default 0,
                    is_forward integer not null default 0,
                    is_ad_like integer not null default 0,
                    collected_at text not null,
                    primary key (channel_username, message_id)
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_channel_posts_channel
                on channel_posts (channel_username, date desc)
                """
            )
            conn.execute(
                """
                create table if not exists channel_comments (
                    channel_username text not null,
                    post_message_id integer not null,
                    comment_id integer not null,
                    comment_text text,
                    comment_date text,
                    commenter_id_hash text,
                    commenter_username text,
                    is_author_reply integer not null default 0,
                    is_spam_like integer not null default 0,
                    collected_at text not null,
                    primary key (channel_username, comment_id)
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_channel_comments_channel
                on channel_comments (channel_username, comment_date desc)
                """
            )
            conn.execute(
                """
                create table if not exists channel_metrics (
                    channel_username text primary key,
                    subscribers_count integer,
                    posts_analyzed integer,
                    median_views real,
                    avg_views real,
                    view_rate real,
                    posts_per_week real,
                    views_cv real,
                    median_reactions real,
                    reaction_rate real,
                    median_forwards real,
                    forward_rate real,
                    last_post_at text,
                    calculated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists discussion_metrics (
                    channel_username text primary key,
                    posts_with_comments integer,
                    median_comments real,
                    avg_comments real,
                    comment_rate real,
                    unique_commenters integer,
                    author_replies_count integer,
                    author_reply_rate real,
                    spam_ratio real,
                    discussion_score real,
                    comments_enabled integer not null default 0,
                    calculated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists campaign_scores (
                    channel_username text primary key,
                    niche_fit_score real,
                    monetization_signal_score real,
                    audience_attention_score real,
                    discussion_score real,
                    business_fit_score real,
                    campaign_score real,
                    recommended_action text,
                    reason text,
                    suggested_ai_product text,
                    calculated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists channel_profiles (
                    channel_username text primary key,
                    title text,
                    url text,
                    niche text,
                    monetization_signals text,
                    subscribers_count integer,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists opportunity_posts (
                    id integer primary key autoincrement,
                    channel_username text,
                    message_id integer,
                    post_url text,
                    date text,
                    text text,
                    views integer,
                    comments_count integer,
                    reactions_count integer,
                    post_relevance_score real,
                    pain_markers text,
                    suggested_angle text,
                    opportunity_score real,
                    calculated_at text not null,
                    unique (channel_username, message_id)
                )
                """
            )
            conn.commit()


class SessionRepo(SQLiteStorage):
    """Local repository for Telegram StringSession records."""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["is_authorized"] = bool(data.get("is_authorized"))
        return data

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from telegram_sessions where session_id = ? limit 1",
                (session_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "select * from telegram_sessions order by created_at asc"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert(
        self,
        session_id: str,
        phone: Optional[str] = None,
        string_session: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        is_authorized: Optional[bool] = None,
    ) -> Dict[str, Any]:
        now = _now()
        fields: Dict[str, Any] = {"updated_at": now}
        if phone is not None:
            fields["phone"] = phone
        if string_session is not None:
            fields["string_session"] = string_session
        if phone_code_hash is not None:
            fields["phone_code_hash"] = phone_code_hash
        if is_authorized is not None:
            fields["is_authorized"] = int(is_authorized)

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "select session_id from telegram_sessions where session_id = ? limit 1",
                (session_id,),
            ).fetchone()
            if existing:
                assignments = ", ".join(f"{key} = ?" for key in fields)
                conn.execute(
                    f"update telegram_sessions set {assignments} where session_id = ?",
                    (*fields.values(), session_id),
                )
            else:
                payload = {
                    "session_id": session_id,
                    "phone": phone,
                    "string_session": string_session,
                    "phone_code_hash": phone_code_hash,
                    "is_authorized": int(is_authorized or False),
                    "created_at": now,
                    "updated_at": now,
                }
                columns = ", ".join(payload.keys())
                placeholders = ", ".join("?" for _ in payload)
                conn.execute(
                    f"insert into telegram_sessions ({columns}) values ({placeholders})",
                    tuple(payload.values()),
                )
            conn.commit()
        return self.get(session_id) or {"session_id": session_id}

    def delete(self, session_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "delete from telegram_sessions where session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

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


class CompanyRepo(SQLiteStorage):
    """Local repository for CRM company records."""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "select * from companies order by updated_at desc, id desc"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, company_id: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from companies where id = ? limit 1",
                (company_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = _now()
        data = {
            "name": payload["name"],
            "website": payload.get("website"),
            "telegram_chat": payload.get("telegram_chat"),
            "description": payload.get("description"),
            "notes": payload.get("notes"),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                insert into companies (
                    name, website, telegram_chat, description, notes,
                    created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(data.values()),
            )
            conn.commit()
            company_id = int(cursor.lastrowid)
        return self.get(company_id) or {"id": company_id, **data}

    def update(self, company_id: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {"name", "website", "telegram_chat", "description", "notes"}
        fields = {key: value for key, value in payload.items() if key in allowed}
        if not fields:
            return self.get(company_id)
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"update companies set {assignments} where id = ?",
                (*fields.values(), company_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get(company_id)

    def delete(self, company_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("delete from companies where id = ?", (company_id,))
            conn.commit()
            return cursor.rowcount > 0


class LeadRepo(SQLiteStorage):
    """Local repository for Telegram lead search results."""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["is_public"] = bool(data.get("is_public"))
        data["has_comments"] = bool(data.get("has_comments"))
        data["subscribed"] = bool(data.get("subscribed"))
        return data

    def list_all(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    select * from leads
                    where status = ?
                    order by lead_score desc, updated_at desc, id desc
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select * from leads
                    order by lead_score desc, updated_at desc, id desc
                    """
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from leads where url = ? limit 1",
                (url,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = _now()
        url = payload["url"]
        data = {
            "title": payload["title"],
            "username": payload.get("username"),
            "url": url,
            "niche": payload.get("niche"),
            "subscribers": payload.get("subscribers"),
            "is_public": int(payload.get("is_public", True)),
            "has_comments": int(payload.get("has_comments", False)),
            "monetization_signals": payload.get("monetization_signals"),
            "lead_score": payload["lead_score"],
            "reason": payload.get("reason"),
            "suggested_ai_product": payload.get("suggested_ai_product"),
            "status": payload.get("status") or "new",
            "subscribed": int(payload.get("subscribed", False)),
            "folder": payload.get("folder"),
            "updated_at": now,
        }
        existing = self.get_by_url(url)
        with self._lock, self._connect() as conn:
            if existing:
                assignments = ", ".join(f"{key} = ?" for key in data)
                conn.execute(
                    f"update leads set {assignments} where url = ?",
                    (*data.values(), url),
                )
                lead_id = existing["id"]
            else:
                insert_data = {**data, "created_at": now}
                columns = ", ".join(insert_data.keys())
                placeholders = ", ".join("?" for _ in insert_data)
                cursor = conn.execute(
                    f"insert into leads ({columns}) values ({placeholders})",
                    tuple(insert_data.values()),
                )
                lead_id = int(cursor.lastrowid)
            conn.commit()

            row = conn.execute(
                "select * from leads where id = ? limit 1",
                (lead_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else {"id": lead_id, **payload}


class ChannelAnalyticsRepo(SQLiteStorage):
    """Local repository for channel analytics and scoring cache."""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def upsert_channel_profile(
        self,
        channel_username: str,
        title: Optional[str],
        url: Optional[str],
        niche: Optional[str],
        monetization_signals: Optional[str],
        subscribers_count: Optional[int] = None,
    ) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into channel_profiles (
                    channel_username, title, url, niche,
                    monetization_signals, subscribers_count, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(channel_username) do update set
                    title=excluded.title,
                    url=excluded.url,
                    niche=excluded.niche,
                    monetization_signals=excluded.monetization_signals,
                    subscribers_count=excluded.subscribers_count,
                    updated_at=excluded.updated_at
                """,
                (
                    channel_username,
                    title,
                    url,
                    niche,
                    monetization_signals,
                    subscribers_count,
                    now,
                ),
            )
            conn.commit()

    def list_profiles(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                select * from channel_profiles
                order by updated_at desc
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_channel_posts(self, channel_username: str, posts: List[Dict[str, Any]]) -> int:
        if not posts:
            return 0

        now = _now()
        with self._lock, self._connect() as conn:
            for post in posts:
                conn.execute(
                    """
                    insert into channel_posts (
                        channel_username, channel_id, message_id, post_url, date,
                        text, views, forwards, replies_count, reactions_count,
                        has_media, has_link, is_forward, is_ad_like, collected_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(channel_username, message_id) do update set
                        channel_id=excluded.channel_id,
                        post_url=excluded.post_url,
                        date=excluded.date,
                        text=excluded.text,
                        views=excluded.views,
                        forwards=excluded.forwards,
                        replies_count=excluded.replies_count,
                        reactions_count=excluded.reactions_count,
                        has_media=excluded.has_media,
                        has_link=excluded.has_link,
                        is_forward=excluded.is_forward,
                        is_ad_like=excluded.is_ad_like,
                        collected_at=excluded.collected_at
                    """,
                    (
                        channel_username,
                        self._coerce_int(post.get("channel_id")),
                        self._coerce_int(post.get("message_id")),
                        post.get("post_url"),
                        post.get("date"),
                        post.get("text"),
                        self._coerce_int(post.get("views")),
                        self._coerce_int(post.get("forwards")),
                        self._coerce_int(post.get("replies_count")),
                        1 if post.get("has_media") else 0,
                        1 if post.get("has_link") else 0,
                        1 if post.get("is_forward") else 0,
                        1 if post.get("is_ad_like") else 0,
                        now,
                    ),
                )
            conn.commit()
        return len(posts)

    def list_channel_posts(
        self,
        channel_username: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from channel_posts
                where channel_username = ?
                order by date desc, message_id desc
                limit ?
                """,
                (channel_username, int(limit)),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_channel_comments(self, channel_username: str, comments: List[Dict[str, Any]]) -> int:
        if not comments:
            return 0

        now = _now()
        with self._lock, self._connect() as conn:
            for comment in comments:
                conn.execute(
                    """
                    insert into channel_comments (
                        channel_username, post_message_id, comment_id,
                        comment_text, comment_date, commenter_id_hash,
                        commenter_username, is_author_reply, is_spam_like,
                        collected_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(channel_username, comment_id) do update set
                        post_message_id=excluded.post_message_id,
                        comment_text=excluded.comment_text,
                        comment_date=excluded.comment_date,
                        commenter_id_hash=excluded.commenter_id_hash,
                        commenter_username=excluded.commenter_username,
                        is_author_reply=excluded.is_author_reply,
                        is_spam_like=excluded.is_spam_like,
                        collected_at=excluded.collected_at
                    """,
                    (
                        channel_username,
                        self._coerce_int(comment.get("post_message_id")),
                        self._coerce_int(comment.get("comment_id")),
                        comment.get("comment_text"),
                        comment.get("comment_date"),
                        comment.get("commenter_id_hash"),
                        comment.get("commenter_username"),
                        1 if comment.get("is_author_reply") else 0,
                        1 if comment.get("is_spam_like") else 0,
                        now,
                    ),
                )
            conn.commit()
        return len(comments)

    def list_channel_comments(self, channel_username: str, limit: int = 500) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from channel_comments
                where channel_username = ?
                order by comment_date desc, comment_id desc
                limit ?
                """,
                (channel_username, int(limit)),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_channel_metrics(self, channel_username: str, payload: Dict[str, Any]) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into channel_metrics (
                    channel_username, subscribers_count, posts_analyzed,
                    median_views, avg_views, view_rate, posts_per_week,
                    views_cv, median_reactions, reaction_rate, median_forwards,
                    forward_rate, last_post_at, calculated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(channel_username) do update set
                    subscribers_count=excluded.subscribers_count,
                    posts_analyzed=excluded.posts_analyzed,
                    median_views=excluded.median_views,
                    avg_views=excluded.avg_views,
                    view_rate=excluded.view_rate,
                    posts_per_week=excluded.posts_per_week,
                    views_cv=excluded.views_cv,
                    median_reactions=excluded.median_reactions,
                    reaction_rate=excluded.reaction_rate,
                    median_forwards=excluded.median_forwards,
                    forward_rate=excluded.forward_rate,
                    last_post_at=excluded.last_post_at,
                    calculated_at=excluded.calculated_at
                """,
                (
                    channel_username,
                    payload.get("subscribers_count"),
                    self._coerce_int(payload.get("posts_analyzed")),
                    self._coerce_float(payload.get("median_views_30")),
                    self._coerce_float(payload.get("avg_views_30")),
                    self._coerce_float(payload.get("view_rate")),
                    self._coerce_float(payload.get("posts_per_week")),
                    self._coerce_float(payload.get("views_cv")),
                    self._coerce_float(payload.get("median_reactions")),
                    self._coerce_float(payload.get("reaction_rate")),
                    self._coerce_float(payload.get("median_forwards")),
                    payload.get("forward_rate"),
                    payload.get("last_post_at"),
                    now,
                ),
            )
            conn.commit()

    def get_channel_metrics(self, channel_username: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from channel_metrics where channel_username = ? limit 1",
                (channel_username,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def upsert_discussion_metrics(self, channel_username: str, payload: Dict[str, Any]) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into discussion_metrics (
                    channel_username, posts_with_comments, median_comments,
                    avg_comments, comment_rate, unique_commenters,
                    author_replies_count, author_reply_rate, spam_ratio,
                    discussion_score, comments_enabled, calculated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(channel_username) do update set
                    posts_with_comments=excluded.posts_with_comments,
                    median_comments=excluded.median_comments,
                    avg_comments=excluded.avg_comments,
                    comment_rate=excluded.comment_rate,
                    unique_commenters=excluded.unique_commenters,
                    author_replies_count=excluded.author_replies_count,
                    author_reply_rate=excluded.author_reply_rate,
                    spam_ratio=excluded.spam_ratio,
                    discussion_score=excluded.discussion_score,
                    comments_enabled=excluded.comments_enabled,
                    calculated_at=excluded.calculated_at
                """,
                (
                    channel_username,
                    self._coerce_int(payload.get("posts_with_comments")),
                    self._coerce_float(payload.get("median_comments_30")),
                    self._coerce_float(payload.get("avg_comments_30")),
                    self._coerce_float(payload.get("comment_rate")),
                    self._coerce_int(payload.get("unique_commenters_30")),
                    self._coerce_int(payload.get("author_replies_count")),
                    self._coerce_float(payload.get("author_reply_rate")),
                    self._coerce_float(payload.get("spam_ratio")),
                    self._coerce_float(payload.get("discussion_score")),
                    1 if payload.get("comments_enabled") else 0,
                    now,
                ),
            )
            conn.commit()

    def get_discussion_metrics(self, channel_username: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from discussion_metrics where channel_username = ? limit 1",
                (channel_username,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def upsert_campaign_score(self, channel_username: str, payload: Dict[str, Any]) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into campaign_scores (
                    channel_username, niche_fit_score, monetization_signal_score,
                    audience_attention_score, discussion_score, business_fit_score,
                    campaign_score, recommended_action, reason, suggested_ai_product,
                    calculated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(channel_username) do update set
                    niche_fit_score=excluded.niche_fit_score,
                    monetization_signal_score=excluded.monetization_signal_score,
                    audience_attention_score=excluded.audience_attention_score,
                    discussion_score=excluded.discussion_score,
                    business_fit_score=excluded.business_fit_score,
                    campaign_score=excluded.campaign_score,
                    recommended_action=excluded.recommended_action,
                    reason=excluded.reason,
                    suggested_ai_product=excluded.suggested_ai_product,
                    calculated_at=excluded.calculated_at
                """,
                (
                    channel_username,
                    self._coerce_float(payload.get("niche_fit_score")),
                    self._coerce_float(payload.get("monetization_signal_score")),
                    self._coerce_float(payload.get("audience_attention_score")),
                    self._coerce_float(payload.get("discussion_score")),
                    self._coerce_float(payload.get("business_fit_score")),
                    self._coerce_float(payload.get("campaign_score")),
                    payload.get("recommended_action"),
                    payload.get("reason"),
                    payload.get("suggested_ai_product"),
                    now,
                ),
            )
            conn.commit()

    def get_campaign_score(self, channel_username: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from campaign_scores where channel_username = ? limit 1",
                (channel_username,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def upsert_opportunity_posts(self, channel_username: str, posts: List[Dict[str, Any]]) -> int:
        if not posts:
            return 0

        with self._lock, self._connect() as conn:
            conn.execute(
                "delete from opportunity_posts where channel_username = ?",
                (channel_username,),
            )
            for post in posts:
                conn.execute(
                    """
                    insert into opportunity_posts (
                        channel_username, message_id, post_url, date,
                        text, views, comments_count, reactions_count,
                        post_relevance_score, pain_markers,
                        suggested_angle, opportunity_score, calculated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel_username,
                        self._coerce_int(post.get("message_id")),
                        post.get("post_url"),
                        post.get("date"),
                        post.get("text"),
                        self._coerce_int(post.get("views")),
                        self._coerce_int(post.get("comments_count")),
                        self._coerce_int(post.get("reactions_count")),
                        self._coerce_float(post.get("post_relevance_score")),
                        post.get("pain_markers"),
                        post.get("suggested_angle"),
                        self._coerce_float(post.get("opportunity_score")),
                        _now(),
                    ),
                )
            conn.commit()
        return len(posts)

    def list_opportunity_posts(self, channel_username: str) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                select *
                from opportunity_posts
                where channel_username = ?
                order by opportunity_score desc, date desc
                """,
                (channel_username,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_ranked_channels(
        self,
        min_score: float = 0.0,
        sort: str = "campaign_score",
        recommended_action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sort_fields = {
            "campaign_score": "cs.campaign_score",
            "view_rate": "cm.view_rate",
            "subscribers_count": "cm.subscribers_count",
            "median_views_30": "cm.median_views",
            "median_comments_30": "dm.median_comments",
        }
        sort_field = sort_fields.get(sort, "cs.campaign_score")
        filters: List[Any] = []
        where_clauses: List[str] = ["1=1"]

        if min_score is not None:
            where_clauses.append("cs.campaign_score >= ?")
            filters.append(float(min_score))
        if recommended_action:
            where_clauses.append("cs.recommended_action = ?")
            filters.append(recommended_action)

        query = f"""
            select
                cp.channel_username,
                cp.title,
                cp.url,
                cp.niche,
                cp.monetization_signals,
                cm.subscribers_count,
                cm.median_views,
                cm.view_rate,
                cm.posts_per_week,
                dm.posts_with_comments,
                dm.median_comments,
                dm.comment_rate,
                dm.unique_commenters,
                cs.campaign_score,
                cs.recommended_action,
                cs.reason,
                cs.niche_fit_score,
                cs.monetization_signal_score,
                dm.discussion_score,
                dm.comments_enabled,
                cm.last_post_at,
                cs.suggested_ai_product
            from campaign_scores cs
            join channel_profiles cp on cp.channel_username = cs.channel_username
            left join channel_metrics cm on cm.channel_username = cs.channel_username
            left join discussion_metrics dm on dm.channel_username = cs.channel_username
            where {" and ".join(where_clauses)}
            order by {sort_field} desc
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, tuple(filters)).fetchall()
        return [self._row_to_dict(row) for row in rows]
