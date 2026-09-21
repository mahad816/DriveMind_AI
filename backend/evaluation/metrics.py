"""Pure deterministic metrics for diagnostic RAG evaluation.

Text checks in this module are lexical diagnostics only. They do not establish
semantic correctness or citation support and must not be treated as an LLM judge.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.retrieval.query_router import QueryRoute

_TYPOGRAPHIC_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


@dataclass(frozen=True)
class PhraseMatch:
    """One lexical phrase check against a normalized answer."""

    phrase: str
    matched: bool


@dataclass(frozen=True)
class MustIncludeMetrics:
    """Lexical coverage of required answer anchors."""

    matches: tuple[PhraseMatch, ...]
    coverage: float | None
    all_present: bool | None


@dataclass(frozen=True)
class FileRankingMetrics:
    """File-level ranking metrics after repeated chunk filenames are collapsed."""

    any_expected_file: bool | None
    expected_file_recall: float | None
    all_expected_files: bool | None
    first_relevant_reciprocal_rank: float | None
    reciprocal_rank_by_file: tuple[tuple[str, float], ...]
    mean_expected_file_reciprocal_rank: float | None


@dataclass(frozen=True)
class StageFileSurvival:
    """Expected-file presence at one named retrieval pipeline stage."""

    stage: str
    present_expected_files: tuple[str, ...]
    any_expected_file: bool | None
    expected_file_recall: float | None
    all_expected_files: bool | None


@dataclass(frozen=True)
class CitationMetrics:
    """Structural and source-file citation diagnostics, not semantic faithfulness."""

    citation_count: int
    marker_count: int
    marker_indices: tuple[int, ...]
    markers_valid: bool
    cited_filenames: tuple[str, ...]
    expected_file_recall: float | None
    all_expected_files_cited: bool | None
    unexpected_cited_files: tuple[str, ...]


def normalize_text(value: str) -> str:
    """Normalize common formatting variants for deterministic lexical matching."""
    normalized = unicodedata.normalize("NFKC", value).translate(_TYPOGRAPHIC_TRANSLATION)
    normalized = normalized.casefold()
    normalized = re.sub(r"\b([ap])\s*\.?\s*m\.?\b", r"\1m", normalized)
    normalized = re.sub(r"\b(\d{1,2}):00\s*(am|pm)\b", r"\1 \2", normalized)
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    normalized = normalized.replace("%", " percent ")
    return " ".join(normalized.split())


def phrase_matches(answer: str, phrases: Sequence[str]) -> tuple[PhraseMatch, ...]:
    """Return normalized substring matches for each phrase in input order."""
    normalized_answer = normalize_text(answer)
    return tuple(
        PhraseMatch(phrase=phrase, matched=normalize_text(phrase) in normalized_answer)
        for phrase in phrases
    )


def must_include_metrics(answer: str, required_phrases: Sequence[str]) -> MustIncludeMetrics:
    """Calculate lexical required-anchor coverage, or N/A when none are required."""
    matches = phrase_matches(answer, required_phrases)
    if not matches:
        return MustIncludeMetrics(matches=(), coverage=None, all_present=None)
    matched_count = sum(match.matched for match in matches)
    return MustIncludeMetrics(
        matches=matches,
        coverage=matched_count / len(matches),
        all_present=matched_count == len(matches),
    )


def must_not_phrase_flags(
    answer: str, prohibited_phrases: Sequence[str]
) -> tuple[PhraseMatch, ...]:
    """Flag lexical occurrences for review; a match is not proof of semantic failure."""
    return phrase_matches(answer, prohibited_phrases)


def file_ranking_metrics(
    candidate_filenames: Sequence[str],
    expected_files: Sequence[str],
) -> FileRankingMetrics:
    """Calculate file-level ranking metrics using each candidate file's first appearance."""
    expected = _unique(expected_files)
    if not expected:
        return FileRankingMetrics(None, None, None, None, (), None)

    ranked_files = _unique(candidate_filenames)
    rank_by_file = {filename: rank for rank, filename in enumerate(ranked_files, start=1)}
    expected_set = set(expected)
    reciprocal_ranks = tuple(
        (filename, 1.0 / rank_by_file[filename] if filename in rank_by_file else 0.0)
        for filename in expected
    )
    found_count = sum(filename in rank_by_file for filename in expected)
    positive_ranks = [rank for filename, rank in rank_by_file.items() if filename in expected_set]
    first_rr = 1.0 / min(positive_ranks) if positive_ranks else 0.0
    return FileRankingMetrics(
        any_expected_file=found_count > 0,
        expected_file_recall=found_count / len(expected),
        all_expected_files=found_count == len(expected),
        first_relevant_reciprocal_rank=first_rr,
        reciprocal_rank_by_file=reciprocal_ranks,
        mean_expected_file_reciprocal_rank=(
            sum(value for _, value in reciprocal_ranks) / len(reciprocal_ranks)
        ),
    )


