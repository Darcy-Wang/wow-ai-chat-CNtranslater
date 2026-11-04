# wow-ai-chat-CNtranslater

**中文** | [English](README.en.md)

[![Windows checks](https://github.com/Darcy-Wang/wow-ai-chat-CNtranslater/actions/workflows/windows.yml/badge.svg)](https://github.com/Darcy-Wang/wow-ai-chat-CNtranslater/actions/workflows/windows.yml)

魔兽世界聊天 AI 中文翻译助手

Windows 桌面工具：通过屏幕局部 OCR 或 `WoWChatLog.txt` 采集聊天，使用本地术语词典、翻译缓存及 OpenAI / DeepSeek 兼容接口生成译文，再在置顶悬浮窗中显示。

## 项目来源

本项目基于 [usherzhao/wow-chat-translator](https://github.com/usherzhao/wow-chat-translator) 的提交 [`d1bb333`](https://github.com/usherzhao/wow-chat-translator/commit/d1bb3332c33cb85f362106cbdb27def226d495b2) 改进，保留原作者贡献。主要修改包括消息去重和缓存准确性、频道过滤、有界任务队列、密钥保存及 Windows 发布验证。暂未添加许可证。

## 运行环境与安装

- 主要支持目标：Windows 10/11、64 位、Python 3.11。完整依赖版本记录在 `requirements.txt`。
- Windows 10/11 桌面的鼠标穿透、显示器缩放和游戏内效果仍需实机验收。原生凭据读写及 EXE 打包启动已有 Windows CI 检查。其他系统可运行部分逻辑和界面测试，不承诺完整功能。
- 程序不读取或修改游戏内存，不注入 DLL，不模拟键鼠。此技术边界不构成对游戏运营方规则或账号结果的保证。

源码运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

已安装依赖后，可双击 `start.bat` 启动。

## 首次使用

1. 在“屏幕 OCR 设置”中框选聊天区域，保存后关闭框选器。用“测试 OCR”检查实际文字；分辨率预设只是起点。
2. 将翻译悬浮窗移到捕获区域之外。程序会暂停重叠区域的持续捕获，防止把自身译文再次送入翻译。
3. 在“AI 接口配置”中选择服务，填写自己的 API Key、地址及模型。测试连通性后保存。测试会产生一次模型调用。
4. 点击“模拟触发测试聊天”预览译文，再启动持续捕获。
5. 在“频道与过滤”中选择需要的频道。小队、团队、副本、密语、说话、大喊及公会默认开启，公共频道默认关闭。OCR 识别不出频道时，由单独的“未知频道”选项控制。
6. 锁定悬浮窗后可在主面板解锁。请先验证鼠标穿透，再进入需要频繁操作的场景。

OCR 默认检测间隔为 1 秒，可调为 0.5～5 秒。画面没有明显变化时跳过 OCR，但仍有截图和差分计算开销。实际延迟包含采集、OCR、排队、网络和模型响应，不保证固定耗时。界面的端到端指标从截图开始（日志模式为完整行被读取）计算至译文展示，不包含聊天出现至下一次截图的等待，也不包含游戏日志尚未落盘的时间。

## 消息准确性与时效

- OCR 仅在相邻识别帧间对完整文字逐条匹配，支持滚动重叠和重复行；不再跨历史模糊删除相似指令。
- `pull in 5`、`pull in 15`、`pull in 1.5` 分别处理；缓存保留数字、标点、词边界和大小写。
- 日志中同一玩家再次发送相同内容仍作为新消息显示，译文可以从缓存复用。
- 纯中文消息可跳过，中英混合消息保留翻译资格。玩家名可自动登记或手动保护。
- 默认最多保留 23 个待交付翻译任务，包括最多 3 个执行中的请求；满载时丢弃新消息，并显示计数。
- 默认消息时效 12 秒。过时任务不再展示译文，表格显示原因；未开始执行的过时任务不会调用接口。
- 结果按采集顺序展示。停止、切换模式或修改翻译设置会废弃旧翻译结果；已经发送的请求无法撤回，仍可能计费。
- API 请求关闭自动重试。认证失败会暂停远程翻译直到重新保存 API 设置，限流冷却 5 秒，超时冷却 2 秒，本地词典和已有缓存仍可用。这些错误会给出简短状态，不把服务端原始错误或密钥写入诊断日志。
- 悬浮窗默认保留 60 条消息，主表格 500 条，控制台 1000 个文本块；缓存最多 3000 条。

OCR 仍有固有限制：无法可靠区分两次采样之间被替换为完全相同文字、且行数与画面位置没有变化的发言；低置信度、换行、背景变化也可能造成遗漏或重复。暂未实现跨行语义拼接或完整聊天事件重建。游戏窗口移动后需要重新框选；跨显示器的捕获区域会被拒绝，显示器对应关系不明确时提示重新选择，不猜测坐标。

## 配置、密钥和隐私

- Windows 配置路径：`%APPDATA%\WoWChatTranslator\config.json`。API Key 单独存放在当前用户的 Windows Credential Manager，JSON 中的 `api_key` 保持为空，`credential_id` 是凭据引用。正常启动只允许一个实例使用该用户配置。
- 首次迁移时可读取旧程序目录的 `config.json`。保存成功后，密钥进入凭据管理器，旧文件中的明文密钥被清空，其他旧配置保留。
- 若旧文件只读导致清理失败，会提示保存未全部完成；处理权限后重新保存。请自行检查以前分享过的压缩包，必要时更换旧密钥。
- 使用临时文件和原子替换保存。读取失败或配置损坏时阻止覆盖原文件，提示用户修复后重启；不会静默重置损坏配置。
- 诊断日志不输出聊天正文、角色名、密钥片段或原始接口错误。原文和译文仍显示在本机界面；实际发送给接口服务商的内容由该服务商处理。使用第三方代理前确认其可信度。
- 配置文件保留游戏路径和手动设置的玩家名，分享配置前应清理。发布流程只使用空白公开示例，绝不复制本机配置。

高级容量设置可在关闭程序后修改配置中的 `max_pending`、`message_max_age`、`max_records`、`console_max_blocks` 及 `overlay.max_messages`。

## 日志模式与 Lua 插件

日志模式需选择对应客户端的 `Logs/WoWChatLog.txt`。现有历史记录默认跳过，只处理启动监听后追加的完整行；支持文件截断、轮换及拆分写入的 UTF-8 文本。游戏客户端可能延迟写盘，实际行为取决于客户端版本，日志模式不保证即时翻译。

可将 `Addon/WowChatTranslator` 安装到客户端的 `Interface/AddOns/`，再在游戏内重新加载界面。插件用于登录时开启 `/chatlog`，不能强制游戏即时刷新日志缓冲。不同客户端的插件 Interface 版本需要实际确认，未在游戏中验证的版本不宣称兼容。

- `/wct status`：查看日志状态。
- `/wct on`、`/wct off`：控制日志及登录自动开启设置。
- `/wct test`：在本地聊天框打印英文文本，供 OCR 预览使用；它不是发送给其他玩家的真实聊天事件，不保证进入聊天日志。

## 测试与 Windows 发布

```powershell
python -m pip install -r requirements-build.txt
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest -q
python run.py --self-test
Remove-Item Env:QT_QPA_PLATFORM
python scripts/build_release.py
```

也可直接执行 `build.bat`：安装锁定依赖 → 运行回归测试 → 构建 → 检查发布配置。产物位于 `dist/WoWChatTranslator/`，分享整个目录，不要只复制 EXE。每次构建都会用空白示例覆盖旧发布配置。

`--self-test` 只初始化 Qt 和本地 OCR 模型后退出，不读用户配置、不截图、不访问付费接口。GitHub Actions 中的 Windows 工作流执行回归、构建和打包程序启动检查；推送后需确认工作流实际通过，不能把配置了工作流等同于已经通过。

测试覆盖倒计时区分、相邻帧去重、重复呼叫、中英混合、副本频道、缓存隔离、队列容量/时效/顺序、停止重启、日志拆分写入与轮换、配置失败、密钥存储边界、发布配置及界面历史容量。

验证记录：本地 macOS arm64 / Python 3.11.15 为 **63 项通过、1 项 Windows 专属测试跳过**；GitHub 托管的 Windows Server 2025 x64 环境已通过自动回归（含原生凭据读写）、EXE 构建和打包后 Qt/OCR 启动检查，详见[此次运行](https://github.com/Darcy-Wang/wow-ai-chat-CNtranslater/actions/runs/41815776996)。这些自动检查不替代实际游戏环境验收。

Windows 实机验收清单见 `docs/WINDOWS_ACCEPTANCE.md`。

依赖输入在 `requirements.in`、构建输入在 `requirements-build.in`，锁定文件由 `uv pip compile --universal --python-version 3.11` 生成。升级后须重新运行回归、OCR 自检及 Windows 构建检查。
