"""No paid-capable frozen command starts without a passing verification of the exact store (free, fabricated stores)."""

import argparse
import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from evaluation.rag_eval import (
    cli,
    first_step_probe,
    index_verify,
    probe_pools,
    retrieval_probe,
)
from evaluation.rag_eval.corpus import CorpusFile
from evaluation.rag_eval.frozen_corpus import FrozenCorpus
from evaluation.rag_eval.index_manifest import build_index_manifest, write_index_manifest
from evaluation.rag_eval.index_verify import (
    VerifiedIndex,
    indexed_files,
    require_verified_index,
)
from evaluation.rag_eval.target import FROZEN_STORE, EvalStore, eval_settings

from tests.evaluation.test_index_verify import TEXTS, faithful, replace_chunk, sha

STORE = FROZEN_STORE


@pytest.fixture(autouse=True)
def small_vectors(monkeypatch):
    """The fabricated vectors have 8 values; the real model has 1536."""
    monkeypatch.setattr(index_verify, "resolve_embedding_dimension", lambda model: 8)


def corpus(frozen_for: tuple[str, ...] = ("v1/a.txt",)) -> FrozenCorpus:
    """Two files; only the first has a frozen text digest, like a public PDF has none."""
    files = tuple(
        CorpusFile(p, "v1" if p.startswith("v1") else "public", sha("file:" + p), {}) for p in TEXTS
    )
    return FrozenCorpus(
        version_id="corpus-test",
        public_manifest_sha256="p" * 64,
        files=files,
        expected_chunks={},
        expected_text_sha256={p: sha(TEXTS[p]) for p in frozen_for},
    )


def reader(value):
    async def read(settings):
        if isinstance(value, Exception):
            raise value
        return value

    return read


def write_receipt(folder: Path, db, qd, *, origin="setup", store=STORE, corp=None, **edit) -> Path:
    settings = eval_settings(tool_agent=False, store=store)
    manifest = build_index_manifest(
        corp or corpus(),
        settings=settings,
        indexed=indexed_files(db),
        qdrant_points=len(qd.points),
        origin=origin,
    )
    for key, value in edit.items():
        manifest[key] = value
    return write_index_manifest(manifest, folder=folder)


def gate(tmp_path, db, qd, *, corp=None, store=STORE):
    return asyncio.run(
        require_verified_index(
            store,
            corpus=corp or corpus(),
            folder=tmp_path,
            read_db=reader(db),
            read_qdrant=reader(qd),
        )
    )


def test_a_verified_index_with_its_setup_receipt_passes_and_names_the_exact_store(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd)
    verified = gate(tmp_path, db, qd)
    assert isinstance(verified, VerifiedIndex)
    assert verified.store == STORE
    assert verified.settings.qdrant_collection == STORE.collection
    assert verified.settings.database_url.endswith("/" + STORE.database)
    assert verified.report.files == 2 and verified.report.problems == []


def test_a_missing_manifest_fails_closed(tmp_path):
    db, qd = faithful()
    with pytest.raises(SystemExit, match="no index manifest"):
        gate(tmp_path, db, qd)


def test_an_unreadable_manifest_fails_closed(tmp_path):
    db, qd = faithful()
    (tmp_path / "index_manifest_corpus-test_20260101_000000.json").write_text("{not json")
    with pytest.raises(SystemExit, match="manifest"):
        gate(tmp_path, db, qd)


def test_a_manifest_of_another_store_or_an_inspection_manifest_is_not_a_receipt(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd, origin="inspection")
    with pytest.raises(SystemExit, match="no index manifest"):
        gate(tmp_path, db, qd)
    write_receipt(tmp_path, db, qd, store=EvalStore.named("v4"))
    with pytest.raises(SystemExit, match="no index manifest"):
        gate(tmp_path, db, qd)


def test_a_manifest_for_another_corpus_version_fails_closed(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd, corp=dataclasses.replace(corpus(), version_id="other"))
    with pytest.raises(SystemExit, match="corpus version"):
        gate(tmp_path, db, qd)


def test_a_manifest_recording_another_embedding_model_fails_closed(tmp_path):
    db, qd = faithful()
    write_receipt(
        tmp_path, db, qd, embedding={"model": "text-embedding-3-large", "dimension": 3072}
    )
    with pytest.raises(SystemExit, match="embedding model"):
        gate(tmp_path, db, qd)


def test_the_newest_setup_receipt_decides(tmp_path):
    db, qd = faithful()
    good = write_receipt(tmp_path, db, qd, created_at="2026-01-01T00:00:00+00:00")
    bad = json.loads(good.read_text())
    bad["created_at"] = "2026-02-01T00:00:00+00:00"
    bad["corpus"]["version_id"] = "other"
    (tmp_path / "index_manifest_corpus-test_20260201_000000.json").write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="corpus version"):
        gate(tmp_path, db, qd)


