-- ==========================================================================
-- 文件：5ca004.lua
-- 来源：P07483180.rar → P07483180/5ca004.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：5ca004.lua → DebugAuras.lua（按功能重命名）
-- 作用：光环/冷却调试面板与打印命令
-- ==========================================================================
local DEBUG_PREFIX = "|cff00ff88[WowBuddyDev Debug]|r"
local DEFAULT_UNIT = "target"
local AURA_FILTER_ALL = "ALL"
local AURA_VIEW_MODE = "AURA"
-- 功能：把任意值转成能安全打印的字符串（调试面板所有字段都先过这里）。
-- 入参：value 任意值。
-- 出参：字符串；值本身是 nil 时返回 "nil"，取值被保护时返回「受限」。
-- 说明：12.1 起部分 API 返回值是 secret value，tostring 能过但拿到的串不能拼接，所以这里做两层探测：先 pcall(tostring)，再做一次字符串拼接，任何一步失败都返回「受限」而不是报错。
local function safeString(value)
  if value == nil then
    return "nil"
  end
  local okText, text = pcall(tostring, value)
  if not okText then
    return "受限"
  end
  local okProbe = pcall(function()
    local ignored = text .. ""
  end)
  if not okProbe then
    return "受限"
  end
  return text
end
-- 功能：把布尔值转成「是」/「否」两个汉字。
-- 入参：value 待格式化的值（真值即「是」）。
-- 出参："是" / "否"；取不到可读值时返回「受限」。
-- 说明：单独包一层 pcall 是因为 12.1 里对保护值做条件判断也会抛错；失败时返回「受限」而不是让整块面板不刷新。
local function formatBool(value)
  local okText, yesNo = pcall(function()
    if value then
      return "是"
    else
      return "否"
    end
  end)
  if not okText then
    return "受限"
  end
  return yesNo
end
-- 功能：把任意值收敛成严格的 true / false。
-- 入参：value 任意值。
-- 出参：true 或 false；值不可读时返回 nil（表示「不知道」）。
-- 说明：nil 和 false 必须区分开：面板上「不知道」要显示「受限」，而「否」是明确知道的 false。
local function normalizeBool(value)
  local okTruthy = pcall(function()
    return value and true or false
  end)
  if not okTruthy then
    return nil
  end
  return value and true or false
end
-- 功能：按「键=值」的格式打印一行调试信息。
-- 入参：key 字段名；text 字段值。
-- 出参：无。
-- 说明：整个 string.format 都套着 pcall —— 字段值可能是保护值，格式化失败就退回「键=受限」，不让一行坏数据打断整个面板的输出。
local function printKeyValue(key, text)
  local okPrint = pcall(function()
    print(string.format("%s  %s=%s", DEBUG_PREFIX, key, text))
  end)
  if not okPrint then
    print(string.format("%s  %s=受限", DEBUG_PREFIX, key))
  end
end
-- 功能：把指定单位身上的光环逐条打印到聊天框（/pmsdebug 的手动输出用）。
-- 入参：unit 单位 token；filter 光环过滤（默认 HELPFUL）。
-- 出参：无。
-- 说明：用 C_UnitAuras.GetAuraDataByIndex 顺序读，读到 nil 为止（上限 40）。整段套 pcall：12.1 战斗中读光环会 taint 报错，这时打印提示让玩家脱战后重试，而不是抛错。
function WowBuddyDev.PrintUnitAuras(unit, filter)
  filter = filter or "HELPFUL"
  local filterLabel = filter == "HELPFUL" and "BUFF" or "DEBUFF"
  print(string.format("%s === %s %s ===", DEBUG_PREFIX, unit or "未知", filterLabel))
  if not C_UnitAuras or not C_UnitAuras.GetAuraDataByIndex then
    print(DEBUG_PREFIX .. " C_UnitAuras.GetAuraDataByIndex 不可用")
    return
  end
  local auraCount = 0
  local okRead, okReadEnd = pcall(function()
    for auraIndex = 1, 40, 1 do
      local aura = C_UnitAuras.GetAuraDataByIndex(unit, auraIndex, filter)
      if not aura then
        break
      end
      auraCount = auraCount + 1
      print(DEBUG_PREFIX .. " [" .. auraCount .. "]")
      printKeyValue("name", aura.name)
      printKeyValue("spellId", aura.spellId)
      printKeyValue("icon", aura.icon)
      printKeyValue("stacks", aura.applications)
      printKeyValue("duration", aura.duration)
      printKeyValue("expiration", aura.expirationTime)
      printKeyValue("source", aura.sourceUnit)
      printKeyValue("boss", aura.isBossAura)
      printKeyValue("steal", aura.isStealable)
      printKeyValue("instanceID", aura.auraInstanceID)
    end
  end)
  if not okRead then
    print(DEBUG_PREFIX .. " aura 读取受限（12.1 战斗中 tainted，请脱战后重试）")
    return
  end
  if auraCount == 0 then
    print(DEBUG_PREFIX .. " 无数据")
  else
    print(DEBUG_PREFIX .. " 共 " .. auraCount .. " 个")
  end
