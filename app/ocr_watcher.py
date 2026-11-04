import time
from threading import Event, Lock
from typing import Dict
import numpy as np
import mss
from PyQt6.QtCore import QThread, pyqtSignal
from rapidocr_onnxruntime import RapidOCR
from app.log_watcher import LogWatcherThread
from app.message_policy import OcrFrameTracker


class OcrWatcherThread(QThread):
    new_message_signal = pyqtSignal(dict)
    status_signal = pyqtSignal(str)

    def __init__(self, region: Dict[str, int], interval: float = 1.0):
        super().__init__()
        self.region = dict(region)
        self.interval = max(0.5, float(interval))
        self._stop = Event()
        self._lock = Lock()
        self._revision = 0
        self._paused = False

    def stop(self):
        self._stop.set()

    def update_region(self, region):
        with self._lock:
            self.region = dict(region)
            self._revision += 1

    def set_paused(self, paused):
        with self._lock:
            if paused != self._paused:
                self._paused = paused
                self._revision += 1

    def update_interval(self, interval):
        self.interval = max(0.5, float(interval))

    def run(self):
        self.status_signal.emit("正在初始化 RapidOCR 本地引擎…")
        try:
            engine = RapidOCR()
            tracker = OcrFrameTracker()
            previous_gray = None
            revision = -1
            self.status_signal.emit("OCR 已就绪，正在捕获")
            with mss.MSS() as screen:
                while not self._stop.is_set():
                    with self._lock:
                        region, current_revision, paused = dict(self.region), self._revision, self._paused
                    if current_revision != revision:
                        tracker.reset()
                        previous_gray = None
                        revision = current_revision
                    if paused:
                        self._stop.wait(0.2)
                        continue
                    try:
                        captured_at = time.monotonic()
                        image = np.array(screen.grab(region))
                        gray = np.dot(image[..., :3], [0.114, 0.587, 0.299]).astype(np.uint8)
                        changed = (previous_gray is None or previous_gray.shape != gray.shape
                                   or np.mean(np.abs(gray.astype(np.float32) - previous_gray.astype(np.float32))) >= 1.0)
                        if changed:
                            # rapidocr-onnxruntime accepts OpenCV BGR arrays.
                            result, _ = engine(image[..., :3].copy())
                            previous_gray = gray
                            lines = [item for item in (result or [])
                                     if len((item[1] or "").strip()) >= 2 and float(item[2]) >= 0.65]
                            lines.sort(key=lambda item: (min(point[1] for point in item[0]), min(point[0] for point in item[0])))
                            indices = tracker.new_indices([item[1] for item in lines])
                            for index in indices:
                                if self._stop.is_set():
                                    break
                                text = lines[index][1].strip()
                                parsed = LogWatcherThread.parse_line(text)
                                parsed.update(is_ocr=True, _captured_at=captured_at)
                                if parsed["channel"] == "Other":
                                    parsed["channel_display"] = "[未知频道/OCR]"
                                self.new_message_signal.emit(parsed)
                            self.status_signal.emit("OCR 正在捕获")
                    except Exception as error:
                        self.status_signal.emit("OCR 捕获失败：" + type(error).__name__)
                    self._stop.wait(self.interval)
        except Exception as error:
            self.status_signal.emit("OCR 初始化或截图失败：" + type(error).__name__)
