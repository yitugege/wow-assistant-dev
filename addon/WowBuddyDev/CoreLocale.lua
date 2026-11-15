-- ==========================================================================
-- 文件：CoreLocale.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 2126-2310 行），语句与顺序未改。
-- 作用：技能名本地化、默认宏、客户端语言判断与错误日志。
-- 加载：TOC 中紧跟 CoreCastState.lua；getSpellInfo 经 WowBuddyDev.Require("Core") 取自 Core.lua。
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreLocale", { "CoreState", "CoreClassData", "Bindings", "Locale" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local getSpellInfo = WowBuddyDev.Require("Core").getSpellInfo -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
WowBuddyDev.LANG = nil
WowBuddyDev._spellNameToID = WowBuddyDev._spellNameToID or {}
local CHINESE_SPELL_NAME_TO_ID = {
  ["狂风怒号"] = 454015,
  ["能量灌注"] = 10060,
  ["氤氲之雾"] = 124682,
  ["复苏之雾"] = 119611,
  ["活血术"] = 116670,
  ["清创生血"] = 115450,
  ["还魂术"] = 115310,
  ["治疗链"] = 1064,
  ["治疗波"] = 331,
  ["激流"] = 61295,
  ["召唤宠物 1"] = 883,
  ["复活宠物"] = 982,
  ["治疗宠物"] = 136,
}
for k7, spellID in pairs(CHINESE_SPELL_NAME_TO_ID) do
  if not WowBuddyDev._spellNameToID[k7] then
    WowBuddyDev._spellNameToID[k7] = spellID
  end
end
-- 功能：把插件内部用的中文技能名翻成当前客户端语言的技能名。
-- 入参：chineseName 中文技能名。
-- 出参：本地化技能名；查不到就原样返回入参。
-- 说明：中文客户端直接用原文，不走查表。查表链路是「中文名 → 技能 ID → 客户端语言名」，中间任何一步查不到都退回原文——退回原文比返回空串安全，至少界面上还有东西可显示。
function WowBuddyDev.L(chineseName)
  if WowBuddyDev.IsChineseClient() then
    return chineseName
  end
  local englishName = WowBuddyDev._localeEN[chineseName]
  if englishName then
    return englishName
  end
  local spellID = WowBuddyDev._spellNameToID and WowBuddyDev._spellNameToID[chineseName]
  local englishName = spellID and getSpellInfo(spellID)
  return englishName or chineseName
end
-- 功能：把动作键名翻成给人看的标签。
-- 入参：actionKey 动作键名；fallbackLabel 兜底标签。
-- 出参：显示用标签。
-- 说明：中文客户端直接用兜底标签。饰品冷却键要用饰品物品名（更直观），其余动作试着从键名里抠出技能 ID 再取技能名，最后才查固定标签表，全都不中才退回兜底标签。
function WowBuddyDev.LocalizeActionLabel(actionKey, fallbackLabel)
  if WowBuddyDev.IsChineseClient() then
    return fallbackLabel
  end
  if actionKey == "trinketCD" and WowBuddyDev.trinketItemID then
    local trinketItemName = C_Item and (C_Item.GetItemInfo and C_Item.GetItemInfo(WowBuddyDev.trinketItemID))
    if trinketItemName then
      return trinketItemName
    end
  end
  if tostring(actionKey):match("_nearest$") or tostring(actionKey):match("_six_line$") or actionKey == "spell_5143_chain" or actionKey == "spell_44425_stopcasting" or actionKey == "spell_475" or actionKey == "spell_51886" then
    return WowBuddyDev.L(fallbackLabel)
  end
  local spellID = tonumber(tostring(actionKey):match("spell_(%d+)") or tostring(actionKey):match("cd_(%d+)") or tostring(actionKey):match("seq_(%d+)"))
  local spellName = spellID and getSpellInfo(spellID)
  if spellName then
    return spellName
  end
  local FOCUS_LABELS_EN = {
    focus_player = "Focus: Self",
    focus_party1 = "Focus: Party 1",
    focus_party2 = "Focus: Party 2",
    focus_party3 = "Focus: Party 3",
    focus_party4 = "Focus: Party 4",
    focus_mouseover = "Focus: Mouseover",
    focus_interrupt = "Focus Interrupt",
    focus_eruption = "Focus Eruption",
  }
  return FOCUS_LABELS_EN[actionKey] or WowBuddyDev.L(fallbackLabel)
end
-- 功能：取客户端语言代码。
-- 入参：无。
-- 出参：语言代码字符串；接口不可用时给英文。
function WowBuddyDev.GetClientLocale()
  return GetLocale and GetLocale() or "enUS"
