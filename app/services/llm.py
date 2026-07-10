"""LLM broker — abstract interface + provider implementations.

The broker pattern allows swapping providers (DeepSeek, OpenAI, Anthropic, etc.)
without changing any calling code. Add a new provider by implementing LLMProvider.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk

from app.config import settings


# ──────────────────────────────────────────────
#  Abstract interface
# ──────────────────────────────────────────────

class LLMProvider(ABC):
    """Interface all LLM providers must implement."""

    @abstractmethod
    async def stream_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        """Stream a completion. Yields text tokens."""
        ...  # pragma: no cover

    @abstractmethod
    async def structured_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        """Non-streaming completion expecting structured JSON output."""
        ...  # pragma: no cover


# ──────────────────────────────────────────────
#  DeepSeek implementation (OpenAI-compatible)
# ──────────────────────────────────────────────

class DeepSeekProvider(LLMProvider):
    """DeepSeek via OpenAI-compatible API."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )

    async def stream_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        stream: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
            model=model or "deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def structured_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=model or "deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


# ──────────────────────────────────────────────
#  OpenAI implementation
# ──────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    """Native OpenAI provider."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def stream_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        stream: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def structured_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=model or "gpt-4o",
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


# ──────────────────────────────────────────────
#  Mock / testing implementation
# ──────────────────────────────────────────────

class MockLLMProvider(LLMProvider):
    """In-memory mock for testing. Returns canned responses."""

    def __init__(
        self,
        stream_tokens: list[str] | None = None,
        structured_response: str = '{"ok": true}',
    ):
        self.stream_tokens = stream_tokens or [
            "This ", "is ", "a ", "mock ", "response."
        ]
        self.structured_response = structured_response
        self.last_messages: list[dict] | None = None
        self.last_system: str | None = None

    async def stream_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        self.last_messages = messages
        self.last_system = system
        for token in self.stream_tokens:
            yield token

    async def structured_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.last_messages = messages
        self.last_system = system
        return self.structured_response


# ──────────────────────────────────────────────
#  Broker — resolves provider at runtime
# ──────────────────────────────────────────────

class LLMBroker:
    """
    Resolves the active LLM provider based on configuration.
    Calling code never touches providers directly — only through this broker.
    """

    def __init__(self):
        self._provider: LLMProvider | None = None

    def _resolve(self) -> LLMProvider:
        if self._provider is not None:
            return self._provider

        # Priority: DeepSeek > OpenAI > Mock
        # Only use a provider if the API key looks real (not a placeholder)
        dsk = settings.deepseek_api_key
        oai = settings.openai_api_key

        if dsk and not dsk.startswith("sk-your") and not dsk.startswith("sk-placeholder"):
            self._provider = DeepSeekProvider(dsk)
        elif oai and not oai.startswith("sk-your") and not oai.startswith("sk-placeholder"):
            self._provider = OpenAIProvider(oai)
        else:
            self._provider = MockLLMProvider()

        return self._provider

    def set_provider(self, provider: LLMProvider) -> None:
        """Override the provider (useful for testing)."""
        self._provider = provider

    async def stream_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        provider = self._resolve()
        async for token in provider.stream_completion(messages, system, model, temperature):
            yield token

    async def structured_completion(
        self,
        messages: list[dict],
        system: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        provider = self._resolve()
        return await provider.structured_completion(messages, system, model, temperature)


# Singleton broker
llm = LLMBroker()
