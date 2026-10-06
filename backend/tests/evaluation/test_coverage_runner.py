"""Development runner safety and exact checkpoint reuse. Mock HTTP only."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.routing.providers.typesafe import TypeSafeSettings
from app.routing.v2.coverage.providers.typesafe_coverage import TypeSafeCoverageVerifier
from evaluation.coverage_runner import evaluate_case, preflight, run, save


class Settings(TypeSafeSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


@pytest.mark.asyncio
async def test_retained_valid_call_reused_exactly(tmp_path: Path) -> None:
    calls = []

    def mock(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert set(json.loads(request.content)["questions"]) == {"COVERAGE"}
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "answers": {
                    "COVERAGE": {
                        "type": "choice",
                        "choice": "MISMATCH",
                        "confidence": 0.95,
                        "probabilities": {"PRESERVED": 0.03, "MISMATCH": 0.95, "UNCERTAIN": 0.02},
                    }
                },
            },
        )

    cases, _ = preflight()
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        verifier = TypeSafeCoverageVerifier(
            Settings(typesafe_api_key=SecretStr("unit-only-secret")), client
        )
        first, reused = await evaluate_case(verifier, cases[0], tmp_path, "fixed")
        assert not reused
        second, reused = await evaluate_case(verifier, cases[0], tmp_path, "fixed")
        assert reused and first == second and len(calls) == 1
        with pytest.raises(ValueError, match="MISMATCH"):
            await evaluate_case(verifier, cases[0], tmp_path, "different-run")
        assert len(calls) == 1
    assert all("unit-only-secret" not in p.read_text() for p in tmp_path.iterdir())


@pytest.mark.asyncio
async def test_held_out_rejected_before_http(tmp_path: Path) -> None:
    cases, _ = preflight()
    forbidden = cases[0].model_copy(update={"split": "held_out"})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("held-out POST"))
    ) as client:
        with pytest.raises(ValueError, match="HELD_OUT_FORBIDDEN"):
            await evaluate_case(
                TypeSafeCoverageVerifier(Settings(typesafe_api_key=SecretStr("test")), client),
                forbidden,
                tmp_path,
                "fixed",
            )
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_unknown_paid_outcome_not_reposted(tmp_path: Path) -> None:
    cases, _ = preflight()
    case = cases[0]
    save(tmp_path / (case.id + ".pending.json"), {"pending": True})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("repeat POST"))
    ) as client:
        with pytest.raises(ValueError, match="UNRESOLVED_POST"):
            await evaluate_case(
                TypeSafeCoverageVerifier(Settings(typesafe_api_key=SecretStr("test")), client),
                case,
                tmp_path,
                "fixed",
            )


@pytest.mark.asyncio
async def test_dry_run_and_development_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    cases, info = preflight()
    assert len(cases) == 32 and all(c.split == "development" for c in cases)
    assert (
        info["targets"]["false_preserved_max"] == 0
        and info["targets"]["preserved_recall_min"] == 0.90
    )

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("POST")

    monkeypatch.setattr(TypeSafeCoverageVerifier, "verify", forbidden)
    assert await run(False) is None
