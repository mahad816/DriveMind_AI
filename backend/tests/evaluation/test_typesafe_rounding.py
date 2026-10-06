"""Offline probability and paid-checkpoint regression; no network."""

from pathlib import Path
import json

import pytest

from app.routing.providers.jev import parse_answers
from app.routing.providers.probability_validation import validate_distribution
from evaluation.typesafe_replay import replay_checkpoint
from evaluation.typesafe_full import main
from tests.evaluation.test_jev_shadow import response
from tests.evaluation.test_typesafe_shadow import settings

CHECKPOINT = Path(__file__).parent / "fixtures/typesafe_first28_checkpoint.jsonl"


@pytest.mark.parametrize(
    "values", [(0.33, 0.33, 0.33), (0.34, 0.34, 0.33), (0.5, 0.25, 0.25), (0.501, 0.249, 0.25)]
)
def test_feasible_rounding(values: tuple[float, ...]) -> None:
    distribution: dict[str, float] = dict(zip(("a", "b", "c"), values, strict=True))
    validate_distribution(distribution, max(distribution, key=lambda k: distribution[k]))


@pytest.mark.parametrize(
    "distribution,selected",
    [
        ({"a": 0.2, "b": 0.2, "c": 0.2}, "a"),
        ({"a": 0.6, "b": 0.4}, "b"),
        ({"a": 0.501, "b": 0.499}, "b"),
    ],
)
def test_infeasible_or_nonmaximum(distribution: dict[str, float], selected: str) -> None:
    with pytest.raises(ValueError):
        validate_distribution(distribution, selected)


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), True, "0.5"])
def test_strict_probability_validation(value: object) -> None:
    raw = response()["answers"]
    raw["mode"]["probabilities"]["SINGLE"] = value
    with pytest.raises(ValueError):
        parse_answers(raw, rounding_aware=True)


def test_rounding_tie() -> None:
    validate_distribution({"a": 0.5, "b": 0.5}, "b")


def test_paid_replay_and_resume_preflight(capsys: pytest.CaptureFixture[str]) -> None:
    records = replay_checkpoint(CHECKPOINT, settings())
    assert len(records) == 28
    assert all(r["observation"]["status"] == "SUCCESS" for r in records)
    for case_id, mode in [
        ("routing-002", "SINGLE"),
        ("routing-003", "SINGLE"),
        ("routing-005", "CLARIFY"),
        ("routing-013", "CLARIFY"),
    ]:
        record = next(r for r in records if r["id"] == case_id)
        assert record["observation"]["prediction"]["mode"] == mode
    assert main(["--resume-from", str(CHECKPOINT)]) == 0
    output = capsys.readouterr().out
    assert '"maximum_posts": 92' in output
    assert '"next_case": "routing-029"' in output
    assert '"reused_existing": 28' in output
    assert "zero API calls" in output
    assert settings().typesafe_api_key.get_secret_value() not in json.dumps(records)


def test_changed_identity_rejected(tmp_path: Path) -> None:
    records = [json.loads(line) for line in CHECKPOINT.read_text().splitlines()]
    records[0]["identity"]["criteria_hash"] = "wrong"
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records))
    with pytest.raises(ValueError, match="mismatch"):
        replay_checkpoint(path, settings())


@pytest.mark.asyncio
async def test_resume_posts_only_remaining_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.routing.semantic import ProviderObservation, RoutingInput
    from evaluation.typesafe_full import run_full
    from evaluation.jev_runner import frozen_cases
    from evaluation.routing_runner import DEFAULT_DATASET

    sent: list[str] = []
    retained = replay_checkpoint(CHECKPOINT, settings())

    class FakeRouter:
        async def route(
            self, request: RoutingInput, *, idempotency_key: str
        ) -> ProviderObservation:
            sent.append(request.question)
            return ProviderObservation.model_validate(retained[0]["observation"])

    async def no_wait(_: float) -> None:
        pass

    monkeypatch.setattr("evaluation.typesafe_full.asyncio.sleep", no_wait)
    result, _ = await run_full(settings(), tmp_path, FakeRouter(), resume_from=CHECKPOINT)
    cases = frozen_cases(DEFAULT_DATASET)
    assert sent == [case.question for case in cases[28:]]
    assert len(sent) == 92
    assert result["operational"]["reused_existing"] == 28
    assert result["operational"]["new_decisions"] == 92
    assert result["operational"]["post_attempts"] == 92