def test_wrong_chunk_content_stops_the_command_even_though_counts_match(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd)
    broken = replace_chunk(db, "public/b.pdf", 1, text="stale chunk text")
    with pytest.raises(SystemExit, match="chunk 1"):
        gate(tmp_path, broken, qd)


def test_an_index_that_changed_after_its_receipt_is_stale(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd)
    files = dict(db.files)
    del files["public/b.pdf"]
    with pytest.raises(SystemExit, match="not in the index"):
        gate(tmp_path, dataclasses.replace(db, files=files), qd)
    # same files, but the receipt describes a different chunk total than the store now holds
    (file,) = db.files["v1/a.txt"]
    other_db, other_qd = faithful()
    write_receipt(tmp_path, other_db, other_qd, created_at="2099-01-01T00:00:00+00:00")
    shorter = dataclasses.replace(qd, points=qd.points[:-1])
    with pytest.raises(SystemExit):
        gate(tmp_path, db, shorter)


def test_a_qdrant_failure_stops_the_command_and_is_never_treated_as_unchecked(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd)
    with pytest.raises(SystemExit, match="Qdrant"):
        asyncio.run(
            require_verified_index(
                STORE,
                corpus=corpus(),
                folder=tmp_path,
                read_db=reader(db),
                read_qdrant=reader(ConnectionError("refused")),
            )
        )


def test_a_database_failure_stops_the_command(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd)
    with pytest.raises(SystemExit, match="database"):
        asyncio.run(
            require_verified_index(
                STORE,
                corpus=corpus(),
                folder=tmp_path,
                read_db=reader(OSError("down")),
                read_qdrant=reader(qd),
            )
        )


def test_an_empty_store_is_refused(tmp_path):
    db, qd = faithful()
    write_receipt(tmp_path, db, qd)
    empty_db = dataclasses.replace(db, files={})
    empty_qd = dataclasses.replace(qd, points=())
    with pytest.raises(SystemExit, match="not in the index"):
        gate(tmp_path, empty_db, empty_qd)


def test_the_gate_never_accepts_the_legacy_store(tmp_path):
    db, qd = faithful()
    from evaluation.rag_eval.target import LEGACY_STORE

    with pytest.raises(SystemExit, match="v2"):
        gate(tmp_path, db, qd, store=LEGACY_STORE)


# ---- the commands --------------------------------------------------------------------------------------


class Reached(Exception):
    pass


def verified() -> VerifiedIndex:
    from evaluation.rag_eval.index_verify import IndexReport

    return VerifiedIndex(
        store=STORE,
        settings=eval_settings(store=STORE),
        manifest="index_manifest_x.json",
        report=IndexReport(files=82, chunks=1508, points=1508, problems=[], limitations=[]),
    )


def namespace(**kw):
    return argparse.Namespace(
        **{
            "frozen": True,
            "messy": False,
            "with_messy": False,
            "dataset": None,
            "store": None,
            "split": "all",
            "ids": None,
            "cap": 1.0,
            "phrasings": False,
            "passage": False,
            "plan": False,
            "threshold": None,
            "relative": None,
            "top_k": None,
            "repeats": 1,
            "tag": None,
            **kw,
        }
    )


@pytest.fixture(autouse=True)
def cheap_validation(monkeypatch):
    """Validating cases reads the public PDFs (minutes); these tests are about what happens after it.
    The frozen retrieval probe validates in ``probe_pools``; the first-step probe still does it itself."""
    monkeypatch.setattr(probe_pools, "validate", lambda *a, **k: [])
    monkeypatch.setattr(probe_pools, "files_to_check", lambda *a: [])
    monkeypatch.setattr(retrieval_probe, "validate", lambda *a, **k: [])
    monkeypatch.setattr(first_step_probe, "validate", lambda *a: [])
    monkeypatch.setattr(first_step_probe, "files_to_check", lambda *a: [])
    for module in (retrieval_probe, first_step_probe):
        monkeypatch.setattr(module, "verify", lambda files: None)


@pytest.mark.parametrize("module", [retrieval_probe, first_step_probe])
def test_a_failed_verification_stops_each_probe_before_any_provider_or_store_use(
    module, monkeypatch
):
    async def refuse(*a, **k):
        raise SystemExit("INDEX NOT VERIFIED: nope")

    monkeypatch.setattr(module, "require_verified_index", refuse)
    monkeypatch.setattr(module, "session_factory", lambda *a: (_ for _ in ()).throw(Reached()))
    monkeypatch.setattr(module, "eval_settings", lambda **k: (_ for _ in ()).throw(Reached()))
    with pytest.raises(SystemExit, match="INDEX NOT VERIFIED"):
        asyncio.run(module.run(namespace(ids=["x"], split="dev")))


