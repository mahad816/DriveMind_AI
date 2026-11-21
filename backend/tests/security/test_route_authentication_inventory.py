"""Inventory of every mounted route and the authentication it requires (M0 ticket 04).

Protective tests: all of them pass today and fail when someone adds, removes or re-wires a route
without updating ``EXPECTED``, so the route table below is a reviewed, executable inventory.

Why this file exists: a former test in ``tests/security/test_session_security.py`` (removed by M0-SEC
ticket 09) looped over ``app.routes`` looking
for ``APIRoute`` objects. With the pinned FastAPI (0.139) ``app.routes`` holds only the documentation
routes and one lazy ``_IncludedRouter``, so that loop checks nothing. This file enumerates the routers
through their public ``APIRouter.routes`` and cross-checks the result against ``app.openapi()``, and
refuses to pass when the two enumerations disagree or are empty.

No database, Google, Qdrant or OpenAI is used: the database dependency is a mock that fails the test
if any route touches it before refusing the request.
"""

import ast
import importlib
import pkgutil
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import APIRouter
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

import app.api as api_package
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app

BACKEND = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND / "app"
PREFIX = "/api/v1"
DEMO_USER = UUID(int=103)
SOME_ID = UUID(int=7)

# Dependencies that decide who may call a route. Names are matched on the callable's __name__.
AUTH_DEPENDENCIES = frozenset(
    {
        "require_normal_mode",
        "require_resource_user",
        "require_chat_user",
        "require_demo_index",
        "require_index_user",
        "require_index_read_user",
        "require_application_principal",
        "require_session_mutation",
        "require_session_logout",
        "require_conversation_mutation",
        "require_session_login_enabled",
    }
)

PUBLIC = frozenset[str]()
# /files and /sources: a session principal in normal mode; anonymous (synthetic corpus) in demo.
RESOURCE = frozenset({"require_resource_user", "require_demo_index"})
# POST /chat: the resource check plus Origin and CSRF in normal mode (M0-SEC ticket 08).
CHAT = frozenset({"require_chat_user", "require_resource_user", "require_demo_index"})
INDEX_MUTATION = frozenset({"require_index_user", "require_normal_mode"})
INDEX_READ = frozenset({"require_index_read_user"})
CONVERSATION_READ = frozenset({"require_application_principal", "require_normal_mode"})
CONVERSATION_MUTATION = frozenset({"require_conversation_mutation", "require_normal_mode"})
LOGIN_FLAG = frozenset({"require_session_login_enabled"})
SESSION_READ = frozenset({"require_session_login_enabled", "require_application_principal"})
SESSION_MUTATION = frozenset({"require_session_login_enabled", "require_session_mutation"})
SESSION_LOGOUT = frozenset({"require_session_login_enabled", "require_session_logout"})

CONVERSATION = "/conversations/{conversation_id}"
# (method, path under /api/v1) -> the authentication dependencies the route must carry.
EXPECTED: dict[tuple[str, str], frozenset[str]] = {
    ("GET", "/health"): PUBLIC,
    ("GET", "/health/ready"): PUBLIC,
    ("GET", "/health/indexing"): PUBLIC,
    ("POST", "/auth/session/google"): LOGIN_FLAG,
    ("GET", "/auth/session/google/callback"): LOGIN_FLAG,
    ("GET", "/auth/session"): SESSION_READ,
    ("POST", "/auth/session/logout"): SESSION_LOGOUT,
    ("POST", "/index/sync"): INDEX_MUTATION,
    ("POST", "/index/ingest"): INDEX_MUTATION,
    ("POST", "/index/chunk"): INDEX_MUTATION,
    ("POST", "/index/build"): INDEX_MUTATION,
    ("GET", "/index/status"): INDEX_READ,
    ("GET", "/index/pending"): INDEX_READ,
    ("GET", "/files"): RESOURCE,
    ("GET", "/files/{file_id}/content"): RESOURCE,
    ("POST", "/chat"): CHAT,
    ("GET", "/sources/{chunk_id}"): RESOURCE,
    ("POST", "/conversations"): CONVERSATION_MUTATION,
    ("GET", "/conversations"): CONVERSATION_READ,
    ("GET", CONVERSATION): CONVERSATION_READ,
    ("PATCH", CONVERSATION): CONVERSATION_MUTATION,
    ("DELETE", CONVERSATION): CONVERSATION_MUTATION,
    ("POST", CONVERSATION + "/turns"): CONVERSATION_MUTATION,
    ("POST", CONVERSATION + "/turns/stream"): CONVERSATION_MUTATION,
    ("GET", CONVERSATION + "/turns/{turn_id}"): CONVERSATION_READ,
    ("POST", CONVERSATION + "/turns/{turn_id}/interrupt"): CONVERSATION_MUTATION,
}

