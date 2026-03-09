import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch
from pydantic import BaseModel


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

        class TimeoutException(Exception):
            pass

        class HTTPError(Exception):
            pass

        httpx_module.AsyncClient = AsyncClient
        httpx_module.TimeoutException = TimeoutException
        httpx_module.HTTPError = HTTPError
        sys.modules["httpx"] = httpx_module


_install_dependency_stubs()


def _reload_openrouter_modules():
    config_module = importlib.import_module("app.config")
    ai_client_module = importlib.import_module("app.ai_client")
    config_module = importlib.reload(config_module)
    ai_client_module = importlib.reload(ai_client_module)
    return config_module, ai_client_module


class FakeResponse:
    def __init__(self, status_code: int, *, text: str = "", json_body: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body

    def json(self):
        if self._json_body is None:
            raise ValueError("No JSON body configured")
        return self._json_body


class FakeAsyncClient:
    queued_responses: list[FakeResponse] = []
    requests: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, headers: dict, json: dict):
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
            }
        )
        if not self.queued_responses:
            raise AssertionError("No fake OpenRouter response configured")
        return self.queued_responses.pop(0)


class OpenRouterClientTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        FakeAsyncClient.queued_responses = []
        FakeAsyncClient.requests = []

    def test_default_models_use_openrouter_free_router(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_MODELS", None)
            config_module, ai_client_module = _reload_openrouter_modules()

        self.assertEqual(config_module.OPENROUTER_MODELS, ["openrouter/free"])
        self.assertEqual(ai_client_module.DEFAULT_OPENROUTER_MODELS, ["openrouter/free"])

    def test_openrouter_models_env_is_parsed_as_csv(self):
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "model-a, openrouter/free , , model-b"},
            clear=False,
        ):
            config_module, ai_client_module = _reload_openrouter_modules()

        self.assertEqual(config_module.OPENROUTER_MODELS, ["model-a", "openrouter/free", "model-b"])
        self.assertEqual(ai_client_module.DEFAULT_OPENROUTER_MODELS, ["model-a", "openrouter/free", "model-b"])

    async def test_generate_comment_falls_back_to_next_model_after_404(self):
        _, ai_client_module = _reload_openrouter_modules()
        FakeAsyncClient.queued_responses = [
            FakeResponse(
                404,
                text='{"error":{"message":"No endpoints found for stale-model.","code":404}}',
            ),
            FakeResponse(
                200,
                json_body={
                    "choices": [
                        {
                            "message": {
                                "content": "Готовый комментарий",
                            }
                        }
                    ]
                },
            ),
        ]

        with patch.object(ai_client_module.httpx, "AsyncClient", FakeAsyncClient):
            client = ai_client_module.OpenRouterClient(
                api_key="test-key",
                models=["stale-model", "openrouter/free"],
            )
            result = await client.generate_comment_with_fallback(
                system_prompt="system",
                user_prompt="user",
                post_text="post",
            )

        self.assertEqual(result, "Готовый комментарий")
        self.assertEqual(
            [request["json"]["model"] for request in FakeAsyncClient.requests],
            ["stale-model", "openrouter/free"],
        )
        self.assertTrue(
            all(
                request["json"].get("reasoning") == {"effort": "none", "exclude": True}
                for request in FakeAsyncClient.requests
            )
        )

    async def test_generate_comment_retries_same_model_after_empty_200_response(self):
        _, ai_client_module = _reload_openrouter_modules()
        FakeAsyncClient.queued_responses = [
            FakeResponse(
                200,
                json_body={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "refusal": None,
                                "reasoning": None,
                            },
                        }
                    ]
                },
                text='{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"","refusal":null,"reasoning":null}}]}',
            ),
            FakeResponse(
                200,
                json_body={
                    "choices": [
                        {
                            "message": {
                                "content": "Вторая попытка успешна",
                            }
                        }
                    ]
                },
            ),
        ]

        with patch.object(ai_client_module.httpx, "AsyncClient", FakeAsyncClient):
            client = ai_client_module.OpenRouterClient(
                api_key="test-key",
                models=["openrouter/free"],
                retries_per_model=2,
            )
            result = await client.generate_comment_with_fallback(
                system_prompt="system",
                user_prompt="user",
                post_text="post",
            )

        self.assertEqual(result, "Вторая попытка успешна")
        self.assertEqual(
            [request["json"]["model"] for request in FakeAsyncClient.requests],
            ["openrouter/free", "openrouter/free"],
        )

    def test_extract_content_supports_completion_text_field(self):
        _, ai_client_module = _reload_openrouter_modules()
        extracted = ai_client_module.OpenRouterClient._extract_content(
            {
                "choices": [
                    {
                        "text": "Текст из completion API",
                    }
                ]
            }
        )

        self.assertEqual(extracted, "Текст из completion API")

    def test_build_payload_disables_reasoning_for_comment_generation(self):
        _, ai_client_module = _reload_openrouter_modules()

        payload = ai_client_module.OpenRouterClient._build_payload(
            model="openrouter/free",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=300,
            temperature=0.7,
            reasoning={"effort": "none", "exclude": True},
        )

        self.assertEqual(payload["reasoning"], {"effort": "none", "exclude": True})

    def test_build_payload_can_omit_reasoning(self):
        _, ai_client_module = _reload_openrouter_modules()

        payload = ai_client_module.OpenRouterClient._build_payload(
            model="openrouter/free",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=300,
            temperature=0.7,
            reasoning=None,
        )

        self.assertNotIn("reasoning", payload)

    async def test_generate_comment_retries_with_reasoning_enabled_when_provider_requires_it(self):
        _, ai_client_module = _reload_openrouter_modules()
        FakeAsyncClient.queued_responses = [
            FakeResponse(
                400,
                text='{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled.","code":400}}',
            ),
            FakeResponse(
                200,
                json_body={
                    "choices": [
                        {
                            "message": {
                                "content": "Ответ после включения reasoning",
                            }
                        }
                    ]
                },
            ),
        ]

        with patch.object(ai_client_module.httpx, "AsyncClient", FakeAsyncClient):
            client = ai_client_module.OpenRouterClient(
                api_key="test-key",
                models=["openrouter/free"],
                retries_per_model=2,
            )
            result = await client.generate_comment_with_fallback(
                system_prompt="system",
                user_prompt="user",
                post_text="post",
            )

        self.assertEqual(result, "Ответ после включения reasoning")
        self.assertEqual(len(FakeAsyncClient.requests), 2)
        self.assertEqual(
            FakeAsyncClient.requests[0]["json"]["reasoning"],
            {"effort": "none", "exclude": True},
        )
        self.assertEqual(
            FakeAsyncClient.requests[1]["json"]["reasoning"],
            {"enabled": True, "exclude": True},
        )

    async def test_generate_structured_output_returns_validated_model(self):
        _, ai_client_module = _reload_openrouter_modules()

        class ReplyDecision(BaseModel):
            should_reply: bool
            matched_trigger: str | None
            reply_text: str | None

        FakeAsyncClient.queued_responses = [
            FakeResponse(
                200,
                json_body={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"should_reply":true,'
                                    '"matched_trigger":"Сколько стоит?",'
                                    '"reply_text":"Цена 1000 руб."}'
                                )
                            }
                        }
                    ]
                },
            )
        ]

        with patch.object(ai_client_module.httpx, "AsyncClient", FakeAsyncClient):
            client = ai_client_module.OpenRouterClient(
                api_key="test-key",
                structured_models=["openrouter/free"],
            )
            result = await client.generate_structured_output_with_fallback(
                schema_model=ReplyDecision,
                schema_name="reply_decision",
                system_prompt="system",
                user_prompt="user",
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.should_reply)
        self.assertEqual(result.matched_trigger, "Сколько стоит?")
        self.assertEqual(result.reply_text, "Цена 1000 руб.")
        self.assertEqual(FakeAsyncClient.requests[0]["json"]["response_format"]["type"], "json_schema")
        self.assertEqual(
            FakeAsyncClient.requests[0]["json"]["provider"],
            {"require_parameters": True},
        )
        self.assertEqual(
            FakeAsyncClient.requests[0]["json"]["plugins"],
            [{"id": "response-healing"}],
        )
        self.assertEqual(
            FakeAsyncClient.requests[0]["json"]["reasoning"],
            {"enabled": True, "exclude": True},
        )

    async def test_generate_structured_output_retries_same_model_after_429(self):
        _, ai_client_module = _reload_openrouter_modules()

        class ReplyDecision(BaseModel):
            should_reply: bool
            matched_trigger: str | None
            reply_text: str | None

        FakeAsyncClient.queued_responses = [
            FakeResponse(
                429,
                text='{"error":{"message":"Provider returned error","code":429}}',
            ),
            FakeResponse(
                200,
                json_body={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"should_reply":true,'
                                    '"matched_trigger":"цена",'
                                    '"reply_text":"1000 руб."}'
                                )
                            }
                        }
                    ]
                },
            ),
        ]

        with patch.object(ai_client_module.httpx, "AsyncClient", FakeAsyncClient):
            client = ai_client_module.OpenRouterClient(
                api_key="test-key",
                structured_models=["openrouter/free"],
                retries_per_model=2,
            )
            result = await client.generate_structured_output_with_fallback(
                schema_model=ReplyDecision,
                schema_name="reply_decision",
                system_prompt="system",
                user_prompt="user",
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.should_reply)
        self.assertEqual(result.reply_text, "1000 руб.")
        self.assertEqual(
            [request["json"]["model"] for request in FakeAsyncClient.requests],
            ["openrouter/free", "openrouter/free"],
        )


if __name__ == "__main__":
    unittest.main()
