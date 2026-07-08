"""Query routing — classify an incoming question into processing paths.

Routes:
  CHITCHAT       — social messages; no retrieval.
  FILE_INVENTORY — file counts, lists, resume/CV inventory SQL path.
  FILE_TARGET    — user asks about a specific file by name (e.g. Tell me about "HI").
  GROUNDED_RAG   — general knowledge questions via hybrid retrieval.
"""

from __future__ import annotations

import re
from enum import StrEnum

from app.retrieval.filename_targets import extract_filename_targets, is_file_about_question

# Quoted token in the query (e.g. "HI", "Far611") — presence means the user is
# referencing something by name and can never be a pure social message.
_QUOTED_TOKEN_RE = re.compile(r'"[^"]{1,}"|\'[^\']{1,}\'')


class QueryRoute(StrEnum):
    """Top-level routing decision for an incoming user question."""

    CHITCHAT = "chitchat"
    FILE_INVENTORY = "file_inventory"
    FILE_TARGET = "file_target"
    GROUNDED_RAG = "grounded_rag"


# ── Chitchat detection ─────────────────────────────────────────────────────────

# Pure social phrases.  Punctuation is stripped before matching.
_CHITCHAT_EXACT: frozenset[str] = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hiya",
        "howdy",
        "yo",
        "sup",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "cheers",
        "ok",
        "okay",
        "cool",
        "great",
        "nice",
        "awesome",
        "good",
        "bye",
        "goodbye",
        "see you",
        "see ya",
        "later",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
        "how are you",
        "how are you doing",
        "how do you do",
        "what's up",
        "whats up",
        "how is it going",
        "hows it going",
    }
)

# Any match here overrides chitchat classification — the message has knowledge intent.
_KNOWLEDGE_SIGNALS_RE = re.compile(
    r"\b("
    r"file|files|document|documents|folder|folders|drive|"
    r"resume|cv|certificate|transcript|report|thesis|portfolio|"
    r"pdf|docx|doc|txt|"
    r"find|search|show|list|get|fetch|look|check|"
    r"what|how|why|when|where|which|who|"
    r"explain|summarize|summary|describe|"
    r"tell me|count|how many|total|number of|"
    r"latest|recent|newest|last|"
    r"name|named|called|mention|mentions|contain|contains|include|"
    r"gpa|grade|project|internship|work|experience|skill|"
    r"certification|award|achievement|internship"
    r")\b",
    re.IGNORECASE,
)

# ── File-inventory detection ───────────────────────────────────────────────────

# Domain terms that indicate specific file types the user is searching for.
_INVENTORY_DOMAIN_RE = re.compile(
    r"\b("
    r"resume|resumes|"
    r"cv|cvs|"
    r"curriculum vitae|curriculum|"
    r"certificate|certificates|certification|certifications|"
    r"transcript|transcripts|"
    r"thesis|dissertation|"
    r"report|reports|"
    r"portfolio|"
    r"cover letter|cover letters"
    r")\b",
    re.IGNORECASE,
)

# Action signals that combine with a domain term to indicate inventory intent.
_INVENTORY_ACTION_RE = re.compile(
    r"\b("
    r"how many|count|total|number of|"
    r"all|every|any|each|"
    r"find|list|show|search|get|check|look|fetch|"
    r"latest|newest|recent|most recent|last"
    r")\b",
    re.IGNORECASE,
)

# "files (with/named/called) <term>" patterns — explicit file-name search.
_FILES_WITH_NAME_RE = re.compile(
    r"\bfiles?\b.{0,50}\b(name[ds]?|called|with|containing|titled?|mentioning)\b",
    re.IGNORECASE,
)

# General file-count queries — no domain term required.
# Triggers for questions like:
#   "list total number of files", "how many files do I have", "count all files",
#   "show me all files", "list all my files", "what files do I have indexed"
_GENERAL_FILE_COUNT_RE = re.compile(
    r"("
    r"\b(how many|count|total|number of)\b.{0,40}\bfiles?\b"
    r"|"
    r"\b(list all|show all|all my|all indexed)\b.{0,30}\bfiles?\b"
    r"|"
    r"\bfiles?\b.{0,40}\b(how many|count|total|number of)\b"
    r")",
    re.IGNORECASE,
)


# ── Public API ─────────────────────────────────────────────────────────────────

def classify_query(question: str) -> QueryRoute:
    """Classify a question into the appropriate processing route.

    Priority order:
      1. Chitchat — pure social, no knowledge signals.
      2. File inventory — counts, lists, resume/CV searches.
      3. File target — asking about a specific named file.
      4. Grounded RAG — default hybrid retrieval.
    """
    normalized = question.strip()
    if not normalized:
        return QueryRoute.GROUNDED_RAG

    lower = normalized.lower()

    # Quoted token → never chitchat (e.g. Tell me about "HI")
    if _QUOTED_TOKEN_RE.search(normalized):
        if _is_file_inventory(lower):
            return QueryRoute.FILE_INVENTORY
        if is_file_about_question(normalized):
            return QueryRoute.FILE_TARGET
        return QueryRoute.GROUNDED_RAG

    if _is_chitchat(lower):
        return QueryRoute.CHITCHAT

    if _is_file_inventory(lower):
        return QueryRoute.FILE_INVENTORY

    if is_file_about_question(normalized) and extract_filename_targets(normalized):
        return QueryRoute.FILE_TARGET

    return QueryRoute.GROUNDED_RAG


# ── Internal helpers ───────────────────────────────────────────────────────────

def _is_chitchat(lower: str) -> bool:
    """Return True for purely social messages with no knowledge-seeking content."""
    # Strip leading/trailing punctuation before exact phrase matching.
    cleaned = re.sub(r"[!?.,;'\"\-]+$", "", lower).strip()
    cleaned = re.sub(r"^[!?.,;'\"\-]+", "", cleaned).strip()

    if cleaned in _CHITCHAT_EXACT:
        return True

    # Any knowledge signal overrides social classification.
    if _KNOWLEDGE_SIGNALS_RE.search(lower):
        return False

    # Short messages without knowledge signals are treated as social.
    words = lower.split()
    return len(words) <= 5


def _is_file_inventory(lower: str) -> bool:
    """Return True for file listing, counting, or filename-search questions."""
    has_domain = bool(_INVENTORY_DOMAIN_RE.search(lower))
    has_action = bool(_INVENTORY_ACTION_RE.search(lower))

    # Domain term + action signal → domain-specific inventory
    if has_domain and has_action:
        return True

    # Explicit "files with/named X" pattern
    if _FILES_WITH_NAME_RE.search(lower):
        return True

    # General file count / listing (no domain term needed)
    if _GENERAL_FILE_COUNT_RE.search(lower):
        return True

    return False
