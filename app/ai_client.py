import logging
from typing import Any, Sequence, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODELS,
    OPENROUTER_RETRIES_PER_MODEL,
    OPENROUTER_STRUCTURED_MODELS,
)

logger = logging.getLogger(__name__)
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODELS: list[str] = list(OPENROUTER_MODELS)
DEFAULT_OPENROUTER_STRUCTURED_MODELS: list[str] = list(OPENROUTER_STRUCTURED_MODELS)
OPENROUTER_NO_REASONING_PAYLOAD = {
    "effort": "none",
    "exclude": True,
}
OPENROUTER_HIDDEN_REASONING_PAYLOAD = {
    "enabled": True,
    "exclude": True,
}
OPENROUTER_RESPONSE_HEALING_PLUGIN = {
    "id": "response-healing",
}
OPENROUTER_PROVIDER_REQUIRE_PARAMETERS = {
    "require_parameters": True,
}


class OpenRouterClient:
    """Клиент OpenRouter с последовательной попыткой по списку моделей/роутеров."""

    def __init__(
        self,
        api_key: str | None = None,
        models: Sequence[str] | None = None,
        structured_models: Sequence[str] | None = None,
        timeout_seconds: float = 30.0,
        retries_per_model: int = OPENROUTER_RETRIES_PER_MODEL,
    ) -> None:
        self.api_key = (api_key if api_key is not None else OPENROUTER_API_KEY).strip()
        self.models = self._normalize_models(models or DEFAULT_OPENROUTER_MODELS)
        self.structured_models = self._normalize_models(
            structured_models or DEFAULT_OPENROUTER_STRUCTURED_MODELS or self.models
        )
        self.timeout_seconds = timeout_seconds
        self.retries_per_model = max(1, int(retries_per_model))

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

        text = first_choice.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return ""

        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, dict):
            text_part = content.get("text")
            if isinstance(text_part, str):
                return text_part.strip()

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

    @classmethod
    def _extract_empty_response_details(cls, response_json: dict[str, Any], raw_text: str) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            return f"choices missing; body={cls._truncate_for_log(raw_text)}"

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return f"first choice is not an object; body={cls._truncate_for_log(raw_text)}"

        message = first_choice.get("message")
        refusal = None
        reasoning = None
        finish_reason = first_choice.get("finish_reason")
        if isinstance(message, dict):
            refusal = message.get("refusal")
            reasoning = message.get("reasoning")

        detail_parts: list[str] = []
        if finish_reason:
            detail_parts.append(f"finish_reason={finish_reason}")
        if isinstance(refusal, str) and refusal.strip():
            detail_parts.append(f"refusal={cls._truncate_for_log(refusal.strip())}")
        if isinstance(reasoning, str) and reasoning.strip():
            detail_parts.append(f"reasoning={cls._truncate_for_log(reasoning.strip())}")
        detail_parts.append(f"body={cls._truncate_for_log(raw_text)}")
        return "; ".join(detail_parts)

    @staticmethod
    def _clean_comment_text(text: str) -> str:
        return (text or "").strip().strip('"').strip()

    @staticmethod
    def _build_payload(
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        response_format: dict[str, Any] | None = None,
        plugins: list[dict[str, Any]] | None = None,
        provider: dict[str, Any] | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if plugins:
            payload["plugins"] = plugins
        if provider:
            payload["provider"] = provider
        if reasoning is not None:
            payload["reasoning"] = reasoning
        return payload

    @staticmethod
    def _should_retry_status_code(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code <= 599

    @staticmethod
    def _response_requires_reasoning(response_text: str) -> bool:
        normalized = str(response_text or "").lower()
        return "reasoning is mandatory" in normalized or "cannot be disabled" in normalized

    @staticmethod
    def _build_json_schema_response_format(
        *,
        schema_model: type[BaseModel],
        schema_name: str,
    ) -> dict[str, Any]:
        if hasattr(schema_model, "model_json_schema"):
            schema = schema_model.model_json_schema()
        else:
            schema = schema_model.schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }

    @staticmethod
    def _extract_structured_content_payload(response_json: dict[str, Any]) -> Any:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            return None

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return None

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return None

        return message.get("content")

    @classmethod
    def _parse_structured_output(
        cls,
        *,
        schema_model: type[StructuredOutputT],
        content: Any,
        response_json: dict[str, Any],
    ) -> StructuredOutputT:
        if isinstance(content, str):
            stripped = content.strip()
            if not stripped:
                raise ValueError("Structured output content is empty")
            if hasattr(schema_model, "model_validate_json"):
                return schema_model.model_validate_json(stripped)
            return schema_model.parse_raw(stripped)
        if isinstance(content, dict):
            if hasattr(schema_model, "model_validate"):
                return schema_model.model_validate(content)
            return schema_model.parse_obj(content)
        if isinstance(content, list):
            extracted = cls._extract_content(response_json)
            if not extracted:
                raise ValueError("Structured output content list does not contain text")
            if hasattr(schema_model, "model_validate_json"):
                return schema_model.model_validate_json(extracted)
            return schema_model.parse_raw(extracted)

        extracted = cls._extract_content(response_json)
        if not extracted:
            raise ValueError("Structured output content is missing")
        if hasattr(schema_model, "model_validate_json"):
            return schema_model.model_validate_json(extracted)
        return schema_model.parse_raw(extracted)

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
                current_reasoning = dict(OPENROUTER_NO_REASONING_PAYLOAD)
                for attempt in range(1, self.retries_per_model + 1):
                    messages: list[dict[str, str]] = []
                    if normalized_system_prompt:
                        messages.append({"role": "system", "content": normalized_system_prompt})
                    messages.append({"role": "user", "content": user_content})

                    payload = self._build_payload(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        # For short public comments we do not want hidden reasoning to consume the
                        # completion budget and produce `content=null` on free routed models.
                        reasoning=dict(current_reasoning),
                    )

                    is_last_attempt = attempt >= self.retries_per_model

                    try:
                        response = await client.post(
                            OPENROUTER_CHAT_COMPLETIONS_URL,
                            headers=headers,
                            json=payload,
                        )
                    except httpx.TimeoutException:
                        logger.warning(
                            "Таймаут OpenRouter для модели '%s' (attempt %s/%s)%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue
                    except httpx.HTTPError as e:
                        logger.warning(
                            "HTTP ошибка OpenRouter для модели '%s' (attempt %s/%s): %s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            e,
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue
                    except Exception as e:
                        logger.warning(
                            "Неожиданная ошибка OpenRouter для модели '%s' (attempt %s/%s): %s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            e,
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue

                    if response.status_code >= 400:
                        if response.status_code == 404 and "No endpoints found" in response.text:
                            logger.warning(
                                "Модель/роутер OpenRouter '%s' недоступна. Проверьте OPENROUTER_MODELS или используйте 'openrouter/free'",
                                model,
                            )
                        if (
                            response.status_code == 400
                            and current_reasoning == OPENROUTER_NO_REASONING_PAYLOAD
                            and self._response_requires_reasoning(response.text)
                            and not is_last_attempt
                        ):
                            logger.warning(
                                "Провайдер OpenRouter требует reasoning для модели '%s'; повторяем попытку с reasoning enabled",
                                model,
                            )
                            current_reasoning = dict(OPENROUTER_HIDDEN_REASONING_PAYLOAD)
                            continue
                        if self._should_retry_status_code(response.status_code) and not is_last_attempt:
                            logger.warning(
                                "OpenRouter вернул retryable ошибку для модели '%s' (attempt %s/%s): status=%s body=%s, повторяем",
                                model,
                                attempt,
                                self.retries_per_model,
                                response.status_code,
                                self._truncate_for_log(response.text),
                            )
                            continue
                        logger.warning(
                            "OpenRouter вернул ошибку для модели '%s' (attempt %s/%s): status=%s body=%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            response.status_code,
                            self._truncate_for_log(response.text),
                        )
                        break

                    try:
                        body = response.json()
                    except ValueError:
                        logger.warning(
                            "Некорректный JSON от OpenRouter для модели '%s' (attempt %s/%s): body=%s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            self._truncate_for_log(response.text),
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue

                    generated = self._clean_comment_text(self._extract_content(body))
                    if not generated:
                        logger.warning(
                            "Пустой ответ от OpenRouter для модели '%s' (attempt %s/%s): %s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            self._extract_empty_response_details(body, response.text),
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue

                    logger.info(
                        "Комментарий успешно сгенерирован через OpenRouter модель '%s' (attempt %s/%s)",
                        model,
                        attempt,
                        self.retries_per_model,
                    )
                    return generated

        logger.error("Все fallback-модели OpenRouter вернули ошибку или пустой ответ")
        return None

    async def generate_structured_output_with_fallback(
        self,
        *,
        schema_model: type[StructuredOutputT],
        schema_name: str,
        system_prompt: str,
        user_prompt: str,
        models: Sequence[str] | None = None,
        max_tokens: int = 500,
        temperature: float = 0.2,
    ) -> StructuredOutputT | None:
        """Запрашивает у OpenRouter structured output и валидирует его Pydantic-схемой."""
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY не задан, structured output невозможен")
            return None

        selected_models = self._normalize_models(models or self.structured_models or self.models)
        if not selected_models:
            logger.error("Список structured-моделей OpenRouter пуст")
            return None

        normalized_system_prompt = (system_prompt or "").strip()
        normalized_user_prompt = (user_prompt or "").strip()
        if not normalized_user_prompt:
            logger.warning("Пустой user_prompt для structured output OpenRouter")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        response_format = self._build_json_schema_response_format(
            schema_model=schema_model,
            schema_name=schema_name,
        )

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for model in selected_models:
                for attempt in range(1, self.retries_per_model + 1):
                    messages: list[dict[str, str]] = []
                    if normalized_system_prompt:
                        messages.append({"role": "system", "content": normalized_system_prompt})
                    messages.append({"role": "user", "content": normalized_user_prompt})

                    payload = self._build_payload(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        response_format=response_format,
                        plugins=[dict(OPENROUTER_RESPONSE_HEALING_PLUGIN)],
                        provider=dict(OPENROUTER_PROVIDER_REQUIRE_PARAMETERS),
                        reasoning=dict(OPENROUTER_HIDDEN_REASONING_PAYLOAD),
                    )

                    is_last_attempt = attempt >= self.retries_per_model

                    try:
                        response = await client.post(
                            OPENROUTER_CHAT_COMPLETIONS_URL,
                            headers=headers,
                            json=payload,
                        )
                    except httpx.TimeoutException:
                        logger.warning(
                            "Таймаут structured output OpenRouter для модели '%s' (attempt %s/%s)%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue
                    except httpx.HTTPError as e:
                        logger.warning(
                            "HTTP ошибка structured output OpenRouter для модели '%s' (attempt %s/%s): %s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            e,
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue
                    except Exception as e:
                        logger.warning(
                            "Неожиданная ошибка structured output OpenRouter для модели '%s' (attempt %s/%s): %s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            e,
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue

                    if response.status_code >= 400:
                        if self._should_retry_status_code(response.status_code) and not is_last_attempt:
                            logger.warning(
                                "OpenRouter вернул retryable ошибку structured output для модели '%s' (attempt %s/%s): status=%s body=%s, повторяем",
                                model,
                                attempt,
                                self.retries_per_model,
                                response.status_code,
                                self._truncate_for_log(response.text),
                            )
                            continue
                        logger.warning(
                            "OpenRouter вернул ошибку structured output для модели '%s' (attempt %s/%s): status=%s body=%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            response.status_code,
                            self._truncate_for_log(response.text),
                        )
                        break

                    try:
                        body = response.json()
                    except ValueError:
                        logger.warning(
                            "Некорректный JSON от OpenRouter для structured output модели '%s' (attempt %s/%s): body=%s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            self._truncate_for_log(response.text),
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue

                    raw_content = self._extract_structured_content_payload(body)
                    try:
                        parsed = self._parse_structured_output(
                            schema_model=schema_model,
                            content=raw_content,
                            response_json=body,
                        )
                    except ValidationError as e:
                        logger.warning(
                            "Structured output не прошел валидацию для модели '%s' (attempt %s/%s): %s; body=%s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            e,
                            self._truncate_for_log(response.text),
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue
                    except Exception as e:
                        logger.warning(
                            "Не удалось распарсить structured output модели '%s' (attempt %s/%s): %s; body=%s%s",
                            model,
                            attempt,
                            self.retries_per_model,
                            e,
                            self._truncate_for_log(response.text),
                            ", пробуем следующую" if is_last_attempt else ", повторяем",
                        )
                        if is_last_attempt:
                            break
                        continue

                    logger.info(
                        "Structured output успешно получен через OpenRouter модель '%s' (attempt %s/%s)",
                        model,
                        attempt,
                        self.retries_per_model,
                    )
                    return parsed

        logger.error("Все structured fallback-модели OpenRouter вернули ошибку или невалидный ответ")
        return None
