"""M1-08-F: cost controls of the paid evaluation commands (all free: fakes and tripwires, no provider call).

What is established here, and what is not:

* every model the evaluation can call has a recorded price, and a missing price refuses before any spend;
* every cap decision uses the full-precision estimate (an estimate below a rounding step must not read as zero);
* the first-step probe's client does not retry by itself, its chat requests carry an output-token limit, and a response
  without a usage block stops the run instead of counting as free;
* the plan states these safeguards and the resulting ceiling honestly (cap + one call), and never calls the cap a hard
  limit.

Not established here (needs a paid call, see ticket 08): that the provider accepts ``max_completion_tokens`` for the
chat model, that the chat model does not reason beyond the limit, and what a failed request is billed.
"""

import asyncio
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from evaluation.rag_eval import (
    embedding_estimate,
    meter,
    probe_pools,
)
from evaluation.rag_eval import first_step_probe as fsp
from evaluation.rag_eval.judge import JUDGE_MODEL
from evaluation.rag_eval.meter import (
    CostMeter,
    UnmeteredRequest,
    UnpricedModel,
    price_for,
    refuse_over_cap,
    require_prices,
)

RAG_EVAL = Path(meter.__file__).parent
PRICES = json.loads((RAG_EVAL / "prices.json").read_text())


# ---- the price table -------------------------------------------------------------------------------------


def test_the_price_table_records_its_source_and_dates():
    assert PRICES["source"].startswith("https://")
    date.fromisoformat(PRICES["checked_on"])  # a real date, not free text
    date.fromisoformat(PRICES["estimates"]["checked_on"])
    assert meter.PRICE_TABLE_DATE == PRICES["checked_on"]
    assert "not measurements" in PRICES["estimates"]["basis"]


def test_every_model_the_evaluation_can_call_has_a_price():
    named = {
        field.get_default()
        for name, field in Settings.model_fields.items()
        if name.endswith("_model") and isinstance(field.get_default(), str)
    }
    assert {"gpt-5.4-nano", "text-embedding-3-small"} <= named  # the fields really were found
    for model in sorted(named | {JUDGE_MODEL}):
        price = price_for(model)
        assert price["input"] > 0 and price["cached_input"] >= 0 and price["output"] >= 0, model
    require_prices(*named, JUDGE_MODEL)


def test_a_missing_price_refuses_before_any_spend():
    with pytest.raises(SystemExit, match="No price recorded for zz-unpriced"):
        require_prices("gpt-5.4-nano", "zz-unpriced")
    with pytest.raises(KeyError):
        price_for("zz-unpriced")
    for plan in (
        lambda: fsp.plan_first_step(
            [],
            mode="model",
            repeats=1,
            chat_model="zz-unpriced",
            embedding_model="text-embedding-3-small",
            tools=(),
            cap=1.0,
            split="dev",
        ),
        lambda: probe_pools.plan_probe(["q"], "zz-unpriced", cap=1.0, split="dev"),
        lambda: embedding_estimate.estimate_embedding({"a": "text"}, "zz-unpriced"),
    ):
        with pytest.raises((SystemExit, KeyError)):
            plan()


def test_a_paid_response_from_an_unpriced_model_stops_the_run():
    counter = CostMeter(1.0)
    response = SimpleNamespace(
        model="zz-unpriced", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1)
    )
    with pytest.raises(UnpricedModel):
        counter.record(response, role="agent_step")
    assert counter.tripped


# ---- the cap is compared at full precision ---------------------------------------------------------------


def test_the_cap_comparison_uses_the_exact_estimate():
    refuse_over_cap(1e-7, 1e-7)  # equal: allowed
    with pytest.raises(SystemExit, match="Refusing to start"):
        refuse_over_cap(1.1e-7, 1e-7)


def test_the_refusal_shows_enough_digits_for_a_small_cap():
    with pytest.raises(SystemExit) as caught:
        refuse_over_cap(0.009, 0.004)
    assert "$0.004" in str(caught.value) and "$0.00 " not in str(caught.value)


def test_an_exhausted_meter_message_shows_a_small_cap_exactly():
    counter = CostMeter(0.004)
    counter.total = 0.004
    with pytest.raises(meter.BudgetExceeded, match=r"\$0\.004 cap"):
        counter.check()


