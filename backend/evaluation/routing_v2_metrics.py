"""Frozen-policy observational scoring; no thresholds or semantic repairs."""

import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from evaluation.routing_v2_dataset import load


def fraction(n: int, d: int) -> dict[str, Any]:
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def predicted_request(request: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    cap = request["capability"]
    result = {
        "capability": cap,
        "operation": request.get("operation", request.get("action", {}).get("operation")),
        "ordering": request.get("ordering"),
        "source": request["input_span"],
        "query": None,
    }
    candidates = {c["candidate_id"]: c for c in envelope["input"]["candidates"]}
    if cap in ("FILE_INVENTORY", "COLLECTION_SUMMARY"):
        ref = {"kind": "collection"}
    elif cap == "CHITCHAT":
        ref = {"kind": "social"}
    elif cap == "CONVERSATION_HISTORY":
        ref = {"kind": "history", **request["reference"]}
    elif cap == "GROUNDED_RAG":
        ref = {"kind": request["query"]["kind"]}
        if ref["kind"] == "original_query":
            result["query"] = request["query"]["span"]
    else:
        ref = dict(request["action"]["target"])
        candidate_id = ref.pop("candidate_id")
        if ref["kind"] == "literal":
            source = candidates[candidate_id]["source"]
            ref["name"] = envelope["input"]["question"][source["start"] : source["end"]]
        if ref["kind"] == "context_file":
            ref["context_kind"] = ref.pop("reference_kind")
        result["query"] = request["action"].get("question_span")
    result["reference"] = ref
    return result


def signature(request: dict[str, Any]) -> str:
    reference = {k: v for k, v in request["reference"].items() if v is not None}
    return json.dumps(
        [request["capability"], request["operation"], request.get("ordering"), reference],
        sort_keys=True,
    )


def confidence_bins(values: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    result = []
    for low, high in [(0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]:
        group = [(p, c) for p, c in values if low <= p < high]
        result.append(
            {
                "range": [low, min(high, 1)],
                "count": len(group),
                "mean_probability": sum(p for p, _ in group) / len(group) if group else None,
                "accuracy": sum(c for _, c in group) / len(group) if group else None,
            }
        )
    return result


def latency(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "median_ms": median(values) if values else None,
        "p95_ms": sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None,
        "max_ms": max(values) if values else None,
    }


def analyze(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text())
    dataset, _ = load()
    records = {c["id"]: c for c in artifact["cases"]}
    rows = []
    op_gold: Counter[tuple[str, str]] = Counter()
    op_pred: Counter[tuple[str, str]] = Counter()
    op_tp: Counter[tuple[str, str]] = Counter()
    ref_matrix: Counter[tuple[str, str]] = Counter()
    card_matrix: Counter[tuple[str, str]] = Counter()
    ready_matrix: Counter[tuple[str, str]] = Counter()
    stage1_samples = []
    stage2_samples = []
    brier = []
    loss = []
    stage1_latency: list[float] = []
    stage2_latency: list[float] = []
    structural = 0
    unsafe = []
    high_errors = []
    for case in dataset.cases:
        record = records.get(case.id, {})
        observation = record.get("observation", {})
        stages = observation.get("stages", [])
        input_envelope = record.get("prepared_input", {})
        interpretation = observation.get("interpretation", {}).get("interpretation", {})
        prediction = [
            predicted_request(r, input_envelope) for r in interpretation.get("requests", [])
        ]
        gold = [g.model_dump(mode="json") for g in case.expected_requests]
        gold_keys = [signature(g) for g in gold]
        pred_keys = [signature(p) for p in prediction]
        selected_card = observation.get("cardinality", {}).get("selected", "INVALID")
        cardinality_correct = selected_card == case.expected_cardinality
        pred_unsupported = interpretation.get("kind") == "unsupported"
        special_correct = (
            (pred_unsupported and case.expected_special in ("UNSUPPORTED_OPERATION", "OVER_LIMIT"))
            or case.expected_special == "UNINTERPRETABLE"
            and observation.get("status") == "STAGE1_UNINTERPRETABLE"
        )
        exact = (
            special_correct
            if case.expected_special
            else bool(interpretation) and gold_keys == pred_keys
        )
        semantic_supported_correct = bool(interpretation) and pred_unsupported == bool(
            case.expected_special
        )
        readiness = record.get("readiness", "FAILED")
        readiness_correct = readiness == case.expected_readiness
        outcomes = record.get("resolution", {}).get("outcomes", [])
        argument_correct = readiness_correct
        wrong_file = False
        for i, g in enumerate(gold):
            outcome = outcomes[i] if i < len(outcomes) else {}
            resolved = outcome.get("resolved", {})
            expected = g["readiness"]
            if outcome.get("status") != expected["status"]:
                argument_correct = False
            if (
                expected["detail"]
                and outcome.get("detail", outcome.get("reason")) != expected["detail"]
            ):
                argument_correct = False
            if expected["file_id"]:
                file = (
                    resolved.get("action", {}).get("file", resolved.get("selected_file", {})) or {}
                )
                if file.get("file_id") != expected["file_id"]:
                    argument_correct = False
                    if file:
                        wrong_file = True
            if (
                expected["message_text"]
                and resolved.get("message", {}).get("text") != expected["message_text"]
            ):
                argument_correct = False
        if readiness == "READY" and (case.expected_readiness != "READY" or wrong_file):
            unsafe.append(
                {
                    "id": case.id,
                    "question": case.question,
                    "gold_readiness": case.expected_readiness,
                    "reason": "WRONG_RESOLVED_FILE" if wrong_file else "GOLD_NOT_READY",
                    "prediction": prediction,
                }
            )
        positional = []
        bindings = []
        sources = []
        queries = []
        for i, g in enumerate(gold):
            p = prediction[i] if i < len(prediction) else None
            positional.append(
                bool(p and p["capability"] == g["capability"] and p["operation"] == g["operation"])
            )
            bindings.append(
                bool(
                    p
                    and {k: v for k, v in p["reference"].items() if v is not None}
                    == {k: v for k, v in g["reference"].items() if v is not None}
                )
            )
            sources.append(bool(p and p["source"] in g["source_ranges"]))
            if g["query_ranges"]:
                queries.append(bool(p and p["query"] in g["query_ranges"]))
            ref_matrix[(g["reference"]["kind"], p["reference"]["kind"] if p else "MISSING")] += 1
        gops = Counter((g["capability"], g["operation"]) for g in gold)
        pops = Counter((p["capability"], p["operation"]) for p in prediction)
        op_gold.update(gops)
        op_pred.update(pops)
        op_tp.update(gops & pops)
        card_matrix[(case.expected_cardinality, selected_card)] += 1
        ready_matrix[(case.expected_readiness, readiness)] += 1
        if observation.get("status") in (
            "DOMAIN_TRANSLATION_ERROR",
            "BINDING_VALIDATION_ERROR",
            "STAGE1_INVALID_RESPONSE",
            "STAGE2_INVALID_RESPONSE",
        ):
            structural += 1
        if stages and stages[0]["status"] == "SUCCESS":
            answer = stages[0]["answers"][0]
            dist = dict(answer["probabilities"])
            total = sum(dist.values())
            norm = {k: v / total for k, v in dist.items()}
            stage1_samples.append((dist[answer["selected"]], cardinality_correct))
            brier.append(
                sum((p - int(k == case.expected_cardinality)) ** 2 for k, p in norm.items())
            )
            loss.append(-math.log(max(norm.get(case.expected_cardinality, 0), 1e-15)))
        for s in stages:
            (stage1_latency if s["stage"] == 1 else stage2_latency).append(s["latency_ms"])
        if len(stages) == 2 and stages[1]["status"] == "SUCCESS":
            registry = {o["option_id"]: o for o in record["options"]["options"]}
            for i, answer in enumerate(stages[1]["answers"]):
                dist = dict(answer["probabilities"])
                probability = dist[answer["selected"]]
                vals = sorted(dist.values(), reverse=True)
                margin = vals[0] - vals[1]
                # Margins remain observable, without any activation threshold.
                correct = (
                    special_correct
                    if case.expected_special
                    else i < len(gold_keys) and i < len(pred_keys) and gold_keys[i] == pred_keys[i]
                )
                stage2_samples.append((probability, correct))
                if not correct and probability >= 0.90:
                    high_errors.append(
                        {
                            "id": case.id,
                            "position": i + 1,
                            "selected": answer["selected"],
                            "probability": probability,
                            "margin": margin,
                            "question": case.question,
                            "option": registry.get(answer["selected"]),
                        }
                    )
        rows.append(
            {
                "id": case.id,
                "question": case.question,
                "cohort": case.cohort,
                "difficulty": case.difficulty,
                "tags": case.tags,
                "state": case.state_fixture,
                "expected_cardinality": case.expected_cardinality,
                "predicted_cardinality": selected_card,
                "cardinality_correct": cardinality_correct,
                "exact_semantic": exact,
                "semantic_supported_correct": semantic_supported_correct,
                "readiness_correct": readiness_correct,
                "resolved_arguments_correct": argument_correct,
                "readiness": readiness,
                "prediction": prediction,
                "gold": gold,
                "positional_operations": positional,
                "bindings": bindings,
                "sources": sources,
                "queries": queries,
                "compound_operation_tp": sum((gops & pops).values()),
                "gold_operation_count": sum(gops.values()),
                "pred_operation_count": sum(pops.values()),
                "compound_request_set_correct": Counter(gold_keys) == Counter(pred_keys)
                and bool(gold_keys),
                "unsafe_ready": any(u["id"] == case.id for u in unsafe),
                "status": observation.get("status", "NOT_RUN"),
            }
        )

    def aggregate(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(group),
            "cardinality": fraction(sum(r["cardinality_correct"] for r in group), len(group)),
            "exact_semantic": fraction(sum(r["exact_semantic"] for r in group), len(group)),
            "readiness": fraction(sum(r["readiness_correct"] for r in group), len(group)),
            "resolved_arguments": fraction(
                sum(r["resolved_arguments_correct"] for r in group), len(group)
            ),
            "binding": fraction(
                sum(sum(r["bindings"]) for r in group), sum(len(r["bindings"]) for r in group)
            ),
            "source": fraction(
                sum(sum(r["sources"]) for r in group), sum(len(r["sources"]) for r in group)
            ),
        }

    compound = [r for r in rows if r["cohort"] == "COMPOUND"]
    ones = [r for r in rows if r["expected_cardinality"] == "ONE" and r["gold"]]
    contextual = [r for r in rows if "contextual" in r["tags"]]
    collection = [
        (r, i)
        for r in rows
        for i, g in enumerate(r["gold"])
        if g["capability"] == "COLLECTION_SUMMARY"
    ]
    ready_gold = [
        r
        for r in rows
        if r["id"] in {c.id for c in dataset.cases if c.expected_readiness == "READY"}
    ]
    readiness_tp = sum(r["readiness"] == "READY" for r in ready_gold)
    ready_pred = sum(r["readiness"] == "READY" for r in rows)
    rejection = sum(r["readiness"] in ("NEEDS_CLARIFICATION", "UNSUPPORTED") for r in ready_gold)
    tp = sum(op_tp.values())
    gp = sum(op_gold.values())
    pp = sum(op_pred.values())
    core: dict[str, Any] = {
        "cardinality_accuracy": fraction(sum(r["cardinality_correct"] for r in rows), 180),
        "structural_invalid": fraction(structural, 180),
        "exact_semantic_bundle": fraction(sum(r["exact_semantic"] for r in rows), 180),
        "one_capability_operation": fraction(
            sum(len(r["prediction"]) == 1 and all(r["positional_operations"]) for r in ones),
            len(ones),
        ),
        "operation_precision": fraction(tp, pp),
        "operation_recall": fraction(tp, gp),
        "operation_f1": 2 * tp / (gp + pp) if gp + pp else None,
        "supported_unsupported": fraction(sum(r["semantic_supported_correct"] for r in rows), 180),
        "readiness_accuracy": fraction(sum(r["readiness_correct"] for r in rows), 180),
        "resolved_arguments_accuracy": fraction(
            sum(r["resolved_arguments_correct"] for r in rows), 180
        ),
        "ready_precision": fraction(readiness_tp, ready_pred),
        "ready_recall": fraction(readiness_tp, len(ready_gold)),
        "false_rejection": fraction(rejection, len(ready_gold)),
        "false_clarification": fraction(
            sum(r["readiness"] == "NEEDS_CLARIFICATION" for r in ready_gold), len(ready_gold)
        ),
        "contextual_readiness": fraction(
            sum(r["readiness_correct"] for r in contextual), len(contextual)
        ),
        "collection_semantic": fraction(
            sum(r["positional_operations"][i] for r, i in collection), len(collection)
        ),
        "unsafe_ready_count": len(unsafe),
    }
    gt = sum(r["gold_operation_count"] for r in compound)
    pt = sum(r["pred_operation_count"] for r in compound)
    ct = sum(r["compound_operation_tp"] for r in compound)
    comp = {
        "exact_bundle": fraction(sum(r["exact_semantic"] for r in compound), len(compound)),
        "request_set": fraction(
            sum(r["compound_request_set_correct"] for r in compound), len(compound)
        ),
        "operation_recall": fraction(ct, gt),
        "omission": fraction(gt - ct, gt),
        "extra_operation": fraction(pt - ct, pt),
        "ordering": fraction(sum(r["exact_semantic"] for r in compound), len(compound)),
    }

    def matrix(counter: Counter[tuple[str, str]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for (gold, pred), count in counter.items():
            result.setdefault(gold, {})[pred] = count
        return result

    subgroup = {
        field: {
            key: aggregate([r for r in rows if key in r[field] if field == "tags"])
            if field == "tags"
            else aggregate([r for r in rows if r[field] == key])
            for key in sorted(
                {v for r in rows for v in (r[field] if field == "tags" else [r[field]])}
            )
        }
        for field in ["difficulty", "tags", "state"]
    }
    per_operation = {
        f"{cap}:{op}": {
            "precision": fraction(op_tp[(cap, op)], op_pred[(cap, op)]),
            "recall": fraction(op_tp[(cap, op)], n),
        }
        for (cap, op), n in op_gold.items()
    }
    stages = [s for c in artifact["cases"] for s in c["observation"]["stages"]]
    usage = {
        f"stage{stage}_{kind}": sum(s["usage"][kind] for s in stages if s["stage"] == stage)
        if all(s["usage"][kind] is not None for s in stages if s["stage"] == stage)
        else None
        for stage in (1, 2)
        for kind in ("input_tokens", "output_tokens")
    }
    calibration = {
        "stage1_brier": sum(brier) / len(brier) if brier else None,
        "stage1_log_loss": sum(loss) / len(loss) if loss else None,
        "stage1_bins": confidence_bins(stage1_samples),
        "stage2_bins": confidence_bins(stage2_samples),
        "stage1_distribution_note": "Only mathematically validated Choice distributions renormalized to remove representational rounding for proper scoring rules.",
        "stage2_note": "Dynamic option sets and multiple gold-equivalent options make a single-label Brier/log loss inappropriate without a frozen equivalence mapping; selected-option diagnostics only.",
    }
    gates = {
        "structural_invalid": "PASS" if structural == 0 else "FAIL",
        "cardinality": "PASS" if core["cardinality_accuracy"]["value"] >= 0.95 else "FAIL",
        "one_semantics": "PASS" if core["one_capability_operation"]["value"] >= 0.90 else "FAIL",
        "compound_recall": "PASS" if comp["operation_recall"]["value"] >= 0.90 else "FAIL",
        "compound_exact": "PASS" if comp["exact_bundle"]["value"] >= 0.85 else "FAIL",
        "supported_unsupported": "PASS"
        if core["supported_unsupported"]["value"] >= 0.90
        else "FAIL",
        "contextual_readiness": "PASS" if core["contextual_readiness"]["value"] >= 0.90 else "FAIL",
        "collection_summary": "PASS" if core["collection_semantic"]["value"] >= 0.90 else "FAIL",
        "false_rejection": "PASS" if core["false_rejection"]["value"] <= 0.05 else "FAIL",
        "unsafe_ready": "PASS" if not unsafe else "FAIL",
    }
    return {
        "core": core,
        "compound": comp,
        "cardinality_confusion": matrix(card_matrix),
        "readiness_confusion": matrix(ready_matrix),
        "reference_confusion": matrix(ref_matrix),
        "operation_breakdown": per_operation,
        "subgroups": subgroup,
        "calibration": calibration,
        "unsafe_ready": unsafe,
        "high_confidence_errors": high_errors,
        "latency": {
            "stage1": latency(stage1_latency),
            "stage2": latency(stage2_latency),
            "routing": latency([c["routing_latency_ms"] for c in artifact["cases"]]),
        },
        "usage": usage,
        "reliability": {
            "http_attempts": sum(s["post_attempts"] for s in stages),
            "http_200": sum(s["http_status"] == 200 for s in stages),
            "stage1_valid": sum(s["stage"] == 1 and s["status"] == "SUCCESS" for s in stages),
            "stage2_valid": sum(s["stage"] == 2 and s["status"] == "SUCCESS" for s in stages),
            "stage2_represented": sum(s["stage"] == 2 for s in stages),
            "translations_success": sum(
                r["status"] in ("SUCCESS", "STAGE1_OVER_LIMIT") for r in rows
            ),
            "provider_failures": sum(s["status"] == "PROVIDER_ERROR" for s in stages),
            "invalid_responses": sum(s["status"] == "INVALID_RESPONSE" for s in stages),
            "models": sorted({s["returned_model"] for s in stages if s["returned_model"]}),
        },
        "gates": gates,
        "rows": rows,
    }
