"""Spend meter with a cap, installed around the OpenAI SDK for the duration of a run.

Every chat and embedding response carries a ``usage`` block; this adds it up with the checked
price table (``prices.json``) and refuses further calls once the cap is reached. An unknown model
raises instead of being silently counted as free. Figures are estimates from token counts.

The cap is checked BETWEEN calls from the usage each response reports. It is not a provider-side limit: a run
can pass it by the call in flight, and a retried, cancelled-but-billed or usage-less request is invisible
(``METERING_LIMITS``). Three opt-in safeguards narrow that gap for a command that wants them: ``max_output_tokens``
puts an output limit on every chat request that sets none, ``require_usage`` stops the run at a response without
a usage block instead of counting it as free, and ``require_complete`` stops the run at a chat response that did
not finish normally (cut off by the output limit, filtered, or in a state this code does not know).

Each call is attributed to the case that made it (``case_var``) and to a role. The role comes from the
fixed system prompt the request carries, never from the model name, so two roles that share a model stay
apart. A call whose shape is not recognised falls back to ``label_var`` (the judge and the grader set it).
"""

import argparse
import asyncio
import contextvars
import json
import math
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.agents.tool_rag.claim_check import SYSTEM_PROMPT as CLAIM_CHECK_PROMPT
from app.agents.tool_rag.conversation import INTENT_SYSTEM_PROMPT
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT
from app.llm import prompts as legacy

_TABLE = json.loads((Path(__file__).with_name("prices.json")).read_text())
PRICES = _TABLE["models"]
PRICE_TABLE_DATE: str = _TABLE["checked_on"]
ESTIMATES = _TABLE["estimates"]
label_var: contextvars.ContextVar[str] = contextvars.ContextVar("meter_label", default="unlabelled")
# The case a call belongs to. Set once per case inside its own task, so concurrent cases never mix.
case_var: contextvars.ContextVar[str] = contextvars.ContextVar("meter_case", default="")

# The system prompt a chat request starts with decides its role. Exact text, so a changed prompt that
# is not listed here shows up as "unlabelled" instead of being silently attributed to a neighbour.
ROLE_BY_SYSTEM_PROMPT: dict[str, str] = {
    INTENT_SYSTEM_PROMPT: "intent_gate",
    CLAIM_CHECK_PROMPT: "claim_check",
    AGENT_SYSTEM_PROMPT: "agent_step",
    legacy.FOLLOWUP_REWRITE_SYSTEM_PROMPT: "followup_rewrite",
    **dict.fromkeys(
        (
            legacy.RAG_SYSTEM_PROMPT,
            legacy.FILE_TARGET_SYSTEM_PROMPT,
            legacy.FILE_INVENTORY_SYSTEM_PROMPT,
            legacy.COLLECTION_SYSTEM_PROMPT,
            legacy.CHITCHAT_SYSTEM_PROMPT,
            legacy.DEMO_CHITCHAT_SYSTEM_PROMPT,
        ),
        "answer_generation",
    ),
}
EMBEDDING_ROLE = "embedding"
COMPLETE_FINISH_REASONS = frozenset({"stop", "tool_calls"})
COUNTERS = ("calls", "failed_calls", "cancelled_calls", "missing_usage_calls")
TOKENS = ("input_tokens", "output_tokens", "cached_tokens")

# Written into every manifest: what this meter can and cannot see.
METERING_LIMITS: dict[str, Any] = {
    "counted": "successful non-streaming chat and embedding requests with their usage block; "
    "failed and cancelled requests as counts without tokens",
    "invisible": [
        "SDK automatic retries (they happen below the wrapped method; a command must switch them off at its "
        "client, as the first-step probe does)",
        "streamed requests (refused: the meter stops the run instead of guessing)",
        "a request that was billed after its caller gave up",
    ],
    "attribution": "role from the first system prompt of the request, case from a context variable",
}