def test_estimates_are_not_rounded_before_the_cap_sees_them(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(meter.ESTIMATES["judge"], "usd", 4e-7)
    assert meter.estimate_judge(1)["estimated_usd"] == 4e-7
    run = meter.estimate_run(["legacy"], 1, 1, 0)
    assert run["estimated_usd"] == pytest.approx(meter.ESTIMATES["per_question"]["legacy"]["usd"])
    tiny = embedding_estimate.estimate_embedding({"a": "x"}, "text-embedding-3-small")
    exact = tiny["estimated_tokens"] * tiny["price_usd_per_million_tokens"] / 1_000_000
    assert tiny["estimated_usd"] == exact > 0


# ---- the wording of every cost limit ---------------------------------------------------------------------


def test_no_help_text_or_docstring_calls_the_cap_hard():
    pattern = re.compile(r"\bhard (spend )?cap\b", re.IGNORECASE)
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(RAG_EVAL.glob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_token_estimates_are_not_called_upper_bounds_of_the_real_count():
    """UTF-8 bytes / 3 times 1.2 is a conservative planning figure, not a proven bound (no tokenizer is installed)."""
    for module in (fsp, probe_pools, embedding_estimate):
        assert module.__file__ is not None
        text = Path(module.__file__).read_text()
        assert not re.search(r"upper bound of\s+UTF-8", text), module.__name__
        assert "tokens are an upper bound" not in text, module.__name__


def test_plan_output_says_the_cap_is_checked_between_calls(capsys: pytest.CaptureFixture[str]):
    from evaluation.rag_eval import cli

    cli.report_plan({"estimated_usd": 0.1}, 1.0)
    out = " ".join(capsys.readouterr().out.split())
    assert "not a provider-side limit" in out and "between calls" in out


# ---- safeguards of the first-step probe ------------------------------------------------------------------


def test_the_chat_client_of_the_probe_does_not_retry_by_itself():
    settings = SimpleNamespace(openai_api_key="sk-fabricated-not-a-key", chat_model="gpt-5.4-nano")
    service = fsp.make_chat_service(settings)  # type: ignore[arg-type]
    assert service._client is not None and service._client.max_retries == 0


def test_the_probe_refuses_to_build_a_client_without_a_key():
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        fsp.make_chat_service(SimpleNamespace(openai_api_key=None, chat_model="gpt-5.4-nano"))  # type: ignore[arg-type]


class Recorder:
    """Stands in for the SDK's create methods: records the request, answers with a usage block (or none)."""

    def __init__(self, usage: Any = True):
        self.calls: list[dict[str, Any]] = []
        self.usage = usage

    async def __call__(self, *_a: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        usage = (
            SimpleNamespace(prompt_tokens=100, completion_tokens=10) if self.usage is True else None
        )
        return SimpleNamespace(model="gpt-5.4-nano", usage=usage)


def installed_with(
    monkeypatch: pytest.MonkeyPatch, counter: CostMeter, chat: Any, embed: Any
) -> Any:
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    monkeypatch.setattr(AsyncCompletions, "create", chat)
    monkeypatch.setattr(AsyncEmbeddings, "create", embed)
    return counter.installed()


def test_the_meter_can_put_an_output_limit_on_chat_requests_only(monkeypatch: pytest.MonkeyPatch):
    chat, embed = Recorder(), Recorder()
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    with installed_with(monkeypatch, CostMeter(1.0, max_output_tokens=77), chat, embed):

        async def go() -> None:
            await AsyncCompletions.create(None, model="gpt-5.4-nano", messages=[])  # type: ignore[call-arg, arg-type]
            await AsyncCompletions.create(  # the caller's own limit is never overridden
                None,  # type: ignore[arg-type]
                model="gpt-5.4-nano",
                messages=[],
                max_completion_tokens=5,  # type: ignore[call-arg]
            )
            await AsyncEmbeddings.create(None, model="text-embedding-3-small", input="q")  # type: ignore[call-arg, arg-type]

        asyncio.run(go())
    assert [c["max_completion_tokens"] for c in chat.calls] == [77, 5]
    assert "max_completion_tokens" not in embed.calls[0]


def test_the_default_meter_leaves_requests_unchanged(monkeypatch: pytest.MonkeyPatch):
    chat, embed = Recorder(), Recorder()
    from openai.resources.chat.completions import AsyncCompletions

    with installed_with(monkeypatch, CostMeter(1.0), chat, embed):
        asyncio.run(AsyncCompletions.create(None, model="gpt-5.4-nano", messages=[]))  # type: ignore[call-arg, arg-type]
    assert "max_completion_tokens" not in chat.calls[0]


def test_a_response_without_usage_stops_a_strict_meter_and_not_the_default(
    monkeypatch: pytest.MonkeyPatch,
):
    from openai.resources.chat.completions import AsyncCompletions

    strict = CostMeter(1.0, require_usage=True)
    with installed_with(monkeypatch, strict, Recorder(usage=False), Recorder()):
        with pytest.raises(UnmeteredRequest, match="usage"):
            asyncio.run(AsyncCompletions.create(None, model="gpt-5.4-nano", messages=[]))  # type: ignore[call-arg, arg-type]
    assert strict.tripped and strict.exhausted
    lenient = CostMeter(1.0)  # the older behaviour of the other commands: counted and flagged
    with installed_with(monkeypatch, lenient, Recorder(usage=False), Recorder()):
        asyncio.run(AsyncCompletions.create(None, model="gpt-5.4-nano", messages=[]))  # type: ignore[call-arg, arg-type]
    assert not lenient.tripped


def plan_for(**changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = dict(
        mode="both",
        repeats=2,
        chat_model="gpt-5.4-nano",
        embedding_model="text-embedding-3-small",
        tools=(),
        cap=0.5,
        split="dev",
    )
    case = {
        "id": "c1",
        "split": "dev",
        "category": "single_fact",
        "question": "What is the refund window?",
        "expected_files": ["synthetic/a.txt"],
    }
    return fsp.plan_first_step([case], **{**args, **changes})


def test_the_plan_states_the_safeguards_and_the_ceiling_it_can_defend():
    p = plan_for()
    safeguards = p["safeguards"]
    assert safeguards["sdk_retries"] == 0
    assert safeguards["max_output_tokens_per_chat_call"] == fsp.MAX_OUTPUT_TOKENS_PER_STEP
    assert safeguards["stops_on_first_failed_call"] and safeguards["stops_on_missing_usage"]
    one_call = p["max_single_step_usd"]
    assert one_call > 0
    assert p["spend_ceiling_usd"] == pytest.approx(0.5 + one_call)
    assert p["cap_is_hard_limit"] is False
    text = " ".join(p["assumptions"] + p["not_enforced"])
    for phrase in ("provider accepts", "failed request", "embedding", "reasoning"):
        assert phrase in text


def test_the_ceiling_follows_the_output_limit_and_the_model_price():
    cheap, dear = plan_for(), plan_for(chat_model="gpt-5.4")
    assert dear["max_single_step_usd"] > cheap["max_single_step_usd"]
    out_price = price_for("gpt-5.4-nano")["output"]
    assert cheap["max_single_step_usd"] >= fsp.MAX_OUTPUT_TOKENS_PER_STEP * out_price / 1_000_000


def test_a_baseline_only_plan_has_no_chat_ceiling():
    p = plan_for(mode="baseline")
    assert p["chat_calls"] == 0 and p["max_single_step_usd"] < 1e-4


# ---- truncated and incomplete responses ----------------------------------------------------------------------


def chat_response(finish: Any, content: Any = None, calls: Any = None, *, extra: Any = None) -> Any:
    choices = [
        SimpleNamespace(
            finish_reason=finish, message=SimpleNamespace(content=content, tool_calls=calls)
        )
    ]
    if extra is not None:
        choices.append(extra)
    return SimpleNamespace(
        model="gpt-5.4-nano",
        choices=choices,
        usage=SimpleNamespace(
            prompt_tokens=2700, completion_tokens=1000, prompt_tokens_details=None
        ),
    )


class Canned:
    def __init__(self, response: Any):
        self.response = response
        self.calls = 0

    async def __call__(self, *_a: Any, **_k: Any) -> Any:
        self.calls += 1
        return self.response


def call_create(counter: CostMeter, response: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from openai.resources.chat.completions import AsyncCompletions

    with installed_with(monkeypatch, counter, Canned(response), Recorder()):
        return asyncio.run(AsyncCompletions.create(None, model="gpt-5.4-nano", messages=[]))  # type: ignore[call-arg, arg-type]


def strict() -> CostMeter:
    return CostMeter(1.0, max_output_tokens=1000, require_usage=True, require_complete=True)


def test_a_response_cut_off_by_the_output_limit_stops_the_run_after_its_cost_is_counted(
    monkeypatch: pytest.MonkeyPatch,
):
    from evaluation.rag_eval.meter import IncompleteResponse

    counter = strict()
    with pytest.raises(IncompleteResponse, match="length"):
        call_create(counter, chat_response("length", content="partial"), monkeypatch)
    assert counter.tripped and counter.exhausted
    assert counter.total > 0 and counter.rows[("unlabelled", "gpt-5.4-nano")]["calls"] == 1


@pytest.mark.parametrize("finish", ["content_filter", None, "function_call", "something_new"])
def test_any_finish_reason_other_than_stop_or_tool_calls_is_refused(
    monkeypatch: pytest.MonkeyPatch, finish: Any
):
    from evaluation.rag_eval.meter import IncompleteResponse

    with pytest.raises(IncompleteResponse):
        call_create(strict(), chat_response(finish, content="x"), monkeypatch)


def test_a_response_without_choices_or_with_a_second_bad_choice_is_refused(
    monkeypatch: pytest.MonkeyPatch,
):
    from evaluation.rag_eval.meter import IncompleteResponse

    empty = chat_response("stop")
    empty.choices = []
    with pytest.raises(IncompleteResponse):
        call_create(strict(), empty, monkeypatch)
    second = SimpleNamespace(
        finish_reason="length", message=SimpleNamespace(content="", tool_calls=None)
    )
    with pytest.raises(IncompleteResponse):
        call_create(strict(), chat_response("stop", content="ok", extra=second), monkeypatch)


@pytest.mark.parametrize("finish", ["stop", "tool_calls"])
def test_complete_responses_pass_and_the_default_meter_does_not_look(
    monkeypatch: pytest.MonkeyPatch, finish: str
):
    assert call_create(strict(), chat_response(finish, content="ok"), monkeypatch) is not None
    lenient = CostMeter(1.0)  # the other commands keep their behaviour
    assert call_create(lenient, chat_response("length"), monkeypatch) is not None
    assert not lenient.tripped


def test_embedding_responses_are_not_judged_by_a_finish_reason(monkeypatch: pytest.MonkeyPatch):
    from openai.resources.embeddings import AsyncEmbeddings

    counter = strict()
    embed = SimpleNamespace(
        model="text-embedding-3-small", usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0)
    )
    with installed_with(monkeypatch, counter, Recorder(), Canned(embed)):
        asyncio.run(AsyncEmbeddings.create(None, model="text-embedding-3-small", input="q"))  # type: ignore[call-arg, arg-type]
    assert not counter.tripped


def make_step(monkeypatch: pytest.MonkeyPatch, counter: CostMeter, response: Any) -> Any:
    from openai.resources.chat.completions import AsyncCompletions
    from app.agents.tool_rag.agent_models import AgentMessage

    service = fsp.make_chat_service(
        SimpleNamespace(openai_api_key="sk-fabricated-not-a-key", chat_model="gpt-5.4-nano")  # type: ignore[arg-type]
    )
    monkeypatch.setattr(AsyncCompletions, "create", Canned(response))

    async def go() -> Any:
        with counter.installed():
            return await service.step(messages=[AgentMessage(role="USER", text="q")], tools=())

    return asyncio.run(go())


def test_through_the_real_service_a_truncated_reply_is_not_a_valid_empty_result(
    monkeypatch: pytest.MonkeyPatch,
):
    """The three ways a cut-off reply could otherwise look fine or fail vaguely, through ``step`` itself."""
    from evaluation.rag_eval.meter import IncompleteResponse

    cut_call = SimpleNamespace(
        id="c1",
        type="function",
        function=SimpleNamespace(name="search_knowledge", arguments='{"query": "refu'),
    )
    for response in (
        chat_response("length"),  # reasoning used the whole limit: no content at all
        chat_response(
            "length", content="The refund window is"
        ),  # cut-off text would pass as "no search"
        chat_response("length", calls=[cut_call]),  # cut-off arguments
    ):
        with pytest.raises(IncompleteResponse):
            make_step(monkeypatch, strict(), response)


def test_through_the_real_service_a_genuine_decision_not_to_search_is_still_a_valid_result(
    monkeypatch: pytest.MonkeyPatch,
):
    result = make_step(monkeypatch, strict(), chat_response("stop", content="Hello there."))
    assert result.tool_calls == () and result.text == "Hello there."


def test_the_plan_describes_what_the_limit_and_truncation_stop_really_do():
    p = plan_for()
    assert p["safeguards"]["stops_on_truncated_response"] is True
    text = " ".join(p["not_enforced"] + p["assumptions"])
    assert "finish_reason" in text and "ends the run at the first call" not in text
    assert "unverified" in text or "not verifiable" in text
