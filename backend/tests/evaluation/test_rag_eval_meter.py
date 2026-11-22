"""The cost meter is what enforces the spend cap, so it is tested against fake SDK calls."""

from types import SimpleNamespace
from typing import Any

import pytest
from openai.resources.chat.completions import AsyncCompletions

from evaluation.rag_eval.meter import (
    BudgetExceeded,
    CostMeter,
    UnpricedModel,
    cost_of,
    label_var,
    price_for,
)


async def sdk_create(*args: Any, **kwargs: Any) -> Any:
    """Call whatever is currently installed as the SDK method, with fake arguments."""
    method: Any = AsyncCompletions.create
    return await method(*args, **kwargs)


def response(model: str, inp: int, out: int, cached: int = 0):
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=inp,
            completion_tokens=out,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        ),
    )


def test_cost_uses_the_checked_prices():
    # 1M input + 1M output on gpt-5.4-nano = 0.20 + 1.25
    assert cost_of("gpt-5.4-nano", 1_000_000, 1_000_000) == pytest.approx(1.45)
    # cached input is billed at the cached rate, only the remainder at the full rate
    assert cost_of("gpt-5.4-nano", 1_000_000, 0, cached_tokens=400_000) == pytest.approx(
        0.6 * 0.20 + 0.4 * 0.02
    )


def test_dated_model_names_resolve_to_the_most_specific_price():
    assert price_for("gpt-5.4-mini-2026-03-17") == price_for("gpt-5.4-mini")
    assert price_for("gpt-5.4-mini-2026-03-17") != price_for("gpt-5.4")
    assert price_for("gpt-5.4-nano-2026-03-17")["input"] == 0.20


def test_unknown_model_is_an_error_not_free():
    with pytest.raises(KeyError, match="no price recorded"):
        price_for("gpt-99-imaginary")
    with pytest.raises(
        UnpricedModel
    ):  # stops the run; a plain KeyError would be swallowed by the app
        CostMeter(1.0).record(response("gpt-99-imaginary", 10, 10))


def test_totals_are_split_by_label_and_model():
    meter = CostMeter(3.0)
    token = label_var.set("tool_agent")
    try:
        meter.record(response("gpt-5.4-nano-2026-03-17", 1000, 100))
        meter.record(response("gpt-5.4-nano-2026-03-17", 1000, 100))
    finally:
        label_var.reset(token)
    label_var.set("judge")
    meter.record(response("gpt-5.4-mini-2026-03-17", 500, 50))
    rows = {(r["label"], r["model"]): r for r in meter.summary()["by_label_and_model"]}
    assert rows[("tool_agent", "gpt-5.4-nano-2026-03-17")]["calls"] == 2
    assert rows[("judge", "gpt-5.4-mini-2026-03-17")]["input_tokens"] == 500
    assert meter.summary()["estimated_total_usd"] == pytest.approx(meter.total, abs=1e-5)


def test_cap_blocks_the_next_call_but_never_cuts_one_in_flight():
    meter = CostMeter(0.001)
    meter.check()  # fine while under the cap
    meter.record(response("gpt-5.4-nano", 5_000, 500))  # pushes it over
    with pytest.raises(BudgetExceeded):
        meter.check()


async def test_installed_meter_wraps_the_real_sdk_methods_and_restores_them(monkeypatch):
    calls = []

    async def fake_create(self, *args, **kwargs):
        calls.append(kwargs)
        return response("gpt-5.4-nano", 100, 10)

    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    meter = CostMeter(3.0)
    with meter.installed():
        assert AsyncCompletions.create is not fake_create
        await sdk_create(SimpleNamespace(), model="gpt-5.4-nano")
    assert AsyncCompletions.create is fake_create  # restored exactly
    assert len(calls) == 1 and meter.total > 0


async def test_installed_meter_stops_calls_after_the_cap(monkeypatch):
    async def fake_create(self, *args, **kwargs):
        return response("gpt-5.4-nano", 10_000_000, 0)  # $2 per call

    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    meter = CostMeter(3.0)
    with meter.installed():
        await sdk_create(SimpleNamespace())
        await sdk_create(SimpleNamespace())  # total $4.00, over the cap
        with pytest.raises(BudgetExceeded):
            await sdk_create(SimpleNamespace())
