import sys
import json
import os
import copy
import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    # OpenAI 接口配置
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    
    # 魔兽与日志设置
    "wow_log_path": "",
    
    # 翻译策略
    "target_language": "中文",
    "skip_chinese": True,
    "enable_local_dict": True,
    
    # 频道过滤 (True = 开启翻译, False = 忽略)
    "channels": {
        "Party": True,      # 小队
        "Raid": True,
        "Instance": True,       # 团队
        "Whisper": True,    # 密语/私聊
        "Yell": True,       # 大喊
        "Say": True,        # 普通说话
        "Guild": True,      # 公会
        "General": False,   # 综合频道 (默认关闭以省 token)
        "Trade": False,     # 交易频道
        "World": False,     # 世界频道
        "Other": False      # 其他
    },
    
    # 工作模式: 'ocr' (屏幕实时识别·推荐) 或 'log' (日志文件监听)
    "ocr_unknown_channel": True,
    "max_pending": 23,
    "message_max_age": 12.0,
    "max_records": 500,
    "console_max_blocks": 1000,
    "work_mode": "ocr",
    "ocr_interval": 1.0,
    "ocr_region": {
        "left": 30,
        "top": 1050,
        "width": 580,
        "height": 330
    },

    # 悬浮窗外观设置
    "overlay": {
        "visible": True,
        "x": 200,
        "y": 200,
        "width": 520,
        "height": 340,
        "opacity": 0.85,
        "font_size": 13,
        "click_through": False,   # 鼠标穿透
        "show_original": True,    # 是否同时显示英文原文
        "max_messages": 60        # 历史记录最大保留条数
    }
}

def validate_config(config):
    for key in ("api_key", "base_url", "model", "wow_log_path", "target_language", "protected_names"):
        if key in config and not isinstance(config[key], str):
            raise ValueError("配置字段类型错误: " + key)
    for key in ("skip_chinese", "enable_local_dict", "ocr_unknown_channel"):
        if not isinstance(config[key], bool):
            raise ValueError("配置字段类型错误: " + key)
    for key, low, high in (("max_pending", 1, 200), ("message_max_age", 1, 120),
                           ("max_records", 1, 5000), ("console_max_blocks", 100, 10000),
                           ("ocr_interval", 0.5, 5.0)):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError("配置字段范围错误: " + key)
        if key in ("max_pending", "max_records", "console_max_blocks") and not isinstance(value, int):
            raise ValueError("配置字段必须是整数: " + key)
    if config["work_mode"] not in ("ocr", "log"):
        raise ValueError("无效工作模式")
    if not all(isinstance(value, bool) for value in config["channels"].values()):
        raise ValueError("频道开关必须为布尔值")
    for key in ("left", "top", "width", "height"):
        if type(config["ocr_region"][key]) is not int:
            raise ValueError("捕获坐标必须是整数")
    if not all(1 <= config["ocr_region"][key] <= 32768 for key in ("width", "height")):
        raise ValueError("捕获区域尺寸无效")
    overlay = config["overlay"]
    for key, low, high in (("max_messages", 1, 500), ("font_size", 10, 28),
                           ("width", 100, 32768), ("height", 100, 32768),
                           ("x", -100000, 100000), ("y", -100000, 100000)):
        if type(overlay[key]) is not int or not low <= overlay[key] <= high:
            raise ValueError("悬浮窗字段无效: " + key)
    if not isinstance(overlay["opacity"], (int, float)) or not 0.2 <= overlay["opacity"] <= 1:
        raise ValueError("悬浮窗透明度无效")
    for key in ("visible", "click_through", "show_original"):
        if not isinstance(overlay[key], bool):
            raise ValueError("悬浮窗开关类型错误")


class WindowsCredentialStore:
    def get(self, target):
        if sys.platform != "win32":
            return ""
        import win32cred
        try:
            credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC)
        except Exception as error:
            if getattr(error, "winerror", None) == 1168:
                return ""
            raise
        blob = credential["CredentialBlob"]
        return blob.decode("utf-16-le") if isinstance(blob, bytes) else blob

    def set(self, target, secret):
        if sys.platform != "win32":
            if secret:
                raise OSError("密钥持久化仅支持 Windows Credential Manager；当前平台可测试逻辑和界面")
            return
        import win32cred
        if not secret:
            try:
                win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC)
            except Exception as error:
                if getattr(error, "winerror", None) != 1168:
                    raise
            return
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": "api-key",
            "CredentialBlob": secret.encode("utf-16-le"),
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def config_file_path():
    root = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    return root / "WoWChatTranslator" / "config.json"


