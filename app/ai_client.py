import logging
from typing import Any, Sequence

import httpx

from app.config import OPENROUTER_API_KEY, OPENROUTER_MODELS

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODELS: list[str] = list(OPENROUTER_MODELS)


class OpenRouterClient:
    """Клиент OpenRouter с последовательной попыткой по списку моделей/роутеров."""

    def __init__(
        self,
        api_key: str | None = None,
        models: Sequence[str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = (api_key if api_key is not None else OPENROUTER_API_KEY).strip()
        self.models = self._normalize_models(models or DEFAULT_OPENROUTER_MODELS)
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize_models(models: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        for model in models:
            model_name = str(model).strip()
            if model_name:
                normalized.append(model_name)
        return normalized

    @staticmethod
    def _truncate_for_log(text: str, limit: int = 300) -> str:
        value = (text or "").strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    @staticmethod
    def _extract_content(response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return ""

        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text_part = item.get("text")
                    if isinstance(text_part, str):
                        parts.append(text_part)
            return "\n".join(part.strip() for part in parts if part and part.strip()).strip()

        return ""

    @staticmethod
    def _clean_comment_text(text: str) -> str:
        return (text or "").strip().strip('"').strip()

    async def generate_comment_with_fallback(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        post_text: str,
        models: Sequence[str] | None = None,
        max_tokens: int = 300,
        temperature: float = 0.7,
    ) -> str | None:
        """Генерирует комментарий, перебирая модели до первого валидного ответа."""
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY не задан, генерация комментария невозможна")
            return None

        selected_models = self._normalize_models(models or self.models)
        if not selected_models:
            logger.error("Список моделей OpenRouter пуст, генерация комментария невозможна")
            return None

        normalized_system_prompt = (system_prompt or "").strip()
        normalized_user_prompt = (user_prompt or "").strip()
        normalized_post_text = (post_text or "").strip()

        user_content_parts = []
        if normalized_user_prompt:
            user_content_parts.append(normalized_user_prompt)
        if normalized_post_text:
            user_content_parts.append(f"Текст поста:\n{normalized_post_text}")
        user_content = "\n\n".join(user_content_parts).strip()

        if not user_content:
            logger.warning("Пустой контент запроса к OpenRouter: user_prompt и post_text не заполнены")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for model in selected_models:
                messages: list[dict[str, str]] = []
                if normalized_system_prompt:
                    messages.append({"role": "system", "content": normalized_system_prompt})
                messages.append({"role": "user", "content": user_content})

                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }

                try:
                    response = await client.post(
                        OPENROUTER_CHAT_COMPLETIONS_URL,
                        headers=headers,
                        json=payload,
                    )
                except httpx.TimeoutException:
                    logger.warning("Таймаут OpenRouter для модели '%s', пробуем следующую", model)
                    continue
                except httpx.HTTPError as e:
                    logger.warning("HTTP ошибка OpenRouter для модели '%s': %s", model, e)
                    continue
                except Exception as e:
                    logger.warning("Неожиданная ошибка OpenRouter для модели '%s': %s", model, e)
                    continue

                if response.status_code >= 400:
                    if response.status_code == 404 and "No endpoints found" in response.text:
                        logger.warning(
                            "Модель/роутер OpenRouter '%s' недоступна. Проверьте OPENROUTER_MODELS или используйте 'openrouter/free'",
                            model,
                        )
                    logger.warning(
                        "OpenRouter вернул ошибку для модели '%s': status=%s body=%s",
                        model,
                        response.status_code,
                        self._truncate_for_log(response.text),
                    )
                    continue

                try:
                    body = response.json()
                except ValueError:
                    logger.warning(
                        "Некорректный JSON от OpenRouter для модели '%s': body=%s",
                        model,
                        self._truncate_for_log(response.text),
                    )
                    continue

                generated = self._clean_comment_text(self._extract_content(body))
                if not generated:
                    logger.warning(
                        "Пустой ответ от OpenRouter для модели '%s', пробуем следующую",
                        model,
                    )
                    continue

                logger.info("Комментарий успешно сгенерирован через OpenRouter модель '%s'", model)
                return generated

        logger.error("Все fallback-модели OpenRouter вернули ошибку или пустой ответ")
        return None
