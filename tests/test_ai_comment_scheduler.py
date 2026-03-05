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
    def __init__(self, message_id: int, date: datetime, text: str = ""):
        self.id = message_id
        self.date = date
        self.message = text
        self.text = text
        self.raw_text = text


class FakeSentMessage:
    def __init__(self, message_id: int):
        self.id = message_id


class FakeClient:
    def __init__(self, messages_by_entity=None, failing_entities=None, failing_send_entities=None):
        self.messages_by_entity = messages_by_entity or {}
        self.failing_entities = set(failing_entities or [])
        self.failing_send_entities = set(failing_send_entities or [])
        self.sent_messages = []

    async def get_entity(self, entity):
        if entity in self.failing_entities:
            raise ValueError(f"entity {entity} is unavailable")
        return entity

    async def get_messages(self, entity, limit: int):
        messages = self.messages_by_entity.get(entity, [])
        return list(messages)[:limit]

    async def send_message(self, entity, message: str, comment_to: int | None = None):
        if entity in self.failing_send_entities:
            raise ValueError(f"entity {entity} does not allow comments")
        sent_message = FakeSentMessage(len(self.sent_messages) + 1000)
        self.sent_messages.append(
            {
                "entity": entity,
                "message": message,
                "comment_to": comment_to,
                "sent_message_id": sent_message.id,
            }
        )
        return sent_message


class FakeAiCommentJobsRepo:
    def __init__(self):
        self.calls = []
        self.history_records = {}

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

    def get_history_record(self, *, job_id: str, channel_id: str, message_id: int):
        return self.history_records.get((job_id, channel_id, int(message_id)))

    def upsert_history_record(
        self,
        *,
        job_id: str,
        channel_id: str,
        message_id: int,
        status: str,
        error: str | None = None,
        comment_message_id: int | None = None,
    ):
        record = {
            "job_id": job_id,
            "channel_id": channel_id,
            "message_id": int(message_id),
            "status": status,
            "error": error,
            "comment_message_id": comment_message_id,
        }
        self.history_records[(job_id, channel_id, int(message_id))] = record
        return record

    def seed_history_record(self, *, job_id: str, channel_id: str, message_id: int, status: str):
        self.upsert_history_record(
            job_id=job_id,
            channel_id=channel_id,
            message_id=message_id,
            status=status,
        )


