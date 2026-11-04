"""Build a Windows release; never copy developer configuration."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.config import atomic_json


def prepare_release(destination, example=None):
    example = Path(example) if example else ROOT / "config.example.json"
    with example.open(encoding="utf-8") as stream:
        configuration = json.load(stream)
    if configuration.get("api_key") or configuration.get("wow_log_path") or configuration.get("protected_names"):
        raise ValueError("发布示例包含密钥、游戏路径或玩家名，请清空后再发布")
    # Always overwrite stale release configuration, even after a previous build.
    atomic_json(Path(destination) / "config.json", configuration)
    verify_release(destination)


def verify_release(destination):
    for path in Path(destination).rglob("config*.json"):
        with path.open(encoding="utf-8") as stream:
            configuration = json.load(stream)
        if isinstance(configuration, dict) and configuration.get("api_key"):
            raise ValueError("发布包包含非空 API Key：" + str(path.name))


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows 发布包必须在 Windows 上构建。")
    # Validate before PyInstaller collects the example resource.
    with (ROOT / "config.example.json").open(encoding="utf-8") as stream:
        if json.load(stream).get("api_key"):
            raise SystemExit("发布示例的 API Key 必须为空。")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "wow_chat_translator.spec"], cwd=ROOT, check=True)
    prepare_release(ROOT / "dist" / "WoWChatTranslator")
    print("已完成构建和发布配置检查：dist/WoWChatTranslator")


if __name__ == "__main__":
    main()