end
-- 功能：建一个调试面板用的按钮：底色纹理、边框纹理、居中文字，并挂上鼠标移入/移出高亮。
-- 入参：parent 父框架；text 按钮文字（会过 P07483180.L 本地化）；width 宽度（默认 70）；height 高度（默认 24）。
-- 出参：button 建好的按钮。
-- 说明：OnEnter 只在按钮「未选中」时才换高亮色 —— 选中态的红底优先级更高。OnLeave 会回调按钮自己的 updateState（由调用方挂上），这样移开鼠标就恢复到该有的选中/未选中外观。
local function createDebugButton(parent, text, width, height)
  local button = CreateFrame("Button", nil, parent)
  button:SetSize(width or 70, height or 24)
  local bgTexture = button:CreateTexture(nil, "BACKGROUND")
  bgTexture:SetAllPoints()
  button.bg = bgTexture
  local borderTexture = button:CreateTexture(nil, "BORDER")
  borderTexture:SetPoint("TOPLEFT", -1, 1)
  borderTexture:SetPoint("BOTTOMRIGHT", 1, -1)
  button.border = borderTexture
  local fontString = button:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  fontString:SetPoint("CENTER")
  fontString:SetText(WowBuddyDev.L(text or ""))
  button:SetFontString(fontString)
  button:SetScript("OnEnter", function(self)
    if not self.selected then
      self.bg:SetColorTexture(.2, .2, .22, .8)
      self.border:SetColorTexture(.5, .5, .55, 1)
      self:GetFontString():SetTextColor(.9, .75, .35, 1)
    end
  end)
  button:SetScript("OnLeave", function(button)
    if button.updateState then
      button.updateState()
    end
  end)
  return button
