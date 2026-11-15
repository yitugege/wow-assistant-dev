-- ==========================================================================
-- 文件：CoreControls.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 3361-3616 行（不含注册表）），语句与顺序未改。
-- 作用：控制键冲突检测、按键状态判断、通用样式按钮、停靠窗与开关类斜杠命令。
-- 加载：TOC 中位于 Core.lua 之后；只使用 WowBuddyDev 全局表。
-- ==========================================================================
-- ---- 以下为原 Core.lua 内容 ----
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreControls", { "CoreSettings", "CoreState", "CoreClassData", "CoreLocale", "Bindings", "ActionKeyCheck", "RaidFocus", "SettingsUI", "PixelBar" }) or _G.WowBuddyDev -- @@注册表命名空间@@
do
  local cachedActionToKey, cachedActionKeyOrder, cachedGetRaidFocusKeys, cachedRaidFocusEnabled
  local keyOwners = {}
  -- 功能：作废「按键归属」缓存，下次查询时重建。
  -- 入参：无。
  -- 出参：无。
  -- 说明：职业数据或动作键表换过之后必须调一次，否则冲突检测会拿着上一套按键表的结果，把撞键判断错。
  function WowBuddyDev.InvalidateControlBindingConflicts()
    cachedActionToKey = nil
  end
  -- 功能：查某个按键被谁占用了（普通动作键还是团队焦点键）。
  -- 入参：key 按键字符串。
  -- 出参：占用方类型（"action" 动作键 / "raid" 团队焦点键）和它的序号；空按键或没人占用时返回 nil。
  -- 说明：整张归属表按「动作键表、按键顺序表、GetRaidFocusKeys、团队焦点是否开启」四个引用做缓存，四者都没变就不重建——这个函数在按键检测里调用很频繁，每次重建会很费。普通动作键优先登记，团队焦点键和它撞车时不会覆盖它。
  function WowBuddyDev.GetControlBindingConflict(key)
    if not key or key == "" then
      return nil
    end
    local raidFocusEnabled = WowBuddyDev.classData and WowBuddyDev.classData.raidFocusEnabled == true or false
    if cachedActionToKey ~= WowBuddyDev.ACTION_TO_KEY or cachedActionKeyOrder ~= WowBuddyDev.ACTION_KEY_ORDER or cachedGetRaidFocusKeys ~= WowBuddyDev.GetRaidFocusKeys or cachedRaidFocusEnabled ~= raidFocusEnabled then
      keyOwners = {}
      for _, boundKey in ipairs(WowBuddyDev.GetClassMacroKeys and WowBuddyDev.GetClassMacroKeys() or {}) do
        keyOwners[WowBuddyDev.NormalizeActionKey(boundKey)] = { "action", boundKey }
      end
      for k14, boundKey in pairs(WowBuddyDev.ACTION_TO_KEY or {}) do
        keyOwners[WowBuddyDev.NormalizeActionKey(boundKey)] = { "action", k14 }
      end
      if raidFocusEnabled and WowBuddyDev.GetRaidFocusKeys then
        for index20, raidFocusKey in ipairs(WowBuddyDev.GetRaidFocusKeys()) do
          local normalizedKey = WowBuddyDev.NormalizeActionKey(raidFocusKey)
          if not keyOwners[normalizedKey] then
            keyOwners[normalizedKey] = { "raid", index20 }
          end
        end
      end
      cachedActionToKey = WowBuddyDev.ACTION_TO_KEY
      cachedActionKeyOrder = WowBuddyDev.ACTION_KEY_ORDER
      cachedGetRaidFocusKeys = WowBuddyDev.GetRaidFocusKeys
      cachedRaidFocusEnabled = raidFocusEnabled
    end
    local keyOwner = keyOwners[WowBuddyDev.NormalizeActionKey(key)]
    if keyOwner then
      return keyOwner[1], keyOwner[2]
    end
  end