class ConfigManager:
    def __init__(self, config_path=None, credential_store=None):
        self.on_error = None
        self.last_error = ""
        self.load_error = False
        self.legacy_path = None
        if config_path is None:
            config_path = config_file_path()
            application_dir = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                               else Path(__file__).resolve().parent.parent)
            legacy = application_dir / "config.json"
            if legacy.exists() and legacy.resolve() != Path(config_path).resolve():
                self.legacy_path = legacy
        self.config_path = str(config_path)
        digest = hashlib.sha256(str(Path(config_path).resolve()).encode()).hexdigest()[:16]
        self.credential_target = "WoWChatTranslator/" + digest
        self.credential_prefix = self.credential_target
        self._stored_secret = ""
        self.credential_store = credential_store or WindowsCredentialStore()
        self.config = self.load()

    def _error(self, message):
        self.last_error = message
        if self.on_error:
            self.on_error(message)
        return False

    def load(self):
        merged = copy.deepcopy(DEFAULT_CONFIG)
        path = Path(self.config_path)
        if not path.exists() and self.legacy_path:
            path = self.legacy_path
        try:
            if path.exists():
                with path.open(encoding="utf-8") as stream:
                    data = json.load(stream)
                if not isinstance(data, dict):
                    raise ValueError("配置必须是 JSON 对象")
                for key, value in data.items():
                    if key in merged and isinstance(merged[key], dict):
                        if not isinstance(value, dict):
                            raise ValueError("配置字段类型错误: " + key)
                        merged[key].update(value)
                    else:
                        merged[key] = value
            validate_config(merged)
            identifier = merged.get("credential_id", "")
            if identifier:
                prefix = self.credential_prefix + "/"
                if (not isinstance(identifier, str) or not identifier.startswith(prefix)
                        or len(identifier[len(prefix):]) != 32
                        or any(char not in "0123456789abcdef" for char in identifier[len(prefix):])):
                    raise ValueError("凭据引用无效")
                self.credential_target = identifier
            stored_key = self.credential_store.get(self.credential_target) if identifier else ""
            self._stored_secret = stored_key
            merged["api_key"] = stored_key or merged.get("api_key", "")
        except Exception as error:
            self.load_error = True
            self._error("配置或凭据读取失败，已阻止覆盖原文件: " + type(error).__name__)
            return copy.deepcopy(DEFAULT_CONFIG)
        return merged

    def save(self, config=None):
        if config is not None:
            self.config = config
        if self.load_error:
            return self._error("请先修复配置或凭据读取问题并重启，原配置未被覆盖")
        staged_target = None
        committed = False
        try:
            validate_config(self.config)
            secret = self.config.get("api_key", "")
            old_target = self.credential_target
            target = self.config.get("credential_id", "") if secret else ""
            if secret and (secret != self._stored_secret or not target):
                # The JSON atomically points to a new credential only after it is
                # stored. A failed file write never pairs an old endpoint with a
                # newly entered key, or destroys the previously usable credential.
                target = self.credential_prefix + "/" + uuid.uuid4().hex
                staged_target = target
                self.credential_store.set(target, secret)
            public_config = copy.deepcopy(self.config)
            public_config["api_key"] = ""
            public_config["credential_id"] = target
            atomic_json(self.config_path, public_config)
            committed = True
            self.config["credential_id"] = target
            self.credential_target = target or self.credential_prefix
            self._stored_secret = secret
            if old_target != self.credential_target and old_target != self.credential_prefix:
                self.credential_store.set(old_target, "")
            if self.legacy_path and self.legacy_path.resolve() != Path(self.config_path).resolve():
                with self.legacy_path.open(encoding="utf-8") as stream:
                    legacy = json.load(stream)
                if legacy.get("api_key"):
                    legacy["api_key"] = ""
                    atomic_json(self.legacy_path, legacy)
                self.legacy_path = None
            self.last_error = ""
            return True
        except Exception as error:
            if staged_target and not committed:
                try:
                    self.credential_store.set(staged_target, "")
                except Exception:
                    pass
            return self._error("配置保存失败，设置尚未全部持久化: " + type(error).__name__)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        return self.save()
