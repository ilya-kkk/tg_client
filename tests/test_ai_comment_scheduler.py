import unittest
from datetime import datetime, timezone
import sys
import types


def _install_dependency_stubs() -> None:
    if "dotenv" not in sys.modules:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: None
        sys.modules["dotenv"] = dotenv_module

    if "httpx" not in sys.modules:
        httpx_module = types.ModuleType("httpx")

        class AsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        httpx_module.AsyncClient = AsyncClient
        sys.modules["httpx"] = httpx_module

    if "supabase" not in sys.modules:
        supabase_module = types.ModuleType("supabase")

        class Client:
            pass

        def create_client(*args, **kwargs):
            return Client()

        supabase_module.Client = Client
        supabase_module.create_client = create_client
        sys.modules["supabase"] = supabase_module

    if "telethon" in sys.modules:
        return

    telethon_module = types.ModuleType("telethon")

    class TelegramClient:
        def __init__(self, *args, **kwargs):
            pass

    class NewMessage:
        Event = object

        def __init__(self, *args, **kwargs):
            pass

    telethon_module.TelegramClient = TelegramClient
    telethon_module.events = types.SimpleNamespace(NewMessage=NewMessage)
    sys.modules["telethon"] = telethon_module

    sessions_module = types.ModuleType("telethon.sessions")

    class StringSession:
        def __init__(self, *args, **kwargs):
            pass

    sessions_module.StringSession = StringSession
    sys.modules["telethon.sessions"] = sessions_module

    errors_module = types.ModuleType("telethon.errors")

    class SessionPasswordNeededError(Exception):
        pass

    class PhoneCodeInvalidError(Exception):
        pass

    class PhoneNumberInvalidError(Exception):
        pass

    class FloodWaitError(Exception):
        def __init__(self, seconds: int = 0):
            super().__init__(seconds)
            self.seconds = seconds

    class RPCError(Exception):
        def __init__(self, message: str = ""):
            super().__init__(message)
            self.message = message

    errors_module.SessionPasswordNeededError = SessionPasswordNeededError
    errors_module.PhoneCodeInvalidError = PhoneCodeInvalidError
    errors_module.PhoneNumberInvalidError = PhoneNumberInvalidError
    errors_module.FloodWaitError = FloodWaitError
    errors_module.RPCError = RPCError
    sys.modules["telethon.errors"] = errors_module

    tl_module = types.ModuleType("telethon.tl")
    sys.modules["telethon.tl"] = tl_module

    functions_module = types.ModuleType("telethon.tl.functions")
    functions_module.messages = types.SimpleNamespace(
        SendReactionRequest=type("SendReactionRequest", (), {}),
    )
    sys.modules["telethon.tl.functions"] = functions_module
    tl_module.functions = functions_module

    tl_types_module = types.ModuleType("telethon.tl.types")
    for name in [
        "User",
        "Chat",
        "Channel",
        "MessageMediaPhoto",
        "MessageMediaDocument",
        "DocumentAttributeVideo",
        "DocumentAttributeAudio",
        "DocumentAttributeSticker",
        "PeerUser",
        "PeerChat",
        "PeerChannel",
        "ReactionEmoji",
    ]:
        setattr(tl_types_module, name, type(name, (), {}))
    sys.modules["telethon.tl.types"] = tl_types_module
    tl_module.types = tl_types_module


_install_dependency_stubs()

from app.telegram_client import MultiSessionManager


class FakeMessage:
    def __init__(self, message_id: int, date: datetime):
        self.id = message_id
        self.date = date


class FakeClient:
    def __init__(self, messages_by_entity=None, failing_entities=None):
        self.messages_by_entity = messages_by_entity or {}
        self.failing_entities = set(failing_entities or [])

    async def get_entity(self, entity):
        if entity in self.failing_entities:
            raise ValueError(f"entity {entity} is unavailable")
        return entity

    async def get_messages(self, entity, limit: int):
        messages = self.messages_by_entity.get(entity, [])
        return list(messages)[:limit]


