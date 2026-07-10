"""Shared test fixtures and configuration.

Monkeypatches app.db with an in-memory mock so tests don't need PostgreSQL.
"""

import sys
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ──────────────────────────────────────────────
#  Monkeypatch app.db with in-memory mock
#  This must happen BEFORE any app imports
# ──────────────────────────────────────────────

import tests.test_db as mock_db_module

# Replace the app.db module with our mock
sys.modules["app.db"] = mock_db_module

# Now safe to import app modules
from app.main import app
from app.services.llm import MockLLMProvider, llm


# ──────────────────────────────────────────────
#  Override LLM with mock for all tests
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_llm():
    """Replace the real LLM provider with a mock for every test."""
    mock = MockLLMProvider(
        stream_tokens=["Mock ", "response ", "from ", "LLM."],
        structured_response=(
            '{"ok": true, "figures": [], "symbols": [], '
            '"emotionalTone": "serene", "individuationIndex": 0.5}'
        ),
    )
    llm.set_provider(mock)
    yield mock


# ──────────────────────────────────────────────
#  Reset mock DB between tests
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_mock_db():
    """Reset the in-memory database between tests."""
    mock_db_module.get_mock_db().reset()


# ──────────────────────────────────────────────
#  Test client
# ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

@pytest.fixture
def test_client_id() -> str:
    return str(uuid4())


@pytest.fixture
def auth_headers(test_client_id: str) -> dict:
    return {"X-Client-Id": test_client_id}
