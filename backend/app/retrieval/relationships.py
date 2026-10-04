"""Conservative, local passage selection for explicit relationship questions.

This matches bounded English relation syntax, not entailment. Unrecognized requests
retain normal RAG; recognized relationships without a matching passage fail closed.
"""

import re
from dataclasses import dataclass

from app.retrieval.types import RetrievedChunk

_COMPARISON = re.compile(r"\b(?:over|instead of|rather than|preferred to)\s+([^?!.;,]+)", re.I)
_CHOICE = re.compile(
    r"\b(?:chosen|choose|chose|selected|select|preferred|prefer|picked|pick)\b", re.I
)
_CAUSE = re.compile(r"\b(?:caused?|causes|causing|because of|led to|resulted in|replaced)\b", re.I)
_OPERAND_END = re.compile(
    r"\b(?:because|since|as|due to|owing to|so that|although|though|while|which|who|when|where)\b",
    re.I,
)


def _operand(text: str) -> str:
    """Separate a comparison object from its following rationale/relative clause."""
    return _OPERAND_END.split(text, maxsplit=1)[0].strip()


_STOP_WORDS = frozenset(
    "a an the is are was were be been being it its this that those these what which who why how when do does did happen happens happened occurs occur would will can may must has have had to of for and or by in on from with as if summarize explain tell me chosen choose chose selected select preferred prefer picked pick".split()
)


def _terms(text: str) -> set[str]:
    return {
        word.rstrip("s")
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in _STOP_WORDS
    }


def _matches(required: set[str], text: str) -> bool:
    actual = _terms(text)
    # Permit an omitted modifier, but preserve explicit negation.
    negatives = {"not", "never", "no", "without"}
    if required & negatives != actual & negatives:
        return False
    return bool(required) and len(required & actual) >= max(1, (len(required) * 2 + 2) // 3)


@dataclass(frozen=True)
class RelationshipEvidence:
    question: str
    passages: dict[int, str]
    limitation: str = ""


def select_relationship_evidence(
    question: str, chunks: list[RetrievedChunk]
) -> RelationshipEvidence | None:
    """Select sentences from already bounded sources, preserving source numbers."""
    comparison = _COMPARISON.search(question)
    if comparison and comparison[0].lower().startswith("over ") and not _CHOICE.search(question):
        comparison = None
    conditional = re.search(r"\bif\s+(.+?)[?!.]*$", question, re.I)
    consequence = re.search(
        r"\b(?:consequences|effects|outcomes)\s+of\s+(.+?)[?!.]*$", question, re.I
    )
    conditional = conditional or consequence
    cause = _CAUSE.search(question)
    if not comparison and not conditional and not cause:
        return None
    sentences = {
        index: [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", chunk.text)
            if sentence.strip()
        ]
        for index, chunk in enumerate(chunks, start=1)
    }
    passages: dict[int, str] = {}
    if comparison:
        alternative = _operand(comparison[1])
        required = _terms(alternative)
        subject = re.split(r"\bwhy\b", question[: comparison.start()], flags=re.I)[-1]
        subject_terms = _terms(subject)
        for index, source in sentences.items():
            matched = []
            for sentence in source:
                relation = _COMPARISON.search(sentence)
                if (
                    relation
                    and _CHOICE.search(sentence)
                    and bool(required)
                    and required <= _terms(_operand(relation[1]))
                    and (not subject_terms or _matches(subject_terms, sentence[: relation.start()]))
                ):
                    matched.append(sentence)
            if matched:
                passages[index] = "\n".join(matched)
        if passages:
            return RelationshipEvidence(question, passages)
        # A distinct base-fact question can still be answered, without exposing the
        # unsupported comparison to generation. Pure comparisons have no safe base.
        base = re.split(r"[,;]?\s+(?:and\s+)?why\b", question, maxsplit=1, flags=re.I)[0].strip(
            " ,;?"
        )
        if base == question.strip(" ,;?") or not re.match(
            r"^(?:what|which|who|when|how)\b", base, re.I
        ):
            base = ""
        limitation = (
            f"The selected evidence does not establish a choice or preference involving {alternative}. "
            "It does not establish that this alternative was considered or rejected."
        )
        return RelationshipEvidence(
            base, {i: c.text for i, c in enumerate(chunks, 1)} if base else {}, limitation
        )
    if conditional:
        required = _terms(conditional[1])
        for index, source in sentences.items():
            matched = []
            for sentence in source:
                condition = re.search(r"\bif\s+(.+?)(?:,|;|\bthen\b)", sentence, re.I)
                if condition and _matches(required, condition[1]):
                    matched.append(sentence)
            if matched:
                passages[index] = "\n".join(matched)
        return RelationshipEvidence(
            question,
            passages,
            ""
            if passages
            else "The selected evidence does not explicitly connect that condition to a consequence.",
        )
    assert cause is not None
    left, right = question[: cause.start()], question[cause.end() :]
    replacement = cause[0].lower() == "replaced"
    left_terms, right_terms = _terms(left), _terms(_operand(right) if replacement else right)
    for index, source in sentences.items():
        matched = []
        for sentence in source:
            link = _CAUSE.search(sentence)
            if (
                link
                and (not replacement or link[0].lower() == "replaced")
                and bool(left_terms or right_terms)
                and (not left_terms or _matches(left_terms, sentence[: link.start()]))
                and (
                    not right_terms
                    or _matches(
                        right_terms,
                        _operand(sentence[link.end() :]) if replacement else sentence[link.end() :],
                    )
                )
            ):
                matched.append(sentence)
        if matched:
            passages[index] = "\n".join(matched)
    return RelationshipEvidence(
        question,
        passages,
        ""
        if passages
        else "The selected evidence does not establish the requested causal or replacement relationship.",
    )
