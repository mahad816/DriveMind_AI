"""Contract-only examples, never semantic classification or network calls."""

import ast
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError
from app.routing.intent_frame import (
    domain as d,
    references as r,
    scope as s,
    execution as e,
    evidence as v,
)

IDENTITY = "a" * 64
USER = UUID(int=1)
FILE_A = UUID(int=2)
FILE_B = UUID(int=3)
SPAN = r.InputSpan(start=0, end=80)


def step(
    position=1,
    capability: d.Capability = "FILE_TARGET",
    operation: d.Operation = "SUMMARIZE",
    target=None,
    scope=None,
    **extra,
):
    return d.IntentStep(
        position=position,
        capability=capability,
        operation=operation,
        target=target
        if target is not None
        else r.LiteralFileCandidateReference(candidate_id="B001"),
        scope=scope if scope is not None else s.ExplicitFileTargetScope(),
        source=SPAN,
        **extra,
    )


def inventory(position=1, operation: d.Operation = "LIST", scope=None):
    return step(
        position,
        "FILE_INVENTORY",
        operation,
        r.NoTargetReference(),
        scope if scope is not None else s.AllVisibleIndexedFiles(),
        **({"ordering": "DEFAULT"} if operation == "LIST" else {}),
    )


def frame(*steps):
    return d.RequestedIntent(prepared_input_identity=IDENTITY, steps=steps)


def result(producer=1, index=0, unique=False):
    return r.ResultReference(
        producer_step_position=producer,
        required_output_kind="FILE" if unique else "ORDERED_FILE_LIST",
        selector=r.UniqueFileSelector() if unique else r.ItemAtIndexSelector(index=index),
    )


def resolved(position=1, file_id=FILE_A):
    return e.ExecutionStep(
        position=position,
        arguments=e.ResolvedFileArguments(file_id=file_id, canonical_name="synthetic.pdf"),
        scope=s.ResolvedFileScope(file_ids=(file_id,)),
    )


def plan(intent, *steps):
    return e.ExecutionPlan(user_id=USER, intent=intent, steps=steps)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_cardinality_order_and_roundtrip(count):
    x = frame(*(step(i) for i in range(1, count + 1)))
    assert x.cardinality == count
    assert TypeAdapter(d.IntentFrame).validate_json(x.model_dump_json()) == x
    assert "action_count" not in x.model_dump()
    assert "cardinality" not in x.model_dump()
    with pytest.raises(ValidationError):
        setattr(x, "kind", "UNSUPPORTED")


@pytest.mark.parametrize("positions", [(), (1, 2, 3, 4), (2,), (1, 3), (1, 1), (2, 1)])
def test_invalid_positions(positions):
    with pytest.raises(ValidationError):
        frame(*(step(i) for i in positions))


@pytest.mark.parametrize("producer,consumer", [(1, 1), (2, 2), (3, 2)])
def test_self_or_future_result(producer, consumer):
    with pytest.raises(ValidationError):
        frame(inventory(), step(consumer, target=result(producer)))


def test_result_selector_contract_and_actual_order():
    x = frame(inventory(), step(2, target=result()))
    y = plan(
        x,
        e.ExecutionStep(
            position=1, arguments=e.CollectionArguments(), scope=s.EligibleCollectionScope()
        ),
        e.ExecutionStep(
            position=2,
            arguments=e.DeferredFileArguments(reference=result()),
            scope=s.DeferredFileResultScope(),
        ),
    )
    assert isinstance(y.steps[1].arguments, e.DeferredFileArguments)
    assert isinstance(y.steps[1].arguments.reference.selector, r.ItemAtIndexSelector)
    assert y.steps[1].arguments.reference.producer_step_position == 1
    assert y.steps[1].arguments.reference.selector.index == 0
    assert s.DEFAULT_LIST_ORDER == (
        "filename_unicode_casefold_ascending",
        "internal_file_id_ascending",
    )
    # Contract declares actual producer result consumption, not independent recency.
    with pytest.raises(ValidationError):
        plan(x, y.steps[0], resolved(2))
    assert e.ExecutionPlan.model_validate_json(y.model_dump_json()) == y


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "ITEM_AT_INDEX", "index": -1},
        {"kind": "JSON_PATH", "path": "$.first"},
        {"kind": "ITEM_AT_INDEX", "index": True},
        {"kind": "ITEM_AT_INDEX", "index": "0"},
    ],
)
def test_invalid_selectors(data):
    with pytest.raises(ValidationError):
        TypeAdapter(r.ResultSelector).validate_python(data)


