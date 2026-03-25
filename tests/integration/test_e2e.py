"""End-to-end integration tests.

These tests require a running PostgreSQL instance.
Set PM_DATABASE_URL to point to it, or skip with:
    pytest tests/integration/ -m "not integration"

Run with:
    PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager \
        python3 -m pytest tests/integration/ -v
"""

from __future__ import annotations

import os

import pytest

# Skip the entire module if no DB URL is configured
DB_URL = os.environ.get(
    "PM_DATABASE_URL",
    "postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager",
)

@pytest.fixture()
async def api_client():
    """Create a FastAPI test client with lifespan managed."""
    import httpx
    from httpx import ASGITransport

    from prompt_manager.api.app import create_app
    from prompt_manager.api.db.engine import close_pool, create_pool, run_migrations
    from prompt_manager.core.config import PromptManagerSettings

    settings = PromptManagerSettings(database_url=DB_URL)
    await run_migrations(settings)
    await create_pool(settings)

    app = create_app(settings)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    # Cleanup test data
    import asyncpg

    conn = await asyncpg.connect(dsn=DB_URL)
    for table in [
        "metric_events", "session_assignments", "experiment_arms",
        "experiments", "optimization_runs", "prompt_versions", "prompts",
    ]:
        await conn.execute(f"DELETE FROM {table}")  # noqa: S608
    await conn.close()
    await close_pool()


