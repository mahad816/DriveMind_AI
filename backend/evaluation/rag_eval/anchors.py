"""Which indexed chunk holds a case's evidence quote, and does a cited chunk really exist?

``dataset.validate`` already proves every evidence quote lies in the *file's* extracted text. The product
cites *chunks*, so chunk-level scoring needs the quote mapped onto the chunks the index really holds.

An anchor is classified against the chunks of its file, in order:

* ``whole``  - the quote lies inside at least one chunk (overlapping chunks can give two).
* ``split``  - no single chunk holds it but two neighbouring chunks together do (the chunk boundary cut it).
* ``absent`` - not even a neighbouring pair holds it: the index lost it, or the validator was not run.

Rule for a split anchor (stated, not hidden): it is satisfied when **any one** of the chunks it spans is
cited or retrieved. The model cannot know where a boundary falls, so demanding both halves would punish
a correct citation. ``anchor_problems`` keeps these rare (at most 2 percent) so the rule cannot hide much.

A whole anchor that lies in two overlapping chunks is satisfied by either.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile

from .text import norm

MAX_SPLIT_SHARE = 0.02

Kind = Literal["whole", "split", "absent"]


@dataclass(frozen=True)
class ChunkInfo:
    chunk_id: str
    file_name: str  # the indexed file's name (the corpus maps a path to it)
    owner_id: str
    chunk_index: int
    text: str


@dataclass(frozen=True)
class AnchorMap:
    file: str  # corpus path, as the case writes it
    quote: str
    kind: Kind
    chunk_ids: tuple[str, ...]  # any one of these satisfies the anchor; empty when absent


def quote_in_chunk(quote: str, chunk_text: str) -> bool:
    """The validator's own test (normalised substring), applied to one chunk."""
    wanted = norm(quote)
    return bool(wanted) and wanted in norm(chunk_text)


def map_anchor(file: str, quote: str, chunks: Sequence[tuple[str, str]]) -> AnchorMap:
    """Classify one quote against ``(chunk_id, text)`` pairs of its file, already in chunk order."""
    whole = tuple(cid for cid, text in chunks if quote_in_chunk(quote, text))
    if whole:
        return AnchorMap(file, quote, "whole", whole)
    for (first_id, first), (second_id, second) in zip(chunks, chunks[1:], strict=False):
        if quote_in_chunk(quote, first + " " + second):
            return AnchorMap(file, quote, "split", (first_id, second_id))
    return AnchorMap(file, quote, "absent", ())


def map_case_anchors(
    case: Mapping[str, Any],
    chunks_by_file_name: Mapping[str, Sequence[tuple[str, str]]],
    names: Mapping[str, str],
) -> list[AnchorMap]:
    """Every anchor of one case. ``names`` maps a corpus path to the indexed file name."""
    return [
        map_anchor(a["file"], a["quote"], chunks_by_file_name.get(names.get(a["file"], ""), ()))
        for a in case.get("evidence_anchors", [])
    ]


def anchor_problems(
    by_case: Mapping[str, Sequence[AnchorMap]], *, max_split_share: float = MAX_SPLIT_SHARE
) -> list[str]:
    """Problems for the dataset check: an anchor the index does not hold, too many split anchors."""
    problems: list[str] = []
    total = split = 0
    for case_id, anchors in by_case.items():
        for anchor in anchors:
            total += 1
            split += anchor.kind == "split"
            if anchor.kind == "absent":
                problems.append(f"{case_id}: anchor not in any indexed chunk of {anchor.file}")
    if total and split / total > max_split_share:
        problems.append(
            f"{split} of {total} anchors are cut by a chunk boundary "
            f"({split / total:.1%}, limit {max_split_share:.0%})"
        )
    return problems


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:  # a fabricated identifier is data here, not an error
        return None


async def load_file_chunks(
    db: AsyncSession, owner_id: uuid.UUID, file_names: Iterable[str]
) -> dict[str, list[tuple[str, str]]]:
    """``{file name: [(chunk_id, text) in chunk order]}`` for the owner's files of those names."""
    rows = await db.execute(
        select(DriveFile.name, Chunk.id, Chunk.text)
        .join(Document, Document.drive_file_id == DriveFile.id)
        .join(Chunk, Chunk.document_id == Document.id)
        .where(DriveFile.user_id == owner_id, DriveFile.name.in_(list(file_names)))
        .order_by(DriveFile.name, Chunk.chunk_index)
    )
    out: dict[str, list[tuple[str, str]]] = {}
    for name, chunk_id, text in rows:
        out.setdefault(name, []).append((str(chunk_id), text))
    return out


async def load_chunks(db: AsyncSession, chunk_ids: Iterable[str]) -> dict[str, ChunkInfo]:
    """Chunks by identifier, whoever owns them (ownership is judged by the caller). Unknown or
    malformed identifiers are simply absent from the result."""
    parsed = {u: raw for raw in chunk_ids if (u := _uuid(raw)) is not None}
    if not parsed:
        return {}
    rows = await db.execute(
        select(Chunk.id, Chunk.chunk_index, Chunk.text, DriveFile.name, DriveFile.user_id)
        .join(Document, Chunk.document_id == Document.id)
        .join(DriveFile, Document.drive_file_id == DriveFile.id)
        .where(Chunk.id.in_(list(parsed)))
    )
    return {
        str(cid): ChunkInfo(str(cid), name, str(owner), index, text)
        for cid, index, text, name, owner in rows
    }
