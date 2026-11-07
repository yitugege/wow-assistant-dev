-- ==========================================================================
-- 文件：01b1a6.lua
-- 来源：P07483180.rar → P07483180/01b1a6.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：01b1a6.lua → CDMImport.lua（按功能重命名）
-- 作用：冷却管理器(CDM)配置导入 + LibSharedMedia 字体注册
-- ==========================================================================
local cachedDB = nil
local s = "default"
local VIEWER_FRAME_NAMES = { "EssentialCooldownViewer", "UtilityCooldownViewer", "BuffIconCooldownViewer", "BuffBarCooldownViewer" }
local migrateDB
-- 功能：懒加载并返回 SavedVariables 数据库表（cdmStateSaverDB）。
-- 入参：无。
-- 出参：数据库表。
-- 说明：优先挂在 P07483180.DB 下，插件核心没加载时退回全局 CDMStateSaverDB；首次取用时先跑 migrateDB 升级结构。注意：cachedDB 缓存的是表引用，之后不再重新查 _G，只有 /reload 才会刷新。
local function getDB()
  if not cachedDB then
    if _G.WowBuddyDev and _G.WowBuddyDev.DB then
      _G.WowBuddyDev.DB.cdmStateSaverDB = _G.WowBuddyDev.DB.cdmStateSaverDB or {}
      cachedDB = _G.WowBuddyDev.DB.cdmStateSaverDB
    else
      _G.CDMStateSaverDB = _G.CDMStateSaverDB or {}
      cachedDB = _G.CDMStateSaverDB
    end
    migrateDB()
  end
  return cachedDB
end
local DEFAULT_COOLDOWN_FONT_SIZE = {
  EssentialCooldownViewer = 16,
  UtilityCooldownViewer = 16,
  BuffIconCooldownViewer = 16,
  BuffBarCooldownViewer = 16,
}
local DEFAULT_STACK_FONT_SIZE = {
  EssentialCooldownViewer = 16,
  UtilityCooldownViewer = 14,
  BuffIconCooldownViewer = 14,
  BuffBarCooldownViewer = 14,
}
local getBuffIconHideWhenInactive
-- 功能：把旧版扁平存储升级成 profiles 结构，并补齐字体/自动恢复等默认字段。
-- 入参：无。
-- 出参：无（就地修改数据库表）。
-- 说明：只在数据库首次加载时由 getDB 调用一次；fontVersion < 3 时清空 fontFlags/fontSize 并重建两张字号表，因为 viewerChild 起冷却字号和层数字号改成按 viewer 分开存。
migrateDB = function()
  local db = getDB()
  if db.dataConfig and not db.profiles then
    db.profiles = {
      default = {
        dataConfig = db.dataConfig,
        positions = db.positions,
        editModeSettings = db.editModeSettings,
        savedAt = db.dataSavedAt or time(),
      },
    }
    db.dataConfig = nil
    db.positions = nil
    db.editModeSettings = nil
    db.dataSavedAt = nil
    db.editModeSavedAt = nil
  end
  db.profiles = db.profiles or {}
  db.activeProfile = db.activeProfile or "default"
  s = db.activeProfile
  if db.autoRestore == nil then
    db.autoRestore = false
  end
  db.cooldownFontSize = db.cooldownFontSize or {}
  db.stackFontSize = db.stackFontSize or {}
  if not db.fontVersion or db.fontVersion < 3 then
    db.fontFlags = nil
    db.fontSize = nil
    db.cooldownFontSize = {}
    db.stackFontSize = {}
    db.fontVersion = 3
  end
end
-- 功能：按名字取一份保存的配置档。
-- 入参：profileName 配置档名，省略或为空时用当前档名（s，即 activeProfile）。
-- 出参：配置档表；不存在时返回 nil。
-- 说明：先把 profiles 兜底成空表，避免旧存档没有这个字段时报错。
local function getProfile(profileName)
  local db = getDB()
  db.profiles = db.profiles or {}
  return db.profiles[profileName or s or "default"]
end
-- 功能：写入或覆盖一份配置档，并把它切成当前档。
-- 入参：profileName 配置档名；profile 配置档表。
-- 出参：无。
-- 说明：内存里的 activeProfile 和 s 一起更新，导入完成后 getProfile 省略参数才会拿到刚写进去的这份。
local function setProfile(profileName, profile)
  local db = getDB()
  db.profiles = db.profiles or {}
  db.profiles[profileName] = profile
  s = profileName
  db.activeProfile = profileName
end
-- 功能：确认冷却管理器 API 可用，必要时主动加载 Blizzard_CooldownViewer。
-- 入参：无。
-- 出参：布尔（C_CooldownViewer 及其 GetLayoutData/SetLayoutData 都在时为真）。
-- 说明：新版客户端把 C_CooldownViewer 放在可延迟加载的暴雪插件里，所以第一次取不到时要 pcall 加载一次再复查；加载失败也不抛错，只返回假值。
local function ensureCooldownViewerReady()
  local cooldownViewer = _G.C_CooldownViewer
  if cooldownViewer and (cooldownViewer.GetLayoutData and cooldownViewer.SetLayoutData) then
    return true
  end
  local loadAddOnFunc = _G.C_AddOns and _G.C_AddOns.LoadAddOn or _G.LoadAddOn
  if loadAddOnFunc then
    pcall(loadAddOnFunc, "Blizzard_CooldownViewer")
  end
  cooldownViewer = _G.C_CooldownViewer
  return cooldownViewer and (cooldownViewer.GetLayoutData and cooldownViewer.SetLayoutData)
end
-- 功能：取当前配置的自定义字体路径。
-- 入参：无。
-- 出参：字体路径字符串。
-- 说明：没设置过就用插件自带字体 Fonts\2B518D9B.ttf（该字体在文件开头已注册进 LibSharedMedia）。
local function getFontPath()
  local db = getDB()
  return db and db.fontPath or "Fonts\\2B518D9B.ttf"
end
local sharedMediaHandle = LibStub and LibStub("LibSharedMedia-3.0", true)
if sharedMediaHandle then
  sharedMediaHandle:Register("font", "WowBuddyDev", "Fonts\\2B518D9B.ttf")
end
-- 功能：试探某个字体路径客户端能不能加载。
-- 入参：fontPath 字体路径。
-- 出参：布尔（SetFont 的 pcall 结果）。
-- 说明：建一个临时 FontString 试 SetFont，探针用完立即 Hide，不会显示；路径为空直接判假。
local function isFontLoadable(fontPath)
  if not fontPath or fontPath == "" then
    return false
  end
  local probeFontString = UIParent:CreateFontString(nil, "OVERLAY")
  local ok = pcall(function()
    probeFontString:SetFont(fontPath, 12, "")
  end)
  probeFontString:Hide()
  return ok
end
-- 功能：取字体描边标志。
-- 入参：无。
-- 出参：flags 字符串。
-- 说明：没设置过用 THICKOUTLINE（默认值同时写在 applyFont 的兜底分支里）。
local function getFontFlags()
  local db = getDB()
  return db.fontFlags or "THICKOUTLINE"
end
-- 功能：取基础字号。
-- 入参：无。
-- 出参：数字。
-- 说明：没设置过用 18。
local function getFontSize()
  local db = getDB()
  return db and db.fontSize or 18
end
-- 功能：取某个 viewer 的冷却倒计时字号。
-- 入参：viewerName 冷却管理器框体名（如 EssentialCooldownViewer）。
-- 出参：字号数字。
-- 说明：优先玩家设置，其次 DEFAULT_COOLDOWN_FONT_SIZE，最后兜底 16。
local function getCooldownFontSize(viewerName)
  local db = getDB()
  local customSize = db.cooldownFontSize and db.cooldownFontSize[viewerName]
  if customSize then
    return customSize
  end
  return DEFAULT_COOLDOWN_FONT_SIZE[viewerName] or 16