def file_hit_at_k(
    candidate_filenames: Sequence[str], expected_files: Sequence[str], k: int
) -> bool | None:
    """Return whether any expected file appears in the first K unique files."""
    expected = set(expected_files)
    if not expected:
        return None
    if k <= 0:
        return False
    return bool(expected.intersection(_unique(candidate_filenames)[:k]))


def file_recall_at_k(
    candidate_filenames: Sequence[str], expected_files: Sequence[str], k: int
) -> float | None:
    """Return expected-file set recall in the first K unique files."""
    expected = set(expected_files)
    if not expected:
        return None
    if k <= 0:
        return 0.0
    return len(expected.intersection(_unique(candidate_filenames)[:k])) / len(expected)


def all_expected_files_at_k(
    candidate_filenames: Sequence[str], expected_files: Sequence[str], k: int
) -> bool | None:
    """Return whether all expected files appear in the first K unique files."""
    expected = set(expected_files)
    if not expected:
        return None
    if k <= 0:
        return False
    return expected.issubset(_unique(candidate_filenames)[:k])


def expected_file_stage_survival(
    stages: Mapping[str, Sequence[str]],
    expected_files: Sequence[str],
) -> tuple[StageFileSurvival, ...]:
    """Compare expected-file presence across ordered, named pipeline stages."""
    expected = _unique(expected_files)
    expected_set = set(expected)
    results: list[StageFileSurvival] = []
    for stage, candidates in stages.items():
        present_set = expected_set.intersection(_unique(candidates))
        present = tuple(filename for filename in expected if filename in present_set)
        if not expected:
            results.append(StageFileSurvival(stage, (), None, None, None))
            continue
        results.append(
            StageFileSurvival(
                stage=stage,
                present_expected_files=present,
                any_expected_file=bool(present),
                expected_file_recall=len(present) / len(expected),
                all_expected_files=len(present) == len(expected),
            )
        )
    return tuple(results)


def route_matches(expected_route: str, observed_route: QueryRoute | str | None) -> bool:
    """Compare a gold enum member name with a production route value or enum."""
    expected_name = _route_name(expected_route)
    observed_name = _route_name(observed_route)
    return expected_name is not None and expected_name == observed_name


def citation_metrics(
    answer: str,
    citation_filenames: Sequence[str],
    expected_files: Sequence[str],
) -> CitationMetrics:
    """Score citation numbering and source filenames without judging claim support."""
    marker_indices = tuple(int(value) for value in re.findall(r"\[(\d+)\]", answer))
    valid_indices = set(range(1, len(citation_filenames) + 1))
    observed_indices = set(marker_indices)
    markers_valid = observed_indices == valid_indices and all(index > 0 for index in marker_indices)

    cited_filenames = _unique(citation_filenames)
    expected = set(expected_files)
    cited = set(cited_filenames)
    if expected:
        recall: float | None = len(expected.intersection(cited)) / len(expected)
        all_cited: bool | None = expected.issubset(cited)
    else:
        recall = None
        all_cited = None

    return CitationMetrics(
        citation_count=len(citation_filenames),
        marker_count=len(marker_indices),
        marker_indices=marker_indices,
        markers_valid=markers_valid,
        cited_filenames=cited_filenames,
        expected_file_recall=recall,
        all_expected_files_cited=all_cited,
        unexpected_cited_files=tuple(
            filename for filename in cited_filenames if filename not in expected
        ),
    )


def _route_name(route: QueryRoute | str | None) -> str | None:
    if route is None:
        return None
    if isinstance(route, QueryRoute):
        return route.name
    candidate = route.strip()
    if not candidate:
        return None
    upper = candidate.upper()
    if upper in QueryRoute.__members__:
        return upper
    try:
        return QueryRoute(candidate.casefold()).name
    except ValueError:
        return None


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
