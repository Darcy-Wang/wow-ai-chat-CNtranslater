import sys
from html import escape
from collections import deque
from typing import Dict, Any
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QTextBrowser, QPushButton, QSlider, QSizeGrip
)

# 经典魔兽频道色彩
CHANNEL_COLORS = {
    "Party": "#A8A8FF",     # 小队蓝
    "Raid": "#FF7D0A",      # 团队橙
    "Instance": "#FF7D0A",
    "Whisper": "#FF80FF",   # 密语粉
    "Guild": "#40FF40",     # 公会绿
    "Yell": "#FF4040",      # 大喊红
    "Say": "#FFFFFF",       # 普通白
    "General": "#D8D8D8",   # 综合
    "Trade": "#D8D8D8",     # 交易
    "World": "#FFB8B8",     # 世界
    "Other": "#CCCCCC"      # 其他
}

class OverlayWindow(QWidget):
    lock_state_changed = pyqtSignal(bool)

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.overlay_cfg = config.get("overlay", {})
        
        self.is_locked = bool(self.overlay_cfg.get("click_through", False))
        self.drag_position = QPoint()
        self.max_messages = int(self.overlay_cfg.get("max_messages", 60))
        self.messages = deque(maxlen=self.max_messages)
        self.font_size = int(self.overlay_cfg.get("font_size", 13))
        self.show_original = bool(self.overlay_cfg.get("show_original", True))

        self.init_window_flags()
        self.init_ui()
        self.apply_geometry_from_config()
        self.set_lock_state(self.is_locked)

    def init_window_flags(self):
        # 无边框 + 置顶 + 独立工具窗口
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(4)

        # 1. 顶部操作栏 (拖动把手与快捷工具)
        self.header_widget = QWidget(self)
        self.header_widget.setObjectName("headerWidget")
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(6)

        self.title_label = QLabel("🛡️ 魔兽实时翻译 悬浮窗", self.header_widget)
        self.title_label.setStyleSheet("color: #00ccff; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        # 锁定/穿透按钮
        self.btn_lock = QPushButton("🔒 锁定并穿透", self.header_widget)
        self.btn_lock.setToolTip("锁定后鼠标将穿透悬浮窗，可直接点击游戏内部 (可在主面板解锁)")
        self.btn_lock.clicked.connect(self.toggle_lock)
        header_layout.addWidget(self.btn_lock)

        # 清屏按钮
        self.btn_clear = QPushButton("清空", self.header_widget)
        self.btn_clear.clicked.connect(self.clear_messages)
        header_layout.addWidget(self.btn_clear)

        # 隐藏按钮
        self.btn_hide = QPushButton("✕", self.header_widget)
        self.btn_hide.setToolTip("隐藏悬浮窗 (可在控制面板重新打开)")
        self.btn_hide.clicked.connect(self.hide)
        header_layout.addWidget(self.btn_hide)

        main_layout.addWidget(self.header_widget)

        # 2. 消息展示富文本区域
        self.text_browser = QTextBrowser(self)
        self.text_browser.setObjectName("chatBrowser")
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 初始指引提示 (让用户一目了然译文展示位置)
        self.text_browser.setHtml(
            "<div style='color: #00e5ff; padding: 6px; font-size: 12px; line-height: 1.5; border-bottom: 1px dashed rgba(0, 229, 255, 0.3);'>"
            "🛡️ <b>[魔兽实时翻译悬浮窗 已就绪]</b><br>"
            "<span style='color: #cccccc;'>这里是<b>中文翻译结果的同屏实时展示窗口</b>。<br>"
            "当游戏内出现小队/团队英文聊天时，中文译文将以高亮黄色字体实时滚动显示在此处。<br>"
            "👉 <b>快速预览</b>：在主控制面板点击 <b>【🧪 模拟触发测试聊天】</b> 可立即查看翻译效果！</span>"
            "</div>"
        )
        main_layout.addWidget(self.text_browser)

        # 3. 底部轻量调整栏 (仅在未锁定时显示)
        self.footer_widget = QWidget(self)
        footer_layout = QHBoxLayout(self.footer_widget)
        footer_layout.setContentsMargins(4, 0, 4, 0)
        
        self.lbl_opacity = QLabel("透明度:", self.footer_widget)
        self.lbl_opacity.setStyleSheet("color: #888888; font-size: 11px;")
        footer_layout.addWidget(self.lbl_opacity)

        self.slider_opacity = QSlider(Qt.Orientation.Horizontal, self.footer_widget)
        self.slider_opacity.setRange(20, 100)
        cur_opacity = int(self.overlay_cfg.get("opacity", 0.85) * 100)
        self.slider_opacity.setValue(cur_opacity)
        self.slider_opacity.setFixedWidth(80)
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        footer_layout.addWidget(self.slider_opacity)

        footer_layout.addStretch()

        # 窗口右下角缩放手柄
        self.size_grip = QSizeGrip(self)
        footer_layout.addWidget(self.size_grip)

        main_layout.addWidget(self.footer_widget)

        self.update_styles()

    def update_styles(self):
        opacity = self.slider_opacity.value() / 100.0 if hasattr(self, 'slider_opacity') else 0.85
        bg_alpha = int(opacity * 230)
        
        style = f"""
            QWidget#headerWidget {{
                background-color: rgba(20, 24, 30, {bg_alpha});
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 1px solid rgba(0, 204, 255, 0.3);
                border-bottom: none;
            }}
            QTextBrowser#chatBrowser {{
                background-color: rgba(12, 14, 18, {bg_alpha});
                border: 1px solid rgba(0, 204, 255, 0.3);
                border-radius: 0px 0px 8px 8px;
                color: #FFFFFF;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-size: {self.font_size}px;
                padding: 6px;
            }}
            QPushButton {{
                background-color: rgba(40, 50, 65, 200);
                color: #E0E0E0;
                border: 1px solid #455a75;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 180, 255, 180);
                color: #FFFFFF;
            }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: #333333;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #00ccff;
                width: 10px;
                margin: -3px 0;
                border-radius: 5px;
            }}
        """
        self.setStyleSheet(style)

    def apply_geometry_from_config(self):
        x = self.overlay_cfg.get("x", 200)
        y = self.overlay_cfg.get("y", 200)
        w = self.overlay_cfg.get("width", 520)
        h = self.overlay_cfg.get("height", 340)
        self.setGeometry(x, y, w, h)

    def save_geometry_to_config(self):
        geom = self.geometry()
        self.overlay_cfg["x"] = geom.x()
        self.overlay_cfg["y"] = geom.y()
        self.overlay_cfg["width"] = geom.width()
        self.overlay_cfg["height"] = geom.height()
        self.overlay_cfg["opacity"] = self.slider_opacity.value() / 100.0
        self.overlay_cfg["click_through"] = self.is_locked
        self.overlay_cfg["font_size"] = self.font_size
        self.overlay_cfg["show_original"] = self.show_original

    def toggle_lock(self):
        self.set_lock_state(not self.is_locked)

    def set_lock_state(self, locked: bool):
        self.is_locked = locked
        self.save_geometry_to_config()
        self.lock_state_changed.emit(locked)

        if locked:
            self.btn_lock.setText("🔓 已穿透 (点击解锁)")
            self.btn_lock.setStyleSheet("background-color: #aa3333; color: white;")
            self.header_widget.setVisible(False)
            self.footer_widget.setVisible(False)
            self.apply_win32_clickthrough(True)
        else:
            self.btn_lock.setText("🔒 锁定并穿透")
            self.btn_lock.setStyleSheet("")
            self.header_widget.setVisible(True)
            self.footer_widget.setVisible(True)
            self.apply_win32_clickthrough(False)

    def apply_win32_clickthrough(self, enable: bool):
        """利用 Windows 原生 API 切换鼠标穿透"""
        if sys.platform != "win32":
            return
        try:
            import win32gui
            import win32con
            hwnd = int(self.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if enable:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED)
            else:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, (style & ~win32con.WS_EX_TRANSPARENT) | win32con.WS_EX_LAYERED)
        except Exception as e:
            print(f"[Overlay] 设置 Windows 穿透属性失败: {e}")

    def on_opacity_changed(self, val):
        self.update_styles()
        self.save_geometry_to_config()

    def set_font_size(self, size: int):
        self.font_size = max(10, min(28, size))
        self.update_styles()
        self.save_geometry_to_config()
        self.render_messages()

    def set_show_original(self, show: bool):
        self.show_original = show
        self.save_geometry_to_config()
        self.render_messages()

    def clear_messages(self):
        self.messages.clear()
        self.text_browser.clear()

    def append_message(self, data: Dict[str, Any], translation: str, source: str = "openai"):
        """
        向悬浮窗添加一条格式化的翻译记录
        data 包含: time, channel, channel_display, sender, content
        """
        ch_type = data.get("channel", "Other")
        self.messages.append((dict(data), translation, source))
        self.render_messages()

    def format_message(self, data, translation, source):
        ch_type = data.get("channel", "Other")
        ch_disp = escape(data.get("channel_display", "[聊天]"))
        sender = escape(data.get("sender", ""))
        content = escape(data.get("content", ""))
        time_str = escape(data.get("time", ""))
        translation = escape(translation)

        color = CHANNEL_COLORS.get(ch_type, "#FFFFFF")

        # 来源标识
        src_tag = ""
        if source == "local_dict":
            src_tag = "<span style='color: #4CAF50; font-size: 10px;'>[本地速查]</span> "
        elif source == "cache":
            src_tag = "<span style='color: #2196F3; font-size: 10px;'>[缓存]</span> "

        sender_html = f"<span style='color: #E5C158; font-weight: bold;'>[{sender}]</span>: " if sender else ""
        time_html = f"<span style='color: #777777; font-size: 10px;'>{time_str[-8:]}</span> "

        # 组装 HTML
        html = f"<div style='margin-bottom: 6px; line-height: 1.3;'>"
        html += f"{time_html}<span style='color: {color}; font-weight: bold;'>{ch_disp}</span> {sender_html}{src_tag}"
        
        # 英文原文 (小字浅灰)
        if self.show_original and content != translation:
            html += f"<div style='color: #9E9E9E; font-size: {max(9, self.font_size - 2)}px; margin-left: 4px;'>{content}</div>"
            
        # 中文译文 (加粗高亮显眼)
        html += f"<div style='color: #FFFF99; font-weight: 500; font-size: {self.font_size}px; margin-left: 4px;'>➜ {translation}</div>"
        html += f"</div>"

        return html

    def render_messages(self):
        self.text_browser.setHtml("".join(self.format_message(*message) for message in self.messages))
        # 自动滚动到底部
        scrollbar = self.text_browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # 窗口拖动实现
    def mousePressEvent(self, event):
        if not self.is_locked and event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.is_locked and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.save_geometry_to_config()
            event.accept()

    def closeEvent(self, event):
        self.save_geometry_to_config()
        super().closeEvent(event)