end
-- 功能：取某个 viewer 的层数/充能数字号。
-- 入参：viewerName 冷却管理器框体名。
-- 出参：字号数字。
-- 说明：优先玩家设置，其次 DEFAULT_STACK_FONT_SIZE，最后兜底 14。
local function getStackFontSize(viewerName)
  local db = getDB()
  local customSize = db.stackFontSize and db.stackFontSize[viewerName]
  if customSize then
    return customSize
  end
  return DEFAULT_STACK_FONT_SIZE[viewerName] or 14
end
-- 功能：给一个 FontString 换字体，兼容 .ttf 与 .ttc 两种写法。
-- 入参：fontString 目标 FontString；fontPath 字体路径；fontSize 字号（省略时用 getFontSize）；setWhite 为真时把文本设成白色。
-- 出参：无。
-- 说明：GetFont 读不到描边时用 getFontFlags；依次尝试 路径、路径:0、同名.ttc、同名.ttc:0 四种写法（不同客户端支持的写法不一样），全失败再退回 GameFontNormal 的字体。风险：全程 pcall，路径写错只是字体没生效，不会报错刷屏。
local function applyFont(fontString, fontPath, fontSize, setWhite)
  if not fontString then
    return
  end
  local currentFont, currentSize, currentFlags = fontString:GetFont()
  local flags = currentFlags or getFontFlags()
  local fontCandidates = { fontPath, fontPath .. ":0", fontPath:gsub("%.ttf$", ".ttc"), fontPath:gsub("%.ttf$", ".ttc") .. ":0" }
  for index, v in ipairs(fontCandidates) do
    local ok = pcall(function()
      fontString:SetFont(v, fontSize or getFontSize(), flags)
    end)
    if ok then
      if setWhite then
        pcall(function()
          fontString:SetTextColor(1, 1, 1, 1)
        end)
      end
      return
    end
  end
  local fallbackFont = select(1, GameFontNormal:GetFont())
  if fallbackFont then
    pcall(function()
      fontString:SetFont(fallbackFont, fontSize or getFontSize(), flags)
    end)
  end
end
-- 功能：用临时 FontString 量一段文本的像素宽高，并换算成屏幕占比。
-- 入参：fontPath 字体路径；fontSize 字号；text 文本（默认 0:00）；fontFlags 描边标志。
-- 出参：宽、高、宽/UIParent宽、高/UIParent高；字体加载失败时返回 0, 0, 0, 0。
-- 说明：量完就 Hide 探针；归一化到 UIParent 是为了让读取端按屏幕比例复原格子几何，不随分辨率变。
local function measureText(fontPath, fontSize, text, fontFlags)
  fontFlags = fontFlags or ""
  text = text or "0:00"
  local probeFontString = UIParent:CreateFontString(nil, "OVERLAY")
  local ok = pcall(function()
    probeFontString:SetFont(fontPath, fontSize, fontFlags)
  end)
  if not ok then
    probeFontString:Hide()
    return 0, 0, 0, 0
  end
  probeFontString:SetText(text)
  local textWidth = probeFontString:GetStringWidth()
  local textHeight = probeFontString:GetStringHeight()
  probeFontString:Hide()
  local uiWidth, uiHeight = UIParent:GetWidth(), UIParent:GetHeight()
  return textWidth, textHeight, textWidth / uiWidth, textHeight / uiHeight
end
-- 功能：量出 viewer 文本的最大宽高：冷却时间按 0:00、层数按 99 各量一次后取大值。
-- 入参：无。
-- 出参：最大宽、最大高、归一化宽、归一化高、冷却字号、层数字号。
-- 说明：取 99 是因为层数最多两位；换字体或改字号后几何会变，所以每次都要重新量，不能缓存。
local function measureViewerTextMetrics()
  local fontPath = getFontPath()
  local fontFlags = getFontFlags()
  local db = getDB()
  local cooldownFontSize = db.cooldownFontSize or 16
  local stackFontSize = db.stackFontSize or 14
  local cdWidth, cdHeight, cdRelWidth, cdRelHeight = measureText(fontPath, cooldownFontSize, "0:00", fontFlags)
  local stackTextWidth, stackTextHeight, stackRelWidth, stackRelHeight = measureText(fontPath, stackFontSize, "99", fontFlags)
  local maxTextWidth = math.max(cdWidth, stackTextWidth)
  local maxTextHeight = math.max(cdHeight, stackTextHeight)
  local uiWidth, uiHeight = UIParent:GetWidth(), UIParent:GetHeight()
  return maxTextWidth, maxTextHeight, maxTextWidth / uiWidth, maxTextHeight / uiHeight, cooldownFontSize, stackFontSize
end
-- 功能：把一个 FontString 重新锚到父框的指定角上。
-- 入参：fontString 目标 FontString；point 锚点（默认 BOTTOMRIGHT）；offsetX 相对 X；offsetY 相对 Y；relativeFrame 相对框（默认取 FontString 自己的父框）。
-- 出参：无。
-- 说明：先校验对象类型是 FontString、父框存在，再 ClearAllPoints + SetPoint，整段 pcall 兜住暴雪改框体结构。风险：不做类型校验时，暴雪把子对象换成非 FontString 会直接报错刷屏。
local function anchorFontString(fontString, point, offsetX, offsetY, relativeFrame)
  if not fontString then
    return
  end
  if type(fontString) ~= "table" or not fontString.GetObjectType then
    return
  end
  local objectType = fontString:GetObjectType()
  if objectType ~= "FontString" then
    return
  end
  relativeFrame = relativeFrame or fontString:GetParent()
  if not relativeFrame then
    return
  end
  pcall(function()
    fontString:ClearAllPoints()
    fontString:SetPoint(point or "BOTTOMRIGHT", relativeFrame, point or "BOTTOMRIGHT", offsetX or 0, offsetY or 0)
  end)
end
-- 功能：把所有 viewer 的充能数/层数文本重新锚到图标右下角。
-- 入参：无。
-- 出参：无。
-- 说明：战斗中改框体位置会被保护，直接返回；只处理 Essential 的 ChargeCount 和 BuffIcon 的 Applications 两种结构（各版本客户端的子对象结构不一样），取子对象那段用 pcall 包住。
local function reanchorViewerTexts()
  if InCombatLockdown() then
    return
  end
  for index2, viewerName in ipairs(VIEWER_FRAME_NAMES) do
    local viewerFrame = _G[viewerName]
    if viewerFrame then
      for index3, viewerChild in ipairs({ viewerFrame:GetChildren() }) do
        if viewerName == "EssentialCooldownViewer" and (viewerChild.ChargeCount and viewerChild.ChargeCount.Current) then
          pcall(anchorFontString, viewerChild.ChargeCount.Current, "BOTTOMRIGHT", 0, 0, viewerChild)
        end
        if viewerName == "BuffIconCooldownViewer" and (viewerChild.Applications and viewerChild.Applications.Applications) then
          pcall(anchorFontString, viewerChild.Applications.Applications, "BOTTOMRIGHT", 0, 0, viewerChild)
        end
      end
    end
  end
end
-- 功能：判断一个 viewer 框体对象是否初始化完成、可以取子对象。
-- 入参：frameObject 框体对象。
-- 出参：布尔。
-- 说明：对象为空返回假；有 IsInitialized 且返回假时也返回假 —— 这种状态下去取 Cooldown/ChargeCount 会报错。
local function isViewerReady(frameObject)
  if not frameObject then
    return false
  end
  if frameObject.IsInitialized and not frameObject:IsInitialized() then
    return false
  end
  return true