class TestMultiSessionManager(MultiSessionManager):
    def __init__(self, clients_by_session):
        super().__init__(session_repo=None)
        self.clients_by_session = clients_by_session
        self.generated_comments = {}
        self.generated_calls = []

    async def get_client(self, session_id: str):
        return self.clients_by_session[session_id]

    async def generate_ai_comment_with_fallback(
        self,
        *,
        job_id: str,
        channel_id: str,
        message_id: int,
        system_prompt: str,
        user_prompt: str,
        post_text: str,
        ai_comment_jobs_repo=None,
        fallback_models=None,
    ):
        self.generated_calls.append(
            {
                "job_id": job_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "post_text": post_text,
            }
        )
        generated = self.generated_comments.get(message_id)
        if generated is None:
            return None
        return generated


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

    async def test_process_posts_posts_comments_round_robin_and_updates_checkpoint(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_three": [
                    FakeMessage(405, datetime(2026, 3, 5, 14, 5, tzinfo=timezone.utc), "post one"),
                    FakeMessage(404, datetime(2026, 3, 5, 14, 3, tzinfo=timezone.utc), "post two"),
                ]
            }
        )
        session_b_client = FakeClient()
        manager = TestMultiSessionManager(
            {
                "session-a": session_a_client,
                "session-b": session_b_client,
            }
        )
        manager.generated_comments = {
            404: " first comment ",
            405: "second comment",
        }
        job = {
            "id": "job-4",
            "is_active": True,
            "account_sessions": ["session-a", "session-b"],
            "target_channels": ["@channel_three"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T14:00:00+00:00",
        }

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(
            processed_posts,
            [
                {
                    "channel_id": "@channel_three",
                    "message_id": 404,
                    "status": "posted",
                    "session_id": "session-a",
                    "comment_message_id": 1000,
                },
                {
                    "channel_id": "@channel_three",
                    "message_id": 405,
                    "status": "posted",
                    "session_id": "session-b",
                    "comment_message_id": 1000,
                },
            ],
        )
        self.assertEqual(
            manager.generated_calls,
            [
                {
                    "job_id": "job-4",
                    "channel_id": "@channel_three",
                    "message_id": 404,
                    "system_prompt": "system",
                    "user_prompt": "user",
                    "post_text": "post two",
                },
                {
                    "job_id": "job-4",
                    "channel_id": "@channel_three",
                    "message_id": 405,
                    "system_prompt": "system",
                    "user_prompt": "user",
                    "post_text": "post one",
                },
            ],
        )
        self.assertEqual(
            session_a_client.sent_messages,
            [
                {
                    "entity": "@channel_three",
                    "message": "first comment",
                    "comment_to": 404,
                    "sent_message_id": 1000,
                }
            ],
        )
        self.assertEqual(
            session_b_client.sent_messages,
            [
                {
                    "entity": "@channel_three",
                    "message": "second comment",
                    "comment_to": 405,
                    "sent_message_id": 1000,
                }
            ],
        )
        self.assertEqual(
            repo.history_records[("job-4", "@channel_three", 404)],
            {
                "job_id": "job-4",
                "channel_id": "@channel_three",
                "message_id": 404,
                "status": "posted",
                "error": None,
                "comment_message_id": 1000,
            },
        )
        self.assertEqual(
            repo.history_records[("job-4", "@channel_three", 405)],
            {
                "job_id": "job-4",
                "channel_id": "@channel_three",
                "message_id": 405,
                "status": "posted",
                "error": None,
                "comment_message_id": 1000,
            },
        )
        self.assertEqual(
            repo.calls,
            [
                {
                    "job_id": "job-4",
                    "last_checked_at": "2026-03-05T14:05:00+00:00",
                }
            ],
        )
        self.assertEqual(job["last_checked_at"], "2026-03-05T14:05:00+00:00")

    async def test_process_posts_skips_already_processed_messages(self):
        repo = FakeAiCommentJobsRepo()
        repo.seed_history_record(
            job_id="job-5",
            channel_id="@channel_four",
            message_id=505,
            status="posted",
        )
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_four": [
                    FakeMessage(505, datetime(2026, 3, 5, 15, 5, tzinfo=timezone.utc), "already done"),
                ]
            }
        )
        manager = TestMultiSessionManager({"session-a": session_a_client})
        manager.generated_comments = {505: "must not be used"}
        job = {
            "id": "job-5",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_four"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T15:00:00+00:00",
        }

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(
            processed_posts,
            [
                {
                    "channel_id": "@channel_four",
                    "message_id": 505,
                    "status": "skipped",
                }
            ],
        )
        self.assertEqual(manager.generated_calls, [])
        self.assertEqual(session_a_client.sent_messages, [])
        self.assertEqual(
            repo.calls,
            [
                {
                    "job_id": "job-5",
                    "last_checked_at": "2026-03-05T15:05:00+00:00",
                }
            ],
        )

    async def test_process_posts_marks_failed_when_comment_cannot_be_published(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_five": [
                    FakeMessage(605, datetime(2026, 3, 5, 16, 5, tzinfo=timezone.utc), "publish me"),
                ]
            },
            failing_send_entities={"@channel_five"},
        )
        manager = TestMultiSessionManager({"session-a": session_a_client})
        manager.generated_comments = {605: "publish comment"}
        job = {
            "id": "job-6",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_five"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T16:00:00+00:00",
        }

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(len(processed_posts), 1)
        self.assertEqual(processed_posts[0]["status"], "failed")
        self.assertIn("session-a", processed_posts[0]["error"])
        self.assertEqual(
            repo.history_records[("job-6", "@channel_five", 605)]["status"],
            "failed",
        )
        self.assertIn(
            "session-a",
            repo.history_records[("job-6", "@channel_five", 605)]["error"],
        )
        self.assertEqual(
            repo.calls,
            [
                {
                    "job_id": "job-6",
                    "last_checked_at": "2026-03-05T16:05:00+00:00",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
