-- ==========================================================================
-- 文件：c2f0bc.lua
-- 来源：P07483180.rar → P07483180/c2f0bc.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：c2f0bc.lua → SettingsReset.lua（按功能重命名）
-- 作用：设置界面的恢复默认部分
-- ==========================================================================
WowBuddyDev.macroEditorFrame = CreateFrame("Frame", nil, WowBuddyDev.mainFrame)
WowBuddyDev.macroEditorFrame:SetSize(520, 444)
WowBuddyDev.macroEditorFrame:SetPoint("TOPLEFT", WowBuddyDev.mainFrame, "TOPLEFT", 10, -76)
WowBuddyDev.macroEditorFrame:SetPoint("BOTTOMRIGHT", WowBuddyDev.mainFrame, "BOTTOMRIGHT", -10, 40)
WowBuddyDev.macroEditorFrame:Hide()
local frame = CreateFrame("ScrollFrame", "WowBuddyDevMacroEditorScroll", WowBuddyDev.macroEditorFrame, "UIPanelScrollFrameTemplate")
frame:SetPoint("TOPLEFT", WowBuddyDev.macroEditorFrame, "TOPLEFT", 0, 0)
frame:SetPoint("BOTTOMRIGHT", WowBuddyDev.macroEditorFrame, "BOTTOMRIGHT", -26, 0)
frame:EnableMouseWheel(true)
frame:SetScript("OnMouseWheel", function(self, event)
  local scrollBar = _G[self:GetName() .. "ScrollBar"]
  if scrollBar then
    scrollBar:SetValue(scrollBar:GetValue() - event * 48)
  end
end)
local frame2 = CreateFrame("Frame", nil, frame)
frame2:SetSize(480, 36)
frame:SetScrollChild(frame2)
local macroRows = {}
-- 功能：取「当前专精」的展示名，供按键页顶部提示用。
-- 入参：无。
-- 出参：形如「神圣 (12/0/0)」；天赋读不到 / 还没加点 / 没有该职业的表时返回 nil。
-- 说明：必须与 IsActionOfCurrentSpec 用的是同一份天赋状态，否则会出现
--       「提示说在按专精过滤，实际一条都没过滤」这种自相矛盾的界面。
--       mainIndex <= 0（未加点）时过滤本来就全放行，所以这里也返回 nil 不提示。
local function currentSpecFilterName()
  if not (WowBuddyDev.ForeverSpecSpells and WowBuddyDev.DB) then
    return nil
  end
  local specID = tonumber(WowBuddyDev.DB.currentSpecID)
  if not specID or not WowBuddyDev.ForeverSpecSpells[specID] then
    return nil
  end
  if type(WowBuddyDev.GetForeverTalentState) ~= "function" then
    return nil
  end
  local ok, state = pcall(WowBuddyDev.GetForeverTalentState, specID)
  if not ok or type(state) ~= "table" or not state.readable then
    return nil
  end
  if type(state.mainIndex) ~= "number" or state.mainIndex <= 0 or not state.display then
    return nil
  end
  return state.display