end
-- 功能：只改 FontString 的字号，保留原字体和描边。
-- 入参：fontString 目标 FontString；newFontSize 新字号。
-- 出参：pcall 结果（布尔）。
-- 说明：先用 pcall 取回 GetFont 的四个返回值再改字号（暴雪某些 FontString 的 GetFont 会抛错）；描边为空时补空串，避免 SetFont 报参数错。
local function applyFontSize(fontString, newFontSize)
  if not fontString or not fontString.GetFont or not fontString.SetFont then
    return false
  end
  local getFontOk, fontPath, fontSize, fontFlags = pcall(fontString.GetFont, fontString)
  if not getFontOk or not fontPath then
    return false
  end
  return pcall(fontString.SetFont, fontString, fontPath, newFontSize, fontFlags or "")
end
-- 功能：按默认字号刷新一个 viewer 里所有冷却/层数文本的字号，返回成功条数。
-- 入参：viewerName 冷却管理器框体名。
-- 出参：成功改写的文本条数。
-- 说明：viewer 未就绪直接返回 0；文本分散在 Cooldown、ChargeCount、Applications、Icon.Applications、Bar.Duration 五处，逐处取到才改；计数走 applyFontSizeAndCount 闭包。
local function applyViewerFonts(viewerName)
  local viewerFrame = _G[viewerName]
  if not isViewerReady(viewerFrame) then
    return 0
  end
  local appliedCount = 0
  local cooldownFontSize = getCooldownFontSize(viewerName)
  local stackFontSize = getStackFontSize(viewerName)
  -- 功能：改字号并给成功次数加一的计数闭包。
  -- 入参：fontString 目标 FontString；fontSize 字号。
  -- 出参：无。
  -- 说明：写成闭包是为了在 applyViewerFonts 的循环里累计成功条数（appliedCount 是它的 upvalue）。
  local function applyFontSizeAndCount(fontString, fontSize)
    if applyFontSize(fontString, fontSize) then
      appliedCount = appliedCount + 1
    end
  end
  for index4, viewerChild in ipairs({ viewerFrame:GetChildren() }) do
    if viewerChild.Cooldown and viewerChild.Cooldown.GetCountdownFontString then
      applyFontSizeAndCount(viewerChild.Cooldown:GetCountdownFontString(), cooldownFontSize)
    end
    if viewerChild.ChargeCount and viewerChild.ChargeCount.Current then
      applyFontSizeAndCount(viewerChild.ChargeCount.Current, stackFontSize)
    end
    if viewerChild.Applications and viewerChild.Applications.Applications then
      applyFontSizeAndCount(viewerChild.Applications.Applications, stackFontSize)
    end
    if viewerChild.Icon and viewerChild.Icon.Applications then
      applyFontSizeAndCount(viewerChild.Icon.Applications, stackFontSize)
    end
    if viewerChild.Bar and viewerChild.Bar.Duration then
      applyFontSizeAndCount(viewerChild.Bar.Duration, cooldownFontSize)
    end
  end
  return appliedCount
end
-- 功能：给一个 viewer 套上自定义字体文件：冷却文本用冷却字号，层数文本用层数字号。
-- 入参：viewerName 冷却管理器框体名。
-- 出参：布尔（viewer 未就绪时返回假）。
-- 说明：与 applyViewerFonts 的区别是这里连字体文件一起换；只处理同时带 Icon 和 Cooldown 的子对象，.ttc 写法和退回字体交给 applyFont。
local function applyViewerCustomFont(viewerName)
  local viewerFrame = _G[viewerName]
  if not isViewerReady(viewerFrame) then
    return false
  end
  local fontPath = getFontPath()
  local cooldownFontSize = getCooldownFontSize(viewerName)
  local stackFontSize = getStackFontSize(viewerName)
  for index5, viewerChild in ipairs({ viewerFrame:GetChildren() }) do
    if viewerChild.Icon and viewerChild.Cooldown then
      if viewerChild.Cooldown.GetCountdownFontString then
        local countdownText = viewerChild.Cooldown:GetCountdownFontString()
        applyFont(countdownText, fontPath, cooldownFontSize, true)
      end
      if viewerChild.ChargeCount and viewerChild.ChargeCount.Current then
        applyFont(viewerChild.ChargeCount.Current, fontPath, stackFontSize, false)
      end
      if viewerChild.Applications and viewerChild.Applications.Applications then
        applyFont(viewerChild.Applications.Applications, fontPath, stackFontSize, false)
      end
    end
  end
  return true
end
-- 功能：对全部 viewer 应用自定义字体，然后重新锚定文本位置。
-- 入参：无。
-- 出参：无。
-- 说明：战斗中改字体同样受保护，先打印中文提示并返回，让玩家脱战重试。
local function refreshAllViewerFonts()
  if InCombatLockdown() then
    print("|cffff0000[WowBuddyDev CDM]|r 战斗中无法修改字体，请脱战后重试")
    return
  end
  for index6, viewerName in ipairs(VIEWER_FRAME_NAMES) do
    applyViewerCustomFont(viewerName)
  end
  reanchorViewerTexts()
end
-- 功能：保存字体路径与描边标志并立刻应用到所有 viewer。
-- 入参：fontPath 字体路径（可为 nil）；fontFlags 描边标志（可为 nil）。
-- 出参：无。
-- 说明：两个参数都可空，只覆盖真正传进来的那一项 —— 否则 /cdms font 会把描边设置一起清掉。
local function setFontAndFlags(fontPath, fontFlags)
  local db = getDB()
  if fontPath and fontPath ~= "" then
    db.fontPath = fontPath
  end
  if fontFlags then
    db.fontFlags = fontFlags
  end
  refreshAllViewerFonts()
  reanchorViewerTexts()
end
-- 功能：设置基础字号（/cdms fontsize 数字）。
-- 入参：sizeText 字号文本。
-- 出参：无。
-- 说明：tonumber 后必须大于 0 才写入，否则只打印用法；改完立刻刷新字体和锚点。
local function setBaseFontSize(sizeText)
  local db = getDB()
  local fontSize = tonumber(sizeText)
  if fontSize and fontSize > 0 then
    db.fontSize = fontSize
    refreshAllViewerFonts()
    reanchorViewerTexts()
  else
    print("用法: /cdms fontsize <数字>    例: /cdms fontsize 22")
  end
end
-- 功能：判断编辑模式里冷却管理器相关的 API 是否齐全。
-- 入参：无。
-- 出参：链式 and 的真值（只当条件用，不保证是 boolean）。
-- 说明：C_EditMode.GetLayouts、C_EditMode.SaveLayouts 和 Enum.EditModeSystem.CooldownViewer 缺一个就不能用，直接返回假值。
local function isEditModeApiAvailable()
  return C_EditMode and (C_EditMode.GetLayouts and (C_EditMode.SaveLayouts and (Enum and (Enum.EditModeSystem and Enum.EditModeSystem.CooldownViewer))))
end
-- 功能：从编辑模式的 layouts 里取出当前生效的那份布局表。
-- 入参：editModeLayouts C_EditMode.GetLayouts() 的返回表。
-- 出参：布局表；取不到返回 nil。
-- 说明：先把 EditModePresetLayoutManager 的预设布局拼到 layouts 后面（改版后预设布局不在这张表里，位置会对不上），再按 activeLayout 直接命中、退一位、进一位，最后按 layoutID 全表扫描。
local function getActiveLayout(editModeLayouts)
  if not editModeLayouts or not editModeLayouts.layouts then
    return nil
  end
  if EditModePresetLayoutManager and EditModePresetLayoutManager.GetCopyOfPresetLayouts then
    local presetLayouts = EditModePresetLayoutManager:GetCopyOfPresetLayouts()
    if type(presetLayouts) == "table" and type(editModeLayouts.layouts) == "table" then
      local mergedLayouts = {}
      for index7, presetLayout in ipairs(presetLayouts) do
        mergedLayouts[index7] = presetLayout
      end
      local presetCount = #presetLayouts
      for index8, customLayout in ipairs(editModeLayouts.layouts) do
        mergedLayouts[presetCount + index8] = customLayout
      end
      editModeLayouts.layouts = mergedLayouts
    end
  end
  local activeLayoutID = editModeLayouts.activeLayout
  if activeLayoutID == nil then
    return nil
  end
  local activeLayout = editModeLayouts.layouts[activeLayoutID]
  if activeLayout then
    return activeLayout
  end
  activeLayout = editModeLayouts.layouts[activeLayoutID + 1]
  if activeLayout then
    return activeLayout
  end
  activeLayout = editModeLayouts.layouts[activeLayoutID - 1]
  if activeLayout then
    return activeLayout
  end
  for index9, candidateLayout in ipairs(editModeLayouts.layouts) do
    if candidateLayout.layoutID == activeLayoutID then
      return candidateLayout
    end
  end
  return nil
