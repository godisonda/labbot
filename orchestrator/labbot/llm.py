from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))
import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Type, TypeVar
import openai
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("mtuci-labbot.llm")

PRICING_PER_1M = {
    "deepseek-chat": {"input_cache_miss": 0.27, "input_cache_hit": 0.07, "output": 1.10},
    "deepseek-reasoner": {"input_cache_miss": 0.55, "input_cache_hit": 0.14, "output": 2.19},
}


class DeepSeekAPIError(Exception):
    pass


class DeepSeekClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 180.0,
        max_retries: int = 4,
        max_cost_limit: float = 2.00,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise DeepSeekAPIError(
                "DEEPSEEK_API_KEY не задан в переменных окружения или файле .env!"
            )

        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.max_cost_limit = float(max_cost_limit)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cached_tokens = 0
        self.estimated_cost_usd = 0.0

        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )
        logger.info("DeepSeekClient инициализирован. Base URL: %s, Модель: %s", self.base_url, self.model)

    def close(self):
        if hasattr(self.client, "close"):
            self.client.close()

    def _update_usage(self, usage: Any):
        if not usage:
            return
        p_tokens = getattr(usage, "prompt_tokens", 0) or 0
        c_tokens = getattr(usage, "completion_tokens", 0) or 0
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0

        self.total_prompt_tokens += p_tokens
        self.total_completion_tokens += c_tokens
        self.total_cached_tokens += cached_tokens

        pricing = PRICING_PER_1M.get(self.model, PRICING_PER_1M["deepseek-chat"])
        uncached = max(0, p_tokens - cached_tokens)
        call_cost = (
            (uncached / 1_000_000) * pricing["input_cache_miss"]
            + (cached_tokens / 1_000_000) * pricing["input_cache_hit"]
            + (c_tokens / 1_000_000) * pricing["output"]
        )
        self.estimated_cost_usd += call_cost

        if self.estimated_cost_usd > self.max_cost_limit:
            raise DeepSeekAPIError(
                f"Превышен лимит стоимости (${self.max_cost_limit:.2f}). Текущие расходы: ${self.estimated_cost_usd:.4f}."
            )

    def _request_with_retry(self, **kwargs) -> Any:
        delay = 2.0
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                start_time = time.time()
                response = self.client.chat.completions.create(**kwargs)
                elapsed = time.time() - start_time
                logger.info("Запрос к DeepSeek API успешен за %.2f с (попытка %d/%d)", elapsed, attempt, self.max_retries)
                self._update_usage(response.usage)
                return response
            except openai.APIStatusError as e:
                status = getattr(e, "status_code", None)
                if status == 402:
                    raise DeepSeekAPIError(
                        "Недостаточно средств на балансе DeepSeek (HTTP 402). Пополните счёт."
                    ) from e
                if status in (401, 403):
                    raise DeepSeekAPIError(
                        f"Ошибка авторизации DeepSeek (HTTP {status}): проверьте DEEPSEEK_API_KEY."
                    ) from e

                last_exception = e
                sleep_time = (delay * (2 ** (attempt - 1))) + random.uniform(0.5, 1.5)
                logger.warning(
                    "Ошибка API (%s, HTTP %s). Попытка %d/%d. Ожидание %.2f с...",
                    type(e).__name__, status, attempt, self.max_retries, sleep_time,
                )
                time.sleep(sleep_time)
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                last_exception = e
                sleep_time = (delay * (2 ** (attempt - 1))) + random.uniform(0.5, 1.5)
                logger.warning("Ошибка API (%s). Попытка %d/%d. Ожидание %.2f с...", type(e).__name__, attempt, self.max_retries, sleep_time)
                time.sleep(sleep_time)
            except Exception as e:
                raise DeepSeekAPIError(f"Ошибка API: {e}") from e

        raise DeepSeekAPIError(f"Не удалось получить ответ после {self.max_retries} попыток: {last_exception}")

    def generate_text(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        response = self._request_with_retry(
            model=self.model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
        )
        content = response.choices[0].message.content or ""
        return content.strip()

    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema_cls: Type[T],
        temperature: float = 0.1,
        max_tokens: int = 8192,
        max_fix_attempts: int = 2,
    ) -> T:
        schema_prompt = (
            f"\nВнимание: Твой ответ ОБЯЗАН быть строго валидным JSON-объектом, "
            f"соответствующим следующей JSON Schema:\n{json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)}"
        )
        enriched_messages = list(messages)
        if enriched_messages and enriched_messages[0]["role"] == "system":
            enriched_messages[0] = {
                "role": "system",
                "content": enriched_messages[0]["content"] + schema_prompt,
            }
        else:
            enriched_messages.insert(0, {"role": "system", "content": schema_prompt})

        cur_messages = list(enriched_messages)

        for fix_attempt in range(max_fix_attempts + 1):
            response = self._request_with_retry(
                model=self.model,
                messages=cur_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw_text = (response.choices[0].message.content or "{}").strip()
            raw_text = re.sub(r"^```(?:json)?\s*\n", "", raw_text) if "re" in globals() else raw_text
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            try:
                data = json.loads(raw_text)
                return schema_cls.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as err:
                logger.warning("Ошибка валидации JSON (%d/%d): %s", fix_attempt, max_fix_attempts, err)
                if fix_attempt == max_fix_attempts:
                    raise DeepSeekAPIError(f"Ошибка валидации {schema_cls.__name__}: {err}")
                cur_messages.append({"role": "assistant", "content": raw_text})
                cur_messages.append({
                    "role": "user",
                    "content": f"JSON не соответствует схеме: {err}. Верни строго валидный JSON.",
                })
