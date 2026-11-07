-- ==========================================================================
-- 文件：301f9d.lua
-- 来源：P07483180.rar → P07483180/301f9d.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：301f9d.lua → DebugDock.lua（按功能重命名）
-- 作用：调试窗口（充能直读、驱散开发、场景诊断）
-- ==========================================================================
local DEBUG_PREFIX = "|cff00ff88[WowBuddyDev Dev]|r"
local dockSections = {
  {
    title = "v2 引擎",
    items = {
      {
        label = "v2 状态",
        cmd = "/pmsv2",
        tip = "打印 v2 引擎面板状态与逐槽探针（逐变体冷却/充能/aura 实查）",
      },
      {
        label = "充能直读",
        cmd = "/pmscharge",
        tip = "打印当前专精充能技能的候选ID、当前ID与直读层数",
      },
    },
  },
  {
    title = "Aura 排障",
    items = {
      {
        label = "aura观察",
        cmd = "/pmswatch",
        tip = "战斗中新 aura 自动捕获：脱战 diff 打印真身 spellID",
      },
      {
        label = "aura快照",
        cmd = "/pmswatch now",
        tip = "立即全量打印当前 aura（脱战手动 dump）",
      },
      { label = "调试窗口", cmd = "/pmsdebug", tip = "打开 Aura 调试窗口" },
    },
  },
  {
    title = "驱散开发",
    items = {
      {
        label = "loc收集",
        cmd = "/pmsloc",
        tip = "LoC 失控机制收集器开关：被控瞬间打印可粘贴进 locTypes 的白名单行（同 locType + spellID 去重）",
      },
      {
        label = "loc清单",
        cmd = "/pmsloc dump",
        tip = "重印本次会话已收集的全部 locType 条目",
      },
    },
  },
  {
    title = "场景诊断",
    items = {
      {
        label = "敌人统计",
        cmd = "/mklactive",
        tip = "统计可见姓名板中正在战斗的存活敌人数量",
      },
      {
        label = "目标探测",
        cmd = "/mkltarget",
        tip = "打印当前目标身份（NPC ID 等，木桩实测用）",
      },
      { label = "综合诊断", cmd = "/pmstest", tip = "角色信息 + API 可用性 + 模块状态总览" },
    },
  },
}
-- 功能：把一条斜杠命令文本塞进聊天输入框并直接发送（停靠窗菜单按钮点击的实现）。
-- 入参：chatCommand 要发送的命令文本。
-- 出参：无。
-- 说明：先用 ChatEdit_ChooseBoxForSend 取当前可用的聊天框；取不到（或 ChatEdit_SendText 不存在）就只打印「命令不可用」，不抛错。发送前先存下输入框原文、发完原样还原，免得把玩家正在打字的半截内容冲掉。
local function runChatCommand(chatCommand)
  local chatEditBox = ChatEdit_ChooseBoxForSend and ChatEdit_ChooseBoxForSend()
  if not (chatEditBox and ChatEdit_SendText) then
    print(DEBUG_PREFIX .. " |cffff0000命令不可用: " .. tostring(chatCommand) .. "|r")
    return
  end
  local originalText = chatEditBox:GetText()
  chatEditBox:SetText(chatCommand)
  ChatEdit_SendText(chatEditBox)
  if originalText and originalText ~= "" then
    chatEditBox:SetText(originalText)
  end
