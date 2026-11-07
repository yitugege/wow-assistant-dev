-- ==========================================================================
-- 文件：7ec6f7.lua
-- 来源：P07483180.rar → P07483180/7ec6f7.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：7ec6f7.lua → SettingsUI.lua（按功能重命名）
-- 作用：设置界面：宏行/按键/天赋导入
-- ==========================================================================
local mainWindow = CreateFrame("Frame", "WowBuddyDevMain", UIParent, BackdropTemplateMixin and "BackdropTemplate")
mainWindow:SetSize(540, 560)
mainWindow:SetPoint("CENTER", UIParent, "CENTER", 0, 0)
mainWindow:SetBackdrop({
  bgFile = "Interface\\Buttons\\WHITE8X8",
  edgeFile = "Interface\\Buttons\\WHITE8X8",
  tile = false,
  tileSize = 0,
  edgeSize = 1,
  insets = { left = 0, right = 0, top = 0, bottom = 0 },
})
mainWindow:SetBackdropColor(.08, .08, .09, .95)
mainWindow:SetBackdropBorderColor(.22, .22, .24, 1)
mainWindow:EnableMouse(true)
mainWindow:SetMovable(true)
mainWindow:RegisterForDrag("LeftButton")
mainWindow:SetScript("OnDragStart", mainWindow.StartMoving)
mainWindow:SetScript("OnDragStop", mainWindow.StopMovingOrSizing)
mainWindow:SetFrameStrata("DIALOG")
mainWindow:Hide()
WowBuddyDev.mainFrame = mainWindow
local titleText = mainWindow:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
titleText:SetPoint("TOP", mainWindow, "TOP", 0, -14)
titleText:SetText("WowBuddyDev")
local tabButtons = {}
WowBuddyDev.tabFrames = {}
-- 功能：切换主窗口标签页：选中项高亮、其余置灰，按序号显示对应的标签页框架，最后刷新该页自身的内容。
-- 入参：tabIndex 标签序号（1 设置 / 2 天赋 / 3 按键 / 4 CVar 设置 / 5 制作按键宏）。
-- 出参：无。
-- 说明：标签页框架存在 P07483180.tabFrames 里，按键页（ShowMacroEditor）和 CVar / 宏助手页由别的文件或本文件后面才建，所以每个都要先判空再调；少了判空，对应模块没加载时切页就会报错。
function WowBuddyDev.SwitchTab(tabIndex)
  for index, tabButton in ipairs(tabButtons) do
    if index == tabIndex then
      tabButton.bg:SetColorTexture(.6, .1, .15, .9)
      tabButton.border:SetColorTexture(.8, .2, .25, 1)
      tabButton:GetFontString():SetTextColor(1, 1, 1, 1)
      if WowBuddyDev.tabFrames[index] then
        WowBuddyDev.tabFrames[index]:Show()
      end
    else
      tabButton.bg:SetColorTexture(0, 0, 0, 0)
      tabButton.border:SetColorTexture(0, 0, 0, 0)
      tabButton:GetFontString():SetTextColor(.9, .75, .35, 1)
      if WowBuddyDev.tabFrames[index] then
        WowBuddyDev.tabFrames[index]:Hide()
      end
    end
  end
  if tabIndex == 2 and WowBuddyDev.ShowTalentPicker then
    WowBuddyDev.ShowTalentPicker()
  end
  if tabIndex == 3 and ShowMacroEditor then
    ShowMacroEditor()
  end
  if tabIndex == 4 and WowBuddyDev.RefreshCVarPanel then
    WowBuddyDev.RefreshCVarPanel()
  end
  if tabIndex == 5 and WowBuddyDev.RefreshMacroHelper then
    WowBuddyDev.RefreshMacroHelper()
  end
end
local tabLabels = { WowBuddyDev.L("设置"), WowBuddyDev.L("天赋"), WowBuddyDev.L("按键"), "CVar设置", "制作按键宏" }
local tabWidth = 92
local tabGap = 10
local tabRowWidth = #tabLabels * tabWidth + (#tabLabels - 1) * tabGap
local tabRowLeft = (540 - tabRowWidth) / 2
for tabIndex, tabLabel in ipairs(tabLabels) do
  local tabButton = WowBuddyDev.CreateStyledButton(mainWindow, tabLabel, tabWidth, 24)
  tabButton:SetPoint("TOPLEFT", mainWindow, "TOPLEFT", tabRowLeft + (tabIndex - 1) * (tabWidth + tabGap), -40)
  local capturedTabIndex = tabIndex
  tabButton:SetScript("OnClick", function()
    WowBuddyDev.SwitchTab(capturedTabIndex)
  end)
  tabButtons[tabIndex] = tabButton
end
local closeButton = WowBuddyDev.CreateStyledButton(mainWindow, "关 闭", 80, 24)
closeButton:SetPoint("BOTTOM", mainWindow, "BOTTOM", 0, 12)
closeButton:SetScript("OnClick", function()
  mainWindow:Hide()
end)
WowBuddyDev.configFrame = CreateFrame("Frame", nil, mainWindow)
WowBuddyDev.configFrame:SetSize(520, 444)
WowBuddyDev.configFrame:SetPoint("TOPLEFT", mainWindow, "TOPLEFT", 10, -76)
WowBuddyDev.configFrame:SetPoint("BOTTOMRIGHT", mainWindow, "BOTTOMRIGHT", -10, 40)
WowBuddyDev.configFrame:Hide()
local topFrameLevel = 100
WowBuddyDev.mklFrames = { WowBuddyDev.configFrame }
-- 功能：把指定框架抬到最上面（FrameLevel 逐个递增）。
-- 入参：frameToRaise 要抬起的框架。
-- 出参：无。
-- 说明：FrameLevel 只增不减，保证后开的宏编辑窗口一定压在前一个之上；起点 100，避开主窗口自己的层级。
function WowBuddyDev.BringToFront(frameToRaise)
  topFrameLevel = topFrameLevel + 1
  frameToRaise:SetFrameLevel(topFrameLevel)
end
local pendingLoadout = nil
-- 功能：把一段天赋导入字符串写进当前专精的活动配置，并暂存起来等玩家点【应用改动】提交。
-- 入参：importString 天赋字符串；loadoutName 预设名，用来拼配置名「WowBuddyDev_预设名」。
-- 出参：true 导入成功（已暂存）；false 表示战斗锁定、当前不可编辑天赋、天赋框架加载失败、字符串无效 / 版本不符 / 专精不符 / 天赋树哈希过期，或导入本身报错，具体原因都已 print。
-- 说明：表头校验按 C_Traits.GetLoadoutSerializationVersion 比版本号，再比专精 ID；天赋树哈希全部为 0 时表示导出端没带哈希，这种情况跳过比对（否则会误判成「字符串已过期」）。导入只改活动配置，真正落库要玩家在天赋页点【应用改动】。
local function importTalentLoadout(importString, loadoutName)
  if InCombatLockdown() then
    print(WowBuddyDev.L("|cffff0000[MKK]|r 战斗中无法修改天赋"))
    return false
  end
  local canEditTalents, editError = C_ClassTalents.CanEditTalents()
  if not canEditTalents then
    print(WowBuddyDev.L("|cffff0000[MKK]|r 当前无法编辑天赋: ") .. tostring(editError))
    return false
  end
  if not C_AddOns.IsAddOnLoaded("Blizzard_PlayerSpells") then
    local isAddonLoaded, v27 = C_AddOns.LoadAddOn("Blizzard_PlayerSpells")
    if not isAddonLoaded then
      print(WowBuddyDev.L("|cffff0000[MKK]|r 无法加载天赋框架"))
      return false
    end
  end
  local importName = "WowBuddyDev_" .. WowBuddyDev.L(loadoutName)
  local isImportOk, importError = pcall(function()
    local importMixin = ClassTalentImportExportMixin
    local importStream = ExportUtil.MakeImportDataStream(importString)
    local hasValidHeader, serializationVersion, headerSpecID, treeHash = importMixin:ReadLoadoutHeader(importStream)
    if not hasValidHeader then
      error(WowBuddyDev.L("天赋字符串无效"), 0)
    end
    if serializationVersion ~= C_Traits.GetLoadoutSerializationVersion() then
      error(WowBuddyDev.L("天赋字符串版本不兼容，请重新导出"), 0)
    end
    local v34, v35, specID = WowBuddyDev.GetPlayerClassSpec()
    if headerSpecID ~= specID then
      error(WowBuddyDev.L("天赋字符串不属于当前专精"), 0)
    end
    local activeConfigID = C_ClassTalents.GetActiveConfigID()
    local traitTreeID = C_ClassTalents.GetTraitTreeForSpec(specID)
    local isTreeHashEmpty = true
    for index4, hashValue in ipairs(treeHash) do
      if hashValue ~= 0 then
        isTreeHashEmpty = false
        break
      end
    end
    if not isTreeHashEmpty then
      local currentTreeHash = C_Traits.GetTreeHash(traitTreeID)
      for hashIndex, expectedHash in ipairs(treeHash) do
        if currentTreeHash[hashIndex] ~= expectedHash then
          error(WowBuddyDev.L("天赋树已变更，字符串已过期"), 0)
        end
      end
    end
    local loadoutContent = importMixin:ReadLoadoutContent(importStream, traitTreeID)
    local entryInfo = importMixin:ConvertToImportLoadoutEntryInfo(activeConfigID, traitTreeID, loadoutContent)
    local isLoadoutImported, loadoutImportError = C_ClassTalents.ImportLoadout(activeConfigID, entryInfo, importName, importString)
    if not isLoadoutImported then
      error(tostring(loadoutImportError or WowBuddyDev.L("未知错误")), 0)
    end
  end)
  if not isImportOk then
    print(WowBuddyDev.L("|cffff0000[MKK]|r 导入失败: ") .. tostring(importError))
    return false
  end
  pendingLoadout = { configID = C_ClassTalents.GetActiveConfigID(), name = loadoutName }
  return true
