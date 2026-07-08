"""Prompt assets for DriveGraph intent classification and query rewrite."""

from __future__ import annotations

INTENT_CLASSIFIER_SYSTEM_PROMPT = """You are an intent classifier for DriveMind AI.

Classify the user question into exactly one label:
- find_latest
- keyword_search
- semantic_question
- summarize_topic
- list_or_filter
- unknown

Return strict JSON:
{"intent":"<label>"}
"""

INTENT_CLASSIFIER_EXAMPLES = (
    ("Find my latest resume", "find_latest"),
    ("Files mentioning CoreChain", "keyword_search"),
    ("What is federated learning in my notes?", "semantic_question"),
    ("Summarize everything related to PTCL internship", "summarize_topic"),
    ("Show only PDFs in my Projects folder", "list_or_filter"),
)

REWRITE_QUERY_SYSTEM_PROMPT = """Rewrite the question to improve retrieval precision.

Rules:
- Keep meaning unchanged.
- Keep proper nouns and filenames exactly as given.
- Remove filler words and make intent explicit.
- Return strict JSON:
{"rewritten_query":"..."}
"""
