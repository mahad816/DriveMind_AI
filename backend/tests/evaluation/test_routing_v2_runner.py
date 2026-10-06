"""Offline stage journaling and exact-identity resume safety."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2.preparation import prepare, PreparedEnvelope
from app.routing.v2.questions import stage1_questions
from evaluation.routing_v2_runner import JournalRouter, run, save


class IsolatedSettings(TypeSafeSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def settings() -> TypeSafeSettings:
    return IsolatedSettings(typesafe_api_key=SecretStr("unit-only-secret"))


def response(questions: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 20, "output_tokens": 10},
        "answers": {
            name: {
                "type": "choice",
                "choice": next(iter(q["criteria"])),
                "confidence": 1,
                "probabilities": {k: int(i == 0) for i, k in enumerate(q["criteria"])},
            }
            for name, q in questions.items()
        },
    }


@pytest.mark.asyncio
async def test_stage_reuse_avoids_second_post_and_excludes_secret(tmp_path: Path) -> None:
    calls = []

    def mock(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=response(json.loads(request.content)["questions"]))

    envelope = prepare("Explain service identities")
    assert isinstance(envelope, PreparedEnvelope)
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        router = JournalRouter(settings(), client, tmp_path, "fixed")
        router.case_id = "v2-001"
        first = await router.stage(envelope, stage1_questions(), 1, execute=True)
        second = await router.stage(envelope, stage1_questions(), 1, execute=True)
        assert first == second and len(calls) == 1
        assert (
            router.accounting["new_stage1_posts"] == 1 and router.accounting["reused_stage1"] == 1
        )
        assert all("unit-only-secret" not in p.read_text() for p in tmp_path.iterdir())
        router.run_identity = "changed"
        with pytest.raises(ValueError, match="INCOMPATIBLE"):
            await router.stage(envelope, stage1_questions(), 1, execute=True)
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_unresolved_pending_post_never_repeated(tmp_path: Path) -> None:
    envelope = prepare("Explain service identities")
    assert isinstance(envelope, PreparedEnvelope)
    save(tmp_path / "v2-001.stage1.pending.json", {"identity": "pending"})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("POST repeated"))
    ) as client:
        router = JournalRouter(settings(), client, tmp_path, "fixed")
        router.case_id = "v2-001"
        with pytest.raises(ValueError, match="UNRESOLVED_POST"):
            await router.stage(envelope, stage1_questions(), 1, execute=True)


@pytest.mark.asyncio
async def test_stage2_failure_reuses_paid_stage1_and_stage2(tmp_path: Path) -> None:
    calls = []

    def mock(request: httpx.Request) -> httpx.Response:
        questions = json.loads(request.content)["questions"]
        calls.append(questions)
        return (
            httpx.Response(200, json=response(questions))
            if "STRUCTURE" in questions
            else httpx.Response(529)
        )

    envelope = prepare("Explain service identities")
    assert isinstance(envelope, PreparedEnvelope)
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        router = JournalRouter(settings(), client, tmp_path, "fixed")
        router.case_id = "v2-001"
        first = await router.interpret(envelope, execute=True)
        second = await router.interpret(envelope, execute=True)
        assert first.status == second.status == "STAGE2_PROVIDER_ERROR"
        assert len(calls) == 2
        assert router.accounting["reused_stage1"] == router.accounting["reused_stage2"] == 1


@pytest.mark.asyncio
async def test_default_dry_run_zero_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("live provider called")

    monkeypatch.setattr(JournalRouter, "stage", forbidden)
    assert await run() is None
