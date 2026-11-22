"""The index manifest records what the evaluation index holds and is checked against the frozen corpus (free).

Nothing here calls a provider or opens a database: the per-file figures a real index would report are
fabricated, and the database statement is inspected rather than executed.
"""

import argparse
import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.ingestion.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_TARGET_CHUNK_SIZE
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION
from evaluation.rag_eval import cli
from evaluation.rag_eval.frozen_corpus import FrozenCorpus, frozen_corpus
from evaluation.rag_eval.index_manifest import (
    IndexedFile,
    build_index_manifest,
    index_problems,
    indexed_statement,
    write_index_manifest,
)
from evaluation.rag_eval.target import EVAL_COLLECTION, EVAL_USER_ID, eval_settings

CORPUS = frozen_corpus()


def faithful_index(corpus: FrozenCorpus = CORPUS) -> dict[str, IndexedFile]:
    """What a correct index would report: frozen chunk counts where frozen, a plausible count for public files."""
    return {
        f.path: IndexedFile(
            chunks=corpus.expected_chunks.get(f.path, 7),
            text_sha256=corpus.expected_text_sha256.get(f.path, "a" * 64),
            pipeline_version=EXTRACTION_PIPELINE_VERSION,
            status="indexed",
        )
        for f in corpus.files
    }


def manifest_for(indexed: dict[str, IndexedFile], points: int | None = None) -> dict[str, Any]:
    total = sum(i.chunks for i in indexed.values())
    return build_index_manifest(
        CORPUS,
        settings=eval_settings(tool_agent=False),
        indexed=indexed,
        qdrant_points=total if points is None else points,
    )


def test_a_faithful_index_manifest_is_consistent_with_the_corpus():
    manifest = manifest_for(faithful_index())
    assert index_problems(manifest, CORPUS) == []


def test_the_manifest_records_everything_the_ticket_asks_for():
    indexed = faithful_index()
    manifest = manifest_for(indexed)
    assert manifest["corpus"]["version_id"] == CORPUS.version_id
    assert manifest["corpus"]["files_digest"] == CORPUS.files_digest
    assert manifest["corpus"]["public_manifest_sha256"] == CORPUS.public_manifest_sha256
    assert manifest["embedding"]["model"] == eval_settings().embedding_model
    assert isinstance(manifest["embedding"]["dimension"], int)
    assert manifest["pipeline"] == {
        "extraction_pipeline_version": EXTRACTION_PIPELINE_VERSION,
        "chunk_target_size": DEFAULT_TARGET_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
    }
    assert manifest["store"]["collection"] == EVAL_COLLECTION
    assert set(manifest["files"]) == {f.path for f in CORPUS.files}
    first = next(iter(manifest["files"].values()))
    assert {"kind", "sha256", "chunks", "text_sha256", "status"} <= set(first)
    assert manifest["totals"]["files"] == len(CORPUS.files)
    assert manifest["totals"]["chunks"] == sum(i.chunks for i in indexed.values())
    assert "retrieval_top_k" in manifest["settings"] and "fts_language" in manifest["settings"]
    json.dumps(manifest)  # plain data only


def test_no_expected_chunk_count_is_stored_for_public_files():
    manifest = manifest_for(faithful_index())
    public = [v for p, v in manifest["files"].items() if p.startswith("public/")]
    assert public and all(v["expected_chunks"] is None for v in public)
    frozen = [v for p, v in manifest["files"].items() if not p.startswith("public/")]
    assert all(isinstance(v["expected_chunks"], int) for v in frozen)


def test_a_missing_file_in_the_index_is_named():
    indexed = faithful_index()
    del indexed["v1/cooperative_bylaws.txt"]
    problems = index_problems(manifest_for(indexed), CORPUS)
    assert any("v1/cooperative_bylaws.txt" in p and "not in the index" in p for p in problems)


def test_an_extra_file_in_the_index_is_named():
    indexed = faithful_index()
    indexed["synthetic/old_leftover.txt"] = IndexedFile(
        3, "b" * 64, EXTRACTION_PIPELINE_VERSION, "indexed"
    )
    problems = index_problems(manifest_for(indexed), CORPUS)
    assert any(
        "synthetic/old_leftover.txt" in p and "not in the frozen corpus" in p for p in problems
    )


def test_a_frozen_chunk_count_mismatch_is_named():
    indexed = faithful_index()
    bad = "v1/cooperative_bylaws.txt"
    old = indexed[bad]
    indexed[bad] = IndexedFile(old.chunks + 1, old.text_sha256, old.pipeline_version, old.status)
    problems = index_problems(manifest_for(indexed), CORPUS)
    assert any(bad in p and "chunks" in p for p in problems)


def test_changed_stored_text_is_named_even_when_the_chunk_count_matches():
    indexed = faithful_index()
    bad = "synthetic/budget_2026.txt"
    old = indexed[bad]
    indexed[bad] = IndexedFile(old.chunks, "c" * 64, old.pipeline_version, old.status)
    assert any(bad in p and "text" in p for p in index_problems(manifest_for(indexed), CORPUS))


