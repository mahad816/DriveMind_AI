"""Deterministic text normalisation and fact matching shared by validation and scoring."""

import re
import unicodedata

_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d{3}\b)")
_KEEP = re.compile(r"[^a-z0-9.:\s]")
_LOOSE_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")
_LOOSE_COLON = re.compile(r"(?<!\d):|:(?!\d)")
_SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Lower-case, strip thousands separators and punctuation, keep 1.3 / 99.95 / 08:00 intact."""
    value = unicodedata.normalize("NFKC", text).lower().replace("%", " percent ")
    value = _DIGIT_COMMA.sub("", value)
    value = _KEEP.sub(" ", value.replace("_", " "))
    value = _LOOSE_COLON.sub(" ", _LOOSE_DOT.sub(" ", value))
    return _SPACE.sub(" ", value).strip()


def contains(haystack: str, needle: str) -> bool:
    """Whole-token containment on normalised text: '5' matches 'five incidents: 5' but not '15' or '5.5'."""
    target = norm(needle)
    if not target:
        return False
    pattern = r"(?<![a-z0-9.:])" + re.escape(target) + r"(?![a-z0-9]|[.:]\d)"
    return re.search(pattern, norm(haystack)) is not None


def satisfies(haystack: str, group: list[str]) -> bool:
    """A must-include group is satisfied by ANY of its accepted surface forms."""
    return any(contains(haystack, alternative) for alternative in group)
