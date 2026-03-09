import sys
import types
import unittest
from datetime import datetime, timezone


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

from app.telegram_client import AiReplyDecision, MultiSessionManager


class FakeOpenRouterClient:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def generate_structured_output_with_fallback(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeMessage:
    def __init__(
        self,
        message_id: int,
        date: datetime,
        text: str = "",
        *,
        sender_id: int | None = None,
        out: bool = False,
        action=None,
    ):
        self.id = message_id
        self.date = date
        self.message = text
        self.text = text
        self.raw_text = text
        self.sender_id = sender_id
        self.out = out
        self.action = action


class FakeSentMessage:
    def __init__(self, message_id: int):
        self.id = message_id


class FakeMe:
    def __init__(self, user_id: int):
        self.id = user_id


class FakeClient:
    def __init__(self, *, user_id: int, messages_by_entity=None, entity_errors=None, send_errors=None):
        self.user_id = user_id
        self.messages_by_entity = messages_by_entity or {}
        self.entity_errors = entity_errors or {}
        self.send_errors = send_errors or {}
        self.sent_messages = []

    async def get_me(self):
        return FakeMe(self.user_id)

    async def get_entity(self, entity):
        if entity in self.entity_errors:
            raise self.entity_errors[entity]
        return entity

    async def get_messages(self, entity, limit: int | None = None, ids: int | None = None):
        messages = self.messages_by_entity.get(entity, [])
        if ids is not None:
            for message in messages:
                if getattr(message, "id", None) == ids:
                    return message
            return None
        return list(messages)[: limit or len(messages)]

    async def send_message(self, entity, message: str, reply_to: int | None = None):
        if entity in self.send_errors:
            raise self.send_errors[entity]
        sent_message = FakeSentMessage(len(self.sent_messages) + 5000)
        self.sent_messages.append(
            {
                "entity": entity,
                "message": message,
                "reply_to": reply_to,
                "sent_message_id": sent_message.id,
            }
        )
        return sent_message


class FakeAiReplyJobsRepo:
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

    def get_history_record(self, *, job_id: str, chat_id: str, message_id: int):
        return self.history_records.get((job_id, chat_id, int(message_id)))

    def upsert_history_record(
        self,
        *,
        job_id: str,
        chat_id: str,
        message_id: int,
        status: str,
        chat_name: str | None = None,
        sender_id: int | None = None,
        message_text: str | None = None,
        message_date: str | None = None,
        matched_trigger: str | None = None,
        reply_message_id: int | None = None,
        reply_text: str | None = None,
        processed_session_id: str | None = None,
        error: str | None = None,
    ):
        record = {
            "job_id": job_id,
            "chat_id": chat_id,
            "chat_name": chat_name,
            "message_id": int(message_id),
            "sender_id": sender_id,
            "message_text": message_text,
            "message_date": message_date,
            "matched_trigger": matched_trigger,
            "reply_message_id": reply_message_id,
            "reply_text": reply_text,
            "processed_session_id": processed_session_id,
            "status": status,
            "error": error,
        }
        self.history_records[(job_id, chat_id, int(message_id))] = record
        return record


class TestMultiSessionManager(MultiSessionManager):
    def __init__(self, clients_by_session):
        super().__init__(session_repo=None)
        self.clients_by_session = clients_by_session
        self.generated_decisions = {}
        self.generated_calls = []

    async def get_client(self, session_id: str):
        return self.clients_by_session[session_id]

    async def generate_ai_reply_decision_with_fallback(
        self,
        *,
        job_id: str,
        chat_id: str,
        message_id: int,
        triggers,
        reply_prompt: str,
        message_text: str,
        fallback_models=None,
    ):
        self.generated_calls.append(
            {
                "job_id": job_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "triggers": list(triggers),
                "reply_prompt": reply_prompt,
                "message_text": message_text,
            }
        )
        return self.generated_decisions.get(message_id)


class AiReplySchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_ai_reply_decision_infers_should_reply_when_field_is_missing(self):
        openrouter_client = FakeOpenRouterClient(
            AiReplyDecision(
                should_reply=None,
                matched_trigger="Сколько стоит?",
                reply_text="Цена 1000 руб.",
            )
        )
        manager = MultiSessionManager(openrouter_client=openrouter_client)

        decision = await manager.generate_ai_reply_decision_with_fallback(
            job_id="job-infer",
            chat_id="@chat_infer",
            message_id=501,
            triggers=["Сколько стоит?"],
            reply_prompt="Отвечай коротко.",
            message_text="Сколько стоит?",
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.matched_trigger, "Сколько стоит?")
        self.assertEqual(decision.reply_text, "Цена 1000 руб.")

    async def test_initial_poll_sets_checkpoint_and_skips_existing_messages(self):
        repo = FakeAiReplyJobsRepo()
        manager = TestMultiSessionManager(
            {
                "session-a": FakeClient(
                    user_id=100,
                    messages_by_entity={
                        "@chat_one": [
                            FakeMessage(
                                101,
                                datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
                                "Сколько стоит?",
                                sender_id=200,
                            )
                        ]
                    },
                )
            }
        )
        job = {
            "id": "job-1",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_chats": ["@chat_one"],
            "triggers": ["Сколько стоит?"],
            "reply_prompt": "Отвечай коротко.",
            "last_checked_at": None,
        }
        repo.set_job(job)

        before_poll = datetime.now(timezone.utc)
        fresh_messages = await manager.poll_ai_reply_job_chats(job, ai_reply_jobs_repo=repo)
        after_poll = datetime.now(timezone.utc)

        self.assertEqual(fresh_messages, [])
        self.assertEqual(len(repo.calls), 1)
        stored_checkpoint = datetime.fromisoformat(repo.calls[0]["last_checked_at"])
        self.assertEqual(repo.calls[0]["job_id"], "job-1")
        self.assertGreaterEqual(stored_checkpoint, before_poll)
        self.assertLessEqual(stored_checkpoint, after_poll)
        self.assertEqual(job["last_checked_at"], repo.calls[0]["last_checked_at"])

    async def test_process_messages_replies_and_skips_non_matching(self):
        repo = FakeAiReplyJobsRepo()
        session_client = FakeClient(
            user_id=100,
            messages_by_entity={
                "@chat_two": [
                    FakeMessage(
                        702,
                        datetime(2026, 3, 6, 12, 2, tzinfo=timezone.utc),
                        "Привет",
                        sender_id=301,
                    ),
                    FakeMessage(
                        701,
                        datetime(2026, 3, 6, 12, 1, tzinfo=timezone.utc),
                        "Сколько стоит?",
                        sender_id=300,
                    ),
                ]
            },
        )
        manager = TestMultiSessionManager({"session-a": session_client})
        manager.generated_decisions[701] = AiReplyDecision(
            should_reply=True,
            matched_trigger="Сколько стоит?",
            reply_text="Цена 1000 руб.",
        )
        manager.generated_decisions[702] = AiReplyDecision(
            should_reply=False,
            matched_trigger=None,
            reply_text=None,
        )
        job = {
            "id": "job-2",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_chats": ["@chat_two"],
            "triggers": ["Сколько стоит?"],
            "reply_prompt": "Отвечай коротко.",
            "last_checked_at": "2026-03-06T12:00:00+00:00",
        }
        repo.set_job(job)

        processed = await manager.process_ai_reply_jobs(job, ai_reply_jobs_repo=repo)

        self.assertEqual(
            [(item["message_id"], item["status"]) for item in processed],
            [(701, "replied"), (702, "skipped")],
        )
        self.assertEqual(len(session_client.sent_messages), 1)
        self.assertEqual(session_client.sent_messages[0]["reply_to"], 701)
        self.assertEqual(session_client.sent_messages[0]["message"], "Цена 1000 руб.")

        replied_record = repo.history_records[("job-2", "@chat_two", 701)]
        self.assertEqual(replied_record["status"], "replied")
        self.assertEqual(replied_record["matched_trigger"], "Сколько стоит?")
        self.assertEqual(replied_record["reply_text"], "Цена 1000 руб.")
        self.assertEqual(replied_record["processed_session_id"], "session-a")

        skipped_record = repo.history_records[("job-2", "@chat_two", 702)]
        self.assertEqual(skipped_record["status"], "skipped")
        self.assertIsNone(skipped_record["reply_text"])

        self.assertEqual(
            repo.calls,
            [
                {
                    "job_id": "job-2",
                    "last_checked_at": "2026-03-06T12:02:00+00:00",
                }
            ],
        )

    async def test_messages_from_managed_accounts_are_ignored(self):
        repo = FakeAiReplyJobsRepo()
        session_client = FakeClient(
            user_id=100,
            messages_by_entity={
                "@chat_three": [
                    FakeMessage(
                        803,
                        datetime(2026, 3, 6, 13, 3, tzinfo=timezone.utc),
                        "Сколько стоит?",
                        sender_id=100,
                    ),
                    FakeMessage(
                        802,
                        datetime(2026, 3, 6, 13, 2, tzinfo=timezone.utc),
                        "Сколько стоит?",
                        sender_id=333,
                    ),
                ]
            },
        )
        manager = TestMultiSessionManager({"session-a": session_client})
        manager.generated_decisions[802] = AiReplyDecision(
            should_reply=True,
            matched_trigger="Сколько стоит?",
            reply_text="Цена 2000 руб.",
        )
        job = {
            "id": "job-3",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_chats": ["@chat_three"],
            "triggers": ["Сколько стоит?"],
            "reply_prompt": "Отвечай коротко.",
            "last_checked_at": "2026-03-06T13:00:00+00:00",
        }
        repo.set_job(job)

        processed = await manager.process_ai_reply_jobs(job, ai_reply_jobs_repo=repo)

        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0]["message_id"], 802)
        self.assertEqual(len(manager.generated_calls), 1)
        self.assertEqual(manager.generated_calls[0]["message_id"], 802)
        self.assertNotIn(("job-3", "@chat_three", 803), repo.history_records)

    async def test_process_ai_reply_jobs_keeps_checkpoint_for_pending_retry(self):
        repo = FakeAiReplyJobsRepo()
        session_client = FakeClient(
            user_id=100,
            messages_by_entity={
                "@chat_retry": [
                    FakeMessage(
                        901,
                        datetime(2026, 3, 6, 14, 1, tzinfo=timezone.utc),
                        "Сколько стоит?",
                        sender_id=444,
                    )
                ]
            },
        )
        manager = TestMultiSessionManager({"session-a": session_client})
        job = {
            "id": "job-retry",
            "is_active": True,
            "account_sessions": ["session-a"],
            "target_chats": ["@chat_retry"],
            "triggers": ["Сколько стоит?"],
            "reply_prompt": "Отвечай коротко.",
            "last_checked_at": "2026-03-06T14:00:00+00:00",
        }
        repo.set_job(job)

        processed = await manager.process_ai_reply_jobs(job, ai_reply_jobs_repo=repo)

        self.assertEqual(
            processed,
            [
                {
                    "chat_id": "@chat_retry",
                    "message_id": 901,
                    "status": "pending_retry",
                    "error": "Не удалось получить structured output для решения по входящему сообщению",
                }
            ],
        )
        self.assertEqual(repo.calls, [])
        self.assertEqual(job["last_checked_at"], "2026-03-06T14:00:00+00:00")
        pending_record = repo.history_records[("job-retry", "@chat_retry", 901)]
        self.assertEqual(pending_record["status"], "pending_retry")
        self.assertEqual(
            pending_record["error"],
            "Не удалось получить structured output для решения по входящему сообщению",
        )


if __name__ == "__main__":
    unittest.main()
