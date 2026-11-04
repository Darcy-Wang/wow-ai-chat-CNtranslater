"""Bounded, ordered, session-scoped translation delivery without Qt dependencies."""
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import RLock


class TranslationQueue:
    def __init__(self, workers=3, capacity=23, max_age=12.0, clock=time.monotonic):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="translate")
        self.capacity = capacity
        self.max_age = max_age
        self.clock = clock
        self.session = 0
        self.sequence = 0
        self.jobs = OrderedDict()
        self.futures = set()
        self.lock = RLock()

    def submit(self, data, translate):
        with self.lock:
            if len(self.jobs) >= self.capacity or len(self.futures) >= self.capacity:
                return None
            self.sequence += 1
            message = dict(data)
            message.update(_session=self.session, _sequence=self.sequence)
            message.setdefault("_captured_at", self.clock())

            def run():
                if self.clock() - message["_captured_at"] >= self.max_age:
                    return "[消息已过时]", "expired", 0.0
                return translate(message)

            future = self.executor.submit(run)
            self.futures.add(future)
            self.jobs[self.sequence] = (message, future)
            future.add_done_callback(self._done)
            return message

    def _done(self, future):
        with self.lock:
            self.futures.discard(future)

    @property
    def pending_count(self):
        return len(self.jobs)

    def poll(self):
        """Return completed/expired jobs in capture order; never wait for a worker."""
        ready = []
        while self.jobs:
            sequence, (data, future) = next(iter(self.jobs.items()))
            age = self.clock() - data["_captured_at"]
            if age >= self.max_age:
                future.cancel()
                result = ("[消息已过时，译文不再显示]", "expired", age)
            elif future.done():
                try:
                    result = future.result()
                except Exception:
                    result = ("[翻译任务失败]", "error", age)
            else:
                break
            del self.jobs[sequence]
            ready.append((data, *result))
        return ready

    def new_session(self):
        self.session += 1
        for _, future in self.jobs.values():
            future.cancel()
        self.jobs.clear()

    def close(self):
        self.new_session()
        self.executor.shutdown(wait=False, cancel_futures=True)