def test_output_compatibility_checked_at_execution_boundary():
    x = frame(inventory(operation="COUNT"), step(2, target=result(unique=True)))
    with pytest.raises(ValidationError):
        plan(
            x,
            e.ExecutionStep(
                position=1, arguments=e.CollectionArguments(), scope=s.EligibleCollectionScope()
            ),
            e.ExecutionStep(
                position=2,
                arguments=e.DeferredFileArguments(reference=result(unique=True)),
                scope=s.DeferredFileResultScope(),
            ),
        )
    with pytest.raises(ValidationError):
        r.ResultReference(
            producer_step_position=1,
            required_output_kind="FILE",
            selector=r.ItemAtIndexSelector(index=0),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"capability": "CHITCHAT"},
        {"operation": "COUNT"},
        {"ordering": "DEFAULT"},
        {"target": {"kind": "LITERAL_FILE", "filename": "invented.pdf"}},
        {"target": {"kind": "LITERAL_FILE", "candidate_id": str(FILE_A)}},
        {"target": {"kind": "RESOLVED_FILE", "file_id": FILE_A}},
        {"scope": None},
        {"scope": {"kind": "ALL"}},
        {"file_id": FILE_A},
    ],
)
def test_invalid_semantic_combinations(changes):
    data = step().model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        d.IntentStep.model_validate(data)


def test_no_independent_count_or_default_scope():
    with pytest.raises(ValidationError):
        d.RequestedIntent.model_validate(
            {"prepared_input_identity": IDENTITY, "steps": (step(),), "action_count": 2}
        )
    data = step().model_dump()
    data.pop("scope")
    with pytest.raises(ValidationError):
        d.IntentStep.model_validate(data)
    assert r.UnspecifiedSingleFileReference() != r.NoTargetReference()
    assert result() != r.PriorFileReference(candidate_id="B002")
    with pytest.raises(ValidationError):
        plan(frame(step(target=r.UnspecifiedSingleFileReference())), resolved())


@pytest.mark.parametrize(
    "restriction",
    [
        s.FolderReferenceScope(candidate_id="B002"),
        s.LabelReferenceScope(candidate_id="B002"),
        s.ModifiedTimeReferenceScope(candidate_id="B002"),
        s.RestrictedCollectionScope(
            restrictions=(
                s.FolderReferenceScope(candidate_id="B002"),
                s.LabelReferenceScope(candidate_id="B003"),
            )
        ),
    ],
)
def test_scope_preserved_but_not_executable(restriction):
    x = frame(inventory(operation="COUNT", scope=restriction))
    assert x.steps[0].scope == restriction
    with pytest.raises(ValidationError):
        plan(
            x,
            e.ExecutionStep(
                position=1, arguments=e.CollectionArguments(), scope=s.EligibleCollectionScope()
            ),
        )
    with pytest.raises(ValidationError):
        TypeAdapter(s.RetrievalScope).validate_python(restriction.model_dump())


def test_independent_explicit_requests_and_missing_execution_step():
    x = frame(step(), step(2, target=r.LiteralFileCandidateReference(candidate_id="B002")))
    y = plan(x, resolved(), resolved(2, FILE_B))
    assert len(y.steps) == 2
    with pytest.raises(ValidationError):
        plan(x, resolved())
    with pytest.raises(ValidationError):
        plan(
            frame(step()),
            e.ExecutionStep(
                position=1,
                arguments=resolved().arguments,
                scope=s.ResolvedFileScope(file_ids=(FILE_B,)),
            ),
        )
    assert frame(step(), step(2)).cardinality == 2  # same target/operation is legitimate


def test_non_file_and_context_arguments():
    history = r.HistoryReference(role="user", relative_position=1)
    h = step(
        capability="CONVERSATION_HISTORY", operation="RECALL", target=history, scope=s.NoFileScope()
    )
    plan(
        frame(h),
        e.ExecutionStep(
            position=1,
            arguments=e.HistoryArguments(reference=history, text="prior synthetic question"),
            scope=s.NoRetrievalScope(),
        ),
    )
    social = step(
        capability="CHITCHAT",
        operation="RESPOND",
        target=r.NoTargetReference(),
        scope=s.NoFileScope(),
    )
    plan(
        frame(social),
        e.ExecutionStep(
            position=1, arguments=e.TextArguments(text="Hello"), scope=s.NoRetrievalScope()
        ),
    )
    topic = r.PriorTopicReference(candidate_id="B002")
    g = step(
        capability="GROUNDED_RAG",
        operation="ANSWER",
        target=topic,
        scope=s.AllVisibleIndexedFiles(),
        query=r.InputSpan(start=0, end=40),
    )
    plan(
        frame(g),
        e.ExecutionStep(
            position=1,
            arguments=e.TopicArguments(
                candidate_id="B002",
                current_query="Explain further",
                topic="synthetic authentication",
            ),
            scope=s.EligibleCollectionScope(),
        ),
    )
    with pytest.raises(ValidationError):
        plan(
            frame(g),
            e.ExecutionStep(
                position=1,
                arguments=e.TextArguments(text="Explain further"),
                scope=s.EligibleCollectionScope(),
            ),
        )