end
WowBuddyDev.waitingForKey = nil
WowBuddyDev.masterKeyPressed = false
WowBuddyDev.burstKeyPressed = false
-- 功能：判断某个绑定名的按键此刻是不是真的按着（含修饰键状态校验）。
-- 入参：key 绑定名字符串，如 "SHIFT-BUTTON1"、"F1"。
-- 出参：true/false。
-- 说明：修饰键按严格相等比对——要求按住 Shift 时，没按或按了别的修饰键都算没按。主开关/爆发/群体这三个键如果和别人撞了绑定，直接返回 false，避免一次按键触发两套功能。鼠标键走 IsMouseButtonDown，键盘键走 IsKeyDown；旧客户端没有 IsKeyDown 时一律返回 false。
function WowBuddyDev.IsBindPressed(key)
  if not key or key == "" then
    return false
  end
  local db = WowBuddyDev.DB
  if db and ((key == db.masterKey or key == db.burstKey or key == db.aoeKey) and WowBuddyDev.GetControlBindingConflict(key)) then
    return false
  end
  local normalizedKey = key
  local needsShift, needsCtrl, needsAlt = false, false, false
  if normalizedKey:find("SHIFT%-") then
    needsShift = true
    normalizedKey = normalizedKey:gsub("SHIFT%-", "")
  end
  if normalizedKey:find("CTRL%-") then
    needsCtrl = true
    normalizedKey = normalizedKey:gsub("CTRL%-", "")
  end
  if normalizedKey:find("ALT%-") then
    needsAlt = true
    normalizedKey = normalizedKey:gsub("ALT%-", "")
  end
  local shiftDown = IsShiftKeyDown() and true or false
  local ctrlDown = IsControlKeyDown() and true or false
  local altDown = IsAltKeyDown() and true or false
  if shiftDown ~= needsShift then
    return false
  end
  if ctrlDown ~= needsCtrl then
    return false
  end
  if altDown ~= needsAlt then
    return false
  end
  if normalizedKey:find("^BUTTON") then
    local mouseButton = tonumber(normalizedKey:match("BUTTON(%d+)"))
    if mouseButton then
      return IsMouseButtonDown(mouseButton)
    end
    return false
  end
  if IsKeyDown then
    return IsKeyDown(normalizedKey)
  end
  return false
end
-- 功能：把按键名转成界面上显示的文字。
-- 入参：key 按键名。
-- 出参：按键名本身；空值时返回本地化的「未设置」。
-- 说明：只做空值兜底，按键名不做翻译——键名就是游戏里的物理键位，界面和提示都要显示原始名字。
function WowBuddyDev.GetKeyDisplayText(key)
  if not key or key == "" then
    return WowBuddyDev.L("未设置")
  end
  return key
end
-- 功能：建一个统一样式的按钮：隐藏原生材质，自绘背景、边框和文字，并带悬停高亮。
-- 入参：parent 父框；label 按钮文字（会过本地化）；width/height 尺寸（省略时 70×22）。
-- 出参：建好的 Button。
-- 说明：原生三张纹理只是设成全透明而不是取消，这样点击区域和按下反馈都还在。悬停时背景和边框变红、文字变白；离开时按 restoreTextColor 还原文字颜色，所以外部若改过文字颜色，必须同步更新这个字段，否则鼠标一进一出颜色就被还原成默认值。
function WowBuddyDev.CreateStyledButton(parent, label, width, height)
  local styledButton = CreateFrame("Button", nil, parent)
  styledButton:SetSize(width or 70, height or 22)
  local normalTexture = styledButton:GetNormalTexture()
  if normalTexture then
    normalTexture:SetAlpha(0)
  end
  local highlightTexture = styledButton:GetHighlightTexture()
  if highlightTexture then
    highlightTexture:SetAlpha(0)
  end
  local pushedTexture = styledButton:GetPushedTexture()
  if pushedTexture then
    pushedTexture:SetAlpha(0)
  end
  local backgroundTexture = styledButton:CreateTexture(nil, "BACKGROUND")
  backgroundTexture:SetAllPoints()
  backgroundTexture:SetColorTexture(0, 0, 0, 0)
  styledButton.bg = backgroundTexture
  local borderTexture = styledButton:CreateTexture(nil, "BORDER")
  borderTexture:SetPoint("TOPLEFT", -1, 1)
  borderTexture:SetPoint("BOTTOMRIGHT", 1, -1)
  borderTexture:SetColorTexture(0, 0, 0, 0)
  styledButton.border = borderTexture
  local labelText = styledButton:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  labelText:SetPoint("CENTER")
  labelText:SetText(WowBuddyDev.L(label or ""))
  labelText:SetTextColor(.9, .75, .35, 1)
  styledButton:SetFontString(labelText)
  styledButton.restoreTextColor = { .9, .75, .35, 1 }
  styledButton:SetScript("OnEnter", function(self7)
    self7.bg:SetColorTexture(.6, .1, .15, .9)
    self7.border:SetColorTexture(.8, .2, .25, 1)
    self7:GetFontString():SetTextColor(1, 1, 1, 1)
  end)
  styledButton:SetScript("OnLeave", function(self8)
    self8.bg:SetColorTexture(0, 0, 0, 0)
    self8.border:SetColorTexture(0, 0, 0, 0)
    local restoreTextColor = self8.restoreTextColor
    if restoreTextColor then
      self8:GetFontString():SetTextColor(restoreTextColor[1], restoreTextColor[2], restoreTextColor[3], restoreTextColor[4])
    end
  end)
  return styledButton
