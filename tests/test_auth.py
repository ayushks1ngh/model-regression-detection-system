"""Tests for bearer-token authentication, token management, and rate limiting."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from model_regression_detection.api.tokens import generate_token, parse_token_id, verify_token
from model_regression_detection.config import Environment, Settings
from model_regression_detection.main import create_app
from model_regression_detection.persistence import Base, RunRepository
from model_regression_detection.persistence.models import ProjectTokenRow

pytestmark = pytest.mark.anyio


# ── Token utilities ─────────────────────────────────────────────────────


async def test_generate_token_returns_secret_and_hash() -> None:
    token_id = uuid4().hex
    secret, token_hash = generate_token(token_id)
    assert secret.startswith("mrds_")
    assert token_id in secret
    assert ":" in token_hash


async def test_generate_and_verify_token() -> None:
    token_id = uuid4().hex
    secret, token_hash = generate_token(token_id)
    assert verify_token(secret, token_hash) is True


async def test_verify_rejects_wrong_secret() -> None:
    token_id = uuid4().hex
    _, token_hash = generate_token(token_id)
    assert verify_token("wrong_secret", token_hash) is False


async def test_verify_rejects_malformed_hash() -> None:
    assert verify_token("secret", "not-a-valid-hash") is False


async def test_parse_token_id_extracts_correctly() -> None:
    token_id = uuid4().hex
    secret = f"mrds_{token_id}_abc123"
    assert parse_token_id(secret) == token_id


async def test_parse_token_id_returns_none_for_invalid_format() -> None:
    assert parse_token_id("invalid") is None
    assert parse_token_id("") is None


# ── Repository token methods ─────────────────────────────────────────────


async def _engine() -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_create_and_list_tokens() -> None:
    engine, factory = await _engine()
    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-t", "proj-t", "Token Test")
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        tid = await repo.create_token("proj-t", "ci-token", "hash123")
        await session.commit()
        assert tid is not None

    async with factory() as session:
        repo = RunRepository(session)
        tokens = await repo.list_tokens("proj-t")
        assert len(tokens) == 1
        assert tokens[0].name == "ci-token"

    await engine.dispose()


async def test_repository_revoke_token() -> None:
    engine, factory = await _engine()
    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-t", "proj-t", "Token Test")
        tid = await repo.create_token("proj-t", "temp", "hash")
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        revoked = await repo.revoke_token(tid)
        await session.commit()
        assert revoked is True

    async with factory() as session:
        tokens = await RunRepository(session).list_tokens("proj-t")
        assert len(tokens) == 0  # revoked tokens are excluded
    await engine.dispose()


async def test_touch_token_updates_last_used() -> None:
    engine, factory = await _engine()
    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-t", "proj-t", "Token Test")
        tid = await repo.create_token("proj-t", "temp", "hash")
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.touch_token(tid)
        await session.commit()

    async with factory() as session:
        row = await session.get(ProjectTokenRow, tid)
        assert row is not None
        assert row.last_used_at is not None
    await engine.dispose()


# ── Auth API ─────────────────────────────────────────────────────────────


async def _create_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[tuple[TestClient, str, str]]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'auth_test.db'}"
    asyncio.run(_create_schema(database_url))
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        database_url=database_url,
    )
    with TestClient(create_app(settings)) as test_client:
        # Create a project and token via DB
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        token_secret: str = ""

        async def setup() -> None:
            nonlocal token_secret
            async with factory() as session:
                repo = RunRepository(session)
                await repo.ensure_project("proj-auth", "proj-auth", "Auth Test")
                token_id = uuid4().hex
                token_secret, token_hash = generate_token(token_id)
                await repo.create_token("proj-auth", "test-token", token_hash, token_id)
                await session.commit()
            await engine.dispose()

        asyncio.run(setup())
        yield test_client, database_url, token_secret


def test_create_token_endpoint(ctx: tuple[TestClient, str, str]) -> None:
    """Create a token via the API, authenticated with an existing token."""
    client, _url, existing_token = ctx
    response = client.post(
        "/api/v1/projects/proj-auth/tokens",
        json={"name": "new-ci-token"},
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "new-ci-token"
    assert payload["project_id"] == "proj-auth"
    assert payload["token"].startswith("mrds_")


def test_create_token_with_wrong_project_returns_403(ctx: tuple[TestClient, str, str]) -> None:
    client, _url, existing_token = ctx
    response = client.post(
        "/api/v1/projects/wrong-project/tokens",
        json={"name": "bad"},
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert response.status_code == 403


def test_list_tokens(ctx: tuple[TestClient, str, str]) -> None:
    client, _url, existing_token = ctx
    response = client.get(
        "/api/v1/projects/proj-auth/tokens",
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["tokens"]) >= 1
    names = {t["name"] for t in payload["tokens"]}
    assert "test-token" in names


def test_revoke_token(ctx: tuple[TestClient, str, str]) -> None:
    client, _url, existing_token = ctx

    # Create a new token
    create_resp = client.post(
        "/api/v1/projects/proj-auth/tokens",
        json={"name": "to-revoke"},
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert create_resp.status_code == 201
    new_token_id = create_resp.json()["id"]

    # Revoke it
    revoke_resp = client.post(
        f"/api/v1/projects/proj-auth/tokens/{new_token_id}/revoke",
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert revoke_resp.status_code == 200

    # Verify it's gone
    list_resp = client.get(
        "/api/v1/projects/proj-auth/tokens",
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert list_resp.status_code == 200
    ids = [t["id"] for t in list_resp.json()["tokens"]]
    assert new_token_id not in ids


def test_auth_required_for_run_create(ctx: tuple[TestClient, str, str]) -> None:
    """Authenticated run creation uses the token's project."""
    client, _url, existing_token = ctx
    from tests.test_specification import valid_document

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-auth", "specification": valid_document()},
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["project_id"] == "proj-auth"


def test_auth_rejects_wrong_project(ctx: tuple[TestClient, str, str]) -> None:
    """Token scoped to proj-auth cannot be used with a different project_id."""
    client, _url, existing_token = ctx

    # The body says project_id="different", but the token is for proj-auth
    from tests.test_specification import valid_document

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "different", "specification": valid_document()},
        headers={"Authorization": f"Bearer {existing_token}"},
    )
    # The auth check compares the body's project_id with the token's project_id
    assert response.status_code == 403


def test_missing_auth_still_works(ctx: tuple[TestClient, str, str]) -> None:
    """Without auth header, the endpoint works with the body's project_id."""
    client, _url, _token = ctx
    from tests.test_specification import valid_document

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-auth", "specification": valid_document()},
    )
    assert response.status_code == 202


def test_invalid_token_returns_403(ctx: tuple[TestClient, str, str]) -> None:
    client, _url, _token = ctx
    from tests.test_specification import valid_document

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-auth", "specification": valid_document()},
        headers={"Authorization": "Bearer mrds_invalid_token_abc123"},
    )
    assert response.status_code == 403


def test_malformed_auth_header_falls_back_to_body_project(ctx: tuple[TestClient, str, str]) -> None:
    """Non-Bearer auth headers are ignored — the body's project_id is used."""
    client, _url, _token = ctx
    from tests.test_specification import valid_document

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-auth", "specification": valid_document()},
        headers={"Authorization": "Basic not-bearer"},
    )
    assert response.status_code == 202