def role_of_chat(kwargs: dict[str, Any]) -> str:
    """The role of a chat request, from its first system message; the label when none matches."""
    for message in kwargs.get("messages") or ():
        if isinstance(message, dict) and message.get("role") == "system":
            role = ROLE_BY_SYSTEM_PROMPT.get(message.get("content") or "")
            if role:
                return role
            break  # only the first system message names the role
    return label_var.get()


class BudgetExceeded(BaseException):  # noqa: N818 - named for what happened, like KeyboardInterrupt
    """Raised before a call that would start after the cap was reached.

    A ``BaseException`` on purpose: the application's tool agent, claim check and graph turn every
    ``Exception`` from a provider call into a recorded failure or a fail-open answer, which would hide
    the cap and let the run go on writing "errors". This one passes through all of them.
    """


class UnmeteredRequest(BudgetExceeded):
    """A streamed request: its usage cannot be read here, so the spend could no longer be counted."""


class IncompleteResponse(BudgetExceeded):
    """A chat response did not finish normally (``finish_reason`` other than ``stop`` or ``tool_calls``).

    Its text or tool arguments may be cut off, so no caller may read it as a valid, empty or partial answer. The
    message names the finish reason only, never any text of the response."""


class UnpricedModel(BudgetExceeded):
    """A paid response came from a model with no recorded price, so the spend can no longer be counted."""


def format_usd(amount: float) -> str:
    """A dollar amount with enough digits that a small cap is not shown as $0.00."""
    return f"${amount:.6g}"


def price_for(model: str) -> dict[str, float]:
    # Longest key wins so "gpt-5.4-mini-2026-03-17" never falls back to "gpt-5.4".
    for key in sorted(PRICES, key=len, reverse=True):
        if model == key or model.startswith(key + "-"):
            price: dict[str, float] = PRICES[key]
            return price
    raise KeyError(f"no price recorded for model {model!r}; add it to prices.json before running")