end
WowBuddyDev.talentPickerFrame = CreateFrame("Frame", nil, mainWindow)
WowBuddyDev.talentPickerFrame:SetSize(520, 444)
WowBuddyDev.talentPickerFrame:SetPoint("TOPLEFT", mainWindow, "TOPLEFT", 10, -76)
WowBuddyDev.talentPickerFrame:SetPoint("BOTTOMRIGHT", mainWindow, "BOTTOMRIGHT", -10, 40)
WowBuddyDev.talentPickerFrame:Hide()
local talentStatusText = WowBuddyDev.talentPickerFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
talentStatusText:SetPoint("TOP", WowBuddyDev.talentPickerFrame, "TOP", 0, -14)
talentStatusText:SetText("")
talentStatusText:SetTextColor(.7, .7, .7, 1)
local loadoutButtonContainer = CreateFrame("Frame", nil, WowBuddyDev.talentPickerFrame)
loadoutButtonContainer:SetPoint("TOPLEFT", WowBuddyDev.talentPickerFrame, "TOPLEFT", 20, -50)
loadoutButtonContainer:SetPoint("BOTTOMRIGHT", WowBuddyDev.talentPickerFrame, "BOTTOMRIGHT", -20, 50)
local loadoutButtons = {}
-- 功能：重建天赋页的预设按钮：按当前专精取预设天赋，两列排布，每行两个按钮。
-- 入参：无。
-- 出参：无。
-- 说明：每次先隐藏并 SetParent(nil) 解绑旧按钮再清表重建，否则反复切页会留下点不动的残影。当前专精没有预设时在标题行提示。按钮点击只做导入 + 暂存，不直接生效。
function WowBuddyDev.ShowTalentPicker()
  for index6, oldButton in ipairs(loadoutButtons) do
    oldButton:Hide()
    oldButton:SetParent(nil)
  end
  wipe(loadoutButtons)
  local v48, v49, specID = WowBuddyDev.GetPlayerClassSpec()
  local presetLoadouts = {}
  if specID and (WowBuddyDev.classes[specID] and WowBuddyDev.classes[specID].talentLoadouts) then
    presetLoadouts = WowBuddyDev.classes[specID].talentLoadouts
  end
  if #presetLoadouts == 0 then
    talentStatusText:SetText(WowBuddyDev.L("当前专精暂无预设天赋"))
  else
    talentStatusText:SetText("")
  end
  local firstColumnX = 20
  local secondColumnX = 260
  local firstRowY = -20
  local rowStep = 34
  local columnIndex = 0
  local rowIndex = 0
  for index7, loadout in ipairs(presetLoadouts) do
    local loadoutButton = WowBuddyDev.CreateStyledButton(loadoutButtonContainer, loadout.name, 220, 28)
    local buttonX = columnIndex == 0 and firstColumnX or secondColumnX
    local buttonY = firstRowY - rowIndex * rowStep
    loadoutButton:SetPoint("TOPLEFT", loadoutButtonContainer, "TOPLEFT", buttonX, buttonY)
    loadoutButton:SetScript("OnClick", function()
      local isImported = importTalentLoadout(loadout.importString, loadout.name)
      if isImported then
        talentStatusText:SetText(WowBuddyDev.L("已暂存：「") .. WowBuddyDev.L(loadout.name) .. WowBuddyDev.L("」，请点击下方【应用改动】"))
        talentStatusText:SetTextColor(0, 1, .5, 1)
      end
    end)
    table.insert(loadoutButtons, loadoutButton)
    columnIndex = columnIndex + 1
    if columnIndex >= 2 then
      columnIndex = 0
      rowIndex = rowIndex + 1
    end
  end
