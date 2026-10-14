"""Real migration subprocesses must preserve encoded credentials without printing them."""

import asyncio
import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
async def migration_database():
    """Requires a disposable local admin connection and enforced TCP password auth."""
    raw = os.environ.get("SESSION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("SESSION_TEST_DATABASE_URL must name a disposable local database")
    url = make_url(raw)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("drivemind_session_test")
    ):
        pytest.fail("Refusing a non-isolated migration target", pytrace=False)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    role = "h1_" + uuid4().hex
    database = "drivemind_session_test_h1_" + uuid4().hex
    try:
        async with admin.connect() as db:
            await db.execute(text(f'CREATE ROLE "{role}" LOGIN'))
            await db.execute(text(f'CREATE DATABASE "{database}" OWNER "{role}"'))
        yield admin, url.set(username=role, database=database), role
    finally:
        async with admin.connect() as db:
            await db.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            await db.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        await admin.dispose()


async def set_password(admin, role, password):
    async with admin.connect() as db:
        # Keep the password out of SQL text, including failed-statement diagnostics.
        await db.execute(
            text("SELECT set_config('h1.password', :password, false)"), {"password": password}
        )
        await db.execute(
            text(
                "DO $$ BEGIN EXECUTE format('ALTER ROLE %I PASSWORD %L', "
                f"'{role}', current_setting('h1.password')); END $$"
            )
        )


async def migrate(url, *, invalid_port=False):
    raw = url.render_as_string(hide_password=False)
    if invalid_port:
        raw = raw.replace(f":{url.port}/", ":invalid/")
    env = os.environ | {"DATABASE_URL": raw, "DEMO_MODE": "false", "INDEXING_ENABLED": "false"}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "head",
        cwd=BACKEND,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    output = (stdout + stderr).decode(errors="replace")
    encoded = raw.split("@", 1)[0].split(":", 2)[-1]
    # Do not expose synthetic secrets even when this regression intentionally fails.
    if any(value and value in output for value in (raw, url.password, encoded)):
        pytest.fail("Migration subprocess exposed database credentials", pytrace=False)
    return process.returncode, output


@pytest.mark.parametrize("reserved", [True, False], ids=["reserved-password", "plain-password"])
async def test_migrations_preserve_password_and_do_not_leak(migration_database, reserved):
    admin, url, role = migration_database
    password = secrets.token_hex(24) + ("%@#/:" if reserved else "")
    await set_password(admin, role, password)
    url = url.set(password=password)
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.connect() as db:
            version = await db.scalar(text("SHOW server_version"))
            assert version.split(".", 1)[0] in {"16", "18"}
            assert await db.scalar(text("SELECT current_user")) == role
        code, _ = await migrate(url)
        assert code == 0, "Migration failed; output withheld to protect credentials"
        async with engine.connect() as db:
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version")) == "20261015_1200"
            )
            assert await db.scalar(text("SELECT count(*) FROM conversations")) == 0
            assert await db.scalar(text("SELECT count(*) FROM conversation_turns")) == 0
        # Already-at-head is also a valid plain/encoded URL connection path.
        code, _ = await migrate(url)
        assert code == 0, "Repeated migration failed; output withheld"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("fault", ["wrong-password", "invalid-port"])
async def test_invalid_configuration_fails_without_credentials(migration_database, fault):
    admin, url, role = migration_database
    password = secrets.token_hex(24) + "%@#/:"
    await set_password(admin, role, password)
    url = url.set(password=password)
    if fault == "wrong-password":
        url = url.set(password=password + "wrong")
    code, output = await migrate(url, invalid_port=fault == "invalid-port")
    assert code != 0
    assert "invalid interpolation syntax" not in output
    assert ("InvalidPasswordError" if fault == "wrong-password" else "invalid") in output
    async with admin.connect() as db:
        assert not await db.scalar(
            text(
                "SELECT EXISTS(SELECT FROM pg_stat_activity WHERE datname=:name AND state='active')"
            ),
            {"name": url.database},
        )
