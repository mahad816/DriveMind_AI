"""Bounded explicit restriction checks, never tool/action/intent selection."""

import re
from . import contracts as c

# These three structural forms are deliberately finite, not a general filter parser.
_PATTERNS = (
    re.compile(r"\b(?:in|within|under|from)\s+(?:the\s+)?[\w -]{1,80}\bfolder\b", re.I),
    re.compile(r"\b(?:tagged|labelled|labeled)\s+[\w-]+", re.I),
    re.compile(
        r"\b(?:files?|documents?|items?)\s+(?:that\s+(?:were|are)\s+)?(?:changed|modified|updated)\s+(?:this|last|after|before|since|between|on|in)\b",
        re.I,
    ),
)


def unsupported_scope_widening(question: str, arguments: object) -> bool:
    broad = isinstance(arguments, c.FilesQueryArguments) or (
        isinstance(arguments, c.SearchKnowledgeArguments)
        and isinstance(arguments.scope, c.AllEligibleFiles)
    )
    return broad and any(pattern.search(question) for pattern in _PATTERNS)
