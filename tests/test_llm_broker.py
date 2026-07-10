"""Tests for the LLM broker and provider implementations."""

import pytest

from app.services.llm import (
    DeepSeekProvider,
    LLMBroker,
    MockLLMProvider,
    OpenAIProvider,
)


@pytest.mark.asyncio
async def test_mock_provider_stream():
    """MockLLMProvider should yield configured tokens."""
    mock = MockLLMProvider(stream_tokens=["Hello ", "world"])
    tokens = []
    async for token in mock.stream_completion(
        messages=[{"role": "user", "content": "Hi"}],
        system="Be helpful.",
    ):
        tokens.append(token)
    assert tokens == ["Hello ", "world"]


@pytest.mark.asyncio
async def test_mock_provider_structured():
    """MockLLMProvider should return configured structured response."""
    mock = MockLLMProvider(structured_response='{"result": "success"}')
    result = await mock.structured_completion(
        messages=[{"role": "user", "content": "Extract data"}],
        system="Extract JSON.",
    )
    assert result == '{"result": "success"}'


@pytest.mark.asyncio
async def test_mock_provider_records_calls():
    """MockLLMProvider should record the last messages and system prompt."""
    mock = MockLLMProvider()
    async for _ in mock.stream_completion(
        messages=[{"role": "user", "content": "Hello"}],
        system="System prompt",
    ):
        pass

    assert mock.last_messages == [{"role": "user", "content": "Hello"}]
    assert mock.last_system == "System prompt"


def test_broker_defaults_to_mock():
    """LLMBroker should default to MockLLMProvider when no API keys are set."""
    broker = LLMBroker()
    # Force re-resolve by clearing any pre-set provider
    broker._provider = None
    provider = broker._resolve()
    assert isinstance(provider, MockLLMProvider)


def test_broker_set_provider():
    """LLMBroker.set_provider() should override the active provider."""
    broker = LLMBroker()
    mock = MockLLMProvider()
    broker.set_provider(mock)
    assert broker._provider is mock


@pytest.mark.asyncio
async def test_broker_delegates_stream():
    """LLMBroker should delegate stream_completion to the active provider."""
    broker = LLMBroker()
    mock = MockLLMProvider(stream_tokens=["a", "b"])
    broker.set_provider(mock)

    tokens = []
    async for token in broker.stream_completion(
        messages=[{"role": "user", "content": "Hi"}],
        system="Be helpful.",
    ):
        tokens.append(token)
    assert tokens == ["a", "b"]


@pytest.mark.asyncio
async def test_broker_delegates_structured():
    """LLMBroker should delegate structured_completion to the active provider."""
    broker = LLMBroker()
    mock = MockLLMProvider(structured_response='{"ok": true}')
    broker.set_provider(mock)

    result = await broker.structured_completion(
        messages=[{"role": "user", "content": "Extract"}],
        system="Extract JSON.",
    )
    assert result == '{"ok": true}'
