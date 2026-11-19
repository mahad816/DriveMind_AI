"""Live evaluation of the conversational-intent gate against ``intent_v1.json``.

Safe on import. Makes paid model calls (one tiny request per case) only with ``--execute``.
Reads the OpenAI key from the environment/settings and never prints it.

    uv run python -m evaluation.intent_eval --execute [--model gpt-6-luna]

Reports per-intent accuracy and, separately, the two error directions:
  * false_decline: a document question treated as small talk/out-of-scope (worst: the user
    loses an answer);
  * missed_chitchat: small talk sent to the document agent (mild: today's refusal).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.agents.tool_rag.conversation import CONVERSATIONAL, classify_intent
from app.core.config import Settings, get_settings
from app.llm.openai_service import OpenAIChatService

DATASET = Path(__file__).parent / "datasets" / "intent_v1.json"
RESULTS = Path(__file__).parent / "results"


async def evaluate(settings: Settings) -> dict[str, object]:
    cases = json.loads(DATASET.read_text())["cases"]
    service = OpenAIChatService(settings)
    errors: list[str] = []
    latencies: list[float] = []

    async def complete(system: str, user: str) -> str:
        started = time.perf_counter()
        try:
            return await service.complete_json(system, user)
        except Exception as exc:  # Record, then let classify_intent fail safe.
            errors.append(type(exc).__name__)
            raise
        finally:
            latencies.append((time.perf_counter() - started) * 1000)

    rows = []
    for case in cases:
        predicted = await classify_intent(complete, case["text"])
        rows.append({**case, "predicted": predicted, "correct": predicted == case["intent"]})
    per_intent: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        per_intent[row["intent"]].append(row["correct"])
    wrong = [r for r in rows if not r["correct"]]
    return {
        "dataset": "intent_v1",
        "model": service.model_name,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "cases": len(rows),
        "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 4),
        "per_intent_accuracy": {
            k: round(sum(v) / len(v), 4) for k, v in sorted(per_intent.items())
        },
        "false_decline": sum(
            1
            for r in wrong
            if r["intent"] == "document_question" and r["predicted"] in CONVERSATIONAL
        ),
        "missed_chitchat": sum(
            1
            for r in wrong
            if r["intent"] in CONVERSATIONAL and r["predicted"] == "document_question"
        ),
        "confused_between_conversational": sum(
            1 for r in wrong if r["intent"] in CONVERSATIONAL and r["predicted"] in CONVERSATIONAL
        ),
        "api_errors": dict(Counter(errors)),
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_max": round(max(latencies), 1) if latencies else None,
        "mistakes": [
            {"id": r["id"], "text": r["text"], "expected": r["intent"], "got": r["predicted"]}
            for r in wrong
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Make paid API calls.")
    parser.add_argument("--model", default=None, help="Override settings.chat_model.")
    args = parser.parse_args()
    if not args.execute:
        print("Dry run: pass --execute to call the model (77 tiny requests).")
        return
    settings = get_settings().model_copy(update={"chat_model": args.model} if args.model else {})
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not configured in the environment.")
    report = asyncio.run(evaluate(settings))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"intent_{datetime.now(UTC):%Y%m%d_%H%M%S}_{report['model']}.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "mistakes"}, indent=1))
    for m in report["mistakes"]:  # type: ignore[union-attr]
        print(f"MISS {m['id']}: {m['text']!r} expected={m['expected']} got={m['got']}")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
