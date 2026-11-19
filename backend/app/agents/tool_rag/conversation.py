"""Conversational-intent gate that runs before the document agent.

A small model call classifies the *meaning* of the message (any wording, order, typos or
Roman Urdu) into a fixed set of intents. There is no phrase list. Safety comes from the
shape of the output, not from trusting the model:

* the model only ever returns an enum value; the user-visible reply is server-owned text,
  so it can never contain claims about the user's documents;
* anything uncertain, malformed, too long, slow or failing falls back to
  ``document_question``, i.e. the normal evidence-grounded agent (fail-safe direction).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Literal, get_args

logger = logging.getLogger(__name__)

Intent = Literal[
    "greeting", "thanks", "farewell", "about_assistant", "out_of_scope", "document_question"
]
INTENTS: frozenset[str] = frozenset(get_args(Intent))
CONVERSATIONAL: frozenset[str] = INTENTS - {"document_question"}
# A real greeting or thanks is short; long messages skip the call and go to the agent.
MAX_CLASSIFIED_CHARS = 300
CLASSIFY_TIMEOUT_SECONDS = 10.0

INTENT_SYSTEM_PROMPT = (
    "You route messages for DriveMind, an assistant that answers questions only from the user's "
    "own indexed Google Drive documents. Classify the user's message by meaning, in any wording, "
    "word order, spelling, or language (including Roman Urdu such as 'salam', 'shukriya', "
    '\'kya haal hai\'). Reply with JSON only: {"intent": "<value>"}.\n'
    "Values:\n"
    "- greeting: only a hello or social opener, e.g. 'hi', 'hello, can you hear me?', 'salam', "
    "'good evening', 'how are you?', 'anyone there?'.\n"
    "- thanks: only thanks or an acknowledgement, e.g. 'thanks a lot', 'shukriya', 'great, ok'.\n"
    "- farewell: only a goodbye, e.g. 'bye', 'see you later', 'khuda hafiz'.\n"
    "- about_assistant: asks what the assistant is or can do, e.g. 'what can you do?', "
    "'who are you?', 'how do you work?'.\n"
    "- out_of_scope: asks the assistant to produce or do something clearly unrelated to the user's "
    "documents, e.g. write code or an algorithm, write an email or poem, translate, solve math, "
    "tell a joke, give life advice.\n"
    "- document_question: EVERYTHING ELSE, including any question about files, documents, "
    "folders, policies, people, facts or topics that the user's documents might contain, any "
    "request to find, list, count, summarize, compare or quote something, and any follow-up "
    "such as 'the second one' or 'and that file?'.\n"
    "Rules: if the message mixes a greeting or thanks with a request about documents "
    "('hi, summarize my resume'), choose document_question. If a request needs the user's files "
    "even when phrased as writing something, choose document_question. If you are unsure, "
    "choose document_question."
)

REPLIES: dict[str, str] = {
    "greeting": "Hello! I'm DriveMind. Ask me anything about the documents in your Google Drive.",
    "thanks": "You're welcome! Let me know if you'd like to look anything else up in your documents.",
    "farewell": "Goodbye! Come back any time you want to search your documents.",
    "about_assistant": (
        "I'm DriveMind, a read-only assistant for your indexed Google Drive documents. "
        "I can answer questions from them with cited sources, summarize a file, find which "
        "files mention a topic, and list or count your indexed files. I never change anything "
        "in your Drive."
    ),
    "out_of_scope": (
        "I can only answer using the documents in your Google Drive, so I can't help with that. "
        "Try asking about something in your files, for example a summary of a document or "
        "which file mentions a topic."
    ),
}

CompleteJson = Callable[[str, str], Awaitable[str]]


async def classify_intent(complete_json: CompleteJson, question: str) -> Intent:
    """Return the message intent, or ``document_question`` whenever anything is uncertain."""
    text = question.strip()
    if not text or len(text) > MAX_CLASSIFIED_CHARS:
        return "document_question"
    try:
        async with asyncio.timeout(CLASSIFY_TIMEOUT_SECONDS):
            raw = await complete_json(INTENT_SYSTEM_PROMPT, text)
        value = json.loads(raw).get("intent")
    except Exception:
        # Never surface a classifier failure; the grounded agent still answers safely.
        logger.info("rag_execution path=intent outcome=CLASSIFIER_ERROR")
        return "document_question"
    if isinstance(value, str) and value in INTENTS:
        return value  # type: ignore[return-value]
    return "document_question"