def test_explicit_dispositions():
    for x in [
        d.UnsupportedIntent(
            prepared_input_identity=IDENTITY, source=SPAN, reason="OPERATION_UNSUPPORTED"
        ),
        d.UninterpretableIntent(
            prepared_input_identity=IDENTITY, source=SPAN, reason="AMBIGUOUS_MEANING"
        ),
    ]:
        assert TypeAdapter(d.IntentFrame).validate_json(x.model_dump_json()) == x
        with pytest.raises(ValidationError):
            e.ExecutionPlan(user_id=USER, intent=x, steps=(resolved(),))


def test_retrieval_contract_no_semantic_scope_or_prompt_parameters():
    x = e.RetrievalRequest(
        user_id=USER,
        query="synthetic query",
        scope=s.ResolvedFileScope(file_ids=()),
        candidate_limit=8,
    )
    assert isinstance(x.scope, s.ResolvedFileScope)
    assert x.scope.file_ids == ()
    assert e.RetrievalRequest.model_validate_json(x.model_dump_json()) == x
    for bad in [s.AllVisibleIndexedFiles(), s.DeferredFileResultScope()]:
        with pytest.raises(ValidationError):
            e.RetrievalRequest(user_id=USER, query="x", scope=bad, candidate_limit=8)
    with pytest.raises(ValidationError):
        e.RetrievalRequest(
            user_id=USER, query="x", scope=s.EligibleCollectionScope(), candidate_limit=True
        )
    with pytest.raises(ValidationError):
        e.RetrievalRequest.model_validate(
            {
                "user_id": USER,
                "query": "x",
                "scope": s.EligibleCollectionScope(),
                "candidate_limit": 8,
                "temperature": 1,
            }
        )


def chunk(index=0, text="😀 source"):
    return v.EvidenceChunk(
        chunk_id=UUID(int=10 + index),
        document_id=UUID(int=20),
        file_id=FILE_A,
        chunk_index=index,
        text=text,
        filename="synthetic.pdf",
    )


def test_authoritative_evidence_mapping_and_unicode():
    a, b = chunk(), chunk(1, "second source")
    x = v.EvidenceSection(
        anchor_chunk_id=a.chunk_id,
        members=(a, b),
        parts=(
            v.ChunkTextRange(chunk_id=a.chunk_id, start=0, end=len(a.text)),
            v.EvidenceSeparator(text="\n\n"),
            v.ChunkTextRange(chunk_id=b.chunk_id, start=0, end=len(b.text)),
        ),
    )
    assert x.combined_text == a.text + "\n\n" + b.text
    for cid, start, end in x.member_ranges:
        member = next(m for m in x.members if m.chunk_id == cid)
        assert x.combined_text[start:end] == member.text
    assert v.EvidenceSection.model_validate_json(x.model_dump_json()) == x
    with pytest.raises(ValidationError):
        v.EvidenceSection.model_validate({**x.model_dump(), "combined_text": "generated summary"})


@pytest.mark.parametrize(
    "bad",
    [
        "missing_member",
        "unknown_chunk",
        "bad_offset",
        "reversed",
        "no_anchor",
        "generated_separator",
    ],
)
def test_evidence_provenance_failures(bad):
    a, b = chunk(), chunk(1)
    parts = [
        {"kind": "CHUNK_TEXT", "chunk_id": a.chunk_id, "start": 0, "end": len(a.text)},
        {"kind": "CHUNK_TEXT", "chunk_id": b.chunk_id, "start": 0, "end": len(b.text)},
    ]
    data = {"anchor_chunk_id": a.chunk_id, "members": (a, b), "parts": tuple(parts)}
    if bad == "missing_member":
        data["parts"] = (parts[0],)
    if bad == "unknown_chunk":
        parts[1]["chunk_id"] = UUID(int=999)
    if bad == "bad_offset":
        parts[0]["end"] = 999
    if bad == "reversed":
        data["members"] = (b, a)
    if bad == "no_anchor":
        data["anchor_chunk_id"] = UUID(int=999)
    if bad == "generated_separator":
        data["parts"] = (parts[0], {"kind": "SEPARATOR", "text": "generated summary"}, parts[1])
    with pytest.raises(ValidationError):
        v.EvidenceSection.model_validate(data)


