-- ==========================================================================
-- 文件：CoreButtons.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 2296-2716 行），语句与顺序未改。
-- 作用：安全按钮创建、宏绑定与按键覆盖、绑定检查命令、职业数据注册。
-- 加载：TOC 中位于 CoreLocale.lua 之后、CoreEvents.lua 之前（原文件中的相对顺序）。
-- ==========================================================================
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreButtons", { "CoreSettings", "CoreState", "Core", "CoreLocale", "CoreEvents", "CoreControls", "Bindings", "RaidFocus", "AutoTarget", "Recovery", "WandShot", "CharacterState", "PixelBar", "DirectCastHook" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local reloadClassData = WowBuddyDev.Require("CoreClassData").reloadClassData -- @@拆分新增@@
local migrateChijiMacro = WowBuddyDev.Require("CoreSettings").migrateChijiMacro -- @@拆分新增@@
-- 原在 Core.lua 第 93 行前置声明，本段内赋值，经导出表提供给 CoreEvents。
local refreshMacroBindings -- @@拆分新增@@
-- ---- 以下为原 Core.lua 内容 ----
local secureButtons = {}
local macroBindingRegistry = {}
local macroBindingErrors = {}
WowBuddyDev.macroBindingBackend = "ZZHELPER"
local NUMPAD_KEY_ALIASES = { NUMPADADD = "NUMPADPLUS", NUMPADSUBTRACT = "NUMPADMINUS" }
-- 功能：把按键字符串规范化：取出修饰键、统一大小写、把小键盘别名换成标准名，最后按固定顺序拼回修饰键。
-- 入参：key 原始按键字符串。
-- 出参：规范化后的按键字符串。
-- 说明：客户端不同来源的按键写法不一致（大小写、修饰键顺序、小键盘两套名字），不统一就会出现「同一个键被当成两个键」，导致按键判定和冲突检测漏判。
local function normalizeBindingKey(key)
  if type(key) ~= "string" then
    return key
  end
  local normalizedKey = key:match("^%s*(.-)%s*$"):upper()
  local hasAlt = normalizedKey:find("ALT%-") ~= nil
  local hasCtrl = normalizedKey:find("CTRL%-") ~= nil
  local hasShift = normalizedKey:find("SHIFT%-") ~= nil
  normalizedKey = normalizedKey:gsub("ALT%-", ""):gsub("CTRL%-", ""):gsub("SHIFT%-", "")
  normalizedKey = NUMPAD_KEY_ALIASES[normalizedKey] or normalizedKey
  return (hasAlt and "ALT-" or "") .. (hasCtrl and "CTRL-" or "") .. (hasShift and "SHIFT-" or "") .. normalizedKey
end
local overrideOwnerFrame = CreateFrame("Frame", "WowBuddyDevOverrideOwner")
local applyingMacroBindings = false
local bindingRefreshScheduled = false
local function reportMacroBindingError(actionKey, message)
  message = tostring(message)
  if macroBindingErrors[actionKey] == message then
    return
  end
  macroBindingErrors[actionKey] = message
  WowBuddyDev.AddErrorLog("MacroBinding", tostring(actionKey) .. ": " .. message)
