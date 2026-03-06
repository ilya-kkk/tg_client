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

from telethon.errors import FloodWaitError
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


class ChatWriteForbiddenError(Exception):
    pass


class FakeClient:
    def __init__(
        self,
        messages_by_entity=None,
        failing_entities=None,
        failing_send_entities=None,
        entity_errors=None,
        message_errors=None,
        send_errors=None,
    ):
        self.messages_by_entity = messages_by_entity or {}
        self.failing_entities = set(failing_entities or [])
        self.failing_send_entities = set(failing_send_entities or [])
        self.entity_errors = entity_errors or {}
        self.message_errors = message_errors or {}
        self.send_errors = send_errors or {}
        self.sent_messages = []
        self.send_attempts = []

    async def get_entity(self, entity):
        if entity in self.entity_errors:
            raise self.entity_errors[entity]
        if entity in self.failing_entities:
            raise ValueError(f"entity {entity} is unavailable")
        return entity

    async def get_messages(self, entity, limit: int | None = None, ids: int | None = None):
        if entity in self.message_errors:
            raise self.message_errors[entity]
        messages = self.messages_by_entity.get(entity, [])
        if ids is not None:
            for message in messages:
                if getattr(message, "id", None) == ids:
                    return message
            return None
        return list(messages)[: limit or len(messages)]

    async def send_message(self, entity, message: str, comment_to: int | None = None):
        self.send_attempts.append(
            {
                "entity": entity,
                "message": message,
                "comment_to": comment_to,
            }
        )
        if entity in self.send_errors:
            raise self.send_errors[entity]
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
        self.jobs = {}

    def set_job(self, job: dict):
        normalized_job = dict(job)
        job_id = str(normalized_job.get("id") or "").strip()
        if job_id:
            self.jobs[job_id] = normalized_job
        return normalized_job

    def update_job(self, job_id: str, **changes):
        normalized_job_id = str(job_id or "").strip()
        current_job = dict(self.jobs.get(normalized_job_id) or {"id": normalized_job_id})
        current_job.update(changes)
        self.jobs[normalized_job_id] = current_job
        return current_job

    def get_by_id_for_worker(self, job_id: str):
        job = self.jobs.get(str(job_id or "").strip())
        if job is None:
            return None
        return dict(job)

    def update_last_checked_at(self, job_id: str, last_checked_at: str):
        self.calls.append(
            {
                "job_id": job_id,
                "last_checked_at": last_checked_at,
            }
        )
        if job_id in self.jobs:
            self.jobs[job_id]["last_checked_at"] = last_checked_at
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
        comment_text: str | None = None,
    ):
        record = {
            "job_id": job_id,
            "channel_id": channel_id,
            "message_id": int(message_id),
            "status": status,
            "error": error,
            "comment_message_id": comment_message_id,
            "comment_text": comment_text,
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


class FailingGenerationManager(TestMultiSessionManager):
    def __init__(self, clients_by_session, failing_message_ids=None):
        super().__init__(clients_by_session)
        self.failing_message_ids = set(failing_message_ids or [])

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
        if message_id in self.failing_message_ids:
            raise RuntimeError(f"boom-{message_id}")
        return await super().generate_ai_comment_with_fallback(
            job_id=job_id,
            channel_id=channel_id,
            message_id=message_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            post_text=post_text,
            ai_comment_jobs_repo=ai_comment_jobs_repo,
            fallback_models=fallback_models,
        )


class DeactivatingGenerationManager(TestMultiSessionManager):
    def __init__(self, clients_by_session, repo: FakeAiCommentJobsRepo, deactivate_after_message_id: int):
        super().__init__(clients_by_session)
        self.repo = repo
        self.deactivate_after_message_id = deactivate_after_message_id

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
        generated = await super().generate_ai_comment_with_fallback(
            job_id=job_id,
            channel_id=channel_id,
            message_id=message_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            post_text=post_text,
            ai_comment_jobs_repo=ai_comment_jobs_repo,
            fallback_models=fallback_models,
        )
        if message_id == self.deactivate_after_message_id:
            self.repo.update_job(job_id, is_active=False)
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
        repo.set_job(job)

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
                "comment_text": "first comment",
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
                "comment_text": "second comment",
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
        repo.set_job(job)

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
        repo.set_job(job)

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(len(processed_posts), 1)
        self.assertEqual(processed_posts[0]["status"], "failed")
        self.assertIn("отключены комментарии", processed_posts[0]["error"])
        self.assertEqual(
            repo.history_records[("job-6", "@channel_five", 605)]["status"],
            "failed",
        )
        self.assertIn(
            "отключены комментарии",
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

    async def test_process_posts_uses_next_session_when_first_has_no_rights(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_six": [
                    FakeMessage(706, datetime(2026, 3, 5, 17, 5, tzinfo=timezone.utc), "rights test"),
                ]
            },
            send_errors={"@channel_six": ChatWriteForbiddenError("CHAT_WRITE_FORBIDDEN")},
        )
        session_b_client = FakeClient()
        manager = TestMultiSessionManager(
            {
                "session-a": session_a_client,
                "session-b": session_b_client,
            }
        )
        manager.generated_comments = {706: "publish comment"}
        job = {
            "id": "job-7",
            "is_active": True,
            "account_sessions": ["session-a", "session-b"],
            "target_channels": ["@channel_six"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T17:00:00+00:00",
        }
        repo.set_job(job)

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(len(processed_posts), 1)
        self.assertEqual(processed_posts[0]["status"], "posted")
        self.assertEqual(processed_posts[0]["session_id"], "session-b")
        self.assertEqual(len(session_a_client.send_attempts), 1)
        self.assertEqual(len(session_b_client.sent_messages), 1)

    async def test_process_posts_skips_paused_session_after_flood_wait(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_seven": [
                    FakeMessage(803, datetime(2026, 3, 5, 18, 7, tzinfo=timezone.utc), "post three"),
                    FakeMessage(802, datetime(2026, 3, 5, 18, 6, tzinfo=timezone.utc), "post two"),
                    FakeMessage(801, datetime(2026, 3, 5, 18, 5, tzinfo=timezone.utc), "post one"),
                ]
            },
            send_errors={"@channel_seven": FloodWaitError(30)},
        )
        session_b_client = FakeClient()
        manager = TestMultiSessionManager(
            {
                "session-a": session_a_client,
                "session-b": session_b_client,
            }
        )
        manager.generated_comments = {
            801: "comment one",
            802: "comment two",
            803: "comment three",
        }
        job = {
            "id": "job-8",
            "is_active": True,
            "account_sessions": ["session-a", "session-b"],
            "target_channels": ["@channel_seven"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T18:00:00+00:00",
        }
        repo.set_job(job)

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(
            [item["status"] for item in processed_posts],
            ["posted", "posted", "posted"],
        )
        self.assertEqual(len(session_a_client.send_attempts), 1)
        self.assertEqual(len(session_b_client.sent_messages), 3)
        self.assertTrue(all(item["session_id"] == "session-b" for item in processed_posts))

    async def test_process_posts_continues_after_unexpected_single_post_error(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_eight": [
                    FakeMessage(902, datetime(2026, 3, 5, 19, 6, tzinfo=timezone.utc), "second post"),
                    FakeMessage(901, datetime(2026, 3, 5, 19, 5, tzinfo=timezone.utc), "first post"),
                ]
            }
        )
        manager = FailingGenerationManager(
            {"session-a": session_a_client},
            failing_message_ids={901},
        )
        manager.generated_comments = {902: "safe comment"}
        job = {
            "id": "job-9",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_eight"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T19:00:00+00:00",
        }
        repo.set_job(job)

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(len(processed_posts), 2)
        self.assertEqual(processed_posts[0]["status"], "failed")
        self.assertIn("boom-901", processed_posts[0]["error"])
        self.assertEqual(processed_posts[1]["status"], "posted")
        self.assertEqual(
            repo.history_records[("job-9", "@channel_eight", 901)]["status"],
            "failed",
        )

    async def test_process_posts_skips_cycle_when_job_was_disabled_before_processing(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_toggle": [
                    FakeMessage(1001, datetime(2026, 3, 5, 20, 5, tzinfo=timezone.utc), "first post"),
                ]
            }
        )
        manager = TestMultiSessionManager({"session-a": session_a_client})
        manager.generated_comments = {1001: "must not be used"}
        job = {
            "id": "job-10",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_toggle"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T20:00:00+00:00",
        }
        repo.set_job({**job, "is_active": False})

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(processed_posts, [])
        self.assertEqual(manager.generated_calls, [])
        self.assertEqual(session_a_client.sent_messages, [])
        self.assertEqual(repo.calls, [])
        self.assertEqual(job["last_checked_at"], "2026-03-05T20:00:00+00:00")

    async def test_process_posts_stops_after_current_post_when_job_is_disabled_mid_cycle(self):
        repo = FakeAiCommentJobsRepo()
        session_a_client = FakeClient(
            messages_by_entity={
                "@channel_toggle_mid_cycle": [
                    FakeMessage(1102, datetime(2026, 3, 5, 21, 6, tzinfo=timezone.utc), "second post"),
                    FakeMessage(1101, datetime(2026, 3, 5, 21, 5, tzinfo=timezone.utc), "first post"),
                ]
            }
        )
        manager = DeactivatingGenerationManager(
            {"session-a": session_a_client},
            repo=repo,
            deactivate_after_message_id=1101,
        )
        manager.generated_comments = {
            1101: "first comment",
            1102: "second comment",
        }
        job = {
            "id": "job-11",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_channels": ["@channel_toggle_mid_cycle"],
            "system_prompt": "system",
            "user_prompt": "user",
            "last_checked_at": "2026-03-05T21:00:00+00:00",
        }
        repo.set_job(job)

        processed_posts = await manager.process_ai_comment_jobs(
            job,
            ai_comment_jobs_repo=repo,
        )

        self.assertEqual(
            processed_posts,
            [
                {
                    "channel_id": "@channel_toggle_mid_cycle",
                    "message_id": 1101,
                    "status": "posted",
                    "session_id": "session-a",
                    "comment_message_id": 1000,
                }
            ],
        )
        self.assertEqual(
            manager.generated_calls,
            [
                {
                    "job_id": "job-11",
                    "channel_id": "@channel_toggle_mid_cycle",
                    "message_id": 1101,
                    "system_prompt": "system",
                    "user_prompt": "user",
                    "post_text": "first post",
                }
            ],
        )
        self.assertEqual(
            session_a_client.sent_messages,
            [
                {
                    "entity": "@channel_toggle_mid_cycle",
                    "message": "first comment",
                    "comment_to": 1101,
                    "sent_message_id": 1000,
                }
            ],
        )
        self.assertEqual(repo.calls, [])
        self.assertEqual(job["last_checked_at"], "2026-03-05T21:00:00+00:00")

    async def test_get_message_by_id_for_sessions_falls_back_to_next_session(self):
        session_a_client = FakeClient(
            entity_errors={"@channel_preview": ValueError("entity unavailable")},
        )
        session_b_client = FakeClient(
            messages_by_entity={
                "@channel_preview": [
                    FakeMessage(1201, datetime(2026, 3, 5, 22, 5, tzinfo=timezone.utc), "preview post"),
                ]
            }
        )
        manager = TestMultiSessionManager(
            {
                "session-a": session_a_client,
                "session-b": session_b_client,
            }
        )

        result = await manager.get_message_by_id_for_sessions(
            ["session-a", "session-b"],
            "@channel_preview",
            1201,
        )

        self.assertEqual(result["session_id"], "session-b")
        self.assertEqual(result["channel_id"], "@channel_preview")
        self.assertEqual(result["post"]["id"], 1201)
        self.assertEqual(result["post"]["text"], "preview post")

    def test_normalize_ai_comment_text_cleans_wrappers_and_truncates(self):
        cleaned = MultiSessionManager._normalize_ai_comment_text(
            "```text\nКомментарий:   hello   world  \n\nsecond line\n```"
        )
        truncated = MultiSessionManager._normalize_ai_comment_text("x" * 1100, limit=1000)

        self.assertEqual(cleaned, "hello world\nsecond line")
        self.assertEqual(len(truncated), 1000)


if __name__ == "__main__":
    unittest.main()