end
local applyTalentButton = WowBuddyDev.CreateStyledButton(WowBuddyDev.talentPickerFrame, "应用改动", 100, 26)
applyTalentButton:SetPoint("BOTTOM", WowBuddyDev.talentPickerFrame, "BOTTOM", 0, 16)
applyTalentButton:SetScript("OnClick", function()
  if pendingLoadout then
    C_Traits.CommitConfig(pendingLoadout.configID)
    pendingLoadout = nil
    talentStatusText:SetText("")
    talentStatusText:SetTextColor(.7, .7, .7, 1)
  else
    print(WowBuddyDev.L("|cffff0000[MKK]|r 没有待应用的天赋"))
  end
end)
local keyCaptureOverlay = CreateFrame("Frame", nil, UIParent)
keyCaptureOverlay:SetAllPoints()
keyCaptureOverlay:EnableKeyboard(true)
keyCaptureOverlay:EnableMouse(true)
keyCaptureOverlay:SetPropagateKeyboardInput(false)
keyCaptureOverlay:Hide()
keyCaptureOverlay:SetFrameStrata("FULLSCREEN_DIALOG")
local captureHintText = keyCaptureOverlay:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
captureHintText:SetPoint("CENTER", keyCaptureOverlay, "CENTER", 0, 0)
captureHintText:SetText(WowBuddyDev.L("请按下要绑定的按键（ESC取消）"))
local modifierKeys = {
  SHIFT = true,
  LSHIFT = true,
  RSHIFT = true,
  CTRL = true,
  LCTRL = true,
  RCTRL = true,
  ALT = true,
  LALT = true,
  RALT = true,
}
-- 功能：把当前按住的修饰键和目标键拼成「ALT-CTRL-SHIFT-主键」形式的按键串。
-- 入参：keyName 主键名，如 "1"、"F1"、"BUTTON2"。
-- 出参：拼接后的按键串。
-- 说明：顺序固定 ALT→CTRL→SHIFT，和暴雪绑定串的写法一致；顺序写错会绑不上键。返回的串同时用于查冲突和写绑定，两边必须同一个格式。
local function buildKeyCombo(keyName)
  local comboParts = {}
  if IsAltKeyDown() then
    comboParts[#comboParts + 1] = "ALT"
  end
  if IsControlKeyDown() then
    comboParts[#comboParts + 1] = "CTRL"
  end
  if IsShiftKeyDown() then
    comboParts[#comboParts + 1] = "SHIFT"
  end
  comboParts[#comboParts + 1] = keyName
  return table.concat(comboParts, "-")
end
-- 功能：判断某个按键是否已被插件自己的动作源或团队选人占用，占用时返回可读的占用说明。
-- 入参：keyName 按键串。
-- 出参：占用说明字符串；没被占用返回 nil。
-- 说明：GetControlBindingConflict 返回类型 + 取值两个；action 类型再去 P07483180.ACTION_LABELS 换成中文名，查不到就直接用原始值，避免拿 nil 去格式化。
local function getKeyConflictText(keyName)
  local conflictType, conflictValue = WowBuddyDev.GetControlBindingConflict(keyName)
  if conflictType == "action" then
    local actionLabel = ((WowBuddyDev.ACTION_LABELS or {}))[conflictValue] or conflictValue
    return string.format(WowBuddyDev.L("动作源「%s」"), WowBuddyDev.L(actionLabel))
  elseif conflictType == "raid" then
    return string.format(WowBuddyDev.L("团队选人 raid%d"), conflictValue)
  end
end
-- 功能：把按下的按键写到当前正在等的那个开关绑定上（总开关 / 爆发 / 群体），并刷新按钮文字。
-- 入参：keyName 按键串。
-- 出参：true 写入成功；false 表示这个键被别的功能占用，提示已经显示在捕获框上。
-- 说明：waitingForKey 决定这次写哪个开关，三种都不是就什么都不做、直接返回 true，不能把绑定写串。冲突时把捕获框的提示整串染红，方便玩家看清为什么没生效。
local function applyCapturedKey(keyName)
  local conflictText = getKeyConflictText(keyName)
  if conflictText then
    captureHintText:SetText("|cffff5555" .. string.format(WowBuddyDev.L("按键 %s 已被%s占用，无法设置。\n请换一个按键（ESC取消）"), WowBuddyDev.GetKeyDisplayText(keyName), conflictText) .. "|r")
    return false
  end
  if WowBuddyDev.waitingForKey == "master" then
    WowBuddyDev.DB.masterKey = keyName
    if WowBuddyDev.configFrame.masterUpdate then
      WowBuddyDev.configFrame.masterUpdate()
    end
  elseif WowBuddyDev.waitingForKey == "burst" then
    WowBuddyDev.DB.burstKey = keyName
    if WowBuddyDev.configFrame.burstUpdate then
      WowBuddyDev.configFrame.burstUpdate()
    end
  elseif WowBuddyDev.waitingForKey == "aoe" then
    WowBuddyDev.DB.aoeKey = keyName
    if WowBuddyDev.configFrame.aoeUpdate then
      WowBuddyDev.configFrame.aoeUpdate()
    end
  end
  return true
end
keyCaptureOverlay:SetScript("OnKeyDown", function(self, event)
  if event == "ESCAPE" then
    WowBuddyDev.waitingForKey = nil
    self:Hide()
    return
  end
  if modifierKeys[event] then
    return
  end
  local keyCombo = buildKeyCombo(event)
  if not applyCapturedKey(keyCombo) then
    return
  end
  WowBuddyDev.waitingForKey = nil
  self:Hide()
end)
keyCaptureOverlay:SetScript("OnMouseDown", function(self, mouseButton)
  if mouseButton == "LeftButton" then
    return
  end
  local buttonNumber = mouseButton == "RightButton" and "2" or mouseButton == "MiddleButton" and "3" or mouseButton:match("(%d+)") or "1"
  local keyCombo = buildKeyCombo("BUTTON" .. buttonNumber)
  if not applyCapturedKey(keyCombo) then
    return
  end
  WowBuddyDev.waitingForKey = nil
  self:Hide()
end)
-- 功能：在父框架里画一条 1 像素高的水平分隔线。
-- 入参：parentFrame 父框架；yOffset 纵向偏移。
-- 出参：分隔线纹理。
-- 说明：左右各留 20 像素，和设置页其它控件的缩进对齐。
local function createSeparator(parentFrame, yOffset)
  local separatorLine = parentFrame:CreateTexture(nil, "ARTWORK")
  separatorLine:SetHeight(1)
  separatorLine:SetPoint("TOPLEFT", parentFrame, "TOPLEFT", 20, yOffset)
  separatorLine:SetPoint("TOPRIGHT", parentFrame, "TOPRIGHT", -20, yOffset)
  separatorLine:SetColorTexture(.3, .3, .35, 1)
  return separatorLine
end
-- 功能：建一行「说明文字 + 按键按钮」；左键点按钮进入按键捕获，右键清除绑定。
-- 入参：parentFrame 父框架；labelText 说明文字；bindingAction 绑定项（master / burst / aoe）；yOffset 纵向偏移。
-- 出参：按键按钮、刷新该按钮文字的函数（两个值）。
-- 说明：按钮上挂 controlConflict 字段，鼠标提示据此说明被谁占用；右键清除后必须调刷新函数，否则按钮上还留着旧按键。返回的刷新函数由外面存进 P07483180.configFrame.masterUpdate / burstUpdate / aoeUpdate，切页时会再调。
local function createKeyBindingRow(parentFrame, labelText, bindingAction, yOffset)
  local labelFontString = parentFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  labelFontString:SetPoint("TOPLEFT", parentFrame, "TOPLEFT", 24, yOffset)
  labelFontString:SetText(labelText)
  labelFontString:SetJustifyH("LEFT")
  labelFontString:SetWidth(100)
  local keyButton = WowBuddyDev.CreateStyledButton(parentFrame, "", 120, 24)
  keyButton:SetPoint("LEFT", labelFontString, "RIGHT", 10, 0)
  -- 功能：重新读当前绑定，刷新本行按键按钮的文字和冲突标记。
  -- 入参：无。
  -- 出参：无。
  -- 说明：闭包在 createKeyBindingRow 里，直接读该行的 bindingAction 决定取总开关 / 爆发 / 群体哪个绑定；被占用时整串染红，未占用时用 GetKeyDisplayText 取显示名。
  local function refreshKeyButtonText()
    local currentKey
    if bindingAction == "master" then
      currentKey = WowBuddyDev.DB.masterKey
    elseif bindingAction == "burst" then
      currentKey = WowBuddyDev.DB.burstKey
    elseif bindingAction == "aoe" then
      currentKey = WowBuddyDev.DB.aoeKey
    end
    keyButton.controlConflict = getKeyConflictText(currentKey)
    local keyDisplayText = WowBuddyDev.GetKeyDisplayText(currentKey)
    keyButton:SetText(keyButton.controlConflict and "|cffff5555" .. keyDisplayText .. "|r" or keyDisplayText)
  end
  keyButton:HookScript("OnEnter", function(self)
    if not self.controlConflict then
      return
    end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(WowBuddyDev.L("快捷键占用"))
    GameTooltip:AddLine(string.format(WowBuddyDev.L("此快捷键已被%s占用，暂不切换开关。\n左键重新设置，右键清除；仍可使用界面按钮。"), self.controlConflict), 1, .35, .35, true)
    GameTooltip:Show()
  end)
  keyButton:HookScript("OnLeave", function(self)
    if GameTooltip:IsOwned(self) then
      GameTooltip:Hide()
    end
  end)
  keyButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  keyButton:SetScript("OnClick", function(self, mouseButton)
    if mouseButton == "RightButton" then
      if bindingAction == "master" then
        WowBuddyDev.DB.masterKey = nil
      elseif bindingAction == "burst" then
        WowBuddyDev.DB.burstKey = nil
      elseif bindingAction == "aoe" then
        WowBuddyDev.DB.aoeKey = nil
      end
      refreshKeyButtonText()
      -- 这三个键由DB保存并由PixelBar轮询；未修改游戏绑定表，无需SaveBindings。
    else
      WowBuddyDev.waitingForKey = bindingAction
      captureHintText:SetText(WowBuddyDev.L("请按下要绑定的按键（ESC取消）"))
      keyCaptureOverlay:Show()
    end
  end)
  refreshKeyButtonText()
  return keyButton, refreshKeyButtonText
end
WowBuddyDev.InitDB()
local v66, updateMasterKeyText = createKeyBindingRow(WowBuddyDev.configFrame, WowBuddyDev.L("总开关:"), "master", -58)
local burstKeyButton, updateBurstKeyText = createKeyBindingRow(WowBuddyDev.configFrame, WowBuddyDev.L("爆发开关:"), "burst", -93)
local v70, updateAoeKeyText = createKeyBindingRow(WowBuddyDev.configFrame, WowBuddyDev.L("模式切换:"), "aoe", -128)
WowBuddyDev.configFrame.masterUpdate = updateMasterKeyText
WowBuddyDev.configFrame.burstUpdate = updateBurstKeyText
WowBuddyDev.configFrame.aoeUpdate = updateAoeKeyText
-- 功能：刷新三个开关（总开关 / 爆发 / 模式切换）按键按钮上的文字。
-- 入参：无。
-- 出参：无。
-- 说明：三个刷新函数由 createKeyBindingRow 返回，创建时就存进了 P07483180.configFrame.masterUpdate / burstUpdate / aoeUpdate，本函数只是把它们一起调一次。
function WowBuddyDev.RefreshControlKeySettingUI()
  updateMasterKeyText()
  updateBurstKeyText()
  updateAoeKeyText()
end
local burstAutoCloseEditBox = CreateFrame("EditBox", nil, WowBuddyDev.configFrame, "InputBoxTemplate")
burstAutoCloseEditBox:SetSize(48, 24)
burstAutoCloseEditBox:SetPoint("LEFT", burstKeyButton, "RIGHT", 10, 0)
burstAutoCloseEditBox:SetAutoFocus(false)
burstAutoCloseEditBox:SetNumeric(true)
burstAutoCloseEditBox:SetMaxLetters(6)
burstAutoCloseEditBox:SetJustifyH("CENTER")
burstAutoCloseEditBox:SetText("0")
-- 功能：把当前专精的爆发自动关闭秒数读进输入框。
-- 入参：无。
-- 出参：无。
-- 说明：切页、保存失败、按 ESC 都要回填一次，不能让输入框里留着没保存成功的值。
local function refreshBurstAutoCloseEditBox()
  local seconds = WowBuddyDev.GetBurstAutoCloseSeconds()
  burstAutoCloseEditBox:SetText(tostring(seconds))
end
-- 功能：把输入框里的秒数保存到当前专精，并把规范化后的结果回填。
-- 入参：无（秒数取自输入框自身）。
-- 出参：无。
-- 说明：专精识别失败时不保存（这个设置按专精区分），随即回填旧值并取消焦点，提示已经 print 过了。保存成功时打印实际生效的秒数和专精名。
local function saveBurstAutoCloseSeconds()
  local isSaved, savedSeconds, specName = WowBuddyDev.SaveBurstAutoCloseSeconds(burstAutoCloseEditBox:GetText())
  if not isSaved then
    print(WowBuddyDev.L("|cffff0000[WowBuddyDev]|r 当前专精识别失败，设置未保存"))
    refreshBurstAutoCloseEditBox()
    burstAutoCloseEditBox:ClearFocus()
    return
  end
  burstAutoCloseEditBox:SetText(tostring(savedSeconds))
  burstAutoCloseEditBox:ClearFocus()
  print(WowBuddyDev.L("|cff00ff88[WowBuddyDev]|r 爆发自动关闭设置已保存：") .. WowBuddyDev.L(specName) .. " · " .. tostring(savedSeconds) .. WowBuddyDev.L(" 秒"))
end
burstAutoCloseEditBox:SetScript("OnEnterPressed", saveBurstAutoCloseSeconds)
burstAutoCloseEditBox:SetScript("OnEscapePressed", function(self)
  refreshBurstAutoCloseEditBox()
  self:ClearFocus()
end)
local burstSecondsSuffixText = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
burstSecondsSuffixText:SetPoint("LEFT", burstAutoCloseEditBox, "RIGHT", 6, 0)
burstSecondsSuffixText:SetText(WowBuddyDev.L("秒后自动关闭爆发"))
local burstSaveButton = WowBuddyDev.CreateStyledButton(WowBuddyDev.configFrame, WowBuddyDev.L("保存"), 52, 22)
burstSaveButton:SetPoint("LEFT", burstSecondsSuffixText, "RIGHT", 8, 0)
burstSaveButton:SetScript("OnClick", saveBurstAutoCloseSeconds)
refreshBurstAutoCloseEditBox()
local classSpecText = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
classSpecText:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 24, -163)
classSpecText:SetText(WowBuddyDev.L("职业: 检测中..."))
classSpecText:SetTextColor(.65, .65, .65, 1)
-- 功能：刷新「职业: xxx    天赋: xxx」这行提示文字。
-- 入参：无。
-- 出参：无。
-- 说明：读 P07483180.DB.currentClass / currentSpecName，缺值时分别退回 "UNKNOWN" 和「未知」，保证任何加载顺序下这行字都不会是 nil。
local function refreshClassSpecText()
  local currentClass = WowBuddyDev.DB.currentClass or "UNKNOWN"
  local currentSpecName = WowBuddyDev.DB.currentSpecName or WowBuddyDev.L("未知")
  classSpecText:SetText(WowBuddyDev.L("职业: ") .. currentClass .. WowBuddyDev.L("    天赋: ") .. currentSpecName)
end
-- 功能：刷新「职业 / 天赋」提示行和爆发自动关闭秒数输入框。
-- 入参：无。
-- 出参：无。
-- 说明：设置页每次显示（OnShow）都会调用，保证换专精后看到的是当前专精的值。
function WowBuddyDev.RefreshBurstAutoCloseSettingUI()
  refreshClassSpecText()
  refreshBurstAutoCloseEditBox()
end
createSeparator(WowBuddyDev.configFrame, -185)
local autoTargetCheck = CreateFrame("CheckButton", nil, WowBuddyDev.configFrame, "UICheckButtonTemplate")
autoTargetCheck:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 20, -199)
-- 功能：把「自动寻怪」勾选框同步成当前设置并解除禁用。
-- 入参：无。
-- 出参：无。
-- 说明：同时挂在 P07483180.RefreshAutoTargetSettingUI 上，别处改了这个开关也能同步过来；初始化时也要调一次。
local function refreshAutoTargetCheck()
  autoTargetCheck:SetChecked(WowBuddyDev.GetAutoTargetEnabled())
  autoTargetCheck:Enable()
end
WowBuddyDev.RefreshAutoTargetSettingUI = refreshAutoTargetCheck
autoTargetCheck:SetScript("OnClick", function(self)
  WowBuddyDev.SetAutoTargetEnabled(self:GetChecked() and true or false)
end)
refreshAutoTargetCheck()
local autoTargetLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
autoTargetLabel:SetPoint("LEFT", autoTargetCheck, "RIGHT", 4, 0)
autoTargetLabel:SetText(WowBuddyDev.L("自动寻怪"))
local debugInfoCheck = CreateFrame("CheckButton", nil, WowBuddyDev.configFrame, "UICheckButtonTemplate")
debugInfoCheck:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 20, -229)
debugInfoCheck:SetScript("OnClick", function(self)
  if self:GetChecked() then
    WowBuddyDev.debugFrame:Show()
  else
    WowBuddyDev.debugFrame:Hide()
  end
  if WowBuddyDev.RefreshPanelDebugIcons then
    WowBuddyDev.RefreshPanelDebugIcons()
  end
end)
debugInfoCheck:SetChecked(false)
local debugInfoLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
debugInfoLabel:SetPoint("LEFT", debugInfoCheck, "RIGHT", 4, 0)
debugInfoLabel:SetText(WowBuddyDev.L("显示调试信息"))
local logoTextCheck = CreateFrame("CheckButton", nil, WowBuddyDev.configFrame, "UICheckButtonTemplate")
logoTextCheck:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 20, -259)
logoTextCheck:SetScript("OnClick", function(self)
  WowBuddyDev.DB.showLogoText = self:GetChecked()
  if WowBuddyDev.RefreshStateLogo then
    WowBuddyDev.RefreshStateLogo()
  end
end)
local logoTextLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
logoTextLabel:SetPoint("LEFT", logoTextCheck, "RIGHT", 4, 0)
logoTextLabel:SetText(WowBuddyDev.L("显示状态文字"))
local disableTextAlertCheck = CreateFrame("CheckButton", nil, WowBuddyDev.configFrame, "UICheckButtonTemplate")
disableTextAlertCheck:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 260, -199)
disableTextAlertCheck:SetScript("OnClick", function(self)
  WowBuddyDev.DB.disableTextAlert = self:GetChecked() or false
end)
local disableTextAlertLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
disableTextAlertLabel:SetPoint("LEFT", disableTextAlertCheck, "RIGHT", 4, 0)
disableTextAlertLabel:SetText(WowBuddyDev.L("禁用文字提示"))
local disableSoundCheck = CreateFrame("CheckButton", nil, WowBuddyDev.configFrame, "UICheckButtonTemplate")
disableSoundCheck:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 260, -229)
disableSoundCheck:SetScript("OnClick", function(self)
  WowBuddyDev.DB.disableSound = self:GetChecked() or false
end)
local disableSoundLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
disableSoundLabel:SetPoint("LEFT", disableSoundCheck, "RIGHT", 4, 0)
disableSoundLabel:SetText(WowBuddyDev.L("禁用音效"))
local panelIconsCheck = CreateFrame("CheckButton", nil, WowBuddyDev.configFrame, "UICheckButtonTemplate")
panelIconsCheck:SetPoint("TOPLEFT", WowBuddyDev.configFrame, "TOPLEFT", 260, -259)
panelIconsCheck:SetScript("OnClick", function(self)
  WowBuddyDev.DB.v2PanelIcons = self:GetChecked() or false
  print(WowBuddyDev.L("v2 面板图标显示已切换，/reload 后生效"))
end)
panelIconsCheck:Disable()
local panelIconsLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
panelIconsLabel:SetPoint("LEFT", panelIconsCheck, "RIGHT", 4, 0)
panelIconsLabel:SetText(WowBuddyDev.L("显示图标"))
panelIconsLabel:SetTextColor(.5, .5, .5, 1)
WowBuddyDev.configFrame:SetScript("OnShow", function()
  WowBuddyDev.RefreshBurstAutoCloseSettingUI()
  if WowBuddyDev.configFrame.masterUpdate then
    WowBuddyDev.configFrame.masterUpdate()
  end
  if WowBuddyDev.configFrame.burstUpdate then
    WowBuddyDev.configFrame.burstUpdate()
  end
  if WowBuddyDev.configFrame.aoeUpdate then
    WowBuddyDev.configFrame.aoeUpdate()
  end
  refreshAutoTargetCheck()
  debugInfoCheck:SetChecked(WowBuddyDev.debugFrame:IsShown())
  disableTextAlertCheck:SetChecked(WowBuddyDev.DB.disableTextAlert)
  disableSoundCheck:SetChecked(WowBuddyDev.DB.disableSound)
  panelIconsCheck:SetChecked(WowBuddyDev.DB.v2PanelIcons or false)
  logoTextCheck:SetChecked(WowBuddyDev.DB.showLogoText ~= false)
  if WowBuddyDev.UpdateLogoToggleBtn then
    WowBuddyDev.UpdateLogoToggleBtn()
  end
end)
createSeparator(WowBuddyDev.configFrame, -323)
-- 功能：在设置页建一行宏信息（宏名、绑定按键、编辑按钮）；点编辑弹出多行编辑框改宏内容。
-- 入参：parentFrame 父框架；actionKey 动作键（同时是滚动框全局名的后缀）；bindingKey 绑定按键文本；macroLabel 宏名；offsetX / offsetY 相对父框架的位置。
-- 出参：整行的框架。
-- 说明：编辑窗口的滚动条是按全局名找的（WowBuddyDevScroll + actionKey），所以滚动框和编辑框都必须命名，否则拿不到 ScrollBar 就没法调样式。保存顺序是先写用户宏、再重建安全按钮、最后 SaveBindings，顺序反了按键会指向旧宏；整个按钮战斗中禁用。
function WowBuddyDev.CreateMacroRow(parentFrame, actionKey, bindingKey, macroLabel, offsetX, offsetY)
  local rowFrame = CreateFrame("Frame", nil, parentFrame)
  rowFrame:SetSize(240, 22)
  rowFrame:SetPoint("TOPLEFT", parentFrame, "TOPLEFT", offsetX, offsetY)
  local labelText = rowFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  labelText:SetPoint("LEFT", rowFrame, "LEFT", 0, 0)
  labelText:SetText(macroLabel)
  labelText:SetJustifyH("LEFT")
  labelText:SetWidth(110)
  local keyText = rowFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  keyText:SetPoint("LEFT", labelText, "RIGHT", 6, 0)
  keyText:SetText("|cffffcc00" .. bindingKey .. "|r")
  keyText:SetJustifyH("LEFT")
  keyText:SetWidth(70)
  local editButton = WowBuddyDev.CreateStyledButton(rowFrame, WowBuddyDev.L("编辑"), 50, 20)
  editButton:SetPoint("LEFT", keyText, "RIGHT", 4, 0)
  -- 功能：按是否处于战斗锁定，启用 / 禁用宏行的「编辑」按钮。
  -- 入参：无。
  -- 出参：无。
  -- 说明：宏编辑最终要重建安全按钮，战斗中做不了，所以进战斗必须禁用；该行同时监听 PLAYER_REGEN_DISABLED 和 PLAYER_REGEN_ENABLED 两个事件来调它。
  local function updateEditButtonEnabled()
    if InCombatLockdown() then
      editButton:Disable()
    else
      editButton:Enable()
    end
  end
  rowFrame:RegisterEvent("PLAYER_REGEN_DISABLED")
  rowFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
  rowFrame:SetScript("OnEvent", updateEditButtonEnabled)
  updateEditButtonEnabled()
  editButton:SetScript("OnClick", function()
    if InCombatLockdown() then
      return
    end
    local editorFrame = CreateFrame("Frame", nil, UIParent, BackdropTemplateMixin and "BackdropTemplate")
    editorFrame:SetSize(440, 280)
    editorFrame:SetPoint("CENTER")
    editorFrame:SetBackdrop({
      bgFile = "Interface\\Buttons\\WHITE8X8",
      edgeFile = "Interface\\Buttons\\WHITE8X8",
      tile = false,
      tileSize = 0,
      edgeSize = 1,
      insets = { left = 0, right = 0, top = 0, bottom = 0 },
    })
    editorFrame:SetBackdropColor(.08, .08, .09, 1)
    editorFrame:SetBackdropBorderColor(.22, .22, .24, 1)
    editorFrame:SetAlpha(1)
    editorFrame:EnableMouse(true)
    editorFrame:SetMovable(true)
    editorFrame:RegisterForDrag("LeftButton")
    editorFrame:SetScript("OnDragStart", editorFrame.StartMoving)
    editorFrame:SetScript("OnDragStop", editorFrame.StopMovingOrSizing)
    editorFrame:SetFrameStrata("FULLSCREEN_DIALOG")
    editorFrame:Show()
    WowBuddyDev.BringToFront(editorFrame)
    local editorTitleText = editorFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
    editorTitleText:SetPoint("TOP", editorFrame, "TOP", 0, -18)
    editorTitleText:SetText(WowBuddyDev.L("编辑宏: ") .. macroLabel .. " (" .. bindingKey .. ")")
    local editorScrollFrame = CreateFrame("ScrollFrame", "WowBuddyDevScroll" .. actionKey, editorFrame, "UIPanelScrollFrameTemplate")
    editorScrollFrame:SetSize(400, 130)
    editorScrollFrame:SetPoint("TOP", editorTitleText, "BOTTOM", 0, -20)
    local editorScrollBar = _G[editorScrollFrame:GetName() .. "ScrollBar"]
    if editorScrollBar then
      local editorScrollUpButton = _G[editorScrollBar:GetName() .. "ScrollUpButton"]
      local editorScrollDownButton = _G[editorScrollBar:GetName() .. "ScrollDownButton"]
      if editorScrollUpButton then
        editorScrollUpButton:SetSize(16, 16)
        editorScrollUpButton:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollUpButton-Up")
      end
      if editorScrollDownButton then
        editorScrollDownButton:SetSize(16, 16)
        editorScrollDownButton:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
      end
    end
    local macroEditBox = CreateFrame("EditBox", nil, editorScrollFrame)
    macroEditBox:SetSize(380, 130)
    macroEditBox:SetMultiLine(true)
    macroEditBox:SetAutoFocus(true)
    macroEditBox:SetTextInsets(6, 6, 6, 6)
    macroEditBox:SetFontObject("ChatFontNormal")
    local hasUserMacro, macroText = WowBuddyDev.GetUserMacro(actionKey)
    if not hasUserMacro then
      macroText = WowBuddyDev.GetDefaultMacro(actionKey)
    end
    macroEditBox:SetText(macroText)
    local editBoxBackground = macroEditBox:CreateTexture(nil, "BACKGROUND")
    editBoxBackground:SetAllPoints()
    editBoxBackground:SetColorTexture(.05, .05, .06, 1)
    editorScrollFrame:SetScrollChild(macroEditBox)
    editorScrollFrame:EnableMouseWheel(true)
    editorScrollFrame:SetScript("OnMouseWheel", function(self, wheelDelta)
      local wheelScrollBar = _G[self:GetName() .. "ScrollBar"]
      if wheelScrollBar then
        local scrollStep = -wheelDelta * 20
        wheelScrollBar:SetValue(wheelScrollBar:GetValue() + scrollStep)
      end
    end)
    local macroSaveButton = WowBuddyDev.CreateStyledButton(editorFrame, WowBuddyDev.L("保存"), 90, 24)
    macroSaveButton:SetPoint("BOTTOMLEFT", editorFrame, "BOTTOMLEFT", 70, 18)
    macroSaveButton:SetScript("OnClick", function()
      if InCombatLockdown() then
        return
      end
      local newMacroText = macroEditBox:GetText() or ""
      if not WowBuddyDev.SaveUserMacro(actionKey, newMacroText) then
        return
      end
      WowBuddyDev.CreateSecureButton(actionKey, bindingKey, newMacroText)
      SaveBindings(GetCurrentBindingSet())
      editorFrame:Hide()
    end)
    local macroCancelButton = WowBuddyDev.CreateStyledButton(editorFrame, WowBuddyDev.L("取消"), 90, 24)
    macroCancelButton:SetPoint("BOTTOMRIGHT", editorFrame, "BOTTOMRIGHT", -70, 18)
    macroCancelButton:SetScript("OnClick", function()
      editorFrame:Hide()
    end)
  end)
  return rowFrame