end
WowBuddyDev.ReportMacroBindingError = reportMacroBindingError
-- 功能：建（或复用）一个安全按钮，并按当前配置给它设置好点击行为。
-- 入参：actionKey 动作键；bindingKey 绑定的按键；macroBody 要执行的宏体。
-- 出参：true 成功；false 表示战斗中延后处理。
-- 说明：采用 ZZHELPER Layout.lua 的隐藏宏按钮方式，每个按钮拥有自己的覆写绑定。
function WowBuddyDev.CreateSecureButton(actionKey, bindingKey, macroBody)
  if InCombatLockdown() then
    overrideOwnerFrame.pendingMacroBindings = true
    return false
  end
  local normalizedKey = normalizeBindingKey(bindingKey)
  if WowBuddyDev.GetClassBindingAction then
    actionKey = WowBuddyDev.GetClassBindingAction(actionKey, normalizedKey)
  end
  assert(type(actionKey) == "string" and actionKey ~= "", "Invalid action key")
  assert(type(normalizedKey) == "string" and normalizedKey ~= "", "Invalid binding key")
  assert(macroBody == nil or type(macroBody) == "string", "Invalid macro text")
  local buttonName = "WBD_BTN_" .. actionKey
  local secureButton = secureButtons[actionKey]
  if not secureButton then
    secureButton = CreateFrame("Button", buttonName, UIParent, "SecureActionButtonTemplate")
    secureButton:SetSize(30, 30)
    secureButton:SetPoint("TOPLEFT", UIParent, "BOTTOMRIGHT", 1, -1)
    secureButton:RegisterForClicks("AnyDown", "AnyUp")
    secureButton:Show()
    secureButtons[actionKey] = secureButton
  end
  ClearOverrideBindings(secureButton)
  macroBindingRegistry[actionKey] = nil
  secureButton:SetAttribute("spell", nil)
  secureButton:SetAttribute("unit", nil)
  secureButton:SetAttribute("type", "macro")
  secureButton:SetAttribute("macrotext", macroBody or "")
  local ok, result = pcall(SetOverrideBindingClick, secureButton, true, normalizedKey, buttonName, "LeftButton")
  if not ok or result == false then
    local message = ok and "SetOverrideBindingClick rejected binding" or result
    reportMacroBindingError(actionKey, message)
    error(message, 0)
  end
  macroBindingRegistry[actionKey] = {
    key = normalizedKey, buttonName = buttonName, macroText = macroBody or "",
  }
  macroBindingErrors[actionKey] = nil
  -- 可选观察者（DirectCast 点击挂钩）；它出错不能影响已经完成的绑定。
  if type(WowBuddyDev.OnSecureButtonBound) == "function" then
    pcall(WowBuddyDev.OnSecureButtonBound, secureButton, actionKey)
  end
  return true
end
-- 功能：按动作键取回它的安全按钮对象。
-- 入参：actionKey 动作键。
-- 出参：按钮对象；取不到时返回 nil。
-- 说明：给需要往按钮上挂硬件事件钩子的模块用（如自动选目标的执行回执）。
--       按钮在 CreateFrame 时带了全局名，所以登记表里查不到也能按名字兜回来。
function WowBuddyDev.GetSecureButton(actionKey)
  if type(actionKey) ~= "string" or actionKey == "" then
    return nil
  end
  local button = secureButtons[actionKey]
  if button then
    return button
  end
  return _G["WBD_BTN_" .. actionKey]
end
function WowBuddyDev.NormalizeClassActionKey(actionKey)
  local key = type(actionKey) == "string" and actionKey:match("^class_(.+)$")
  return key and "class_" .. normalizeBindingKey(key) or nil
end
-- 只读返回成功登记的宏文本，不暴露可变登记表或读取受保护按钮属性。
-- /dc 命令会转为小写；逻辑动作和 class_* 按键使用同一套绑定映射。
function WowBuddyDev.GetBoundMacro(actionKey)
  if type(actionKey) ~= "string" or actionKey == "" then return nil end
  local entry = macroBindingRegistry[actionKey]
  if not entry then
    local classAction = WowBuddyDev.NormalizeClassActionKey(actionKey)
    if classAction then
      entry = macroBindingRegistry[classAction]
    elseif WowBuddyDev.GetClassBindingAction then
      local bindingKey = (WowBuddyDev.ACTION_TO_KEY or {})[actionKey]
      if bindingKey then
        local registered = WowBuddyDev.GetClassBindingAction(actionKey, normalizeBindingKey(bindingKey))
        entry = macroBindingRegistry[registered]
      end
    end
  end
  return entry and entry.macroText or nil
end
-- 功能：建（或复用）一个安全按钮，用于把焦点设到指定单位。
-- 入参：actionKey 动作键；bindingKey 绑定的按键；unit 目标单位。
-- 出参：true 成功；false 表示战斗中延后处理。
-- 说明：焦点切换也使用隐藏宏按钮，保留单位存在条件。
function WowBuddyDev.CreateSecureFocusButton(actionKey, bindingKey, unit)
  assert(type(unit) == "string" and unit:match("^%w+$"), "Invalid focus unit")
  return WowBuddyDev.CreateSecureButton(actionKey, bindingKey, "/focus [@" .. unit .. ",exists]")
