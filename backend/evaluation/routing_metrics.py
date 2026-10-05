"""Deterministic routing metrics with explicit applicability and denominators."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from app.routing.contract import Capability, RoutingMode
from evaluation.routing_baseline import RuleObservation
from evaluation.routing_dataset import RoutingCase


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_routing(
    cases: Sequence[RoutingCase], observations: Sequence[RuleObservation]
) -> dict[str, Any]:
    if len(cases) != len(observations):
        raise ValueError("cases and observations must align")
    tp: Counter[Capability] = Counter()
    fp: Counter[Capability] = Counter()
    fn: Counter[Capability] = Counter()
    confusion: dict[str, Counter[str]] = {}
    single_count = single_correct = mode_correct = 0
    compound_count = compound_expected = compound_matched = 0
    clarification_count = clarification_missed = 0
    social_count = social_false_positive = 0
    operation_expected = operation_inferable = operation_matched = 0
    for case, prediction in zip(cases, observations, strict=True):
        mode_correct += case.expected_mode == prediction.observable_mode
        if "social_decoration" in case.tags:
            social_count += 1
            social_false_positive += prediction.rule_route == Capability.CHITCHAT
        if case.expected_mode == RoutingMode.CLARIFY:
            clarification_count += 1
            clarification_missed += prediction.observable_mode != RoutingMode.CLARIFY
            continue  # No gold capability; do not manufacture a seventh route.
        expected = Counter(request.capability for request in case.expected_requests)
        predicted = Counter({prediction.rule_route: 1})
        matched = expected & predicted
        tp.update(matched)
        fp.update(predicted - expected)
        fn.update(expected - predicted)
        operation_expected += len(case.expected_requests)
        if prediction.operation is not None:
            operation_inferable += 1
            operation_matched += any(
                request.capability == prediction.rule_route
                and request.operation == prediction.operation
                for request in case.expected_requests
            )
        if case.expected_mode == RoutingMode.SINGLE:
            single_count += 1
            expected_route = case.expected_requests[0].capability
            single_correct += expected_route == prediction.rule_route
            confusion.setdefault(expected_route.value, Counter())[prediction.rule_route.value] += 1
        else:
            compound_count += 1
            compound_expected += len(case.expected_requests)
            compound_matched += sum(matched.values())
    per_capability = {}
    for capability in Capability:
        true, false, missing = tp[capability], fp[capability], fn[capability]
        per_capability[capability.value] = {
            "tp": true,
            "fp": false,
            "fn": missing,
            "precision": ratio(true, true + false),
            "recall": ratio(true, true + missing),
            "f1": ratio(2 * true, 2 * true + false + missing),
        }
    return {
        "mode_accuracy": ratio(mode_correct, len(cases)),
        "mode_correct": mode_correct,
        "case_count": len(cases),
        "single_six_route_accuracy": ratio(single_correct, single_count),
        "single_correct": single_correct,
        "single_count": single_count,
        "capabilities": per_capability,
        "capability_micro_precision": ratio(sum(tp.values()), sum(tp.values()) + sum(fp.values())),
        "capability_micro_recall": ratio(sum(tp.values()), sum(tp.values()) + sum(fn.values())),
        "capability_micro_f1": ratio(
            2 * sum(tp.values()), 2 * sum(tp.values()) + sum(fp.values()) + sum(fn.values())
        ),
        "compound_case_count": compound_count,
        "compound_omission_rate": ratio(compound_expected - compound_matched, compound_expected),
        "compound_omitted_operations": compound_expected - compound_matched,
        "compound_expected_operations": compound_expected,
        "clarification_miss_rate": ratio(clarification_missed, clarification_count),
        "clarification_count": clarification_count,
        "clarification_missed": clarification_missed,
        "social_decoration_false_positive_rate": ratio(social_false_positive, social_count),
        "social_decoration_count": social_count,
        "social_decoration_false_positives": social_false_positive,
        "operation_coverage": ratio(operation_matched, operation_expected),
        "operation_expected": operation_expected,
        "operation_inferable_predictions": operation_inferable,
        "operation_matched": operation_matched,
        "inferable_operation_accuracy": ratio(operation_matched, operation_inferable),
        "confusion_matrix_single": {key: dict(value) for key, value in sorted(confusion.items())},
        "policy": {
            "mode": "legacy observable single action, not semantic mode understanding",
            "capability": "multiset matching on SINGLE/COMPOUND; CLARIFY excluded",
            "operation": "only singleton operation vocabularies inferable; unknown counts uncovered",
            "compound": "one prediction can cover at most one gold operation, including duplicates",
            "arguments": "not observable or scored by legacy classifier",
        },
    }
