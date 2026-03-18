from storage.engine import StorageEngine


def test_set_then_get_returns_value() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.get("a") == "1"


def test_set_overwrites_existing_value() -> None:
    storage = StorageEngine()

    storage.set("a", "1")
    storage.set("a", "2")

    assert storage.get("a") == "2"


def test_delete_existing_key_returns_true_and_removes_value() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.delete("a") is True
    assert storage.get("a") is None


def test_missing_key_lookup_and_delete_behave_as_expected() -> None:
    storage = StorageEngine()

    assert storage.get("missing") is None
    assert storage.delete("missing") is False
