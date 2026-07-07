"""Tests for extracted text hashing."""

from app.ingestion.hash_util import compute_extracted_text_hash


def test_compute_extracted_text_hash_is_stable() -> None:
    """Same input should always produce the same SHA-256 digest."""
    text = "DriveMind extraction sample"
    assert compute_extracted_text_hash(text) == compute_extracted_text_hash(text)


def test_compute_extracted_text_hash_differs_for_different_text() -> None:
    """Different text should produce different digests."""
    assert compute_extracted_text_hash("alpha") != compute_extracted_text_hash("beta")


def test_compute_extracted_text_hash_returns_sha256_hex() -> None:
    """Digest should be a 64-character lowercase hex string."""
    digest = compute_extracted_text_hash("hello")
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(char in "0123456789abcdef" for char in digest)