class TestPromptCRUD:
    async def test_create_and_get_prompt(self, api_client: "httpx.AsyncClient") -> None:
        resp = await api_client.post(
            "/prompts",
            json={"slug": "test-crud", "name": "Test", "body": "Hello {name}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "test-crud"

        resp = await api_client.get("/prompts/test-crud")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "test-crud"

    async def test_duplicate_slug_returns_409(self, api_client: "httpx.AsyncClient") -> None:
        await api_client.post(
            "/prompts",
            json={"slug": "dup-test", "name": "Dup", "body": "content"},
        )
        resp = await api_client.post(
            "/prompts",
            json={"slug": "dup-test", "name": "Dup2", "body": "content2"},
        )
        assert resp.status_code == 409


class TestVersioning:
    async def test_create_versions_and_resolve_latest(
        self, api_client: "httpx.AsyncClient"
    ) -> None:
        # Create prompt with v1
        await api_client.post(
            "/prompts",
            json={"slug": "ver-test", "name": "Version Test", "body": "Version 1"},
        )

        # Create v2
        resp = await api_client.post(
            "/prompts/ver-test/versions", json={"body": "Version 2"}
        )
        assert resp.status_code == 201
        assert resp.json()["version"] == 2

        # Resolve should return v2 (latest)
        resp = await api_client.get("/resolve/ver-test")
        assert resp.status_code == 200
        assert resp.json()["version"] == 2
        assert resp.json()["body"] == "Version 2"

    async def test_resolve_pinned_version(self, api_client: "httpx.AsyncClient") -> None:
        await api_client.post(
            "/prompts",
            json={"slug": "pin-test", "name": "Pin", "body": "v1 content"},
        )
        await api_client.post("/prompts/pin-test/versions", json={"body": "v2 content"})

        resp = await api_client.get("/resolve/pin-test?version=1")
        assert resp.json()["version"] == 1
        assert resp.json()["body"] == "v1 content"


class TestExperimentRouting:
    async def test_experiment_routes_traffic(self, api_client: "httpx.AsyncClient") -> None:
        # Setup: create prompt with 2 versions
        resp = await api_client.post(
            "/prompts",
            json={"slug": "exp-test", "name": "Exp Test", "body": "Control"},
        )
        prompt_id = resp.json()["id"]

        resp = await api_client.post("/prompts/exp-test/versions", json={"body": "Variant"})
        v2_id = resp.json()["id"]

        # Get v1 id
        resp = await api_client.get("/prompts/exp-test/versions")
        versions = resp.json()
        v1_id = versions[0]["id"]

        # Create and start experiment
        resp = await api_client.post(
            "/experiments",
            json={
                "prompt_slug": "exp-test",
                "name": "routing-test",
                "arms": [
                    {"version_id": v1_id, "weight": 50, "label": "control"},
                    {"version_id": v2_id, "weight": 50, "label": "variant"},
                ],
            },
        )
        exp_id = resp.json()["id"]

        await api_client.patch(
            f"/experiments/{exp_id}/status", json={"status": "running"}
        )

        # Route 20 sessions — should see both versions
        versions_seen = set()
        for i in range(20):
            resp = await api_client.get(f"/resolve/exp-test?session_id=session-{i}")
            versions_seen.add(resp.json()["version"])

        assert len(versions_seen) == 2, f"Expected both versions, got {versions_seen}"

    async def test_sticky_session(self, api_client: "httpx.AsyncClient") -> None:
        # Setup
        resp = await api_client.post(
            "/prompts",
            json={"slug": "sticky-test", "name": "Sticky", "body": "v1"},
        )
        await api_client.post("/prompts/sticky-test/versions", json={"body": "v2"})

        resp = await api_client.get("/prompts/sticky-test/versions")
        versions = resp.json()
        v1_id, v2_id = versions[0]["id"], versions[1]["id"]

        resp = await api_client.post(
            "/experiments",
            json={
                "prompt_slug": "sticky-test",
                "name": "sticky-exp",
                "arms": [
                    {"version_id": v1_id, "weight": 50},
                    {"version_id": v2_id, "weight": 50},
                ],
            },
        )
        exp_id = resp.json()["id"]
        await api_client.patch(
            f"/experiments/{exp_id}/status", json={"status": "running"}
        )

        # Same session should always get the same version
        first = await api_client.get("/resolve/sticky-test?session_id=sticky-user")
        first_version = first.json()["version"]

        for _ in range(5):
            resp = await api_client.get("/resolve/sticky-test?session_id=sticky-user")
            assert resp.json()["version"] == first_version


class TestMetrics:
    async def test_ingest_and_aggregate(self, api_client: "httpx.AsyncClient") -> None:
        resp = await api_client.post(
            "/prompts",
            json={"slug": "metric-test", "name": "Metric Test", "body": "content"},
        )
        prompt_id = resp.json()["id"]

        resp = await api_client.get("/prompts/metric-test/versions")
        version_id = resp.json()[0]["id"]

        # Ingest metrics
        for val in [7.0, 8.0, 9.0]:
            await api_client.post(
                "/metrics",
                json={
                    "prompt_id": prompt_id,
                    "version_id": version_id,
                    "metric_name": "quality",
                    "metric_value": val,
                },
            )

        # Aggregate
        resp = await api_client.get(
            f"/metrics/aggregate?prompt_id={prompt_id}&metric_name=quality"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["count"] == 3
        assert data[0]["mean"] == 8.0


class TestClientSDK:
    async def test_client_resolve(self, api_client: "httpx.AsyncClient") -> None:
        """Test the client SDK against the test API."""
        from prompt_manager.client import PromptManagerClient

        # Seed a prompt via API
        await api_client.post(
            "/prompts",
            json={"slug": "client-test", "name": "Client Test", "body": "Hello {user}"},
        )

        # Use client SDK
        client = PromptManagerClient(base_url="http://test")
        # Replace internal httpx client with the test transport
        client._client = api_client

        result = await client.resolve("client-test")
        assert result.body == "Hello {user}"
        assert result.version == 1


class TestCrossPackageIntegration:
    """Test that shonku and autoresearcher-shonku work together."""

    def test_shonku_agent_collects_tools(self) -> None:
        from shonku import ShonkuAgent, tool

        class TestAgent(ShonkuAgent):
            name = "test"
            instructions = "test"

            @tool(description="Test tool")
            def my_tool(self, x: str) -> str:
                return x

        agent = TestAgent()
        assert len(agent._own_tools) == 1
        assert agent._own_tools[0].name == "my_tool"

    def test_autoresearcher_agents_exist(self) -> None:
        from autoresearcher_shonku import (
            AutoResearcherAgent,
            ExperimentManagerAgent,
            PromptAnalyzerAgent,
            PromptOptimizerAgent,
        )

        assert AutoResearcherAgent.name == "autoresearcher"
        assert len(AutoResearcherAgent.required_tools) == 6
        assert PromptAnalyzerAgent.name == "prompt-analyzer"
        assert PromptOptimizerAgent.name == "prompt-optimizer"
        assert ExperimentManagerAgent.name == "experiment-manager"

    def test_tool_set_merges_external_and_agent_tools(self) -> None:
        from shonku.tool_set import ToolSet
        from shonku.types import ToolSpec

        ts = ToolSet()
        ts.add(ToolSpec(name="get_prompt", description="Get a prompt", callable=lambda: None))
        ts.add(ToolSpec(name="get_metrics", description="Get metrics", callable=lambda: None))

        from autoresearcher_shonku import AutoResearcherAgent

        agent = AutoResearcherAgent()
        agent_ts = ToolSet()
        for t in agent._own_tools:
            agent_ts.add(t)

        merged = ts.merge(agent_ts)
        names = list(merged._tools.keys())
        assert "get_prompt" in names
        assert "get_metrics" in names
        assert "check_safety_rails" in names