end
local resetButton = WowBuddyDev.CreateStyledButton(WowBuddyDev.configFrame, "恢复默认设置", 130, 24)
resetButton:SetPoint("BOTTOMLEFT", WowBuddyDev.configFrame, "BOTTOMLEFT", 24, 46)
-- 功能：按是否处于战斗锁定，启用 / 禁用「恢复默认设置」按钮。
-- 入参：无。
-- 出参：无。
-- 说明：恢复默认会重设全部宏和安全按钮，战斗中禁止；同样靠进 / 出战斗事件触发，初始化时先调一次。
local function updateResetButtonEnabled()
  if InCombatLockdown() then
    resetButton:Disable()
  else
    resetButton:Enable()
  end
end
resetButton:RegisterEvent("PLAYER_REGEN_DISABLED")
resetButton:RegisterEvent("PLAYER_REGEN_ENABLED")
resetButton:SetScript("OnEvent", updateResetButtonEnabled)
updateResetButtonEnabled()
resetButton:SetScript("OnClick", function()
  if InCombatLockdown() then
    return
  end
  for actionKey, bindingKey in pairs(WowBuddyDev.ACTION_TO_KEY) do
    WowBuddyDev.ClearUserMacro(actionKey)
    local defaultMacro = WowBuddyDev.GetDefaultMacro(actionKey)
    WowBuddyDev.CreateSecureButton(actionKey, bindingKey, defaultMacro)
  end
  WowBuddyDev.DB.masterKey = nil
  WowBuddyDev.DB.burstKey = nil
  WowBuddyDev.SaveBurstAutoCloseSeconds(0)
  WowBuddyDev.DB.aoeKey = nil
  WowBuddyDev.DB.autoTarget = false
  WowBuddyDev.DB.healerAutoTarget = true
  WowBuddyDev.DB.protectionPaladinAutoTarget = false
  WowBuddyDev.DB.masterSwitch = true
  if WowBuddyDev.UpdateMasterSwitchUI then
    WowBuddyDev.UpdateMasterSwitchUI(true)
  end
  WowBuddyDev.SetBurstSwitch(false)
  if WowBuddyDev.configFrame.masterUpdate then
    WowBuddyDev.configFrame.masterUpdate()
  end
  if WowBuddyDev.configFrame.burstUpdate then
    WowBuddyDev.configFrame.burstUpdate()
  end
  if WowBuddyDev.configFrame.aoeUpdate then
    WowBuddyDev.configFrame.aoeUpdate()
  end
  refreshBurstAutoCloseEditBox()
  refreshAutoTargetCheck()
  debugInfoCheck:SetChecked(WowBuddyDev.debugFrame:IsShown())
  SaveBindings(GetCurrentBindingSet())
end)
local logoLabel = WowBuddyDev.configFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
logoLabel:SetText(WowBuddyDev.L("logo"))
do
  local logoRowWidth = logoLabel:GetStringWidth() + 8 + 176 + 36
  logoLabel:SetPoint("BOTTOMLEFT", WowBuddyDev.configFrame, "BOTTOMLEFT", (520 - logoRowWidth) / 2, 18)
