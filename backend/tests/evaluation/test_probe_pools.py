"""M1-08-D: the retrieval probe selects pools, honours the held-out gate and prints a free cost plan.

Free: no key, no network, no container. Every sealed file and attestation here is FABRICATED in tmp_path; the real
sealed pool, review sheet and freeze manifest are never read. The marker text is invented and appears in no
committed dataset. A tripwire replaces the provider's embedding and chat methods for every test in this file, so a
test that reaches a paid call fails instead of spending.
"""

import argparse
import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.rag_eval import pools, probe_pools, retrieval_probe, review_gate
from evaluation.rag_eval.meter import PRICE_TABLE_DATE, price_for
from evaluation.rag_eval.retrieval_probe import Hit
from evaluation.rag_eval.sealing import MIN_CELL, small_cells

MARKER = "zq-d-probe-marker"
HEX = "a" * 64


@pytest.fixture(autouse=True)
def no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from openai.resources.chat.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings

    async def tripwire(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider call was attempted")

    monkeypatch.setattr(AsyncEmbeddings, "create", tripwire)
    monkeypatch.setattr(AsyncCompletions, "create", tripwire)


def fab_case(
    i: int, *, split: str = "held_out", behavior: str = "answer", **kw: Any
) -> dict[str, Any]:
    fmt = ("docx", "pdf", "xlsx")[i % 3]
    refusal = behavior in {"not_found", "decline_or_not_found", "correct_premise"}
    return {
        "id": f"hog{i:03d}",
        "split": split,
        "schema": 3,
        "category": "x",
        "language": "en",
        "expected_behavior": behavior,
        "question": f"{MARKER} question {i}?",
        "reference_answer": f"{MARKER} answer {i}",
        "expected_files": [] if refusal else [f"v1/{MARKER}_{i}.{fmt}"],
        "evidence_anchors": [] if refusal else [{"file": f"v1/{MARKER}_{i}.{fmt}", "quote": "q"}],
        "must_include": [],
        "must_not_include": [],
        "computed": False,
        **kw,
    }


# ---- mode checks (pure) --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"phrasings": True}, "--phrasings"),
        ({"passage": True}, "--passage"),
        ({"messy": True}, "--messy"),
        ({"overrides": ["--threshold"]}, "--threshold"),
        ({"frozen": False}, "--frozen"),
    ],
)
def test_held_out_refuses_every_mode_that_could_leak_or_tune(kwargs, words):
    base: dict[str, Any] = {"frozen": True}
    with pytest.raises(SystemExit, match=words):
        probe_pools.check_probe_mode("held_out", **{**base, **kwargs})


def test_regression_pool_needs_the_frozen_corpus_and_an_unknown_split_is_refused():
    with pytest.raises(SystemExit, match="--frozen"):
        probe_pools.check_probe_mode("regression", frozen=False)
    with pytest.raises(SystemExit, match="unknown split"):
        probe_pools.check_probe_mode("nope", frozen=True)


@pytest.mark.parametrize(
    ("split", "kwargs"),
    [
        ("dev", {"frozen": False}),
        ("test", {"frozen": False, "phrasings": True}),
        ("all", {"frozen": True, "phrasings": True, "passage": True, "overrides": ["--top-k"]}),
        ("regression", {"frozen": True, "passage": True}),
        ("held_out", {"frozen": True}),
    ],
)
def test_the_allowed_modes_pass(split, kwargs):
    probe_pools.check_probe_mode(split, **kwargs)


# ---- the planned queries are the queries probe() makes -----------------------------------------------


def test_planned_queries_equal_the_searches_probe_makes():
    cases = [
        fab_case(1, split="dev"),
        fab_case(2, split="dev", language="ur"),
        fab_case(3, split="dev", history=[{"role": "user", "text": "earlier"}]),
        fab_case(4, split="test", behavior="not_found"),
        fab_case(5, split="test", behavior="clarify", expected_files=[]),
    ]
    seen: list[str] = []

    async def search(query: str) -> list[Hit]:
        seen.append(query)
        return []

    names = list(retrieval_probe.PHRASINGS)
    asyncio.run(retrieval_probe.probe(search, cases, names))
    assert retrieval_probe.planned_queries(cases, names) == seen
    assert (
        len(seen) == 4 + 1 + 1
    )  # case 1: four wordings; case 2: plain only; case 4: refusal; 3 and 5 none


