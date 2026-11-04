import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import app.config as module
from app.config import ConfigManager, WindowsCredentialStore
from scripts.build_release import prepare_release, verify_release


def test_secrets_in_credentials_not_json_and_defaults_are_independent(tmp_path, credentials):
    manager = ConfigManager(tmp_path / "one.json", credential_store=credentials)
    manager.config["api_key"] = "private-test-key"
    manager.config["channels"]["Party"] = False
    assert manager.save()
    assert "private-test-key" not in (tmp_path / "one.json").read_text()
    assert ConfigManager(tmp_path / "one.json", credentials).get("api_key") == "private-test-key"
    assert ConfigManager(tmp_path / "two.json", credentials).get("channels")["Party"]


def test_atomic_failure_preserves_original_and_reports_error(tmp_path, credentials, monkeypatch):
    path = tmp_path / "config.json"
    manager = ConfigManager(path, credentials)
    assert manager.save()
    original = path.read_bytes()
    failures = []
    manager.on_error = failures.append
    def fail(*args):
        raise PermissionError("private-test-key")
    monkeypatch.setattr(module.os, "replace", fail)
    manager.config["model"] = "new-model"
    assert manager.save() is False
    assert path.read_bytes() == original
    assert failures and "private-test-key" not in failures[0]
    assert not list(tmp_path.glob(".config-*"))


def test_broken_configuration_is_not_silently_overwritten(tmp_path, credentials):
    path = tmp_path / "config.json"
    path.write_text("{broken")
    manager = ConfigManager(path, credentials)
    assert manager.load_error
    assert manager.save() is False
    assert path.read_text() == "{broken"


def test_legacy_key_is_removed_only_after_persistence(tmp_path, credentials):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"api_key": "legacy-secret", "model": "old-model"}))
    manager = ConfigManager(tmp_path / "user" / "config.json", credentials)
    manager.legacy_path = legacy
    manager.config = manager.load()
    assert manager.get("api_key") == "legacy-secret"
    assert manager.save()
    assert json.loads(legacy.read_text())["api_key"] == ""
    assert ConfigManager(manager.config_path, credentials).get("api_key") == "legacy-secret"


def test_release_overwrites_stale_secret_configuration(tmp_path):
    example = tmp_path / "example.json"
    example.write_text(json.dumps({"api_key": "", "wow_log_path": "", "protected_names": ""}))
    destination = tmp_path / "release"
    destination.mkdir()
    (destination / "config.json").write_text('{"api_key":"developer-secret"}')
    prepare_release(destination, example)
    assert json.loads((destination / "config.json").read_text())["api_key"] == ""
    nested = destination / "_internal"
    nested.mkdir()
    (nested / "config.example.json").write_text('{"api_key":"accidental-secret"}')
    with pytest.raises(ValueError):
        verify_release(destination)


def test_contaminated_example_is_rejected(tmp_path):
    example = tmp_path / "example.json"
    example.write_text('{"api_key":"secret"}')
    with pytest.raises(ValueError):
        prepare_release(tmp_path / "release", example)


def test_windows_credential_blob_roundtrip(monkeypatch):
    import sys
    saved = {}
    def write(value, flags):
        # Match the native binding's asymmetric input/output contract.
        assert isinstance(value["CredentialBlob"], str)
        saved.update(value)
        saved["CredentialBlob"] = value["CredentialBlob"].encode("utf-16-le")
    fake = SimpleNamespace(CRED_TYPE_GENERIC=1, CRED_PERSIST_LOCAL_MACHINE=2,
                           CredWrite=write,
                           CredRead=lambda target, kind: saved)
    monkeypatch.setitem(sys.modules, "win32cred", fake)
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="win32"))
    store = WindowsCredentialStore()
    store.set("test-target", "中文-secret")
    assert store.get("test-target") == "中文-secret"
    assert saved["CredentialBlob"] == "中文-secret".encode("utf-16-le")


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="requires Windows Credential Manager")
def test_native_windows_credential_roundtrip():
    import uuid
    target = "WoWChatTranslator/test/" + uuid.uuid4().hex
    store = WindowsCredentialStore()
    try:
        for secret in ("isolated-test-secret", "中文-isolated-test-secret"):
            store.set(target, secret)
            assert store.get(target) == secret
    finally:
        store.set(target, "")
    assert store.get(target) == ""


def test_failed_endpoint_change_preserves_previous_key_pair(tmp_path, credentials, monkeypatch):
    path = tmp_path / "config.json"
    manager = ConfigManager(path, credentials)
    manager.config.update(api_key="old-key", base_url="https://old.example.test/v1")
    assert manager.save()
    original_target = manager.credential_target
    manager.config.update(api_key="new-key", base_url="https://new.example.test/v1")
    def fail(*args):
        raise PermissionError()
    monkeypatch.setattr(module.os, "replace", fail)
    assert manager.save() is False
    reloaded = ConfigManager(path, credentials)
    assert reloaded.get("api_key") == "old-key"
    assert reloaded.get("base_url") == "https://old.example.test/v1"
    assert credentials.values[original_target] == "old-key"
    assert "new-key" not in credentials.values.values()


@pytest.mark.parametrize("field,value", [("max_pending", 0), ("max_records", 1.5),
                                         ("message_max_age", -1), ("ocr_interval", "fast")])
def test_invalid_capacity_configuration_is_not_overwritten(tmp_path, credentials, field, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({field: value}))
    manager = ConfigManager(path, credentials)
    assert manager.load_error
    assert manager.save() is False
    assert json.loads(path.read_text()) == {field: value}


def test_empty_adjacent_release_config_does_not_require_write_access(tmp_path, credentials, monkeypatch):
    legacy = tmp_path / "readonly-application" / "config.json"
    legacy.parent.mkdir()
    legacy.write_text('{"api_key":""}')
    manager = ConfigManager(tmp_path / "user" / "config.json", credentials)
    manager.legacy_path = legacy
    original = module.atomic_json
    def writable_user_path_only(path, configuration):
        if Path(path) == legacy:
            raise PermissionError("application directory is read-only")
        original(path, configuration)
    monkeypatch.setattr(module, "atomic_json", writable_user_path_only)
    assert manager.save()