end
-- 功能：建一个 logo 尺寸按钮（小 / 中 / 大），点击后写 P07483180.DB.logoSize 并刷新 logo。
-- 入参：sizeLabel 按钮文字；logoSize 对应字号；offsetX 相对 logo 文字的横向偏移。
-- 出参：按钮。
-- 说明：字号直接写进配置，再由刷新函数按需重画；刷新函数先判空，logo 模块没加载时不会报错。
local function createLogoSizeButton(sizeLabel, logoSize, offsetX)
  local sizeButton = WowBuddyDev.CreateStyledButton(WowBuddyDev.configFrame, sizeLabel, 44, 22)
  sizeButton:SetPoint("LEFT", logoLabel, "RIGHT", offsetX, 0)
  sizeButton:SetScript("OnClick", function()
    WowBuddyDev.DB.logoSize = logoSize
    if WowBuddyDev.RefreshStateLogo then
      WowBuddyDev.RefreshStateLogo()
    end
  end)
  return sizeButton
end
createLogoSizeButton(WowBuddyDev.L("小"), 32, 8)
createLogoSizeButton(WowBuddyDev.L("中"), 48, 56)
createLogoSizeButton(WowBuddyDev.L("大"), 64, 104)
local logoToggleButton = WowBuddyDev.CreateStyledButton(WowBuddyDev.configFrame, "", 44, 22)
logoToggleButton:SetPoint("LEFT", logoLabel, "RIGHT", 152, 0)
-- 功能：按 P07483180.DB.logoHidden 把 logo 显示 / 隐藏按钮上的文字刷成「显示」或「隐藏」。
-- 入参：无。
-- 出参：无。
-- 说明：这个按钮只切显隐、不改尺寸，所以文字要跟着状态走；别处改了 logoHidden 之后也要调它，否则按钮文字和实际状态会对不上。
function WowBuddyDev.UpdateLogoToggleBtn()
  logoToggleButton:SetText(WowBuddyDev.DB.logoHidden and WowBuddyDev.L("显示") or WowBuddyDev.L("隐藏"))
