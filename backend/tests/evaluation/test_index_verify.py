"""The shared index verifier: content, identifiers and vectors, on fabricated snapshots (free, no database, no provider)."""

import copy
import dataclasses
import hashlib
import math
import uuid


from app.ingestion.chunking import chunk_text
from app.ingestion.hash_util import compute_extracted_text_hash
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION
from evaluation.rag_eval.index_verify import (
    DbChunk,
    DbDocument,
    DbFile,
    DbSnapshot,
    ExpectedFile,
    QdrantPoint,
    QdrantSnapshot,
    compare_index,
)
from evaluation.rag_eval.target import EVAL_USER_ID

DIM = 8
LONG = " ".join(f"Clause {i} says the notice period is {i} days." for i in range(400))
TEXTS = {"v1/a.txt": "Alpha policy. The limit is 5 days.", "public/b.pdf": LONG}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def unit(seed: int) -> tuple[float, ...]:
    raw = [math.sin(seed * (k + 1) + 1.0) for k in range(DIM)]
    norm = math.sqrt(sum(x * x for x in raw))
    return tuple(x / norm for x in raw)


def expected() -> dict[str, ExpectedFile]:
    return {
        p: ExpectedFile(
            path=p,
            text_sha256=sha(t),
            chunk_texts=tuple(c.text for c in chunk_text(t)),
        )
        for p, t in TEXTS.items()
    }


def faithful() -> tuple[DbSnapshot, QdrantSnapshot]:
    files: dict[str, tuple[DbFile, ...]] = {}
    points: list[QdrantPoint] = []
    seed = 0
    for path, text in TEXTS.items():
        fid, doc_id = uuid.uuid4(), uuid.uuid4()
        doc_hash = compute_extracted_text_hash(text)
        chunks = []
        for c in chunk_text(text):
            seed += 1
            chunk = DbChunk(uuid.uuid4(), c.chunk_index, c.text, doc_hash)
            chunks.append(chunk)
            points.append(
                QdrantPoint(
                    id=str(chunk.id),
                    payload={
                        "chunk_id": str(chunk.id),
                        "drive_file_id": str(fid),
                        "filename": path.rsplit("/", 1)[-1],
                        "chunk_index": c.chunk_index,
                        "extracted_text_hash": doc_hash,
                        "user_id": str(EVAL_USER_ID),
                    },
                    vector=unit(seed),
                )
            )
        doc = DbDocument(
            doc_id, sha(text), doc_hash, EXTRACTION_PIPELINE_VERSION, tuple(chunks), text
        )
        files[path] = (DbFile(fid, path.rsplit("/", 1)[-1], "indexed", EVAL_USER_ID, (doc,)),)
    db = DbSnapshot(files=files, foreign_files=0, orphan_chunks=0)
    return db, QdrantSnapshot(vector_size=DIM, distance="Cosine", points=tuple(points))


def problems(db: DbSnapshot, qd: QdrantSnapshot, exp=None) -> list[str]:
    return compare_index(exp or expected(), db, qd, embedding_dimension=DIM, user_id=EVAL_USER_ID)


def replace_chunk(db: DbSnapshot, path: str, at: int, **change) -> DbSnapshot:
    (file,) = db.files[path]
    (doc,) = file.documents
    chunks = tuple(dataclasses.replace(c, **change) if c.index == at else c for c in doc.chunks)
    new = dataclasses.replace(file, documents=(dataclasses.replace(doc, chunks=chunks),))
    return dataclasses.replace(db, files={**db.files, path: (new,)})


def test_the_fabricated_chunks_really_overlap_several_times():
    assert len(expected()["public/b.pdf"].chunk_texts or ()) > 3


def test_a_faithful_index_has_no_problems():
    assert problems(*faithful()) == []


def test_wrong_chunk_content_is_caught_even_when_every_count_matches():
    db, qd = faithful()
    db = replace_chunk(db, "v1/a.txt", 0, text="Alpha policy. The limit is 50 days.")
    found = problems(db, qd)
    assert any("v1/a.txt" in p and "chunk 0" in p and "differs" in p for p in found)


