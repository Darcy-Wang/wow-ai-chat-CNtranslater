import time
import pytest
from PyQt6.QtWidgets import QMessageBox
from app.config import ConfigManager
from app.overlay_window import OverlayWindow
import app.main_window as module


@pytest.fixture
def window(qapp, tmp_path, credentials, monkeypatch):
    manager = ConfigManager(tmp_path / "config.json", credentials)
    manager.config["overlay"]["visible"] = False
    monkeypatch.setattr(module, "ConfigManager", lambda: manager)
    monkeypatch.setattr(module.WowDetector, "scan_installations", lambda: [])
    main = module.MainWindow()
    main.translator.translate_message = lambda text, **kwargs: ("翻译：" + text, "cache", 0)
    yield main
    main.close()
    qapp.processEvents()


def drain(window, qapp):
    deadline = time.monotonic() + 3
    while window.translation_queue.pending_count:
        qapp.processEvents()
        window.poll_translations()
        if time.monotonic() > deadline:
            raise AssertionError("translation delivery timed out")
        time.sleep(0.005)


def message(content="oom", channel="Party", **values):
    return dict(content=content, channel=channel, sender="Alice", time="11/04 10:00:00", **values)


def test_repeated_log_calls_are_both_displayed(window, qapp):
    window.on_new_raw_message(message())
    window.on_new_raw_message(message())
    drain(window, qapp)
    assert window.table_logs.rowCount() == 2
    assert all("翻译：oom" in window.table_logs.item(row, 4).text() for row in range(2))


def test_instance_mixed_language_and_unknown_channel_policy(window, qapp):
    window.on_new_raw_message(message("坦克 please interrupt", "Instance"))
    window.on_new_raw_message(message("坦克请打断", "Instance"))
    window.config["ocr_unknown_channel"] = False
    window.on_new_raw_message(message("unknown", "Other", is_ocr=True))
    window.on_new_raw_message(message("unknown", "Other"))
    drain(window, qapp)
    assert window.table_logs.rowCount() == 1
    assert "please interrupt" in window.table_logs.item(0, 4).text()


def test_history_is_bounded_and_clear_is_safe_with_pending_jobs(window, qapp):
    window.config["max_records"] = 2
    for count in range(5):
        window.on_new_raw_message(message(f"pull in {count}"))
    assert window.table_logs.rowCount() == 2
    window.clear_table_records()
    drain(window, qapp)
    assert window.table_logs.rowCount() == 0
    assert not window._pending_rows
    assert window.log_console_edit.document().maximumBlockCount() == 1000


def test_stop_invalidates_pending_delivery(window, qapp):
    window.on_new_raw_message(message())
    window.stop_listening()
    drain(window, qapp)
    assert window.table_logs.item(0, 4).text() == "[已取消]"


def test_no_success_dialog_on_failed_save(window, monkeypatch):
    successes = []
    monkeypatch.setattr(window.config_mgr, "save", lambda: False)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: successes.append(args))
    window.save_api_settings()
    window.save_filter_settings()
    assert not successes


def test_overlay_limits_escapes_and_updates_existing_messages(qapp):
    overlay = OverlayWindow({"overlay": {"max_messages": 2}})
    try:
        for index in range(3):
            overlay.append_message({"sender": "<Alice>", "content": f"original-{index}<b>"}, f"translated-{index}<img src=x>")
        assert len(overlay.messages) == 2
        plain = overlay.text_browser.toPlainText()
        assert "original-0" not in plain
        assert "<Alice>" in plain and "<img src=x>" in plain
        overlay.set_show_original(False)
        assert "original-1" not in overlay.text_browser.toPlainText()
        overlay.clear_messages()
        assert len(overlay.messages) == 0
    finally:
        overlay.close()


def test_settings_invalidation_keeps_active_capture_epoch(window, qapp):
    epoch = window._capture_epoch
    window.invalidate_translations()
    window.on_new_raw_message(message(), epoch)
    drain(window, qapp)
    assert window.table_logs.rowCount() == 1
    window.stop_listening()
    window.on_new_raw_message(message(), epoch)
    assert window.table_logs.rowCount() == 1


def test_selector_saves_viewport_not_toolbar(qapp):
    from app.ocr_selector import RegionSelectorWindow
    region = dict(left=100, top=200, width=580, height=330)
    selector = RegionSelectorWindow(region)
    selected = []
    selector.region_saved.connect(selected.append)
    selector.show()
    qapp.processEvents()
    selector.save_and_close()
    assert selected == [region]


def test_screen_access_failure_is_reported_without_crashing(window, monkeypatch):
    import mss
    warnings = []
    def fail():
        raise OSError("screen access denied")
    monkeypatch.setattr(mss, "MSS", fail)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.start_listening()
    assert warnings
    assert window.ocr_watcher is None


def test_invalid_startup_client_keeps_settings_ui_available(qapp, tmp_path, credentials, monkeypatch):
    manager = ConfigManager(tmp_path / "invalid-client.json", credentials)
    manager.config["api_key"] = "test-key"
    manager.config["overlay"]["visible"] = False
    original_factory = module.WowTranslator
    def factory(*args, **kwargs):
        if kwargs.get("api_key"):
            raise ValueError("invalid client settings")
        return original_factory(*args, **kwargs)
    warnings = []
    monkeypatch.setattr(module, "ConfigManager", lambda: manager)
    monkeypatch.setattr(module, "WowTranslator", factory)
    monkeypatch.setattr(module.WowDetector, "scan_installations", lambda: [])
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    main = module.MainWindow()
    try:
        qapp.processEvents()
        assert main.translator._client is None
        assert main.edit_api_key.text() == "test-key"
        qapp.processEvents()  # The warning is queued after the startup callback.
        assert warnings
    finally:
        main.close()
        qapp.processEvents()