end
logoToggleButton:SetScript("OnClick", function()
  WowBuddyDev.DB.logoHidden = not WowBuddyDev.DB.logoHidden
  if WowBuddyDev.RefreshAllOverlayVisibility then
    WowBuddyDev.RefreshAllOverlayVisibility()
  elseif WowBuddyDev.stateLogo then
    WowBuddyDev.stateLogo:SetShown(not WowBuddyDev.DB.logoHidden)
  end
  WowBuddyDev.UpdateLogoToggleBtn()
end)
WowBuddyDev.UpdateLogoToggleBtn()
local cvarTabFrame = CreateFrame("Frame", nil, mainWindow)
cvarTabFrame:SetSize(520, 444)
cvarTabFrame:SetPoint("TOPLEFT", mainWindow, "TOPLEFT", 10, -76)
cvarTabFrame:SetPoint("BOTTOMRIGHT", mainWindow, "BOTTOMRIGHT", -10, 40)
cvarTabFrame:Hide()
local cvarPanelTitle = cvarTabFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
cvarPanelTitle:SetPoint("TOP", cvarTabFrame, "TOP", 0, -14)
cvarPanelTitle:SetText(WowBuddyDev.L("游戏参数设置"))
cvarPanelTitle:SetTextColor(.7, .7, .7, 1)
local cvarPanelHint = cvarTabFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
cvarPanelHint:SetPoint("TOP", cvarPanelTitle, "BOTTOM", 0, -4)
cvarPanelHint:SetText(WowBuddyDev.L("调整以下参数可优化 WowBuddyDev 的运行效果，修改后立即生效"))
cvarPanelHint:SetTextColor(.5, .5, .5, 1)
cvarPanelHint:SetFont(WowBuddyDev.fontFile, 11, "")
-- 功能：建一行「标题 + 滑条 + 当前值文字」的滑条设置项。
-- 入参：parentFrame 父框架；labelText 标题；minValue / maxValue 取值范围；valueStep 步长；offsetY 纵向偏移。
-- 出参：行框架、滑条、值文字（三个值，调用方一般只留滑条和值文字）。
-- 说明：OptionsSliderTemplate 自带的 Low / High / Text 三个文字全部清空，改用自己画的值文字，免得模板英文和中文标题挤在一起。
local function createSliderRow(parentFrame, labelText, minValue, maxValue, valueStep, offsetY, a7)
  local rowFrame = CreateFrame("Frame", nil, parentFrame)
  rowFrame:SetSize(480, 54)
  rowFrame:SetPoint("TOPLEFT", parentFrame, "TOPLEFT", 20, offsetY)
  local labelFontString = rowFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  labelFontString:SetPoint("TOPLEFT", rowFrame, "TOPLEFT", 0, 0)
  labelFontString:SetText(labelText)
  labelFontString:SetTextColor(.8, .8, .8, 1)
  local slider = CreateFrame("Slider", nil, rowFrame, "OptionsSliderTemplate")
  slider:SetPoint("TOPLEFT", labelFontString, "BOTTOMLEFT", 0, -6)
  slider:SetWidth(340)
  slider:SetHeight(16)
  slider:SetMinMaxValues(minValue, maxValue)
  slider:SetValueStep(valueStep)
  slider:SetObeyStepOnDrag(true)
  local thumbTexture = slider:GetThumbTexture()
  if thumbTexture then
    thumbTexture:SetVertexColor(.9, .75, .35, 1)
  end
  if slider.Low then
    slider.Low:SetText("")
  end
  if slider.High then
    slider.High:SetText("")
  end
  if slider.Text then
    slider.Text:SetText("")
  end
  local valueText = rowFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  valueText:SetPoint("LEFT", slider, "RIGHT", 12, 0)
  valueText:SetTextColor(.9, .75, .35, 1)
  return rowFrame, slider, valueText