end
-- 功能：全局重刷宏的总入口——把所有动作键重新写成安全按钮绑定。
-- 入参：无。
-- 出参：无。
-- 说明：战斗中改绑定会被客户端拒绝，所以直接记下 pendingMacroBindings 标记，等 PLAYER_REGEN_ENABLED 再重刷。宏体里带 `spell:数字` 的一律丢弃并改回默认宏——这种缩写宏已经不能用，留着只会刷出无效按钮。每个动作键单独包 pcall 创建，某个键失败不影响其余按键；职业模块的团队焦点、自动选目标绑定和按键冲突缓存也在这里一起刷新。
ApplyMacros_Internal = function()
  if InCombatLockdown() then
    overrideOwnerFrame.pendingMacroBindings = true
    return
  end
  overrideOwnerFrame.pendingMacroBindings = nil
  migrateChijiMacro()
  ClearOverrideBindings(overrideOwnerFrame)
  -- Per-button owners must all be cleared when the specialization changes.
  for _, button in pairs(secureButtons) do
    ClearOverrideBindings(button)
    button:SetAttribute("type", nil)
    button:SetAttribute("macrotext", nil)
  end
  wipe(macroBindingRegistry)
  wipe(macroBindingErrors)
  local hasClassMacros = false
  if WowBuddyDev.ApplyClassMacros then
    local ok, result = pcall(WowBuddyDev.ApplyClassMacros)
    hasClassMacros = ok and result
    if not ok then
      reportMacroBindingError("class", result)
    end
  end
  for k8, boundKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
    local macroBody = WowBuddyDev.GetDefaultMacro(k8)
    local isUserEdited, userMacroBody = WowBuddyDev.GetUserMacro(k8)
    if isUserEdited then
      macroBody = userMacroBody
    end
    if macroBody and macroBody:find("spell:%d+") then
      macroBody = nil
      isUserEdited = false
    end
    if not isUserEdited and (not macroBody or macroBody == "") then
      macroBody = WowBuddyDev.GetDefaultMacro(k8)
    end
    if not hasClassMacros or isUserEdited then
      local callOK, callErr = pcall(WowBuddyDev.CreateSecureButton, k8, boundKey, macroBody)
      if not callOK then
        reportMacroBindingError(k8, callErr)
      end
    end
  end
  if WowBuddyDev.ApplyRaidFocusBindings then
    local ok, err = pcall(WowBuddyDev.ApplyRaidFocusBindings)
    if not ok then reportMacroBindingError("raid_focus", err) end
  end
  if WowBuddyDev.ApplyAutoTargetBinding then
    local ok, err = pcall(WowBuddyDev.ApplyAutoTargetBinding)
    if not ok then reportMacroBindingError("auto_target", err) end
  end
  if WowBuddyDev.ApplyRecoveryBindings then
    local ok, err = pcall(WowBuddyDev.ApplyRecoveryBindings)
    if not ok then reportMacroBindingError("recovery", err) end
  end
  if WowBuddyDev.ApplyWandBinding then
    local ok, err = pcall(WowBuddyDev.ApplyWandBinding)
    if not ok then reportMacroBindingError("shoot_wand", err) end
  end
  if WowBuddyDev.ApplyDiscardTargetBinding then
    local ok, err = pcall(WowBuddyDev.ApplyDiscardTargetBinding)
    if not ok then reportMacroBindingError("discard_unreachable_target", err) end
  end
  if WowBuddyDev.InvalidateControlBindingConflicts then
    WowBuddyDev.InvalidateControlBindingConflicts()
  end
end
-- 功能：安全地重刷所有安全按钮的宏绑定（整体包一层保护调用）。
-- 入参：无。
-- 出参：无。
-- 说明：记录绑定失败，并阻止刷新期间的 UPDATE_BINDINGS 递归调度。
refreshMacroBindings = function()
  if applyingMacroBindings then
    return
  end
  applyingMacroBindings = true
  local callOK, callErr = pcall(ApplyMacros_Internal)
  applyingMacroBindings = false
  if not callOK then
    reportMacroBindingError("refresh", callErr)
  end
