import os
import time
import logging
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PROVIDER_CONFIG = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
}

_PRICING = {
    "deepseek": {"input": 0.27, "output": 1.10},
    "qwen": {"input": 2.00, "output": 6.00},
    "openai": {"input": 0.15, "output": 0.60},
}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    content: str
    usage: Usage = field(default_factory=Usage)


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        pass


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, model: str, api_key: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        return LLMResponse(content=content, usage=usage)

    def close(self):
        self._client.close()


def get_provider(name: Optional[str] = None) -> OpenAICompatibleProvider:
    name = (name or os.environ.get("LLM_PROVIDER", "deepseek")).lower()
    config = _PROVIDER_CONFIG.get(name)
    if not config:
        raise ValueError(f"Unknown provider: {name}, choose from {list(_PROVIDER_CONFIG)}")
    api_key = os.environ.get(config["api_key_env"])
    if not api_key:
        raise ValueError(f"Missing {config['api_key_env']} environment variable")
    return OpenAICompatibleProvider(
        name=name,
        base_url=config["base_url"],
        model=config["model"],
        api_key=api_key,
    )


def estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for c in text if c.isascii())
    non_ascii_chars = len(text) - ascii_chars
    return int(ascii_chars / 4 + non_ascii_chars / 1.5)


def calculate_cost(usage: Usage, provider: str) -> float:
    pricing = _PRICING.get(provider.lower(), _PRICING["openai"])
    input_cost = usage.prompt_tokens * pricing["input"] / 1_000_000
    output_cost = usage.completion_tokens * pricing["output"] / 1_000_000
    return round(input_cost + output_cost, 6)


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict],
    max_retries: int = 3,
    **kwargs,
) -> LLMResponse:
    for attempt in range(max_retries):
        try:
            return provider.chat(messages, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2**attempt
            logger.warning(
                "Chat failed (attempt %d/%d): %s. Retrying in %ds...",
                attempt + 1,
                max_retries,
                e,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError("Unreachable")


def quick_chat(prompt: str, provider: Optional[str] = None, **kwargs) -> str:
    p = get_provider(provider)
    try:
        response = chat_with_retry(p, [{"role": "user", "content": prompt}], **kwargs)
        return response.content
    finally:
        p.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    for name in ["deepseek", "qwen", "openai"]:
        env_key = _PROVIDER_CONFIG[name]["api_key_env"]
        if not os.environ.get(env_key):
            logger.info("Skipping %s: %s not set", name, env_key)
            continue
        logger.info("Testing provider: %s", name)
        try:
            provider = get_provider(name)
            response = chat_with_retry(
                provider,
                [{"role": "user", "content": "Say hello in 5 words or less."}],
            )
            cost = calculate_cost(response.usage, name)
            logger.info(
                "Response: %s | Usage: %s | Cost: $%.6f",
                response.content,
                response.usage,
                cost,
            )
            provider.close()
        except Exception as e:
            logger.error("Provider %s failed: %s", name, e)