# The legacy Google OAuth router is defined but must stay unmounted (nothing else may import it).
UNMOUNTED_ROUTER_MODULES = {"app.api.auth"}


def _dependency_names(dependant: Dependant) -> set[str]:
    names = {getattr(dependant.call, "__name__", "")}
    for child in dependant.dependencies:
        names |= _dependency_names(child)
    return names


def _router_modules() -> dict[str, APIRouter]:
    modules: dict[str, APIRouter] = {}
    for info in pkgutil.iter_modules(api_package.__path__):
        module = importlib.import_module(f"app.api.{info.name}")
        # app.api.router only aggregates the others; it defines no routes of its own.
        if hasattr(module, "router") and info.name != "router":
            modules[module.__name__] = module.router
    return modules


def _defined_routes(*, mounted_only: bool) -> dict[tuple[str, str], frozenset[str]]:
    """Every APIRoute of the routers defined in app/api, with its authentication dependencies."""
    found: dict[tuple[str, str], frozenset[str]] = {}
    for name, router in _router_modules().items():
        if mounted_only and name in UNMOUNTED_ROUTER_MODULES:
            continue
        for route in router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods or ():
                    found[(method, route.path)] = frozenset(
                        _dependency_names(route.dependant) & AUTH_DEPENDENCIES
                    )
    return found


def _mounted_operations() -> set[tuple[str, str]]:
    schema = create_app().openapi()["paths"]
    return {
        (method.upper(), path.removeprefix(PREFIX))
        for path, operations in schema.items()
        for method in operations
    }


def test_the_mounted_operations_are_exactly_the_reviewed_inventory() -> None:
    mounted = _mounted_operations()
    assert mounted, "no mounted operations were found: the enumeration is broken"
    assert mounted == set(EXPECTED), (
        f"unreviewed routes: {sorted(mounted - set(EXPECTED))}; "
        f"routes that disappeared: {sorted(set(EXPECTED) - mounted)}"
    )


def test_every_mounted_route_carries_the_authentication_the_inventory_expects() -> None:
    defined = _defined_routes(mounted_only=True)
    assert set(defined) == _mounted_operations(), (
        "a router defined in app/api is not mounted, or a mounted route is not defined there"
    )
    wrong = {
        key: (sorted(defined[key]), sorted(expected))
        for key, expected in EXPECTED.items()
        if defined[key] != expected
    }
    assert not wrong, f"authentication differs from the inventory (found, expected): {wrong}"


def test_only_the_retired_google_router_is_defined_but_unmounted() -> None:
    mounted = _mounted_operations()
    unmounted_modules = set()
    for name, router in _router_modules().items():
        paths = {
            (method, route.path)
            for route in router.routes
            if isinstance(route, APIRoute)
            for method in route.methods or ()
        }
        assert paths, f"{name} defines a router without routes: the enumeration is broken"
        if not paths & mounted:
            unmounted_modules.add(name)
    assert unmounted_modules == UNMOUNTED_ROUTER_MODULES


def test_nothing_in_the_application_imports_the_retired_google_router() -> None:
    importers = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = {node.module} | {f"{node.module}.{alias.name}" for alias in node.names}
            elif isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            else:
                continue
            if "app.api.auth" in imported:
                importers.append(str(path.relative_to(BACKEND)))
    assert importers == [], f"modules import the unmounted legacy OAuth router: {importers}"


# --- Behaviour without credentials ---------------------------------------------------------------

_IDS = {
    "{conversation_id}": str(SOME_ID),
    "{turn_id}": str(SOME_ID),
    "{file_id}": str(SOME_ID),
    "{chunk_id}": str(SOME_ID),
}


def _url(path: str) -> str:
    for placeholder, value in _IDS.items():
        path = path.replace(placeholder, value)
    return PREFIX + path


def _refused_database() -> MagicMock:
    # Any await on this mock raises TypeError, so the response would be a 500 instead of the
    # expected 401/403/404 and the test would fail.
    return MagicMock(name="database that must not be queried")


@pytest.fixture
def settings_for(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)

    def build(**values: object) -> Settings:
        return Settings(**values)  # type: ignore[arg-type]

    return build


def _client(settings: Settings) -> AsyncClient:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db] = _refused_database
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver")