HISTORICAL_QUESTIONS = {
    146: "Display the indexed items and give a digest of the first one.",
    149: "Find a document, then explain the result you just found.",
    150: "Show the available files and summarize the first result.",
    153: "Identify the latest file, then give it a brief overview.",
    154: "Locate the oldest document and explain what it says.",
    155: "Review access_standard.pdf, then explain that file in more detail.",
    161: "Give it a concise content overview.",
    163: "Please provide a file summary.",
    176: "Give a separate synopsis of only documents tagged confidential.",
    177: "Count only the files in the Finance folder.",
    180: "Give me a separate synopsis for files changed this week only.",
}


# Eleven historical shapes are explicitly authored semantic fixtures, not classification.
@pytest.mark.parametrize("case_id", [146, 149, 150, 153, 154, 155, 161, 163, 176, 177, 180])
def test_historical_failure_representations(case_id):
    question = HISTORICAL_QUESTIONS[case_id]
    source = r.InputSpan(start=0, end=len(question))
    if case_id in {146, 150}:
        x = frame(inventory(), step(2, target=result()))
        assert isinstance(x.steps[1].target, r.ResultReference)
        assert isinstance(x.steps[1].target.selector, r.ItemAtIndexSelector)
        assert x.steps[1].target.selector.index == 0
    elif case_id == 149:
        x = d.UnsupportedIntent(
            prepared_input_identity=IDENTITY, source=source, reason="RESULT_SELECTION_UNSUPPORTED"
        )
        assert x.kind == "UNSUPPORTED"  # no defined rule choosing the unqualified found document
    elif case_id in {153, 154}:
        x = frame(
            inventory(operation="LATEST" if case_id == 153 else "OLDEST"),
            step(2, target=result(unique=True)),
        )
        assert isinstance(x.steps[1].target, r.ResultReference)
    elif case_id == 155:
        x = frame(step(), step(2, target=r.LiteralFileCandidateReference(candidate_id="B001")))
        assert x.cardinality == 2  # both refer to the same current-input file, not summary output
    elif case_id == 161:
        x = frame(step(target=r.PriorFileReference(candidate_id="B001")))
        assert isinstance(x.steps[0].scope, s.ExplicitFileTargetScope)
    elif case_id == 163:
        x = frame(step(target=r.UnspecifiedSingleFileReference()))
        assert isinstance(x.steps[0].scope, s.ExplicitFileTargetScope)
    else:
        restriction = {
            176: s.LabelReferenceScope(candidate_id="B002"),
            177: s.FolderReferenceScope(candidate_id="B002"),
            180: s.ModifiedTimeReferenceScope(candidate_id="B002"),
        }[case_id]
        cap: d.Capability
        op: d.Operation
        cap, op = (
            ("FILE_INVENTORY", "COUNT")
            if case_id == 177
            else ("COLLECTION_SUMMARY", "SUMMARIZE_EACH")
        )
        x = frame(
            step(capability=cap, operation=op, target=r.NoTargetReference(), scope=restriction)
        )
        assert x.steps[0].scope == restriction
    if isinstance(x, d.RequestedIntent):
        x = d.RequestedIntent(
            prepared_input_identity=x.prepared_input_identity,
            steps=tuple(
                d.IntentStep.model_validate({**i.model_dump(), "source": source}) for i in x.steps
            ),
        )
        assert all(question[i.source.start : i.source.end] == question for i in x.steps)


def test_package_has_no_runtime_or_historical_dependencies():
    root = Path(d.__file__).parent
    forbidden = (
        "app.routing.v2",
        "sqlalchemy",
        "qdrant",
        "openai",
        "langgraph",
        "app.services",
        "app.routing.providers",
    )
    for p in root.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden)
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith(forbidden) for a in node.names)


@pytest.mark.parametrize("operation", ["LATEST", "OLDEST"])
def test_unique_file_dependency_execution(operation):
    x = frame(inventory(operation=operation), step(2, target=result(unique=True)))
    plan(
        x,
        e.ExecutionStep(
            position=1, arguments=e.CollectionArguments(), scope=s.EligibleCollectionScope()
        ),
        e.ExecutionStep(
            position=2,
            arguments=e.DeferredFileArguments(reference=result(unique=True)),
            scope=s.DeferredFileResultScope(),
        ),
    )


@pytest.mark.parametrize(
    "values",
    [
        {"start": -1, "end": 2},
        {"start": 1, "end": 1},
        {"start": 0, "end": 8001},
        {"start": True, "end": 2},
    ],
)
def test_span_rejections(values):
    with pytest.raises(ValidationError):
        r.InputSpan.model_validate(values)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_invalid_evidence_scores(value):
    with pytest.raises(ValidationError):
        v.RetrievalScore(source="vector", value=value)
