from types import SimpleNamespace
import pytest
from PyQt6.QtCore import QRect
from app.screen_region import physical_region


def screen(x, y, width, height, ratio):
    return SimpleNamespace(geometry=lambda: QRect(x, y, width, height), devicePixelRatio=lambda: ratio)


def test_scaled_primary_coordinates():
    result = physical_region(dict(left=100, top=200, width=300, height=100),
                             [screen(0, 0, 1706, 960, 1.5)],
                             [dict(left=0, top=0, width=2560, height=1440)])
    assert result == dict(left=150, top=300, width=450, height=150)


def test_negative_monitor_origin():
    result = physical_region(dict(left=-1800, top=100, width=200, height=100),
                             [screen(-1920, 0, 1920, 1080, 1)],
                             [dict(left=-1920, top=0, width=1920, height=1080)])
    assert result == dict(left=-1800, top=100, width=200, height=100)


def test_cross_monitor_region_is_rejected():
    with pytest.raises(ValueError):
        physical_region(dict(left=-100, top=100, width=200, height=100),
                        [screen(-1920, 0, 1920, 1080, 1), screen(0, 0, 1920, 1080, 1)],
                        [dict(left=-1920, top=0, width=1920, height=1080), dict(left=0, top=0, width=1920, height=1080)])
