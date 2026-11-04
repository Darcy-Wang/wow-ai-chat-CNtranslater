import pytest
from app.message_policy import OcrFrameTracker, text_key, is_chinese_only
from app.log_watcher import LogWatcherThread


@pytest.mark.parametrize("first,second", [("pull in 5", "pull in 15"), ("pull in 1.5", "pull in 15"),
                                         ("don't pull", "do pull"), ("we'll pull", "well pull")])
def test_meaningful_changes_are_new_messages(first, second):
    tracker = OcrFrameTracker()
    assert tracker.new_indices([first]) == [0]
    assert tracker.new_indices([second]) == [0]
    assert text_key(first) != text_key(second)


def test_adjacent_frames_scroll_repetition_and_reappearance():
    tracker = OcrFrameTracker()
    assert tracker.new_indices(["first", "oom"]) == [0, 1]
    assert tracker.new_indices(["first", "oom"]) == []
    assert tracker.new_indices(["oom", "oom"]) == [1]
    assert tracker.new_indices(["oom", "new message"]) == [1]
    assert tracker.new_indices([]) == []
    assert tracker.new_indices(["oom"]) == [0]
    tracker.reset()
    assert tracker.new_indices(["oom"]) == [0]


@pytest.mark.parametrize("text,skip", [("坦克请打断", True), ("等 5 秒！", True),
                                      ("坦克 please interrupt", False), ("坦克 DPS", False),
                                      ("中文 한국어", False), ("中文 русский", False), ("123", False)])
def test_only_chinese_is_skipped(text, skip):
    assert is_chinese_only(text) == skip


@pytest.mark.parametrize("channel", ["Instance", "Instance Chat", "Instance Leader", "副本", "副本向导"])
def test_instance_channels(channel):
    parsed = LogWatcherThread.parse_line(f"11/04 10:00:00.123  [{channel}] [Alice]: interrupt now")
    assert parsed["channel"] == "Instance"
    assert parsed["sender"] == "Alice"
    assert parsed["content"] == "interrupt now"
