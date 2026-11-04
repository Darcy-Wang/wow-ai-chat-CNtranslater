# wow-ai-chat-CNtranslater

[中文](README.md) | **English**

An AI-powered Chinese chat translation companion for World of Warcraft. This Windows desktop application captures a selected screen region with local OCR or tails `WoWChatLog.txt`, translates messages through a local glossary, an in-memory cache, and an OpenAI / DeepSeek-compatible API, then displays translations in a transparent, always-on-top overlay.

The application interface and default translations are in Chinese. This document provides English setup and operating instructions.

## Project origin

Based on [usherzhao/wow-chat-translator](https://github.com/usherzhao/wow-chat-translator), starting from commit [`d1bb333`](https://github.com/usherzhao/wow-chat-translator/commit/d1bb3332c33cb85f362106cbdb27def226d495b2). Credit remains with the original contributors. This version improves message deduplication, translation caching, channel filtering, bounded scheduling, credential storage, and Windows release checks. No license has been added.

## Requirements and installation

- Primary target: 64-bit Windows 10/11 and Python 3.11. Runtime versions are pinned in `requirements.txt`.
- Native click-through, Credential Manager, display scaling, and in-game behavior require Windows acceptance testing. Other operating systems can run some logic and UI tests; complete functionality is not promised.
- The application does not read or modify game memory, inject DLLs, or simulate keyboard or mouse input. These implementation boundaries do not guarantee compliance with game operator policies or any particular account outcome.

Run from source in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

After installing dependencies, `start.bat` can also launch the application. It prefers the local Windows `.venv` interpreter when present.

## First-time setup

1. Open **屏幕 OCR 设置** (Screen OCR settings), select the chat area, save it, and close the selector. Use **测试 OCR** (Test OCR) to inspect recognized text. Resolution presets are starting points and may need adjustment.
2. Move the translation overlay outside the capture region. Continuous capture pauses while they overlap to prevent translating the application's own output.
3. Open **AI 接口配置** (AI API settings), select a provider, and enter your API key, endpoint, and model. Test the connection and save. The connection test makes one model request and may incur a charge.
4. Click **模拟触发测试聊天** (Simulate a test message) to preview translation delivery, then start capture.
5. Configure channels under **频道与过滤** (Channels and filters). Party, raid, instance, whisper, say, yell, and guild are enabled by default; public channels are disabled. A separate option controls OCR text with an unrecognized channel.
6. Lock the overlay to enable click-through; unlock it from the main panel. Verify click-through before relying on it during gameplay.

The default OCR polling interval is one second, adjustable between 0.5 and 5 seconds. Frames without significant changes skip OCR but still require capture and image comparison. Actual latency includes capture, OCR, queueing, network, and model response time; there is no fixed latency guarantee. Displayed end-to-end metrics start when a screenshot is taken, or when a complete log line is read, and end when a translation is displayed. They exclude waiting for the next polling cycle and waiting for the game to flush its log.

## Message accuracy and freshness

- OCR matches exact lines one-to-one between adjacent recognized frames, including scrolling overlap and duplicate visible lines. It does not suppress similar text across the session history.
- `pull in 5`, `pull in 15`, and `pull in 1.5` remain distinct. Cache keys preserve numbers, punctuation, word boundaries, and letter case.
- Repeated log messages from the same player remain new display events, even when their translation can be reused from cache.
- Chinese-only messages can be skipped; mixed Chinese and English messages remain eligible for translation. Player names can be registered automatically or protected manually.
- The default queue capacity is 23 outstanding deliveries, including at most three running requests. New messages are dropped when capacity is reached; the UI reports the count.
- The default message lifetime is 12 seconds. Expired translations are not displayed in the overlay; the table records the reason. A job already stale before execution does not call the API.
- Results are delivered in capture order. Stopping, switching capture modes, or changing translation settings invalidates old translation results. Requests already sent cannot be recalled and may still be billed.
- API automatic retries are disabled. Authentication failures pause remote translation until API settings are saved again. Rate limits trigger a five-second cooldown, and timeouts a two-second cooldown. The local glossary and existing cache remain available. Diagnostic messages omit raw provider errors and credentials.
- Default history limits: 60 overlay messages, 500 table rows, 1,000 console text blocks, and 3,000 cache entries.

OCR cannot reliably distinguish a new occurrence that replaces an identical message between samples while the visible line count and positions remain unchanged. Low confidence, wrapped lines, and changing backgrounds may still cause missed or repeated text. Cross-line semantic reconstruction is not implemented. Select the region again after moving the game window. Regions spanning displays are rejected; ambiguous display mappings produce an error rather than guessed coordinates.

## Configuration, credentials, and privacy

- Windows configuration: `%APPDATA%\WoWChatTranslator\config.json`. API keys are stored separately in the current user's Windows Credential Manager. The JSON `api_key` remains empty; `credential_id` references the stored credential. Normal startup permits one application instance per user configuration.
- Legacy `config.json` next to the application can be imported. After successful saving, credentials move to Credential Manager, the legacy plaintext key is cleared, and other legacy settings are retained.
- A read-only legacy file can prevent key cleanup. The application reports incomplete saving; fix permissions and save again. Previously distributed archives should be reviewed separately, and exposed keys rotated if needed.
- Configuration uses temporary files and atomic replacement. Read errors or invalid configuration block overwriting the original file; repair it and restart.
- Diagnostics do not log chat content, player names, key fragments, or raw provider errors. Original text and translations remain visible in the local UI. Text sent for remote translation is processed by the selected provider; assess third-party proxies before using them.
- Configuration can contain local game paths and manually protected player names. Remove those before sharing configuration. Release builds use only the blank public example, never the developer's local configuration.

Advanced limits can be adjusted while the application is closed: `max_pending`, `message_max_age`, `max_records`, `console_max_blocks`, and `overlay.max_messages`.

## Log mode and the Lua helper

Select the active client's `Logs/WoWChatLog.txt`. Existing history is skipped when monitoring starts; only complete newly appended lines are processed. The tailer handles truncation, file rotation, and split UTF-8 writes. Log flushing depends on the game client, so log mode does not guarantee immediate translation.

Install `Addon/WowChatTranslator` under the client's `Interface/AddOns/` directory and reload the game interface. The helper enables `/chatlog` on login; it cannot force immediate log flushing. Check the addon Interface version against your specific client. Untested game versions are not claimed to be compatible.

- `/wct status`: show logging status.
- `/wct on` and `/wct off`: control logging and automatic enabling on login.
- `/wct test`: print local English text for OCR preview. It does not send a message to other players and is not guaranteed to appear in the chat log.

## Tests and Windows builds

```powershell
python -m pip install -r requirements-build.txt
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest -q
python run.py --self-test
Remove-Item Env:QT_QPA_PLATFORM
python scripts/build_release.py
```

Alternatively, run `build.bat`: install pinned dependencies, run regression tests, build, and check release configuration. The output is `dist/WoWChatTranslator/`. Distribute the entire directory, not only the executable. Each build overwrites old release configuration with the blank public example.

`--self-test` initializes Qt and local OCR models, then exits. It does not read user configuration, capture the screen, or call paid APIs. The Windows GitHub Actions workflow runs regression tests, builds the application, and tests the packaged executable's startup. Check the actual workflow result; having a workflow file does not mean the build passed.

Local verification before publication: **62 tests passed, one Windows-only native credential integration test skipped**, on macOS arm64 with Python 3.11.15. Qt/OCR startup and synthetic-image OCR inference passed. Windows native credentials, real-game interaction, executable packaging, and prolonged operation still require validation. See [the Windows acceptance checklist (Chinese)](docs/WINDOWS_ACCEPTANCE.md).

Dependency inputs are `requirements.in` and `requirements-build.in`; lock files are generated with `uv pip compile --universal --python-version 3.11`. Re-run regression tests, OCR startup checks, and Windows build checks after updates.
