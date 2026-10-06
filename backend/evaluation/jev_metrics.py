"""Shadow semantic scores and probability diagnostics; errors remain in denominators."""

from collections import Counter
import math
import statistics
from typing import Any

from app.routing.contract import Capability, RoutingMode
from app.routing.semantic import ObservationStatus, ProviderObservation
from evaluation.routing_dataset import RoutingCase
from evaluation.routing_metrics import ratio


def expected_labels(case: RoutingCase) -> list[str]:
    return [f"{r.capability.value}:{r.operation.value}" for r in case.expected_requests]


def exact_correct(case: RoutingCase, observation: ProviderObservation) -> bool:
    prediction = observation.prediction
    if observation.status != ObservationStatus.SUCCESS or prediction is None:
        return False
    labels = [
        f"{r.capability.value}:{r.operation.value if r.operation else 'UNKNOWN'}"
        for r in prediction.requests
    ]
    return (
        prediction.mode == case.expected_mode
        and labels == expected_labels(case)
        and prediction.clarification_reason == case.expected_clarification_reason
    )


def calibration(samples: list[tuple[float, bool]]) -> dict[str, Any]:
    bins = []
    for index in range(5):
        values = [(p, correct) for p, correct in samples if min(int(p * 5), 4) == index]
        bins.append(
            {
                "lower": index / 5,
                "upper": (index + 1) / 5,
                "count": len(values),
                "mean_probability": statistics.mean(p for p, _ in values) if values else None,
                "accuracy": statistics.mean(c for _, c in values) if values else None,
            }
        )
    return {
        "sample_count": len(samples),
        "bins": bins,
        "brier": statistics.mean((p - int(c)) ** 2 for p, c in samples) if samples else None,
        "log_loss": statistics.mean(
            -math.log(max(min(p if c else 1 - p, 1 - 1e-12), 1e-12)) for p, c in samples
        )
        if samples
        else None,
    }


