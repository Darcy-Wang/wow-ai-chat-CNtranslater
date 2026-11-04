import os
import sys
import shutil
if sys.platform == "win32":
    import winreg
from typing import List, Dict, Optional

COMMON_PATHS = [
    r"Z:\games\World of Warcraft",
    r"C:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files\World of Warcraft",
    r"D:\World of Warcraft",
    r"D:\Games\World of Warcraft",
    r"E:\World of Warcraft",
    r"E:\Games\World of Warcraft",
    r"F:\World of Warcraft",
    r"F:\Games\World of Warcraft",
]

WOW_FLAVORS = [
    "_classic_beta_",
    "_retail_",
    "_classic_",
    "_classic_era_",
    "_ptr_",
]

class WowDetector:
    @staticmethod
    def get_running_wow_path() -> Optional[str]:
        """通过正在运行的进程快速检测魔兽主目录"""
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'exe']):
                name = (proc.info.get('name') or "").lower()
                if name.startswith("wow") and name.endswith(".exe"):
                    exe_path = proc.info.get('exe')
                    if exe_path and os.path.exists(exe_path):
                        # 返回 exe 所在目录，如 Z:\games\World of Warcraft\_classic_beta_
                        return os.path.dirname(exe_path)
        except Exception:
            pass
        return None

    @staticmethod
    def get_registry_paths() -> List[str]:
        """从注册表探测暴雪安装目录"""
        paths = []
        if sys.platform != "win32":
            return paths
        reg_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Blizzard Entertainment\World of Warcraft"),
        ]
        for root, subkey in reg_keys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "InstallPath")
                    if val and os.path.exists(val):
                        paths.append(val)
            except Exception:
                pass
        return paths

    @classmethod
    def scan_installations(cls) -> List[Dict[str, str]]:
        """
        全面扫描系统中的魔兽世界安装和各个客户端版本 (Retail / Classic / Beta 等)
        返回列表项:
        {
            "name": "Classic Beta (Z:\\...)",
            "flavor_dir": "Z:\\games\\World of Warcraft\\_classic_beta_",
            "log_path": "Z:\\games\\World of Warcraft\\_classic_beta_\\Logs\\WoWChatLog.txt",
            "log_exists": True/False,
            "addon_installed": True/False
        }
        """
        candidates = []
        checked_dirs = set()

        # 1. 优先检查正在运行的进程
        running_flavor = cls.get_running_wow_path()
        if running_flavor:
            # 如果是在 Utils 这种子目录，退回上级
            if os.path.basename(running_flavor).lower() in ["utils", "logs", "interface"]:
                running_flavor = os.path.dirname(running_flavor)
            if running_flavor not in checked_dirs:
                checked_dirs.add(os.path.normpath(running_flavor).lower())
                candidates.append(running_flavor)

        # 2. 检查注册表
        for p in cls.get_registry_paths():
            p_norm = os.path.normpath(p).lower()
            if p_norm not in checked_dirs:
                checked_dirs.add(p_norm)
                candidates.append(p)

        # 3. 检查常用预设路径
        for root in COMMON_PATHS:
            if os.path.exists(root):
                for flavor in WOW_FLAVORS:
                    flavor_dir = os.path.join(root, flavor)
                    f_norm = os.path.normpath(flavor_dir).lower()
                    if os.path.exists(flavor_dir) and f_norm not in checked_dirs:
                        checked_dirs.add(f_norm)
                        candidates.append(flavor_dir)

        results = []
        for flavor_dir in candidates:
            # 判断是否为有效的魔兽客户端目录
            logs_dir = os.path.join(flavor_dir, "Logs")
            chatlog_file = os.path.join(logs_dir, "WoWChatLog.txt")
            addon_target = os.path.join(flavor_dir, "Interface", "AddOns", "WowChatTranslator")
            
            # 命名展示
            flavor_name = os.path.basename(flavor_dir)
            if not flavor_name:
                flavor_name = os.path.basename(os.path.dirname(flavor_dir))
                
            display_name = f"{flavor_name} ({flavor_dir})"
            
            results.append({
                "name": display_name,
                "flavor_dir": flavor_dir,
                "log_path": chatlog_file,
                "log_exists": os.path.exists(chatlog_file),
                "addon_installed": os.path.exists(addon_target)
            })

        return results

    @staticmethod
    def install_addon_to_flavor(flavor_dir: str) -> bool:
        """
        将附带的 WowChatTranslator 插件安装到指定客户端的 Interface/AddOns 目录
        """
        if getattr(sys, 'frozen', False):
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            source_addon_dir = os.path.join(base_dir, "Addon", "WowChatTranslator")
            if not os.path.exists(source_addon_dir):
                source_addon_dir = os.path.join(os.path.dirname(sys.executable), "Addon", "WowChatTranslator")
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            source_addon_dir = os.path.join(base_dir, "Addon", "WowChatTranslator")
        
        if not os.path.exists(source_addon_dir):
            raise FileNotFoundError(f"插件源目录不存在: {source_addon_dir}")

        target_addons_dir = os.path.join(flavor_dir, "Interface", "AddOns")
        os.makedirs(target_addons_dir, exist_ok=True)

        target_addon_dir = os.path.join(target_addons_dir, "WowChatTranslator")
        if os.path.exists(target_addon_dir):
            shutil.rmtree(target_addon_dir)

        shutil.copytree(source_addon_dir, target_addon_dir)
        return True