end
-- 功能：建（并缓存）Aura 调试窗口：单位选择、BUFF/DEBUFF 过滤、Aura/冷却视图切换、状态行、滚动输出框、关闭按钮。
-- 入参：无。
-- 出参：auraDebugFrame 调试窗口框架。
-- 说明：三组按钮（单位 / 过滤 / 视图）共用 createDebugButton，各自的 updateState 负责按当前选中项刷颜色。切换「冷却」视图时会强制把单位切回玩家（自己）—— 冷却数据只有玩家自己有。滚动框用 ScrollingMessageFrame，滚轮往上滚看历史。
local function createAuraDebugWindow()
  local auraDebugFrame = CreateFrame("Frame", "WowBuddyDevAuraDebugWindow", UIParent, BackdropTemplateMixin and "BackdropTemplate")
  auraDebugFrame:SetSize(540, 520)
  auraDebugFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 0)
  auraDebugFrame:SetBackdrop({
    bgFile = "Interface\\Buttons\\WHITE8X8",
    edgeFile = "Interface\\Buttons\\WHITE8X8",
    tile = false,
    tileSize = 0,
    edgeSize = 1,
    insets = { left = 0, right = 0, top = 0, bottom = 0 },
  })
  auraDebugFrame:SetBackdropColor(.08, .08, .09, .95)
  auraDebugFrame:SetBackdropBorderColor(.22, .22, .24, 1)
  auraDebugFrame:EnableMouse(true)
  auraDebugFrame:SetMovable(true)
  auraDebugFrame:RegisterForDrag("LeftButton")
  auraDebugFrame:SetScript("OnDragStart", auraDebugFrame.StartMoving)
  auraDebugFrame:SetScript("OnDragStop", auraDebugFrame.StopMovingOrSizing)
  auraDebugFrame:SetFrameStrata("DIALOG")
  auraDebugFrame:Hide()
  local titleText = auraDebugFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
  titleText:SetPoint("TOP", auraDebugFrame, "TOP", 0, -14)
  titleText:SetText(WowBuddyDev.L("WowBuddyDev Aura 调试"))
  local unitButtons = {}
  local unitButtonDefs = {
    { text = "目标", value = "target" },
    { text = "玩家", value = "player" },
    { text = "焦点", value = "focus" },
  }
  -- 功能：按当前选中的单位刷新「目标 / 玩家 / 焦点」三个按钮的外观。
  -- 入参：无。
  -- 出参：无。
  -- 说明：选中项用红底白字，未选中的用暗底灰字；选中判定看按钮的 value 是不是等于当前选中的单位（unit 变量）。
  local function refreshUnitButtonState()
    for unitIndex, button in ipairs(unitButtons) do
      button.selected = (button.value == DEFAULT_UNIT)
      if button.selected then
        button.bg:SetColorTexture(.6, .1, .15, .9)
        button.border:SetColorTexture(.8, .2, .25, 1)
        button:GetFontString():SetTextColor(1, 1, 1, 1)
      else
        button.bg:SetColorTexture(.12, .12, .13, .6)
        button.border:SetColorTexture(.35, .35, .38, 1)
        button:GetFontString():SetTextColor(.6, .6, .6, 1)
      end
    end
  end
  local refreshFilterButtonState, refreshViewModeButtonState
  local cooldownButton = nil
  -- 功能：刷新「冷却」视图按钮的可用状态：只有单位是玩家自己时才可点。
  -- 入参：无。
  -- 出参：无。
  -- 说明：冷却数据只对玩家自己有；不可用时按钮变暗、底色变灰，同时 EnableMouse(false) 让它连点击反馈都没有。
  local function refreshCooldownButtonState()
    if not cooldownButton then
      return
    end
    local isPlayerUnit = (DEFAULT_UNIT == "player")
    cooldownButton:EnableMouse(isPlayerUnit)
    if isPlayerUnit then
      cooldownButton:GetFontString():SetTextColor(.6, .6, .6, 1)
    else
      cooldownButton:GetFontString():SetTextColor(.3, .3, .3, 1)
      cooldownButton.bg:SetColorTexture(.08, .08, .09, .4)
      cooldownButton.border:SetColorTexture(.22, .22, .24, .5)
    end
  end
  for unitIndex, unitDef in ipairs(unitButtonDefs) do
    local unitButton = createDebugButton(auraDebugFrame, unitDef.text, 70, 24)
    unitButton:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 16 + (unitIndex - 1) * 78, -42)
    unitButton.value = unitDef.value
    unitButton.updateState = refreshUnitButtonState
    unitButton:SetScript("OnClick", function()
      DEFAULT_UNIT = unitDef.value
      refreshUnitButtonState()
      refreshCooldownButtonState()
      if AURA_VIEW_MODE == "COOLDOWN" and DEFAULT_UNIT ~= "player" then
        AURA_VIEW_MODE = "AURA"
        refreshViewModeButtonState()
        refreshFilterButtonState()
      end
      if WowBuddyDev.RefreshAuraDebugPanel then
        WowBuddyDev.RefreshAuraDebugPanel()
      end
    end)
    table.insert(unitButtons, unitButton)
  end
  local refreshButton = createDebugButton(auraDebugFrame, WowBuddyDev.L("刷新"), 70, 24)
  refreshButton:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 250, -42)
  refreshButton.updateState = function()
    refreshButton.bg:SetColorTexture(.12, .12, .13, .6)
    refreshButton.border:SetColorTexture(.35, .35, .38, 1)
    refreshButton:GetFontString():SetTextColor(.6, .6, .6, 1)
  end
  refreshButton:SetScript("OnClick", function()
    if WowBuddyDev.RefreshAuraDebugPanel then
      WowBuddyDev.RefreshAuraDebugPanel()
    end
  end)
  local printButton = createDebugButton(auraDebugFrame, "输出到聊天框", 110, 24)
  printButton:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 340, -42)
  printButton.updateState = function()
    printButton.bg:SetColorTexture(.12, .12, .13, .6)
    printButton.border:SetColorTexture(.35, .35, .38, 1)
    printButton:GetFontString():SetTextColor(.6, .6, .6, 1)
  end
  printButton:SetScript("OnClick", function()
    if AURA_VIEW_MODE == "COOLDOWN" then
      if WowBuddyDev.PrintCooldownInfo then
        WowBuddyDev.PrintCooldownInfo()
      end
    elseif AURA_FILTER_ALL == "ALL" then
      WowBuddyDev.PrintUnitAuras(DEFAULT_UNIT, "HELPFUL")
      WowBuddyDev.PrintUnitAuras(DEFAULT_UNIT, "HARMFUL")
    else
      WowBuddyDev.PrintUnitAuras(DEFAULT_UNIT, AURA_FILTER_ALL)
    end
  end)
  local filterButtons = {}
  local filterButtonDefs = {
    { text = "全部", value = "ALL" },
    { text = "BUFF", value = "HELPFUL" },
    { text = "DEBUFF", value = "HARMFUL" },
  }
  -- 功能：按当前过滤条件刷新「全部 / BUFF / DEBUFF」三个按钮的外观。
  -- 入参：无。
  -- 出参：无。
  -- 说明：只有视图模式是 AURA 时才按过滤条件高亮 —— 在冷却视图下这三个按钮不表示当前状态。
  refreshFilterButtonState = function()
    for filterIndex, filterButton in ipairs(filterButtons) do
      filterButton.selected = (AURA_VIEW_MODE == "AURA" and filterButton.value == AURA_FILTER_ALL)
      if filterButton.selected then
        filterButton.bg:SetColorTexture(.6, .1, .15, .9)
        filterButton.border:SetColorTexture(.8, .2, .25, 1)
        filterButton:GetFontString():SetTextColor(1, 1, 1, 1)
      else
        filterButton.bg:SetColorTexture(.12, .12, .13, .6)
        filterButton.border:SetColorTexture(.35, .35, .38, 1)
        filterButton:GetFontString():SetTextColor(.6, .6, .6, 1)
      end
    end
  end
  for filterIndex, filterDef in ipairs(filterButtonDefs) do
    local filterButton = createDebugButton(auraDebugFrame, filterDef.text, 70, 24)
    filterButton:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 16 + (filterIndex - 1) * 78, -72)
    filterButton.value = filterDef.value
    filterButton.updateState = refreshFilterButtonState
    filterButton:SetScript("OnClick", function()
      AURA_FILTER_ALL = filterDef.value
      AURA_VIEW_MODE = "AURA"
      refreshFilterButtonState()
      refreshViewModeButtonState()
      if WowBuddyDev.RefreshAuraDebugPanel then
        WowBuddyDev.RefreshAuraDebugPanel()
      end
    end)
    table.insert(filterButtons, filterButton)
  end
  local viewModeButtons = {}
  local viewModeButtonDefs = { { text = "Aura", value = "AURA" }, { text = "冷却", value = "COOLDOWN" } }
  -- 功能：按当前视图刷新「Aura / 冷却」两个按钮的外观。
  -- 入参：无。
  -- 出参：无。
  -- 说明：视图变量同时也是 RefreshAuraDebugPanel 的分派依据，所以刷完外观后必须让它和实际渲染的内容保持一致。
  refreshViewModeButtonState = function()
    for viewModeIndex, viewModeButton in ipairs(viewModeButtons) do
      viewModeButton.selected = (viewModeButton.value == AURA_VIEW_MODE)
      if viewModeButton.selected then
        viewModeButton.bg:SetColorTexture(.6, .1, .15, .9)
        viewModeButton.border:SetColorTexture(.8, .2, .25, 1)
        viewModeButton:GetFontString():SetTextColor(1, 1, 1, 1)
      else
        viewModeButton.bg:SetColorTexture(.12, .12, .13, .6)
        viewModeButton.border:SetColorTexture(.35, .35, .38, 1)
        viewModeButton:GetFontString():SetTextColor(.6, .6, .6, 1)
      end
    end
  end
  for viewModeIndex, viewModeDef in ipairs(viewModeButtonDefs) do
    local viewModeButton = createDebugButton(auraDebugFrame, viewModeDef.text, 70, 24)
    viewModeButton:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 250 + (viewModeIndex - 1) * 78, -72)
    viewModeButton.value = viewModeDef.value
    viewModeButton.updateState = refreshViewModeButtonState
    if viewModeDef.value == "COOLDOWN" then
      cooldownButton = viewModeButton
    end
    viewModeButton:SetScript("OnClick", function()
      if viewModeDef.value == "COOLDOWN" and DEFAULT_UNIT ~= "player" then
        return
      end
      AURA_VIEW_MODE = viewModeDef.value
      if viewModeDef.value == "COOLDOWN" then
        DEFAULT_UNIT = "player"
        refreshUnitButtonState()
        refreshCooldownButtonState()
      end
      refreshFilterButtonState()
      refreshViewModeButtonState()
      if WowBuddyDev.RefreshAuraDebugPanel then
        WowBuddyDev.RefreshAuraDebugPanel()
      end
    end)
    table.insert(viewModeButtons, viewModeButton)
  end
  local statusText = auraDebugFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  statusText:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 16, -104)
  statusText:SetText(WowBuddyDev.L("当前: 目标 | 全部 | 总数: 0 | BUFF: 0 | DEBUFF: 0"))
  statusText:SetTextColor(.8, .8, .8, 1)
  WowBuddyDev.auraDebugStatusText = statusText
  local scrollFrame = CreateFrame("ScrollingMessageFrame", "WowBuddyDevAuraDebugSMF", auraDebugFrame)
  scrollFrame:SetPoint("TOPLEFT", auraDebugFrame, "TOPLEFT", 14, -126)
  scrollFrame:SetPoint("BOTTOMRIGHT", auraDebugFrame, "BOTTOMRIGHT", -14, 42)
  scrollFrame:SetFontObject("GameFontNormal")
  scrollFrame:SetTextColor(.85, .85, .85, 1)
  scrollFrame:SetJustifyH("LEFT")
  scrollFrame:SetFading(false)
  scrollFrame:SetMaxLines(200)
  scrollFrame:EnableMouseWheel(true)
  scrollFrame:SetScript("OnMouseWheel", function(scrollFrame, event)
    if event > 0 then
      scrollFrame:ScrollUp()
    else
      scrollFrame:ScrollDown()
    end
  end)
  scrollFrame:SetHyperlinksEnabled(false)
  scrollFrame:Show()
  local scrollBg = scrollFrame:CreateTexture(nil, "BACKGROUND")
  scrollBg:SetAllPoints()
  scrollBg:SetColorTexture(.05, .05, .06, 1)
  scrollBg:SetDrawLayer("BACKGROUND", -1)
  auraDebugFrame.smf = scrollFrame
  local closeButton = createDebugButton(auraDebugFrame, "关 闭", 80, 24)
  closeButton:SetPoint("BOTTOM", auraDebugFrame, "BOTTOM", 0, 12)
  closeButton.updateState = function()
    closeButton.bg:SetColorTexture(.12, .12, .13, .6)
    closeButton.border:SetColorTexture(.35, .35, .38, 1)
    closeButton:GetFontString():SetTextColor(.6, .6, .6, 1)
  end
  closeButton:SetScript("OnClick", function()
    auraDebugFrame:Hide()
  end)
  refreshUnitButtonState()
  refreshFilterButtonState()
  refreshViewModeButtonState()
  refreshCooldownButtonState()
  return auraDebugFrame