end
WowBuddyDev.RefreshMacroBindings = refreshMacroBindings
overrideOwnerFrame:RegisterEvent("UPDATE_BINDINGS")
overrideOwnerFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
overrideOwnerFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
overrideOwnerFrame:SetScript("OnEvent", function(self4, eventName)
  if eventName == "UPDATE_BINDINGS" then
    if applyingMacroBindings or bindingRefreshScheduled then
      return
    end
    bindingRefreshScheduled = true
    C_Timer.After(0, function()
      bindingRefreshScheduled = false
      refreshMacroBindings()
    end)
  elseif eventName == "PLAYER_ENTERING_WORLD" then
    for index14, delaySec in ipairs({ 3, 6, 9 }) do
      C_Timer.After(delaySec, function()
        refreshMacroBindings()
      end)
    end
  elseif eventName == "PLAYER_REGEN_ENABLED" and self4.pendingMacroBindings then
    refreshMacroBindings()
  end
end)
function WowBuddyDev.CheckMacroBindings()
  local passed, total = 0, 0
  local failures = {}
  local activeBindings = {}
  for actionKey, entry in pairs(macroBindingRegistry) do
    local button = secureButtons[actionKey]
    if GetBindingAction(entry.key, true) == "CLICK " .. entry.buttonName .. ":LeftButton"
        and button:GetAttribute("type") == "macro"
        and button:GetAttribute("macrotext") == entry.macroText then
      activeBindings[entry.key] = entry
    end
  end
  for actionKey, entry in pairs(macroBindingRegistry) do
    total = total + 1
    local button = secureButtons[actionKey]
    local expected = "CLICK " .. entry.buttonName .. ":LeftButton"
    local actual = GetBindingAction(entry.key, true) or ""
    -- Cooldown and spell actions can intentionally share a key and macro.
    local alias = activeBindings[entry.key]
    local matches = actual == expected or (alias and alias.macroText == entry.macroText)
    if matches and button:GetAttribute("type") == "macro"
        and button:GetAttribute("macrotext") == entry.macroText then
      passed = passed + 1
    else
      failures[#failures + 1] = actionKey .. " (" .. entry.key .. "): " .. actual
    end
  end
  for actionKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
    local registeredAction = actionKey
    if WowBuddyDev.GetClassBindingAction then
      registeredAction = WowBuddyDev.GetClassBindingAction(actionKey, WowBuddyDev.ACTION_TO_KEY[actionKey])
    end
    if not macroBindingRegistry[registeredAction] then
      total = total + 1
      failures[#failures + 1] = actionKey .. ": " .. (macroBindingErrors[actionKey] or "not bound")
    end
  end
  for _, key in ipairs(WowBuddyDev.GetClassMacroKeys and WowBuddyDev.GetClassMacroKeys() or {}) do
    if not macroBindingRegistry["class_" .. key] then
      total = total + 1
      failures[#failures + 1] = key .. ": class macro not bound"
    end
  end
  for actionKey, message in pairs(macroBindingErrors) do
    if not (WowBuddyDev.ACTION_TO_KEY or {})[actionKey] then
      failures[#failures + 1] = actionKey .. ": " .. message
    end
  end
  if overrideOwnerFrame.pendingMacroBindings then
    failures[#failures + 1] = "pending combat end"
  end
  if total == 0 then
    failures[#failures + 1] = "no actions registered"
  end
  table.sort(failures)
  return #failures == 0, passed, total, failures
end
SLASH_PMBIND1 = "/pmbind"
SlashCmdList.PMBIND = function()
  local ok, passed, total, failures = WowBuddyDev.CheckMacroBindings()
  print(string.format("[WowBuddyDev] ZZHELPER bindings: %d/%d %s", passed, total, ok and "OK" or "FAILED"))
  if WowBuddyDev.GetClassMacroInfo then
    local classToken, slotCount = WowBuddyDev.GetClassMacroInfo()
    if classToken then
      print(string.format("[WowBuddyDev] %s: %d slots", classToken, slotCount))
    end
  end
  for _, message in ipairs(failures) do
    print("[WowBuddyDev] " .. message)
  end
end
do
  local SENSITIVE_ACTIONS = { "TOGGLESOUND", "TOGGLEMUSIC", "TOGGLEAMBIENCE", "TOGGLEUI" }
  local sensitiveBindingFrame = CreateFrame("Frame")
  local retryPending = false
  -- 功能：把带 Ctrl/Alt/Shift 修饰的系统功能键解绑并记进存档，避免和插件的功能键抢键。
  -- 入参：无。
  -- 出参：无。
  -- 说明：只处理带修饰键的绑定，普通绑定是玩家的常用键不动。解绑前先把原绑定记进存档（按战网账号或角色 GUID 分桶），方便以后还原。战斗中不能改绑定，这时只置一个待办标记，出战斗再补做。
  local function removeSensitiveBindings()
    if InCombatLockdown() then
      retryPending = true
      return
    end
    retryPending = false
    if not WowBuddyDev.DB then
      return
    end
    local bindingSet = GetCurrentBindingSet()
    if bindingSet ~= 1 and bindingSet ~= 2 then
      return
    end
    local ledgerScope = bindingSet == 1 and "account" or UnitGUID("player")
    if not ledgerScope then
      return
    end
    local removedAny = false
    for index15, sensitiveAction in ipairs(SENSITIVE_ACTIONS) do
      local bindingContext = C_KeyBindings.GetBindingContextForAction(sensitiveAction)
      local boundKeys = { GetBindingKey(sensitiveAction, nil, bindingContext) }
      for k9, boundKey in pairs(boundKeys) do
        if type(boundKey) == "string" and ((boundKey:find("^CTRL%-") or boundKey:find("^ALT%-") or boundKey:find("^SHIFT%-")) and GetBindingAction(boundKey, nil, bindingContext) == sensitiveAction) then
          local removedSensitiveBindings = WowBuddyDev.DB.removedSensitiveBindings or {}
          WowBuddyDev.DB.removedSensitiveBindings = removedSensitiveBindings
          removedSensitiveBindings[ledgerScope] = removedSensitiveBindings[ledgerScope] or {}
          local bindingRecordKey = tostring(bindingContext) .. ":" .. boundKey
          removedSensitiveBindings[ledgerScope][bindingRecordKey] = removedSensitiveBindings[ledgerScope][bindingRecordKey] or { key = boundKey, action = sensitiveAction, context = bindingContext }
          if SetBinding(boundKey, nil, bindingContext) then
            removedAny = true
          end
        end
      end
    end
    if removedAny then
      SaveBindings(bindingSet)
    end
  end
  sensitiveBindingFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
  sensitiveBindingFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
  sensitiveBindingFrame:SetScript("OnEvent", function(self5, eventName)
    if eventName == "PLAYER_ENTERING_WORLD" or retryPending then
      pcall(removeSensitiveBindings)
    end
  end)
end
-- 功能：注册一个职业模块，并把它的默认宏和标签登记进「技能名反查表」。
-- 入参：classFile 职业文件名；classData 职业模块数据表。
-- 出参：无。
-- 说明：反查表是给「中文技能名 → 技能 ID」用的，所以从默认宏里解析施法命令、从动作标签和像素字段里逐条登记。只登记新键、不覆盖已有值，避免后面的职业模块把先前登记的正确 ID 冲掉。如果注册的正是当前专精所属职业，就立刻重载职业数据、重刷绑定并重建像素条——职业文件是在登录后才注册的，所以这一跳是必须的。
function WowBuddyDev.RegisterClass(classFile, classData)
  WowBuddyDev.classes[classFile] = classData
  if classData.DEFAULT_MACROS then
    for k10, macroBody in pairs(classData.DEFAULT_MACROS) do
      local spellID = tonumber(k10:match("spell_(%d+)") or k10:match("cd_(%d+)") or k10:match("seq_(%d+)"))
      if spellID and type(macroBody) == "string" then
        local isFirstCast = true
        for k11 in gmatch(macroBody, "[^\n]+") do
          local castTarget = k11:match("^/cast%s+%b[]%s*(.+)$")
          if not castTarget then
            castTarget = k11:match("^/cast%s+(.+)$")
          end
          if castTarget and castTarget ~= "" then
            castTarget = castTarget:gsub("^%s+", ""):gsub("%s+$", "")
            if castTarget ~= "" and (isFirstCast and not WowBuddyDev._spellNameToID[castTarget]) then
              WowBuddyDev._spellNameToID[castTarget] = spellID
            end
            isFirstCast = false
          else
            if not k11:match("^/cast") then

            end
          end
        end
      end
    end
  end
  if classData.pixelData then
    for index16, pixelField in ipairs(classData.pixelData) do
      if pixelField.spellID and (pixelField.label and not WowBuddyDev._spellNameToID[pixelField.label]) then
        WowBuddyDev._spellNameToID[pixelField.label] = pixelField.spellID
      end
    end
  end
  if classData.ACTION_LABELS then
    for k12, label in pairs(classData.ACTION_LABELS) do
      local spellID = tonumber(k12:match("spell_(%d+)") or k12:match("cd_(%d+)") or k12:match("seq_(%d+)"))
      if spellID and (label and not WowBuddyDev._spellNameToID[label]) then
        WowBuddyDev._spellNameToID[label] = spellID
      end
    end
  end
  if IsLoggedIn and IsLoggedIn() then
    local currentSpecID = select(3, WowBuddyDev.GetPlayerClassSpec())
    if currentSpecID == classFile then
      reloadClassData()
      refreshMacroBindings()
      WowBuddyDev.RebuildPixelBars()
      if WowBuddyDev.RefreshDockButtonColors then
        WowBuddyDev.RefreshDockButtonColors()
      end
    end
  end
end
WowBuddyDev.ModuleExports("CoreButtons").refreshMacroBindings = refreshMacroBindings -- @@拆分新增@@
WowBuddyDev.RegisterModule("CoreButtons", { "CoreClassData", "Core", "CoreSettings", "CoreLocale" })