end
local specHint = frame2:CreateFontString(nil, "OVERLAY", "GameFontNormal")
specHint:SetPoint("TOPLEFT", frame2, "TOPLEFT", 24, -4)
specHint:SetJustifyH("LEFT")
specHint:Hide()
-- 功能：重建宏编辑页：清掉旧行，按 macroOrder 顺序给每个动作键建一行。
-- 入参：无。
-- 出参：无。
-- 说明：macroOrder 为空时用动作键映射表兜底，并按 spell_数字 里的数字排序；每行占两列（第一列 x=24、第二列 x=260，行高 24、首行 y=-20），全部建完再按行数调整滚动区高度并回到顶部。
--       ★ 只列当前专精的技能（见 Core.lua IsActionOfCurrentSpec）：天赋树上有归属的按主系判，
--         训练师通用技能看学没学会，读不到就放行；切焦点/自动攻击这类非技能动作一律保留。
ShowMacroEditor = function()
  for index, row in ipairs(macroRows) do
    row:Hide()
    row:SetParent(nil)
  end
  wipe(macroRows)
  local macroOrder = WowBuddyDev.classData and WowBuddyDev.classData.macroOrder or {}
  if #macroOrder == 0 then
    for k, orderActionKey in pairs(WowBuddyDev.ACTION_TO_KEY) do
      table.insert(macroOrder, k)
    end
    table.sort(macroOrder, function(leftKey, rightKey)
      local leftSpellID = tonumber(leftKey:match("spell_(%d+)")) or 0
      local rightSpellID = tonumber(rightKey:match("spell_(%d+)")) or 0
      return leftSpellID < rightSpellID
    end)
  end
  local startY = -20
  local rowHeight = 24
  local firstColumnX = 24
  local secondColumnX = 260
  local columnIndex = 0
  local rowIndex = 0
  local specName = currentSpecFilterName()
  if specName then
    specHint:SetText(WowBuddyDev.L("只显示当前专精的技能：%s"):format(specName))
    specHint:Show()
    startY = startY - rowHeight
  else
    specHint:Hide()
  end
  for index2, actionKey in ipairs(macroOrder) do
    local boundKey = WowBuddyDev.ACTION_TO_KEY[actionKey]
    local actionLabel = WowBuddyDev.LocalizeActionLabel(actionKey, WowBuddyDev.ACTION_LABELS[actionKey] or actionKey)
    if boundKey and WowBuddyDev.IsActionOfCurrentSpec(actionKey) then
      local rowX = columnIndex == 0 and firstColumnX or secondColumnX
      local rowY = startY - rowIndex * rowHeight
      local macroRow = WowBuddyDev.CreateMacroRow(frame2, actionKey, boundKey, actionLabel, rowX, rowY)
      table.insert(macroRows, macroRow)
      columnIndex = columnIndex + 1
      if columnIndex >= 2 then
        columnIndex = 0
        rowIndex = rowIndex + 1
      end
    end
  end
  local totalRowCount = rowIndex
  if columnIndex > 0 then
    totalRowCount = totalRowCount + 1
  end
  -- ★ 顶部提示行也占一行高度：漏了它，最后一行会被滚动区裁掉 8px（能滚但看着像缺行）。
  local hintOffset = specName and rowHeight or 0
  frame2:SetHeight(36 + hintOffset + totalRowCount * rowHeight)
  frame:SetVerticalScroll(0)
end
WowBuddyDev.tabFrames[3] = WowBuddyDev.macroEditorFrame
local resetButton = WowBuddyDev.CreateStyledButton(WowBuddyDev.macroEditorFrame, WowBuddyDev.L("恢复默认"), 100, 24)
resetButton:SetPoint("BOTTOMLEFT", WowBuddyDev.macroEditorFrame, "BOTTOMLEFT", 30, 10)
-- 功能：按是否处于战斗锁定，切换「恢复默认」按钮的可用状态。
-- 入参：无。
-- 出参：无。
-- 说明：同一个函数既当 PLAYER_REGEN_DISABLED / PLAYER_REGEN_ENABLED 的回调，也在注册后立刻手工调一次，保证进面板时状态就是对的。
local function updateResetButtonState()
  if InCombatLockdown() then
    resetButton:Disable()
  else
    resetButton:Enable()
  end
end
resetButton:RegisterEvent("PLAYER_REGEN_DISABLED")
resetButton:RegisterEvent("PLAYER_REGEN_ENABLED")
resetButton:SetScript("OnEvent", updateResetButtonState)
updateResetButtonState()
resetButton:SetScript("OnClick", function()
  if InCombatLockdown() then
    return
  end
  for pairActionKey, pairBoundKey in pairs(WowBuddyDev.ACTION_TO_KEY) do
    WowBuddyDev.ClearUserMacro(pairActionKey)
    local defaultMacro = WowBuddyDev.GetDefaultMacro and WowBuddyDev.GetDefaultMacro(pairActionKey)
    if defaultMacro then
      WowBuddyDev.CreateSecureButton(pairActionKey, pairBoundKey, defaultMacro)
    end
  end
  SaveBindings(GetCurrentBindingSet())
  ShowMacroEditor()
  print(WowBuddyDev.L("|cff00ff00[WowBuddyDev]|r 全部宏已恢复官方默认"))
end)
