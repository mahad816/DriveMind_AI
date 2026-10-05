"""Connection configuration contracts; all client operations are mocked."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.demo.service import DemoCorpusService
from app.embeddings.qdrant_connection import create_qdrant_client
from app.embeddings.vector_store import QdrantVectorStore


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("QDRANT_URL", "QDRANT_API_KEY", "QDRANT_HOST", "QDRANT_PORT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def constructor(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    factory = MagicMock(return_value=AsyncMock())
    monkeypatch.setattr("app.embeddings.qdrant_connection.AsyncQdrantClient", factory)
    return factory


def test_local_connection_preserves_host_and_port(constructor: MagicMock) -> None:
    create_qdrant_client(Settings(qdrant_host="qdrant.local", qdrant_port=7333))
    constructor.assert_called_once_with(host="qdrant.local", port=7333)


def test_cloud_environment_overrides_local_connection(
    constructor: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QDRANT_URL", "https://cluster.example.invalid:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "synthetic-test-key")
    create_qdrant_client(Settings(qdrant_host="unused.local", qdrant_port=7333))
    constructor.assert_called_once_with(
        url="https://cluster.example.invalid:6333", port=None, api_key="synthetic-test-key"
    )


@pytest.mark.parametrize("url", ["https://cluster.example.invalid", "http://qdrant.local:6333"])
def test_url_without_key_does_not_pass_api_key(constructor: MagicMock, url: str) -> None:
    create_qdrant_client(Settings(qdrant_url=url))
    constructor.assert_called_once_with(url=url, port=None)


@pytest.mark.parametrize(
    "url, key",
    [
        ("cluster.example.invalid", ""),
        ("ftp://cluster.example.invalid", ""),
        ("https://", ""),
        ("https://cluster.example.invalid:bad", ""),
        ("https://cluster.example.invalid:99999", ""),
        ("https://user:password@cluster.example.invalid", ""),
        ("https://cluster.example.invalid?api-key=private", ""),
        ("https://cluster.example.invalid#fragment", ""),
        ("https://bad host.invalid", ""),
        ("", "synthetic-test-key"),
        ("http://cluster.example.invalid", "synthetic-test-key"),
    ],
)
def test_invalid_configuration_never_constructs_a_fallback_client(
    constructor: MagicMock, url: str, key: str
) -> None:
    with pytest.raises(ValueError, match="QDRANT") as error:
        create_qdrant_client(Settings(qdrant_url=url, qdrant_api_key=key))
    constructor.assert_not_called()
    assert "synthetic-test-key" not in str(error.value)
    assert "password" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("cloud", [False, True])
async def test_vector_store_and_demo_inspection_share_connection_behavior(
    constructor: MagicMock, cloud: bool
) -> None:
    settings = Settings(
        demo_mode=True,
        database_url="postgresql+asyncpg://demo:demo@localhost/demo_test",
        qdrant_collection="demo_test",
        qdrant_host="qdrant.local",
        qdrant_port=7333,
        qdrant_url="https://cluster.example.invalid" if cloud else "",
        qdrant_api_key="synthetic-test-key" if cloud else "",
    )
    client = constructor.return_value
    client.collection_exists.return_value = False
    assert QdrantVectorStore(settings)._get_client() is client
    assert not await DemoCorpusService(AsyncMock(), settings).inspect_vectors(chunks=[])
    assert constructor.call_count == 2
    expected = (
        {"url": "https://cluster.example.invalid", "port": None, "api_key": "synthetic-test-key"}
        if cloud
        else {"host": "qdrant.local", "port": 7333}
    )
    assert all(call.kwargs == expected for call in constructor.call_args_list)
    client.close.assert_awaited_once()
