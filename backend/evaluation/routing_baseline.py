"""Evaluation-only observation of the original first-pass rule classifier."""

from app.retrieval.query_router import QueryRoute, classify_query
from app.routing.contract import Capability, Operation, OPERATIONS, RoutingMode, StrictModel
from app.services.conversation_history import needs_followup_context
from evaluation.routing_dataset import RoutingCase


class RuleObservation(StrictModel):
    rule_route: Capability
    observable_mode: RoutingMode = RoutingMode.SINGLE
    operation: Operation | None = None
    followup_rewrite_eligible: bool
    followup_context_signal: bool
    classification_stage: str = "original_question_first_pass"


def observe_rules(case: RoutingCase) -> RuleObservation:
    """Never infer compound support, arguments, or confidence from gold labels."""
    route = classify_query(case.question)
    capability = Capability(route.name)
    operations = OPERATIONS[capability]
    context_signal = needs_followup_context(case.question)
    return RuleObservation(
        rule_route=capability,
        operation=next(iter(operations)) if len(operations) == 1 else None,
        followup_context_signal=context_signal,
        followup_rewrite_eligible=bool(case.history)
        and route not in (QueryRoute.CONVERSATION_HISTORY, QueryRoute.CHITCHAT)
        and context_signal,
    )
