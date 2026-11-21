"""M0-SEC ticket 08: cross-site forgery of ``POST /chat`` in normal (Owner) mode.

Real PostgreSQL (disposable), real application sessions, the mounted route and a counting fake
provider that calls ``mark_paid_started()`` the way each provider chokepoint does. A forged request
"succeeds" when the fake provider was reached. No network, no key, no paid call.

What a browser can and cannot do is modelled by the request shapes below:

* a cross-site HTML form or ``fetch(..., {mode: "no-cors"})`` can only send a *simple* request:
  ``application/x-www-form-urlencoded``, ``multipart/form-data`` or ``text/plain`` bodies, no custom
  header (so no ``X-CSRF-Token``), and an ``Origin`` header naming the attacker (or ``null``);
* an ``application/json`` body or a custom header needs a CORS preflight, which the backend (no CORS
  middleware) never approves, so a cross-origin page cannot send them from a browser;
* a same-site attacker (for example a sibling subdomain) can make the browser attach the session
  cookie, but cannot choose the ``Origin`` header or read the CSRF token.

The tests with a valid session cookie therefore assert what the *server* does with each forged shape,
independently of what the browser would attach.
"""

import pytest
from sqlalchemy import func, select
from starlette.responses import Response

from app.db.models import QueryHistory
from app.security.session_helpers import session_cookie_policy, set_session_cookie
from .conftest import USER_A, USER_B
from .test_conversation_api import api, world
from .test_paid_question_routes import CHAT, ask, ledger, meter

__all__ = ["api", "world", "meter"]

ATTACKER = "https://attacker.example.invalid"
JSON_TEXT = '{"question": "forged question"}'


def cookie_only(api):
    """What a same-site forgery carries: the session cookie, nothing else the attacker controls."""
    return {"Cookie": api.headers[USER_A]["Cookie"]}


async def history_rows(api) -> int:
    async with api.world.sessions() as db:
        return int(await db.scalar(select(func.count()).select_from(QueryHistory)) or 0)


async def post_forged(api, headers, *, content=None, json=None):
    return await api.client.post(CHAT, headers=headers, content=content, json=json)


# --- legitimate request ---------------------------------------------------------------------


async def test_a_legitimate_request_with_origin_cookie_and_token_still_answers(api, meter):
    response = await ask(api, "chat")
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Canonical answer"
    assert meter.calls == ["A question"]
    assert len(await ledger(api)) == 1


# --- Origin ---------------------------------------------------------------------------------


async def test_missing_origin_is_refused_before_any_provider_call(api, meter):
    headers = {k: v for k, v in api.headers[USER_A].items() if k != "Origin"}
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []
    assert await ledger(api) == []


@pytest.mark.parametrize(
    "kind", ["attacker", "null", "suffix-host", "wrong-scheme", "empty", "trailing-path"]
)
async def test_a_wrong_origin_is_refused_before_any_provider_call(api, meter, kind):
    trusted = api.settings.frontend_url  # derived, so a settings change cannot make a case vacuous
    host = trusted.split("://", 1)[1]
    origin = {
        "attacker": ATTACKER,
        "null": "null",
        "suffix-host": f"https://{host}.attacker.example.invalid",
        "wrong-scheme": f"http://{host}",
        "empty": "",
        "trailing-path": trusted + "/evil",
    }[kind]
    headers = {**api.headers[USER_A], "Origin": origin}
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []
    assert await ledger(api) == []


async def test_a_duplicate_origin_header_is_refused_even_if_one_value_is_right(api, meter):
    headers = [
        ("Origin", api.settings.frontend_url),
        ("Origin", ATTACKER),
        ("X-CSRF-Token", api.headers[USER_A]["X-CSRF-Token"]),
        ("Cookie", api.headers[USER_A]["Cookie"]),
    ]
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []


# --- CSRF token -----------------------------------------------------------------------------


async def test_a_missing_csrf_token_is_refused_before_any_provider_call(api, meter):
    headers = {k: v for k, v in api.headers[USER_A].items() if k != "X-CSRF-Token"}
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []
    assert await ledger(api) == []


@pytest.mark.parametrize("token", ["not-the-token", "", "A" * 43])
async def test_an_invalid_csrf_token_is_refused_before_any_provider_call(api, meter, token):
    headers = {**api.headers[USER_A], "X-CSRF-Token": token}
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []
    assert await ledger(api) == []


async def test_another_sessions_csrf_token_is_refused(api, meter):
    headers = {**api.headers[USER_A], "X-CSRF-Token": api.headers[USER_B]["X-CSRF-Token"]}
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []


# --- forged "simple" cross-site requests (what a form or no-cors fetch can send) --------------


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded"],
)
async def test_a_forged_simple_request_with_the_cookie_never_reaches_the_provider(
    api, meter, content_type
):
    """The session cookie plus the attacker's Origin and no token: refused, nothing spent."""
    headers = {**cookie_only(api), "Origin": ATTACKER, "Content-Type": content_type}
    before = await history_rows(api)
    response = await post_forged(api, headers, content=JSON_TEXT)
    assert response.status_code == 403, response.text
    assert meter.calls == []
    assert await ledger(api) == []
    assert await history_rows(api) == before


async def test_a_forged_json_request_with_only_the_cookie_is_refused(api, meter):
    """A same-site or non-browser forgery that sends valid JSON and the cookie, no Origin, no token."""
    response = await post_forged(api, cookie_only(api), json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []
    assert await ledger(api) == []


async def test_a_forged_request_with_the_attackers_origin_and_the_cookie_is_refused(api, meter):
    headers = {**cookie_only(api), "Origin": ATTACKER}
    response = await post_forged(api, headers, json={"question": "forged"})
    assert response.status_code == 403, response.text
    assert meter.calls == []


# --- cookie behaviour a browser relies on ---------------------------------------------------


async def test_the_session_cookie_is_host_only_secure_and_lax_so_it_is_not_sent_cross_site(api):
    """The cookie attributes the assessment relies on (``__Host-`` prefix, Secure, Lax, no Domain)."""
    policy = session_cookie_policy(api.settings)
    assert policy.name == "__Host-drivemind-session" and policy.secure
    session = api.issued[USER_A]
    response = Response()
    set_session_cookie(
        response,
        credential=session.credential,
        expires_at=session.expires_at,
        settings=api.settings,
    )
    attributes = response.headers["set-cookie"].lower()
    assert attributes.startswith("__host-drivemind-session=")
    for required in ("samesite=lax", "secure", "httponly", "path=/"):
        assert required in attributes
    assert "domain=" not in attributes


# --- no CORS: a cross-origin page cannot pass the preflight a JSON or custom-header request needs


async def test_there_is_no_cors_approval_for_a_cross_origin_preflight(api):
    response = await api.client.options(
        CHAT,
        headers={
            "Origin": ATTACKER,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


async def test_a_successful_response_carries_no_cors_headers(api, meter):
    response = await ask(api, "chat")
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
