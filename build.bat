@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title WoW Chat Translator 打包工具
set "WCT_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "WCT_PYTHON=%~dp0.venv\Scripts\python.exe"

echo 正在安装锁定的构建与运行依赖...
"%WCT_PYTHON%" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed

echo 正在运行回归检查...
set QT_QPA_PLATFORM=offscreen
"%WCT_PYTHON%" -m pytest -q
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=

echo 正在构建 Windows 发布包并检查空白配置...
"%WCT_PYTHON%" scripts\build_release.py
if errorlevel 1 goto failed

echo 发布目录：dist\WoWChatTranslator
echo 配置已重置为公开示例，可压缩整个目录分享。
pause
exit /b 0

:failed
echo 构建失败；请检查上方错误。未通过检查的目录不要发布。
pause
exit /b 1
