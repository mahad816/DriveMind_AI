"""The evaluation store namespace: a versioned PostgreSQL database and Qdrant collection that must agree (free)."""

import pytest

from evaluation.rag_eval import target
from evaluation.rag_eval.target import (
    EVAL_COLLECTION,
    EVAL_DB,
    FROZEN_STORE,
    LEGACY_STORE,
    EvalStore,
    assert_safe,
    eval_settings,
    store_for,
    store_of,
)


def test_the_legacy_store_is_still_v2_and_the_frozen_default_is_a_different_store():
    assert (LEGACY_STORE.database, LEGACY_STORE.collection) == (EVAL_DB, EVAL_COLLECTION)
    assert EVAL_DB == EVAL_COLLECTION == "drivemind_eval_v2"
    assert FROZEN_STORE.database == FROZEN_STORE.collection == "drivemind_eval_v3"
    assert FROZEN_STORE != LEGACY_STORE


def test_legacy_settings_are_unchanged_by_default():
    settings = eval_settings()
    assert settings.qdrant_collection == "drivemind_eval_v2"
    assert settings.database_url.endswith("/drivemind_eval_v2")


def test_a_store_selects_database_and_collection_together():
    settings = eval_settings(store=EvalStore.named("v4"))
    assert settings.database_url.endswith("/drivemind_eval_v4")
    assert settings.qdrant_collection == "drivemind_eval_v4"
    assert store_of(settings) == EvalStore.named("v4")


@pytest.mark.parametrize(
    "name", ["", "v", "3", "v3; DROP DATABASE x", "drivemind", "V3", "v3 ", "v1234", "../v3"]
)
def test_store_names_are_a_strict_version_tag(name):
    with pytest.raises(ValueError, match="store name"):
        EvalStore.named(name)


def test_frozen_commands_default_to_the_v3_store_and_can_name_another():
    assert store_for(frozen=True) == FROZEN_STORE
    assert store_for(frozen=True, name="v5") == EvalStore.named("v5")


def test_frozen_commands_can_never_select_the_legacy_store():
    with pytest.raises(SystemExit, match="v2"):
        store_for(frozen=True, name="v2")


def test_legacy_commands_refuse_a_store_name():
    with pytest.raises(SystemExit, match="--frozen"):
        store_for(frozen=False, name="v3")
    assert store_for(frozen=False) == LEGACY_STORE


def test_a_database_and_collection_from_different_versions_are_refused():
    mixed = eval_settings(store=EvalStore.named("v3")).model_copy(
        update={"qdrant_collection": "drivemind_eval_v2"}
    )
    with pytest.raises(RuntimeError, match="same"):
        assert_safe(mixed)
    with pytest.raises(RuntimeError, match="same"):
        store_of(mixed)


def test_the_existing_isolation_rules_still_hold():
    good = eval_settings(store=FROZEN_STORE)
    assert_safe(good)
    for update in (
        {"database_url": "postgresql+asyncpg://u:p@db.example.com:5432/drivemind_eval_v3"},
        {"database_url": "postgresql+asyncpg://u:p@127.0.0.1:5432/drivemind"},
        {"qdrant_host": "qdrant.example.com"},
        {"qdrant_collection": "documents"},
        {"qdrant_url": "https://cloud.example.com"},
        {"qdrant_api_key": "secret"},
        {"demo_mode": True},
    ):
        with pytest.raises(RuntimeError):
            assert_safe(good.model_copy(update=update))


def test_creating_a_database_is_only_ever_for_a_validated_store_name():
    source = open(target.__file__).read()
    assert "DROP" not in source.upper().replace("DROPPED", "")
