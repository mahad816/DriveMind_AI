"""The setup estimate comes from extracted and chunked text, not from file bytes (free)."""

import argparse
import asyncio
import json
import math

import pytest

from app.ingestion.chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_TARGET_CHUNK_SIZE, chunk_text
from evaluation.rag_eval import cli, corpus
from evaluation.rag_eval.embedding_estimate import (
    BYTES_PER_TOKEN,
    SAFETY_MARGIN,
    estimate_embedding,
)
from evaluation.rag_eval.meter import PRICE_TABLE_DATE, PRICES

MODEL = "text-embedding-3-small"


def test_the_estimate_counts_the_chunks_the_index_will_embed_including_their_overlap():
    text = ("Sentence number one is here. " * 400).strip()  # forces several overlapping chunks
    chunks = chunk_text(text)
    assert len(chunks) > 2
    plan = estimate_embedding({"a.txt": text}, MODEL)
    embedded_bytes = sum(len(c.text.encode()) for c in chunks)
    assert embedded_bytes > len(text.encode())  # the overlap is real, and it is counted
    assert plan["chunks"] == len(chunks)
    assert plan["chunk_utf8_bytes"] == embedded_bytes
    raw = math.ceil(embedded_bytes / BYTES_PER_TOKEN)
    assert plan["raw_tokens"] == raw
    assert plan["estimated_tokens"] == math.ceil(raw * SAFETY_MARGIN)


def test_the_estimate_uses_the_recorded_price_of_the_configured_model_and_does_not_edit_it():
    before = dict(PRICES[MODEL])
    plan = estimate_embedding({"a.txt": "x" * 9000}, MODEL)
    expected = plan["estimated_tokens"] * PRICES[MODEL]["input"] / 1_000_000
    assert plan["estimated_usd"] == pytest.approx(expected, abs=1e-5)
    assert plan["price_usd_per_million_tokens"] == PRICES[MODEL]["input"]
    assert plan["price_table_date"] == PRICE_TABLE_DATE
    assert PRICES[MODEL] == before


def test_the_estimate_states_its_model_method_and_assumptions():
    plan = estimate_embedding({"a.txt": "hello world " * 50}, MODEL)
    assert plan["model"] == MODEL
    assert plan["chunk_target_size"] == DEFAULT_TARGET_CHUNK_SIZE
    assert plan["chunk_overlap"] == DEFAULT_CHUNK_OVERLAP
    text = " ".join(plan["assumptions"])
    for word in ("no tokenizer", "overlap", "safety margin", "conservative estimate"):
        assert word in text


def test_non_latin_text_is_not_underestimated():
    urdu = "یہ ایک اردو جملہ ہے جو آزمائش کے لیے لکھا گیا ہے۔ " * 40
    plan = estimate_embedding({"u.txt": urdu}, MODEL)
    assert plan["estimated_tokens"] >= len(urdu) * 0.5  # UTF-8 bytes, never characters


def test_a_model_without_a_recorded_price_is_refused():
    with pytest.raises(KeyError, match="no price recorded"):
        estimate_embedding({"a.txt": "x"}, "text-embedding-unknown")


def test_empty_text_costs_nothing():
    plan = estimate_embedding({"a.txt": "   "}, MODEL)
    assert plan["chunks"] == 0 and plan["estimated_tokens"] == 0 and plan["estimated_usd"] == 0


# ---- the setup command ---------------------------------------------------------------------------------


def args(**kw):
    return argparse.Namespace(
        **{"plan": True, "cap": 1.0, "frozen": False, "with_messy": False, "store": None, **kw}
    )


def fake_texts(monkeypatch, body: str):
    monkeypatch.setattr(corpus, "extract_text", lambda file: body)
    monkeypatch.setattr(cli, "extract_text", lambda file: body, raising=False)
    monkeypatch.setattr("evaluation.rag_eval.embedding_estimate.extract_text", lambda f: body)


def test_the_plan_is_priced_from_extracted_text_not_from_file_bytes(monkeypatch, capsys):
    fake_texts(monkeypatch, "short text")  # every file extracts to a few bytes, whatever its size
    asyncio.run(cli.setup(args()))
    out = capsys.readouterr().out
    plan = json.loads(out.split("\nEstimate")[0])["plan"]
    assert "megabytes" not in plan
    assert plan["embedding"]["chunks"] == plan["corpus_files"]
    assert plan["estimated_usd"] == plan["embedding"]["estimated_usd"] < 0.0001
    assert plan["embedding"]["model"] == MODEL


def test_the_plan_never_calls_a_provider_or_touches_a_store(monkeypatch, capsys):
    fake_texts(monkeypatch, "short text")
    for name in ("ensure_database", "migrate", "ingest", "eval_settings"):
        monkeypatch.setattr(cli, name, lambda *a, **k: pytest.fail("a plan touches nothing"))
    asyncio.run(cli.setup(args()))
    assert "Nothing was called or written" in capsys.readouterr().out


def test_a_run_whose_estimate_is_above_the_cap_is_refused_before_any_store_is_touched(monkeypatch):
    fake_texts(monkeypatch, "word " * 400_000)
    for name in ("ensure_database", "migrate", "ingest", "eval_settings"):
        monkeypatch.setattr(cli, name, lambda *a, **k: pytest.fail("refused before any work"))
    with pytest.raises(SystemExit, match="above the"):
        asyncio.run(cli.setup(args(plan=False, cap=0.001)))