def test_wrong_public_pdf_chunk_content_is_caught_too():
    db, qd = faithful()
    db = replace_chunk(db, "public/b.pdf", 2, text="stale text from an older pipeline")
    assert any("public/b.pdf" in p and "chunk 2" in p for p in problems(db, qd))


def test_stored_text_that_differs_from_the_expected_text_is_named():
    db, qd = faithful()
    exp = expected()
    exp["v1/a.txt"] = dataclasses.replace(exp["v1/a.txt"], text_sha256=sha("another text"))
    assert any("stored text" in p and "v1/a.txt" in p for p in problems(db, qd, exp))


def test_a_stale_pipeline_version_is_named():
    db, qd = faithful()
    (file,) = db.files["v1/a.txt"]
    doc = dataclasses.replace(file.documents[0], pipeline_version=1)
    db = dataclasses.replace(
        db, files={**db.files, "v1/a.txt": (dataclasses.replace(file, documents=(doc,)),)}
    )
    assert any("pipeline version 1" in p for p in problems(db, qd))


def test_chunks_built_from_another_version_of_the_text_are_named():
    db, qd = faithful()
    db = replace_chunk(db, "v1/a.txt", 0, text_hash="0" * 64)
    assert any("v1/a.txt" in p and "different version of the text" in p for p in problems(db, qd))


def test_missing_extra_and_duplicate_documents_are_named():
    db, qd = faithful()
    files = dict(db.files)
    del files["v1/a.txt"]
    assert any(
        "v1/a.txt" in p and "not in the index" in p
        for p in problems(dataclasses.replace(db, files=files), qd)
    )

    extra = {**db.files, "v1/zzz.txt": db.files["v1/a.txt"]}
    assert any(
        "v1/zzz.txt" in p and "not in the frozen corpus" in p
        for p in problems(dataclasses.replace(db, files=extra), qd)
    )

    (file,) = db.files["v1/a.txt"]
    two_docs = dataclasses.replace(file, documents=(file.documents[0], file.documents[0]))
    dup = {**db.files, "v1/a.txt": (two_docs,)}
    assert any("2 documents" in p for p in problems(dataclasses.replace(db, files=dup), qd))

    two_files = {**db.files, "v1/a.txt": (file, file)}
    assert any(
        "2 file records" in p for p in problems(dataclasses.replace(db, files=two_files), qd)
    )


def test_a_file_that_is_not_indexed_or_has_no_chunks_is_named():
    db, qd = faithful()
    (file,) = db.files["v1/a.txt"]
    failed = dataclasses.replace(file, status="failed")
    assert any(
        "status is 'failed'" in p
        for p in problems(dataclasses.replace(db, files={**db.files, "v1/a.txt": (failed,)}), qd)
    )
    doc = dataclasses.replace(file.documents[0], chunks=())
    empty = dataclasses.replace(file, documents=(doc,))
    assert any(
        "no chunks" in p or "0 chunks" in p
        for p in problems(dataclasses.replace(db, files={**db.files, "v1/a.txt": (empty,)}), qd)
    )


def test_chunk_numbering_must_be_contiguous():
    db, qd = faithful()
    db = replace_chunk(db, "public/b.pdf", 1, index=7)
    assert any("public/b.pdf" in p for p in problems(db, qd))


# ---- vectors ------------------------------------------------------------------------------------------


def test_a_missing_vector_is_named_even_when_another_point_makes_the_count_match():
    db, qd = faithful()
    points = list(qd.points)
    dropped = points.pop(0)
    stray = QdrantPoint(str(uuid.uuid4()), {}, unit(999))
    qd = dataclasses.replace(qd, points=tuple([*points, stray]))
    found = problems(db, qd)
    assert len(qd.points) == len(faithful()[1].points)  # counts agree
    assert any(dropped.id in p and "no vector" in p for p in found)
    assert any(stray.id in p and "no chunk" in p for p in found)


