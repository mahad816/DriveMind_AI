"""Supplemental frozen-gold analysis; existing core scoring is unchanged."""

from collections import Counter, defaultdict
from typing import Any

from app.routing.contract import RoutingMode
from app.routing.semantic import ObservationStatus, ProviderObservation
from evaluation.jev_metrics import calibration, expected_labels, score_jev
from evaluation.routing_baseline import observe_rules
from evaluation.routing_dataset import RoutingCase
from evaluation.routing_metrics import ratio, score_routing


def labels(obs: ProviderObservation) -> list[str]:
    if obs.status != ObservationStatus.SUCCESS or obs.prediction is None:
        return []
    return [
        f"{r.capability.value}:{r.operation.value if r.operation else 'UNKNOWN'}"
        for r in obs.prediction.requests
    ]


def analysis(cases: list[RoutingCase], observations: list[ProviderObservation]) -> dict[str, Any]:
    core = score_jev(cases, observations)
    groups: dict[str, list[int]] = defaultdict(list)
    operation_tp: Counter[str] = Counter()
    operation_fp: Counter[str] = Counter()
    operation_fn: Counter[str] = Counter()
    compound_exact = compound_ordered = compound_total = compound_ops = compound_matched = (
        compound_extra
    ) = 0
    clarify_total = clarify_mode = clarify_reason = 0
    comparison = []
    relevant_samples: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    diagnostic_samples: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    semantic_errors = []
    disagreements: Counter[str] = Counter()
    for index, (case, obs) in enumerate(zip(cases, observations, strict=True)):
        gold = expected_labels(case)
        predicted = labels(obs)
        wanted, actual = Counter(gold), Counter(predicted)
        matched = wanted & actual
        if case.expected_mode != RoutingMode.CLARIFY:
            operation_tp.update(matched)
            operation_fp.update(actual - wanted)
            operation_fn.update(wanted - actual)
        groups["mode:" + case.expected_mode.value].append(index)
        groups["difficulty:" + case.difficulty].append(index)
        for tag in case.tags:
            groups["tag:" + tag].append(index)
        for capability in {r.capability.value for r in case.expected_requests}:
            groups["capability:" + capability].append(index)
        for operation in {r.operation.value for r in case.expected_requests}:
            groups["operation:" + operation].append(index)
        prediction = obs.prediction if obs.status == ObservationStatus.SUCCESS else None
        if case.expected_mode == RoutingMode.COMPOUND:
            compound_total += 1
            compound_ops += len(gold)
            compound_matched += sum(matched.values())
            compound_extra += sum((actual - wanted).values())
            compound_exact += bool(
                prediction and prediction.mode == RoutingMode.COMPOUND and wanted == actual
            )
            compound_ordered += bool(
                prediction and prediction.mode == RoutingMode.COMPOUND and gold == predicted
            )
        if case.expected_mode == RoutingMode.CLARIFY:
            clarify_total += 1
            mode_ok = bool(prediction and prediction.mode == RoutingMode.CLARIFY)
            clarify_mode += mode_ok
            clarify_reason += bool(
                mode_ok
                and prediction
                and prediction.clarification_reason == case.expected_clarification_reason
            )
        rule = observe_rules(case)
        if case.expected_mode == RoutingMode.SINGLE:
            rule_ok = rule.rule_route == case.expected_requests[0].capability
            semantic_ok = bool(
                prediction
                and prediction.mode == RoutingMode.SINGLE
                and len(prediction.requests) == 1
                and prediction.requests[0].capability == case.expected_requests[0].capability
            )
            outcome = (
                "both_correct"
                if rule_ok and semantic_ok
                else "rule_win"
                if rule_ok
                else "typesafe_win"
                if semantic_ok
                else "both_wrong"
            )
            comparison.append(
                {
                    "id": case.id,
                    "question": case.question,
                    "outcome": outcome,
                    "gold": gold,
                    "rule": rule.rule_route.value,
                    "typesafe": predicted,
                }
            )
        if obs.assembly_diagnostics:
            disagreements.update(obs.assembly_diagnostics.disagreement_flags)
        # Keep valid per-question distributions separate, including clarification reason.
        if obs.status != ObservationStatus.SUCCESS:
            continue
        targets = {
            "mode": case.expected_mode.value,
            "clarification": case.expected_clarification_reason.value
            if case.expected_clarification_reason
            else "NONE",
            **{f"operation_{i + 1}": gold[i] if i < len(gold) else "NONE" for i in range(3)},
        }
        for name, target in targets.items():
            answer = obs.answers[name]
            assert answer.selected is not None
            probability = answer.probabilities[answer.selected]
            correct = answer.selected == target
            relevant = bool(
                obs.assembly_diagnostics and name in obs.assembly_diagnostics.relevant_answer_ids
            )
            (relevant_samples if relevant else diagnostic_samples)[name].append(
                (probability, correct)
            )
            if relevant and not correct and probability >= 0.9:
                semantic_errors.append(
                    {
                        "id": case.id,
                        "question": case.question,
                        "question_id": name,
                        "gold": target,
                        "selected": answer.selected,
                        "probability": probability,
                        "margin": max(answer.probabilities.values())
                        - sorted(answer.probabilities.values(), reverse=True)[1],
                    }
                )
    per_group = {}
    for name, indices in sorted(groups.items()):
        selected_cases = [cases[i] for i in indices]
        selected_obs = [observations[i] for i in indices]
        metrics = score_jev(selected_cases, selected_obs)
        per_group[name] = {
            key: metrics[key]
            for key in (
                "case_count",
                "mode_accuracy",
                "single_six_route_accuracy",
                "exact_decision_accuracy_labels_only",
                "operation_coverage",
                "compound_omission_rate",
                "clarification_miss_rate",
                "errors",
            )
        }
    operation_labels = sorted(set(operation_tp) | set(operation_fp) | set(operation_fn))
    return {
        "core": core,
        "clarification": {
            "count": clarify_total,
            "mode_correct": clarify_mode,
            "mode_accuracy": ratio(clarify_mode, clarify_total),
            "reason_correct": clarify_reason,
            "exact_reason_accuracy": ratio(clarify_reason, clarify_total),
            "reason_accuracy_given_correct_mode": ratio(clarify_reason, clarify_mode),
        },
        "compound": {
            "count": compound_total,
            "exact_request_multiset_accuracy": ratio(compound_exact, compound_total),
            "ordered_request_accuracy": ratio(compound_ordered, compound_total),
            "operation_recall": ratio(compound_matched, compound_ops),
            "operation_omission_rate": ratio(compound_ops - compound_matched, compound_ops),
            "extra_operation_rate_per_gold_operation": ratio(compound_extra, compound_ops),
            "ordering_accuracy_given_exact_multiset": ratio(compound_ordered, compound_exact),
            "gold_operations": compound_ops,
            "matched_operations": compound_matched,
            "extra_operations": compound_extra,
        },
        "operation_precision": ratio(
            sum(operation_tp.values()), sum(operation_tp.values()) + sum(operation_fp.values())
        ),
        "operation_accuracy": ratio(
            sum(operation_tp.values()), sum(operation_tp.values()) + sum(operation_fp.values())
        ),
        "operation_accuracy_definition": "precision of predicted capability-operation instances; coverage/recall uses gold instances",
        "operations": {
            name: {
                "tp": operation_tp[name],
                "fp": operation_fp[name],
                "fn": operation_fn[name],
                "precision": ratio(operation_tp[name], operation_tp[name] + operation_fp[name]),
                "recall": ratio(operation_tp[name], operation_tp[name] + operation_fn[name]),
                "f1": ratio(
                    2 * operation_tp[name],
                    2 * operation_tp[name] + operation_fp[name] + operation_fn[name],
                ),
            }
            for name in operation_labels
        },
        "strata": per_group,
        "single_comparison": comparison,
        "comparison_counts": dict(Counter(c["outcome"] for c in comparison)),
        "execution_relevant_reliability": {
            name: calibration(values) for name, values in relevant_samples.items()
        },
        "diagnostic_only_reliability": {
            name: calibration(values) for name, values in diagnostic_samples.items()
        },
        "high_probability_semantic_errors": semantic_errors,
        "diagnostic_disagreements": dict(disagreements),
        "rule_baseline": score_routing(cases, [observe_rules(c) for c in cases]),
        "policy": "Gold/criteria/assembler/core scoring unchanged. Compound sets are multisets; ordering is label-level only, repeated identical labels cannot expose target swaps.",
    }
