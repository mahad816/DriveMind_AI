"""Passage-level retrieval metrics: is the chunk that holds the evidence among the retrieved chunks, and where?

Pure functions over what the retriever returned (``Hit`` with its chunk id) and what ``anchors.py`` mapped
(``AnchorMap``). No database, no provider. ``retrieval_probe`` supplies the hits and the mapped anchors.

Definitions (one retrieval of one question, results cut to the first ``top_k`` distinct chunks):

* chunks            distinct chunks in rank order; a repeated chunk id keeps its first position
                    (``duplicates_dropped`` counts the rest). Rank 1 is the first chunk.
* anchor found      the anchor's chunk set (``AnchorMap.chunk_ids``) meets the retrieved chunks. A split anchor
                    is satisfied by either half, a whole anchor lying in two overlapping chunks by either.
* any_found         at least one anchor found: the headline passage recall. all_found: every anchor found.
                    anchor_coverage: anchors found / anchors.
* first_rank        rank of the first retrieved chunk that is any anchor's chunk; ``None`` when none.
                    reciprocal_rank is 1 / first_rank, and 0 when nothing was found, so MRR is a mean over
                    measured cases with a miss counting zero.
* no_evidence       no anchor chunk retrieved at all.
* file level        file_recall = expected files with at least one retrieved chunk / expected files. It is a
                    separate, weaker figure and never stands in for passage recall; ``right_file_wrong_passage``
                    counts cases the file level would have called a success and the passage level does not.
* distinct_files    files among the retrieved chunks.

A case is ``measured`` only when every anchor maps to at least one indexed chunk. If any anchor is ``absent``
the case is a ``mapping_failure`` (the index or the quote is wrong, not the search) and a case that should have
anchors but has none is ``no_anchors``. Both are counted and listed apart and enter no denominator.

Refusal cases ("not in the files") have no evidence: only the best vector score among the retrieved chunks is
recorded, to recheck that no score threshold can separate them from answerable questions.

The sealed held-out pool is refused here (``HeldOutRefused``); its reporting belongs to a later checkpoint.
Pools are never combined: the report has one block per pool and no overall one.
"""

import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .anchors import AnchorMap
from .pools import pool_of
from .retrieval_probe import ANSWERABLE, REFUSAL, Hit
from .schema_v3 import evidence_formats
from .score import rate_of
from .sealing import HELD_OUT_POOL
from .stats import percentile

BREAKDOWNS = {"by_category": "category", "by_format": "format", "by_language": "language"}


class HeldOutRefused(ValueError):
    """Held-out rows reached the passage report; they may not be reported here."""


def _distinct(hits: Sequence[Hit], top_k: int | None) -> tuple[list[Hit], int]:
    """First ``top_k`` distinct chunks in rank order, and how many repeated hits were dropped before the cut."""
    seen: set[str] = set()
    kept: list[Hit] = []
    dropped = 0
    for hit in hits:
        key = hit.chunk_id if hit.chunk_id is not None else f"no-id:{len(kept)}:{hit.filename}"
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(hit)
    return (kept if top_k is None else kept[:top_k]), dropped


def _file_name(path: str, names: Mapping[str, str]) -> str:
    return names.get(path) or path.rsplit("/", 1)[-1]


def measure_passages(
    hits: Sequence[Hit],
    anchors: Sequence[AnchorMap],
    expected_files: Sequence[str],
    names: Mapping[str, str],
    *,
    top_k: int | None,
) -> dict[str, Any]:
    """Passage and file metrics of one answerable case. ``names`` maps a corpus path to its indexed file name."""
    chunks, dropped = _distinct(hits, top_k)
    wanted_files = list(dict.fromkeys(_file_name(p, names) for p in expected_files))
    retrieved_files = list(dict.fromkeys(c.filename for c in chunks))
    files_found = sum(f in retrieved_files for f in wanted_files)
    absent = sum(a.kind == "absent" for a in anchors)
    status = "no_anchors" if not anchors else "mapping_failure" if absent else "measured"
    out: dict[str, Any] = {
        "status": status,
        "chunks": len(chunks),
        "duplicates_dropped": dropped,
        "distinct_files": len(retrieved_files),
        "anchors": len(anchors),
        "absent_anchors": absent,
        "files_found": files_found,
        "file_recall": files_found / len(wanted_files) if wanted_files else None,
        "any_file_found": files_found > 0,
        "all_files_found": bool(wanted_files) and files_found == len(wanted_files),
        "anchors_found": None,
        "anchor_coverage": None,
        "any_found": None,
        "all_found": None,
        "first_rank": None,
        "reciprocal_rank": None,
        "no_evidence": None,
        "right_file_wrong_passage": None,
    }
    if status != "measured":
        return out
    rank_of = {c.chunk_id: i for i, c in enumerate(chunks, start=1) if c.chunk_id is not None}
    found = [a for a in anchors if any(cid in rank_of for cid in a.chunk_ids)]
    ranks = [rank_of[cid] for a in found for cid in a.chunk_ids if cid in rank_of]
    first = min(ranks) if ranks else None
    out |= {
        "anchors_found": len(found),
        "anchor_coverage": len(found) / len(anchors),
        "any_found": bool(found),
        "all_found": len(found) == len(anchors),
        "first_rank": first,
        "reciprocal_rank": 1 / first if first else 0.0,
        "no_evidence": not found,
        "right_file_wrong_passage": bool(files_found) and not found,
    }
    return out


