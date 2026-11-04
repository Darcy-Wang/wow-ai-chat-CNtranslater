-- WoW Chat Translator In-Game Helper Addon
-- 自动管理聊天日志记录，方便外部 AI 翻译工具实时监听

local ADDON_NAME = "WowChatTranslator"
local PREFIX = "|cff00ccff[WCT翻译助手]|r "

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")

local function PrintMsg(msg)
    DEFAULT_CHAT_FRAME:AddMessage(PREFIX .. msg)
end

local function EnsureLogging()
    if not LoggingChat() then
        LoggingChat(true)
        PrintMsg("已自动开启聊天日志记录 (|cffffff00/chatlog|r)。外部 AI 翻译器已可实时捕获。")
    else
        PrintMsg("聊天日志已在记录中。")
    end
end

frame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" and arg1 == ADDON_NAME then
        if WCT_Config == nil then
            WCT_Config = {
                autoLog = true,
                installedNotice = true,
            }
        end
    elseif event == "PLAYER_LOGIN" then
        if WCT_Config and WCT_Config.autoLog then
            -- 延迟 1 秒确保界面完全就绪
            C_Timer.After(1.0, function()
                EnsureLogging()
            end)
        end
    end
end)

-- 注册斜杠指令
SLASH_WOWCHATTRANSLATOR1 = "/wct"
SLASH_WOWCHATTRANSLATOR2 = "/wowtrans"
SlashCmdList["WOWCHATTRANSLATOR"] = function(msg)
    local cmd = string.lower(string.trim(msg or ""))
    if cmd == "on" then
        WCT_Config.autoLog = true
        LoggingChat(true)
        PrintMsg("|cff00ff00已开启|r 聊天日志记录。")
    elseif cmd == "off" then
        WCT_Config.autoLog = false
        LoggingChat(false)
        PrintMsg("|cffff0000已关闭|r 聊天日志记录。")
    elseif cmd == "status" then
        local status = LoggingChat() and "|cff00ff00正在记录|r" or "|cffff0000未开启|r"
        local auto = WCT_Config.autoLog and "是" or "否"
        PrintMsg(string.format("状态: 当前日志 %s，登录自动开启: %s", status, auto))
    elseif cmd == "test" then
        PrintMsg("正在显示本地 OCR 测试文本...")
        -- 打印一条英文模拟消息
        print("[WCT-Test] Ready to pull boss in 5 seconds. Tanks be ready!")
        print("[WCT-Test] Can anyone summon me to the dungeon entrance please?")
        PrintMsg("本地测试文本已输出，仅供 OCR 测试；日志模式请使用真实聊天。")
    else
        PrintMsg("指令帮助:")
        print("  |cffffff00/wct status|r - 查看当前日志记录状态")
        print("  |cffffff00/wct on|r     - 开启聊天日志记录")
        print("  |cffffff00/wct off|r    - 关闭聊天日志记录")
        print("  |cffffff00/wct test|r   - 显示本地文本测试 OCR")
    end
end