end
-- 功能：判断当前是不是中文客户端。
-- 入参：无。
-- 出参：true/false。
-- 说明：允许外部先写死语言标记来强制指定，标记没设时才按客户端语言判断。简体和繁体都算中文。
function WowBuddyDev.IsChineseClient()
  if WowBuddyDev.LANG == "zh" then
    return true
  end
  if WowBuddyDev.LANG == "en" then
    return false
  end
  local locale = WowBuddyDev.GetClientLocale()
  return locale == "zhCN" or locale == "zhTW"
end
-- 功能：把宏体里的中文技能名替换成当前客户端语言的技能名。
-- 入参：macroBody 宏体文本。
-- 出参：替换后的宏体。
-- 说明：逐行解析宏命令，只处理施法和取消光环两种命令，并且保留原有的中括号条件段——条件里的技能名同样要翻译，否则条件会失配。认不出的行原样保留。
function WowBuddyDev.LocalizeMacroBody(macroBody)
  if not macroBody or macroBody == "" then
    return macroBody
  end
  if WowBuddyDev.IsChineseClient() then
    return macroBody
  end
  local macroLines = { strsplit("\n", macroBody) }
  for index13, macroLine in ipairs(macroLines) do
    local command, condition, argument = macroLine:match("^(/%a+)%s*(%b[])%s*(.+)$")
    if not command then
      command, argument = macroLine:match("^(/%a+)%s+(.+)$")
      condition = nil
    end
    if command and argument then
      command = command:lower()
      if command == "/cast" or command == "/cancelaura" then
        argument = argument:gsub("^%s+", ""):gsub("%s+$", "")
        local spellID = WowBuddyDev._spellNameToID[argument]
        if spellID then
          local englishName = getSpellInfo(spellID)
          if englishName then
            if condition then
              macroLines[index13] = command .. " " .. condition .. " " .. englishName
            else
              macroLines[index13] = command .. " " .. englishName
            end
          end
        end
      end
    end
  end
  return table.concat(macroLines, "\n")
end
-- 功能：取某个动作的默认宏体。
-- 入参：actionKey 动作键名。
-- 出参：宏体字符串；取不到给空串。
-- 说明：职业模块登记过默认宏就用它，否则从动作键里抠出技能 ID 拼一条简单施法宏。返回空串而不是 nil，是因为调用方会直接拿它去比字符串。
function WowBuddyDev.GetDefaultMacro(actionKey)
  local macroBody
  if WowBuddyDev.GetClassDefaultMacro and WowBuddyDev.classData then
    local key = (WowBuddyDev.classData.ACTION_TO_KEY or {})[actionKey]
    macroBody = key and WowBuddyDev.GetClassDefaultMacro(key)
    if macroBody then
      return WowBuddyDev.LocalizeMacroBody(macroBody)
    end
  end
  if WowBuddyDev.classData and (WowBuddyDev.classData.DEFAULT_MACROS and WowBuddyDev.classData.DEFAULT_MACROS[actionKey]) then
    macroBody = WowBuddyDev.classData.DEFAULT_MACROS[actionKey]
  else
    local spellID = tonumber(actionKey:match("spell_(%d+)") or actionKey:match("cd_(%d+)"))
    if not spellID then
      return ""
    end
    local englishName = getSpellInfo(spellID)
    return englishName and "/cast " .. englishName or ""
  end
  return WowBuddyDev.LocalizeMacroBody(macroBody)
end
WowBuddyDev.errorLogs = {}
-- 功能：往插件错误日志里追加一条，并刷新日志界面。
-- 入参：logType 类型；message 内容。
-- 出参：无。
-- 说明：新记录插到最前面，最多保留一批，超出就丢最老的，避免长时间运行把内存吃满。
function WowBuddyDev.AddErrorLog(logType, message)
  local timeText = date("%H:%M:%S")
  table.insert(WowBuddyDev.errorLogs, 1, { time = timeText, type = logType, message = message })
  while #WowBuddyDev.errorLogs > 50 do
    table.remove(WowBuddyDev.errorLogs)
  end
  if WowBuddyDev.RefreshErrorLog then
    WowBuddyDev.RefreshErrorLog()
  end
end
-- 功能：取错误日志列表。
-- 入参：无。
-- 出参：日志表（内部表本身，调用方不要改）。
function WowBuddyDev.GetErrorLogs()
  return WowBuddyDev.errorLogs
end
-- 功能：清空错误日志并刷新界面。
-- 入参：无。
-- 出参：无。
function WowBuddyDev.ClearErrorLogs()
  wipe(WowBuddyDev.errorLogs)
  if WowBuddyDev.RefreshErrorLog then
    WowBuddyDev.RefreshErrorLog()
  end
end
WowBuddyDev.RegisterModule("CoreLocale", { "Core" })
