import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class MemoryCredentials:
    def __init__(self):
        self.values = {}

    def get(self, target):
        return self.values.get(target, "")

    def set(self, target, secret):
        self.values[target] = secret


@pytest.fixture
def credentials():
    return MemoryCredentials()