# ---- the free plan -------------------------------------------------------------------------------------


def test_plan_prices_the_exact_queries_at_the_models_recorded_price():
    queries = ["a" * 30] * 3
    plan = probe_pools.plan_probe(queries, "text-embedding-3-small", cap=1.0, split="dev")
    raw = math.ceil(90 / probe_pools.BYTES_PER_TOKEN)
    tokens = math.ceil(raw * probe_pools.SAFETY_MARGIN)
    price = price_for("text-embedding-3-small")["input"]
    assert plan["embedding_calls"] == 3 and plan["chat_calls"] == 0
    assert plan["estimated_tokens"] == tokens
    exact = tokens * price / 1_000_000
    assert plan["estimated_usd"] == exact  # full precision: the figure the cap is compared with
    assert plan["price_usd_per_million_tokens"] == price
    assert plan["price_table_date"] == PRICE_TABLE_DATE
    assert plan["model"] == "text-embedding-3-small" and plan["within_cap"] is True


def test_plan_counts_bytes_not_characters_and_flags_a_cap_it_exceeds():
    plan = probe_pools.plan_probe(["ا" * 1000], "text-embedding-3-small", cap=1e-9, split="dev")
    assert plan["estimated_tokens"] >= math.ceil(2000 / probe_pools.BYTES_PER_TOKEN)
    assert plan["within_cap"] is False


def test_plan_for_a_model_without_a_price_stops_instead_of_guessing():
    with pytest.raises(SystemExit, match="No price recorded"):
        probe_pools.plan_probe(["q"], "unpriced-model-x", cap=1.0, split="dev")


# ---- the sealed report discloses totals and gate groups only ----------------------------------------


def sealed_inputs(n: int = 25):
    cases = [fab_case(i) for i in range(n)]
    cases += [fab_case(100 + i, behavior="not_found") for i in range(12)]
    rows = [
        {
            "id": c["id"],
            "split": "held_out",
            "expected": retrieval_probe.expected_names(c),
            **retrieval_probe.measure(
                [Hit("other.txt", 0.4)]
                + ([Hit(retrieval_probe.expected_names(c)[0], 0.6)] if i % 2 == 0 else []),
                retrieval_probe.expected_names(c),
            ),
        }
        for i, c in enumerate(c for c in cases if c["expected_behavior"] == "answer")
    ]
    refusal = [
        {"id": c["id"], **retrieval_probe.measure([Hit("other.txt", 0.3)], [])}
        for c in cases
        if c["expected_behavior"] == "not_found"
    ]
    return rows, refusal, cases


def test_sealed_report_has_totals_and_groups_and_no_case_text():
    rows, refusal, cases = sealed_inputs()
    report = probe_pools.sealed_probe_report(rows, refusal, cases, skipped_history=3)
    text = json.dumps(report)
    assert report["pool"] == "held_out" and report["answerable"]["total"]["n"] == 25
    assert report["answerable"]["total"]["found"] == 13
    assert "format_docx" in report["answerable"]["groups"]
    assert report["refusal"]["n"] == 12 and report["skipped_history"] == 3
    for case in cases:
        assert case["id"] not in text
        assert MARKER not in text
    assert "missed" not in text and "expected" not in text and "files" not in text
    assert small_cells(report) == []


def test_sealed_report_suppresses_a_cell_under_the_minimum():
    rows, refusal, cases = sealed_inputs(MIN_CELL + 5)
    # the first five answer cases are the only members of a fabricated small group
    small = {r["id"] for r in rows[:5]}
    cases = [{**c, "tags": ["ambiguous"]} if c["id"] in small else c for c in cases]
    report = probe_pools.sealed_probe_report(rows, refusal, cases, skipped_history=0)
    assert report["answerable"]["groups"]["ambiguous"] == {
        "suppressed": f"fewer than {MIN_CELL} cases"
    }
    assert small_cells(report) == []
    tiny = probe_pools.sealed_probe_report(rows[:4], refusal[:3], cases, skipped_history=0)
    assert tiny["answerable"]["total"] == {"suppressed": f"fewer than {MIN_CELL} cases"}
    assert tiny["refusal"] == {"suppressed": f"fewer than {MIN_CELL} cases"}


# ---- selecting the pools --------------------------------------------------------------------------------