end
-- 功能：对外接口：取 Aura 调试窗口（第一次调用时创建并缓存）。
-- 入参：无。
-- 出参：P07483180.auraDebugFrame。
-- 说明：整个窗口是懒创建的 —— 没人在调试时不该占用内存和事件。
function WowBuddyDev.GetAuraDebugWindow()
  if not WowBuddyDev.auraDebugFrame then
    WowBuddyDev.auraDebugFrame = createAuraDebugWindow()
  end
  return WowBuddyDev.auraDebugFrame
end
-- 功能：把法术 ID 解析成技能名（查不到就返回本地化的「未知」）。
-- 入参：spellID 法术 ID。
-- 出参：技能名字符串。
-- 说明：优先用 12.x 的 C_Spell.GetSpellName，老接口 GetSpellInfo 作为兜底；两者都要走 pcall，因为战斗中查名字可能被限制。
local function resolveSpellName(spellID)
  local okName, spellName = pcall(function()
    if C_Spell and C_Spell.GetSpellName then
      return C_Spell.GetSpellName(spellID)
    end
    local spellInfo = GetSpellInfo(spellID)
    return spellInfo
  end)
  if okName and spellName then
    return spellName
  end
  return WowBuddyDev.L("未知")
end
-- 功能：把当前单位 + 过滤条件下的光环列表刷进调试窗口的滚动框，并更新状态行统计。
-- 入参：无。
-- 出参：无。
-- 说明：过滤条件为「全部」时把有益和有害各刷一遍，否则只刷一个。每行还带剩余时间（0.1 秒精度）—— 计算时同样套 pcall，因为 expirationTime 可能是保护值，取不到就显示 N/A。状态行给出总数、BUFF 数、DEBUFF 数三个统计。
function WowBuddyDev.RefreshAuraView()
  local debugWindow = WowBuddyDev.GetAuraDebugWindow()
  if not debugWindow:IsShown() then
    return
  end
  local scrollFrame = debugWindow.smf
  if not scrollFrame then
    return
  end
  scrollFrame:Clear()
  local unit = DEFAULT_UNIT
  local filter = AURA_FILTER_ALL
  local filterList = {}
  if filter == "ALL" then
    filterList = { "HELPFUL", "HARMFUL" }
  else
    filterList = { filter }
  end
  local total = 0
  local buffCount = 0
  local debuffCount = 0
  for filterIndex, filter in ipairs(filterList) do
    local filterCount = 0
    for auraIndex = 1, 40, 1 do
      local aura = C_UnitAuras.GetAuraDataByIndex(unit, auraIndex, filter)
      if not aura then
        break
      end
      filterCount = filterCount + 1
      local durationText = "N/A"
      local okDuration, remaining = pcall(function()
        local expiration = aura.expirationTime
        if expiration and expiration > 0 then
          return expiration - GetTime()
        end
        return 0
      end)
      if okDuration then
        durationText = string.format("%.1f", remaining)
      end
      local line = string.format("[%s] #%d | %s | ID=%s | icon=%s | 层=%s | 持续=%s | 剩余=%s", (filter == "HELPFUL" and "B" or "D"), filterCount, safeString(aura.name), safeString(aura.spellId), safeString(aura.icon), safeString(aura.applications), safeString(aura.duration), durationText)
      scrollFrame:AddMessage(line)
    end
    total = total + filterCount
    if filter == "HELPFUL" then
      buffCount = filterCount
    end
    if filter == "HARMFUL" then
      debuffCount = filterCount
    end
    if filterCount == 0 then
      scrollFrame:AddMessage((filter == "HELPFUL" and "BUFF" or "DEBUFF") .. " 无数据")
    end
    scrollFrame:AddMessage(" ")
  end
  if WowBuddyDev.auraDebugStatusText then
    local unitLabel = DEFAULT_UNIT == "target" and "目标" or DEFAULT_UNIT == "player" and "玩家" or DEFAULT_UNIT == "focus" and "焦点" or DEFAULT_UNIT
    local filterLabel = AURA_FILTER_ALL == "ALL" and "全部" or AURA_FILTER_ALL == "HELPFUL" and "BUFF" or AURA_FILTER_ALL == "HARMFUL" and "DEBUFF" or AURA_FILTER_ALL
    WowBuddyDev.auraDebugStatusText:SetText(string.format("当前: %s | %s | 总数: %d | BUFF: %d | DEBUFF: %d", unitLabel, filterLabel, total, buffCount, debuffCount))
  end
