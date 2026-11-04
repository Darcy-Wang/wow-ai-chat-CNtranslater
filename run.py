import sys
import os

# 将项目根目录加入模块搜索路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget
from PyQt6.QtCore import Qt, QLockFile
from app.main_window import MainWindow
from app.config import config_file_path

def main():
    # 针对高分屏 DPI 适配
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    if "--self-test" in sys.argv:
        # Test the packaged Qt runtime and bundled OCR models without touching
        # user configuration, starting capture, or calling a paid API.
        from PyQt6.QtCore import QTimer
        from rapidocr_onnxruntime import RapidOCR
        app = QApplication(sys.argv)
        RapidOCR()
        widget = QWidget()
        widget.show()
        QTimer.singleShot(100, app.quit)
        sys.exit(app.exec())

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    path = config_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        QMessageBox.critical(None, "无法启动", "用户配置目录不可写，请检查目录权限。")
        sys.exit(1)
    # Serialize access to configuration and credential migration across processes.
    lock = QLockFile(str(path) + ".lock")
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.warning(None, "程序已运行", "另一个实例正在使用此配置，请使用现有窗口。")
        sys.exit(1)
    app.aboutToQuit.connect(lock.unlock)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