def _descriptor(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "pool": pool_of(case),
        "category": case["category"],
        "language": case.get("language", "en"),
        "format": "+".join(evidence_formats(case)) or "none",
        "expected_behavior": case["expected_behavior"],
    }


def passage_row(
    case: Mapping[str, Any],
    hits: Sequence[Hit],
    anchors: Sequence[AnchorMap],
    names: Mapping[str, str],
    top_k: int | None,
) -> dict[str, Any]:
    return _descriptor(case) | measure_passages(
        hits, anchors, case["expected_files"], names, top_k=top_k
    )


def refusal_row(case: Mapping[str, Any], hits: Sequence[Hit], top_k: int | None) -> dict[str, Any]:
    chunks, _ = _distinct(hits, top_k)
    scores = [c.vector_score for c in chunks if c.vector_score is not None]
    return _descriptor(case) | {
        "chunks": len(chunks),
        "best_vector_score": round(max(scores), 3) if scores else None,
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _ids(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"n": len(rows), "ids": sorted(r["id"] for r in rows)}


def summarise_pool(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Rates and means of one group of answerable rows. Mapping failures and unanchored cases are counted and
    listed, and are in no denominator."""
    measured = [r for r in rows if r["status"] == "measured"]
    found_ranks = Counter(str(r["first_rank"]) for r in measured if r["first_rank"])
    return {
        "answerable_cases": len(rows),
        "measured": len(measured),
        "mapping_failures": _ids([r for r in rows if r["status"] == "mapping_failure"]),
        "no_anchors": _ids([r for r in rows if r["status"] == "no_anchors"]),
        "any_found": rate_of([r["any_found"] for r in measured]),
        "all_found": rate_of([r["all_found"] for r in measured]),
        "mean_anchor_coverage": _mean([r["anchor_coverage"] for r in measured]),
        "mrr": _mean([r["reciprocal_rank"] for r in measured]),
        "first_rank_distribution": dict(sorted(found_ranks.items(), key=lambda kv: int(kv[0]))),
        "no_evidence": _ids([r for r in measured if r["no_evidence"]]),
        "right_file_wrong_passage": _ids([r for r in measured if r["right_file_wrong_passage"]]),
        "file_level": {
            "any_file_found": rate_of([r["any_file_found"] for r in measured]),
            "all_files_found": rate_of([r["all_files_found"] for r in measured]),
            "mean_file_recall": _mean(
                [r["file_recall"] for r in measured if r["file_recall"] is not None]
            ),
        },
        "mean_distinct_files": _mean([r["distinct_files"] for r in measured]),
        "mean_chunks": _mean([r["chunks"] for r in measured]),
    }


def summarise_refusal_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scores = sorted(r["best_vector_score"] for r in rows if r["best_vector_score"] is not None)
    return {
        "n": len(rows),
        "with_any_result": sum(r["chunks"] > 0 for r in rows),
        "no_vector_score": sum(r["best_vector_score"] is None for r in rows),
        "best_score": {
            "n": len(scores),
            "min": scores[0] if scores else None,
            "median": round(statistics.median(scores), 3) if scores else None,
            "p90": percentile(scores, 0.9),
            "max": scores[-1] if scores else None,
        },
    }


def _grouped(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    return {name: summarise_pool(group) for name, group in sorted(groups.items())}


def passage_report(
    answerable: Sequence[Mapping[str, Any]], refusal: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """One block per pool (development, regression); within it the overall figures and the three breakdowns.
    Raises ``HeldOutRefused`` if any row belongs to the sealed pool."""
    if any(r["pool"] == HELD_OUT_POOL for r in [*answerable, *refusal]):
        raise HeldOutRefused("held-out rows may not enter the passage report")
    pools = sorted({r["pool"] for r in [*answerable, *refusal]})
    report: dict[str, Any] = {}
    for pool in pools:
        mine = [r for r in answerable if r["pool"] == pool]
        block: dict[str, Any] = {"overall": summarise_pool(mine)}
        for label, key in BREAKDOWNS.items():
            block[label] = _grouped(mine, key)
        block["refusal"] = summarise_refusal_scores([r for r in refusal if r["pool"] == pool])
        report[pool] = block
    return {"pools": report}


async def passage_section(
    sessions: Any,
    cases: Sequence[dict[str, Any]],
    files: Sequence[Any],
    plain_hits: Mapping[str, Sequence[Hit]],
    *,
    top_k: int | None,
) -> dict[str, Any]:
    """Passage report for the cases a probe searched. Reads the evaluation database only (no provider call).
    Cases that need an earlier turn are not searched and are counted as ``skipped_history``."""
    from .retrieval_probe import split_cases  # late: retrieval_probe imports this module lazily
    from .runner import load_resolved

    if any(pool_of(c) == HELD_OUT_POOL for c in cases):  # before any database read
        raise HeldOutRefused("held-out cases may not enter the passage report")
    answerable, refusal = split_cases(cases)
    resolved = await load_resolved(sessions, {c["id"]: c for c in answerable}, [], files)
    skipped = sum(1 for c in cases if c.get("history"))
    if not resolved.database:
        return {
            "status": "unavailable",
            "reason": "the evaluation database was unreachable or does not hold the anchor files; "
            "no passage metric was computed (file-level figures above are unaffected)",
            "skipped_history": skipped,
        }
    rows = [
        passage_row(c, plain_hits[c["id"]], resolved.anchors[c["id"]], resolved.names, top_k)
        for c in answerable
        if c["id"] in plain_hits
    ]
    refusal_rows = [
        refusal_row(c, plain_hits[c["id"]], top_k) for c in refusal if c["id"] in plain_hits
    ]
    return {
        "status": "ok",
        "top_k": top_k,
        "query": "the question text itself (an upper bound; the agent writes its own query)",
        "skipped_history": skipped,
        **passage_report(rows, refusal_rows),
        "rows": rows,
        "refusal_rows": refusal_rows,
    }


def _pct(rate: Mapping[str, Any]) -> str:
    lo, hi = rate["ci95"]
    value = "n/a" if rate["rate"] is None else f"{100 * rate['rate']:.1f}%"
    return f"{rate['passed']}/{rate['n']} {value} [{100 * lo:.0f}-{100 * hi:.0f}]"


def print_passage(section: Mapping[str, Any]) -> None:
    if section["status"] != "ok":
        print(f"\npassage metrics: {section['reason']}")
        return
    print(f"\npassage level (top-{section['top_k']}, query = question text)")
    for pool, block in section["pools"].items():
        o = block["overall"]
        print(
            f"  {pool}: {o['measured']}/{o['answerable_cases']} measured, "
            f"any anchor {_pct(o['any_found'])}, all anchors {_pct(o['all_found'])}, MRR {o['mrr']}, "
            f"file-level any {_pct(o['file_level']['any_file_found'])}"
        )
        print(
            f"    mapping failures {o['mapping_failures']['n']}, no anchors {o['no_anchors']['n']}, "
            f"no evidence retrieved {o['no_evidence']['n']}, right file wrong passage "
            f"{o['right_file_wrong_passage']['n']}"
        )
        best = block["refusal"]["best_score"]
        print(f"    refusal best score: n={best['n']} median {best['median']} max {best['max']}")


__all__ = [
    "passage_section",
    "print_passage",
    "ANSWERABLE",
    "REFUSAL",
    "HeldOutRefused",
    "measure_passages",
    "passage_report",
    "passage_row",
    "refusal_row",
    "summarise_pool",
    "summarise_refusal_scores",
]