end
-- 功能：取追踪增益效果（BuffIcon）在编辑模式里的 systemIndex。
-- 入参：无。
-- 出参：数字。
-- 说明：Enum.EditModeCooldownViewerSystemIndices 在老客户端可能不存在，缺了按 3 处理。
local function getBuffIconSystemIndex()
  if Enum.EditModeCooldownViewerSystemIndices and Enum.EditModeCooldownViewerSystemIndices.BuffIcon then
    return Enum.EditModeCooldownViewerSystemIndices.BuffIcon
  end
  return 3
end
local HIDE_WHEN_INACTIVE_SETTING_ID = 8
-- 功能：把 systemIndex 反查成枚举名，方便打印。
-- 入参：systemIndex 编辑模式里的系统序号。
-- 出参：枚举名字符串；查不到返回 unknown(数字)。
-- 说明：只给 /cdms inspect 的诊断输出用，不参与任何逻辑判断。
local function getSystemIndexName(systemIndex)
  if not Enum.EditModeCooldownViewerSystemIndices then
    return "unknown"
  end
  for k, indexValue in pairs(Enum.EditModeCooldownViewerSystemIndices) do
    if indexValue == systemIndex then
      return k
    end
  end
  return "unknown(" .. tostring(systemIndex) .. ")"
end
-- 功能：把当前生效布局里冷却管理器各 system 的设置逐条打印出来。
-- 入参：无。
-- 出参：无（只打印）。
-- 说明：纯诊断（/cdms inspect）；编辑模式 API 不可用、取不到 layouts 或取不到 active layout 时打印中文提示后返回。
local function inspectEditModeSettings()
  if not isEditModeApiAvailable() then
    print("|cffff0000[WowBuddyDev]|r EditMode API 不可用")
    return
  end
  local editModeLayouts = C_EditMode.GetLayouts()
  if not editModeLayouts or not editModeLayouts.layouts then
    print("|cffff0000[WowBuddyDev]|r 无法获取 layouts")
    return
  end
  local activeLayout = getActiveLayout(editModeLayouts)
  if not activeLayout then
    print("|cffff0000[WowBuddyDev]|r 无法获取 active layout")
    return
  end
  print("|cff00ff00[WowBuddyDev]|r active layout: " .. tostring(activeLayout.layoutName) .. " type=" .. tostring(activeLayout.layoutType))
  if not activeLayout.systems then
    print("|cffff0000[WowBuddyDev]|r active layout 没有 systems")
    return
  end
  for index10, system in ipairs(activeLayout.systems) do
    if system.system == Enum.EditModeSystem.CooldownViewer then
      local indexName = getSystemIndexName(system.systemIndex)
      print("|cff888888[WowBuddyDev]|r system=" .. indexName .. " index=" .. tostring(system.systemIndex))
      if system.settings then
        for index11, setting in ipairs(system.settings) do
          print("|cff888888[WowBuddyDev]|r   setting=" .. tostring(setting.setting) .. " value=" .. tostring(setting.value))
        end
      end
    end
  end
end
-- 功能：读追踪增益效果（BuffIcon）在编辑模式里的隐藏开关当前值。
-- 入参：无。
-- 出参：true/false；编辑模式 API 不可用或找不到该 system 时返回 nil。
-- 说明：setting == HIDE_WHEN_INACTIVE_SETTING_ID 且 value == 1 才算开；nil 与 false 必须区分（nil 是读不到，调用方不能当成关）。注意：本文件顶部有同名 local 声明，所以这里的 function 写法是给那个局部变量赋值、不是定义全局函数（已核对没有别的文件调用同名全局）；CDMManager.GetBuffIconHideWhenInactive 就是它。
function getBuffIconHideWhenInactive()
  if not isEditModeApiAvailable() then
    return nil
  end
  local editModeLayouts = C_EditMode.GetLayouts()
  if not editModeLayouts or not editModeLayouts.layouts then
    return nil
  end
  local activeLayout = getActiveLayout(editModeLayouts)
  if not activeLayout or not activeLayout.systems then
    return nil
  end
  local buffIconSystemIndex = getBuffIconSystemIndex()
  for index12, system in ipairs(activeLayout.systems) do
    if system.system == Enum.EditModeSystem.CooldownViewer and system.systemIndex == buffIconSystemIndex then
      for index13, setting in ipairs(system.settings or {}) do
        if setting.setting == HIDE_WHEN_INACTIVE_SETTING_ID then
          return setting.value == 1
        end
      end
      return false
    end
  end
  return nil
end
-- 功能：让冷却管理器的设置面板刷新一次布局。
-- 入参：无。
-- 出参：布尔（战斗中或面板不存在时为假）。
-- 说明：优先调 CooldownViewerSettings:RefreshLayout（pcall 包住，面板还没建好时会抛错）；老客户端没有这个方法就返回假，交给调用方用定时器重试。
local function refreshViewerSettings()
  if InCombatLockdown() then
    return false
  end
  local settingsFrame = _G.CooldownViewerSettings
  if not settingsFrame then
    return false
  end
  if settingsFrame.RefreshLayout then
    pcall(settingsFrame.RefreshLayout, settingsFrame)
    return true
  end
  return false
end
-- 功能：取当前冷却管理器的布局数据串。
-- 入参：无。
-- 出参：字符串；API 不可用、战斗中或数据为空时返回 nil。
-- 说明：这是编辑模式布局的完整序列化串，存档、导出、职业-专精缓存都靠它。
local function getLayoutData()
  if not ensureCooldownViewerReady() then
    return nil
  end
  if InCombatLockdown() then
    return nil
  end
  local cooldownViewer = _G.C_CooldownViewer
  local layoutData = cooldownViewer.GetLayoutData()
  if type(layoutData) ~= "string" or layoutData == "" then
    return nil
  end
  return layoutData
end
-- 功能：应用一份编辑模式设置（当前实现只触发一次设置面板刷新）。
-- 入参：editModeSettings 编辑模式设置表（函数体内没有用到）。
-- 出参：无。
-- 说明：真正的刷新在 refreshViewerSettings；保留这个入口是为了和存档结构一一对应，也方便以后单独处理某项设置。
local function applyEditModeSettings(editModeSettings)
  if InCombatLockdown() then
    return
  end
  refreshViewerSettings()
end
local refreshRetryTimer = nil
-- 功能：把一段冷却管理器布局数据写回游戏，并让设置面板刷新。
-- 入参：layoutData 布局数据串。
-- 出参：真为 true；失败返回 false 加原因字符串（missing_data / cooldown_viewer_not_ready / in_combat / 异常文本）。
-- 说明：SetLayoutData 用 pcall 包住并把异常文本打印出来；刷新失败说明暴雪面板还没建好，用 1.5 秒定时器再试一次（refreshRetryTimer 保存定时器句柄，重入时先 Cancel）。
local function loadDataConfig(layoutData)
  if not layoutData then
    return false, "missing_data"
  end
  if not ensureCooldownViewerReady() then
    return false, "cooldown_viewer_not_ready"
  end
  if InCombatLockdown() then
    return false, "in_combat"
  end
  local cooldownViewer = _G.C_CooldownViewer
  local setOk, setErr = pcall(cooldownViewer.SetLayoutData, layoutData)
  if not setOk then
    print("|cffff0000[WowBuddyDev CDM]|r: 写入失败: " .. tostring(setErr))
    return false, tostring(setErr)
  end
  local refreshed = refreshViewerSettings()
  if not refreshed then
    if refreshRetryTimer then
      refreshRetryTimer:Cancel()
    end
    refreshRetryTimer = C_Timer.NewTimer(1.5, function()
      local retryRefreshed = refreshViewerSettings()
      refreshRetryTimer = nil
    end)
  end
  return true
