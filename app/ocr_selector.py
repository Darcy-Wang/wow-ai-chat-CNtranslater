from typing import Dict, Any
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QSizeGrip
)

class RegionSelectorWindow(QWidget):
    region_saved = pyqtSignal(dict)

    def __init__(self, current_region: Dict[str, int]):
        super().__init__()
        self.current_region = current_region or {"left": 30, "top": 1050, "width": 580, "height": 330}
        self.drag_position = QPoint()

        self.init_window()
        self.init_ui()
        self.apply_geometry()

    def init_window(self):
        # 置顶 + 无边框半透明
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # 顶部工具栏
        toolbar = QWidget(self)
        toolbar.setStyleSheet("background-color: rgba(20, 25, 35, 230); border-radius: 6px; padding: 4px;")
        h = QHBoxLayout(toolbar)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)

        lbl_tip = QLabel("拖动虚线框对准聊天栏", toolbar)
        lbl_tip.setStyleSheet("color: #00ffcc; font-weight: bold; font-size: 12px;")
        h.addWidget(lbl_tip)

        h.addStretch()

        btn_preset_2k = QPushButton("2K", toolbar)
        btn_preset_2k.setStyleSheet("color: #eeeeee; background-color: #2d3446; padding: 4px;")
        btn_preset_2k.clicked.connect(self.preset_2k)
        h.addWidget(btn_preset_2k)

        btn_preset_1080 = QPushButton("1080P", toolbar)
        btn_preset_1080.setStyleSheet("color: #eeeeee; background-color: #2d3446; padding: 4px;")
        btn_preset_1080.clicked.connect(self.preset_1080)
        h.addWidget(btn_preset_1080)

        btn_save = QPushButton("保存", toolbar)
        btn_save.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        btn_save.clicked.connect(self.save_and_close)
        h.addWidget(btn_save)

        btn_cancel = QPushButton("关闭", toolbar)
        btn_cancel.setStyleSheet("color: #eeeeee; background-color: #2d3446; padding: 4px;")
        btn_cancel.clicked.connect(self.close)
        h.addWidget(btn_cancel)

        layout.addWidget(toolbar)

        # 中间镂空半透明捕获视口
        self.viewport = QWidget(self)
        self.viewport.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 200, 255, 35);
                border: 2px dashed #00e5ff;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.viewport, stretch=1)

        # 底部调整栏与缩放抓手
        footer = QWidget(self)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_coord = QLabel("", footer)
        self.lbl_coord.setStyleSheet("color: #bbbbbb; font-size: 11px;")
        f_layout.addWidget(self.lbl_coord)

        f_layout.addStretch()
        self.size_grip = QSizeGrip(self)
        f_layout.addWidget(self.size_grip)

        layout.addWidget(footer)
        self.update_coord_label()

    def update_coord_label(self):
        if not hasattr(self, "lbl_coord"):
            return
        origin = self.viewport.mapToGlobal(QPoint(0, 0))
        self.lbl_coord.setText(f"捕获: X={origin.x()}, Y={origin.y()} | {self.viewport.width()}x{self.viewport.height()}")

    def apply_geometry(self):
        x = self.current_region.get("left", 30)
        y = self.current_region.get("top", 1050)
        w = self.current_region.get("width", 580)
        h = self.current_region.get("height", 330)
        self.layout().activate()
        extra_width = self.width() - self.viewport.width()
        extra_height = self.height() - self.viewport.height()
        self.resize(w + extra_width, h + extra_height)
        self.layout().activate()
        self.move(x - self.viewport.x(), y - self.viewport.y())
        self.update_coord_label()

    def preset_2k(self):
        self.current_region = dict(left=30, top=1050, width=580, height=330)
        self.apply_geometry()

    def preset_1080(self):
        self.current_region = dict(left=20, top=780, width=480, height=260)
        self.apply_geometry()

    def save_and_close(self):
        origin = self.viewport.mapToGlobal(QPoint(0, 0))
        saved = {
            "left": origin.x(), "top": origin.y(),
            "width": self.viewport.width(), "height": self.viewport.height(),
        }
        self.region_saved.emit(saved)
        self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.update_coord_label()
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_coord_label()
