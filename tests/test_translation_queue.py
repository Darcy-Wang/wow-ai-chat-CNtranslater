import time
from threading import Event
from app.translation_queue import TranslationQueue


def wait_until(condition):
    deadline = time.monotonic() + 3
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("worker did not finish")
        time.sleep(0.005)


def test_completion_order_is_capture_order():
    queue = TranslationQueue(workers=2)
    gate, second_done = Event(), Event()
    def translate(data):
        if data["content"] == "first":
            gate.wait(3)
        else:
            second_done.set()
        return data["content"], "openai", 0.1
    try:
        queue.submit({"content": "first"}, translate)
        queue.submit({"content": "second"}, translate)
        assert second_done.wait(2)
        assert queue.poll() == []
        gate.set()
        wait_until(lambda: all(future.done() for future in queue.futures.copy()))
        assert [result[1] for result in queue.poll()] == ["first", "second"]
    finally:
        gate.set()
        queue.close()


def test_completed_but_undelivered_jobs_are_also_bounded():
    queue = TranslationQueue(capacity=2)
    try:
        for text in ("one", "two"):
            assert queue.submit({"content": text}, lambda data: (data["content"], "cache", 0))
        wait_until(lambda: not queue.futures)
        assert queue.submit({"content": "overflow"}, lambda data: None) is None
        assert len(queue.poll()) == 2
    finally:
        queue.close()


def test_stop_restart_drops_old_results_and_preserves_running_capacity():
    queue = TranslationQueue(workers=1, capacity=1)
    gate, started = Event(), Event()
    def slow(data):
        started.set()
        gate.wait(3)
        return "old-result", "openai", 1
    try:
        queue.submit({"content": "old"}, slow)
        assert started.wait(2)
        queue.new_session()
        assert queue.poll() == []
        assert queue.submit({"content": "new"}, slow) is None
        gate.set()
        wait_until(lambda: not queue.futures)
        assert queue.poll() == []
        assert queue.submit({"content": "new"}, lambda data: ("new-result", "cache", 0))
        wait_until(lambda: not queue.futures)
        assert queue.poll()[0][1] == "new-result"
    finally:
        gate.set()
        queue.close()


def test_expired_queue_entries_do_not_call_api():
    now = [0.0]
    queue = TranslationQueue(workers=1, max_age=5, clock=lambda: now[0])
    calls = []
    try:
        queue.submit({"content": "old", "_captured_at": -10}, lambda data: calls.append(data))
        wait_until(lambda: not queue.futures)
        result = queue.poll()[0]
        assert result[2] == "expired"
        assert calls == []
    finally:
        queue.close()
