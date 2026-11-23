"""Rebuilding an evaluation store: documents extracted by an older pipeline are re-read, not skipped (free, fake session)."""

import uuid
from types import SimpleNamespace

import pytest

from app.db.enums import DriveFileStatus
from app.db.models.document import Document
from app.db.models.drive_file import DriveFile
from app.db.models.user import User
from app.ingestion.hash_util import compute_extracted_text_hash
from app.ingestion.pipeline_version import EXTRACTION_PIPELINE_VERSION
from evaluation.rag_eval import target
from evaluation.rag_eval.corpus import CorpusFile
from evaluation.rag_eval.target import (
    EVAL_USER_ID,
    FROZEN_STORE,
    LEGACY_STORE,
    eval_settings,
    file_id,
)

FILE = CorpusFile("v1/a.txt", "v1", "0" * 64, {})
NEW = "New text, read by the current pipeline."


class FakeDb:
    def __init__(self, known: dict[uuid.UUID, object]):
        self.objects = dict(known)
        self.added: list[object] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, model, key):
        if model is User:
            return object()
        return self.objects.get(key)

    async def scalars(self, statement):
        return [k for k, v in self.objects.items() if isinstance(v, DriveFile)]

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


def stored(version: int, text: str, status=DriveFileStatus.INDEXED):
    fid = file_id(FILE.path)
    doc_id = uuid.uuid5(uuid.NAMESPACE_URL, f"drivemind-eval-v2/doc/{FILE.path}")
    drive_file = DriveFile(
        id=fid,
        user_id=EVAL_USER_ID,
        drive_file_id=f"eval:{FILE.path}",
        name="a.txt",
        mime_type="text/plain",
        folder_path="/eval/v1",
        status=status,
    )
    document = Document(
        id=doc_id,
        drive_file_id=fid,
        extracted_text=text,
        extracted_text_hash=compute_extracted_text_hash(text),
        pipeline_version=version,
    )
    return drive_file, document, {fid: drive_file, doc_id: document}


def run(monkeypatch, objects, *, refresh_stale, store=FROZEN_STORE):
    import asyncio

    db = FakeDb(objects)
    monkeypatch.setattr(target, "session_factory", lambda settings: lambda: db)
    monkeypatch.setattr(target, "extract_text", lambda file: NEW)
    built = []

    class Service:
        def __init__(self, session, settings):
            pass

        async def build_index(self, user_id):
            built.append(user_id)
            return SimpleNamespace(failed=0, skipped=0, embedded=1)

    monkeypatch.setattr(target, "IndexingService", Service)
    asyncio.run(target.ingest(eval_settings(store=store), [FILE], refresh_stale=refresh_stale))
    return db, built


def test_a_pipeline_v1_document_with_changed_text_is_refreshed_and_queued_for_chunking(monkeypatch):
    drive_file, document, objects = stored(1, "Old text from pipeline one.")
    db, built = run(monkeypatch, objects, refresh_stale=True)
    assert document.extracted_text == NEW
    assert document.extracted_text_hash == compute_extracted_text_hash(NEW)
    assert document.pipeline_version == EXTRACTION_PIPELINE_VERSION
    assert drive_file.status == DriveFileStatus.INDEXING
    assert built == [EVAL_USER_ID] and db.added == []


def test_a_pipeline_v1_document_with_identical_text_only_gets_the_new_version(monkeypatch):
    drive_file, document, objects = stored(1, NEW)
    run(monkeypatch, objects, refresh_stale=True)
    assert document.pipeline_version == EXTRACTION_PIPELINE_VERSION
    assert drive_file.status == DriveFileStatus.INDEXED  # nothing to re-embed


def test_a_current_document_with_a_different_text_is_also_refreshed(monkeypatch):
    drive_file, document, objects = stored(EXTRACTION_PIPELINE_VERSION, "edited text")
    run(monkeypatch, objects, refresh_stale=True)
    assert document.extracted_text == NEW and drive_file.status == DriveFileStatus.INDEXING


@pytest.mark.parametrize(
    "status", [DriveFileStatus.FAILED, DriveFileStatus.SKIPPED, DriveFileStatus.INDEXING]
)
def test_a_half_finished_file_is_queued_again(monkeypatch, status):
    drive_file, document, objects = stored(EXTRACTION_PIPELINE_VERSION, NEW, status)
    run(monkeypatch, objects, refresh_stale=True)
    assert drive_file.status == DriveFileStatus.INDEXING


def test_an_up_to_date_indexed_document_is_left_alone(monkeypatch):
    drive_file, document, objects = stored(EXTRACTION_PIPELINE_VERSION, NEW)
    run(monkeypatch, objects, refresh_stale=True)
    assert drive_file.status == DriveFileStatus.INDEXED and document.extracted_text == NEW


def test_the_legacy_behaviour_is_unchanged_without_the_refresh_switch(monkeypatch):
    drive_file, document, objects = stored(1, "Old text from pipeline one.")
    run(monkeypatch, objects, refresh_stale=False, store=LEGACY_STORE)
    assert document.extracted_text == "Old text from pipeline one."
    assert document.pipeline_version == 1 and drive_file.status == DriveFileStatus.INDEXED


def test_the_legacy_store_is_never_refreshed(monkeypatch):
    drive_file, document, objects = stored(1, "Old text from pipeline one.")
    with pytest.raises(RuntimeError, match="legacy"):
        run(monkeypatch, objects, refresh_stale=True, store=LEGACY_STORE)
    assert document.extracted_text == "Old text from pipeline one."


def test_pre_extracted_texts_are_used_instead_of_reading_the_files_again(monkeypatch):
    import asyncio

    db = FakeDb({})
    monkeypatch.setattr(target, "session_factory", lambda settings: lambda: db)
    monkeypatch.setattr(target, "extract_text", lambda file: pytest.fail("already extracted"))
    monkeypatch.setattr(
        target,
        "IndexingService",
        lambda s, st: SimpleNamespace(build_index=lambda user_id: _done()),
    )
    asyncio.run(target.ingest(eval_settings(store=FROZEN_STORE), [FILE], texts={FILE.path: NEW}))
    docs = [o for o in db.added if isinstance(o, Document)]
    assert [d.extracted_text for d in docs] == [NEW]


async def _done():
    return SimpleNamespace(failed=0, skipped=0, embedded=1)