NEEDS_SESSION = sorted(
    key for key, auth in EXPECTED.items() if auth and not key[1].startswith("/auth/")
)
LOGIN_ROUTES = sorted(key for key in EXPECTED if key[1].startswith("/auth/"))


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", NEEDS_SESSION, ids=[f"{m} {p}" for m, p in NEEDS_SESSION])
async def test_normal_mode_without_a_session_cookie_is_refused_before_any_data_access(
    settings_for, method: str, path: str
) -> None:
    async with _client(settings_for(demo_mode=False)) as client:
        response = await client.request(method, _url(path))
    assert response.status_code == 401, response.text
    assert response.headers.get("set-cookie") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", LOGIN_ROUTES, ids=[f"{m} {p}" for m, p in LOGIN_ROUTES])
async def test_session_endpoints_do_not_exist_while_the_session_flag_is_off(
    settings_for, method: str, path: str
) -> None:
    settings = settings_for(demo_mode=False)
    assert settings.google_application_sessions_enabled is False  # the shipped default
    async with _client(settings) as client:
        response = await client.request(method, _url(path))
    assert response.status_code == 404, response.text
    assert response.headers.get("set-cookie") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", LOGIN_ROUTES, ids=[f"{m} {p}" for m, p in LOGIN_ROUTES])
async def test_session_endpoints_are_forbidden_in_demo_mode_even_with_the_flag_on(
    settings_for, method: str, path: str
) -> None:
    settings = settings_for(
        demo_mode=True, demo_user_id=str(DEMO_USER), google_application_sessions_enabled=True
    )
    async with _client(settings) as client:
        response = await client.request(method, _url(path))
    assert response.status_code == 403, response.text


DEMO_BLOCKED = sorted(key for key, auth in EXPECTED.items() if "require_normal_mode" in auth)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", DEMO_BLOCKED, ids=[f"{m} {p}" for m, p in DEMO_BLOCKED])
async def test_demo_visitors_cannot_reach_indexing_or_conversations(
    settings_for, method: str, path: str
) -> None:
    async with _client(settings_for(demo_mode=True, demo_user_id=str(DEMO_USER))) as client:
        response = await client.request(method, _url(path))
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "This operation is unavailable in public demo mode."}


def test_demo_blocked_routes_are_exactly_indexing_mutations_and_conversations() -> None:
    expected = {
        key
        for key in EXPECTED
        if key[1].startswith("/conversations")
        or (key[0] == "POST" and key[1].startswith("/index/"))
    }
    assert set(DEMO_BLOCKED) == expected


def test_the_hosted_entrypoint_disables_the_access_log() -> None:
    """OAuth callback URLs carry ``code`` and ``state`` in the query string; uvicorn's access log
    would record them. ``deploy/start.sh`` is the Dockerfile CMD (Railway)."""
    script = (BACKEND / "deploy" / "start.sh").read_text(encoding="utf-8")
    command = next(line for line in script.splitlines() if "uvicorn" in line)
    assert "--no-access-log" in script.replace("\\\n", " "), command
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["sh", "deploy/start.sh"]' in dockerfile
    assert "DEBUG=false" in dockerfile and "DEMO_MODE=false" in dockerfile


@pytest.fixture
def login_enabled(settings_for) -> Settings:
    """The flag on, with a valid login configuration, so the session endpoints exist."""
    frontend = "https://app.example.invalid"
    return settings_for(
        demo_mode=False,
        app_env="production",
        debug=False,
        frontend_url=frontend,
        google_application_sessions_enabled=True,
        google_session_redirect_uri=frontend + "/api/v1/auth/session/google/callback",
        google_client_id="synthetic-client",
        google_client_secret="synthetic-client-secret",
    )


@pytest.mark.asyncio
async def test_with_the_flag_on_inspecting_a_session_without_a_cookie_is_401(
    login_enabled: Settings,
) -> None:
    async with _client(login_enabled) as client:
        response = await client.get(PREFIX + "/auth/session")
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_with_the_flag_on_logout_checks_origin_and_csrf_before_the_cookie(
    login_enabled: Settings,
) -> None:
    token = "A" * 43  # well-formed, matches nothing
    async with _client(login_enabled) as client:
        bare = await client.post(PREFIX + "/auth/session/logout")
        no_csrf = await client.post(
            PREFIX + "/auth/session/logout", headers={"Origin": login_enabled.frontend_url}
        )
        no_cookie = await client.post(
            PREFIX + "/auth/session/logout",
            headers={"Origin": login_enabled.frontend_url, "X-CSRF-Token": token},
        )
    assert (bare.status_code, no_csrf.status_code) == (403, 403)
    assert no_cookie.status_code == 401
