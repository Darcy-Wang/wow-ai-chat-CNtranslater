import os
import sys
import re
import time
from collections import deque
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QRect
from PyQt6.QtGui import QIcon, QFont, QColor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QGroupBox, QSpinBox, QSlider, QFrame,
    QDoubleSpinBox, QTextEdit, QPlainTextEdit, QApplication
)

from app.translation_queue import TranslationQueue
from app.screen_region import physical_region
from app.config import ConfigManager
from app.wow_detector import WowDetector
from app.log_watcher import LogWatcherThread
from app.translator import WowTranslator
from app.overlay_window import OverlayWindow, CHANNEL_COLORS
from app.ocr_watcher import OcrWatcherThread
from app.ocr_selector import RegionSelectorWindow

class ConsoleOutputRedirector(QObject):
    text_written = pyqtSignal(str)

    def __init__(self, original_stream):
        super().__init__()
        self.original_stream = original_stream

    def write(self, text):
        try:
            if self.original_stream is not None:
                self.original_stream.write(text)
                self.original_stream.flush()
        except Exception:
            pass
        if text.strip():
            self.text_written.emit(text.rstrip())

    def flush(self):
        try:
            if self.original_stream is not None:
                self.original_stream.flush()
        except Exception:
            pass

class TranslationWorkerSignals(QObject):
    finished = pyqtSignal(dict, str, str, float)  # (parsed_data, translation, source, elapsed)
    test_finished = pyqtSignal(bool, str, float)   # (ok, msg, latency)
    ocr_test_finished = pyqtSignal(list, str)      # (results, error_msg)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("魔兽世界实时聊天翻译器 (WoW Chat AI Translator)")
        self.resize(920, 680)

        # 加载配置
        self.config_mgr = ConfigManager()
        self.config = self.config_mgr.config

        # 核心服务初始化
        startup_error = ""
        try:
            self.translator = WowTranslator(
                api_key=self.config.get("api_key", ""),
                base_url=self.config.get("base_url", "https://api.openai.com/v1"),
                model=self.config.get("model", "gpt-4o-mini"),
                target_language=self.config.get("target_language", "中文"))
        except Exception:
            self.translator = WowTranslator()
            startup_error = "接口客户端初始化失败，请检查并重新保存 API 设置"
        self.thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diagnostics")
        self.translation_queue = TranslationQueue(
            capacity=int(self.config.get("max_pending", 23)),
            max_age=float(self.config.get("message_max_age", 12.0)))
        self._closing = False
        self._capture_epoch = 0
        self._retired_watchers = []
        self._pending_rows = {}
        self._record_ids = deque()
        self._latencies = deque(maxlen=1000)
        self._dropped = 0
        self._last_result_status = ""
        self._diagnostic_futures = set()
        self.worker_signals = TranslationWorkerSignals()

        self.worker_signals.test_finished.connect(self.on_api_test_finished)
        self.worker_signals.ocr_test_finished.connect(self.on_ocr_test_finished)

        # 统计数据
        self.stat_captured = 0
        self.stat_translated = 0
        self.stat_dict_hits = 0
        self.stat_total_time = 0.0

        # 创建悬浮窗
        self.overlay = OverlayWindow(self.config)
        self.overlay.lock_state_changed.connect(self.on_overlay_lock_changed)
        if self.config.get("overlay", {}).get("visible", True):
            self.overlay.show()

        # 监听线程
        self.log_watcher = None
        self.ocr_watcher = None
        self.region_selector = None

        # 控制台重定向 (终端与软件内双向同步打印)
        self.log_redirector = ConsoleOutputRedirector(sys.stdout)
        self.log_redirector.text_written.connect(self.append_console_log)
        sys.stdout = self.log_redirector

        self.init_ui()
        self.load_settings_to_ui()
        self.config_mgr.on_error = self.on_config_error
        if self.config_mgr.last_error:
            QTimer.singleShot(0, lambda: self.on_config_error(self.config_mgr.last_error))
        if startup_error:
            QTimer.singleShot(0, lambda: self.on_config_error(startup_error))
        self.auto_detect_wow_setup()
        self.delivery_timer = QTimer(self)
        self.delivery_timer.timeout.connect(self.poll_translations)
        self.delivery_timer.start(100)

    def append_console_log(self, text: str):
        if hasattr(self, 'log_console_edit'):
            self.log_console_edit.appendPlainText(text)

    def init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 顶部全局状态栏
        main_layout.addWidget(self.create_top_bar())

        # 标签页
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.create_monitor_tab(), "📊 实时监控")
        self.tabs.addTab(self.create_ocr_tab(), "📷 屏幕 OCR 设置")
        self.tabs.addTab(self.create_api_tab(), "🤖 AI 接口配置")
        self.tabs.addTab(self.create_filter_tab(), "🎯 频道与过滤")
        self.tabs.addTab(self.create_wow_tab(), "🎮 游戏与日志模式")
        self.tabs.addTab(self.create_log_tab(), "📜 运行控制台")
        main_layout.addWidget(self.tabs)

        self.apply_theme()

    def create_top_bar(self) -> QWidget:
        bar = QFrame(self)
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        bar.setStyleSheet("background-color: #1e222b; border-radius: 8px; padding: 6px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)

        self.lbl_status_indicator = QLabel("● 监听状态: 未启动", bar)
        self.lbl_status_indicator.setStyleSheet("color: #888888; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.lbl_status_indicator)

        layout.addSpacing(15)

        # 模式切换
        lbl_mode = QLabel("工作模式:", bar)
        lbl_mode.setStyleSheet("color: #00ccff; font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl_mode)

        self.combo_work_mode = QComboBox(bar)
        self.combo_work_mode.addItems([
            "📷 屏幕 OCR 实时捕获 (秒级·推荐)",
            "📄 日志文件模式 (/chatlog)"
        ])
        cur_mode = self.config.get("work_mode", "ocr")
        self.combo_work_mode.setCurrentIndex(0 if cur_mode == "ocr" else 1)
        self.combo_work_mode.currentIndexChanged.connect(self.on_work_mode_changed)
        layout.addWidget(self.combo_work_mode)

        self.btn_select_region = QPushButton("📐 框选区域", bar)
        self.btn_select_region.setToolTip("打开屏幕框选器，调整要抓取翻译的聊天区域")
        self.btn_select_region.clicked.connect(self.open_region_selector)
        layout.addWidget(self.btn_select_region)

        layout.addStretch()

        self.btn_toggle_listen = QPushButton("▶ 启动捕获", bar)
        self.btn_toggle_listen.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        self.btn_toggle_listen.clicked.connect(self.toggle_listening)
        layout.addWidget(self.btn_toggle_listen)

        self.btn_toggle_overlay = QPushButton("🖥️ 悬浮窗", bar)
        self.btn_toggle_overlay.clicked.connect(self.toggle_overlay_visibility)
        layout.addWidget(self.btn_toggle_overlay)

        self.btn_lock_overlay = QPushButton("🔒 解锁悬浮窗", bar)
        self.btn_lock_overlay.clicked.connect(self.toggle_overlay_lock)
        layout.addWidget(self.btn_lock_overlay)

        return bar

    def create_monitor_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # 统计指标卡片
        stats_box = QHBoxLayout()
        self.card_captured = self.create_stat_card("已捕获消息", "0")
        self.card_translated = self.create_stat_card("AI 翻译次数", "0")
        self.card_dict_hits = self.create_stat_card("本地字典秒答", "0")
        self.card_avg_time = self.create_stat_card("平均端到端延迟", "0 ms")
        stats_box.addWidget(self.card_captured)
        stats_box.addWidget(self.card_translated)
        stats_box.addWidget(self.card_dict_hits)
        stats_box.addWidget(self.card_avg_time)
        layout.addLayout(stats_box)
        self.lbl_pipeline_status = QLabel("待展示 0 | 首次使用：框选区域 → 测试 OCR → 测试接口 → 预览译文", widget)
        self.lbl_pipeline_status.setWordWrap(True)
        layout.addWidget(self.lbl_pipeline_status)
        self.lbl_first_use = QLabel("首次使用：框选并测试 OCR → 测试并保存接口 → 模拟消息预览 → 启动捕获", widget)
        self.lbl_first_use.setWordWrap(True)
        self.lbl_first_use.setVisible(not bool(self.config.get("api_key")))
        layout.addWidget(self.lbl_first_use)

        # 显眼的位置说明横幅与悬浮窗召回按钮
        tip_frame = QFrame(widget)
        tip_frame.setStyleSheet("background-color: rgba(0, 204, 255, 0.1); border: 1px solid rgba(0, 204, 255, 0.3); border-radius: 6px; padding: 4px;")
        h_tip = QHBoxLayout(tip_frame)
        h_tip.setContentsMargins(10, 6, 10, 6)
        lbl_tip = QLabel("📌 <b>翻译显示位置</b>：中文译文将实时同步呈现在<b>【游戏屏幕置顶悬浮窗】</b>以及下方监控表格的<b>【翻译结果】</b>列中。", tip_frame)
        lbl_tip.setStyleSheet("color: #00e5ff; font-size: 12px;")
        h_tip.addWidget(lbl_tip)
        h_tip.addStretch()

        btn_center_overlay = QPushButton("🎯 召回/居中悬浮窗", tip_frame)
        btn_center_overlay.setStyleSheet("background-color: #0288d1; color: white; padding: 4px 10px; font-weight: bold; border-radius: 4px;")
        btn_center_overlay.clicked.connect(self.center_overlay_window)
        h_tip.addWidget(btn_center_overlay)
        layout.addWidget(tip_frame)

        # 监控列表表格
        self.table_logs = QTableWidget(0, 5, widget)
        self.table_logs.setHorizontalHeaderLabels(["时间", "频道", "发送者", "原文内容", "翻译结果"])
        self.table_logs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_logs.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_logs)

        # 底部快捷测试按钮
        btn_bar = QHBoxLayout()
        self.btn_send_test = QPushButton("🧪 模拟触发测试聊天 (无需组队)", widget)
        self.btn_send_test.clicked.connect(self.simulate_test_message)
        btn_bar.addWidget(self.btn_send_test)

        self.btn_clear_table = QPushButton("清空记录", widget)
        self.btn_clear_table.clicked.connect(self.clear_table_records)
        btn_bar.addWidget(self.btn_clear_table)
        btn_bar.addStretch()

        layout.addLayout(btn_bar)
        return widget

    def create_stat_card(self, title: str, value: str) -> QWidget:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet("background-color: #232733; border: 1px solid #333a4c; border-radius: 6px; padding: 6px;")
        v = QVBoxLayout(card)
        v.setContentsMargins(6, 6, 6, 6)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #999999; font-size: 11px;")
        lbl_val = QLabel(value)
        lbl_val.setStyleSheet("color: #00ccff; font-size: 18px; font-weight: bold;")
        lbl_val.setObjectName("valLabel")
        v.addWidget(lbl_title)
        v.addWidget(lbl_val)
        return card

    def update_stat_card(self, card: QWidget, val_str: str):
        lbl = card.findChild(QLabel, "valLabel")
        if lbl:
            lbl.setText(val_str)

    def create_ocr_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 核心优势说明
        group_intro = QGroupBox("屏幕 OCR 实时捕获原理与优势")
        v_intro = QVBoxLayout(group_intro)
        lbl_info = QLabel(
            "🌟 核心优势：通过屏幕识别减少对日志落盘时机的依赖。\n"
            "直接截取游戏内聊天框（或任务/NPC对话）区域，通过本地轻量高精度 RapidOCR 引擎进行文字识别，翻译延迟取决于检测间隔、识别、排队及接口响应。",
            group_intro
        )
        lbl_info.setStyleSheet("color: #b0bec5; font-size: 12px; line-height: 1.4;")
        v_intro.addWidget(lbl_info)
        layout.addWidget(group_intro)

        # 区域设置
        group_region = QGroupBox("捕获区域设置")
        v_region = QVBoxLayout(group_region)

        h_btn_box = QHBoxLayout()
        self.btn_open_selector = QPushButton("📐 打开半透明虚线框选器 (拖动对准游戏聊天栏)", group_region)
        self.btn_open_selector.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        self.btn_open_selector.clicked.connect(self.open_region_selector)
        h_btn_box.addWidget(self.btn_open_selector)

        btn_p2k = QPushButton("🎯 2K主屏预设", group_region)
        btn_p2k.clicked.connect(lambda: self.apply_preset_region(30, 1050, 580, 330))
        h_btn_box.addWidget(btn_p2k)

        btn_p1080 = QPushButton("🎯 1080P主屏预设", group_region)
        btn_p1080.clicked.connect(lambda: self.apply_preset_region(20, 780, 480, 260))
        h_btn_box.addWidget(btn_p1080)

        h_btn_box.addStretch()
        v_region.addLayout(h_btn_box)

        # 当前坐标指示
        self.lbl_current_region = QLabel("", group_region)
        self.lbl_current_region.setStyleSheet("color: #00ccff; font-weight: bold; margin-top: 4px;")
        v_region.addWidget(self.lbl_current_region)
        self.update_region_label()

        # 扫描频率
        h_interval = QHBoxLayout()
        h_interval.addWidget(QLabel("截屏检测间隔 (秒):", group_region))
        self.spin_interval = QDoubleSpinBox(group_region)
        self.spin_interval.setRange(0.5, 5.0)
        self.spin_interval.setSingleStep(0.2)
        self.spin_interval.setValue(float(self.config.get("ocr_interval", 1.0)))
        self.spin_interval.valueChanged.connect(self.on_ocr_interval_changed)
        h_interval.addWidget(self.spin_interval)

        lbl_hint = QLabel("(注: 内置帧间差分检测算法，画面无明显变化时跳过 OCR，仍执行截图和差分)", group_region)
        lbl_hint.setStyleSheet("color: #888888; font-size: 11px;")
        h_interval.addWidget(lbl_hint)
        h_interval.addStretch()
        v_region.addLayout(h_interval)

        layout.addWidget(group_region)

        # 识别测试区
        group_test = QGroupBox("识别调试与即时测试")
        v_test = QVBoxLayout(group_test)

        h_tbar = QHBoxLayout()
        self.btn_test_ocr = QPushButton("🖼️ 截取当前区域并测试 OCR 识别", group_test)
        self.btn_test_ocr.setStyleSheet("background-color: #5c6bc0; color: white; padding: 6px 12px; font-weight: bold; border-radius: 4px;")
        self.btn_test_ocr.clicked.connect(self.test_ocr_capture)
        h_tbar.addWidget(self.btn_test_ocr)

        self.lbl_ocr_test_status = QLabel("", group_test)
        h_tbar.addWidget(self.lbl_ocr_test_status)
        h_tbar.addStretch()
        v_test.addLayout(h_tbar)

        self.edit_ocr_result = QTextEdit(group_test)
        self.edit_ocr_result.setReadOnly(True)
        self.edit_ocr_result.setPlaceholderText("点击上方测试按钮后，这里将显示识别出的文字行...")
        self.edit_ocr_result.setFixedHeight(120)
        v_test.addWidget(self.edit_ocr_result)

        layout.addWidget(group_test)
        layout.addStretch()
        return widget

    def update_region_label(self):
        reg = self.config.get("ocr_region", {"left": 30, "top": 1050, "width": 580, "height": 330})
        if hasattr(self, 'lbl_current_region'):
            self.lbl_current_region.setText(
                f"当前捕获区域: X={reg.get('left')}, Y={reg.get('top')} | 宽度={reg.get('width')}, 高度={reg.get('height')}"
            )

    def apply_preset_region(self, left: int, top: int, width: int, height: int):
        reg = {"left": left, "top": top, "width": width, "height": height}
        self.on_region_saved(reg)

    def open_region_selector(self):
        reg = self.config.get("ocr_region", {"left": 30, "top": 1050, "width": 580, "height": 330})
        self.region_selector = RegionSelectorWindow(reg)
        self.region_selector.region_saved.connect(self.on_region_saved)
        self.region_selector.show()

    def on_region_saved(self, region: Dict[str, int]):
        self.config["ocr_region"] = region
        if not self.config_mgr.save():
            return
        self.update_region_label()
        if self.ocr_watcher:
            try:
                self.ocr_watcher.update_region(self.capture_region())
            except ValueError as error:
                self.stop_listening()
                QMessageBox.warning(self, "区域无效", str(error))
        QMessageBox.information(
            self,
            "区域已保存",
            f"已保存抓取区域: X={region['left']}, Y={region['top']}, 尺寸={region['width']}x{region['height']}"
        )

    def on_ocr_interval_changed(self, val: float):
        self.config["ocr_interval"] = val
        self.config_mgr.save()
        if self.ocr_watcher:
            self.ocr_watcher.update_interval(val)

    def on_work_mode_changed(self, idx: int):
        mode = "ocr" if idx == 0 else "log"
        self.config["work_mode"] = mode
        self.config_mgr.save()
        # 如果当前正在运行，提示重启
        if (self.ocr_watcher and self.ocr_watcher.isRunning()) or (self.log_watcher and self.log_watcher.isRunning()):
            self.stop_listening()
            self.start_listening()

    def test_ocr_capture(self):
        self.lbl_ocr_test_status.setText("正在截图并执行 OCR 识别...")
        self.lbl_ocr_test_status.setStyleSheet("color: #ff9800;")
        self.btn_test_ocr.setEnabled(False)

        try:
            reg = self.capture_region()
        except ValueError as error:
            self.on_ocr_test_finished([], str(error))
            return
        if self.overlay_overlaps_capture():
            self.on_ocr_test_finished([], "请先将悬浮窗移到捕获区域外，避免识别自身译文")
            return

        def _worker():
            try:
                import mss
                import numpy as np
                from rapidocr_onnxruntime import RapidOCR

                with mss.MSS() as sct:
                    monitor = {
                        "left": int(reg.get("left", 30)),
                        "top": int(reg.get("top", 1050)),
                        "width": int(reg.get("width", 580)),
                        "height": int(reg.get("height", 330))
                    }
                    shot = sct.grab(monitor)
                    img_np = np.array(shot)
                    img_rgb = img_np[..., :3].copy()

                engine = RapidOCR()
                res, _ = engine(img_rgb)
                lines = []
                if res:
                    for item in res:
                        lines.append(f"• {item[1]} (置信度: {int(item[2]*100)}%)")
                return lines, ""
            except Exception as e:
                return [], "OCR 测试失败：" + type(e).__name__

        def _task():
            lines, err = _worker()
            self.worker_signals.ocr_test_finished.emit(lines, err)

        self._diagnostic_futures.add(self.thread_pool.submit(_task))

    def on_ocr_test_finished(self, lines: List[str], err: str):
        self.btn_test_ocr.setEnabled(True)
        if err:
            self.lbl_ocr_test_status.setText(f"❌ 识别出错: {err}")
            self.lbl_ocr_test_status.setStyleSheet("color: #f44336;")
            self.edit_ocr_result.setPlainText(f"错误详情: {err}")
        elif lines:
            self.lbl_ocr_test_status.setText(f"✓ 成功识别到 {len(lines)} 行文字！")
            self.lbl_ocr_test_status.setStyleSheet("color: #4caf50;")
            self.edit_ocr_result.setPlainText("\n".join(lines))
        else:
            self.lbl_ocr_test_status.setText("⚠ 未识别到文字 (请确认所选区域内是否有文字显示)")
            self.lbl_ocr_test_status.setStyleSheet("color: #ff9800;")
            self.edit_ocr_result.setPlainText("当前区域画面内没有检测到清晰文字。建议点击“打开半透明虚线框选器”重新对齐游戏聊天栏。")

    def create_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        group_api = QGroupBox("OpenAI / DeepSeek / 兼容接口设置")
        form = QVBoxLayout(group_api)

        # 预设快速选择
        h_preset = QHBoxLayout()
        h_preset.addWidget(QLabel("服务预设:", group_api))
        self.combo_presets = QComboBox(group_api)
        self.combo_presets.addItems([
            "OpenAI 官方 (gpt-4o-mini)",
            "DeepSeek 官方 (deepseek-chat - 超高性价比推荐)",
            "自定义 / 第三方代理"
        ])
        self.combo_presets.currentIndexChanged.connect(self.on_preset_changed)
        h_preset.addWidget(self.combo_presets)
        h_preset.addStretch()
        form.addLayout(h_preset)

        # Base URL
        h_url = QHBoxLayout()
        h_url.addWidget(QLabel("API 地址 (Base URL):", group_api))
        self.edit_base_url = QLineEdit(group_api)
        self.edit_base_url.setPlaceholderText("https://api.openai.com/v1")
        h_url.addWidget(self.edit_base_url)
        form.addLayout(h_url)

        # API Key
        h_key = QHBoxLayout()
        h_key.addWidget(QLabel("API Key (密钥):", group_api))
        self.edit_api_key = QLineEdit(group_api)
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_api_key.setPlaceholderText("sk-...")
        h_key.addWidget(self.edit_api_key)

        self.btn_toggle_key_echo = QPushButton("👁️ 显示/隐藏", group_api)
        self.btn_toggle_key_echo.clicked.connect(self.toggle_key_echo)
        h_key.addWidget(self.btn_toggle_key_echo)
        form.addLayout(h_key)

        # 模型名称
        h_model = QHBoxLayout()
        h_model.addWidget(QLabel("模型名称 (Model):", group_api))
        self.edit_model = QLineEdit(group_api)
        self.edit_model.setPlaceholderText("gpt-4o-mini 或 deepseek-chat")
        h_model.addWidget(self.edit_model)
        form.addLayout(h_model)

        # 测试按钮
        h_test = QHBoxLayout()
        self.btn_test_api = QPushButton("⚡ 测试 API 连通性与测速", group_api)
        self.btn_test_api.setStyleSheet("background-color: #0288d1; color: white; padding: 6px 12px; border-radius: 4px;")
        self.btn_test_api.clicked.connect(self.test_api_connection)
        h_test.addWidget(self.btn_test_api)

        self.lbl_api_test_result = QLabel("", group_api)
        h_test.addWidget(self.lbl_api_test_result)
        h_test.addStretch()
        form.addLayout(h_test)

        layout.addWidget(group_api)

        # 保存设置按钮
        h_save = QHBoxLayout()
        self.btn_save_api = QPushButton("💾 保存 API 设置", widget)
        self.btn_save_api.clicked.connect(self.save_api_settings)
        h_save.addWidget(self.btn_save_api)
        h_save.addStretch()
        layout.addLayout(h_save)

        layout.addStretch()
        return widget

    def create_filter_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 频道过滤
        group_ch = QGroupBox("监听频道过滤 (打钩代表翻译，取消代表忽略)")
        ch_layout = QVBoxLayout(group_ch)

        self.ch_checkboxes: Dict[str, QCheckBox] = {}
        channels_info = [
            ("Party", "小队频道 (Party - 强烈推荐)"),
            ("Raid", "团队频道 / 团队警告 (Raid / Raid Warning - 强烈推荐)"),
            ("Instance", "副本队伍 / 副本团 (Instance / Instance Chat)"),
            ("Other", "日志中的其他频道"),
            ("Whisper", "密语 / 私聊 (Whisper - 强烈推荐)"),
            ("Say", "说话频道 (Say)"),
            ("Yell", "大喊频道 (Yell)"),
            ("Guild", "公会频道 (Guild)"),
            ("General", "综合频道 (General - 人多易耗费 Token)"),
            ("Trade", "交易频道 (Trade)"),
            ("World", "世界 / 寻组频道 (World / LFG)"),
        ]

        grid = QHBoxLayout()
        v1 = QVBoxLayout()
        v2 = QVBoxLayout()
        for idx, (ch_key, ch_name) in enumerate(channels_info):
            cb = QCheckBox(ch_name, group_ch)
            self.ch_checkboxes[ch_key] = cb
            if idx < 5:
                v1.addWidget(cb)
            else:
                v2.addWidget(cb)
        grid.addLayout(v1)
        grid.addLayout(v2)
        ch_layout.addLayout(grid)
        layout.addWidget(group_ch)

        # 智能省 Token 与优化规则
        group_rule = QGroupBox("智能翻译优化策略")
        rule_layout = QVBoxLayout(group_rule)

        self.cb_skip_chinese = QCheckBox("跳过纯中文消息（中英混合消息仍翻译）", group_rule)
        rule_layout.addWidget(self.cb_skip_chinese)

        self.cb_local_dict = QCheckBox("启用本地游戏黑话速查字典 (如 'inv', 'wipe', '111', 'pull' 毫秒级零成本秒答)", group_rule)
        rule_layout.addWidget(self.cb_local_dict)
        self.cb_ocr_unknown = QCheckBox("翻译 OCR 中无法识别频道的文字（可能包含公共频道或 NPC 对话）", group_rule)
        rule_layout.addWidget(self.cb_ocr_unknown)

        self.cb_show_original = QCheckBox("悬浮窗同时显示英文原文与中文译文", group_rule)
        rule_layout.addWidget(self.cb_show_original)

        # 玩家姓名保护设置
        h_names = QHBoxLayout()
        lbl_names = QLabel("自定义保护玩家姓名 (多个用逗号隔开):", group_rule)
        lbl_names.setStyleSheet("color: #81c784; font-weight: bold;")
        h_names.addWidget(lbl_names)
        self.edit_custom_names = QLineEdit(group_rule)
        self.edit_custom_names.setPlaceholderText("例如: Usher, Shadowslayer, Healerbro (永久禁止AI意译为中文)")
        h_names.addWidget(self.edit_custom_names)
        rule_layout.addLayout(h_names)

        # 字体大小滑块
        h_font = QHBoxLayout()
        h_font.addWidget(QLabel("悬浮窗字体大小:", group_rule))
        self.spin_font_size = QSpinBox(group_rule)
        self.spin_font_size.setRange(10, 24)
        self.spin_font_size.valueChanged.connect(self.on_font_size_changed)
        h_font.addWidget(self.spin_font_size)
        h_font.addStretch()
        rule_layout.addLayout(h_font)

        layout.addWidget(group_rule)

        btn_save = QPushButton("💾 保存频道与规则设置", widget)
        btn_save.clicked.connect(self.save_filter_settings)
        layout.addWidget(btn_save)

        layout.addStretch()
        return widget

    def create_wow_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 游戏目录与日志路径
        group_path = QGroupBox("魔兽世界安装与日志文件定位")
        form = QVBoxLayout(group_path)

        h_detect = QHBoxLayout()
        h_detect.addWidget(QLabel("已检测到的客户端:", group_path))
        self.combo_installations = QComboBox(group_path)
        self.combo_installations.currentIndexChanged.connect(self.on_installation_selected)
        h_detect.addWidget(self.combo_installations)

        self.btn_rescan = QPushButton("🔄 重新扫描", group_path)
        self.btn_rescan.clicked.connect(self.auto_detect_wow_setup)
        h_detect.addWidget(self.btn_rescan)
        form.addLayout(h_detect)

        # 当前监听的日志完整路径
        h_file = QHBoxLayout()
        h_file.addWidget(QLabel("当前日志文件:", group_path))
        self.edit_log_path = QLineEdit(group_path)
        h_file.addWidget(self.edit_log_path)
        self.btn_browse_log = QPushButton("浏览...", group_path)
        self.btn_browse_log.clicked.connect(self.browse_log_file)
        h_file.addWidget(self.btn_browse_log)
        form.addLayout(h_file)

        self.lbl_log_status = QLabel("", group_path)
        form.addWidget(self.lbl_log_status)

        layout.addWidget(group_path)

        # 一键安装游戏内插件
        group_addon = QGroupBox("游戏内置辅助插件 (WowChatTranslator)")
        addon_layout = QVBoxLayout(group_addon)
        lbl_addon_intro = QLabel(
            "说明: 暴雪默认在每次退出游戏后会关闭 /chatlog。安装本插件后，登录游戏会自动开启日志，无需手动输入 /chatlog 命令。",
            group_addon
        )
        lbl_addon_intro.setWordWrap(True)
        lbl_addon_intro.setStyleSheet("color: #b0bec5; font-size: 12px;")
        addon_layout.addWidget(lbl_addon_intro)

        h_addon_btn = QHBoxLayout()
        self.btn_install_addon = QPushButton("📥 一键安装/更新插件到当前客户端", group_addon)
        self.btn_install_addon.setStyleSheet("background-color: #5c6bc0; color: white; padding: 6px 14px; font-weight: bold; border-radius: 4px;")
        self.btn_install_addon.clicked.connect(self.install_addon)
        h_addon_btn.addWidget(self.btn_install_addon)
        h_addon_btn.addStretch()
        addon_layout.addLayout(h_addon_btn)

        layout.addWidget(group_addon)
        layout.addStretch()
        return widget

    def apply_theme(self):
        style = """
            QMainWindow {
                background-color: #12141a;
            }
            QTabWidget::pane {
                border: 1px solid #2d3345;
                background-color: #181b24;
                border-radius: 6px;
            }
            QTabBar::tab {
                background-color: #1c202b;
                color: #a0a6b5;
                padding: 8px 16px;
                font-weight: bold;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #242938;
                color: #00ccff;
                border-bottom: 2px solid #00ccff;
            }
            QGroupBox {
                color: #00ccff;
                font-weight: bold;
                border: 1px solid #2d3345;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
            }
            QLabel {
                color: #e0e0e0;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #202430;
                color: #ffffff;
                border: 1px solid #3d455b;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #00ccff;
            }
            QPushButton {
                background-color: #2d3446;
                color: #e0e0e0;
                border: 1px solid #45506b;
                border-radius: 4px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background-color: #384259;
                color: #ffffff;
            }
            QTableWidget {
                background-color: #161922;
                color: #ffffff;
                gridline-color: #262c3d;
                border: 1px solid #262c3d;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #202533;
                color: #00ccff;
                font-weight: bold;
                border: 1px solid #262c3d;
                padding: 4px;
            }
            QCheckBox {
                color: #d0d0d0;
            }
            QCheckBox::indicator:checked {
                background-color: #00ccff;
                border: 1px solid #00ccff;
            }
        """
        self.setStyleSheet(style)

    def load_settings_to_ui(self):
        # API 配置
        self.edit_base_url.setText(self.config.get("base_url", "https://api.openai.com/v1"))
        self.edit_api_key.setText(self.config.get("api_key", ""))
        self.edit_model.setText(self.config.get("model", "gpt-4o-mini"))

        # 频道设置
        cfg_channels = self.config.get("channels", {})
        for ch_key, cb in self.ch_checkboxes.items():
            cb.setChecked(cfg_channels.get(ch_key, True))

        # 规则设置
        self.cb_skip_chinese.setChecked(self.config.get("skip_chinese", True))
        self.cb_local_dict.setChecked(self.config.get("enable_local_dict", True))
        self.cb_ocr_unknown.setChecked(self.config.get("ocr_unknown_channel", True))

        # 玩家姓名保护
        custom_names = self.config.get("protected_names", "")
        self.edit_custom_names.setText(custom_names)
        self.translator.set_protected_names(custom_names.replace("，", ",").split(","))

        overlay_cfg = self.config.get("overlay", {})
        self.cb_show_original.setChecked(overlay_cfg.get("show_original", True))
        self.spin_font_size.setValue(overlay_cfg.get("font_size", 13))

        # 日志路径
        self.edit_log_path.setText(self.config.get("wow_log_path", ""))

        self.update_lock_button_ui(self.overlay.is_locked)

    def auto_detect_wow_setup(self):
        """扫描魔兽安装并在下拉框展示"""
        self.installations = WowDetector.scan_installations()
        self.combo_installations.clear()

        if not self.installations:
            self.combo_installations.addItem("未检测到魔兽目录 (请手动选择日志文件)", "")
            self.lbl_log_status.setText("⚠ 未自动发现魔兽客户端，请点击上方“浏览...”手动选择 WoWChatLog.txt")
            self.lbl_log_status.setStyleSheet("color: #ff9800;")
            return

        selected_idx = 0
        cfg_path = self.config.get("wow_log_path", "")
        for idx, item in enumerate(self.installations):
            self.combo_installations.addItem(item["name"], item)
            if cfg_path and os.path.normpath(item["log_path"]).lower() == os.path.normpath(cfg_path).lower():
                selected_idx = idx

        self.combo_installations.setCurrentIndex(selected_idx)
        self.on_installation_selected(selected_idx)

    def on_installation_selected(self, index: int):
        if index < 0 or index >= len(self.installations):
            return
        item = self.installations[index]
        log_path = item["log_path"]
        self.edit_log_path.setText(log_path)
        self.config["wow_log_path"] = log_path
        self.config_mgr.save()

        if os.path.exists(log_path):
            self.lbl_log_status.setText(f"✓ 找到日志文件: {log_path}")
            self.lbl_log_status.setStyleSheet("color: #4caf50;")
        else:
            self.lbl_log_status.setText(f"ℹ 该客户端尚未生成日志文件 (请在游戏内输入 /chatlog 或安装插件后登录)")
            self.lbl_log_status.setStyleSheet("color: #ff9800;")

    def browse_log_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 WoWChatLog.txt",
            self.edit_log_path.text() or r"C:\Program Files (x86)\World of Warcraft",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if path:
            self.edit_log_path.setText(path)
            self.config["wow_log_path"] = path
            self.config_mgr.save()
            if self.log_watcher:
                self.log_watcher.set_log_path(path)

    def install_addon(self):
        idx = self.combo_installations.currentIndex()
        if idx < 0 or idx >= len(self.installations):
            QMessageBox.warning(self, "提示", "请先选择有效的魔兽客户端版本！")
            return
        item = self.installations[idx]
        flavor_dir = item["flavor_dir"]
        try:
            WowDetector.install_addon_to_flavor(flavor_dir)
            target = os.path.join(flavor_dir, "Interface", "AddOns", "WowChatTranslator")
            QMessageBox.information(
                self,
                "插件安装成功",
                f"已成功安装 WowChatTranslator 插件到:\n{target}\n\n请在游戏内输入 /reload 重载界面即可生效！"
            )
        except Exception as e:
            QMessageBox.critical(self, "安装失败", f"插件复制失败: {e}")

    def on_preset_changed(self, idx: int):
        if idx == 0:  # OpenAI
            self.edit_base_url.setText("https://api.openai.com/v1")
            self.edit_model.setText("gpt-4o-mini")
        elif idx == 1:  # DeepSeek
            self.edit_base_url.setText("https://api.deepseek.com")
            self.edit_model.setText("deepseek-chat")

    def toggle_key_echo(self):
        if self.edit_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)

    def test_api_connection(self):
        key = self.edit_api_key.text().strip()
        url = self.edit_base_url.text().strip()
        model = self.edit_model.text().strip()

        if not key:
            self.lbl_api_test_result.setText("❌ API Key 不能为空")
            self.lbl_api_test_result.setStyleSheet("color: #f44336;")
            return

        self.lbl_api_test_result.setText("正在测试连接...")
        self.lbl_api_test_result.setStyleSheet("color: #ff9800;")
        self.btn_test_api.setEnabled(False)

        # 异步测试 (在独立工作线程中运行，完成后发射 Qt 信号安全回调主线程)
        def _test():
            try:
                trans = WowTranslator(api_key=key, base_url=url, model=model)
                ok, msg, latency = trans.test_connection()
            except Exception:
                ok, msg, latency = False, "接口设置无效，请检查地址和模型", 0.0
            self.worker_signals.test_finished.emit(ok, msg, latency)

        self._diagnostic_futures.add(self.thread_pool.submit(_test))

    def on_api_test_finished(self, ok: bool, msg: str, latency: float):
        self.btn_test_api.setEnabled(True)
        if ok:
            self.lbl_api_test_result.setText(f"✓ {msg} (延迟: {int(latency*1000)}ms)")
            self.lbl_api_test_result.setStyleSheet("color: #4caf50;")
        else:
            self.lbl_api_test_result.setText(f"❌ {msg}")
            self.lbl_api_test_result.setStyleSheet("color: #f44336;")

    def save_api_settings(self):
        settings = (self.edit_api_key.text().strip(), self.edit_base_url.text().strip(), self.edit_model.text().strip())
        try:
            # Validate before replacing the currently usable client.
            replacement = WowTranslator(*settings, target_language=self.config.get("target_language", "中文"))
        except Exception:
            QMessageBox.warning(self, "设置无效", "请检查 API 地址和模型设置")
            return
        keys = ("api_key", "base_url", "model")
        previous = {key: self.config.get(key, "") for key in keys}
        self.config.update(zip(keys, settings))
        if not self.config_mgr.save():
            self.config.update(previous)
            return
        self.invalidate_translations()
        with self.translator.lock:
            replacement.protected_names = set(self.translator.protected_names)
            replacement.manual_names = set(self.translator.manual_names)
        self.translator = replacement
        self.lbl_first_use.hide()
        QMessageBox.information(self, "保存成功", "设置已保存；密钥存放在 Windows Credential Manager 中。")

    def save_filter_settings(self):
        channels_cfg = {}
        for ch_key, cb in self.ch_checkboxes.items():
            channels_cfg[ch_key] = cb.isChecked()
        self.config["channels"] = channels_cfg

        self.config["skip_chinese"] = self.cb_skip_chinese.isChecked()
        self.config["enable_local_dict"] = self.cb_local_dict.isChecked()
        self.config["ocr_unknown_channel"] = self.cb_ocr_unknown.isChecked()

        custom_names = self.edit_custom_names.text().strip()
        self.config["protected_names"] = custom_names
        self.translator.set_protected_names(custom_names.replace("，", ",").split(","))

        show_orig = self.cb_show_original.isChecked()
        self.overlay.set_show_original(show_orig)
        self.overlay.set_font_size(self.spin_font_size.value())

        if self.config_mgr.save():
            self.invalidate_translations()
            QMessageBox.information(self, "保存成功", "频道与规则过滤设置已保存！")

    def on_font_size_changed(self, val: int):
        self.overlay.set_font_size(val)

    def toggle_overlay_visibility(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()
            self.overlay.raise_()
            self.overlay.activateWindow()

    def center_overlay_window(self):
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.activateWindow()
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        center = screen.availableGeometry().center()
        self.overlay.setGeometry(center.x() - 260, center.y() - 170, 520, 340)
        self.overlay.save_geometry_to_config()
        QMessageBox.information(self, "提示", "已将翻译悬浮窗召回并重置到屏幕中央可见位置！")

    def toggle_overlay_lock(self):
        self.overlay.set_lock_state(not self.overlay.is_locked)

    def on_overlay_lock_changed(self, locked: bool):
        self.update_lock_button_ui(locked)

    def update_lock_button_ui(self, locked: bool):
        if locked:
            self.btn_lock_overlay.setText("🔓 点击解锁悬浮窗 (当前已穿透)")
            self.btn_lock_overlay.setStyleSheet("background-color: #c62828; color: white;")
        else:
            self.btn_lock_overlay.setText("🔒 锁定悬浮窗并穿透")
            self.btn_lock_overlay.setStyleSheet("background-color: #2d3446; color: #e0e0e0;")

    def is_currently_running(self) -> bool:
        return bool(
            (self.ocr_watcher and self.ocr_watcher.isRunning()) or
            (self.log_watcher and self.log_watcher.isRunning())
        )

    def toggle_listening(self):
        if self.is_currently_running():
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        if self._closing or self.is_currently_running():
            return
        self.invalidate_translations()
        self._capture_epoch += 1
        mode = self.config.get("work_mode", "ocr")
        if mode == "ocr":
            try:
                region = self.capture_region()
                if self.overlay_overlaps_capture():
                    raise ValueError("请先将悬浮窗移到捕获区域外，避免识别自身译文")
            except ValueError as error:
                QMessageBox.warning(self, "无法开始捕获", str(error))
                return
            watcher = OcrWatcherThread(region, float(self.config.get("ocr_interval", 1.0)))
            self.ocr_watcher = watcher
        else:
            path = self.edit_log_path.text().strip()
            if not path:
                QMessageBox.warning(self, "缺少日志路径", "请先选择 WoWChatLog.txt")
                return
            watcher = LogWatcherThread(path)
            self.log_watcher = watcher
        session = self._capture_epoch
        watcher.new_message_signal.connect(lambda data: self.on_new_raw_message(data, session))
        watcher.status_signal.connect(lambda message: self.on_watcher_status(message, session))
        watcher.finished.connect(self.on_capture_finished)
        watcher.start()
        self.btn_toggle_listen.setText("⏹ 停止捕获")
        self.lbl_status_indicator.setText("● 正在初始化捕获…")
        self.lbl_status_indicator.setStyleSheet("color: #ff9800;")

    def stop_listening(self):
        self.invalidate_translations()
        self._capture_epoch += 1
        for watcher in (self.ocr_watcher, self.log_watcher):
            if watcher:
                watcher.stop()
                self._retired_watchers.append(watcher)
        self.ocr_watcher = self.log_watcher = None
        self.btn_toggle_listen.setText("▶ 启动捕获")
        self.lbl_status_indicator.setText("● 监听状态：已停止")
        self.lbl_status_indicator.setStyleSheet("color: #888888;")

    def on_watcher_status(self, message, session=None):
        if session is not None and session != self._capture_epoch:
            return
        self.lbl_status_indicator.setText("● " + message)
        self.lbl_status_indicator.setStyleSheet("color: #ff9800;" if "失败" in message or "等待" in message else "color: #4caf50;")

    def on_new_raw_message(self, data, session=None):
        if self._closing or (session is not None and session != self._capture_epoch):
            return
        self.stat_captured += 1
        self.update_stat_card(self.card_captured, str(self.stat_captured))
        channel, content = data.get("channel", "Other"), data.get("content", "")
        if not content.strip():
            return
        if data.get("is_ocr") and self.overlay_overlaps_capture():
            return
        sender = data.get("sender", "")
        if sender:
            self.translator.register_player_name(sender)
        if self.config.get("skip_chinese", True) and self.config.get("target_language", "中文") == "中文" and self.translator.should_skip(content):
            return
        if channel == "Other" and data.get("is_ocr"):
            allowed = self.config.get("ocr_unknown_channel", True)
        else:
            allowed = self.config.get("channels", {}).get(channel, False)
        if not allowed:
            return
        skip_chinese = self.config.get("skip_chinese", True)
        enable_dict = self.config.get("enable_local_dict", True)
        translator = self.translator
        accepted = self.translation_queue.submit(data, lambda message: translator.translate_message(
            message["content"], skip_chinese=skip_chinese, enable_local_dict=enable_dict))
        if accepted is None:
            self._dropped += 1
            self._last_result_status = "队列已满，已丢弃新消息"
            return
        row = self.table_logs.rowCount()
        self.table_logs.insertRow(row)
        values = (data.get("time", ""), data.get("channel_display", ""), sender, content, "等待翻译…")
        for column, value in enumerate(values):
            self.table_logs.setItem(row, column, QTableWidgetItem(value))
        self.table_logs.item(row, 1).setForeground(QColor(CHANNEL_COLORS.get(channel, "#FFFFFF")))
        sequence = accepted["_sequence"]
        self._pending_rows[sequence] = self.table_logs.item(row, 4)
        self._record_ids.append(sequence)
        while self.table_logs.rowCount() > int(self.config.get("max_records", 500)):
            self._pending_rows.pop(self._record_ids.popleft(), None)
            self.table_logs.removeRow(0)
        self.table_logs.scrollToBottom()

    def on_translation_finished(self, data, translation, source, elapsed):
        if data.get("_session") != self.translation_queue.session or self._closing:
            return
        item = self._pending_rows.pop(data["_sequence"], None)
        if item is not None:
            item.setText(("[字典] " if source == "local_dict" else "") + translation)
            item.setForeground(QColor("#ff9800" if source in ("error", "expired") else "#00ccff"))
        if source == "expired":
            self._dropped += 1
            self._last_result_status = "已跳过过时消息"
            return
        if source == "error":
            self._last_result_status = translation
            return
        self._last_result_status = ""
        if source == "local_dict":
            self.stat_dict_hits += 1
            self.update_stat_card(self.card_dict_hits, str(self.stat_dict_hits))
        elif source == "openai":
            self.stat_translated += 1
            self.update_stat_card(self.card_translated, str(self.stat_translated))
        age = time.monotonic() - data["_captured_at"]
        self._latencies.append(age)
        self.update_stat_card(self.card_avg_time, f"{sum(self._latencies) / len(self._latencies) * 1000:.0f} ms")
        if self.overlay.isVisible():
            self.overlay.append_message(data, translation, source)

    def simulate_test_message(self):
        """模拟一条队伍消息以供测试"""
        sample_messages = [
            ("Party", "[小队]", "Tankmaster", "Ready to pull the boss in 5 seconds. Everyone focus add!"),
            ("Party", "[小队]", "Healergod", "oom, need 5 sec to drink mana please."),
            ("Raid", "[团队]", "Raidleader", "Hero on start! Lust lust lust!"),
            ("Whisper", "[密语]", "Guildbuddy", "Can you inv me to your mythic dungeon group?"),
            ("Party", "[小队]", "Rogueguy", "mb, I accidentally pulled the patrol.")
        ]
        import random
        ch_key, ch_disp, sender, msg = random.choice(sample_messages)
        cur_time = time.strftime("%m/%d %H:%M:%S")

        mock_data = {
            "time": cur_time,
            "channel": ch_key,
            "channel_display": ch_disp,
            "sender": sender,
            "content": msg,
            "raw": f"{cur_time}  {ch_disp} [{sender}]: {msg}"
        }
        self.on_new_raw_message(mock_data)

    def create_log_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部工具栏
        h_tools = QHBoxLayout()
        lbl_hint = QLabel("💡 这里显示运行状态；聊天内容、密钥和接口原始错误不会写入诊断日志。", widget)
        lbl_hint.setStyleSheet("color: #00ccff; font-size: 12px;")
        h_tools.addWidget(lbl_hint)
        h_tools.addStretch()

        btn_clear = QPushButton("清空日志", widget)
        btn_clear.clicked.connect(lambda: self.log_console_edit.clear())
        h_tools.addWidget(btn_clear)

        btn_copy = QPushButton("复制全部日志", widget)
        btn_copy.clicked.connect(self.copy_console_log)
        h_tools.addWidget(btn_copy)
        layout.addLayout(h_tools)

        self.log_console_edit = QPlainTextEdit(widget)
        self.log_console_edit.setReadOnly(True)
        self.log_console_edit.document().setMaximumBlockCount(int(self.config.get("console_max_blocks", 1000)))
        self.log_console_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d1117;
                color: #58a6ff;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.log_console_edit)
        return widget

    def copy_console_log(self):
        text = self.log_console_edit.toPlainText()
        if text:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", "已将全部日志复制到剪贴板！")

    def clear_table_records(self):
        self._pending_rows.clear()
        self._record_ids.clear()
        self.table_logs.setRowCount(0)

    def closeEvent(self, event):
        if not self._closing:
            self._closing = True
            self.stop_listening()
            self.delivery_timer.stop()
            self.overlay.close()
            self.translation_queue.close()
            self.thread_pool.shutdown(wait=False, cancel_futures=True)
            self.config_mgr.save()
        # Keep QThreads and signal receivers alive until native OCR/API work exits.
        if any(watcher.isRunning() for watcher in self._retired_watchers) or any(
                not future.done() for future in self._diagnostic_futures) or self.translation_queue.futures:
            event.ignore()
            self.lbl_status_indicator.setText("正在等待后台任务结束…")
            QTimer.singleShot(100, self.close)
            return
        sys.stdout = self.log_redirector.original_stream
        super().closeEvent(event)

    def on_config_error(self, message):
        self._last_result_status = message
        if getattr(self, "_shown_config_error", None) != message:
            self._shown_config_error = message
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "配置未保存", message))

    def invalidate_translations(self):
        self.translation_queue.new_session()
        for item in self._pending_rows.values():
            item.setText("[已取消]")
        self._pending_rows.clear()

    def on_capture_finished(self):
        watcher = self.sender()
        if watcher is self.ocr_watcher or watcher is self.log_watcher:
            self.ocr_watcher = self.log_watcher = None
            self.btn_toggle_listen.setText("▶ 启动捕获")
        if watcher in self._retired_watchers:
            self._retired_watchers.remove(watcher)
        watcher.deleteLater()

    def capture_region(self):
        import mss
        try:
            with mss.MSS() as screen:
                return physical_region(self.config["ocr_region"], QApplication.screens(), screen.monitors[1:])
        except ValueError:
            raise
        except Exception:
            raise ValueError("无法访问显示器，请检查桌面会话或屏幕捕获权限后重试") from None

    def overlay_overlaps_capture(self):
        region = self.config["ocr_region"]
        rectangle = QRect(region["left"], region["top"], region["width"], region["height"])
        return self.overlay.isVisible() and self.overlay.frameGeometry().intersects(rectangle)

    def poll_translations(self):
        self._diagnostic_futures = {future for future in self._diagnostic_futures if not future.done()}
        if self.ocr_watcher:
            overlapping = self.overlay_overlaps_capture()
            self.ocr_watcher.set_paused(overlapping)
            if overlapping:
                self.lbl_status_indicator.setText("● 捕获已暂停：请将悬浮窗移到捕获区域外")
        for result in self.translation_queue.poll():
            self.on_translation_finished(*result)
        label = f"待展示 {self.translation_queue.pending_count} | 已丢弃/过时 {self._dropped}"
        if self._latencies:
            ordered = sorted(self._latencies)
            label += f" | 端到端 P50 {ordered[int((len(ordered)-1)*0.5)]*1000:.0f} ms / P95 {ordered[int((len(ordered)-1)*0.95)]*1000:.0f} ms"
        self.lbl_pipeline_status.setText(label + (" | " + self._last_result_status if self._last_result_status else ""))
