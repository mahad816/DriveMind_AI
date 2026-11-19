"""Product-shaped test of the KI-002 claim checker: does it remove an invented fact, and spare a true one?

For answerable cases whose answer is a plain fact (not computed), the evidence is the text of the
file(s) that really hold the answer and the clean answer is the case's reference answer. Three
variants are built from it with fixed rules, no model involved:

  clean      the reference answer as it is (a flag here is a FALSE removal);
  appended   the clean answer plus one fabricated, specific sentence that is in no file;
  contradict the reference answer with its first number changed (contradicts the file).

The planted sentences are synthetic, so this measures the product's failure shape (an invented
specific fact next to a real answer), not general faithfulness; RAGBench covers the latter.

    python -m evaluation.rag_eval.planted_claims --model gpt-5.4-mini
"""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.tool_rag.claim_check import find_unsupported, numbers_missing, split_statements
from app.core.config import get_settings
from app.llm.openai_agent_service import OpenAIAgentChatService

from .corpus import public_files, synthetic_files
from .dataset import corpus_texts, load_cases
from .meter import CostMeter, label_var
from .score import wilson

RESULTS = Path(__file__).resolve().parents[1] / "results"
FABRICATIONS = [
    "This was confirmed by an external audit in March 2019.",
    "The same rule also applies to all contractors for up to 14 months.",
    "It was introduced after a board vote of 7 to 2 in 2021.",
    "A penalty of 4,800 USD applies when this is breached.",
    "The head of operations, Marta Ilves, signed off on it personally.",
]


def change_first_number(text: str) -> str | None:
    """Replace the first run of digits with a different number (+7), leaving the rest as it was."""
    match = re.search(r"\d+", text)
    if match is None:
        return None
    return text[: match.start()] + str(int(match.group()) + 7) + text[match.end() :]


def build_items(dataset: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
    """Items whose clean answer the evidence fully supports, plus the rule-built variants.

    A case is left out when its reference answer mentions a number the chosen files do not contain
    (for example "it was 30 days under v1.0" when only v2.0 is given): flagging that is correct, so
    it would only inflate the false-removal rate. A "contradict" variant is built only when the
    changed number is genuinely new, not another value that is in the evidence.
    """
    items, skipped = [], []
    cases = [
        c
        for c in dataset["cases"]
        if c["expected_behavior"] == "answer"
        and not c["computed"]
        and c["category"] != "public_document"
        and not c.get("history")
    ]
    for n, case in enumerate(cases):
        clean = case["reference_answer"]
        evidence = "\n\n".join(f"[{p.split('/')[-1]}]\n{texts[p]}" for p in case["expected_files"])
        if numbers_missing(clean, evidence):
            skipped.append(case["id"])
            continue
        planted = FABRICATIONS[n % len(FABRICATIONS)]
        variants = {"clean": clean, "appended": f"{clean} {planted}"}
        swapped = change_first_number(clean)
        if swapped and swapped != clean and numbers_missing(swapped, evidence):
            variants["contradict"] = swapped
        items.append(
            {
                "id": case["id"],
                "question": case["question"],
                "evidence": evidence,
                "variants": variants,
                "planted": planted,
            }
        )
    SKIPPED_CASES[:] = skipped
    # Honest calculations contain numbers the text does not: they must survive the number hint.
    for case in dataset["cases"]:
        if case["computed"] and case["expected_behavior"] == "answer" and not case.get("history"):
            evidence = "\n\n".join(
                f"[{p.split('/')[-1]}]\n{texts[p]}" for p in case["expected_files"] if p in texts
            )
            if evidence:
                items.append(
                    {
                        "id": case["id"],
                        "question": case["question"],
                        "evidence": evidence,
                        "variants": {"computed": case["reference_answer"]},
                        "planted": "",
                    }
                )
    return items


SKIPPED_CASES: list[str] = []


async def main(args: argparse.Namespace) -> None:
    files = synthetic_files() + public_files(require_present=False)
    items = build_items(load_cases(), corpus_texts([f for f in files if f.kind == "synthetic"]))
    service = OpenAIAgentChatService(get_settings().model_copy(update={"chat_model": args.model}))
    gate, meter = asyncio.Semaphore(4), CostMeter(args.cap)

    async def one(item: dict[str, Any], kind: str, text: str) -> dict[str, Any]:
        async with gate:
            statements = split_statements(text)
            flagged = await find_unsupported(
                service.complete_json, statements, item["evidence"], item["question"]
            )
        if flagged is None:
            return {"id": item["id"], "kind": kind, "error": True}
        if kind in ("clean", "computed"):
            hit = bool(flagged)  # any flag on a true answer is a false removal
        elif kind == "appended":
            hit = any(
                item["planted"] in statements[i] for i in flagged
            )  # the invented sentence itself removed
        else:
            hit = bool(flagged)  # the changed answer must be caught
        wrong = [
            statements[i]
            for i in flagged
            if kind == "appended" and item["planted"] not in statements[i]
        ]
        return {
            "id": item["id"],
            "kind": kind,
            "hit": hit,
            "collateral": len(wrong),
            "error": False,
        }

    token = label_var.set("planted_claims")
    try:
        with meter.installed():
            rows = await asyncio.gather(
                *(one(i, k, t) for i in items for k, t in i["variants"].items())
            )
    finally:
        label_var.reset(token)
        await service.aclose()
    out: dict[str, Any] = {
        "model": args.model,
        "cases": len(items),
        "left_out_unsupported_reference": list(SKIPPED_CASES),
        "errors": sum(r["error"] for r in rows),
    }
    for kind, label in (
        ("clean", "false_removal_rate"),
        ("appended", "invented_sentence_removed"),
        ("contradict", "contradiction_caught"),
        ("computed", "calculated_answer_false_removal"),
    ):
        ok = [r for r in rows if r["kind"] == kind and not r["error"]]
        k = sum(r["hit"] for r in ok)
        lo, hi = wilson(k, len(ok))
        out[label] = {
            "n": len(ok),
            "count": k,
            "rate": round(k / len(ok), 3) if ok else None,
            "ci95": [round(lo, 3), round(hi, 3)],
        }
    out["collateral_in_appended"] = sum(
        r.get("collateral", 0) for r in rows if r["kind"] == "appended"
    )
    out["spend"] = meter.summary()
    RESULTS.mkdir(exist_ok=True)
    path = (
        RESULTS / f"planted_claims_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{args.model}.json"
    )
    path.write_text(json.dumps({**out, "rows": rows}, indent=1) + "\n")
    print(path.name, json.dumps(out, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--cap", type=float, default=0.4)
    asyncio.run(main(parser.parse_args()))
