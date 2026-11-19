"""Measure the KI-002 claim checker against RAGBench's labelled answers.

RAGBench (galileo-ai/ragbench, CC BY 4.0) gives, for each (question, documents, answer): whether the
answer is fully supported by the documents (``adherence_score``) and which answer sentences are not
(``unsupported_response_sentence_keys``). The labels were produced by a GPT-4o annotator, not by
people, so this measures agreement with that annotator, not truth.

    python -m evaluation.rag_eval.ragbench_check --model gpt-5.4-nano --per-config 40 --seed 2

Two levels are reported, the positive class always being "has an unsupported claim":
  response  - answer text split by the PRODUCT's splitter; flagged if any statement is flagged.
  sentence  - RAGBench's own sentences as the units, so the model's judgement is measured on its own.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


from app.agents.tool_rag.claim_check import (
    MAX_EVIDENCE_CHARS,
    clean_unit,
    find_unsupported,
    split_statements,
)
from app.core.config import get_settings
from app.llm.openai_agent_service import OpenAIAgentChatService

from .meter import CostMeter, label_var
from .score import wilson

API = "https://datasets-server.huggingface.co/rows"
DATASET = "galileo-ai/ragbench"
# cuad (long contracts) is left out on purpose: its documents exceed any sensible prompt budget.
CONFIGS = [
    "covidqa",
    "delucionqa",
    "emanual",
    "expertqa",
    "finqa",
    "hagrid",
    "hotpotqa",
    "msmarco",
    "pubmedqa",
    "tatqa",
    "techqa",
]
RESULTS = Path(__file__).resolve().parents[1] / "results"


CACHE = Path(
    os.environ.get("RAGBENCH_CACHE", Path.home() / ".cache" / "drivemind-eval" / "ragbench")
)


def fetch(url: str) -> dict[str, Any]:
    """GET json with a local cache (the rows API rate-limits) and backoff on HTTP 429 and 5xx."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if cached.exists():
        data: dict[str, Any] = json.loads(cached.read_text())
        return data
    request = urllib.request.Request(url, headers={"User-Agent": "drivemind-eval/0.1"})
    for wait in (0, 15, 45, 120, 240):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(request, timeout=60) as r:
                data = json.load(r)
            cached.write_text(json.dumps(data))
            return data
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise
    raise RuntimeError("Hugging Face rows API kept answering 429/5xx; try again later")


def sample_rows(per_config: int, seed: int) -> list[dict[str, Any]]:
    """Random contiguous windows of the test split of each config (seeded, so repeatable)."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        query = {"dataset": DATASET, "config": config, "split": "test"}
        total = fetch(API + "?" + urllib.parse.urlencode({**query, "offset": 0, "length": 1}))[
            "num_rows_total"
        ]
        offset = rng.randrange(0, max(1, total - per_config))
        got = fetch(
            API
            + "?"
            + urllib.parse.urlencode({**query, "offset": offset, "length": min(per_config, 100)})
        )
        rows += [{"config": config, **r["row"]} for r in got["rows"]]
    return rows


def evidence_of(row: dict[str, Any]) -> str:
    return "\n\n".join(f"[Document {i}]\n{d}" for i, d in enumerate(row["documents"], 1))


def prf(tp: int, fp: int, fn: int, tn: int) -> dict[str, Any]:
    def ratio(a: int, b: int) -> dict[str, Any]:
        lo, hi = wilson(a, b)
        return {
            "value": round(a / b, 3) if b else None,
            "n": b,
            "ci95": [round(lo, 3), round(hi, 3)],
        }

    total = tp + fp + fn + tn
    p, r = (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "base_rate_positive": round((tp + fn) / total, 3) if total else None,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "accuracy": ratio(tp + tn, total),
        "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
    }


async def check_row(complete: Any, row: dict[str, Any]) -> dict[str, Any]:
    evidence = evidence_of(row)
    unsupported_keys = set(row["unsupported_response_sentence_keys"] or [])
    actual_positive = row["adherence_score"] is False
    out: dict[str, Any] = {
        "id": row["id"],
        "config": row["config"],
        "actual_positive": actual_positive,
    }
    # response level, product splitter
    statements = split_statements(row["response"])
    flagged = await find_unsupported(complete, statements, evidence)
    out["response_pred"] = None if flagged is None else bool(flagged)
    # sentence level, dataset sentences
    # RAGBench's own sentence cuts leave list numbers glued on ("...following: 1."); strip them so a
    # fragment is not mistaken for a claim. Labels stay attached by sentence key.
    pairs = [(k, clean_unit(t)) for k, t in row["response_sentences"]]
    flagged_s = await find_unsupported(complete, [t for _, t in pairs], evidence)
    if flagged_s is None:
        out["sentence"] = None
    else:
        pred = {pairs[i][0] for i in flagged_s}
        out["sentence"] = {
            "tp": len(pred & unsupported_keys),
            "fp": len(pred - unsupported_keys),
            "fn": len(unsupported_keys - pred),
            "tn": len({k for k, _ in pairs} - pred - unsupported_keys),
        }
    return out


def summarise(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in results if r["response_pred"] is not None]
    tp = sum(1 for r in done if r["actual_positive"] and r["response_pred"])
    fp = sum(1 for r in done if not r["actual_positive"] and r["response_pred"])
    fn = sum(1 for r in done if r["actual_positive"] and not r["response_pred"])
    tn = len(done) - tp - fp - fn
    sentences = [r["sentence"] for r in results if r["sentence"] is not None]
    s = {k: sum(x[k] for x in sentences) for k in ("tp", "fp", "fn", "tn")}
    return {
        "rows": len(results),
        "checker_failed_rows": len(results) - len(done),
        "response_level": prf(tp, fp, fn, tn),
        "sentence_level": prf(**s),
    }


async def main(args: argparse.Namespace) -> None:
    rows = sample_rows(args.per_config, args.seed)
    usable = [
        r for r in rows if len(evidence_of(r)) <= MAX_EVIDENCE_CHARS and r["response_sentences"]
    ]
    settings = get_settings()
    meter = CostMeter(args.cap)
    gate = asyncio.Semaphore(args.concurrency)
    # The exact call path production uses (temperature 0, JSON mode), only the model differs.
    service = OpenAIAgentChatService(settings.model_copy(update={"chat_model": args.model}))
    complete = service.complete_json

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            return await check_row(complete, row)

    token = label_var.set("claim_check")
    try:
        with meter.installed():
            results = await asyncio.gather(*(one(r) for r in usable))
    finally:
        label_var.reset(token)
        await service.aclose()
    summary = summarise(results)
    out = {
        "model": args.model,
        "seed": args.seed,
        "per_config": args.per_config,
        "fetched": len(rows),
        "skipped_too_long_or_empty": len(rows) - len(usable),
        "dataset_license": "CC BY 4.0 (galileo-ai/ragbench)",
        "summary": summary,
        "by_config": {c: summarise([r for r in results if r["config"] == c]) for c in CONFIGS},
        "spend": meter.summary(),
        "rows": results,
    }
    RESULTS.mkdir(exist_ok=True)
    path = (
        RESULTS
        / f"ragbench_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{args.model}_seed{args.seed}.json"
    )
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(
        path.name,
        json.dumps({k: out[k] for k in ("fetched", "skipped_too_long_or_empty")}),
        json.dumps(summary, indent=1),
        f"spend ${meter.total:.3f}",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--per-config", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--cap", type=float, default=1.0)
    parser.add_argument("--concurrency", type=int, default=4)
    asyncio.run(main(parser.parse_args()))