class FakeAiCommentJobsRepo:
    def __init__(self):
        self.calls = []

    def update_last_checked_at(self, job_id: str, last_checked_at: str):
        self.calls.append(
            {
                "job_id": job_id,
                "last_checked_at": last_checked_at,
            }
        )
        return {
            "id": job_id,
            "last_checked_at": last_checked_at,
        }


class TestMultiSessionManager(MultiSessionManager):
    def __init__(self, clients_by_session):
        super().__init__(session_repo=None)
        self.clients_by_session = clients_by_session

    async def get_client(self, session_id: str):
        return self.clients_by_session[session_id]


class AiCommentSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_poll_sets_checkpoint_and_skips_history(self):
        repo = FakeAiCommentJobsRepo()
        manager = TestMultiSessionManager(
            {
                "session-a": FakeClient(
                    messages_by_entity={
                        "@channel_one": [
                            FakeMessage(101, datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)),
                        ]
                    }
                )
            }
        )
        job = {
            "id": "job-1",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["https://t.me/channel_one"],
            "last_checked_at": None,
        }

        before_poll = datetime.now(timezone.utc)
        fresh_posts = await manager.poll_ai_comment_job_channels(
            job,
            ai_comment_jobs_repo=repo,
        )
        after_poll = datetime.now(timezone.utc)

        self.assertEqual(fresh_posts, [])
        self.assertEqual(len(repo.calls), 1)
        stored_checkpoint = datetime.fromisoformat(repo.calls[0]["last_checked_at"])
        self.assertEqual(repo.calls[0]["job_id"], "job-1")
        self.assertGreaterEqual(stored_checkpoint, before_poll)
        self.assertLessEqual(stored_checkpoint, after_poll)
        self.assertEqual(job["last_checked_at"], repo.calls[0]["last_checked_at"])

    async def test_poll_returns_only_posts_newer_than_last_checked_at(self):
        repo = FakeAiCommentJobsRepo()
        manager = TestMultiSessionManager(
            {
                "session-a": FakeClient(
                    messages_by_entity={
                        "@channel_two": [
                            FakeMessage(205, datetime(2026, 3, 5, 12, 5, tzinfo=timezone.utc)),
                            FakeMessage(204, datetime(2026, 3, 5, 11, 58, tzinfo=timezone.utc)),
                        ]
                    }
                )
            }
        )
        job = {
            "id": "job-2",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_two"],
            "last_checked_at": "2026-03-05T12:00:00+00:00",
        }

        fresh_posts = await manager.poll_ai_comment_job_channels(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(
            fresh_posts,
            [
                {
                    "channel_id": "@channel_two",
                    "message_id": 205,
                    "date": "2026-03-05T12:05:00+00:00",
                    "session_id": "session-a",
                }
            ],
        )
        self.assertEqual(
            repo.calls,
            [
                {
                    "job_id": "job-2",
                    "last_checked_at": "2026-03-05T12:05:00+00:00",
                }
            ],
        )
        self.assertEqual(job["last_checked_at"], "2026-03-05T12:05:00+00:00")

    async def test_checkpoint_is_not_advanced_when_any_channel_fails(self):
        repo = FakeAiCommentJobsRepo()
        manager = TestMultiSessionManager(
            {
                "session-a": FakeClient(
                    messages_by_entity={
                        "@channel_ok": [
                            FakeMessage(305, datetime(2026, 3, 5, 13, 5, tzinfo=timezone.utc)),
                        ]
                    },
                    failing_entities={"@channel_fail"},
                )
            }
        )
        job = {
            "id": "job-3",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_ok", "@channel_fail"],
            "last_checked_at": "2026-03-05T13:00:00+00:00",
        }

        fresh_posts = await manager.poll_ai_comment_job_channels(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(len(fresh_posts), 1)
        self.assertEqual(fresh_posts[0]["message_id"], 305)
        self.assertEqual(repo.calls, [])
        self.assertEqual(job["last_checked_at"], "2026-03-05T13:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
