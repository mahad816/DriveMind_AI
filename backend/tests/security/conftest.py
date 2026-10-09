"""Only explicitly configured disposable loopback PostgreSQL may be used."""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import insert, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.models.user import User

USER_A = UUID(int=101)
USER_B = UUID(int=102)
DEMO_USER = UUID(int=103)
BASE_REVISION = "20260708_1400"
SESSION_REVISION = "20261009_1200"
BACKEND = Path(__file__).resolve().parents[2]


def apply_revision(connection: Connection, revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)
    module = scripts.get_revision(revision).module
    with Operations.context(MigrationContext.configure(connection)):
        if downgrade:
            module.downgrade()
        else:
            module.upgrade()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    return Settings(
        demo_mode=False,
        app_env="production",
        debug=False,
        frontend_url="https://app.example.invalid",
        demo_user_id=str(DEMO_USER),
    )


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    raw = os.environ.get("SESSION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("SESSION_TEST_DATABASE_URL must name an isolated local test database")
    url = make_url(raw)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("drivemind_session_test")
    ):
        pytest.fail("Refusing a non-isolated PostgreSQL test database", pytrace=False)
    schema = "session_test_" + uuid4().hex
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("path_separator", "os")
            scripts = ScriptDirectory.from_config(config)
            for revision in reversed(list(scripts.walk_revisions("base", BASE_REVISION))):
                await connection.run_sync(apply_revision, revision.revision)
            await connection.execute(
                insert(User),
                [
                    {"id": USER_A, "email": "a@example.invalid", "google_id": "verified-subject-a"},
                    {"id": USER_B, "email": "b@example.invalid", "google_id": "verified-subject-b"},
                    {
                        "id": DEMO_USER,
                        "email": "demo@example.invalid",
                        "google_id": "demo:synthetic",
                    },
                ],
            )
            await connection.run_sync(apply_revision, SESSION_REVISION)
        yield engine
    finally:
        try:
            async with engine.begin() as connection:
                # Generated schema only, never public or an existing datastore's schema.
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()
