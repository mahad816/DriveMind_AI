"""Tests for pure deterministic evaluation metric primitives."""

from __future__ import annotations

import pytest

from app.retrieval.query_router import QueryRoute
from evaluation.metrics import (
    all_expected_files_at_k,
    citation_metrics,
    expected_file_stage_survival,
    file_hit_at_k,
    file_ranking_metrics,
    file_recall_at_k,
    must_include_metrics,
    must_not_phrase_flags,
    normalize_text,
    prompt_source_metrics,
    route_matches,
)


def test_route_comparison_uses_enum_member_names_and_values() -> None:
    assert route_matches("CHITCHAT", QueryRoute.CHITCHAT)
    assert route_matches("GROUNDED_RAG", "grounded_rag")
    assert not route_matches("FILE_TARGET", QueryRoute.FILE_INVENTORY)
    assert not route_matches("NOT_A_ROUTE", QueryRoute.CHITCHAT)


def test_file_hit_and_recall_at_k() -> None:
    candidates = ["noise.txt", "alpha.txt", "beta.txt"]
    expected = ["alpha.txt", "beta.txt"]

    assert file_hit_at_k(candidates, expected, 1) is False
    assert file_hit_at_k(candidates, expected, 3) is True
    assert file_recall_at_k(candidates, expected, 1) == 0.0
    assert file_recall_at_k(candidates, expected, 2) == 0.5
    assert file_recall_at_k(candidates, expected, 3) == 1.0
    assert all_expected_files_at_k(candidates, expected, 2) is False
    assert all_expected_files_at_k(candidates, expected, 3) is True


def test_duplicate_chunks_do_not_fake_or_distort_file_ranking() -> None:
    metrics = file_ranking_metrics(
        ["alpha.txt", "alpha.txt", "beta.txt"],
        ["alpha.txt", "beta.txt"],
    )

    assert metrics.any_expected_file is True
    assert metrics.expected_file_recall == 1.0
    assert metrics.all_expected_files is True
    assert metrics.reciprocal_rank_by_file == (("alpha.txt", 1.0), ("beta.txt", 0.5))
    assert metrics.mean_expected_file_reciprocal_rank == 0.75


def test_ranking_metrics_include_missing_file_as_zero() -> None:
    metrics = file_ranking_metrics(["noise.txt", "alpha.txt"], ["alpha.txt", "missing.txt"])

    assert metrics.first_relevant_reciprocal_rank == 0.5
    assert metrics.expected_file_recall == 0.5
    assert metrics.reciprocal_rank_by_file == (("alpha.txt", 0.5), ("missing.txt", 0.0))
    assert metrics.mean_expected_file_reciprocal_rank == 0.25


def test_single_expected_file_ranking() -> None:
    metrics = file_ranking_metrics(["noise.txt", "alpha.txt"], ["alpha.txt"])

    assert metrics.first_relevant_reciprocal_rank == 0.5
    assert metrics.all_expected_files is True


def test_empty_retrieval_and_non_positive_k() -> None:
    metrics = file_ranking_metrics([], ["alpha.txt"])

    assert metrics.any_expected_file is False
    assert metrics.expected_file_recall == 0.0
    assert metrics.first_relevant_reciprocal_rank == 0.0
    assert file_hit_at_k(["alpha.txt"], ["alpha.txt"], 0) is False
    assert file_recall_at_k(["alpha.txt"], ["alpha.txt"], -1) == 0.0
    assert all_expected_files_at_k(["alpha.txt"], ["alpha.txt"], 0) is False


def test_empty_expected_files_are_not_applicable() -> None:
    metrics = file_ranking_metrics(["alpha.txt"], [])

    assert metrics.any_expected_file is None
    assert metrics.expected_file_recall is None
    assert metrics.all_expected_files is None
    assert metrics.first_relevant_reciprocal_rank is None
    assert metrics.mean_expected_file_reciprocal_rank is None
    assert file_hit_at_k(["alpha.txt"], [], 3) is None
    assert file_recall_at_k(["alpha.txt"], [], 3) is None
    assert all_expected_files_at_k(["alpha.txt"], [], 3) is None


def test_prompt_source_metrics_for_one_expected_and_unrelated_source() -> None:
    metrics = prompt_source_metrics(
        ["alpha.txt", "noise.txt"],
        ["alpha.txt"],
    )

    assert metrics.precision == 0.5
    assert metrics.unexpected_count == 1
    assert metrics.unexpected_sources == ("noise.txt",)


def test_prompt_source_metrics_deduplicate_sources_and_preserve_unexpected_order() -> None:
    metrics = prompt_source_metrics(
        ["alpha.txt", "noise-b.txt", "alpha.txt", "noise-a.txt", "noise-b.txt"],
        ["alpha.txt"],
    )

    assert metrics.precision == pytest.approx(1 / 3)
    assert metrics.unexpected_count == 2
    assert metrics.unexpected_sources == ("noise-b.txt", "noise-a.txt")