@pytest.mark.parametrize("module", [retrieval_probe, first_step_probe])
def test_each_probe_uses_the_settings_of_the_verified_store(module, monkeypatch):
    seen = {}

    async def accept(store, **k):
        seen["store"] = store
        return verified()

    def sessions(settings):
        seen["collection"] = settings.qdrant_collection
        raise Reached

    monkeypatch.setattr(module, "require_verified_index", accept)
    monkeypatch.setattr(module, "session_factory", sessions)
    monkeypatch.setattr(
        module, "eval_settings", lambda **k: pytest.fail("settings come from the gate")
    )
    with pytest.raises(Reached):
        asyncio.run(
            module.run(
                namespace(
                    ids=["none"],
                    split="dev",
                    cap=1.0,
                    phrasings=False,
                    threshold=None,
                    relative=None,
                    top_k=None,
                    repeats=1,
                    tag=None,
                )
            )
        )
    assert seen == {"store": STORE, "collection": "drivemind_eval_v3"}


@pytest.mark.parametrize("module", [retrieval_probe, first_step_probe])
def test_a_legacy_probe_is_not_gated_and_stays_on_the_legacy_store(module, monkeypatch):
    monkeypatch.setattr(
        module, "require_verified_index", lambda *a, **k: pytest.fail("legacy is not gated")
    )
    seen = {}

    def settings(**k):
        seen.update(k)
        raise Reached

    monkeypatch.setattr(module, "eval_settings", settings)
    with pytest.raises(Reached):
        asyncio.run(
            module.run(
                namespace(
                    frozen=False,
                    cap=1.0,
                    phrasings=False,
                    threshold=None,
                    relative=None,
                    top_k=None,
                    repeats=1,
                    tag=None,
                    split="dev",
                    ids=["none"],
                )
            )
        )
    assert "store" not in seen or seen["store"].name == "v2"


def cli_args(**kw):
    base = dict(
        command="run",
        file=None,
        cap=1.0,
        plan=False,
        repeats=1,
        pipelines=["legacy"],
        split="dev",
        category=None,
        limit=None,
        ids=None,
        dataset=["d.json"],
        threshold=None,
        relative=None,
        tag=None,
        no_claim_check=False,
        model=None,
        concurrency=1,
        frozen=True,
        with_messy=False,
        store=None,
    )
    return argparse.Namespace(**{**base, **kw})


def stub_cli(monkeypatch):
    case = {
        "id": "c1",
        "category": "x",
        "expected_behavior": "answer",
        "split": "dev",
        "question": "q",
    }
    monkeypatch.setattr(cli, "corpus_files", lambda **k: [])
    monkeypatch.setattr(cli, "verify", lambda files: None)
    monkeypatch.setattr(cli, "load_many", lambda names: {"cases": [case]})
    monkeypatch.setattr(cli, "validate", lambda *a: [])
    monkeypatch.setattr(cli, "files_to_check", lambda *a: [])
    monkeypatch.setattr(cli, "select", lambda cases, split: cases)
    monkeypatch.setattr(cli, "CostMeter", lambda cap: pytest.fail("no spend before the gate"))


def test_a_failed_verification_stops_the_paid_run_before_any_spend(monkeypatch):
    stub_cli(monkeypatch)

    async def refuse(*a, **k):
        raise SystemExit("INDEX NOT VERIFIED: nope")

    monkeypatch.setattr(cli, "require_verified_index", refuse)
    with pytest.raises(SystemExit, match="INDEX NOT VERIFIED"):
        asyncio.run(cli.run(cli_args()))


def test_the_run_plan_is_free_and_ungated(monkeypatch, capsys):
    stub_cli(monkeypatch)
    monkeypatch.setattr(
        cli, "require_verified_index", lambda *a, **k: pytest.fail("a plan is free")
    )
    asyncio.run(cli.run(cli_args(plan=True)))
    assert "Nothing was called" in capsys.readouterr().out


def test_a_failed_verification_stops_rescore_before_any_spend(monkeypatch, tmp_path):
    stub_cli(monkeypatch)
    saved = tmp_path / "r.json"
    saved.write_text(json.dumps({"rows": [], "model": "gpt-5.4-nano", "datasets": ["d.json"]}))
    monkeypatch.setattr(cli, "prepare_case", lambda c, n: c)

    async def refuse(*a, **k):
        raise SystemExit("INDEX NOT VERIFIED: nope")

    monkeypatch.setattr(cli, "require_verified_index", refuse)
    with pytest.raises(SystemExit, match="INDEX NOT VERIFIED"):
        asyncio.run(cli.rescore(cli_args(command="rescore", file=str(saved))))


def test_the_held_out_attestation_is_checked_before_the_index_gate_and_is_not_replaced_by_it(
    monkeypatch,
):
    stub_cli(monkeypatch)
    monkeypatch.setattr(cli, "held_out_path", lambda: Path("/nonexistent/held.json"))

    def refuse_attestation(path):
        raise SystemExit("held-out review not attested")

    monkeypatch.setattr(cli, "load_held_out", refuse_attestation)
    monkeypatch.setattr(
        cli, "require_verified_index", lambda *a, **k: pytest.fail("attestation comes first")
    )
    with pytest.raises(SystemExit, match="not attested"):
        asyncio.run(cli.run(cli_args(split="held_out", dataset=None)))