end
-- 功能：把当前专精 testSpells 里每个技能的冷却与充能刷进调试窗口的滚动框。
-- 入参：无。
-- 出参：无。
-- 说明：没有 testSpells（没配调试技能）时打印一行提示并更新状态行。充能同时给「当前/上限」两个值，任一取不到就整段显示 N/A —— 不显示半条数据。
function WowBuddyDev.RefreshCooldownView()
  local debugWindow = WowBuddyDev.GetAuraDebugWindow()
  if not debugWindow:IsShown() then
    return
  end
  local scrollFrame = debugWindow.smf
  if not scrollFrame then
    return
  end
  scrollFrame:Clear()
  local testSpells = WowBuddyDev.testSpells or {}
  if #testSpells == 0 then
    scrollFrame:AddMessage("当前职业没有 testSpells，无数据")
    if WowBuddyDev.auraDebugStatusText then
      WowBuddyDev.auraDebugStatusText:SetText(WowBuddyDev.L("当前: 冷却 | 无数据"))
    end
    return
  end
  for spellIndex, spellID in ipairs(testSpells) do
    local spellName = resolveSpellName(spellID)
    local cooldownText = "N/A"
    local okCooldown, remaining = pcall(WowBuddyDev.GetSpellCooldownRemaining, spellID)
    if okCooldown then
      cooldownText = string.format("%.1f", remaining)
    end
    local chargeText = "N/A"
    local okCharges, charges = pcall(C_Spell.GetSpellCharges, spellID)
    if okCharges and charges then
      local currentCharges = safeString(charges.currentCharges)
      local maxCharges = safeString(charges.maxCharges)
      if currentCharges ~= "受限" and maxCharges ~= "受限" then
        chargeText = currentCharges .. "/" .. maxCharges
      end
    end
    local line = string.format("[CD] %s | ID=%s | 冷却=%s | 层数=%s", safeString(spellName), tostring(spellID), cooldownText, chargeText)
    scrollFrame:AddMessage(line)
  end
  if WowBuddyDev.auraDebugStatusText then
    WowBuddyDev.auraDebugStatusText:SetText(string.format("当前: 冷却 | 共 %d 个技能", #testSpells))
  end
end
-- 功能：把当前专精 testSpells 的冷却与充能打印到聊天框。
-- 入参：无。
-- 出参：无。
-- 说明：和 RefreshCooldownView 是同一份数据的两条出口（一个进窗口、一个进聊天框），逻辑保持一致。
function WowBuddyDev.PrintCooldownInfo()
  print(DEBUG_PREFIX .. " === 玩家技能冷却 / 层数 ===")
  local testSpells = WowBuddyDev.testSpells or {}
  if #testSpells == 0 then
    print(DEBUG_PREFIX .. " 当前职业没有 testSpells")
    return
  end
  for spellIndex, spellID in ipairs(testSpells) do
    local spellName = resolveSpellName(spellID)
    local cooldownText = "N/A"
    local okCooldown, remaining = pcall(WowBuddyDev.GetSpellCooldownRemaining, spellID)
    if okCooldown then
      cooldownText = string.format("%.1f", remaining)
    end
    local chargeText = "N/A"
    local okCharges, charges = pcall(C_Spell.GetSpellCharges, spellID)
    if okCharges and charges then
      local currentCharges = safeString(charges.currentCharges)
      local maxCharges = safeString(charges.maxCharges)
      if currentCharges ~= "受限" and maxCharges ~= "受限" then
        chargeText = currentCharges .. "/" .. maxCharges
      end
    end
    print(string.format("%s [CD] %s | ID=%s | 冷却=%s | 层数=%s", DEBUG_PREFIX, spellName, tostring(spellID), cooldownText, chargeText))
  end
end
-- 功能：按当前视图模式刷新调试面板（Aura 视图或冷却视图）。
-- 入参：无。
-- 出参：无。
-- 说明：这是窗口内所有按钮点击后统一走的刷新入口，视图变量只在这里读一次。
function WowBuddyDev.RefreshAuraDebugPanel()
  if AURA_VIEW_MODE == "COOLDOWN" then
    WowBuddyDev.RefreshCooldownView()
  else
    WowBuddyDev.RefreshAuraView()
  end
end
SLASH_PMSDEBUG1 = "/pmsdebug"
SlashCmdList.PMSDEBUG = function(input)
  input = ((input or "")):trim():lower()
  local debugWindow = WowBuddyDev.GetAuraDebugWindow()
  if not debugWindow:IsShown() then
    debugWindow:Show()
  end
  AURA_VIEW_MODE = "AURA"
  if input == "" or input == "all" then
    DEFAULT_UNIT = "player"
    AURA_FILTER_ALL = "ALL"
    WowBuddyDev.PrintUnitAuras("player", "HELPFUL")
    WowBuddyDev.PrintUnitAuras("player", "HARMFUL")
  elseif input == "player" then
    DEFAULT_UNIT = "player"
    AURA_FILTER_ALL = "HELPFUL"
    WowBuddyDev.PrintUnitAuras("player", "HELPFUL")
  elseif input == "target" then
    DEFAULT_UNIT = "target"
    AURA_FILTER_ALL = "HARMFUL"
    WowBuddyDev.PrintUnitAuras("target", "HARMFUL")
  elseif input == "focus" then
    DEFAULT_UNIT = "focus"
    AURA_FILTER_ALL = "HELPFUL"
    WowBuddyDev.PrintUnitAuras("focus", "HELPFUL")
  else
    print(DEBUG_PREFIX .. " 未知参数: " .. input .. "，可用: player/target/focus/all")
  end
  WowBuddyDev.RefreshAuraDebugPanel()
end
local WATCH_PREFIX = "|cff00ff88[WowBuddyDev Watch]|r"
local isWatching = false
local previousAuras = {}
-- 功能：把一个单位身上的光环按 index 抓进结果表（给战斗观察员用）。
-- 入参：unit 单位 token；filter 光环过滤（HELPFUL / HARMFUL）；auraTable 结果表（键为 unit:filter:spellID）。
-- 出参：无（结果写进 auraTable）。
-- 说明：读光环永远返回 index 连续的表，所以用循环读到 nil 为止（上限 40 个，防止异常情况死循环）。整段套 pcall，因为战斗中读光环可能抛错；没有 spellId 的光环直接跳过，观察员只关心能对上法术 ID 的。
local function collectUnitAuras(unit, filter, auraTable)
  if not (UnitExists(unit) and (C_UnitAuras and C_UnitAuras.GetAuraDataByIndex)) then
    return
  end
  pcall(function()
    for auraIndex = 1, 40, 1 do
      local aura = C_UnitAuras.GetAuraDataByIndex(unit, auraIndex, filter)
      if not aura then
        break
      end
      if aura.spellId then
        auraTable[unit .. ":" .. filter .. ":" .. aura.spellId] = {
          unit = unit,
          filter = filter,
          spellId = aura.spellId,
          name = aura.name,
          stacks = aura.applications,
          duration = aura.duration,
          remaining = aura.expirationTime and aura.expirationTime - GetTime() or 0,
          source = aura.sourceUnit,
        }
      end
    end
  end)
end
-- 功能：给玩家自己抓一份完整快照（有益 + 有害两遍）。
-- 入参：无。
-- 出参：snapshot 快照表，键为 unit:filter:spellID。
-- 说明：只看玩家自己 —— 观察员是为了补全「自己身上的 buff 到底是不是某个法术」，别人身上的光环没有意义。
local function snapshotAuras()
  local snapshot = {}
  collectUnitAuras("player", "HELPFUL", snapshot)
  collectUnitAuras("player", "HARMFUL", snapshot)
  collectUnitAuras("target", "HELPFUL", snapshot)
  collectUnitAuras("target", "HARMFUL", snapshot)
  return snapshot
end
-- 功能：对比上一份快照，把这次新增的光环逐条打印出来。
-- 入参：auraTable 本次快照。
-- 出参：无。
-- 说明：这正是「观察员」的用处：战斗中看不到的战斗记录延迟、光环延迟，靠脱战前后两份快照的差分把真身 spellID 暴露出来。一条新增都没有时打印一行提示（说明触发失败、光环已消失或脱战太晚）。最后把本次快照存成下次的基准。
local function printNewAuras(auraTable)
  local addedCount = 0
  for auraKey, aura in pairs(auraTable) do
    if not previousAuras[auraKey] then
      addedCount = addedCount + 1
      print(string.format("%s [%s|%s] %s ID=%s 层=%s 持续=%s 剩余=%.1f 来源=%s", WATCH_PREFIX, aura.unit, aura.filter == "HELPFUL" and "BUFF" or "DEBUFF", tostring(aura.name), tostring(aura.spellId), tostring(aura.stacks or 0), tostring(aura.duration or "?"), aura.remaining or 0, tostring(aura.source or "?")))
    end
  end
  if addedCount == 0 then
    print(WATCH_PREFIX .. " 本次战斗无新增 aura（触发失败、已消失或脱战过晚）")
  end
  previousAuras = auraTable
end
-- 功能：脱战后延迟半秒抓一份快照对比；如果这时身上一个光环都没有，就再等 1 秒重试一次。
-- 入参：无。
-- 出参：无。
-- 说明：刚脱战的一瞬间光环还没落地（客户端延迟），所以先等 .5 秒；空快照再等 1 秒是给「脱战瞬间刚好没 buff」的情况留一次机会。每一步都重新检查 isWatching，玩家中途关掉观察员就不再继续。
local function watchAfterCombat()
  if not isWatching then
    return
  end
  C_Timer.After(.5, function()
    if not isWatching then
      return
    end
    local snapshot = snapshotAuras()
    if not next(snapshot) then
      C_Timer.After(1, function()
        if isWatching then
          printNewAuras(snapshotAuras())
        end
      end)
      return
    end
    printNewAuras(snapshot)
  end)
end
local watchEventFrame = CreateFrame("Frame")
watchEventFrame:RegisterEvent("PLAYER_REGEN_DISABLED")
watchEventFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
watchEventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
watchEventFrame:SetScript("OnEvent", function(eventFrame, event2)
  if not isWatching then
    return
  end
  if event2 == "PLAYER_REGEN_DISABLED" or event2 == "PLAYER_ENTERING_WORLD" then
    previousAuras = snapshotAuras()
  else
    watchAfterCombat()
  end
end)
SLASH_PMSWATCH1 = "/pmswatch"
SlashCmdList.PMSWATCH = function(input)
  input = ((input or "")):trim():lower()
  if input == "now" then
    previousAuras = {}
    printNewAuras(snapshotAuras())
    return
  end
  isWatching = not isWatching
  print(WATCH_PREFIX .. " 战斗 buff 观察员: " .. (isWatching and "|cff00ff00开|r" or "|cffff0000关|r"))
end
local isLocCollecting = false
local locEntries = {}
-- 功能：打印一条可粘贴进 locTypes 白名单的 LoC 条目。
-- 入参：locType 失控类型名；locEntry 条目表（spellID / remain / combat）。
-- 出参：无。
-- 说明：输出刻意做成 Lua 表那行的格式，方便直接粘进源码；spellID 和剩余时间都可能是保护值，所以统一过 tostring。
local function printLocEntry(locType, locEntry)
  print(string.format("|cff00ff00[pmsloc]|r \"%s\",  -- spellID=%s remain=%s combat=%s", locType, tostring(locEntry.spellID), tostring(locEntry.remain), tostring(locEntry.combat)))
end
-- 功能：收集当前生效的失控（LoC）机制：按 locType + spellID 去重后逐条打印。
-- 入参：无。
-- 出参：无。
-- 说明：12.1 起 LoC 的 spellID / timeRemaining 可能是 secret value，所以每个字段都要先 issecretvalue 探一遍再用，读不到就用 "?" 占位。去重键用 locType 拼接 spellID，一条只打印一次（战斗中会被反复触发）。
local function collectLocTypes()
  if not (C_LossOfControl and C_LossOfControl.GetActiveLossOfControlDataCount) then
    return
  end
  local locCount = C_LossOfControl.GetActiveLossOfControlDataCount() or 0
  if locCount < 1 then
    return
  end
  local inCombat = InCombatLockdown and InCombatLockdown() or false
  for locIndex = 1, locCount, 1 do
    local locData = C_LossOfControl.GetActiveLossOfControlData(locIndex)
    if locData and (locData.locType and not issecretvalue(locData.locType)) then
      local spellID = locData.spellID and not issecretvalue(locData.spellID) and locData.spellID or "?"
      local locEntry = {
        locType = locData.locType,
        spellID = spellID,
        remain = locData.timeRemaining and not issecretvalue(locData.timeRemaining) and locData.timeRemaining or "?",
        combat = inCombat,
      }
      local locKey = tostring(locData.locType) .. "\031" .. tostring(spellID)
      if not locEntries[locKey] then
        locEntries[locKey] = locEntry
        printLocEntry(locData.locType, locEntry)
      end
    end
  end
end
local locEventFrame = CreateFrame("Frame")
locEventFrame:RegisterEvent("LOSS_OF_CONTROL_ADDED")
locEventFrame:RegisterEvent("LOSS_OF_CONTROL_UPDATE")
locEventFrame:RegisterEvent("PLAYER_CONTROL_LOST")
locEventFrame:SetScript("OnEvent", function()
  if not isLocCollecting then
    return
  end
  collectLocTypes()
  if C_Timer and C_Timer.After then
    C_Timer.After(0, collectLocTypes)
  end
end)
SLASH_PMSLOC1 = "/pmsloc"
SlashCmdList.PMSLOC = function(input)
  input = ((input or "")):trim():lower()
  if input == "dump" then
    local locCount = 0
    for locKey in pairs(locEntries) do
      locCount = locCount + 1
    end
    print("|cff00ff00[pmsloc]|r 已收集 " .. locCount .. " 条 locType：")
    for locKey, locData in pairs(locEntries) do
      printLocEntry(locData.locType, locData)
    end
    return
  end
  isLocCollecting = not isLocCollecting
  print("|cff00ff00[pmsloc]|r LoC 收集器: " .. (isLocCollecting and "|cff00ff00开|r" or "|cffff0000关|r"))
  if isLocCollecting then
    collectLocTypes()
  end
end