@pytest.fixture
def no_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_pools, "validate", lambda *a, **k: [])
    monkeypatch.setattr(probe_pools, "files_to_check", lambda dataset, files: [])


def test_the_committed_pools_are_selected_by_split(no_validation):
    counts = {}
    for split in ("dev", "test", "regression", "all"):
        cases, held = probe_pools.select_probe_cases(split, [])
        counts[split] = len(cases)
        assert held is None
        assert all(c["split"] != "held_out" for c in cases)
    assert counts == {"dev": 201, "test": 81, "regression": 81, "all": 282}


def test_invalid_committed_cases_stop_before_anything_is_selected(monkeypatch):
    monkeypatch.setattr(probe_pools, "files_to_check", lambda dataset, files: [])
    monkeypatch.setattr(probe_pools, "validate", lambda *a, **k: ["x: broken"])
    with pytest.raises(SystemExit, match="x: broken"):
        probe_pools.select_probe_cases("dev", [])


class Sealed:
    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch, count: int = 40):
        self.dir = root / "owner-only"
        self.dir.mkdir()
        self.file = self.dir / "sealed.json"
        self.file.write_text(json.dumps({"cases": [fab_case(i) for i in range(count)]}))
        self.manifest = root / "freeze.json"
        monkeypatch.setattr(pools, "FREEZE_MANIFEST", self.manifest)
        monkeypatch.setenv(pools.HELD_OUT_ENV, str(self.file))

    def freeze(self) -> str:
        digest = review_gate.sha256_file(self.file)
        self.manifest.write_text(json.dumps({"held_out": {"sha256": digest}}))
        return digest

    def attest(self, digest: str) -> None:
        record = {
            "version": 1,
            "sealed_sha256": digest,
            "freeze_held_out_sha256": digest,
            "sheet_sha256": HEX,
            "reviewed": 36,
            "correct": 36,
            "gold_wrong": 0,
            "attested_at": "2026-01-01T00:00:00+00:00",
        }
        review_gate.attestation_path(self.file).write_text(json.dumps(record))


@pytest.fixture
def sealed(tmp_path, monkeypatch, no_validation) -> Sealed:
    return Sealed(tmp_path, monkeypatch)


def test_held_out_loads_only_through_a_valid_attestation(sealed):
    sealed.freeze()
    with pytest.raises(SystemExit, match="attestation"):
        probe_pools.select_probe_cases("held_out", [])
    sealed.attest(review_gate.sha256_file(sealed.file))
    cases, held = probe_pools.select_probe_cases("held_out", [])
    assert len(cases) == 40 and held == sealed.file.resolve()
    assert all(c["pool"] == "held_out" for c in cases)


def test_the_gate_runs_before_the_sealed_file_is_read(sealed):
    sealed.file.write_text("not json at all")
    with pytest.raises(SystemExit, match="attestation"):
        probe_pools.select_probe_cases("held_out", [])


def test_a_sealed_file_changed_after_the_review_is_refused(sealed):
    digest = sealed.freeze()
    sealed.attest(digest)
    sealed.file.write_text(json.dumps({"cases": [fab_case(1)]}))
    with pytest.raises(SystemExit, match="changed since"):
        probe_pools.select_probe_cases("held_out", [])


def test_held_out_without_the_environment_variable_or_inside_the_repo_is_refused(
    monkeypatch, sealed
):
    monkeypatch.delenv(pools.HELD_OUT_ENV)
    with pytest.raises(SystemExit, match=pools.HELD_OUT_ENV):
        probe_pools.select_probe_cases("held_out", [])
    monkeypatch.setenv(pools.HELD_OUT_ENV, str(Path(pools.__file__)))
    with pytest.raises(SystemExit, match="inside the repository"):
        probe_pools.select_probe_cases("held_out", [])


def test_a_held_out_problem_is_counted_and_never_described(sealed, monkeypatch):
    sealed.attest(sealed.freeze())
    monkeypatch.setattr(probe_pools, "validate", lambda *a, **k: [f"hog001: quote {MARKER}"] * 2)
    with pytest.raises(SystemExit) as raised:
        probe_pools.select_probe_cases("held_out", [])
    message = str(raised.value)
    assert "2 problem" in message and MARKER not in message and "hog001" not in message


# ---- run(): refusals come before the store, the meter and every provider call ---------------------------


