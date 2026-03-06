import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
