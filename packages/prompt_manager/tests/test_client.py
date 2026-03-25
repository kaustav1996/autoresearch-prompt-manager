"""Tests for the client SDK with mocked httpx."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from prompt_manager.client.cache import TTLCache
from prompt_manager.client.client import PromptManagerClient
from prompt_manager.client.models import ResolvedPrompt


# ── TTLCache tests ────────────────────────────────────────────────────────


class TestTTLCache:
    def test_get_set(self) -> None:
        cache = TTLCache(ttl=60.0)
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_missing_key(self) -> None:
        cache = TTLCache(ttl=60.0)
        assert cache.get("missing") is None

    def test_expiration(self) -> None:
        cache = TTLCache(ttl=0.0)  # expires immediately
        cache.set("k1", "v1")
        assert cache.get("k1") is None

    def test_invalidate(self) -> None:
        cache = TTLCache(ttl=60.0)
        cache.set("k1", "v1")
        cache.invalidate("k1")
        assert cache.get("k1") is None

    def test_clear(self) -> None:
        cache = TTLCache(ttl=60.0)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_max_size_eviction(self) -> None:
        cache = TTLCache(ttl=60.0, max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # should evict oldest
        assert cache.get("c") == 3
        # At most 2 entries
        count = sum(1 for k in ["a", "b", "c"] if cache.get(k) is not None)
        assert count <= 2


# ── ResolvedPrompt tests ─────────────────────────────────────────────────


class TestResolvedPrompt:
    def test_render(self) -> None:
        rp = ResolvedPrompt(
            slug="test",
            version=1,
            body="Hello {{name}}, welcome to {{place}}!",
            template_vars=["name", "place"],
            content_hash="abc",
            version_id=uuid4(),
        )
        assert rp.render(name="Alice", place="Wonderland") == "Hello Alice, welcome to Wonderland!"

    def test_render_no_vars(self) -> None:
        rp = ResolvedPrompt(
            slug="test",
            version=1,
            body="Static prompt",
            content_hash="def",
            version_id=uuid4(),
        )
        assert rp.render() == "Static prompt"


# ── PromptManagerClient tests (mocked transport) ─────────────────────────


class MockTransport(httpx.AsyncBaseTransport):
    """A mock transport that returns canned responses."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._resolve_response = {
            "slug": "my-prompt",
            "version": 1,
            "body": "Hello {{name}}",
            "template_vars": ["name"],
            "content_hash": "abc123",
            "version_id": str(uuid4()),
        }
        self._prompt_response = {
            "id": str(uuid4()),
            "slug": "my-prompt",
            "name": "My Prompt",
            "tags": [],
            "metadata": {},
            "current_version": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path.startswith("/resolve/"):
            return httpx.Response(200, json=self._resolve_response)
        if path.startswith("/prompts/"):
            return httpx.Response(200, json=self._prompt_response)
        if path == "/metrics":
            return httpx.Response(201, json={"id": str(uuid4())})
        return httpx.Response(404, json={"detail": "Not found"})


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest.fixture
def client(mock_transport: MockTransport) -> PromptManagerClient:
    c = PromptManagerClient.__new__(PromptManagerClient)
    c._client = httpx.AsyncClient(transport=mock_transport, base_url="http://test")
    c._cache = TTLCache(ttl=60.0)
    return c


@pytest.mark.asyncio
async def test_resolve(client: PromptManagerClient, mock_transport: MockTransport) -> None:
    result = await client.resolve("my-prompt")
    assert isinstance(result, ResolvedPrompt)
    assert result.slug == "my-prompt"
    assert result.version == 1
    assert len(mock_transport.requests) == 1


@pytest.mark.asyncio
async def test_resolve_with_cache(client: PromptManagerClient, mock_transport: MockTransport) -> None:
    await client.resolve("my-prompt")
    await client.resolve("my-prompt")
    # Second call should hit cache
    assert len(mock_transport.requests) == 1


@pytest.mark.asyncio
async def test_resolve_no_cache() -> None:
    transport = MockTransport()
    c = PromptManagerClient.__new__(PromptManagerClient)
    c._client = httpx.AsyncClient(transport=transport, base_url="http://test")
    c._cache = None
    await c.resolve("my-prompt")
    await c.resolve("my-prompt")
    assert len(transport.requests) == 2
    await c.close()


@pytest.mark.asyncio
async def test_report_metric(client: PromptManagerClient, mock_transport: MockTransport) -> None:
    await client.report_metric(
        slug="my-prompt",
        version_id=str(uuid4()),
        metric_name="latency_ms",
        value=42.0,
    )
    # First request: GET /prompts/my-prompt, second: POST /metrics
    assert len(mock_transport.requests) == 2
    assert mock_transport.requests[1].method == "POST"


@pytest.mark.asyncio
async def test_context_manager(mock_transport: MockTransport) -> None:
    c = PromptManagerClient.__new__(PromptManagerClient)
    c._client = httpx.AsyncClient(transport=mock_transport, base_url="http://test")
    c._cache = TTLCache(ttl=60.0)
    async with c:
        result = await c.resolve("my-prompt")
        assert result.slug == "my-prompt"