def args(**kw: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "split": "dev",
        "frozen": True,
        "messy": False,
        "with_messy": False,
        "dataset": None,
        "phrasings": False,
        "passage": False,
        "threshold": None,
        "relative": None,
        "top_k": None,
        "store": None,
        "tag": None,
        "cap": 0.5,
        "plan": False,
    }
    return argparse.Namespace(**{**base, **kw})


class Reached(AssertionError):
    pass


@pytest.fixture
def untouched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Everything a refused run must not reach. A call is recorded and raises."""
    calls: list[str] = []

    def spy(name: str):
        def inner(*_a: Any, **_k: Any) -> Any:
            calls.append(name)
            raise Reached(name)

        return inner

    for name in ("require_verified_index", "session_factory", "HybridRetriever", "make_search"):
        monkeypatch.setattr(retrieval_probe, name, spy(name))
    return calls


@pytest.mark.parametrize(
    "kw",
    [
        {"split": "held_out", "phrasings": True},
        {"split": "held_out", "passage": True},
        {"split": "held_out", "threshold": 0.1},
        {"split": "held_out", "frozen": False},
        {"split": "regression", "frozen": False},
    ],
)
def test_a_prohibited_mode_stops_before_the_corpus_the_store_or_any_call(
    kw, monkeypatch, untouched
):
    def corpus(**_k: Any) -> Any:
        untouched.append("corpus_for")
        raise Reached

    monkeypatch.setattr(retrieval_probe, "corpus_for", corpus)
    with pytest.raises(SystemExit):
        asyncio.run(retrieval_probe.run(args(**kw)))
    assert untouched == []


def patch_free_parts(monkeypatch, cases: list[dict[str, Any]], held: Path | None = None) -> None:
    monkeypatch.setattr(retrieval_probe, "corpus_for", lambda **_k: [])
    monkeypatch.setattr(retrieval_probe, "verify", lambda files: None)
    monkeypatch.setattr(retrieval_probe, "select_probe_cases", lambda split, files: (cases, held))
    monkeypatch.setattr(
        retrieval_probe,
        "application_defaults",
        lambda: {"embedding_model": "text-embedding-3-small"},
    )


def test_a_held_out_run_without_attestation_never_reaches_the_store(sealed, monkeypatch, untouched):
    sealed.freeze()
    monkeypatch.setattr(retrieval_probe, "corpus_for", lambda **_k: [])
    monkeypatch.setattr(retrieval_probe, "verify", lambda files: None)
    with pytest.raises(SystemExit, match="attestation"):
        asyncio.run(retrieval_probe.run(args(split="held_out")))
    assert untouched == []


def test_plan_prints_the_estimate_and_touches_nothing_else(
    monkeypatch, untouched, capsys, tmp_path
):
    cases = [fab_case(i, split="dev") for i in range(5)]
    patch_free_parts(monkeypatch, cases)
    monkeypatch.setattr(retrieval_probe, "RESULTS", tmp_path / "results")
    asyncio.run(retrieval_probe.run(args(plan=True, phrasings=True)))
    out = capsys.readouterr().out
    plan = json.loads(out[: out.index("\nEstimate from")])
    assert plan["plan"]["embedding_calls"] == 20 and plan["within_cap"] is True
    assert plan["plan"]["model"] == "text-embedding-3-small"
    assert untouched == [] and not (tmp_path / "results").exists()


def test_an_estimate_above_the_cap_refuses_before_the_store(monkeypatch, untouched):
    patch_free_parts(monkeypatch, [fab_case(i, split="dev") for i in range(5)])
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(retrieval_probe.run(args(cap=1e-9)))
    assert untouched == []


def test_a_model_without_a_price_refuses_before_the_store(monkeypatch, untouched):
    patch_free_parts(monkeypatch, [fab_case(i, split="dev") for i in range(2)])
    monkeypatch.setattr(
        retrieval_probe, "application_defaults", lambda: {"embedding_model": "unpriced-model-x"}
    )
    with pytest.raises(SystemExit, match="No price recorded"):
        asyncio.run(retrieval_probe.run(args()))
    assert untouched == []


def test_a_verified_store_that_embeds_with_another_model_is_priced_again(monkeypatch):
    patch_free_parts(monkeypatch, [fab_case(i, split="dev") for i in range(5)])
    pricey = SimpleNamespace(
        embedding_model="gpt-5.4",  # a stand-in with a much higher recorded price
        retrieval_score_threshold=0.25,
        retrieval_top_k=8,
        retrieval_relative_threshold=0.7,
    )
    pricey.model_copy = lambda update: pricey  # type: ignore[attr-defined]

    async def verified(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(settings=pricey)

    def no_session(*_a: Any, **_k: Any) -> Any:
        raise Reached("session_factory")

    monkeypatch.setattr(retrieval_probe, "require_verified_index", verified)
    monkeypatch.setattr(retrieval_probe, "session_factory", no_session)
    cheap = 0.00001
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(retrieval_probe.run(args(cap=cheap)))


async def plain_search(query: str) -> list[Hit]:
    return [Hit("other.txt", 0.4)]


async def boom_search(query: str) -> list[Hit]:
    raise RuntimeError(f"{MARKER} {query}")


def wire_held_out_run(sealed: Sealed, monkeypatch, tmp_path: Path, *, search) -> None:
    """Everything a held-out run needs except the real store, with a fake search."""
    sealed.attest(sealed.freeze())
    monkeypatch.setattr(retrieval_probe, "corpus_for", lambda **_k: [])
    monkeypatch.setattr(retrieval_probe, "verify", lambda files: None)
    monkeypatch.setattr(
        retrieval_probe,
        "application_defaults",
        lambda: {"embedding_model": "text-embedding-3-small"},
    )
    settings = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        retrieval_score_threshold=0.25,
        retrieval_top_k=8,
        retrieval_relative_threshold=0.7,
    )
    settings.model_copy = lambda update: settings  # type: ignore[attr-defined]

    async def verified(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(settings=settings)

    class Db:
        async def __aenter__(self) -> "Db":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(retrieval_probe, "require_verified_index", verified)
    monkeypatch.setattr(retrieval_probe, "session_factory", lambda s: lambda: Db())
    monkeypatch.setattr(retrieval_probe, "HybridRetriever", lambda db, s: object())
    monkeypatch.setattr(retrieval_probe, "make_search", lambda retriever: search)
    monkeypatch.setattr(retrieval_probe, "RESULTS", tmp_path / "repo-results")


def test_a_held_out_run_writes_only_the_sealed_aggregate_outside_the_repo(
    sealed, monkeypatch, capsys, tmp_path
):
    wire_held_out_run(sealed, monkeypatch, tmp_path, search=plain_search)

    asyncio.run(retrieval_probe.run(args(split="held_out")))

    folder = sealed.dir / "heldout_results"
    written = list(folder.glob("retrieval_probe_*_held_out.json"))
    assert len(written) == 1 and not (tmp_path / "repo-results").exists()
    saved = written[0].read_text()
    shown = capsys.readouterr().out
    for text in (saved, shown):
        assert MARKER not in text and "hog0" not in text and "hog1" not in text
    report = json.loads(saved)
    assert report["held_out"]["answerable"]["total"]["n"] == 40
    assert "rows" not in report and "answerable_rows" not in report
    assert small_cells(report) == []


# ---- corrections round: --frozen --messy, fail-closed held-out, sanitized errors, exact cap ----------


@pytest.mark.parametrize("split", ["dev", "test", "regression", "all", "held_out"])
def test_frozen_with_messy_is_rejected_for_every_split_and_names_both_flags(split):
    with pytest.raises(SystemExit, match=r"--frozen.*--messy|--messy.*--frozen"):
        probe_pools.check_probe_mode(split, frozen=True, messy=True)


def test_messy_without_frozen_is_still_allowed():
    probe_pools.check_probe_mode("dev", frozen=False, messy=True)
    probe_pools.check_probe_mode("all", frozen=False, messy=True)


def test_frozen_with_messy_stops_before_the_corpus_the_store_or_any_call(monkeypatch, untouched):
    def corpus(**_k: Any) -> Any:
        untouched.append("corpus_for")
        raise Reached

    monkeypatch.setattr(retrieval_probe, "corpus_for", corpus)
    with pytest.raises(SystemExit, match="--messy"):
        asyncio.run(retrieval_probe.run(args(frozen=True, messy=True)))
    assert untouched == []


def test_a_missing_sealed_file_fails_closed_without_falling_back_to_another_pool(
    tmp_path, monkeypatch, untouched
):
    monkeypatch.setenv(pools.HELD_OUT_ENV, str(tmp_path / "owner-only" / "nothing.json"))
    monkeypatch.setattr(retrieval_probe, "corpus_for", lambda **_k: [])
    monkeypatch.setattr(retrieval_probe, "verify", lambda files: None)
    with pytest.raises(SystemExit, match="missing file"):
        asyncio.run(retrieval_probe.run(args(split="held_out")))
    assert untouched == []


def test_held_out_without_a_sealed_source_never_proceeds_even_if_selection_returns_none(
    monkeypatch, untouched
):
    patch_free_parts(monkeypatch, [fab_case(i) for i in range(12)], held=None)
    with pytest.raises(SystemExit, match="sealed"):
        asyncio.run(retrieval_probe.run(args(split="held_out")))
    assert untouched == []


@pytest.mark.parametrize(
    "boom",
    [KeyError(MARKER), ValueError(f"{MARKER}: hog001 quote"), TypeError(MARKER)],
)
def test_held_out_validation_exceptions_never_carry_case_content(sealed, monkeypatch, boom):
    sealed.attest(sealed.freeze())

    def explode(*_a: Any, **_k: Any) -> Any:
        raise boom

    monkeypatch.setattr(probe_pools, "validate", explode)
    with pytest.raises(SystemExit) as raised:
        probe_pools.select_probe_cases("held_out", [])
    shown = str(raised.value)
    assert MARKER not in shown and "hog001" not in shown
    assert type(boom).__name__ in shown and "withheld" in shown
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


@pytest.mark.parametrize("target", ["load_held_out", "prepare_case"])
def test_held_out_loading_exceptions_never_carry_case_content(sealed, monkeypatch, target):
    sealed.attest(sealed.freeze())

    def explode(*_a: Any, **_k: Any) -> Any:
        raise ValueError(f"{MARKER}: hog001 leaked")

    monkeypatch.setattr(probe_pools, target, explode)
    with pytest.raises(SystemExit) as raised:
        probe_pools.select_probe_cases("held_out", [])
    assert MARKER not in str(raised.value) and "hog001" not in str(raised.value)
    assert "ValueError" in str(raised.value) and raised.value.__suppress_context__


def test_the_review_gate_message_is_still_shown_because_it_names_no_case(sealed):
    sealed.freeze()
    with pytest.raises(SystemExit, match="attestation"):
        probe_pools.select_probe_cases("held_out", [])


def test_a_failing_held_out_search_is_reported_by_class_only(sealed, monkeypatch, capsys, tmp_path):
    wire_held_out_run(sealed, monkeypatch, tmp_path, search=boom_search)
    with pytest.raises(SystemExit) as raised:
        asyncio.run(retrieval_probe.run(args(split="held_out")))
    shown = str(raised.value) + capsys.readouterr().out
    assert MARKER not in shown and "RuntimeError" in shown and "withheld" in shown
    assert raised.value.__suppress_context__
    assert not (sealed.dir / "heldout_results").exists()
    assert not (tmp_path / "repo-results").exists()


def test_the_cap_is_compared_with_the_full_precision_estimate(monkeypatch, untouched):
    queries = [fab_case(i, split="dev") for i in range(1)]
    patch_free_parts(monkeypatch, queries)
    exact = probe_pools.plan_probe(
        retrieval_probe.planned_queries(queries, ["plain"]),
        "text-embedding-3-small",
        cap=1.0,
        split="dev",
    )["estimated_usd"]
    assert 0 < exact < 0.000005  # the case the old five-decimal rounding got wrong
    with pytest.raises(SystemExit, match="Refusing to start"):
        asyncio.run(retrieval_probe.run(args(cap=exact * 0.99)))
    assert untouched == []
    with pytest.raises(Reached):  # just above the exact estimate: allowed to reach the store gate
        asyncio.run(retrieval_probe.run(args(cap=exact * 1.01)))
    assert untouched == ["require_verified_index"]


def test_plan_within_cap_uses_the_exact_estimate():
    plan = probe_pools.plan_probe(["a" * 30] * 3, "text-embedding-3-small", cap=1e-6, split="dev")
    assert plan["estimated_usd"] < 1e-6 and plan["within_cap"] is True
    tight = probe_pools.plan_probe(["a" * 30] * 3, "text-embedding-3-small", cap=5e-7, split="dev")
    assert tight["within_cap"] is False