end
-- 功能：按名字或法术 ID 查技能，打印 spellID / iconID / 冷却 / 充能，供 /pmsspell 与停靠窗查询框使用。
-- 入参：spellNameOrID 技能名或数字形式的法术 ID 字符串。
-- 出参：无（结果全部 print 到聊天框）。
-- 说明：先 strtrim，空串直接返回；查不到技能就打印「未找到技能」。冷却走 C_Spell.GetSpellCooldown，用返回值 2 判断是否真在冷却（>1.5 才算，否则显示「就绪」）。充能同时给出「客户端 maxCharges」和「插件引擎 GetSpellChargeCount 的直读值」，两边对不上时正好用来对账。
local function printSpellInfo(spellNameOrID)
  spellNameOrID = spellNameOrID and strtrim(spellNameOrID) or ""
  if spellNameOrID == "" then
    return
  end
  local spellInfo = C_Spell and (C_Spell.GetSpellInfo and C_Spell.GetSpellInfo(spellNameOrID))
  if not (spellInfo and spellInfo.spellID) then
    print(DEBUG_PREFIX .. " |cffff0000未找到技能: " .. spellNameOrID .. "|r")
    return
  end
  local spellID = spellInfo.spellID
  print(string.format("%s %s | spellID: %d | iconID: %d", DEBUG_PREFIX, tostring(spellInfo.name or spellNameOrID), spellID, spellInfo.iconID or 0))
  if C_Spell.GetOverrideSpell then
    local okOverride, overrideSpellID = pcall(C_Spell.GetOverrideSpell, spellID, 0, false)
    if okOverride and (type(overrideSpellID) == "number" and overrideSpellID ~= spellID) then
      local overrideInfo = C_Spell.GetSpellInfo(overrideSpellID)
      print(string.format("%s   变体: %d（%s）", DEBUG_PREFIX, overrideSpellID, overrideInfo and overrideInfo.name or "?"))
    end
  end
  local cooldownText = "受限（战斗中）"
  if C_Spell.IsSpellKnown and C_Spell.IsSpellKnown(spellID) == false then
    cooldownText = "未学会"
  else
    local okCooldown, cooldownDetail = pcall(function()
      local startTime, duration = C_Spell.GetSpellCooldown(spellID)
      if not startTime or not duration or duration <= 1.5 then
        return "就绪"
      end
      local remaining = startTime + duration - GetTime()
      if remaining <= 0 then
        return "就绪"
      end
      return string.format("剩余 %.1f 秒", remaining)
    end)
    if okCooldown then
      cooldownText = cooldownDetail
    end
  end
  print(string.format("%s   冷却: %s", DEBUG_PREFIX, cooldownText))
  local maxChargesText = nil
  if C_Spell.GetSpellCharges then
    local okCharges, chargeInfo = pcall(C_Spell.GetSpellCharges, spellID)
    if okCharges and (chargeInfo and chargeInfo.maxCharges) then
      local okMaxCharges, maxChargesRaw = pcall(tostring, chargeInfo.maxCharges)
      maxChargesText = okMaxCharges and maxChargesRaw or "?"
    end
  end
  local engineCharges = WowBuddyDev.GetSpellChargeCount and WowBuddyDev.GetSpellChargeCount(spellID)
  local hasRawCharges, rawChargesValue = false, nil
  if WowBuddyDev.GetSpellChargeDisplayRaw then
    hasRawCharges, rawChargesValue = WowBuddyDev.GetSpellChargeDisplayRaw(spellID)
  end
  local chargeText = "无充能机制"
  if maxChargesText or engineCharges ~= nil or hasRawCharges then
    local engineChargesText = engineCharges ~= nil and tostring(engineCharges) or nil
    if not engineChargesText and hasRawCharges then
      local okRawText, rawText = pcall(function()
        return tostring(rawChargesValue) .. "(原值)"
      end)
      engineChargesText = okRawText and rawText or "受限"
    end
    chargeText = string.format("%s/%s", engineChargesText or "?", maxChargesText or "?")
  end
  print(string.format("%s   充能: %s", DEBUG_PREFIX, chargeText))
end
-- 功能：把停靠窗当前锚点存进 P07483180.DB.debugDockPoint，供下次打开还原位置。
-- 入参：dockFrame 停靠窗框架。
-- 出参：无。
-- 说明：没有 P07483180.DB 或框架不支持 GetPoint 时直接返回。GetPoint(1) 只取第一个锚点的 point/x/y（中间的 relativeTo、relativePoint 用不上，仅占位）。
local function saveDockPosition(dockFrame)
  if not (WowBuddyDev.DB and dockFrame.GetPoint) then
    return
  end
  local point, relativeTo, relativePoint, offsetX, offsetY = dockFrame:GetPoint(1)
  WowBuddyDev.DB.debugDockPoint = { point = point, x = offsetX, y = offsetY }
