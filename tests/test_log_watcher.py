import time
from app.log_watcher import LogWatcherThread


def until(qapp, predicate):
    deadline = time.monotonic() + 4
    while not predicate():
        qapp.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("log watcher did not report expected event")
        time.sleep(0.01)


def test_partial_utf8_repeated_lines_and_file_rotation(qapp, tmp_path):
    path = tmp_path / "chat.txt"
    path.write_bytes(b"old history\n")
    messages, statuses = [], []
    watcher = LogWatcherThread(str(path))
    watcher.new_message_signal.connect(messages.append)
    watcher.status_signal.connect(statuses.append)
    watcher.start()
    try:
        until(qapp, lambda: statuses)
        line = "[Party] [Alice]: 坦克 please interrupt\n".encode()
        split = line.index("坦".encode()) + 1
        with path.open("ab", buffering=0) as stream:
            stream.write(line[:split])
        # Let the tailer observe an incomplete multibyte character and no newline.
        end = time.monotonic() + 0.25
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)
        assert not messages
        with path.open("ab", buffering=0) as stream:
            stream.write(line[split:])
            stream.write(line)
        until(qapp, lambda: len(messages) == 2)
        assert [data["content"] for data in messages] == ["坦克 please interrupt"] * 2
        # The tailer detects a new file identity and reads its first complete line.
        path.rename(tmp_path / "old.txt")
        path.write_text("[Instance] [Bob]: pull in 15\n", encoding="utf-8")
        until(qapp, lambda: len(messages) == 3)
        assert messages[-1]["channel"] == "Instance"
        assert messages[-1]["content"] == "pull in 15"
    finally:
        watcher.stop()
        assert watcher.wait(3000)
        qapp.processEvents()