end
local v108, spellQueueSlider, spellQueueValueText = createSliderRow(cvarTabFrame, "延迟容限 (SpellQueueWindow)", 0, 400, 10, -50, false)
spellQueueSlider:SetScript("OnValueChanged", function(self, sliderValue)
  local roundedValue = sliderValue - sliderValue % 10
  spellQueueValueText:SetText(tostring(roundedValue))
end)
local pendingSpellQueueValue = nil
local deferredCVarEventFrame = CreateFrame("Frame")
deferredCVarEventFrame:SetScript("OnEvent", function(self)
  self:UnregisterEvent("PLAYER_REGEN_ENABLED")
  local pendingValue = pendingSpellQueueValue
  pendingSpellQueueValue = nil
  if pendingValue == nil then
    return
  end
  local isSetOk = pcall(C_CVar.SetCVar, "SpellQueueWindow", tostring(pendingValue))
  if isSetOk then
    print("|cff00ff88[WowBuddyDev]|r " .. string.format(WowBuddyDev.L("延迟容限已在脱战后设为 %d"), pendingValue))
  else
    print("|cffff0000[WowBuddyDev]|r " .. WowBuddyDev.L("延迟容限修改失败"))
  end
  if WowBuddyDev.RefreshCVarPanel then
    WowBuddyDev.RefreshCVarPanel()
  end
end)
spellQueueSlider:SetScript("OnMouseUp", function(self)
  local roundedValue = self:GetValue() - self:GetValue() % 10
  if InCombatLockdown() then
    pendingSpellQueueValue = roundedValue
    deferredCVarEventFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
    print("|cffffcc00[WowBuddyDev]|r " .. string.format(WowBuddyDev.L("战斗中无法修改延迟容限，将在脱战后设为 %d"), roundedValue))
    return
  end
  local isSetOk = pcall(C_CVar.SetCVar, "SpellQueueWindow", tostring(roundedValue))
  if isSetOk then
    print("|cff00ff88[WowBuddyDev]|r " .. string.format(WowBuddyDev.L("延迟容限已设为 %d"), roundedValue))
  else
    print("|cffff0000[WowBuddyDev]|r " .. WowBuddyDev.L("延迟容限修改失败"))
    self:SetValue(tonumber(C_CVar.GetCVar("SpellQueueWindow")) or 400)
  end
  if WowBuddyDev.RefreshCVarPanel then
    WowBuddyDev.RefreshCVarPanel()
  end
end)
local rowHeight = 20
local columnLayout = {
  { x = 0, w = 220, align = "LEFT" },
  { x = 230, w = 70, align = "RIGHT" },
  { x = 310, w = 70, align = "RIGHT" },
  { x = 390, w = 70, align = "LEFT" },
}
-- 功能：在参数面板里建一行 4 列文字：参数名称 / 当前值 / 目标值 / 状态。
-- 入参：parentFrame 父框架；rowIndex 行号（1 起，用来算纵向位置）；isHeader 是否表头行。
-- 出参：该行的 4 个 FontString 数组。
-- 说明：列宽和对其方式读 columnLayout；表头用 GameFontNormal + 金色，普通行用 GameFontHighlightSmall + 灰色，靠字体区分表头和数据，行高与表头行保持一致。
local function createCVarRow(parentFrame, rowIndex, isHeader)
  local rowY = -(rowIndex - 1) * rowHeight
  local rowCells = {}
  local fontObject = isHeader and "GameFontNormal" or "GameFontHighlightSmall"
  for columnIndex, column in ipairs(columnLayout) do
    local cell = parentFrame:CreateFontString(nil, "OVERLAY", fontObject)
    cell:SetPoint("TOPLEFT", parentFrame, "TOPLEFT", column.x, rowY)
    cell:SetSize(column.w, rowHeight)
    cell:SetJustifyH(column.align)
    if isHeader then
      cell:SetTextColor(1, .85, .5, 1)
    else
      cell:SetTextColor(.8, .8, .8, 1)
    end
    rowCells[columnIndex] = cell
  end
  return rowCells
end
local className, classFile = UnitClass("player")
local defaultSpellQueueWindow = classFile == "EVOKER" and "50" or "400"
local cvarList = {
  { cvar = "RenderScale", value = "1", name = "渲染倍数", type = "float" },
  { cvar = "Gamma", value = "1", name = "伽马值", type = "float" },
  { cvar = "Brightness", value = "50", name = "亮度", type = "percent" },
  { cvar = "Contrast", value = "50", name = "对比度", type = "percent" },
  { cvar = "nameplateShowEnemies", value = "1", name = "敌方姓名板", type = "bool" },
  { cvar = "nameplateShowEnemyMinions", value = "1", name = "敌方仆从姓名板", type = "bool" },
  { cvar = "nameplateShowEnemyMinus", value = "1", name = "敌方杂兵姓名板", type = "bool" },
  { cvar = "nameplateShowAll", value = "1", name = "显示所有姓名板", type = "bool" },
  { cvar = "screenEdgeFlash", value = "0", name = "屏幕边缘闪光", type = "bool" },
  {
    cvar = "doNotFlashLowHealthWarning",
    value = "1",
    name = "生命值过低时不闪烁屏幕",
    type = "bool",
  },
  { cvar = "cooldownViewerEnabled", value = "1", name = "冷却管理器显示", type = "bool" },
  { cvar = "ffxDeath", value = "0", name = "死亡全屏特效", type = "bool" },
  { cvar = "ffxGlow", value = "0", name = "全屏泛光", type = "bool" },
  { cvar = "ffxNether", value = "0", name = "虚空特效", type = "bool" },
  { cvar = "SpellQueueWindow", value = defaultSpellQueueWindow, name = "施法队列窗口（延迟容限）", type = "int" },
  { cvar = "ActionButtonUseKeyDown", value = "1", name = "按下按键时施法", type = "bool" },
}
local cvarHeaderRow = CreateFrame("Frame", nil, cvarTabFrame)
cvarHeaderRow:SetPoint("TOPLEFT", cvarTabFrame, "TOPLEFT", 20, -120)
cvarHeaderRow:SetSize(480, rowHeight)
local headerCells = createCVarRow(cvarHeaderRow, 1, true)
headerCells[1]:SetText(WowBuddyDev.L("参数名称"))
headerCells[2]:SetText(WowBuddyDev.L("当前值"))
headerCells[3]:SetText(WowBuddyDev.L("目标值"))
headerCells[4]:SetText(WowBuddyDev.L("状态"))
local headerDivider = cvarHeaderRow:CreateTexture(nil, "BACKGROUND")
headerDivider:SetPoint("BOTTOMLEFT", cvarHeaderRow, "BOTTOMLEFT", 0, 0)
headerDivider:SetSize(460, 1)
headerDivider:SetColorTexture(.3, .3, .3, .5)
local cvarScrollFrame = CreateFrame("ScrollFrame", "WowBuddyDevCVarEnvScroll", cvarTabFrame, "UIPanelScrollFrameTemplate")
cvarScrollFrame:SetPoint("TOPLEFT", cvarHeaderRow, "BOTTOMLEFT", 0, -4)
cvarScrollFrame:SetPoint("BOTTOMRIGHT", cvarTabFrame, "BOTTOMRIGHT", -30, 56)
local cvarScrollBar = _G[cvarScrollFrame:GetName() .. "ScrollBar"]
if cvarScrollBar then
  local cvarScrollUpButton = _G[cvarScrollBar:GetName() .. "ScrollUpButton"]
  local cvarScrollDownButton = _G[cvarScrollBar:GetName() .. "ScrollDownButton"]
  if cvarScrollUpButton then
    cvarScrollUpButton:SetSize(16, 16)
    cvarScrollUpButton:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollUpButton-Up")
  end
  if cvarScrollDownButton then
    cvarScrollDownButton:SetSize(16, 16)
    cvarScrollDownButton:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
  end
end
cvarScrollFrame:EnableMouseWheel(true)
cvarScrollFrame:SetScript("OnMouseWheel", function(self, wheelDelta)
  local wheelScrollBar = _G[self:GetName() .. "ScrollBar"]
  if wheelScrollBar then
    wheelScrollBar:SetValue(wheelScrollBar:GetValue() - wheelDelta * 20)
  end
end)
local cvarRowCount = 1 + #cvarList
local cvarScrollChild = CreateFrame("Frame", nil, cvarScrollFrame)
cvarScrollChild:SetSize(460, cvarRowCount * rowHeight)
cvarScrollFrame:SetScrollChild(cvarScrollChild)
local cvarRows = {}
for rowIndex = 1, cvarRowCount, 1 do
  cvarRows[rowIndex] = createCVarRow(cvarScrollChild, rowIndex, false)
end
-- 功能：把 CVar 的原始值按类型格式化成给人看的文本。
-- 入参：rawValue 原始值（大多是字符串）；valueType 类型（bool / percent / int / 其它浮点）。
-- 出参：格式化后的字符串。
-- 说明：bool 显示「开 / 关」，percent 先除以 100 再保留两位小数。格式化前必须 tonumber 判断：GetCVar 可能返回空串或 "N/A"，直接塞进 %d / %.2f 会报错，所以转不动时原样返回。
local function formatCVarValue(rawValue, valueType)
  local numericValue = tonumber(rawValue)
  if valueType == "bool" then
    if rawValue == "0" or rawValue == 0 then
      return "关"
    end
    if rawValue == "1" or rawValue == 1 then
      return "开"
    end
    return tostring(rawValue)
  elseif valueType == "percent" then
    if numericValue then
      return string.format("%.2f", numericValue / 100)
    end
    return tostring(rawValue)
  elseif valueType == "int" then
    if numericValue then
      return string.format("%d", numericValue)
    end
    return tostring(rawValue)
  else
    if numericValue then
      return string.format("%.2f", numericValue)
    end
    return tostring(rawValue)
  end
end
-- 功能：判断某个 CVar 的当前值是否等于插件的推荐值（面板上显示「安全 / 不安全」）。
-- 入参：currentRaw 当前原始值；cvarEntry 推荐项条目（含 value / type 字段）。
-- 出参：true / false。
-- 说明：percent 类型的推荐值可能写成百分数（>1 就除以 100），也可能写成 1 以内的小数，两边按同一规则归一化后再比，容差 0.001；只要有一个不是数字就退回字符串比较。空值直接判为不安全。
local function isCVarSafe(currentRaw, cvarEntry)
  if currentRaw == nil or currentRaw == "" then
    return false
  end
  local currentNumber = tonumber(currentRaw)
  local recommendedNumber = tonumber(cvarEntry.value)
  if currentNumber and recommendedNumber then
    if cvarEntry.type == "percent" then
      local currentNormalized = currentNumber > 1 and currentNumber / 100 or currentNumber
      local recommendedNormalized = recommendedNumber > 1 and recommendedNumber / 100 or recommendedNumber
      return math.abs(currentNormalized - recommendedNormalized) < .001
    else
      return math.abs(currentNumber - recommendedNumber) < .001
    end
  end
  return tostring(currentRaw) == cvarEntry.value