def test_a_file_that_is_not_indexed_or_has_no_chunks_is_named():
    indexed = faithful_index()
    indexed["public/nist_sp800_145.pdf"] = IndexedFile(
        0, "a" * 64, EXTRACTION_PIPELINE_VERSION, "skipped"
    )
    problems = index_problems(manifest_for(indexed), CORPUS)
    assert any("nist_sp800_145.pdf" in p and "indexed" in p for p in problems)
    assert any("nist_sp800_145.pdf" in p and "no chunks" in p for p in problems)


def test_a_stale_extraction_pipeline_version_is_named():
    indexed = faithful_index()
    bad = "public/nist_sp800_145.pdf"
    old = indexed[bad]
    indexed[bad] = IndexedFile(
        old.chunks, old.text_sha256, EXTRACTION_PIPELINE_VERSION - 1, old.status
    )
    assert any(bad in p and "pipeline" in p for p in index_problems(manifest_for(indexed), CORPUS))


def test_a_vector_count_that_differs_from_the_chunk_total_is_named():
    indexed = faithful_index()
    total = sum(i.chunks for i in indexed.values())
    problems = index_problems(manifest_for(indexed, points=total - 1), CORPUS)
    assert any("vector" in p for p in problems)


def test_an_unread_vector_store_is_not_a_failure_but_is_recorded_as_unchecked():
    indexed = faithful_index()
    manifest = build_index_manifest(
        CORPUS, settings=eval_settings(tool_agent=False), indexed=indexed, qdrant_points=None
    )
    assert manifest["totals"]["qdrant_points"] is None
    assert index_problems(manifest, CORPUS) == []


def test_a_manifest_built_for_another_corpus_version_is_named():
    manifest = manifest_for(faithful_index())
    other = copy.deepcopy(manifest)
    other["corpus"]["version_id"] = "m1-corpus-v1-000000000000"
    assert any("corpus version" in p for p in index_problems(other, CORPUS))
    other = copy.deepcopy(manifest)
    other["corpus"]["files_digest"] = "0" * 64
    assert any("files digest" in p for p in index_problems(other, CORPUS))


def test_edited_totals_are_named():
    manifest = manifest_for(faithful_index())
    manifest["totals"]["chunks"] += 1
    manifest["totals"]["files"] -= 1
    problems = index_problems(manifest, CORPUS)
    assert any("total chunks" in p for p in problems)
    assert any("total files" in p for p in problems)


def test_a_changed_chunking_setting_is_named():
    manifest = manifest_for(faithful_index())
    manifest["pipeline"]["chunk_target_size"] += 1
    assert any("chunk_target_size" in p for p in index_problems(manifest, CORPUS))


# ---- isolation from application data -----------------------------------------------------------------------


def test_the_database_read_is_scoped_to_the_evaluation_user_only():
    compiled = indexed_statement().compile(dialect=postgresql.dialect())
    assert EVAL_USER_ID in compiled.params.values()
    assert "drive_files.user_id" in str(compiled)
    assert "SELECT" in str(compiled).upper() and "DELETE" not in str(compiled).upper()


def test_a_non_evaluation_store_is_refused_before_anything_is_read():
    from evaluation.rag_eval.index_manifest import read_indexed

    unsafe = eval_settings(tool_agent=False).model_copy(
        update={"database_url": "postgresql+asyncpg://u:p@127.0.0.1:5432/drivemind"}
    )
    with pytest.raises(RuntimeError, match="loopback drivemind_eval"):
        asyncio.run(read_indexed(unsafe))


def test_the_manifest_is_written_only_into_the_ignored_results_folder(tmp_path: Path):
    manifest = manifest_for(faithful_index())
    path = write_index_manifest(manifest, folder=tmp_path)
    assert path.parent == tmp_path and json.loads(path.read_text()) == manifest
    from evaluation.rag_eval.index_manifest import DEFAULT_FOLDER

    assert DEFAULT_FOLDER == cli.RESULTS


# ---- the setup command -------------------------------------------------------------------------------------


def args(**kw: Any) -> argparse.Namespace:
    base = {"plan": True, "cap": 1.0, "frozen": False, "with_messy": False}
    return argparse.Namespace(**{**base, **kw})


def test_setup_plan_for_the_frozen_corpus_counts_every_file_and_calls_nothing(capsys):
    asyncio.run(cli.setup(args(frozen=True)))
    plan = json.loads(capsys.readouterr().out.split("\nEstimate")[0])["plan"]
    assert plan["corpus_files"] == len(CORPUS.files)


def test_setup_plan_for_the_legacy_corpus_is_unchanged(capsys):
    asyncio.run(cli.setup(args()))
    legacy = json.loads(capsys.readouterr().out.split("\nEstimate")[0])["plan"]["corpus_files"]
    assert legacy == len(cli.corpus_files(with_messy=False)) < len(CORPUS.files)


def test_frozen_and_with_messy_cannot_be_combined():
    with pytest.raises(SystemExit):
        cli.corpus_files(with_messy=True, frozen=True)


def test_setup_refuses_a_broken_frozen_corpus_before_any_spend(monkeypatch, capsys):
    from evaluation.rag_eval import frozen_corpus as fc

    monkeypatch.setattr(fc, "frozen_problems", lambda root=None: ["v1/x.txt: file is missing"])
    with pytest.raises(SystemExit, match="v1/x.txt"):
        asyncio.run(cli.setup(args(frozen=True)))
