"""Spend meter with a hard cap, installed around the OpenAI SDK for the duration of a run.

Every chat and embedding response carries a ``usage`` block; this adds it up with the checked
price table (``prices.json``) and refuses further calls once the cap is reached. An unknown model
raises instead of being silently counted as free. Figures are estimates from token counts.
"""

import contextvars
import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PRICES = json.loads((Path(__file__).with_name("prices.json")).read_text())["models"]
label_var: contextvars.ContextVar[str] = contextvars.ContextVar("meter_label", default="unlabelled")


class BudgetExceeded(RuntimeError):
    """Raised before a call that would start after the cap was reached."""


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


class CostMeter:
    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = cap_usd
        self.total = 0.0
        self.rows: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )

    def check(self) -> None:
        if self.total >= self.cap_usd:
            raise BudgetExceeded(
                f"estimated spend ${self.total:.4f} reached the ${self.cap_usd:.2f} cap"
            )

    def record(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        model = getattr(response, "model", None) or "unknown"
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        inp = int(getattr(usage, "prompt_tokens", 0) or 0)
        out = int(getattr(usage, "completion_tokens", 0) or 0)
        amount = cost_of(model, inp, out, cached)
        row = self.rows[(label_var.get(), model)]
        row["calls"] += 1
        row["input_tokens"] += inp
        row["output_tokens"] += out
        row["cost_usd"] += amount
        self.total += amount

    def summary(self) -> dict[str, Any]:
        return {
            "cap_usd": self.cap_usd,
            "estimated_total_usd": round(self.total, 5),
            "by_label_and_model": [
                {
                    "label": label,
                    "model": model,
                    **{k: (round(v, 5) if k == "cost_usd" else int(v)) for k, v in row.items()},
                }
                for (label, model), row in sorted(self.rows.items())
            ],
        }

    @contextmanager
    def installed(self) -> Iterator["CostMeter"]:
        from openai.resources.chat.completions import AsyncCompletions
        from openai.resources.embeddings import AsyncEmbeddings

        originals = (AsyncCompletions.create, AsyncEmbeddings.create)

        def wrap(original: Callable[..., Any]) -> Callable[..., Any]:
            async def create(*args: Any, **kwargs: Any) -> Any:
                self.check()
                response = await original(*args, **kwargs)
                self.record(response)
                return response

            return create

        AsyncCompletions.create = wrap(originals[0])  # type: ignore[method-assign]
        AsyncEmbeddings.create = wrap(originals[1])  # type: ignore[method-assign]
        try:
            yield self
        finally:
            AsyncCompletions.create = originals[0]  # type: ignore[method-assign]
            AsyncEmbeddings.create = originals[1]  # type: ignore[method-assign]