def test_prompt_source_metrics_support_multiple_and_all_expected_sources() -> None:
    metrics = prompt_source_metrics(
        ["beta.txt", "alpha.txt", "beta.txt"],
        ["alpha.txt", "beta.txt"],
    )

    assert metrics.precision == 1.0
    assert metrics.unexpected_count == 0
    assert metrics.unexpected_sources == ()


def test_prompt_source_metrics_report_zero_when_no_expected_source_is_present() -> None:
    metrics = prompt_source_metrics(
        ["noise-a.txt", "noise-b.txt"],
        ["alpha.txt"],
    )

    assert metrics.precision == 0.0
    assert metrics.unexpected_count == 2
    assert metrics.unexpected_sources == ("noise-a.txt", "noise-b.txt")


@pytest.mark.parametrize(
    ("prompt_files", "expected_files"),
    [
        (["alpha.txt"], []),
        ([], ["alpha.txt"]),
    ],
)
def test_prompt_source_metrics_are_not_applicable_without_both_sets(
    prompt_files: list[str], expected_files: list[str]
) -> None:
    metrics = prompt_source_metrics(prompt_files, expected_files)

    assert metrics.precision is None
    assert metrics.unexpected_count is None
    assert metrics.unexpected_sources == ()


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("CEDAR FALCON", "cedar falcon"),
        ("alpha\n  beta", "alpha beta"),
        ("PKR 1,200,000", "pkr 1200000"),
        ("78.79%", "78.79 percent"),
        ("11:00 AM", "11 am"),
        ("read\u2011only \u201cDrive\u201d", 'read-only "drive"'),
    ],
)
def test_text_normalization_handles_common_format_variants(left: str, right: str) -> None:
    assert normalize_text(left) == normalize_text(right)


def test_must_include_coverage_is_lexical_and_explicit() -> None:
    result = must_include_metrics("Alpha and beta are present.", ["alpha", "gamma"])

    assert tuple(match.matched for match in result.matches) == (True, False)
    assert result.coverage == 0.5
    assert result.all_present is False


def test_empty_must_include_is_not_applicable() -> None:
    result = must_include_metrics("Any answer", [])

    assert result.coverage is None
    assert result.all_present is None


def test_must_not_matches_are_diagnostic_flags_only() -> None:
    flags = must_not_phrase_flags(
        "It is false that Alpha was deployed.",
        ["Alpha was deployed", "Beta was deployed"],
    )

    assert tuple(flag.matched for flag in flags) == (True, False)


def test_stage_survival_preserves_stage_order_and_expected_file_set() -> None:
    stages = {
        "raw": ["alpha.txt", "noise.txt", "beta.txt"],
        "rrf": ["alpha.txt", "noise.txt"],
        "prompt": ["noise.txt"],
    }

    survival = expected_file_stage_survival(stages, ["alpha.txt", "beta.txt"])

    assert tuple(stage.stage for stage in survival) == ("raw", "rrf", "prompt")
    assert survival[0].present_expected_files == ("alpha.txt", "beta.txt")
    assert survival[0].expected_file_recall == 1.0
    assert survival[1].expected_file_recall == 0.5
    assert survival[2].any_expected_file is False


def test_citation_metrics_check_structure_and_expected_sources() -> None:
    metrics = citation_metrics(
        "Alpha is supported [1], and Beta is supported [2].",
        ["alpha.txt", "beta.txt"],
        ["alpha.txt", "beta.txt"],
    )

    assert metrics.citation_count == 2
    assert metrics.marker_count == 2
    assert metrics.marker_indices == (1, 2)
    assert metrics.markers_valid is True
    assert metrics.expected_file_recall == 1.0
    assert metrics.all_expected_files_cited is True
    assert metrics.unexpected_cited_files == ()


def test_citation_metrics_detect_invalid_and_unexpected_sources() -> None:
    metrics = citation_metrics(
        "Only the second source is cited [2].",
        ["alpha.txt", "noise.txt"],
        ["alpha.txt", "beta.txt"],
    )

    assert metrics.markers_valid is False
    assert metrics.expected_file_recall == 0.5
    assert metrics.all_expected_files_cited is False
    assert metrics.unexpected_cited_files == ("noise.txt",)


def test_citation_source_metrics_are_not_applicable_without_expected_files() -> None:
    metrics = citation_metrics("A direct answer.", [], [])

    assert metrics.markers_valid is True
    assert metrics.expected_file_recall is None
    assert metrics.all_expected_files_cited is None
