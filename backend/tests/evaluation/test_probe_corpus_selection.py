"""Both probes select their corpus through the shared selector, and refuse a broken frozen corpus before any call (free)."""

import argparse
import asyncio

import pytest

from evaluation.rag_eval import first_step_probe, frozen_corpus, retrieval_probe


class Reached(Exception):
    pass


def namespace(**kw):
    return argparse.Namespace(
        **{"frozen": False, "messy": False, "with_messy": False, "dataset": None, **kw}
    )


@pytest.mark.parametrize("module", [retrieval_probe, first_step_probe])
def test_a_broken_frozen_corpus_stops_the_probe_before_any_store_is_touched(module, monkeypatch):
    monkeypatch.setattr(
        frozen_corpus, "frozen_problems", lambda root=None: ["v1/x.txt: file is missing"]
    )
    with pytest.raises(SystemExit, match="v1/x.txt"):
        asyncio.run(module.run(namespace(frozen=True)))


@pytest.mark.parametrize("module", [retrieval_probe, first_step_probe])
@pytest.mark.parametrize("frozen", [False, True])
def test_the_frozen_flag_reaches_the_selector(module, frozen, monkeypatch):
    seen = {}

    def spy(*, frozen: bool, with_messy: bool):
        seen.update(frozen=frozen, with_messy=with_messy)
        raise Reached

    monkeypatch.setattr(module, "corpus_for", spy)
    with pytest.raises(Reached):
        asyncio.run(module.run(namespace(frozen=frozen, messy=True)))
    assert seen == {"frozen": frozen, "with_messy": True}
