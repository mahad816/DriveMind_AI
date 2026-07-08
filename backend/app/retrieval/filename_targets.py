"""Extract explicit filename targets from user questions.

When a user asks "Tell me about Far611" or 'What is in "Resume 2024"', we must
ensure chunks from that file are prioritized over semantically similar but
irrelevant documents (e.g. dozens of Assignment PDFs).
"""

from __future__ import annotations

import re

from app.retrieval.types import RetrievedChunk

# Quoted file names: "HI", "Far611", 'My Document'
_QUOTED_NAME_RE = re.compile(r'"([^"]{1,})"|\'([^\']{1,})\'')

# Detect questions aimed at a specific file's content.
_FILE_ABOUT_RE = re.compile(
    r"\b(?:"
    r"tell me about|"
    r"what(?:'s| is) (?:in|inside)|"
    r"summarize|summary of|"
    r"describe|"
    r"read|open|show me|"
    r"explain|"
    r"content of|"
    r"what does .+ say"
    r")\b",
    re.IGNORECASE,
)

# "tell me about X", "what is in X", "summarize X", etc.
_ABOUT_FILE_RE = re.compile(
    r"\b(?:"
    r"tell me about|"
    r"what(?:'s| is) (?:in|inside)|"
    r"summarize|summary of|"
    r"describe|"
    r"read|open|show me|"
    r"explain|"
    r"content of|"
    r"what does .+ say"
    r")\s+[\"']?([^\"'.?!]+)[\"']?",
    re.IGNORECASE,
)

_MIN_TARGET_LEN = 1


def is_file_about_question(question: str) -> bool:
    """Return True when the user is asking about a specific file's content."""
    if _QUOTED_NAME_RE.search(question):
        return True

    # Unquoted: only a single-token name after a file cue (not "my AWS experience").
    single_token = re.search(
        r"\b(?:"
        r"tell me about|"
        r"what(?:'s| is) (?:in|inside)|"
        r"summarize|summary of|"
        r"describe|"
        r"read|open|show me|"
        r"content of"
        r")\s+([^\s\"'?.,!]+)\s*(?:$|[?.!]|content\b)",
        question,
        re.IGNORECASE,
    )
    if single_token:
        token = single_token.group(1).lower()
        if token not in {"my", "the", "your", "a", "an", "this", "that", "it"}:
            return True

    return False


def extract_filename_targets(question: str) -> list[str]:
    """Return deduplicated filename targets mentioned in the question."""
    targets: list[str] = []
    seen: set[str] = set()

    for match in _QUOTED_NAME_RE.finditer(question):
        candidate = (match.group(1) or match.group(2) or "").strip()
        key = candidate.lower()
        if len(candidate) >= _MIN_TARGET_LEN and key not in seen:
            seen.add(key)
            targets.append(candidate)

    about_match = _ABOUT_FILE_RE.search(question)
    if about_match:
        candidate = about_match.group(1).strip().strip("\"'")
        # Skip broad topic phrases ("my AWS experience", "CoreChain architecture").
        word_count = len(candidate.split())
        if word_count == 1 and not re.match(r"^(my|your|the|a|an)\b", candidate, re.I):
            key = candidate.lower()
            if len(candidate) >= _MIN_TARGET_LEN and key not in seen:
                seen.add(key)
                targets.append(candidate)

    return targets


def filename_matches_target(filename: str, target: str) -> bool:
    """Return True when the drive file name matches the extracted target."""
    fn = filename.lower().strip()
    tg = target.lower().strip()
    if not fn or not tg:
        return False

    # Strip common extensions for comparison.
    fn_base = fn.rsplit(".", 1)[0] if "." in fn else fn
    tg_base = tg.rsplit(".", 1)[0] if "." in tg else tg

    return tg in fn or fn_base == tg_base or fn == tg


def chunk_matches_filename_target(chunk: RetrievedChunk, targets: list[str]) -> bool:
    """Return True when the chunk belongs to a file named in the question."""
    if not targets:
        return False
    return any(filename_matches_target(chunk.filename, target) for target in targets)


def prioritize_filename_targets(
    chunks: list[RetrievedChunk],
    question: str,
) -> list[RetrievedChunk]:
    """Move chunks from explicitly named files to the front of the list."""
    targets = extract_filename_targets(question)
    if not targets:
        return chunks

    matched = [c for c in chunks if chunk_matches_filename_target(c, targets)]
    if not matched:
        return chunks

    matched_ids = {c.chunk_id for c in matched}
    others = [c for c in chunks if c.chunk_id not in matched_ids]
    return matched + others