end
-- 功能：把各 viewer 框体的位置记进配置档，坐标按 UIParent 尺寸归一化成 0~1。
-- 入参：selectedProfile 目标配置档（省略时取当前档）。
-- 出参：无。
-- 说明：归一化是为了换分辨率或改 UI 缩放后还能还原（写 normalized = true，读的时候再乘回去）；只取第一个锚点（GetPoint(1)），多点锚定的框体还原后会变成单点锚定。
local function captureViewerPositions(selectedProfile)
  local profile = selectedProfile or getProfile()
  if not profile then
    return
  end
  profile.positions = profile.positions or {}
  local uiWidth, uiHeight = UIParent:GetWidth(), UIParent:GetHeight()
  for index14, viewerName in ipairs(VIEWER_FRAME_NAMES) do
    local viewerFrame = _G[viewerName]
    if viewerFrame then
      local point, relativeTo, relativePoint, offsetX, offsetY = viewerFrame:GetPoint(1)
      profile.positions[viewerName] = {
        point = point,
        relativeTo = relativeTo and (relativeTo.GetName and relativeTo:GetName() or "UIParent") or "UIParent",
        relativePoint = relativePoint,
        x = offsetX and tonumber(string.format("%.4f", offsetX / uiWidth)) or 0,
        y = offsetY and tonumber(string.format("%.4f", offsetY / uiHeight)) or 0,
        normalized = true,
      }
    end
  end
end
-- 功能：把配置档里记录的 viewer 位置还原到框体上。
-- 入参：无。
-- 出参：布尔（没有位置数据时返回假）。
-- 说明：归一化过的坐标乘回 UIParent 宽高；relativeTo 存的是框体名，查不到就退回 UIParent；战斗中不改框体位置。
local function restoreViewerPositions()
  local profile = getProfile()
  if not profile or not profile.positions then
    return false
  end
  local uiWidth, uiHeight = UIParent:GetWidth(), UIParent:GetHeight()
  for index15, viewerName in ipairs(VIEWER_FRAME_NAMES) do
    local savedPosition = profile.positions[viewerName]
    local viewerFrame = _G[viewerName]
    if savedPosition and (viewerFrame and not InCombatLockdown()) then
      viewerFrame:ClearAllPoints()
      local relativeFrame = _G[savedPosition.relativeTo] or UIParent
      local offsetX = savedPosition.x
      local offsetY = savedPosition.y
      if savedPosition.normalized then
        offsetX = offsetX * uiWidth
        offsetY = offsetY * uiHeight
      end
      viewerFrame:SetPoint(savedPosition.point, relativeFrame, savedPosition.relativePoint, offsetX, offsetY)
    end
  end
  return true
end
-- 功能：抓取布局数据、编辑模式设置、字体设置和各 viewer 位置，存成一份命名配置档。
-- 入参：profileName 配置档名（省略时用当前档名，再兜底 default）。
-- 出参：真为 true；取不到布局数据时返回假。
-- 说明：布局串拿不到就直接放弃，免得存下一份没有 dataConfig 的空档；存完把当前档名切过去，所以 /cdms save 之后紧跟的导出/载入都针对新档。
local function saveProfile(profileName)
  profileName = profileName or s or "default"
  local layoutData = getLayoutData()
  if not layoutData then
    print("|cffff0000[WowBuddyDev CDM]|r: 数据配置保存失败")
    return false
  end
  local editModeSettings = ExtractEditModeSettings()
  local db = getDB()
  local profile = {
    dataConfig = layoutData,
    positions = {},
    editModeSettings = editModeSettings,
    savedAt = time(),
    class = select(2, UnitClass("player")),
    spec = GetSpecialization and GetSpecialization() or nil,
    cooldownFontSize = db.cooldownFontSize,
    stackFontSize = db.stackFontSize,
    fontPath = db.fontPath,
    fontFlags = db.fontFlags,
    fontSize = db.fontSize,
  }
  captureViewerPositions(profile)
  setProfile(profileName, profile)
  s = profileName
  return true
end
-- 功能：载入一份命名配置档：写回布局数据、编辑模式设置、字体设置，并还原框体位置。
-- 入参：profileName 配置档名（省略时用当前档名）。
-- 出参：真为 true；战斗中或档不存在时返回假。
-- 说明：字体文件先试探能否加载，加载不了只打印警告不中断（配置照样还原）；编辑模式设置写回后再用 C_EditMode.SetActiveLayout 让暴雪面板真正刷新一次。
local function loadProfile(profileName)
  if InCombatLockdown() then
    print("|cffff0000[CDM]|r 战斗中无法加载配置")
    return false
  end
  profileName = profileName or s or "default"
  s = profileName
  local activeProfileDB = getDB()
  activeProfileDB.activeProfile = profileName
  local profile = getProfile(profileName)
  if not profile then
    print("|cffff0000[WowBuddyDev CDM]|r: 未找到配置 '" .. profileName .. "'")
    return false
  end
  if profile.dataConfig then
    loadDataConfig(profile.dataConfig)
  end
  do
    local db = getDB()
    if profile.cooldownFontSize then
      db.cooldownFontSize = profile.cooldownFontSize
    end
    if profile.stackFontSize then
      db.stackFontSize = profile.stackFontSize
    end
    if profile.fontPath then
      db.fontPath = profile.fontPath
    end
    if profile.fontFlags then
      db.fontFlags = profile.fontFlags
    end
    if profile.fontSize then
      db.fontSize = profile.fontSize
    end
    local fontPath = getFontPath()
    if not isFontLoadable(fontPath) then
      print("|cffff0000[WowBuddyDev CDM]|r: 警告：字体文件 |cffffffff" .. fontPath .. "|r 不存在！")
    end
    for index16, viewerName in ipairs(VIEWER_FRAME_NAMES) do
      applyViewerCustomFont(viewerName)
    end
    reanchorViewerTexts()
  end
  if profile.editModeSettings then
    local applyResult = ApplyEditModeSettings(profile.editModeSettings)
    applyEditModeSettings(profile.editModeSettings)
    if not InCombatLockdown() and (C_EditMode and C_EditMode.SetActiveLayout) then
      local editModeLayouts = C_EditMode.GetLayouts()
      if editModeLayouts and editModeLayouts.activeLayout then
        local setActiveOk, setActiveErr = pcall(C_EditMode.SetActiveLayout, editModeLayouts.activeLayout)
        if not setActiveOk then
          print("|cffff0000[CDM]|r SetActiveLayout 失败: " .. tostring(setActiveErr))
        else

        end
      else
        print("|cffff0000[CDM]|r 无法获取 activeLayout 来刷新")
      end
    elseif InCombatLockdown() then
      print("|cffff0000[CDM]|r 战斗中跳过 SetActiveLayout")
    else
      print("|cffff0000[CDM]|r C_EditMode.SetActiveLayout 不可用")
    end
  else

  end
  restoreViewerPositions()
  if profile.class then

  end
  return true
end
-- 功能：把内部配置档压成导出用的短键表（viewerName 格式）。
-- 入参：profile 配置档表。
-- 出参：短键表；入参为空时返回 nil。
-- 说明：键名 d/p/e/c/s/cds/ss/fp/ff/fz 是导出格式的一部分（导入方按同样的键读），改这里的键名等于改协议，必须和 decodeProfilePayload 一起改。
local function encodeProfilePayload(profile)
  if not profile then
    return nil
  end
  return {
    v = 2,
    d = profile.dataConfig,
    p = profile.positions,
    e = profile.editModeSettings,
    c = profile.class,
    s = profile.spec,
    cds = profile.cooldownFontSize,
    ss = profile.stackFontSize,
    fp = profile.fontPath,
    ff = profile.fontFlags,
    fz = profile.fontSize,
  }