end
-- 功能：开或关主面板（/pms 命令的落点）。
-- 入参：无。
-- 出参：无。
-- 说明：面板还没建出来时直接返回，不会新建。从隐藏切到显示时顺手把页签切回第 1 页，避免上次停在的页签带着旧数据出现。
function WowBuddyDev.ToggleDock()
  if not WowBuddyDev.mainFrame then
    return
  end
  if WowBuddyDev.mainFrame:IsShown() then
    WowBuddyDev.mainFrame:Hide()
  else
    WowBuddyDev.mainFrame:Show()
    WowBuddyDev.SwitchTab(1)
  end
end
SLASH_MAOKELI1 = "/pms"
SlashCmdList.MAOKELI = WowBuddyDev.ToggleDock
SLASH_CHARU1 = "/charu"
-- 功能：/charu 命令：把「插入」压制的到期时间设成半秒之后。
-- 入参：无。
-- 出参：无。
-- 说明：这里不直接改开关，而是写一个到期时间戳，由渲染循环自己判断——未过期时强制把主开关当关闭处理，于是输出只停 0.5 秒就自动恢复，不需要再有人把它打开。
SlashCmdList.CHARU = function()
  _G.PermesCharuExpire = GetTime() + .5
end
SLASH_MKL_ON1 = "/ON"
-- 功能：/ON 命令：打开总开关并刷新界面。
-- 入参：无。
-- 出参：无。
-- 说明：直接写存档再调 UpdateMasterSwitchUI，界面、提示音和状态图标由它一并同步。
SlashCmdList.MKL_ON = function()
  WowBuddyDev.DB.masterSwitch = true
  if WowBuddyDev.UpdateMasterSwitchUI then
    WowBuddyDev.UpdateMasterSwitchUI(true)
  end
end
SLASH_MKL_OFF1 = "/OFF"
-- 功能：/OFF 命令：关闭总开关并刷新界面。
-- 入参：无。
-- 出参：无。
-- 说明：直接写存档再调 UpdateMasterSwitchUI；这条命令不会去动「整体隐藏」开关，只关总开关。
SlashCmdList.MKL_OFF = function()
  WowBuddyDev.DB.masterSwitch = false
  if WowBuddyDev.UpdateMasterSwitchUI then
    WowBuddyDev.UpdateMasterSwitchUI(false)
  end
end
SLASH_MKL_BFK1 = "/bfk"
-- 功能：/bfk 命令：打开爆发开关。
-- 入参：无。
-- 出参：无。
-- 说明：走 SetBurstSwitch，界面同步和「自动关闭」计时器由它一起处理，命令本身不碰计时器。
SlashCmdList.MKL_BFK = function()
  WowBuddyDev.SetBurstSwitch(true)
end
SLASH_MKL_BFG1 = "/bfg"
-- 功能：/bfg 命令：关闭爆发开关。
-- 入参：无。
-- 出参：无。
-- 说明：走 SetBurstSwitch，关掉之后自动关闭计时器也会被一并取消。
SlashCmdList.MKL_BFG = function()
  WowBuddyDev.SetBurstSwitch(false)
end
SLASH_MKL_DAN1 = "/dan"
-- 功能：/dan 命令：把 AOE 模式切成「单体」。
-- 入参：无。
-- 出参：无。
-- 说明：AOE 模式取值约定是 0 自动、1 单体、2 群体；改完调 UpdateAoeModeUI 同步图标和提示。
SlashCmdList.MKL_DAN = function()
  WowBuddyDev.DB.aoeMode = 1
  if WowBuddyDev.UpdateAoeModeUI then
    WowBuddyDev.UpdateAoeModeUI(1)
  end
end
SLASH_MKL_QUN1 = "/qun"
-- 功能：/qun 命令：把 AOE 模式切成「群体」。
-- 入参：无。
-- 出参：无。
-- 说明：AOE 模式取值约定是 0 自动、1 单体、2 群体；改完调 UpdateAoeModeUI 同步图标和提示。
SlashCmdList.MKL_QUN = function()
  WowBuddyDev.DB.aoeMode = 2
  if WowBuddyDev.UpdateAoeModeUI then
    WowBuddyDev.UpdateAoeModeUI(2)
  end
end
SLASH_MKL_AUTO1 = "/AUTO"
-- 功能：/AUTO 命令：把 AOE 模式切回「自动」（/zi 是同一个函数的别名）。
-- 入参：无。
-- 出参：无。
-- 说明：AOE 模式取值约定是 0 自动、1 单体、2 群体；改完调 UpdateAoeModeUI 同步图标和提示。
SlashCmdList.MKL_AUTO = function()
  WowBuddyDev.DB.aoeMode = 0
  if WowBuddyDev.UpdateAoeModeUI then
    WowBuddyDev.UpdateAoeModeUI(0)
  end
end
SLASH_MKL_ZI1 = "/zi"
SlashCmdList.MKL_ZI = SlashCmdList.MKL_AUTO
WowBuddyDev.RegisterModule("CoreControls", { "Core" })