end
-- 功能：按存档还原停靠窗位置；没有存档就退回默认位置（屏幕左侧 240,40）。
-- 入参：dockFrame 停靠窗框架。
-- 出参：无。
-- 说明：存档里缺 x/y 时按 0 处理，所以早期缺字段的旧存档不会把窗口甩到屏幕外。
local function restoreDockPosition(dockFrame)
  local savedPoint = WowBuddyDev.DB and WowBuddyDev.DB.debugDockPoint
  if savedPoint and savedPoint.point then
    dockFrame:SetPoint(savedPoint.point, UIParent, savedPoint.point, savedPoint.x or 0, savedPoint.y or 0)
  else
    dockFrame:SetPoint("LEFT", UIParent, "LEFT", 240, 40)
  end
end
local dockFrame = nil
-- 功能：建（并缓存）调试停靠窗：标题、关闭按钮、分组菜单按钮、按名查 ID 输入框。
-- 入参：无。
-- 出参：dockFrame 停靠窗框架（已建过就直接返回同一个）。
-- 说明：菜单数据来自文件顶部的 dockSections。按钮两列排布、行高 26；每个按钮在 OnEnter 里先把原来的 OnEnter 处理函数调一遍再补自己的 tooltip，这样不会覆盖 CreateStyledButton 自带的高亮行为。查询框回车和「查询」按钮都走 runSpellQuery。
local function getDebugDock()
  if dockFrame then
    return dockFrame
  end
  dockFrame = CreateFrame("Frame", "WowBuddyDevDebugDock", UIParent, "BackdropTemplate")
  dockFrame:SetSize(250, 460)
  dockFrame:SetFrameStrata("DIALOG")
  dockFrame:SetMovable(true)
  dockFrame:EnableMouse(true)
  dockFrame:RegisterForDrag("LeftButton")
  dockFrame:SetScript("OnDragStart", dockFrame.StartMoving)
  dockFrame:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    saveDockPosition(self)
  end)
  dockFrame:SetBackdrop({
    bgFile = "Interface/ChatFrame/ChatFrameBackground",
    edgeFile = "Interface/ChatFrame/ChatFrameBackground",
    edgeSize = 1,
  })
  dockFrame:SetBackdropColor(.08, .08, .08, .95)
  dockFrame:SetBackdropBorderColor(0, 1, .53, .6)
  local titleText = dockFrame:CreateFontString(nil, "OVERLAY")
  titleText:SetFont(STANDARD_TEXT_FONT, 13, "OUTLINE")
  titleText:SetPoint("TOPLEFT", dockFrame, "TOPLEFT", 10, -7)
  titleText:SetText("|cff00ff88" .. WowBuddyDev.L("WowBuddyDev 调试") .. "|r")
  local closeButton = CreateFrame("Button", nil, dockFrame)
  closeButton:SetSize(18, 18)
  closeButton:SetPoint("TOPRIGHT", dockFrame, "TOPRIGHT", -4, -4)
  local closeTexture = closeButton:CreateTexture(nil, "OVERLAY")
  closeTexture:SetAllPoints()
  closeTexture:SetColorTexture(.8, .2, .25, .9)
  closeButton:SetScript("OnClick", function()
    dockFrame:Hide()
  end)
  local cursorY = -28
  for sectionIndex, v in ipairs(dockSections) do
    local sectionText = dockFrame:CreateFontString(nil, "OVERLAY")
    sectionText:SetFont(STANDARD_TEXT_FONT, 11, "OUTLINE")
    sectionText:SetPoint("TOPLEFT", dockFrame, "TOPLEFT", 10, cursorY)
    sectionText:SetText("|cffffcc00" .. WowBuddyDev.L(v.title) .. "|r")
    cursorY = cursorY - 17
    for itemIndex, item in ipairs(v.items) do
      local columnIndex = (itemIndex - 1) % 2
      local buttonY = cursorY - math.floor((itemIndex - 1) / 2) * 26
      local menuButton = WowBuddyDev.CreateStyledButton(dockFrame, WowBuddyDev.L(item.label), 112, 22)
      menuButton:SetPoint("TOPLEFT", dockFrame, "TOPLEFT", 10 + columnIndex * 118, buttonY)
      menuButton:SetScript("OnClick", function()
        runChatCommand(item.cmd)
      end)
      local originalEnterHandler = menuButton:GetScript("OnEnter")
      menuButton:SetScript("OnEnter", function(self2)
        if originalEnterHandler then
          originalEnterHandler(self2)
        end
        GameTooltip:SetOwner(self2, "ANCHOR_RIGHT")
        GameTooltip:SetText(WowBuddyDev.L(item.label), 1, 1, 1)
        GameTooltip:AddLine(WowBuddyDev.L(item.tip), nil, nil, nil, true)
        GameTooltip:Show()
      end)
      local originalLeaveHandler = menuButton:GetScript("OnLeave")
      menuButton:SetScript("OnLeave", function(self3)
        if originalLeaveHandler then
          originalLeaveHandler(self3)
        end
        GameTooltip:Hide()
      end)
    end
    cursorY = cursorY - math.ceil(#v.items / 2) * 26 - 8
  end
  local searchLabel = dockFrame:CreateFontString(nil, "OVERLAY")
  searchLabel:SetFont(STANDARD_TEXT_FONT, 11, "OUTLINE")
  searchLabel:SetPoint("TOPLEFT", dockFrame, "TOPLEFT", 10, cursorY)
  searchLabel:SetText("|cffffcc00" .. WowBuddyDev.L("按名查 ID") .. "|r")
  local searchBox = CreateFrame("EditBox", nil, dockFrame, "InputBoxTemplate")
  searchBox:SetSize(140, 22)
  searchBox:SetPoint("TOPLEFT", dockFrame, "TOPLEFT", 10, cursorY - 17)
  searchBox:SetAutoFocus(false)
  searchBox:SetMaxLetters(40)
  local searchButton = WowBuddyDev.CreateStyledButton(dockFrame, WowBuddyDev.L("查询"), 76, 22)
  searchButton:SetPoint("TOPLEFT", dockFrame, "TOPLEFT", 158, cursorY - 17)
  -- 功能：读取「按名查 ID」输入框的内容去查技能，查完取消焦点。
  -- 入参：无。
  -- 出参：无。
  -- 说明：这个局部函数同时挂给按钮的 OnClick 和输入框的 OnEnterPressed，两处行为一致。
  local function runSpellQuery()
    printSpellInfo(searchBox:GetText())
    searchBox:ClearFocus()
  end
  searchButton:SetScript("OnClick", runSpellQuery)
  searchBox:SetScript("OnEnterPressed", runSpellQuery)
  searchBox:SetScript("OnEscapePressed", function(self4)
    self4:ClearFocus()
  end)
  dockFrame:SetHeight(-(cursorY - 43) + 12)
  restoreDockPosition(dockFrame)
  dockFrame:Hide()
  return dockFrame
end
-- 功能：开关调试停靠窗（/pmsdev）。
-- 入参：无。
-- 出参：无。
-- 说明：战斗中不做位置还原（InCombatLockdown 时改动安全框架位置会被客户端拒绝），只显示/隐藏。
function WowBuddyDev.ToggleDebugDock()
  local dockFrame = getDebugDock()
  if dockFrame:IsShown() then
    dockFrame:Hide()
  else
    if not InCombatLockdown() then
      restoreDockPosition(dockFrame)
    end
    dockFrame:Show()
  end
end
SLASH_PMSDEV1 = "/pmsdev"
SlashCmdList.PMSDEV = function()
  WowBuddyDev.ToggleDebugDock()
end
SLASH_PMSSPELL1 = "/pmsspell"
SlashCmdList.PMSSPELL = function(spellNameOrID)
  printSpellInfo(spellNameOrID)
end