def cost_of(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    price = price_for(model)
    fresh = max(input_tokens - cached_tokens, 0)
    return (
        fresh * price["input"]
        + cached_tokens * price["cached_input"]
        + output_tokens * price["output"]
    ) / 1_000_000


def _blank() -> dict[str, Any]:
    return {**dict.fromkeys(COUNTERS, 0), **dict.fromkeys(TOKENS, 0), "cost_usd": 0.0}


class CostMeter:
    def __init__(
        self,
        cap_usd: float,
        *,
        max_output_tokens: int | None = None,
        require_usage: bool = False,
        require_complete: bool = False,
    ) -> None:
        self.cap_usd = cap_usd
        self.max_output_tokens = (
            max_output_tokens  # put on chat requests that set no limit; None: leave them alone
        )
        self.require_usage = require_usage  # a response without usage stops the run
        self.require_complete = (
            require_complete  # a chat response that did not finish normally stops the run
        )
        self.total = 0.0
        self.tripped = False  # set the moment the meter refuses or loses count; the run must end
        self.stopped_cases: set[str] = set()
        self.rows: dict[tuple[str, str], dict[str, Any]] = defaultdict(_blank)  # (role, model)
        self.by_case: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(
            lambda: defaultdict(_blank)
        )

    @property
    def exhausted(self) -> bool:
        """True once no further case should be started."""
        return self.tripped or self.total >= self.cap_usd

    def trip(self) -> None:
        self.tripped = True
        self.stopped_cases.add(case_var.get())

    def check(self) -> None:
        if (
            self.exhausted
        ):  # also after an unpriced or streamed request: in-flight cases must stop too
            self.trip()
            raise BudgetExceeded(
                f"estimated spend {format_usd(self.total)} reached the {format_usd(self.cap_usd)} cap"
            )

    def _add(self, role: str, model: str, **deltas: float) -> None:
        """Add to the run-wide row and to the row of the current case, so the two cannot drift apart."""
        for row in (self.rows[(role, model)], self.by_case[case_var.get()][(role, model)]):
            for key, value in deltas.items():
                row[key] += value

    def record(
        self,
        response: Any,
        *,
        role: str | None = None,
        requested_model: str | None = None,
    ) -> None:
        role = role or label_var.get()
        model = getattr(response, "model", None) or requested_model or "unknown"
        usage = getattr(response, "usage", None)
        if usage is None:
            # A paid call whose cost is unknown: counted, flagged, and the case total is a lower bound.
            self._add(role, model, calls=1, missing_usage_calls=1)
            if self.require_usage:
                self.trip()
                raise UnmeteredRequest(
                    "a response came back without a usage block, so its cost cannot be counted; the run stops"
                )
            return
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        inp = int(getattr(usage, "prompt_tokens", 0) or 0)
        out = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            amount = cost_of(model, inp, out, cached)
        except KeyError as exc:
            # Never let an uncounted paid call pass as free: stop the run (application code would swallow a KeyError).
            self.trip()
            raise UnpricedModel(str(exc)) from None
        self._add(
            role,
            model,
            calls=1,
            input_tokens=inp,
            output_tokens=out,
            cached_tokens=cached,
            cost_usd=amount,
        )
        self.total += amount

    def check_complete(self, response: Any) -> None:
        """Stop the run unless every choice of a chat response finished normally.

        OpenAI Chat Completions (non-streaming) reports ``finish_reason``: ``stop`` (a finished reply) and
        ``tool_calls`` (finished tool calls) are the only values accepted. ``length`` (cut off by the output limit,
        which also counts reasoning tokens), ``content_filter``, ``function_call`` (not used with tools), a missing
        value or any value this code does not know is refused: the cost was already counted, and the run ends.
        """
        reasons = [
            getattr(choice, "finish_reason", None)
            for choice in getattr(response, "choices", None) or ()
        ]
        bad = [reason for reason in reasons if reason not in COMPLETE_FINISH_REASONS] or (
            [] if reasons else ["no choices"]
        )
        if bad:
            self.trip()
            raise IncompleteResponse(
                f"a chat response did not finish normally (finish_reason {bad[0]!r}); its content cannot be "
                "trusted, so the run stops"
            )

    def record_failure(self, role: str, model: str, *, cancelled: bool) -> None:
        """A request that raised or was cancelled: counted, without tokens or dollars."""
        self._add(role, model, calls=1, failed_calls=1, cancelled_calls=int(cancelled))

    def summary(self) -> dict[str, Any]:
        return {
            "cap_usd": self.cap_usd,
            "estimated_total_usd": round(self.total, 5),
            "tripped": self.tripped,
            "by_label_and_model": [
                {"label": role, "model": model, **_rounded(row)}
                for (role, model), row in sorted(self.rows.items())
            ],
        }

    def case_accounting(self, case: str) -> dict[str, Any]:
        """Calls, failures, tokens and dollars of one case by role, and their total.

        ``usage_incomplete`` is true when a call came back without a usage block (its cost is missing).
        """
        roles: dict[str, dict[str, Any]] = {}
        for (role, model), row in sorted(self.by_case.get(case, {}).items()):
            entry = roles.setdefault(role, {**_blank(), "models": []})
            for key in (*COUNTERS, *TOKENS, "cost_usd"):
                entry[key] += row[key]
            entry["models"].append(model)
        total = _blank()
        for entry in roles.values():
            for key in (*COUNTERS, *TOKENS, "cost_usd"):
                total[key] += entry[key]
        return {
            "by_role": {role: _rounded(entry) for role, entry in roles.items()},
            "total": _rounded(total),
            "usage_incomplete": bool(total["missing_usage_calls"]),
        }

    @contextmanager
    def installed(self) -> Iterator["CostMeter"]:
        from openai.resources.chat.completions import AsyncCompletions
        from openai.resources.embeddings import AsyncEmbeddings

        originals = (AsyncCompletions.create, AsyncEmbeddings.create)

        def wrap(original: Callable[..., Any], fixed_role: str | None) -> Callable[..., Any]:
            async def create(*args: Any, **kwargs: Any) -> Any:
                self.check()
                if kwargs.get("stream"):
                    self.trip()
                    raise UnmeteredRequest("a streamed request cannot be metered; the run stops")
                if (
                    fixed_role is None
                    and self.max_output_tokens is not None
                    and "max_completion_tokens" not in kwargs
                    and "max_tokens" not in kwargs
                ):
                    kwargs["max_completion_tokens"] = self.max_output_tokens
                role = fixed_role or role_of_chat(kwargs)
                requested = kwargs.get("model")
                try:
                    response = await original(*args, **kwargs)
                except (Exception, asyncio.CancelledError) as exc:
                    self.record_failure(
                        role,
                        requested or "unknown",
                        cancelled=isinstance(exc, asyncio.CancelledError),
                    )
                    raise
                self.record(response, role=role, requested_model=requested)
                if self.require_complete and fixed_role is None:  # chat only
                    self.check_complete(response)
                return response

            return create

        AsyncCompletions.create = wrap(originals[0], None)  # type: ignore[method-assign]
        AsyncEmbeddings.create = wrap(originals[1], EMBEDDING_ROLE)  # type: ignore[method-assign]
        try:
            yield self
        finally:
            AsyncCompletions.create = originals[0]  # type: ignore[method-assign]
            AsyncEmbeddings.create = originals[1]  # type: ignore[method-assign]


def _rounded(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (round(v, 5) if k == "cost_usd" else v) for k, v in row.items()}


def require_prices(*models: str) -> None:
    """Exit before any spend if a model the run will call has no recorded price."""
    missing = []
    for model in models:
        try:
            price_for(model)
        except KeyError:
            missing.append(model)
    if missing:
        raise SystemExit(
            f"No price recorded for {', '.join(missing)}; add it to prices.json first."
        )


def cap_argument(text: str) -> float:
    """argparse type for ``--cap``: a positive, finite number of dollars."""
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("the cap must be a positive number of dollars")
    return value


def estimate_run(
    pipelines: list[str], cases: int, repeats: int, judged_cases: int
) -> dict[str, Any]:
    """Planned calls by role and dollars for ``cases`` questions on each pipeline, ``repeats`` times.

    ``judged_cases`` is the number of those cases the refusal judge reads. Constants are the dated
    planning figures in ``prices.json``; they are not measurements.
    """
    runs = len(pipelines) * repeats
    calls: dict[str, int] = {}
    usd = 0.0
    for pipeline in pipelines:
        unit = ESTIMATES["per_question"][pipeline]
        for role, count in unit["calls"].items():
            calls[role] = calls.get(role, 0) + count * cases * repeats
        usd += unit["usd"] * cases * repeats
    judge = estimate_judge(judged_cases * runs)
    calls["judge"] = judge["calls"]["judge"]
    return {
        "cases": cases,
        "runs": runs,
        "calls": calls,
        "estimated_usd": usd
        + judge["estimated_usd"],  # full precision: the cap is compared with this
    }


def estimate_judge(judged: int) -> dict[str, Any]:
    """Planned refusal-judge calls and dollars for ``judged`` replies (also what ``rescore`` costs)."""
    calls = ESTIMATES["judge"]["calls"] * judged
    return {
        "calls": {"judge": calls},
        "estimated_usd": ESTIMATES["judge"]["usd"] * judged,
    }


def refuse_over_cap(estimated_usd: float, cap_usd: float) -> None:
    """Stop before any provider call when the planned cost already exceeds the cap."""
    if estimated_usd > cap_usd:
        raise SystemExit(
            f"Refusing to start: the estimate {format_usd(estimated_usd)} is above the {format_usd(cap_usd)} cap. "
            "Run with --plan to see the numbers, then raise --cap or reduce the work."
        )
