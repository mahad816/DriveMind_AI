"""Pure bounded state transitions from declared successful execution outcomes."""

from pydantic import Field, StrictInt, model_validator

from app.routing.v2 import domain as d
from app.routing.v2 import resolved as r


class RoutingConversationState(d.ConversationState):
    # Preserve separately resolved compound contexts without weakening phase-2 bounds.
    active_topics: tuple[d.ActiveTopic, ...] = Field(default=(), max_length=3)
    last_resolved_bundle: r.ReadyBundle | None = None

    @model_validator(mode="after")
    def consistent_topics(self) -> "RoutingConversationState":
        expected = self.active_topics[0] if len(self.active_topics) == 1 else None
        if self.active_topic != expected:
            raise ValueError("active_topic must reflect exactly one active_topics entry")
        return self


class TopicAnswer(d.DomainModel):
    request_id: StrictInt = Field(ge=1, le=3)
    answer_summary: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def nonblank(self) -> "TopicAnswer":
        if not self.answer_summary.strip():
            raise ValueError("topic summary cannot be blank")
        return self


class SuccessfulExecution(d.DomainModel):
    """Trusted executor attests every operation succeeded; readiness alone is insufficient."""

    bundle: r.ReadyBundle
    topic_answers: tuple[TopicAnswer, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def appropriate_answers(self) -> "SuccessfulExecution":
        expected = tuple(
            i
            for i, q in enumerate(self.bundle.requests, 1)
            if isinstance(q, r.ResolvedGroundedRequest)
        )
        if tuple(answer.request_id for answer in self.topic_answers) != expected:
            raise ValueError("successful grounded operations require one ordered topic answer each")
        return self


def bounded_messages(
    state: d.ConversationState, messages: tuple[d.RecentMessage, ...]
) -> tuple[d.RecentMessage, ...]:
    result = list(state.recent_messages + messages)[-6:]
    while sum(len(m.text) for m in result) > 6000:
        result.pop(0)
    if any(not m.text.strip() for m in result):
        raise ValueError("new messages must not be blank")
    return tuple(result)


def preserve_context(
    state: d.ConversationState, *, messages: tuple[d.RecentMessage, ...] = ()
) -> RoutingConversationState:
    """Chitchat, clarification, failure, or non-success: append messages only."""
    data = state.model_dump()
    if not isinstance(state, RoutingConversationState):
        data["active_topics"] = () if state.active_topic is None else (state.active_topic,)
    data["recent_messages"] = bounded_messages(state, messages)
    return RoutingConversationState.model_validate(data)


def apply_success(
    state: d.ConversationState,
    execution: SuccessfulExecution,
    *,
    messages: tuple[d.RecentMessage, ...] = (),
) -> RoutingConversationState:
    execution = SuccessfulExecution.model_validate_json(execution.model_dump_json())
    base = preserve_context(state, messages=messages)
    bundle = execution.bundle
    if all(isinstance(q, r.ResolvedChitchatRequest) for q in bundle.requests):
        return base
    data = base.model_dump()
    data.update(
        last_substantive_request=bundle.source,
        last_successful_request_bundle=bundle.source,
        last_resolved_bundle=bundle,
    )
    files = tuple(
        dict.fromkeys(
            q.action.file.file_id
            for q in bundle.requests
            if isinstance(q, r.ResolvedFileTargetRequest)
        )
    )
    topics = []
    for answer in execution.topic_answers:
        request = bundle.requests[answer.request_id - 1]
        assert isinstance(request, r.ResolvedGroundedRequest)
        original = (
            request.query.text
            if isinstance(request.query, r.ResolvedOriginalQuery)
            else request.query.topic.original_question
        )
        topics.append(
            d.ActiveTopic(
                original_question=original.strip()[:2000], answer_summary=answer.answer_summary
            )
        )
    establishes_collection = any(
        isinstance(q, r.ResolvedCollectionSummaryRequest) for q in bundle.requests
    )
    if files or topics or establishes_collection:
        # New substantive content replaces stale active context. Multiple targets
        # are preserved; inventory/history alone do not establish content focus.
        data["active_file_ids"] = files
        data["active_topics"] = tuple(topics)
        data["active_topic"] = topics[0] if len(topics) == 1 else None
    return RoutingConversationState.model_validate(data)


def apply_not_ready(
    state: d.ConversationState,
    outcome: r.ResolutionReport | r.ResolutionFailure,
    *,
    messages: tuple[d.RecentMessage, ...] = (),
) -> RoutingConversationState:
    """Resolution failure/clarification never establishes a successful context."""
    outcome = type(outcome).model_validate_json(outcome.model_dump_json())
    if outcome.status == "READY":
        raise ValueError("READY is not a non-success transition or proof of execution")
    return preserve_context(state, messages=messages)
