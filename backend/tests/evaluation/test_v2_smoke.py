"""Offline frozen-smoke preparation and continuation policy."""

import pytest

from evaluation.v2_smoke_fixture import fixture_hash, load_fixtures
from evaluation.v2_smoke_runner import FROZEN_HASH, preflight, run, system_failure


def test_frozen_fifteen_inputs() -> None:
    assert fixture_hash() == FROZEN_HASH
    assert len(load_fixtures().cases) == 15
    info = preflight()
    assert len(info["cases"]) == 15
    assert info["maximum_posts"] == 30
    assert info["model"] == "jev-latest"


@pytest.mark.asyncio
async def test_dry_run_never_calls_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("provider called")

    monkeypatch.setattr("evaluation.v2_smoke_runner.TypeSafeV2Router.interpret", forbidden)
    assert await run(False) is None


@pytest.mark.parametrize(
    "error",
    ["DUPLICATE_OPTION_SELECTION", "DUPLICATE_SEMANTIC_PROVENANCE", "REQUEST_ORDER_REVERSED"],
)
def test_semantic_selection_errors_continue(error: str) -> None:
    assert not system_failure("DOMAIN_TRANSLATION_ERROR", error)


@pytest.mark.parametrize(
    "status",
    [
        "STAGE1_INVALID_RESPONSE",
        "STAGE2_INVALID_RESPONSE",
        "STAGE1_PROVIDER_ERROR",
        "PREPARATION_ERROR",
    ],
)
def test_infrastructure_errors_stop(status: str) -> None:
    assert system_failure(status, "INVALID")


def test_unknown_translation_error_stops() -> None:
    assert system_failure("DOMAIN_TRANSLATION_ERROR", "UNKNOWN_LOCAL_BUG")
