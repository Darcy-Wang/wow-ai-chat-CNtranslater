import os
import re
import time
import sys
from threading import Event
from typing import Optional, Dict, Any
from PyQt6.QtCore import QThread, pyqtSignal


def open_log(path):
    if sys.platform != "win32":
        return open(path, "rb")
    import msvcrt
    import win32file
    import win32con
    handle = win32file.CreateFile(
        path, win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
    raw_handle = handle.Detach()
    try:
        descriptor = msvcrt.open_osfhandle(raw_handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        win32file.CloseHandle(raw_handle)
        raise
    return os.fdopen(descriptor, "rb")

# 频道映射字典，归一化英文与中文客户端的频道名
CHANNEL_MAPPING = {
    # 小队
    "party": "Party",
    "小队": "Party",
    # 团队
    "raid": "Raid",
    "团队": "Raid",
    "raid warning": "Raid",
    "团队警告": "Raid",
    # 副本队伍 / 副本团
    "instance chat": "Instance",
    "instance": "Instance",
    "副本向导": "Instance",
    "副本": "Instance",
    # 密语 / 私聊
    "whisper": "Whisper",
    "密语": "Whisper",
    "悄悄话": "Whisper",
    # 公会 / 官员
    "guild": "Guild",
    "公会": "Guild",
    "officer": "Guild",
    "官员": "Guild",
    # 普通说话
    "say": "Say",
    "说": "Say",
    # 大喊
    "yell": "Yell",
    "喊": "Yell",
    # 公共频道
    "general": "General",
    "综合": "General",
    "trade": "Trade",
    "交易": "Trade",
    "world": "World",
    "世界": "World",
    "lookingforgroup": "World",
    "寻求组队": "World",
}

class LogWatcherThread(QThread):
    # 触发新消息信号
    new_message_signal = pyqtSignal(dict)
    # 触发状态变化信号 (例如: 文件已找到并开始监听、文件不存在等)
    status_signal = pyqtSignal(str)

    def __init__(self, log_path: str):
        super().__init__()
        self.log_path = log_path
        self._stop = Event()
        self._generation = 0

    def stop(self):
        self._stop.set()

    def set_log_path(self, log_path: str):
        self.log_path = log_path
        self._generation += 1

    @staticmethod
    def parse_line(line: str) -> Optional[Dict[str, Any]]:
        """
        解析一行 WoW 聊天日志
        标准格式示例:
        10/11 01:15:30.123  [Party] [Player]: message
        10/11 01:15:30.123  [1. General - Stormwind City] [Player]: message
        10/11 01:15:30.123  Player whispers: message
        10/11 01:15:30.123  To Player: message
        10/11 01:15:30.123  玩家名 悄悄地对你说: 消息
        """
        line = line.strip()
        if not line:
            return None

        # 匹配时间戳: "M/D HH:MM:SS[.MS]  "
        time_match = re.match(r"^(\d{1,2}/\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d{3})?)\s+(.*)$", line)
        if time_match:
            time_str = time_match.group(1)
            body = time_match.group(2)
        else:
            time_str = time.strftime("%m/%d %H:%M:%S")
            body = line

        channel_cat = "Other"
        channel_display = "Chat"
        sender = ""
        content = ""

        # 模式 1: 带中括号频道的格式: [Channel] [Sender]: Content 或 [Channel][Sender]: Content
        m_bracket = re.match(r"^\[(?P<ch>[^\]]+)\]\s*(?:\[(?P<sender>[^\]]+)\]:?|(?P<sender_alt>[^:]+):)\s*(?P<msg>.*)$", body)
        if m_bracket:
            ch_raw = m_bracket.group("ch").strip()
            sender = (m_bracket.group("sender") or m_bracket.group("sender_alt") or "").strip()
            content = m_bracket.group("msg").strip()
            channel_display = f"[{ch_raw}]"

            # 归一化频道类型
            ch_lower = ch_raw.lower()
            matched = False
            for k, v in CHANNEL_MAPPING.items():
                if k in ch_lower:
                    channel_cat = v
                    matched = True
                    break
            if not matched:
                if re.match(r"^\d+\.", ch_raw):
                    if "trade" in ch_lower or "交易" in ch_lower:
                        channel_cat = "Trade"
                    elif "general" in ch_lower or "综合" in ch_lower:
                        channel_cat = "General"
                    else:
                        channel_cat = "World"
                else:
                    channel_cat = "Other"

            return {
                "time": time_str,
                "channel": channel_cat,
                "channel_display": channel_display,
                "sender": sender,
                "content": content,
                "raw": line
            }

        # 模式 2: 英文私聊 Player whispers: message
        m_whisper_in = re.match(r"^(?P<sender>[\w\u4e00-\u9fa5\-]+)\s+whispers:\s*(?P<msg>.*)$", body, re.IGNORECASE)
        if m_whisper_in:
            return {
                "time": time_str,
                "channel": "Whisper",
                "channel_display": "[密语]",
                "sender": m_whisper_in.group("sender"),
                "content": m_whisper_in.group("msg").strip(),
                "raw": line
            }

        # 模式 3: 英文发送私聊 To Player: message
        m_whisper_out = re.match(r"^To\s+(?P<recipient>[\w\u4e00-\u9fa5\-]+):\s*(?P<msg>.*)$", body, re.IGNORECASE)
        if m_whisper_out:
            return {
                "time": time_str,
                "channel": "Whisper",
                "channel_display": "[发送密语]",
                "sender": f"-> {m_whisper_out.group('recipient')}",
                "content": m_whisper_out.group("msg").strip(),
                "raw": line
            }

        # 模式 4: 中文客户端私聊: 玩家 悄悄地对你说: 消息
        m_cn_whisper_in = re.match(r"^(?P<sender>[\w\u4e00-\u9fa5\-]+)\s+悄悄地对你说:\s*(?P<msg>.*)$", body)
        if m_cn_whisper_in:
            return {
                "time": time_str,
                "channel": "Whisper",
                "channel_display": "[密语]",
                "sender": m_cn_whisper_in.group("sender"),
                "content": m_cn_whisper_in.group("msg").strip(),
                "raw": line
            }

        # 模式 5: 普通说话/大喊: Player says: msg 或 Player yells: msg
        m_say = re.match(r"^(?P<sender>[\w\u4e00-\u9fa5\-]+)\s+(?P<act>says|yells|说|喊道):\s*(?P<msg>.*)$", body, re.IGNORECASE)
        if m_say:
            act = m_say.group("act").lower()
            ch = "Yell" if ("yell" in act or "喊" in act) else "Say"
            disp = "[大喊]" if ch == "Yell" else "[说话]"
            return {
                "time": time_str,
                "channel": ch,
                "channel_display": disp,
                "sender": m_say.group("sender"),
                "content": m_say.group("msg").strip(),
                "raw": line
            }

        # 模式 6: 单个玩家名前缀 [Sender]: msg 或 Sender: msg
        m_single = re.match(r"^(?:\[(?P<s1>[\w\u4e00-\u9fa5\-]+)\]|(?P<s2>[\w\u4e00-\u9fa5\-]+)):\s*(?P<msg>.*)$", body)
        if m_single:
            sender = m_single.group("s1") or m_single.group("s2")
            return {
                "time": time_str,
                "channel": "Say",
                "channel_display": "[聊天]",
                "sender": sender,
                "content": m_single.group("msg").strip(),
                "raw": line
            }

        # 兜底：其他未识别结构
        return {
            "time": time_str,
            "channel": "Other",
            "channel_display": "[其他]",
            "sender": "",
            "content": body,
            "raw": line
        }

    def run(self):
        file_obj = None
        identity = None
        current_path = None
        generation = -1
        pending = b""
        try:
            while not self._stop.is_set():
                path = self.log_path
                try:
                    stat = os.stat(path)
                    new_identity = (stat.st_dev, stat.st_ino)
                    switched = path != current_path or generation != self._generation
                    if file_obj is None or switched or identity != new_identity:
                        if file_obj:
                            file_obj.close()
                        file_obj = open_log(path)
                        # Initial selection tails the file. Rotation starts at zero.
                        if identity is None or switched:
                            file_obj.seek(0, os.SEEK_END)
                        current_path, generation, identity = path, self._generation, new_identity
                        pending = b""
                        self.status_signal.emit("正在监听聊天日志")
                    if stat.st_size < file_obj.tell():
                        file_obj.seek(0)
                        pending = b""
                    chunk = file_obj.read()
                    if chunk:
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            parsed = self.parse_line(line.decode("utf-8", errors="replace"))
                            if parsed and parsed.get("content"):
                                parsed["_captured_at"] = time.monotonic()
                                self.new_message_signal.emit(parsed)
                    self._stop.wait(0.15)
                except Exception:
                    if file_obj:
                        file_obj.close()
                        file_obj = None
                    self.status_signal.emit("等待日志文件，请检查路径并在游戏中开启 /chatlog")
                    self._stop.wait(1.0)
        finally:
            if file_obj:
                file_obj.close()