end
-- 功能：刷新参数面板：第一行是只读的实际 UI 缩放，之后每行按 cvarList 显示当前值、推荐值和「安全 / 不安全」。
-- 入参：无。
-- 出参：无。
-- 说明：GetCVar 取不到或返回空串时按 "N/A" 处理，避免拿 nil / 空串去格式化。行数是「1 + 推荐项数」，多出来的行要清空文字，否则来回切页会留着上一轮的残留内容。
function WowBuddyDev.UpdateCVarEnvInfo()
  local rowIndex = 1
  local uiScale = UIParent:GetEffectiveScale()
  local rowCells = cvarRows[rowIndex]
  rowCells[1]:SetText(WowBuddyDev.L("实际 UI 缩放"))
  rowCells[1]:SetTextColor(.8, .8, .8, 1)
  rowCells[2]:SetText(string.format("%.3f", uiScale or 1))
  rowCells[2]:SetTextColor(.5, .75, 1, 1)
  rowCells[3]:SetText("-")
  rowCells[3]:SetTextColor(.5, .5, .5, 1)
  rowCells[4]:SetText(WowBuddyDev.L("|cff888888只读|r"))
  rowIndex = rowIndex + 1
  for index9, cvarEntry in ipairs(cvarList) do
    rowCells = cvarRows[rowIndex]
    local currentValue = C_CVar.GetCVar(cvarEntry.cvar)
    if not currentValue or currentValue == "" then
      currentValue = "N/A"
    end
    rowCells[1]:SetText(WowBuddyDev.L(cvarEntry.name))
    rowCells[1]:SetTextColor(.8, .8, .8, 1)
    rowCells[2]:SetText(formatCVarValue(currentValue, cvarEntry.type))
    rowCells[2]:SetTextColor(.8, .8, .8, 1)
    rowCells[3]:SetText(formatCVarValue(cvarEntry.value, cvarEntry.type))
    rowCells[3]:SetTextColor(.5, .5, .5, 1)
    if isCVarSafe(currentValue, cvarEntry) then
      rowCells[4]:SetText(WowBuddyDev.L("|cff00ff88安全|r"))
    else
      rowCells[4]:SetText(WowBuddyDev.L("|cffff5555不安全|r"))
    end
    rowIndex = rowIndex + 1
  end
  for emptyRowIndex = rowIndex, #cvarRows, 1 do
    local emptyRowCells = cvarRows[emptyRowIndex]
    emptyRowCells[1]:SetText("")
    emptyRowCells[2]:SetText("")
    emptyRowCells[3]:SetText("")
    emptyRowCells[4]:SetText("")
  end
end
local applyRecommendedButton = WowBuddyDev.CreateStyledButton(cvarTabFrame, "设置为推荐值", 140, 28)
applyRecommendedButton:SetPoint("BOTTOM", cvarTabFrame, "BOTTOM", 0, 16)
applyRecommendedButton:SetScript("OnClick", function()
  if InCombatLockdown() then
    print("|cffff0000[WowBuddyDev]|r 战斗中无法修改受保护的 CVar")
    return
  end
  local appliedCVars = {}
  for index10, cvarEntry in ipairs(cvarList) do
    local isSetOk = pcall(function()
      C_CVar.SetCVar(cvarEntry.cvar, cvarEntry.value)
    end)
    if isSetOk then
      table.insert(appliedCVars, WowBuddyDev.L(cvarEntry.name) .. "=" .. cvarEntry.value)
    end
  end
  if #appliedCVars > 0 then
    print(WowBuddyDev.L("|cff00ff88[WowBuddyDev]|r 安全模式已应用：") .. table.concat(appliedCVars, ", "))
  end
  WowBuddyDev.RefreshCVarPanel()
end)
-- 功能：把延迟容限滑条同步成当前 SpellQueueWindow 值，并刷新参数面板。
-- 入参：无。
-- 出参：无。
-- 说明：CVar 读不到时退回 400（游戏默认值），滑条不会停在 0；值文字按 10 的整数倍显示，和滑条步长、写回时的取整规则保持一致。
function WowBuddyDev.RefreshCVarPanel()
  local spellQueueWindow = tonumber(C_CVar.GetCVar("SpellQueueWindow")) or 400
  spellQueueSlider:SetValue(spellQueueWindow)
  spellQueueValueText:SetText(tostring(spellQueueWindow - spellQueueWindow % 10))
  if WowBuddyDev.UpdateCVarEnvInfo then
    WowBuddyDev.UpdateCVarEnvInfo()
  end
end
local macroTabFrame = CreateFrame("Frame", nil, mainWindow)
macroTabFrame:SetSize(520, 444)
macroTabFrame:SetPoint("TOPLEFT", mainWindow, "TOPLEFT", 10, -76)
macroTabFrame:SetPoint("BOTTOMRIGHT", mainWindow, "BOTTOMRIGHT", -10, 40)
macroTabFrame:Hide()
local macroPanelTitle = macroTabFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
macroPanelTitle:SetPoint("TOP", macroTabFrame, "TOP", 0, -14)
macroPanelTitle:SetText(WowBuddyDev.L("通用宏命令（可复制到游戏宏中使用）"))
macroPanelTitle:SetTextColor(.7, .7, .7, 1)
local macroPanelHint = macroTabFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
macroPanelHint:SetPoint("TOP", macroPanelTitle, "BOTTOM", 0, -4)
macroPanelHint:SetText(WowBuddyDev.L("在聊天框输入即可生效，也可绑定到按键"))
macroPanelHint:SetTextColor(.5, .5, .5, 1)
macroPanelHint:SetFont(WowBuddyDev.fontFile, 11, "")
local macroCommands = {
  { cmd = "/ON", desc = "总开关设置为开" },
  { cmd = "/OFF", desc = "总开关设置为关" },
  { cmd = "/bfk", desc = "爆发开关设置为开" },
  { cmd = "/bfg", desc = "爆发开关设置为关" },
  { cmd = "/dan", desc = "模式设置为单体" },
  { cmd = "/qun", desc = "强制群体：敌人数固定为5" },
  { cmd = "/AUTO", desc = "模式设置为自动" },
  { cmd = "/charu", desc = "临时关闭总开关0.5秒（插入技能用）" },
}
local macroRows = {}
for commandIndex, macroCommand in ipairs(macroCommands) do
  local rowY = -60 - (commandIndex - 1) * 36
  local rowFrame = CreateFrame("Frame", nil, macroTabFrame)
  rowFrame:SetSize(480, 30)
  rowFrame:SetPoint("TOP", macroTabFrame, "TOP", 0, rowY)
  local rowBackground = rowFrame:CreateTexture(nil, "BACKGROUND")
  rowBackground:SetAllPoints()
  rowBackground:SetColorTexture(.05, .05, .06, 1)
  rowFrame.bg = rowBackground
  local rowBorder = rowFrame:CreateTexture(nil, "BORDER")
  rowBorder:SetPoint("TOPLEFT", -1, 1)
  rowBorder:SetPoint("BOTTOMRIGHT", 1, -1)
  rowBorder:SetColorTexture(.22, .22, .24, 1)
  local commandText = rowFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  commandText:SetPoint("LEFT", rowFrame, "LEFT", 12, 0)
  commandText:SetText("|cffffcc00" .. macroCommand.cmd .. "|r")
  commandText:SetJustifyH("LEFT")
  commandText:SetWidth(100)
  local descText = rowFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  descText:SetPoint("LEFT", commandText, "RIGHT", 12, 0)
  rowFrame.descText = descText
  descText:SetJustifyH("LEFT")
  descText:SetTextColor(.8, .8, .8, 1)
  table.insert(macroRows, rowFrame)
end
-- 功能：刷新「制作按键宏」页每一行的说明文字。
-- 入参：无。
-- 出参：无。
-- 说明：命令列表是静态的，但说明要过 P07483180.L 走本地化，所以每次切到该页重刷一次，保证和其它页一样跟着客户端语言走。
function WowBuddyDev.RefreshMacroHelper()
  for commandIndex, rowFrame in ipairs(macroRows) do
    rowFrame.descText:SetText(WowBuddyDev.L(macroCommands[commandIndex].desc))
  end
end
WowBuddyDev.tabFrames[1] = WowBuddyDev.configFrame
WowBuddyDev.tabFrames[2] = WowBuddyDev.talentPickerFrame
WowBuddyDev.tabFrames[4] = cvarTabFrame
WowBuddyDev.tabFrames[5] = macroTabFrame
mainWindow:SetScript("OnShow", function()
  WowBuddyDev.SwitchTab(1)
end)