def test_a_point_whose_payload_points_at_another_chunk_or_file_is_named():
    db, qd = faithful()
    points = list(qd.points)
    points[0] = dataclasses.replace(points[0], payload={**points[0].payload, "chunk_id": "other"})
    assert any("chunk_id" in p for p in problems(db, dataclasses.replace(qd, points=tuple(points))))
    points = list(qd.points)
    points[1] = dataclasses.replace(
        points[1], payload={**points[1].payload, "drive_file_id": str(uuid.uuid4())}
    )
    assert any(
        "drive_file_id" in p for p in problems(db, dataclasses.replace(qd, points=tuple(points)))
    )
    points = list(qd.points)
    points[2] = dataclasses.replace(
        points[2], payload={**points[2].payload, "user_id": str(uuid.uuid4())}
    )
    assert any("user_id" in p for p in problems(db, dataclasses.replace(qd, points=tuple(points))))
    points = list(qd.points)
    points[3] = dataclasses.replace(points[3], payload={**points[3].payload, "chunk_index": 99})
    assert any(
        "chunk_index" in p for p in problems(db, dataclasses.replace(qd, points=tuple(points)))
    )
    points = list(qd.points)
    points[0] = dataclasses.replace(
        points[0], payload={**points[0].payload, "extracted_text_hash": "x"}
    )
    assert any(
        "extracted_text_hash" in p
        for p in problems(db, dataclasses.replace(qd, points=tuple(points)))
    )


def test_a_vector_of_the_wrong_size_a_zero_vector_and_a_non_finite_vector_are_named():
    db, qd = faithful()
    for bad in (
        (0.1,) * (DIM - 1),
        (0.0,) * DIM,
        (math.nan, *unit(1)[1:]),
        (5.0, *(0.0,) * (DIM - 1)),
    ):
        points = list(qd.points)
        points[0] = dataclasses.replace(points[0], vector=bad)
        assert any(
            "vector" in p for p in problems(db, dataclasses.replace(qd, points=tuple(points)))
        ), bad


def test_two_different_chunks_sharing_one_vector_are_named():
    db, qd = faithful()
    points = list(qd.points)
    points[1] = dataclasses.replace(points[1], vector=points[0].vector)
    assert any(
        "identical vector" in p for p in problems(db, dataclasses.replace(qd, points=tuple(points)))
    )


def test_a_point_without_a_vector_is_named():
    db, qd = faithful()
    points = list(qd.points)
    points[0] = dataclasses.replace(points[0], vector=None)
    assert any(
        "no vector data" in p or "vector" in p
        for p in problems(db, dataclasses.replace(qd, points=tuple(points)))
    )


def test_a_collection_of_the_wrong_dimension_or_distance_is_named():
    db, qd = faithful()
    assert any("dimension" in p for p in problems(db, dataclasses.replace(qd, vector_size=1536)))
    assert any("dimension" in p for p in problems(db, dataclasses.replace(qd, vector_size=None)))
    assert any("cosine" in p.lower() for p in problems(db, dataclasses.replace(qd, distance="Dot")))


def test_rows_of_other_owners_and_orphan_chunks_are_named():
    db, qd = faithful()
    assert any("another owner" in p for p in problems(dataclasses.replace(db, foreign_files=2), qd))
    assert any("orphan" in p for p in problems(dataclasses.replace(db, orphan_chunks=3), qd))
    (file,) = db.files["v1/a.txt"]
    other = dataclasses.replace(file, owner=uuid.uuid4())
    assert any(
        "owner" in p
        for p in problems(dataclasses.replace(db, files={**db.files, "v1/a.txt": (other,)}), qd)
    )


def test_chunk_contents_are_not_compared_when_their_expectation_is_unknown_but_everything_else_is():
    db, qd = faithful()
    exp = expected()
    exp["v1/a.txt"] = dataclasses.replace(exp["v1/a.txt"], chunk_texts=None)
    db = replace_chunk(db, "v1/a.txt", 0, text="anything")
    assert problems(db, qd, exp) == []


def test_snapshots_are_not_mutated():
    db, qd = faithful()
    before = copy.deepcopy((db, qd))
    problems(db, qd)
    assert (db, qd) == before