end
-- 功能：把配置档序列化、压缩、Base64 成 CDMSSv2| 开头的字符串，弹窗让玩家复制。
-- 入参：profileName 配置档名。
-- 出参：无（成功时弹 StaticPopupDialogs.CDMSS_COPY）。
-- 说明：先 saveProfile 落盘再导出，保证导出的是最新数据；C_EncodingUtil 或 CBOR/Deflate 任一不可用就打印失败提示。内层的 hashString/serializeTable/hashTable 是为内容指纹准备的，目前没有被调用（保留是为了不破坏原结构）。
local function exportProfile(profileName)
  profileName = profileName or s or "default"
  saveProfile(profileName)
  local profile = getProfile(profileName)
  if not profile then
    print("|cffff0000[WowBuddyDev CDM]|r: 保存配置失败，无法导出")
    return
  end
  -- 功能：对字符串算一个 31 进制滚动哈希（对 1000000007 取模）。
  -- 入参：text 字符串。
  -- 出参：哈希数字；入参不是字符串时返回 0。
  -- 说明：只取前 1000 个字符，避免超长配置串拖慢退出；给导出内容做指纹用。
  local function hashString(text)
    if type(text) ~= "string" then
      return 0
    end
    local hash = 0
    for i = 1, math.min(#text, 1000), 1 do
      hash = (hash * 31 + string.byte(text, i)) % 1000000007
    end
    return hash
  end
  -- 功能：把表递归拼成 键=值;键={...} 形式的确定性字符串。
  -- 入参：sourceTable 任意值。
  -- 出参：字符串。
  -- 说明：键先排序再拼接，否则同样的表每次得到的字符串都不同，哈希会漂；嵌套表用花括号包起来递归处理。
  local function serializeTable(sourceTable)
    if type(sourceTable) ~= "table" then
      return tostring(sourceTable)
    end
    local parts = {}
    local sortedKeys = {}
    for k2 in pairs(sourceTable) do
      table.insert(sortedKeys, k2)
    end
    table.sort(sortedKeys, function(keyA, keyB)
      return tostring(keyA) < tostring(keyB)
    end)
    for index17, key in ipairs(sortedKeys) do
      local value = sourceTable[key]
      if type(value) == "table" then
        table.insert(parts, tostring(key) .. "={" .. serializeTable(value) .. "}")
      else
        table.insert(parts, tostring(key) .. "=" .. tostring(value))
      end
    end
    return table.concat(parts, ";")
  end
  -- 功能：对表先序列化再算哈希，得到内容指纹。
  -- 入参：sourceTable 表。
  -- 出参：哈希数字。
  -- 说明：和 hashString 一起构成导出内容的校验和；当前版本没有任何地方调用它。
  local function hashTable(sourceTable)
    return hashString(serializeTable(sourceTable))
  end
  local payload = encodeProfilePayload(profile)
  if not payload then
    return
  end
  local encodingUtil = _G.C_EncodingUtil
  if encodingUtil and (encodingUtil.SerializeCBOR and (encodingUtil.CompressString and encodingUtil.EncodeBase64)) then
    local serializeOk, serialized = pcall(encodingUtil.SerializeCBOR, payload)
    if serializeOk and serialized then
      local compressOk, compressed = pcall(encodingUtil.CompressString, serialized, Enum.CompressionMethod.Deflate)
      if compressOk and compressed then
        local encodeOk, encoded = pcall(encodingUtil.EncodeBase64, compressed)
        if encodeOk and encoded then
          local exportString = "CDMSSv2|" .. encoded
          StaticPopup_Show("CDMSS_COPY", nil, nil, exportString)
          return
        end
      end
    end
  end
  print("|cffff0000[WowBuddyDev CDM]|r: 导出失败，C_EncodingUtil API 不可用")
end
-- 功能：只导出布局数据（不含字体和位置），生成 CDMSSdata| 开头的字符串弹窗复制。
-- 入参：无。
-- 出参：无（成功时弹 StaticPopupDialogs.CDMSS_COPY）。
-- 说明：给只想同步布局的玩家用；取值失败或编码 API 不可用时打印中文提示。
local function exportDataConfig()
  local layoutData = getLayoutData()
  if not layoutData then
    print("|cffff0000[WowBuddyDev CDM]|r: 数据配置获取失败")
    return
  end
  local className = select(2, UnitClass("player"))
  local specIndex = GetSpecialization and GetSpecialization() or nil
  local payload = { d = layoutData, c = className, s = specIndex, v = 1 }
  local encodingUtil = _G.C_EncodingUtil
  if encodingUtil and (encodingUtil.SerializeCBOR and (encodingUtil.CompressString and encodingUtil.EncodeBase64)) then
    local serializeOk, serialized = pcall(encodingUtil.SerializeCBOR, payload)
    if serializeOk and serialized then
      local compressOk, compressed = pcall(encodingUtil.CompressString, serialized, Enum.CompressionMethod.Deflate)
      if compressOk and compressed then
        local encodeOk, encoded = pcall(encodingUtil.EncodeBase64, compressed)
        if encodeOk and encoded then
          local exportString = "CDMSSdata|" .. encoded
          StaticPopup_Show("CDMSS_COPY", nil, nil, exportString)
          return
        end
      end
    end
  end
  print("|cffff0000[WowBuddyDev CDM]|r: 导出失败")
end
-- 功能：遍历已保存的配置档，算出要展示的名字、时间、职业、专精、长度和是否当前档。
-- 入参：无。
-- 出参：无（当前实现只算值、没有输出）。
-- 说明：风险：这段取值逻辑后面没有 print，/cdms list 实际不会有任何可见输出（疑为还原时丢失了打印语句，不影响判据所以保留原样）；没有存档时打印暂无保存的配置。
local function listProfiles()
  local db = getDB()
  db.profiles = db.profiles or {}
  if not next(db.profiles) then
    print("|cffffaa00[WowBuddyDev CDM]|r: 暂无保存的配置")
    return
  end
  for k3, profile in pairs(db.profiles) do
    local savedAtText = profile.savedAt and date("%Y-%m-%d %H:%M:%S", profile.savedAt) or WowBuddyDev.L("未知")
    local className = profile.class or "?"
    local specText = profile.spec or "?"
    local dataConfigLength = profile.dataConfig and #profile.dataConfig or 0
    local currentMark = k3 == s and " |cff00ff00<< 当前|r" or ""
  end
end
-- 功能：删除一份保存的配置档。
-- 入参：profileName 配置档名。
-- 出参：无。
-- 说明：找不到时打印中文提示；只删 profiles 里的那份，不动当前档名（s）。
local function deleteProfile(profileName)
  local db = getDB()
  db.profiles = db.profiles or {}
  if db.profiles[profileName] then
    db.profiles[profileName] = nil
  else
    print("|cffff0000[WowBuddyDev CDM]|r: 未找到配置 '" .. profileName .. "'")
  end
end
StaticPopupDialogs.CDMSS_COPY = {
  text = "配置字符串已生成（Ctrl+C 复制，Esc 关闭）：",
  button1 = WowBuddyDev.L("关闭"),
  hasEditBox = true,
  editBoxWidth = 450,
  OnShow = function(popup)
    popup.EditBox:SetText(popup.data or "")
    popup.EditBox:HighlightText()
    popup.EditBox:SetFocus()
  end,
  EditBoxOnEnterPressed = function(editBox)
    editBox:GetParent():Hide()
  end,
  EditBoxOnEscapePressed = function(editBox)
    editBox:GetParent():Hide()
  end,
  timeout = 0,
  whileDead = true,
  hideOnEscape = true,
  preferredIndex = 3,
}
SLASH_CDMSS1 = "/cdms"
-- 功能：注册 /cdms 命令，把玩家输入分发到存档/载入/列表/删除/导出/导入/字体/字号/自动恢复/调试各分支。
-- 入参：input 玩家输入的命令行（不含命令名本身）。
-- 出参：无。
-- 说明：输入按空白拆成 命令/参数1/其余 三段；子命令名转小写并去空格，参数只去空格（配置字符串区分大小写，不能转小写）。风险：新增子命令时注意 elseif 链顺序；import 需要两个参数齐全，缺一个只打印用法。
SlashCmdList.CDMSS = function(input)
  local command, arg1, arg2 = input:match("^(%S*)%s*(%S*)%s*(.*)$")
  command = ((command or "")):lower():trim()
  arg1 = ((arg1 or "")):trim()
  arg2 = ((arg2 or "")):trim()
  if command == "save" then
    saveProfile(arg1 ~= "" and arg1 or nil)
  elseif command == "load" then
    loadProfile(arg1 ~= "" and arg1 or nil)
  elseif command == "list" then
    listProfiles()
  elseif command == "delete" or command == "del" then
    if arg1 ~= "" then
      deleteProfile(arg1)
    else
      print("用法: /cdms delete <名称>")
    end
  elseif command == "export" then
    exportProfile(arg1 ~= "" and arg1 or nil)
  elseif command == "import" then
    if arg1 ~= "" and arg2 ~= "" then
      if WowBuddyDev.CDMImportProfile then
        WowBuddyDev.CDMImportProfile(arg1, arg2)
      else
        print("|cffff0000[WowBuddyDev CDM]|r: 导入模块未加载")
      end
    else
      print("用法: /cdms import <名称> <字符串>")
    end
  elseif command == "pos" then
    for index18, viewerName in ipairs(VIEWER_FRAME_NAMES) do
      local viewerFrame = _G[viewerName]
      if viewerFrame then
        local point, relativeTo, relativePoint, offsetX, offsetY = viewerFrame:GetPoint(1)
      end
    end
  elseif command == "inspect" then
    if not isEditModeApiAvailable() then
      return
    end
    local editModeLayouts = C_EditMode.GetLayouts()
    if not editModeLayouts then
      return
    end
    local activeLayout = getActiveLayout(editModeLayouts)
    if not activeLayout then
      print("无法获取 activeLayout")
      return
    end
    for index19, system in ipairs(activeLayout.systems) do
      if system.system == Enum.EditModeSystem.CooldownViewer then
        if system.settings then
          for index20, setting in ipairs(system.settings) do

          end
        end
        if system.anchorInfo then
          local anchorInfo = system.anchorInfo
        end
      end
    end
  elseif command == "font" then
    if arg1 ~= "" then
      setFontAndFlags(arg1)
    else
      print("用法: /cdms font <路径>    例: /cdms font Fonts\\2B518D9B.ttf")
    end
  elseif command == "fontsize" then
    setBaseFontSize(arg1)
  elseif command == "cdfontsize" then
    local viewerName, sizeText = arg1, arg2
    if sizeText == "" then
      sizeText = viewerName
      viewerName = nil
    end
    if viewerName and (viewerName ~= "" and (sizeText and sizeText ~= "")) then
      if not _G[viewerName] then
        print("|cffff0000未知 viewer:|r " .. viewerName)
        return
      end
      local cooldownSize = tonumber(sizeText)
      if not cooldownSize then
        print("|cffff0000请输入数字|r")
        return
      end
      local db = getDB()
      db.cooldownFontSize = db.cooldownFontSize or {}
      db.cooldownFontSize[viewerName] = cooldownSize
      applyViewerFonts(viewerName)
    else
      print("用法: /cdms cdfontsize <viewer> <大小>")
      for index21, viewerName in ipairs(VIEWER_FRAME_NAMES) do
        local cooldownFontSize = getCooldownFontSize(viewerName)
      end
    end
  elseif command == "stfontsize" then
    local viewerName, sizeText = arg1, arg2
    if sizeText == "" then
      sizeText = viewerName
      viewerName = nil
    end
    if viewerName and (viewerName ~= "" and (sizeText and sizeText ~= "")) then
      if not _G[viewerName] then
        print("|cffff0000未知 viewer:|r " .. viewerName)
        return
      end
      local stackSize = tonumber(sizeText)
      if not stackSize then
        print("|cffff0000请输入数字|r")
        return
      end
      local db = getDB()
      db.stackFontSize = db.stackFontSize or {}
      db.stackFontSize[viewerName] = stackSize
      applyViewerFonts(viewerName)
    else
      print("用法: /cdms stfontsize <viewer> <大小>")
      for index22, viewerName in ipairs(VIEWER_FRAME_NAMES) do
        local stackFontSize = getStackFontSize(viewerName)
      end
    end
  elseif command == "fontflags" then
    if arg1 ~= "" then
      setFontAndFlags(nil, arg1)
    else
      print("用法: /cdms fontflags <flags>  例: /cdms fontflags OUTLINE")
    end
  elseif command == "debug" then
    if Enum.EditModeCooldownViewerSystemIndices then
      for k4, indexValue in pairs(Enum.EditModeCooldownViewerSystemIndices) do
        print("  " .. tostring(k4) .. " = " .. tostring(indexValue))
      end
    end
    for index23, viewerName in ipairs(VIEWER_FRAME_NAMES) do
      local viewerFrame = _G[viewerName]
      if viewerFrame then

      end
    end
  elseif command == "autorestore" then
    local db = getDB()
    if arg1 == "off" or arg1 == "disable" or arg1 == "0" then
      db.autoRestore = false
      print("|cff00ff00[WowBuddyDev CDM]|r 自动恢复已 |cffff0000关闭|r。/reload 后不再强制恢复 CDM 配置，可自由调整布局。")
    elseif arg1 == "on" or arg1 == "enable" or arg1 == "1" then
      db.autoRestore = true
      print("|cff00ff00[WowBuddyDev CDM]|r 自动恢复已 |cff00ff00开启|r。/reload 后将恢复上次保存的 CDM 配置。")
    else
      local stateText = db.autoRestore ~= false and "|cff00ff00开启|r" or "|cffff0000关闭|r"
      print("|cff00ff00[WowBuddyDev CDM]|r 自动恢复状态: " .. stateText)
      print("  用法: /cdms autorestore on  |  /cdms autorestore off")
    end
  elseif command == "exportdata" then
    exportDataConfig()
  elseif command == "importdata" then
    if arg1 ~= "" then
      if WowBuddyDev.CDMImportDataConfig then
        WowBuddyDev.CDMImportDataConfig(arg1)
      else
        print("|cffff0000[WowBuddyDev CDM]|r: 导入模块未加载")
      end
    else
      print("用法: /cdms importdata <CDMSSdata|...>")
    end
  else

  end
end
local VIEWER_DISPLAY_CHECKS = {
  { frame = "EssentialCooldownViewer", name = "重要技能冷却" },
  { frame = "BuffIconCooldownViewer", name = "追踪增益效果" },
}
-- 功能：检查重要技能冷却和追踪增益两个 viewer 的显示状态，列出会影响读取的问题项。
-- 入参：无。
-- 出参：问题列表，每项 name（中文名）、timerOff（计时器被关）、notAlways（可见性不是 Always）。
-- 说明：timerShown == false 表示玩家把计时数字关了；visibleSetting 不等于 Enum.CooldownViewerVisibleSetting.Always 表示图标会被隐藏 —— 这两种情况外部读取端都拿不到数字，所以要报出来。
local function getViewerDisplayIssues()
  local issues = {}
  local alwaysValue = Enum.CooldownViewerVisibleSetting and Enum.CooldownViewerVisibleSetting.Always or 0
  for index24, viewer in ipairs(VIEWER_DISPLAY_CHECKS) do
    local viewerFrame = _G[viewer.frame]
    if viewerFrame then
      local timerOff = (viewerFrame.timerShown == false)
      local visibleSetting = viewerFrame.visibleSetting
      local notAlways = (visibleSetting ~= nil and visibleSetting ~= alwaysValue)
      if timerOff or notAlways then
        table.insert(issues, { name = viewer.name, timerOff = timerOff, notAlways = notAlways })
      end
    end
  end
  return issues
end
WowBuddyDev.CDMManager = {
  LoadProfile = loadProfile,
  SetProfile = setProfile,
  GetDB = getDB,
  LoadDataConfig = loadDataConfig,
  ExportProfile = exportProfile,
  EnsureCooldownViewerReady = ensureCooldownViewerReady,
  InspectEditModeSettings = inspectEditModeSettings,
  GetBuffIconHideWhenInactive = getBuffIconHideWhenInactive,
  GetViewerDisplayIssues = getViewerDisplayIssues,
  VIEWERS = VIEWER_FRAME_NAMES,
}
local cdmManager = WowBuddyDev.CDMManager
if not cdmManager then
  print("|cffff0000CDMStateSaver Import|r: 核心模块未加载，导入功能不可用")
  return
end
-- 功能：把 viewerName 短键表还原成内部配置档结构。
-- 入参：payload 短键表。
-- 出参：配置档表；版本号不是 2 时返回 nil。
-- 说明：键名与 encodeProfilePayload 一一对应，改一边必须改另一边；savedAt 用当前时间补（导入的档没有原始保存时间）。
local function decodeProfilePayload(payload)
  if not payload then
    return nil
  end
  if payload.v == 2 then
    return {
      dataConfig = payload.d,
      positions = payload.p,
      editModeSettings = payload.e,
      class = payload.c,
      spec = payload.s,
      cooldownFontSize = payload.cds,
      stackFontSize = payload.ss,
      fontPath = payload.fp,
      fontFlags = payload.ff,
      fontSize = payload.fz,
      savedAt = time(),
    }
  end
  return nil
end
-- 功能：导入 CDMSSdata| 字符串，把布局写回游戏并按职业-专精存档。
-- 入参：importString 配置字符串。
-- 出参：true/false（失败会打印原因）。
-- 说明：先校验前缀，再走 Base64 解码、解压、CBOR 反序列化；成功后写进 db.specDataConfigs[职业-专精]，同一专精下次可以复用。风险：解码链任一环失败只打印解码失败，不区分是哪一步 —— CBOR 结构变了也是这个提示。
local function importDataConfigString(importString)
  if not importString or importString == "" then
    print("|cffff0000[WowBuddyDev CDM]|r: 请输入有效的配置字符串")
    return false
  end
  if not importString:match("^CDMSSdata%|") then
    print("|cffff0000[WowBuddyDev CDM]|r: 格式错误，应以 CDMSSdata| 开头")
    return false
  end
  local encodedPayload = importString:match("^CDMSSdata%|(.+)$")
  if not encodedPayload then
    print("|cffff0000[WowBuddyDev CDM]|r: 格式错误")
    return false
  end
  local encodingUtil = _G.C_EncodingUtil
  if encodingUtil and (encodingUtil.DecodeBase64 and (encodingUtil.DecompressString and encodingUtil.DeserializeCBOR)) then
    local decodeOk, decoded = pcall(encodingUtil.DecodeBase64, encodedPayload)
    if decodeOk and decoded then
      local decompressOk, decompressed = pcall(encodingUtil.DecompressString, decoded, Enum.CompressionMethod.Deflate)
      if decompressOk and decompressed then
        local deserializeOk, payload = pcall(encodingUtil.DeserializeCBOR, decompressed)
        if deserializeOk and (payload and payload.d) then
          cdmManager.LoadDataConfig(payload.d)
          local db = cdmManager.GetDB()
          db.specDataConfigs = db.specDataConfigs or {}
          local className = select(2, UnitClass("player"))
          local specIndex = GetSpecialization and GetSpecialization() or 0
          local specKey = className .. "-" .. specIndex
          db.specDataConfigs[specKey] = { dataConfig = payload.d, importedAt = time() }
          if payload.c then
            print("  来源职业: " .. payload.c .. " 专精: " .. tostring(payload.s or "?"))
          end
          return true
        end
      end
    end
  end
  print("|cffff0000[WowBuddyDev CDM]|r: 解码失败")
  return false
end
-- 功能：导入 CDMSSv2| 字符串成一份命名配置档并立即载入。
-- 入参：profileName 配置档名（空则用 imported）；importString 配置字符串。
-- 出参：true/false。
-- 说明：前缀不是 CDMSSv2| 就直接拒绝（老 CDMSSdata| 走 importDataConfigString）；解码链同样是 Base64 到解压到 CBOR。
local function importProfileString(profileName, importString)
  if not importString or importString == "" then
    print("|cffff0000[WowBuddyDev CDM]|r: 请输入有效的配置字符串")
    return false
  end
  profileName = profileName or "imported"
  if importString:match("^CDMSSv2%|") then
    local encodedPayload = importString:match("^CDMSSv2%|(.+)$")
    if not encodedPayload then
      print("|cffff0000[WowBuddyDev CDM]|r: 格式错误")
      return false
    end
    local encodingUtil = _G.C_EncodingUtil
    if encodingUtil and (encodingUtil.DecodeBase64 and (encodingUtil.DecompressString and encodingUtil.DeserializeCBOR)) then
      local decodeOk, decoded = pcall(encodingUtil.DecodeBase64, encodedPayload)
      if decodeOk and decoded then
        local decompressOk, decompressed = pcall(encodingUtil.DecompressString, decoded, Enum.CompressionMethod.Deflate)
        if decompressOk and decompressed then
          local deserializeOk, payload = pcall(encodingUtil.DeserializeCBOR, decompressed)
          if deserializeOk and payload then
            local profile = decodeProfilePayload(payload)
            if profile then
              cdmManager.SetProfile(profileName, profile)
              cdmManager.LoadProfile(profileName)
              return true
            end
          end
        end
      end
    end
    print("|cffff0000[WowBuddyDev CDM]|r: 解码失败，可能缺少 C_EncodingUtil API")
    return false
  end
  print("|cffff0000[WowBuddyDev CDM]|r: 未知格式，应以 CDMSSv2| 开头")
  return false
end
WowBuddyDev.CDMImportProfile = importProfileString
WowBuddyDev.CDMImportDataConfig = importDataConfigString
StaticPopupDialogs.CDMSS_IMPORT = {
  text = "粘贴配置字符串（以 CDMSSv2| 开头）：",
  button1 = "导入并 /reload",
  button2 = WowBuddyDev.L("取消"),
  hasEditBox = true,
  editBoxWidth = 350,
  OnShow = function(popup)
    popup.EditBox:SetText("")
    popup.EditBox:SetFocus()
  end,
  OnAccept = function(popup)
    if InCombatLockdown() then
      print("|cffff0000[CDM]|r 战斗中无法重载界面，请脱战后重试")
      return
    end
    local importText = popup.EditBox:GetText()
    if importText and importText ~= "" then
      if importProfileString("imported", importText) then
        ReloadUI()
      end
    end
  end,
  EditBoxOnEnterPressed = function(editBox)
    if InCombatLockdown() then
      print("|cffff0000[CDM]|r 战斗中无法重载界面，请脱战后重试")
      editBox:GetParent():Hide()
      return
    end
    local importText = editBox:GetText()
    if importText and importText ~= "" then
      if importProfileString("imported", importText) then
        ReloadUI()
      end
    end
    editBox:GetParent():Hide()
  end,
  EditBoxOnEscapePressed = function(editBox)
    editBox:GetParent():Hide()
  end,
  timeout = 0,
  whileDead = true,
  hideOnEscape = true,
  preferredIndex = 3,
}