def score_jev(cases: list[RoutingCase], observations: list[ProviderObservation]) -> dict[str, Any]:
    if len(cases) != len(observations):
        raise ValueError("Cases and observations must align")
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    operation_matches = total_operations = 0
    compound_missing = compound_total = 0
    single_correct = single_total = mode_correct = exact = clarify_miss = clarify_total = 0
    social_fp = social_total = 0
    confusion: dict[str, Counter[str]] = {}
    choice_samples: dict[str, list[tuple[float, bool]]] = {}
    choice_losses: dict[str, list[tuple[float, float]]] = {}
    presence_samples: dict[str, list[tuple[float, bool]]] = {}
    selective: list[tuple[float, bool]] = []
    diagnostics: list[dict[str, Any]] = []
    for case, obs in zip(cases, observations, strict=True):
        prediction = obs.prediction if obs.status == ObservationStatus.SUCCESS else None
        requests = prediction.requests if prediction else ()
        caps = Counter(r.capability.value for r in requests)
        wanted = Counter(r.capability.value for r in case.expected_requests)
        labels = Counter(
            f"{r.capability.value}:{r.operation.value if r.operation else 'UNKNOWN'}"
            for r in requests
        )
        gold_labels = expected_labels(case)
        exact += exact_correct(case, obs)
        mode_correct += bool(prediction and prediction.mode == case.expected_mode)
        if "social_decoration" in case.tags:
            social_total += 1
            social_fp += bool(caps[Capability.CHITCHAT.value])
        if case.expected_mode == RoutingMode.CLARIFY:
            clarify_total += 1
            clarify_miss += not bool(prediction and prediction.mode == RoutingMode.CLARIFY)
        else:
            tp.update(wanted & caps)
            fp.update(caps - wanted)
            fn.update(wanted - caps)
            total_operations += len(gold_labels)
            operation_matches += sum((Counter(gold_labels) & labels).values())
            if case.expected_mode == RoutingMode.COMPOUND:
                compound_total += len(gold_labels)
                compound_missing += len(gold_labels) - sum((wanted & caps).values())
        if case.expected_mode == RoutingMode.SINGLE:
            single_total += 1
            observed = (
                requests[0].capability.value if len(requests) == 1 else "UNOBSERVED_OR_MULTIPLE"
            )
            gold = case.expected_requests[0].capability.value
            single_correct += bool(
                prediction and prediction.mode == RoutingMode.SINGLE and observed == gold
            )
            confusion.setdefault(gold, Counter())[observed] += 1
        if obs.status != ObservationStatus.SUCCESS:
            continue
        expected = {
            "mode": case.expected_mode.value,
            **{
                f"operation_{i + 1}": gold_labels[i] if i < len(gold_labels) else "NONE"
                for i in range(3)
            },
        }
        for name, target in expected.items():
            answer = obs.answers[name]
            assert answer.selected is not None
            p = answer.probabilities[answer.selected]
            correct = answer.selected == target
            choice_samples.setdefault(name, []).append((p, correct))
            dist = answer.probabilities
            choice_losses.setdefault(name, []).append(
                (
                    sum((value - int(label == target)) ** 2 for label, value in dist.items()),
                    -math.log(max(dist[target], 1e-12)),
                )
            )
            sorted_probs = sorted(dist.values(), reverse=True)
            diagnostics.append(
                {
                    "case_id": case.id,
                    "question_id": name,
                    "selected_probability": p,
                    "top_two_margin": sorted_probs[0] - sorted_probs[1],
                    "correct": correct,
                    "execution_relevant": (
                        name in obs.assembly_diagnostics.relevant_answer_ids
                        if obs.assembly_diagnostics is not None
                        else None
                    ),
                }
            )
            if name == "mode":
                selective.append((p, bool(exact_correct(case, obs))))
        if case.expected_mode != RoutingMode.CLARIFY:
            for capability in Capability:
                name = "has_" + capability.value.lower()
                noul = obs.answers[name].noul
                assert noul is not None
                presence_samples.setdefault(capability.value, []).append(
                    (noul, bool(wanted[capability.value]))
                )
    latency = sorted(o.latency_ms for o in observations if o.calls)
    return {
        "case_count": len(cases),
        "mode_accuracy": ratio(mode_correct, len(cases)),
        "single_six_route_accuracy": ratio(single_correct, single_total),
        "single_correct": single_correct,
        "single_count": single_total,
        "exact_decision_accuracy_labels_only": ratio(exact, len(cases)),
        "capabilities": {
            c.value: {
                "tp": tp[c.value],
                "fp": fp[c.value],
                "fn": fn[c.value],
                "precision": ratio(tp[c.value], tp[c.value] + fp[c.value]),
                "recall": ratio(tp[c.value], tp[c.value] + fn[c.value]),
                "f1": ratio(2 * tp[c.value], 2 * tp[c.value] + fp[c.value] + fn[c.value]),
            }
            for c in Capability
        },
        "capability_micro_precision": ratio(sum(tp.values()), sum(tp.values()) + sum(fp.values())),
        "capability_micro_recall": ratio(sum(tp.values()), sum(tp.values()) + sum(fn.values())),
        "capability_micro_f1": ratio(
            2 * sum(tp.values()), 2 * sum(tp.values()) + sum(fp.values()) + sum(fn.values())
        ),
        "compound_omission_rate": ratio(compound_missing, compound_total),
        "clarification_miss_rate": ratio(clarify_miss, clarify_total),
        "social_decoration_false_positive_rate": ratio(social_fp, social_total),
        "operation_coverage": ratio(operation_matches, total_operations),
        "operation_accuracy_policy": "multiset coverage of capability:operation labels; arguments unscored",
        "confusion_matrix_single": {k: dict(v) for k, v in confusion.items()},
        "choice_calibration": {
            name: {
                "reliability": calibration(values),
                "multiclass_brier": statistics.mean(v[0] for v in choice_losses[name]),
                "multiclass_log_loss": statistics.mean(v[1] for v in choice_losses[name]),
            }
            for name, values in choice_samples.items()
        },
        "presence_calibration": {
            name: calibration(values) for name, values in presence_samples.items()
        },
        "probability_diagnostics": diagnostics,
        "high_probability_errors": [
            d for d in diagnostics if d["selected_probability"] >= 0.9 and not d["correct"]
        ],
        "selective_accuracy": [
            {
                "diagnostic_cutoff": cutoff,
                "coverage": ratio(sum(p >= cutoff for p, _ in selective), len(cases)),
                "exact_accuracy": ratio(
                    sum(c for p, c in selective if p >= cutoff),
                    sum(p >= cutoff for p, _ in selective),
                ),
            }
            for cutoff in (0, 0.5, 0.7, 0.9)
        ],
        "errors": dict(
            Counter(o.status.value for o in observations if o.status != ObservationStatus.SUCCESS)
        ),
        "total_calls_represented": sum(o.calls for o in observations),
        "median_latency_ms": statistics.median(latency) if latency else None,
        "p95_latency_ms": latency[math.ceil(0.95 * len(latency)) - 1] if latency else None,
        "usage": {
            name: (
                sum(int(o.usage[name]) for o in observations if name in o.usage)
                if any(name in o.usage for o in observations)
                else None
            )
            for name in ("input_tokens", "output_tokens", "charged_tokens", "charged_credits")
        },
        "usage_observed_cases": {
            name: sum(name in o.usage for o in observations)
            for name in ("input_tokens", "output_tokens", "charged_tokens", "charged_credits")
        },
        "cost_usd": None,
        "calibration_policy": "successful observations only; independent nouls scored as Bernoulli, never normalized together; failures count incorrect in semantic metrics",
    }
