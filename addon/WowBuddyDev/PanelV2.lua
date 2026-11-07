-- ==========================================================================
-- 文件：b2b089.lua
-- 来源：P07483180.rar → P07483180/b2b089.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：b2b089.lua → PanelV2.lua（按功能重命名）
-- 作用：横排 V2 面板：数字格、字体、契约渲染、光环容器
-- ==========================================================================
local panelLeft = 16
local panelTop = 0
-- 【改装】格子宽度 30 → 40：冷却改成 %.1f 之后文本变成 "13.4" 这种 4 个字形，
-- 在 20 号字下约 38px，比 30 单位的格子宽 —— 文本是以格子中心为锚点、不裁剪画的，
-- 于是位数一变（"9.9"→"10.0"）就左右晃，还会压到隔壁格子。
-- 加宽到 40 之后 5 个字形也放得下。（高度也跟着变 40，不影响纵向布局）
-- 读取端的格子几何是从 protocol.json 的 v2Geometry 读的，改这里没问题。
local cellSize = 40
local cellGap = 2
local cellPitch = cellSize + cellGap
local maxTextSlots = 16
local fontSize = 20
local DEFAULT_FONT = "Fonts\\ARKai_T.ttf"
-- 【改装】数字格另用一个"等宽数字"的字体：原来的 ARKai_T 数字是比例宽度，
-- 1 比别的数字窄很多，于是倒计时从 28.1 变 27.7 时整串会左右移动（实测 3px）。
-- ARIALN.TTF 是客户端自带的数字字体，数字等宽。加载失败会自动退回 ARKai_T，不会报错。
local NUMERIC_FONT = "Fonts\\ARIALN.TTF"
-- 功能：把等宽数字字体套到某个 FontString 上，套完立刻回读校验；校验不过就退回插件标准字体，标准字体也失败才报错。
-- 入参：fontString 目标字体串；fontPath 字体路径，省略时用 DEFAULT_FONT。
-- 出参：无（成功时静默返回）。
-- 说明：校验四项 —— SetFont 返回值、回读路径、字号、OUTLINE 标志。这个面板的数字必须等宽，否则倒计时 28.1→27.7 时整串会横向跳动；所以宁可回读确认，也不假设设置成功了。
local function ensureFont(fontString, a2)
  local applied = fontString:SetFont(a2 or DEFAULT_FONT, fontSize, "OUTLINE")
  local currentFont, currentSize, currentFlags = fontString:GetFont()
  local currentPath = currentFont and string.lower(string.gsub(currentFont, "/", "\\"))
  local wantPath = string.lower(a2 or DEFAULT_FONT)
  local currentHeight = tonumber(currentSize)
  if applied == false or currentPath ~= wantPath or not currentHeight or math.abs(currentHeight - fontSize) > .001 or currentFlags ~= "OUTLINE" then
    if a2 then
      return ensureFont(fontString)          -- 备用字体不可用 → 退回标准字体（不报错）
    end
    error("WowBuddyDev V2 面板标准字体加载失败：" .. DEFAULT_FONT)
  end
end
local barSize = 4
local dimLevel = .2
WowBuddyDev._pixelStripV2BySpec = WowBuddyDev._pixelStripV2BySpec or {}
-- 功能：登记「专精 ID → v2 契约槽位表」的映射，面板渲染时按专精取用。
-- 入参：specID 专精 ID；slotTable 该专精的契约槽位表。
-- 出参：无。
-- 说明：契约由各专精文件在加载时通过 P07483180.RegisterPixelStripV2 注册，是被动导入，面板不主动去问。
function WowBuddyDev.RegisterPixelStripV2(specID, a2)
  WowBuddyDev._pixelStripV2BySpec[specID] = a2
end
local cachedFormatter = nil
-- 功能：建（并缓存）时长文本用的数字格式化器：先试 %.1f / 步长 0.1，建不起来就退回 %d / 步长 1。
-- 入参：无。
-- 出参：格式化器对象；客户端没有 C_StringUtil / Enum.NumericRuleFormatRounding 时返回 nil。
-- 说明：面板文字要精确到 0.1 秒，外部读取端才认得出来。两次 pcall 都失败时返回 nil，不抛错 —— 这时时长文本会退回客户端默认格式（"1m30s" 这种带单位的），读取端就读不出来了，所以能做出来就一定要做出来。
local function getNumberFormatter()
  if cachedFormatter then
    return cachedFormatter
  end
  if not (C_StringUtil and C_StringUtil.CreateNumericRuleFormatter) then
    return nil
  end
  if not (Enum and Enum.NumericRuleFormatRounding) then
    return nil
  end
  local formatter = C_StringUtil.CreateNumericRuleFormatter()
  -- 【改装】原来是 format="%d", step=1（整秒显示）。现在先试 %.1f / step=0.1，
  -- 让面板文字和色块条一样给到 0.1 秒（读取端已能识别小数点）。
  -- 万一格式化器不接受 %.1f，pcall 会失败、getNumberFormatter() 就返回 nil，
  -- 那样时长文本会退回客户端默认格式（"1m30s" 这种带单位的），读取端就读不出来了。
  -- 所以这里加一层兜底：十分位不成就退回原来的整秒，保证面板永远不会变成读不出来的样子。
  local ok = pcall(formatter.SetBreakpoints, formatter, { { threshold = 0, format = "%.1f", step = .1, rounding = Enum.NumericRuleFormatRounding.Nearest } })
  if not ok then
    ok = pcall(formatter.SetBreakpoints, formatter, { { threshold = 0, format = "%d", step = 1, rounding = Enum.NumericRuleFormatRounding.Nearest } })
  end
  if not ok then
    return nil
  end
  cachedFormatter = formatter
  return formatter
end
local cdRows = {}
-- 功能：把契约里的候选法术 ID 列表转成 { [spellID] = true } 集合。
-- 入参：slot 契约槽位（读 spellIDs / spellID）。
-- 出参：集合；两个字段都没有时返回 nil。
-- 说明：给 AddAuraSlot 的 includeSpellIDs 用，也用来认「被替换技能」。
local function buildSpellIdSet(slot)
  if slot.spellIDs then
    local spellIdSet = {}
    for index, v in ipairs(slot.spellIDs) do
      spellIdSet[v] = true
    end
    return spellIdSet
  end
  if slot.spellID then
    return { [slot.spellID] = true }
  end
  return nil
end
-- 功能：决定一个契约槽位的光环过滤器串（HELPFUL / HARMFUL）。
-- 入参：slot 契约槽位。
-- 出参：过滤器字符串；槽位自带 filter 时原样返回。
-- 说明：驱散检测固定按 HARMFUL 找；目标是敌对单位时按 HARMFUL|PLAYER，其余（自己、队友、焦点）按 HELPFUL|PLAYER。
local function getAuraFilter(slot)
  if slot.filter then
    return slot.filter
  end
  if slot.kind == "dispel_presence" then
    return "HARMFUL"
  end
  if (slot.unit or "player") == "target" then
    return "HARMFUL|PLAYER"
  end
  return "HELPFUL|PLAYER"
end
-- 功能：把契约里的可驱散类型列表转成 { [dispelType] = true } 集合。
-- 入参：dispelTypes 类型名列表，可为 nil。
-- 出参：集合（空表也可以）。
local function buildDispelTypeSet(dispelTypes)
  local dispelTypeSet = {}
  for index2, v2 in ipairs(dispelTypes or {}) do
    dispelTypeSet[v2] = true
  end
  return dispelTypeSet
end
-- 功能：查某个天赋节点是否已投入点数。
-- 入参：nodeID 天赋节点 ID。
-- 出参：true/false；取不到当前配置或节点信息时算未点。
-- 说明：英雄天赋点出来的技能在法术书里查不到，只能问 C_Traits，所以这条路径单独走。
local function isTraitNodeActive(nodeID)
  if not (C_ClassTalents and (C_ClassTalents.GetActiveConfigID and (C_Traits and C_Traits.GetNodeInfo))) then
    return false
  end
  local configOK, configID = pcall(C_ClassTalents.GetActiveConfigID)
  if not (configOK and type(configID) == "number") then
    return false
  end
  local nodeOK, nodeInfo = pcall(C_Traits.GetNodeInfo, configID, nodeID)
  return nodeOK and (nodeInfo and (type(nodeInfo.activeRank) == "number" and nodeInfo.activeRank > 0))
end
-- 功能：判断一个格子是不是「还没学会」，该写未学会哨兵 601。
-- 入参：spellID 主技能 ID；spellIDs 候选列表；knownSpellID 学会判定用的替代技能 ID；knownTraitNodeID 天赋节点 ID。
-- 出参：true（未学会）/ false（已学会）。
-- 说明：给了 knownTraitNodeID 就只看天赋；否则逐个 pcall IsSpellKnown，任意一个已会就算已学会。用 pcall 是因为 IsSpellKnown 对非法 ID 会抛错。
local function isFieldUnlearned(spellID, spellIDs, knownSpellID, knownTraitNodeID)
  if knownTraitNodeID then
    return not isTraitNodeActive(knownTraitNodeID)
  end
  local knownTraitNodeIDs = knownSpellID and { knownSpellID } or (spellIDs or { spellID })
  for index3, nodeID in ipairs(knownTraitNodeIDs) do
    local callOK, isKnown = pcall(WowBuddyDev.IsSpellKnown, nodeID)
    if callOK and isKnown then
      return false
    end
  end
  return true
end
-- 功能：每帧刷新所有时长/充能数字行：算当前剩余时长，写进时长绑定并显示；取不到就隐藏或显示未学会哨兵。
-- 入参：无（遍历文件级 cdRows）。
-- 出参：无。
-- 说明：时长是「秘密值」，插件不能自己加减比较，只能把对象交给 binding:SetDuration 让客户端去算，所以这里只管取对象和显隐。取不到时长的两种原因分开处理 —— 未学会显示 601，已学会但不在冷却则整个隐藏。
local function refreshCooldownRows()
  for index4, row in ipairs(cdRows) do
    local cell = row.fs:GetParent()
    if isFieldUnlearned(row.spellID, row.spellIDs, row.knownSpellID, row.knownTraitNodeID) then
      -- 未学会：整格隐藏（图标 + 601 哨兵都不占地方），学会后下一帧自动回来。
      -- 只影响可见性，不动格子布局与契约。
      if cell and cell:IsShown() then
        cell:Hide()
      end
      if row.fs:IsShown() then
        row.fs:Hide()
      end
      if row.unlearned:IsShown() then
        row.unlearned:Hide()
      end
    else
      if cell and not cell:IsShown() then
        cell:Show()
      end
      if row.unlearned:IsShown() then
        row.unlearned:Hide()
      end
      local duration = nil
      local hasDuration = false
      local spellIDList = row.spellIDs or { row.spellID }
      local idSet = row._idSet
      if not idSet then
        idSet = nil
        if row.spellIDs then
          idSet = {}
          for index5, candidateID in ipairs(row.spellIDs) do
            idSet[candidateID] = true
          end
        end
        row._idSet = idSet
      end
      for index6, spellID in ipairs(spellIDList) do
        local isOverridden = false
        if idSet and (C_Spell and C_Spell.GetOverrideSpell) then
          local overrideOK, overrideSpellID = pcall(C_Spell.GetOverrideSpell, spellID, 0, false)
          if overrideOK and (type(overrideSpellID) == "number" and (overrideSpellID ~= spellID and idSet[overrideSpellID])) then
            isOverridden = true
          end
        end
        if not isOverridden then
          if row.chargeRecoveryOnly then
            if C_Spell and C_Spell.GetSpellChargeDuration then
              local chargeOK, chargeDuration = pcall(C_Spell.GetSpellChargeDuration, spellID)
              if chargeOK then
                duration = chargeDuration
                hasDuration = true
              end
            end
          elseif C_Spell and C_Spell.GetSpellCooldownDuration then
            local cooldownOK, cooldownDuration = pcall(C_Spell.GetSpellCooldownDuration, spellID, true)
            if cooldownOK then
              duration = cooldownDuration
              hasDuration = true
            end
          end
          if not row.cooldownOnly and (not row.chargeRecoveryOnly and (not duration and (C_Spell and C_Spell.GetSpellChargeDuration))) then
            local chargeFallbackOK, chargeFallbackDuration = pcall(C_Spell.GetSpellChargeDuration, spellID)
            if chargeFallbackOK then
              duration = chargeFallbackDuration
            end
          end
          if duration then
            break
          end
        end
      end
      if (row.cooldownOnly or row.chargeRecoveryOnly) and not hasDuration then
        if row.fs:IsShown() then
          row.fs:Hide()
        end
        if not row.unlearned:IsShown() then
          row.unlearned:Show()
        end
      elseif duration then
        row.binding:SetDuration(duration)
        if row.binding.SetEnabled then
          row.binding:SetEnabled(true)
        end
        if not row.fs:IsShown() then
          row.fs:Show()
        end
      else
        if row.fs:IsShown() then
          row.fs:Hide()
        end
      end
    end
  end
end
local panelFrame = nil
local panelAuraContainers = {}
local iconCells = {}
local rowCount = 0
-- 功能：懒建横排面板的父 Frame（TOOLTIP 层、层级 9996）并先隐藏。
-- 入参：无。
-- 出参：无。
-- 说明：面板所有格子都挂在这个父 Frame 下；层级压在提示框下层，避免挡住鼠标提示。
local function ensurePanelFrame()
  if panelFrame then
    return
  end
  panelFrame = CreateFrame("Frame", nil, UIParent)
  panelFrame:SetFrameStrata("TOOLTIP")
  panelFrame:SetFrameLevel(9996)
  panelFrame:Hide()
end
-- 功能：建一个 40×40 的图标格（可选技能图标），按列号摆到面板上，并登记进 iconCells 供调试图标刷新用。
-- 入参：column 列号（第几个格子）；spellID 图标技能 ID；desaturated 图标是否置灰。
-- 出参：新建的格子 Frame。
-- 说明：图标置灰（.45 灰）用于「这个格子的技能其实没在转」的场景；关掉图标开关（DB.v2PanelIcons）时画纯黑底避免误看。
local function createIconCell(column, spellID, desaturated)
  local iconCell = CreateFrame("Frame", nil, panelFrame)
  iconCell:SetSize(cellSize, cellSize)
  iconCell:SetPoint("TOPLEFT", panelFrame, "TOPLEFT", column * cellPitch, 0)
  iconCell:EnableMouse(false)
  local iconTexture = iconCell:CreateTexture(nil, "ARTWORK")
  iconTexture:SetAllPoints(iconCell)
  if WowBuddyDev.DB and WowBuddyDev.DB.v2PanelIcons then
    local spellTexture = C_Spell and (C_Spell.GetSpellTexture and C_Spell.GetSpellTexture(spellID))
    if spellTexture then
      iconTexture:SetTexture(spellTexture)
    end
    if desaturated then
      iconTexture:SetDesaturated(true)
      iconTexture:SetVertexColor(.45, .45, .45)
    end
  else
    iconTexture:SetColorTexture(0, 0, 0, 1)
  end
  iconCells[#iconCells + 1] = iconCell
  return iconCell
end
local chargeRows = {}
-- 功能：给 charge_lua 类契约建一行「直读充能数」的文本格。
-- 入参：column 列号；slot 契约槽位。
-- 出参：无。
-- 说明：登记进 chargeRows，供 getChargeDisplayValue / setRawChargeText 每帧写数字。
local function createChargeRow(column, slot)
  local chargeCell = createIconCell(column, slot.spellID or slot.spellIDs and slot.spellIDs[1], false)
  local chargeText = chargeCell:CreateFontString(nil, "OVERLAY")
  ensureFont(chargeText, NUMERIC_FONT)     -- 【改装】数字格用等宽数字字体
  chargeText:SetTextColor(1, 1, 1, 1)
  -- 【改装】居中是晃动的根源：数字位数一变（9.9 → 10.0）文本总宽就跳，
  -- 居中等于两端各移动半个差值。改成右侧对齐后数字右端固定、位数增加时向左长，视觉上不动。
  chargeText:SetPoint("RIGHT", chargeCell, "RIGHT", -1, 0)
  chargeText:Hide()
  chargeRows[#chargeRows + 1] = {
    text = chargeText,
    spellID = slot.spellID,
    spellIDs = slot.spellIDs,
    knownSpellID = slot.knownSpellID,
    knownTraitNodeID = slot.knownTraitNodeID,
    fallbackAuraSpellID = slot.fallbackAuraSpellID,
  }
end
-- 功能：取充能/层数的显示值，先问专精自己的 OverrideChargeDisplayCount，再退回插件统一的 GetSpellChargeCount。
-- 入参：slot 契约槽位。
-- 出参：层数；取不到返回 nil。
-- 说明：斗篷、图腾这类「充能数要另外算」的专精，由 classData.OverrideChargeDisplayCount 覆盖；只有带 fallbackAuraSpellID 的槽位才走覆盖，避免影响别的专精。
local function getChargeDisplayValue(slot)
  local classData = WowBuddyDev.classData
  if slot.fallbackAuraSpellID and (classData and classData.OverrideChargeDisplayCount) then
    local overrideCount = classData.OverrideChargeDisplayCount(slot.spellID)
    if overrideCount ~= nil then
      return overrideCount
    end
  end
  if not WowBuddyDev.GetSpellChargeCount then
    return nil
  end
  return WowBuddyDev.GetSpellChargeCount(slot.spellID, slot.spellIDs)
end
-- 功能：把充能原值直接写进文本格（浮点/字符串都能写）。
-- 入参：row 充能行记录（读 slot 与 text）。
-- 出参：true 写入成功；false 表示 API 不存在或 SetText 被拒。
-- 说明：pcall 是必须的 —— 秘密值在受限客户端上 SetText 会抛错，抛在每帧的刷新里会刷屏。
local function setRawChargeText(row)
  if not WowBuddyDev.GetSpellChargeDisplayRaw then
    return false
  end
  local rawOK, rawText = WowBuddyDev.GetSpellChargeDisplayRaw(row.spellID, row.spellIDs)
  if rawOK and pcall(row.text.SetText, row.text, rawText) then
    return true
  end
  return false
end
-- 功能：每帧刷新所有充能数字行：未学会写哨兵 601，取到值就写值，取不到就隐藏。
-- 入参：无（遍历文件级 chargeRows）。
-- 出参：无。
local function refreshChargeRows()
  for index7, chargeRow in ipairs(chargeRows) do
    local cell = chargeRow.text:GetParent()
    if isFieldUnlearned(chargeRow.spellID, chargeRow.spellIDs, chargeRow.knownSpellID, chargeRow.knownTraitNodeID) then
      -- 未学会：整格隐藏（不再显示 601 哨兵），学会后下一帧自动回来。
      if cell and cell:IsShown() then
        cell:Hide()
      end
      if chargeRow.text:IsShown() then
        chargeRow.text:Hide()
      end
    else
      if cell and not cell:IsShown() then
        cell:Show()
      end
      local chargeValue = getChargeDisplayValue(chargeRow)
      if chargeValue ~= nil then
        chargeRow.text:SetText(chargeValue)
        if not chargeRow.text:IsShown() then
          chargeRow.text:Show()
        end
      elseif setRawChargeText(chargeRow) then
        if not chargeRow.text:IsShown() then
          chargeRow.text:Show()
        end
      else
        if chargeRow.text:IsShown() then
          chargeRow.text:Hide()
        end
      end
    end
  end
end
-- 功能：给 cd_seconds 类契约建一行「剩余秒数」的数字格：前台文本接时长绑定，后台文本是未学会哨兵 601。
-- 入参：rowIndex 这一行在面板里的列序号（格子从左往右排，所以是横向索引）；slot 契约槽位。
-- 出参：无。
-- 说明：cooldownOnly / chargeRecoveryOnly 的槽位只认「纯冷却/纯充能恢复」这一条路径，建绑定要 pcall —— 类型不匹配时直接显示 601 而不是把整个面板带崩。
local function createDurationRow(rowIndex, slot)
  local durationCell = createIconCell(rowIndex, slot.spellID, false)
  local durationText = durationCell:CreateFontString(nil, "OVERLAY")
  ensureFont(durationText, NUMERIC_FONT)     -- 【改装】数字格等宽字体
  durationText:SetTextColor(1, 1, 1, 1)
  durationText:SetPoint("RIGHT", durationCell, "RIGHT", -1, 0)   -- 【改装】右对齐，见 chargeText 的说明
  local unlearnedText = durationCell:CreateFontString(nil, "OVERLAY")
  ensureFont(unlearnedText, NUMERIC_FONT)     -- 【改装】数字格等宽字体
  unlearnedText:SetTextColor(1, 1, 1, 1)
  unlearnedText:SetPoint("RIGHT", durationCell, "RIGHT", -1, 0)   -- 【改装】右对齐
  unlearnedText:SetText("601")
  unlearnedText:Hide()
  if not (C_DurationUtil and C_DurationUtil.CreateDurationTextBinding) then
    if slot.cooldownOnly or slot.chargeRecoveryOnly then
      durationText:Hide()
      unlearnedText:Show()
    end
    return
  end
  local binding
  if slot.cooldownOnly or slot.chargeRecoveryOnly then
    local ok, newBinding = pcall(C_DurationUtil.CreateDurationTextBinding)
    if not ok or not newBinding then
      durationText:Hide()
      unlearnedText:Show()
      return
    end
    binding = newBinding
  else
    binding = C_DurationUtil.CreateDurationTextBinding()
  end
  if binding.SetUpdateInterval then
    binding:SetUpdateInterval(.05)
  end
  local formatter = getNumberFormatter()
  if formatter then
    binding:SetFormatter(formatter)
  end
  binding:SetFontString(durationText)
  cdRows[#cdRows + 1] = {
    fs = durationText,
    unlearned = unlearnedText,
    binding = binding,
    spellID = slot.spellID,
    spellIDs = slot.spellIDs,
    cooldownOnly = slot.cooldownOnly == true,
    chargeRecoveryOnly = slot.chargeRecoveryOnly == true,
    knownSpellID = slot.knownSpellID,
    knownTraitNodeID = slot.knownTraitNodeID,
  }
end
-- 功能：返回一个给 AddAuraSlot 用的 initializeFrame 回调：格子尺寸/位置就位、画技能图标、挂数字文本，并按 kind 决定走时长文本还是层数。
-- 入参：rowIndex 行号；slot 契约槽位。
-- 出参：function(cell) 回调。
-- 说明：aura_seconds 走 SetDurationText + 格式化器，其余（aura_stacks / presence*）走 SetApplicationCount 只显示层数。鼠标点击和悬停一律关掉 —— 格子是只读显示，点它不该弹任何东西。
local function createInitializer(rowIndex, slot)
  return function(cell)
    cell:SetSize(cellSize, cellSize)
    cell:ClearAllPoints()
    cell:SetPoint("TOPLEFT", cell:GetParent(), "TOPLEFT", rowIndex * cellPitch, 0)
    if WowBuddyDev.DB and WowBuddyDev.DB.v2PanelIcons then
      local iconTexture = cell:CreateTexture(nil, "ARTWORK")
      iconTexture:SetAllPoints(cell)
      cell:SetIcon(iconTexture)
    end
    local durationText = cell:CreateFontString(nil, "OVERLAY")
    ensureFont(durationText, NUMERIC_FONT)   -- 【改装】数字格等宽字体
    durationText:SetTextColor(1, 1, 1, 1)
    durationText:SetPoint("RIGHT", cell, "RIGHT", -1, 0)   -- 【改装】右对齐
    if slot.kind == "aura_seconds" then
      local durationTextOptions = {}
      local formatter = getNumberFormatter()
      if formatter then
        durationTextOptions.textFormatter = formatter
      end
      pcall(cell.SetDurationText, cell, durationText, durationTextOptions)
    else
      pcall(cell.SetApplicationCount, cell, durationText)
    end
    if cell.SetMouseClickEnabled then
      pcall(cell.SetMouseClickEnabled, cell, false)
    end
    if cell.SetMouseMotionEnabled then
      pcall(cell.SetMouseMotionEnabled, cell, false)
    end
  end
end
-- 功能：返回一个给 AddAuraSlot 用的 initializeFrame 回调（无图标版）：黑底 + 数字文本，只显示层数。
-- 入参：rowIndex 行号；slot 契约槽位（只用 spellID 取图标）。
-- 出参：function(cell) 回调。
local function createFlatInitializer(rowIndex, slot)
  return function(cell)
    cell:SetSize(cellSize, cellSize)
    cell:ClearAllPoints()
    cell:SetPoint("TOPLEFT", cell:GetParent(), "TOPLEFT", rowIndex * cellPitch, 0)
    local iconTexture = cell:CreateTexture(nil, "ARTWORK")
    iconTexture:SetAllPoints(cell)
    iconTexture:SetColorTexture(0, 0, 0, 1)
    if WowBuddyDev.DB and WowBuddyDev.DB.v2PanelIcons then
      local spellTexture = C_Spell and (C_Spell.GetSpellTexture and C_Spell.GetSpellTexture(slot.spellID))
      if spellTexture then
        iconTexture:SetTexture(spellTexture)
      end
    end
    local countText = cell:CreateFontString(nil, "OVERLAY")
    ensureFont(countText, NUMERIC_FONT)   -- 【改装】数字格等宽字体
    countText:SetTextColor(1, 1, 1, 1)
    countText:SetPoint("RIGHT", cell, "RIGHT", -1, 0)   -- 【改装】右对齐
    pcall(cell.SetApplicationCount, cell, countText)
    if cell.SetMouseClickEnabled then
      pcall(cell.SetMouseClickEnabled, cell, false)
    end
    if cell.SetMouseMotionEnabled then
      pcall(cell.SetMouseMotionEnabled, cell, false)
    end
  end
end
local panelLayoutCache = {}
-- 功能：按调试窗口是否打开展示/隐藏所有格子的调试图标。
-- 入参：无。
-- 出参：无。
-- 说明：被调试窗口开关时调用，不能只靠面板自己刷新。
function WowBuddyDev.RefreshPanelDebugIcons()
  local debugShown = WowBuddyDev.debugFrame and WowBuddyDev.debugFrame:IsShown()
  for index8, cell in ipairs(iconCells) do
    if cell._debugTex then
      cell._debugTex:SetShown(not not (debugShown and cell:IsShown()))
    end
  end
end
-- 功能：渲染横排 v2 面板：挑出文本类契约、按槽位建格子、给光环类槽位配光环容器，最后摆好面板位置和宽度。
-- 入参：contract 当前专精的契约表；specID 专精 ID（当缓存键）。
-- 出参：无。
-- 说明：同一个专精第二次进来走 t9 缓存，只把上次建的格子重新显示并接回 cdRows / chargeRows，不重建（重建会掉光环容器的注册状态）。文本槽位有 ROI embedding 上限，超了就整块不渲染并打印提示。
local function renderPanel(contract, specID)
  if not panelFrame then
    return
  end
  for k, container in pairs(panelAuraContainers) do
    container:Hide()
  end
  for index9, cell in ipairs(iconCells) do
    cell:Hide()
  end
  wipe(cdRows)
  wipe(chargeRows)
  rowCount = 0
  panelFrame:Hide()
  local TEXT_KINDS = { cd_seconds = true, charge_lua = true, aura_seconds = true, aura_stacks = true }
  local textSlots = {}
  for index10, contractSlot in ipairs(contract or {}) do
    if TEXT_KINDS[contractSlot.kind] then
      textSlots[#textSlots + 1] = contractSlot
    end
  end
  if #textSlots == 0 then
    return
  end
  if #textSlots > maxTextSlots then
    print(string.format("|cffff4444Permes v2 契约超上限：文本槽位 %d > %d（ROI embedding 上限），面板未渲染|r", #textSlots, maxTextSlots))
    return
  end
  local slotsByUnit = {}
  local cachedLayout = panelLayoutCache[specID]
  local isNewSpec = not cachedLayout
  if isNewSpec then
    cachedLayout = { firstRow = #iconCells + 1, cd = {}, charge = {}, rowCount = #textSlots }
  end
  for index11, textSlot in ipairs(textSlots) do
    local rowIndex = index11 - 1
    local kind = textSlot.kind
    if kind == "cd_seconds" then
      if isNewSpec then
        createDurationRow(rowIndex, textSlot)
      end
    elseif kind == "charge_lua" then
      if isNewSpec then
        createChargeRow(rowIndex, textSlot)
      end
      if textSlot.fallbackAuraSpellID then
        local unit = textSlot.unit or "player"
        slotsByUnit[unit] = slotsByUnit[unit] or {}
        slotsByUnit[unit][#slotsByUnit[unit] + 1] = {
          slot = {
            key = textSlot.key .. "#fallback_aura",
            kind = "aura_stacks",
            unit = unit,
            spellID = textSlot.fallbackAuraSpellID,
          },
          rowIndex = rowIndex,
          chargeFallback = true,
        }
      end
    else
      if isNewSpec then
        createIconCell(rowIndex, textSlot.spellID or textSlot.spellIDs and textSlot.spellIDs[1], true)
      end
      local unit = textSlot.unit or "player"
      slotsByUnit[unit] = slotsByUnit[unit] or {}
      slotsByUnit[unit][#slotsByUnit[unit] + 1] = { slot = textSlot, rowIndex = rowIndex }
    end
  end
  if isNewSpec then
    cachedLayout.lastRow = #iconCells
    for index12, cdRow in ipairs(cdRows) do
      cachedLayout.cd[#cachedLayout.cd + 1] = cdRow
    end
    for index13, chargeRow in ipairs(chargeRows) do
      cachedLayout.charge[#cachedLayout.charge + 1] = chargeRow
    end
    panelLayoutCache[specID] = cachedLayout
  else
    for i = cachedLayout.firstRow, cachedLayout.lastRow, 1 do
      iconCells[i]:Show()
    end
    for index14, cachedCdRow in ipairs(cachedLayout.cd) do
      cdRows[#cdRows + 1] = cachedCdRow
    end
    for index15, cachedChargeRow in ipairs(cachedLayout.charge) do
      chargeRows[#chargeRows + 1] = cachedChargeRow
    end
  end
  rowCount = cachedLayout.rowCount
  for index16, iconSlot in ipairs(textSlots) do
    local iconCell = iconCells[cachedLayout.firstRow + index16 - 1]
    if iconCell then
      local debugTexture = iconCell._debugTex
      if not debugTexture then
        debugTexture = iconCell:CreateTexture(nil, "ARTWORK")
        debugTexture:SetSize(20, 20)
        debugTexture:SetPoint("TOP", iconCell, "BOTTOM", 0, -2)
        iconCell._debugTex = debugTexture
      end
      local spellID = iconSlot.spellID or iconSlot.spellIDs and iconSlot.spellIDs[1]
      local spellTexture = spellID and (C_Spell and (C_Spell.GetSpellTexture and C_Spell.GetSpellTexture(spellID)))
      if spellTexture then
        debugTexture:SetTexture(spellTexture)
      end
    end
  end
  WowBuddyDev.RefreshPanelDebugIcons()
  for k2, unitPlans in pairs(slotsByUnit) do
    local cacheKey = tostring(specID) .. ":panel:" .. k2
    local auraContainer = panelAuraContainers[cacheKey]
    if not auraContainer then
      auraContainer = CreateFrame("AuraContainer", nil, panelFrame, "CustomAuraContainerTemplate")
      auraContainer:SetSize(1, 1)
      auraContainer:SetPoint("TOPLEFT", panelFrame, "TOPLEFT", 0, 0)
      for index17, plan in ipairs(unitPlans) do
        local slot = plan.slot
        local initializeFrame = plan.chargeFallback and createFlatInitializer(plan.rowIndex, slot) or createInitializer(plan.rowIndex, slot)
        auraContainer:AddAuraSlot(slot.key, getAuraFilter(slot), { candidateFilters = { includeSpellIDs = buildSpellIdSet(slot) }, initializeFrame = initializeFrame })
      end
      auraContainer:SetUnit(k2)
      auraContainer:UpdateAllAuras()
      panelAuraContainers[cacheKey] = auraContainer
      if k2 == "focus" or k2 == "target" or k2 == "mouseover" then
        local unitEventFrame = CreateFrame("Frame")
        local unitEvent = k2 == "focus" and "PLAYER_FOCUS_CHANGED" or k2 == "target" and "PLAYER_TARGET_CHANGED" or "UPDATE_MOUSEOVER_UNIT"
        unitEventFrame:RegisterEvent(unitEvent)
        unitEventFrame:SetScript("OnEvent", function()
          auraContainer:UpdateAllAuras()
        end)
      end
    end
    auraContainer:Show()
  end
  local panelWidth = rowCount * cellPitch - cellGap
  panelFrame:SetSize(panelWidth, cellSize + 10)
  panelFrame:ClearAllPoints()
  panelFrame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", panelLeft, -panelTop)
  WowBuddyDev.RefreshV2SurfaceVisibility()
end
local rowFrames = {}
local barContainers = {}
local presenceCellRecords = {}
local activeSpecID = nil
local bottomFrame = nil
-- 功能：按总开关（DB.allOverlaysHidden）和当前行数决定面板与底衬条显示还是隐藏。
-- 入参：无。
-- 出参：无。
-- 说明：改开关、改行数的地方都会调它一次，保证隐藏状态立刻生效。
function WowBuddyDev.RefreshV2SurfaceVisibility()
  local overlaysHidden = WowBuddyDev.DB and WowBuddyDev.DB.allOverlaysHidden
  if panelFrame then
    panelFrame:SetShown(not overlaysHidden and rowCount > 0)
  end
  if bottomFrame then
    bottomFrame:SetShown(not overlaysHidden)
  end
end
-- 功能：懒建底衬条 frame5，并按行数拉到需要的高度。
-- 入参：rowCount 需要的行数（下限 1）。
-- 出参：无。
local function ensureBottomFrame(rowCount)
  if not bottomFrame then
    bottomFrame = CreateFrame("Frame", nil, UIParent)
    bottomFrame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)
    bottomFrame:SetFrameStrata("TOOLTIP")
    bottomFrame:SetFrameLevel(9997)
  end
  bottomFrame:SetSize(barSize, barSize * math.max(1, rowCount or 1))
  WowBuddyDev.RefreshV2SurfaceVisibility()
end
-- 功能：返回一个给 AddAuraSlot 用的 initializeFrame 回调：画一个绿色（0,1,0）方块底衬，用来提示「这一行的光环容器摆在这里」。
-- 入参：rowIndex 行号；sink 可选登记表，回调真正执行时会把建出来的格子和它的绿色贴图写进去（供 /pmsprobe 取证用）。
-- 出参：function(cell) 回调。
local function createDimInitializer(rowIndex, sink)
  return function(cell)
    cell:SetSize(barSize, barSize)
    cell:ClearAllPoints()
    cell:SetPoint("TOPLEFT", cell:GetParent(), "TOPLEFT", 0, -rowIndex * barSize)
    local dimTexture = cell:CreateTexture(nil, "OVERLAY")
    dimTexture:SetAllPoints(cell)
    dimTexture:SetColorTexture(0, 1, 0, 1)
    if sink then
      sink.cell = cell
      sink.dimTexture = dimTexture
    end
    if cell.SetMouseClickEnabled then
      pcall(cell.SetMouseClickEnabled, cell, false)
    end
    if cell.SetMouseMotionEnabled then
      pcall(cell.SetMouseMotionEnabled, cell, false)
    end
  end
end
local groupCountPools = {}
local groupCountRows = {}
-- 功能：按团队/小队名册把「同队人数」光环容器的单位同步到 player / party1-4 / raid1-N，并刷新它们的层数。
-- 入参：force 是否强制刷新（名册事件后为 true）。
-- 出参：无。
-- 说明：单位没换、也没强制刷新时跳过 UpdateAllAuras，省掉每帧的光环扫描；单位离线或死亡就隐藏该行，不留残留层数。
local function updateGroupCount(force)
  local inRaid = IsInRaid()
  for index18, countRow in ipairs(groupCountRows) do
    for index19, container in ipairs(countRow.containers) do
      local unit = inRaid and "raid" .. index19 or (index19 == 1 and "player" or (index19 <= 5 and "party" .. index19 - 1 or nil))
      local isValid = unit and (UnitExists(unit) and (UnitIsConnected(unit) and not UnitIsDeadOrGhost(unit)))
      if isValid then
        local unitChanged = container.groupCountUnit ~= unit
        if unitChanged then
          container:Hide()
          container:SetUnit(unit)
          container.groupCountUnit = unit
        end
        if force or unitChanged or not container.groupCountActive then
          container:UpdateAllAuras()
        end
        container:Show()
      else
        container:Hide()
      end
      container.groupCountActive = not not isValid
    end
  end
end
-- 功能：给 presence_group_count 槽位建一列 30 个光环容器（每个容器对应一名队友），按行号排到 frame5 上。
-- 入参：slot 契约槽位；specID 专精 ID；rowIndex 行号。
-- 出参：无。
-- 说明：30 是团队人数上限；容器池按「专精 + 槽位 key + 行号」缓存，切专精再切回来能直接复用。
local function createGroupCountRow(slot, specID, rowIndex)
  local cacheKey = tostring(specID) .. ":" .. slot.key .. ":" .. rowIndex
  local pool = groupCountPools[cacheKey]
  if not pool then
    pool = {}
    for i2 = 1, 30, 1 do
      local countContainer = CreateFrame("AuraContainer", nil, bottomFrame, "CustomAuraContainerTemplate")
      countContainer:SetSize(1, 1)
      countContainer:SetPoint("TOPLEFT", bottomFrame, "TOPLEFT", 0, 0)
      countContainer:AddAuraSlot(slot.key .. "#" .. i2, getAuraFilter(slot), {
        candidateFilters = { includeSpellIDs = buildSpellIdSet(slot) },
        -- 功能：光环格子的初始化回调：定尺寸、摆位，铺一层底衬，并关掉格子的鼠标响应。
        -- 入参：cell 光环容器交给回调的单格 Frame。
        -- 出参：无。
        -- 说明：这个键在文件里有两处定义，工具按同一个键给两处插同一段注释——第一处是同队人数的格子（深色底衬、按创建时固定的 rowIndex 逐行错开），第二处是驱散格子（红色底衬、铺满格位并画在更上层）。底衬的显隐由渲染逻辑控制，初始化只负责把格子准备好；SetMouseClickEnabled / SetMouseMotionEnabled 在部分客户端不存在，所以用 pcall 试探后再调。
        initializeFrame = function(cell)
          cell:SetSize(barSize, barSize)
          cell:ClearAllPoints()
          cell:SetPoint("TOPLEFT", cell:GetParent(), "TOPLEFT", 0, -rowIndex * barSize)
          local bgTexture = cell:CreateTexture(nil, "OVERLAY")
          bgTexture:SetAllPoints(cell)
          bgTexture:SetBlendMode("ADD")
          bgTexture:SetColorTexture(0, 0, .031372549019608, 1)
          if cell.SetMouseClickEnabled then
            pcall(cell.SetMouseClickEnabled, cell, false)
          end
          if cell.SetMouseMotionEnabled then
            pcall(cell.SetMouseMotionEnabled, cell, false)
          end
        end,
      })
      countContainer:Hide()
      pool[i2] = countContainer
    end
    groupCountPools[cacheKey] = pool
  end
  groupCountRows[#groupCountRows + 1] = { containers = pool }
end
-- 功能：判断鼠标指向的单位此刻能不能作用于这行光环（友方要求可助，其余要求可攻击）。
-- 入参：rows 同一单位下的行记录列表（取第一行拿 slot.unitRelation）。
-- 出参：true/false。
-- 说明：死人、幽灵、没目标一律 false，避免对着尸体刷 buff 提示。
local function isMouseoverValid(rows)
  if not UnitExists("mouseover") or UnitIsDeadOrGhost("mouseover") then
    return false
  end
  if rows[1].item.slot.unitRelation == "help" then
    return UnitCanAssist("player", "mouseover")
  end
  return UnitCanAttack("player", "mouseover")
end
-- 功能：按鼠标指向是否有效给这些行的底衬上色：有效深灰（可读），无效纯蓝（提示不可用）。
-- 入参：rows 行记录列表。
-- 出参：无。
local function setRowDimColor(rows)
  local isValid = isMouseoverValid(rows)
  for index20, row in ipairs(rows) do
    local dimTexture = row.row and row.row.dimTex
    if dimTexture then
      if isValid then
        dimTexture:SetColorTexture(dimLevel, dimLevel, dimLevel, 1)
      else
        dimTexture:SetColorTexture(0, 0, 1, 1)
      end
    end
  end
end
-- 功能：刷新鼠标指向那一行：专精没变且指向有效才显示并更新光环，否则隐藏，最后统一重画底衬色。
-- 入参：container 该行的光环容器；rows 行记录列表；specID 当前专精 ID。
-- 出参：无。
-- 说明：专精 ID 对不上说明这行是上一个专精留下的，直接隐藏 —— 防止切专精瞬间显示错行的层数。
local function refreshMouseoverRow(container, rows, specID)
  if specID ~= activeSpecID then
    container:Hide()
    return
  end
  local isValid = isMouseoverValid(rows)
  if isValid then
    container:Show()
    container:UpdateAllAuras()
  else
    container:Hide()
  end
  setRowDimColor(rows)
end
local locRows = {}
-- 功能：刷新失控（LoC）提示行：扫当前所有失控状态，命中这行白名单的 locType 就点亮绿色，否则回到深灰。
-- 入参：无（遍历文件级 locRows）。
-- 出参：无。
-- 说明：issecretvalue 判断不能省 —— locType 在受限客户端可能是秘密值，直接当表键用会抛错。
local function refreshLocRows()
  if #locRows == 0 then
    return
  end
  local getLOCCount = C_LossOfControl and C_LossOfControl.GetActiveLossOfControlDataCount
  local getLOCData = C_LossOfControl and C_LossOfControl.GetActiveLossOfControlData
  for index21, locRow in ipairs(locRows) do
    local active = false
    if getLOCCount and getLOCData then
      local locCount = getLOCCount() or 0
      for i3 = 1, locCount, 1 do
        local locData = getLOCData(i3)
        if locData and (locData.locType and (not issecretvalue(locData.locType) and locRow.locTypeSet[locData.locType])) then
          active = true
          break
        end
      end
    end
    local dimTexture = locRow.row and locRow.row.dimTex
    if dimTexture then
      if active then
        dimTexture:SetColorTexture(0, 1, 0, 1)
      else
        dimTexture:SetColorTexture(dimLevel, dimLevel, dimLevel, 1)
      end
    end
  end
end
local presenceRows = {}
local presenceScanCache = {}
-- 功能：把某单位某过滤器下的光环一次性扫进集合，同一轮刷新里同单位的行共用这一份。
-- 入参：unit 单位；filter 光环过滤器串。
-- 出参：{ ids = ID 集合, names = 名字集合, complete = 是否扫到底, degraded = 有没有格子读不出身份 }；
--       complete 为假或 degraded 为真都表示「读不出来」，不是「没有」。
-- 说明：只有按 ID 直查的 API 都不存在时才退到这里。spellId 可能是秘密值（受限客户端战斗中出现），
--       这种格子改记名字 —— 名字串不是秘密值，比对时用 C_Spell.GetSpellName 把白名单 ID 换成名字，
--       全程不需要 Lua 读出一个秘密数字。整轮只在 pcall 真报错时才判成读不出来；
--       万一某个光环 ID 和名字都读不到（战斗锁），那一轮标 degraded、交回容器，别拿半截名单判「没有」。
--       三态是必须的：读不出来时保持格子原样、让原生容器继续说话，别把未知当成没有
--       （按索引扫再直接比 spellId 就会踩这个坑，正式服 class_enhancement.lua:56 那个
--       isAuraOnTarget 就是这么写的，所以它一直没敢被调用）。
local function getUnitAuraScan(unit, filter)
  local cacheKey = unit .. "|" .. tostring(filter)
  local scan = presenceScanCache[cacheKey]
  if scan then
    return scan
  end
  scan = { ids = {}, names = {}, complete = false, degraded = false }
  presenceScanCache[cacheKey] = scan
  if not (C_UnitAuras and C_UnitAuras.GetAuraDataByIndex) then
    return scan
  end
  local scanOK = pcall(function()
    for i6 = 1, 40, 1 do
      local auraData = C_UnitAuras.GetAuraDataByIndex(unit, i6, filter)
      if not auraData then
        scan.complete = true
        return
      end
      local scannedSpellID = auraData.spellId
      local idReadable = type(scannedSpellID) == "number" and not (issecretvalue and issecretvalue(scannedSpellID))
      if idReadable then
        scan.ids[scannedSpellID] = true
      end
      local scannedName = auraData.name
      local nameReadable = type(scannedName) == "string" and not (issecretvalue and issecretvalue(scannedName))
      if nameReadable then
        scan.names[scannedName] = true
      end
      if not (idReadable or nameReadable) then
        scan.degraded = true
      end
    end
    -- 走到这里说明 40 格被占满、根本没扫到底：complete 保持假，判成「读不出来」而不是「没有」。
  end)
  if not scanOK then
    scan.complete = false
  end
  return scan
end
-- 功能：判一个单位身上有没有这批法术 ID 里的任意一个光环。
-- 入参：unit 单位；filter 过滤器串；spellIDs ID 列表。
-- 出参：真 = 确定有；假 = 确定没有；nil = 读不出来。
-- 说明：优先按 ID 直查 —— ID 是当参数传进去的，比对在客户端里做，所以不吃秘密值那道墙。
--       三态是必须的：读不出来时保持格子原样、让原生容器继续说话，别把未知当成没有。
local function queryAuraPresence(unit, filter, spellIDs)
  if not UnitExists(unit) then
    return false
  end
  local queryByPlayerID = nil
  local queryByAnyID = nil
  if C_UnitAuras then
    if unit == "player" then
      queryByPlayerID = C_UnitAuras.GetPlayerAuraBySpellID
    end
    queryByAnyID = C_UnitAuras.GetAuraDataBySpellID
  end
  if queryByPlayerID or queryByAnyID then
    local determined = true
    for index22, spellID in ipairs(spellIDs) do
      local callOK, auraData
      if queryByPlayerID then
        callOK, auraData = pcall(queryByPlayerID, spellID)
      else
        callOK, auraData = pcall(queryByAnyID, spellID, filter, unit)
      end
      if not callOK then
        determined = false
      elseif auraData ~= nil then
        return true
      end
    end
    -- ★ 按 ID 全部查不到/查不动 ≠ 真没有：受限客户端战斗中 spellId 变秘密值，
    --   GetPlayerAuraBySpellID 要么静默返回空、要么直接报错（实测进战斗瞬间
    --   野性印记/荆棘术行掉灰、脱战立刻回绿，外部端每场战斗都误补 buff）。
    --   名字串不是秘密值——无论按 ID 是报错还是查空，都按名字再扫一遍；
    --   只有「按 ID 没报错 + 名字扫描完整无降级 + 两边都没找到」才敢说确认没有，
    --   其余情况一律按读不出来（nil）交回调用方保持原色。
    local scan = getUnitAuraScan(unit, filter)
    local getSpellName = C_Spell and C_Spell.GetSpellName
    for index23, spellID in ipairs(spellIDs) do
      if scan.ids[spellID] then
        return true
      end
      if getSpellName then
        local nameOK, wantedName = pcall(getSpellName, spellID)
        if nameOK and type(wantedName) == "string" and scan.names[wantedName] then
          return true
        end
      end
    end
    if determined and scan.complete and not scan.degraded then
      return false
    end
    return nil
  end
  local scan = getUnitAuraScan(unit, filter)
  local getSpellName = C_Spell and C_Spell.GetSpellName
  for index23, spellID in ipairs(spellIDs) do
    if scan.ids[spellID] then
      return true
    end
    if getSpellName then
      local nameOK, wantedName = pcall(getSpellName, spellID)
      if nameOK and type(wantedName) == "string" and scan.names[wantedName] then
        return true
      end
    end
  end
  if scan.complete and not scan.degraded then
    return false
  end
  return nil
end
local presenceUnknownHoldSec = 3
-- 功能：玩家增益行（luaDriven）的绿/灰只由 Lua 直读光环决定。
-- 入参：无（遍历文件级 presenceRows）。
-- 出参：无。
-- 说明：这类行在 renderPresenceRows 里压根没往容器注册格子，同一个像素只剩这一个写者，换目标时容器
--       再 UpdateAllAuras 也碰不到这一行。/pmsprobe 实测掉灰全部来自容器那层（光环还剩 586 秒就把格子
--       画灰），而同一笔样本里手扫和 Lua 判都是「有」，所以把容器请出去、让 Lua 说话。
--       非玩家单位（target/party/mouseover）的 presence 行不动，仍由容器出像素：战斗中它们的 spellId
--       可能是秘密值，读不出来会被判成假灰，反而把 DoT 打乱。
--       连续读不出来最多保持原色 3 秒，超时按「没有」处理——宁可多补一次 buff，不能一直绿着不漏。
local function refreshPresenceRows()
  if #presenceRows == 0 then
    return
  end
  wipe(presenceScanCache)
  local now = GetTime()
  for index24, presenceRow in ipairs(presenceRows) do
    local dimTexture = presenceRow.luaDriven and presenceRow.row and presenceRow.row.dimTex
    if dimTexture then
      local verdict = queryAuraPresence(presenceRow.unit, presenceRow.filter, presenceRow.spellIDs)
      if verdict == nil then
        if UnitAffectingCombat and UnitAffectingCombat("player") then
          if presenceRow.key and presenceRow.key:find("^seal_") then
            -- ★ 圣印行例外（2026-10-15 二修）：审判会机制性吃掉圣印，战斗中光环
            --   读数又被投毒，无限保鲜=圣印行锁死绿色=战斗中永不补印。入战第一拍
            --   锚定起点，此后 20 秒既无可靠确认也无施法回显就翻灰，让引擎补一次；
            --   回显/查询恢复时会立刻翻绿重锚，正常节奏不受影响。
            if presenceRow.sealAnchor ~= "combat" then
              presenceRow.sealAnchor = "combat"
              presenceRow.knownAt = now
            end
            presenceRow.staleOut = now - presenceRow.knownAt > 20
          else
            -- ★ 战斗中读不出来（spellId 秘密值）时保持原色，不做 3 秒超时：
            --   掉灰会让外部端每场战斗误补 buff（2026-10-09 实测）。脱战后按 ID/按名字
            --   的查询立刻恢复可靠，真掉的光环最多 3 秒就会显灰。
            presenceRow.staleOut = false
            presenceRow.knownAt = now
          end
        else
          presenceRow.sealAnchor = nil
          presenceRow.staleOut = now - presenceRow.knownAt > presenceUnknownHoldSec
        end
      else
        presenceRow.sealAnchor = nil
        presenceRow.knownAt = now
        presenceRow.staleOut = false
        presenceRow.green = verdict
      end
      if not presenceRow.staleOut and presenceRow.green then
        dimTexture:SetColorTexture(0, 1, 0, 1)
      else
        dimTexture:SetColorTexture(dimLevel, dimLevel, dimLevel, 1)
      end
    end
  end
end
-- ============================================================
-- 圣印战斗内回显（2026-10-15 惩戒补印修复）
-- 症状：审判吃掉圣印后，战斗中光环查询被秘密值拦住（verdict=nil），
--   上面的「战斗保持原色」把行锁死在绿 → seal_* 永不等于 false →
--   惩戒循环再也不补印（战斗外 3 秒超时会变灰，所以战斗外正常）。
-- 修法：监听施法成功事件直接翻转行状态——审判成功(20271) → 圣印行
--   立刻变灰；自家 buff 施法成功（行 spellIDs 命中）→ 行立刻变绿。
--   refreshPresenceRows 下一拍（≤0.25s）照常重涂，查询恢复可靠后
--   自动交还话语权。
-- ============================================================
local JUDGEMENT_SPELL_IDS = { [20271] = true }
local JUDGEMENT_NAMES = { ["审判"] = true }
local sealCastIndex = nil
-- 功能：建「圣印行 → 光环名/ID」索引（各等级光环名共用，取行首 ID 的 GetSpellInfo 名）。
-- 出参：写入文件局部 sealCastIndex = { rows=行列表, byName={[名]=行}, byID={[ID]=行} }。
local function buildSealCastIndex()
  sealCastIndex = { rows = {}, byName = {}, byID = {} }
  for _, pr in ipairs(presenceRows) do
    if pr.luaDriven and pr.unit == "player" and pr.key and pr.key:find("^seal_") then
      sealCastIndex.rows[#sealCastIndex.rows + 1] = pr
      for _, sid in ipairs(pr.spellIDs or {}) do
        sealCastIndex.byID[sid] = pr
      end
      local okNm, nm = pcall(GetSpellInfo, (pr.spellIDs or {})[1])
      if okNm and type(nm) == "string" then
        sealCastIndex.byName[nm] = pr
      end
    end
  end
end
-- 功能：审判成功——所有圣印行翻灰（审判机制性消耗任意圣印）。
local function flipAllSealRows(now2)
  for _, pr in ipairs(sealCastIndex.rows) do
    pr.green = false
    pr.staleOut = false
    pr.knownAt = now2
    pr.sealAnchor = "combat"
  end
end
-- 功能：某圣印施法成功——命中行翻绿、其余圣印行翻灰（施放新圣印会顶掉旧的）。
local function flipSealRow(pr, now2)
  for _, other in ipairs(sealCastIndex.rows) do
    other.green = (other == pr)
    other.staleOut = false
    other.knownAt = now2
    other.sealAnchor = "combat"
  end
end
local sealEchoFrame = CreateFrame("Frame")
sealEchoFrame:RegisterEvent("UNIT_SPELLCAST_SUCCEEDED")
sealEchoFrame:SetScript("OnEvent", function(_, event, unit, a, b, c, d)
  if unit ~= "player" then
    return
  end
  if not sealCastIndex then
    buildSealCastIndex()
  end
  if #sealCastIndex.rows == 0 then
    return
  end
  local now2 = GetTime()
  -- 客户端事件签名不定（老式 unit,spellName,rank,lineID,spellID / 新式 unit,guid,spellID），
  -- 逐参数试匹配。★ 2026-10-15 二修：战斗中 spellID 是秘密值，== 比对会直接失败
  -- （等价无害跳过）——上一版用 issecretvalue 把整段拦掉，导致回显恰好在战斗中全灭、
  -- 只在脱战生效（用户实测"进战就不补"）。名字串不是秘密值，是战斗中的可靠通道。
  local function matchArg(v)
    local tv = type(v)
    if tv == "string" then
      if JUDGEMENT_NAMES[v] then
        return "judge"
      end
      return sealCastIndex.byName[v]
    elseif tv == "number" then
      if JUDGEMENT_SPELL_IDS[v] then
        return "judge"
      end
      return sealCastIndex.byID[v]
    end
  end
  for _, v in ipairs({ a, b, c, d }) do
    local okM, res = pcall(matchArg, v)
    if okM and res == "judge" then
      flipAllSealRows(now2)
    elseif okM and res then
      flipSealRow(res, now2)
    end
  end
end)

local GROUP_COUNT_SPECS = {
  [65] = true,
  [66] = true,
  [105] = true,
  [256] = true,
  [257] = true,
  [264] = true,
  [270] = true,
  [1468] = true,
}
local dispelContainers = {}
local dispelValidRows = {}
local mouseoverDispelFrame = nil
-- 功能：把字段引用名（rowRef，如 player_health_pct）换算成它在像素数据里的行号（0 基）。
-- 入参：rowRef 字段引用名。
-- 出参：行号；找不到返回 nil。
-- 说明：公共字段排在前、专精字段接在后面，所以两段分开找、第二段要加上公共字段数量。
local function resolveRowIndex(rowRef)
  for index22, commonField in ipairs(WowBuddyDev.COMMON_PIXEL_DATA) do
    if commonField.id == rowRef then
      return index22 - 1
    end
  end
  for index23, specField in ipairs(WowBuddyDev.pixelData) do
    if specField.id == rowRef then
      return #WowBuddyDev.COMMON_PIXEL_DATA + index23 - 1
    end
  end
  return nil
end
local HEAL_ABSORB_SPECS = {
  [105] = true,
  [264] = true,
  [256] = true,
  [257] = true,
  [65] = true,
  [270] = true,
  [1468] = true,
  [66] = true,
}
local HEAL_ABSORB_ROWS = {
  { unit = "player", rowRef = "player_health_pct" },
  { unit = "party1", rowRef = "party1_health_pct" },
  { unit = "party2", rowRef = "party2_health_pct" },
  { unit = "party3", rowRef = "party3_health_pct" },
  { unit = "party4", rowRef = "party4_health_pct" },
  { unit = "mouseover", rowRef = "mouseover_health_pct" },
}
local absorbBarPool = {}
local absorbBars = {}
-- 功能：取（或建）某一行号对应的绿色 StatusBar，并按行号摆到像素容器上。
-- 入参：rowIndex 行号。
-- 出参：StatusBar。
-- 说明：条按行号建、不销毁，避免战斗中反复创建对象；贴图设 ADD 混合、提到父容器上一层，保证盖在色块上面。
local function getStatusBar(rowIndex)
  local absorbBar = absorbBarPool[rowIndex]
  if absorbBar then
    return absorbBar
  end
  absorbBar = CreateFrame("StatusBar", nil, WowBuddyDev.pixelContainer)
  absorbBar:SetSize(barSize, barSize)
  absorbBar:SetMinMaxValues(0, 1)
  absorbBar:SetOrientation("HORIZONTAL")
  absorbBar:SetStatusBarTexture("Interface\\Buttons\\WHITE8X8")
  absorbBar:SetFrameLevel(WowBuddyDev.pixelContainer:GetFrameLevel() + 1)
  absorbBar:EnableMouse(false)
  local statusBarTexture = absorbBar:GetStatusBarTexture()
  statusBarTexture:SetDrawLayer("OVERLAY", 1)
  statusBarTexture:SetBlendMode("ADD")
  absorbBarPool[rowIndex] = absorbBar
  return absorbBar
end
-- 功能：判断单位是不是「活着的友方」（player 恒真）。
-- 入参：unit 单位令牌。
-- 出参：true/false。
local function isLiveFriendlyUnit(unit)
  if unit == "player" then
    return true
  end
  return UnitExists(unit) and (UnitIsFriend("player", unit) and not UnitIsDeadOrGhost(unit))
end
-- 功能：刷新治疗吸收条：友方单位取 UnitGetTotalHealAbsorbs 当条值，取不到就用暗绿整条提示「读不出来」。
-- 入参：无（遍历文件级 absorbBars）。
-- 出参：无。
-- 说明：12.x 里吸收量是秘密值，SetValue 可能直接抛错，所以整段 pcall；失败必须换颜色，否则玩家会把「没吸收」当成「没显示」。
local function refreshHealAbsorbBars()
  for index24, entry in ipairs(absorbBars) do
    local bar = entry.bar
    if isLiveFriendlyUnit(entry.unit) then
      bar:SetStatusBarColor(0, 1, 0, 1)
      local ok = pcall(function()
        bar:SetValue(UnitGetTotalHealAbsorbs(entry.unit))
      end)
      if not ok then
        bar:SetStatusBarColor(0, .35, 0, 1)
        bar:SetValue(1)
      end
    else
      bar:SetStatusBarColor(0, 1, 0, 1)
      bar:SetValue(0)
    end
  end
end
-- 功能：给当前专精重建治疗吸收条：先清空旧条，只有专精在名单里且像素容器已建时才按行号建条。
-- 入参：specID 专精 ID。
-- 出参：无。
local function rebuildHealAbsorbBars(specID)
  for index25, pooledBar in ipairs(absorbBarPool) do
    pooledBar:SetValue(0)
    pooledBar:Hide()
  end
  wipe(absorbBars)
  if not HEAL_ABSORB_SPECS[specID] then
    return
  end
  if not WowBuddyDev.pixelContainer then
    return
  end
  for index26, rowSpec in ipairs(HEAL_ABSORB_ROWS) do
    local rowIndex = resolveRowIndex(rowSpec.rowRef)
    if rowIndex ~= nil then
      local absorbBar = getStatusBar(#absorbBars + 1)
      absorbBar:ClearAllPoints()
      absorbBar:SetPoint("TOPLEFT", WowBuddyDev.pixelContainer, "TOPLEFT", 0, -rowIndex * barSize)
      absorbBar:SetStatusBarColor(0, 1, 0, 1)
      absorbBar:SetValue(0)
      absorbBar:Show()
      absorbBars[#absorbBars + 1] = { unit = rowSpec.unit, bar = absorbBar }
    end
  end
  refreshHealAbsorbBars()
end
-- 功能：判断单独一行光环容器的单位是否「活着的友方」（player 恒真）。
-- 入参：unit 单位令牌。
-- 出参：true/false。
-- 说明：与 isLiveFriendlyUnit 逻辑相同，但服务于不同的容器集合，不能合并（合并会改变调用顺序）。
local function isBarUnitValid(unit)
  return UnitExists(unit) and (UnitIsFriend("player", unit) and not UnitIsDeadOrGhost(unit))
end
-- 功能：刷新独立单位（player / party1-4 等）的光环容器：只在有效性变化的那一次做显隐和刷新。
-- 入参：无（遍历文件级 dispelValidRows）。
-- 出参：无。
local function refreshStandaloneContainers()
  for index27, row in ipairs(dispelValidRows) do
    local isValid = isBarUnitValid(row.unit)
    if isValid then
      if row.valid ~= true then
        row.container:Show()
        row.container:UpdateAllAuras()
      end
    elseif row.valid ~= false then
      row.container:Hide()
    end
    row.valid = isValid
  end
end
-- 功能：刷新鼠标指向的驱散行：指向有效才显示并更新光环，否则隐藏。
-- 入参：无。
-- 出参：无。
local function refreshMouseoverDispel()
  if not mouseoverDispelFrame then
    return
  end
  local isValid = UnitExists("mouseover") and not UnitIsDeadOrGhost("mouseover")
  if isValid then
    mouseoverDispelFrame:Show()
    mouseoverDispelFrame:UpdateAllAuras()
  else
    mouseoverDispelFrame:Hide()
  end
end
-- 功能：给当前专精重建驱散检测容器：只有专精在名单里时才建，focus 交给另一条渲染路径。
-- 入参：contract 当前专精契约；specID 专精 ID。
-- 出参：无。
-- 说明：mouseover 的驱散行额外挂一个 0.1 秒节流的 OnUpdate —— 目标来回移动时不必每帧扫光环。
local function rebuildDispelContainers(contract, specID)
  for k3, container in pairs(dispelContainers) do
    container:Hide()
  end
  wipe(dispelValidRows)
  mouseoverDispelFrame = nil
  if not GROUP_COUNT_SPECS[specID] then
    return
  end
  if not WowBuddyDev.pixelContainer then
    return
  end
  for index28, slot in ipairs(contract or {}) do
    if slot.kind == "dispel_presence" and (slot.unit or "player") ~= "focus" then
      local unit = slot.unit or "player"
      local rowIndex = slot.rowRef and resolveRowIndex(slot.rowRef)
      if rowIndex == nil then
        print("dispel_presence: 找不到血量字段 " .. tostring(slot.rowRef))
      end
      local cacheKey = tostring(specID) .. ":dispel:" .. unit
      local dispelContainer = dispelContainers[cacheKey]
      if not dispelContainer then
        dispelContainer = CreateFrame("AuraContainer", nil, WowBuddyDev.pixelContainer, "CustomAuraContainerTemplate")
        dispelContainer:SetSize(barSize, barSize)
        dispelContainer:SetPoint("TOPLEFT", WowBuddyDev.pixelContainer, "TOPLEFT", 0, -(rowIndex or 0) * barSize)
        dispelContainer:AddAuraSlot(slot.key, getAuraFilter(slot), {
          candidateFilters = { includeDispelTypes = buildDispelTypeSet(slot.dispelTypes) },
          -- 功能：光环格子的初始化回调：定尺寸、摆位，铺一层底衬，并关掉格子的鼠标响应。
          -- 入参：cell 光环容器交给回调的单格 Frame。
          -- 出参：无。
          -- 说明：这个键在文件里有两处定义，工具按同一个键给两处插同一段注释——第一处是同队人数的格子（深色底衬、按创建时固定的 rowIndex 逐行错开），第二处是驱散格子（红色底衬、铺满格位并画在更上层）。底衬的显隐由渲染逻辑控制，初始化只负责把格子准备好；SetMouseClickEnabled / SetMouseMotionEnabled 在部分客户端不存在，所以用 pcall 试探后再调。
          initializeFrame = function(cell)
            cell:SetSize(barSize, barSize)
            cell:ClearAllPoints()
            cell:SetPoint("TOPLEFT", cell:GetParent(), "TOPLEFT", 0, 0)
            local dispelTexture = cell:CreateTexture(nil, "OVERLAY")
            dispelTexture:SetAllPoints(cell)
            dispelTexture:SetDrawLayer("OVERLAY", 2)
            dispelTexture:SetBlendMode("ADD")
            dispelTexture:SetColorTexture(1, 0, 0, 1)
            if cell.SetMouseClickEnabled then
              pcall(cell.SetMouseClickEnabled, cell, false)
            end
            if cell.SetMouseMotionEnabled then
              pcall(cell.SetMouseMotionEnabled, cell, false)
            end
          end,
        })
        dispelContainer:SetUnit(unit)
        dispelContainer:UpdateAllAuras()
        dispelContainers[cacheKey] = dispelContainer
        if unit == "mouseover" then
          local mouseoverThrottleFrame = CreateFrame("Frame")
          local elapsed = 0
          mouseoverThrottleFrame:SetScript("OnUpdate", function(self, event)
            elapsed = elapsed + event
            if elapsed < .1 then
              return
            end
            elapsed = 0
            refreshMouseoverDispel()
          end)
        end
      end
      if unit == "mouseover" then
        mouseoverDispelFrame = dispelContainer
        refreshMouseoverDispel()
      else
        dispelValidRows[#dispelValidRows + 1] = { container = dispelContainer, unit = unit }
      end
    end
  end
  refreshStandaloneContainers()
end
-- 功能：渲染底衬条区域的所有「存在性」行（presence / loc_presence / 同队人数 / 驱散焦点 / 充能光环回退 / 光环层数）。
-- 入参：contract 当前专精契约；specID 专精 ID；originRow 这一片区域的起始行号。
-- 出参：无。
-- 说明：先把契约展开成逐行计划（rowPlans），再按单位分组建容器；同一专精重复进来复用已有容器，只重新摆位。
local function renderPresenceRows(contract, specID, originRow)
  activeSpecID = specID
  for k4, staleContainer in pairs(barContainers) do
    staleContainer:Hide()
  end
  for k5, pool in pairs(groupCountPools) do
    for index29, pooledContainer in ipairs(pool) do
      pooledContainer:Hide()
      pooledContainer.groupCountActive = false
    end
  end
  groupCountRows = {}
  locRows = {}
  presenceRows = {}
  -- 回显索引持有行对象；重建后下一次事件须索引新行。
  sealCastIndex = nil
  local rowPlans = {}
  for index30, contractSlot in ipairs(contract or {}) do
    if contractSlot.kind == "presence" or contractSlot.kind == "presence_group_count" then
      rowPlans[#rowPlans + 1] = { slot = contractSlot }
    elseif contractSlot.kind == "presence_all" or contractSlot.kind == "presence_count" or contractSlot.kind == "presence_index" then
      for index31, spellID in ipairs(contractSlot.spellIDs or {}) do
        rowPlans[#rowPlans + 1] = { slot = contractSlot, spellID = spellID, sub = index31 }
      end
    elseif contractSlot.kind == "loc_presence" then
      rowPlans[#rowPlans + 1] = { slot = contractSlot, loc = true }
    elseif contractSlot.kind == "dispel_presence" and (GROUP_COUNT_SPECS[specID] and (contractSlot.unit or "player") == "focus") then
      rowPlans[#rowPlans + 1] = { slot = contractSlot, dispelFocus = true }
    elseif contractSlot.kind == "charge_lua" and contractSlot.fallbackAuraSpellID then
      rowPlans[#rowPlans + 1] = { slot = contractSlot, spellID = contractSlot.fallbackAuraSpellID, chargeFallback = true }
    elseif contractSlot.kind == "aura_seconds" and contractSlot.unit == "mouseover" then
      rowPlans[#rowPlans + 1] = { slot = contractSlot, mouseoverValidity = true }
    elseif contractSlot.kind == "aura_stacks" then
      if not contractSlot.no_companion then
        rowPlans[#rowPlans + 1] = { slot = contractSlot }
      end
    end
  end
  for i4 = #rowPlans + 1, #rowFrames, 1 do
    rowFrames[i4]:Hide()
  end
  if #rowPlans == 0 then
    return
  end
  ensureBottomFrame(originRow + #rowPlans)
  local plansByUnit = {}
  for index32, plan in ipairs(rowPlans) do
    local rowIndex = originRow + index32 - 1
    local rowFrame = rowFrames[index32]
    if not rowFrame then
      rowFrame = CreateFrame("Frame", nil, bottomFrame)
      rowFrame:SetSize(barSize, barSize)
      rowFrame:EnableMouse(false)
      local dimTexture = rowFrame:CreateTexture(nil, "OVERLAY")
      dimTexture:SetAllPoints(rowFrame)
      dimTexture:SetColorTexture(dimLevel, dimLevel, dimLevel, 1)
      rowFrame.dimTex = dimTexture
      rowFrames[index32] = rowFrame
    end
    rowFrame:ClearAllPoints()
    rowFrame:SetPoint("TOPLEFT", bottomFrame, "TOPLEFT", 0, -rowIndex * barSize)
    rowFrame.dimTex:SetColorTexture(dimLevel, dimLevel, dimLevel, 1)
    rowFrame:Show()
    if plan.slot.kind == "presence_group_count" then
      rowFrame.dimTex:SetColorTexture(0, 0, 0, 1)
      createGroupCountRow(plan.slot, specID, rowIndex)
    elseif plan.loc then
      local locTypeSet = {}
      for index33, locType in ipairs(plan.slot.locTypes or {}) do
        locTypeSet[locType] = true
      end
      locRows[#locRows + 1] = { row = rowFrame, locTypeSet = locTypeSet }
    else
      local unit = plan.slot.unit or "player"
      if plan.slot.kind == "presence" then
        local presenceSpellIDs = plan.slot.spellIDs
        if not presenceSpellIDs and plan.slot.spellID then
          presenceSpellIDs = { plan.slot.spellID }
        end
        if presenceSpellIDs then
          -- 玩家增益行 + party1-4 的 HELPFUL 行（治疗 HoT/护盾判据）+ 目标行（DoT 维护判据）
          -- 都走 lua 直读：容器层会把还剩几百秒的光环画灰，战斗中 spellId 秘密值还会整行掉灰——
          -- 「换目标就重放荆棘术」同款病。治疗循环战斗中依赖 party HoT 行；输出循环的
          -- 痛/月火/腐蚀/撕裂等 DoT 行同理（否则每个压制期到点就重铺一发）。
          -- lua 查询已有名字兜底与战斗保持原色（queryAuraPresence / refreshPresenceRows），
          -- 灰度口径与容器一致（dimLevel），读取端解码不变。
          -- 鼠标指向/焦点行不动，仍由容器出像素（mouseover 有专门的刷新逻辑）。
          local rowFilter = getAuraFilter(plan.slot)
          plan.luaPresence = unit == "player"
            or unit == "target"
            or (unit:match("^party[1-4]$") and rowFilter and rowFilter:find("HELPFUL") ~= nil)
          presenceRows[#presenceRows + 1] = {
            row = rowFrame,
            rowIndex = rowIndex,
            key = plan.slot.key,
            unit = unit,
            luaDriven = plan.luaPresence,
            filter = rowFilter,
            spellIDs = presenceSpellIDs,
            green = false,
            staleOut = false,
            knownAt = GetTime()
          }
        end
      end
      local groupKey = unit
      if unit == "mouseover" and plan.slot.unitRelation == "help" then
        groupKey = unit .. ":help"
      end
      plansByUnit[groupKey] = plansByUnit[groupKey] or {}
      plansByUnit[groupKey][#plansByUnit[groupKey] + 1] = { item = plan, rowIndex = rowIndex, row = rowFrame }
    end
  end
  -- 说明：玩家增益行（plan.luaPresence）在这里直接不建格，像素唯一由 refreshPresenceRows 涂底衬决定。
  --       之前靠「建完再 Hide 格子」压容器，压不干净：容器在 AddAuraSlot / UpdateAllAuras / Show 之后
  --       都会把格子重新点亮，到下一轮 refreshPresenceRows（0.25 秒）之间有空档，灰像素就是从空档里被
  --       读走的——「换目标就重放荆棘术」撞的正是这里。不留格子就没有空档。
  for k6, unitPlans in pairs(plansByUnit) do
    local unit = unitPlans[1].item.slot.unit or "player"
    local cacheKey = tostring(specID) .. ":bar:" .. k6
    local barContainer = barContainers[cacheKey]
    if not barContainer then
      barContainer = CreateFrame("AuraContainer", nil, bottomFrame, "CustomAuraContainerTemplate")
      barContainer:SetSize(1, 1)
      barContainer:SetPoint("TOPLEFT", bottomFrame, "TOPLEFT", 0, 0)
      for index34, slotPlan in ipairs(unitPlans) do
        local slot = slotPlan.item.slot
        local cellRecord = { slot = slot, unit = unit, specID = specID, rowIndex = slotPlan.rowIndex, backdrop = slotPlan.row }
        presenceCellRecords[tostring(specID) .. ":" .. slotPlan.rowIndex] = cellRecord
        if not slotPlan.item.luaPresence then
          local slotKey = slotPlan.item.chargeFallback and slot.key .. "#fallback_stk" or slotPlan.item.sub and slot.key .. "#" .. slotPlan.item.sub or slotPlan.item.mouseoverValidity and slot.key .. "#mouseover_validity" or (slot.kind == "aura_stacks" and slot.key .. "#stk" or slot.key)
          local spellIdSet = (slotPlan.item.sub or slotPlan.item.chargeFallback) and { [slotPlan.item.spellID] = true } or buildSpellIdSet(slot)
          local slotOptions = { initializeFrame = createDimInitializer(slotPlan.rowIndex, cellRecord) }
          if slotPlan.item.dispelFocus then
            slotOptions.candidateFilters = { includeDispelTypes = buildDispelTypeSet(slot.dispelTypes) }
          elseif slot.dispelTypes then
            slotOptions.candidateFilters = { includeDispelTypes = buildDispelTypeSet(slot.dispelTypes) }
          elseif spellIdSet then
            slotOptions.candidateFilters = { includeSpellIDs = spellIdSet }
          end
          barContainer:AddAuraSlot(slotKey, getAuraFilter(slot), slotOptions)
        end
      end
      barContainer:SetUnit(unit)
      barContainer:UpdateAllAuras()
      barContainers[cacheKey] = barContainer
      if unit == "focus" or unit == "target" or unit == "mouseover" then
        local unitEventFrame = CreateFrame("Frame")
        local unitEvent = unit == "focus" and "PLAYER_FOCUS_CHANGED" or unit == "target" and "PLAYER_TARGET_CHANGED" or "UPDATE_MOUSEOVER_UNIT"
        unitEventFrame:RegisterEvent(unitEvent)
        unitEventFrame:SetScript("OnEvent", function()
          if unit == "mouseover" then
            refreshMouseoverRow(barContainer, unitPlans, specID)
          else
            barContainer:UpdateAllAuras()
          end
        end)
        if unit == "mouseover" then
          local elapsed = 0
          unitEventFrame:SetScript("OnUpdate", function(self2, event2)
            elapsed = elapsed + event2
            if elapsed < .1 then
              return
            end
            elapsed = 0
            refreshMouseoverRow(barContainer, unitPlans, specID)
          end)
        end
      end
    end
    if unit == "mouseover" then
      refreshMouseoverRow(barContainer, unitPlans, specID)
    else
      barContainer:Show()
    end
  end
  updateGroupCount(true)
  refreshLocRows()
end
-- 功能：取当前专精 ID。
-- 入参：无。
-- 出参：专精 ID；没选专精返回 nil。
local function getSpecID()
  local specIndex = GetSpecialization and GetSpecialization()
  if not specIndex then
    return nil
  end
  return GetSpecializationInfo(specIndex)
end
local driverStarted = false
-- 功能：建常驻驱动帧：0.05 秒一次刷新所有面板数字与光环，并监听失控和名册事件触发即时刷新。
-- 入参：无。
-- 出参：无。
-- 说明：有 driverStarted 保护，重复调用直接返回，避免挂上第二个 OnUpdate 让刷新量翻倍。
local function startDriver()
  if driverStarted then
    return
  end
  driverStarted = true
  local driverFrame = CreateFrame("Frame")
  local elapsed = 0
  -- 实测长时间光环（荆棘术 467 剩余 579 秒）在原生 AuraContainer 里翻绿后约 9 秒会自己掉灰，
  -- 期间不派发任何光环事件；5 Hz 全量重扫 UpdateAllAuras 实测救不回来（容器自己的结论就是错的）。
  -- 只涂底衬也救不回来：容器掉灰时格子仍是「显示 + alpha 1」，灰画在格子里、压在 L9998 底衬之上。
  -- 所以玩家增益行干脆不往容器注册格子，改由 refreshPresenceRows 每 0.25 秒直读光环涂底衬。
  local presenceTicks = 0
  driverFrame:SetScript("OnUpdate", function(self3, event3)
    elapsed = elapsed + event3
    if elapsed >= .05 then
      elapsed = 0
      refreshCooldownRows()
      refreshChargeRows()
      refreshLocRows()
      refreshHealAbsorbBars()
      refreshStandaloneContainers()
      updateGroupCount(false)
      presenceTicks = presenceTicks + 1
      if presenceTicks >= 5 then
        presenceTicks = 0
        refreshPresenceRows()
      end
    end
  end)
  driverFrame:RegisterEvent("LOSS_OF_CONTROL_ADDED")
  driverFrame:RegisterEvent("LOSS_OF_CONTROL_UPDATE")
  driverFrame:RegisterEvent("PLAYER_CONTROL_LOST")
  driverFrame:RegisterEvent("PLAYER_CONTROL_GAINED")
  driverFrame:RegisterEvent("GROUP_ROSTER_UPDATE")
  driverFrame:SetScript("OnEvent", function(self4, eventName)
    refreshLocRows()
    if eventName == "GROUP_ROSTER_UPDATE" then
      updateGroupCount(true)
    end
  end)
end
-- 功能：按当前专精把四块面板全部重渲染：底衬条、驱散行、治疗吸收条、横排数字面板。
-- 入参：无。
-- 出参：无。
local function refreshAllPanels()
  local specID = getSpecID()
  local contract = specID and WowBuddyDev._pixelStripV2BySpec[specID] or nil
  local originRow = #WowBuddyDev.COMMON_PIXEL_DATA + #WowBuddyDev.pixelData
  renderPresenceRows(contract, specID, originRow)
  rebuildDispelContainers(contract, specID)
  rebuildHealAbsorbBars(specID)
  renderPanel(contract, specID)
end
local refreshPending = false
-- 功能：把「下一帧需要整面板重建」的标记置上。
-- 入参：无。
-- 出参：无。
-- 说明：天赋/专精变一次往往连着来好几个事件，这里只置标记、由 fn40 那一帧合并成一次重建，避免连续重建面板。
local function requestFastRefresh()
  refreshPending = true
end
local specEventFrame = CreateFrame("Frame")
specEventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
specEventFrame:RegisterEvent("ACTIVE_TALENT_GROUP_CHANGED")
specEventFrame:RegisterEvent("PLAYER_SPECIALIZATION_CHANGED")
specEventFrame:SetScript("OnEvent", function(self5, eventName)
  if eventName == "PLAYER_ENTERING_WORLD" then
    ensurePanelFrame()
    startDriver()
    refreshAllPanels()
  else
    requestFastRefresh()
  end
end)
local refreshFrame = CreateFrame("Frame")
refreshFrame:SetScript("OnUpdate", function()
  if refreshPending then
    refreshPending = false
    refreshAllPanels()
  end
end)
-- 功能：打印当前专精的 v2 面板状态与每个契约槽位的实时取值，供 /pmsv2 排查。
-- 入参：无。
-- 出参：无（只 print）。
-- 说明：不查 CDM、只读契约与客户端 API，所以任何专精下都能安全执行。
function WowBuddyDev.DumpV2State()
  local specID = getSpecID()
  print(string.format("v2 状态: 专精=%s 面板=%s 图标=%d 底行=%d 冷却槽=%d 充能行=%d 时长绑定API=%s", tostring(specID), panelFrame and (panelFrame:IsShown() and "显示" or "隐藏") or "未建", rowCount, #rowFrames, #cdRows, #chargeRows, C_DurationUtil and C_DurationUtil.CreateDurationTextBinding and "可用" or "不可用"))
  local contract = specID and WowBuddyDev._pixelStripV2BySpec[specID]
  if not contract then
    print("当前专精无 v2 契约")
    return
  end
  for index35, slot in ipairs(contract) do
    local line = ""
    if slot.kind == "cd_seconds" then
      local spellIDList = slot.spellIDs or { slot.spellID }
      local spellIdSet = nil
      if slot.spellIDs then
        spellIdSet = {}
        for index36, candidateID in ipairs(spellIDList) do
          spellIdSet[candidateID] = true
        end
      end
      local lines = {}
      for index37, spellID in ipairs(spellIDList) do
        local cooldownDuration, chargeDuration, isOverridden = nil, nil, false
        if spellIdSet and (C_Spell and C_Spell.GetOverrideSpell) then
          local callOK, overrideSpellID = pcall(C_Spell.GetOverrideSpell, spellID, 0, false)
          if callOK and (type(overrideSpellID) == "number" and (overrideSpellID ~= spellID and spellIdSet[overrideSpellID])) then
            isOverridden = true
          end
        end
        if C_Spell and C_Spell.GetSpellCooldownDuration then
          local cdCallOK, cdDuration = pcall(C_Spell.GetSpellCooldownDuration, spellID, true)
          if cdCallOK then
            cooldownDuration = cdDuration
          end
        end
        if C_Spell and C_Spell.GetSpellChargeDuration then
          local chargeCallOK, rawChargeDuration = pcall(C_Spell.GetSpellChargeDuration, spellID)
          if chargeCallOK then
            chargeDuration = rawChargeDuration
          end
        end
        lines[#lines + 1] = string.format("%d:冷却=%s 充能=%s%s", spellID, cooldownDuration ~= nil and "有" or "无", chargeDuration ~= nil and "有" or "无", isOverridden and "(被替换)" or "")
      end
      line = " " .. table.concat(lines, " ")
    elseif slot.kind == "aura_seconds" or slot.kind == "aura_stacks" or slot.kind:find("^presence") then
      local unit = slot.unit or "player"
      local auraFilter = getAuraFilter(slot)
      local spellIDList = slot.spellIDs or { slot.spellID }
      local auraText = "无"
      local auraOK = pcall(function()
        for i5 = 1, 40, 1 do
          local auraData = C_UnitAuras.GetAuraDataByIndex(unit, i5, auraFilter)
          if not auraData then
            break
          end
          for index38, listedSpellID in ipairs(spellIDList) do
            local readOK, matches = pcall(function()
              return auraData.spellId == listedSpellID
            end)
            if readOK and matches then
              local textOK, applicationsText = pcall(tostring, auraData.applications)
              auraText = "有(层数=" .. (textOK and applicationsText or "?") .. ")"
              break
            end
          end
          if auraText ~= "无" then
            break
          end
        end
      end)
      if not auraOK then
        auraText = "受限(12.1)"
      end
      line = " aura=" .. auraText
    end
    print(string.format("  %s kind=%s unit=%s spell=%s%s", slot.key, slot.kind, slot.unit or "player", tostring(slot.spellID or slot.spellIDs and table.concat(slot.spellIDs, "/")), line))
  end
end
SLASH_PERMESV21 = "/pmsv2"
-- 功能：/pmsv2 命令：打印 V2 面板的当前状态。
-- 入参：无。
-- 出参：无。
-- 说明：实际输出逻辑全在 P07483180.DumpV2State 里，这里只是命令入口。
SlashCmdList.PERMESV2 = function()
  WowBuddyDev.DumpV2State()
end
local presenceProbe = nil
-- 功能：按行号取回登记过的容器格记录（含同位置的灰底衬帧）。
-- 入参：row 行号。
-- 出参：记录表或 nil。
-- 说明：键里带专精 ID，避免切专精后拿到上一个专精留下的旧格子。
local function getPresenceRecord(row)
  return row and presenceCellRecords[tostring(getSpecID()) .. ":" .. tostring(row)] or nil
end
-- 功能：按行框反查 refreshPresenceRows 登记的那一条。
-- 入参：rowFrame 行框（可为 nil）。
-- 出参：登记条目，没登记返回 nil。
-- 说明：SetColorTexture 涂的颜色没有 getter（GetVertexColor 读的是另一套顶点色，恒为 1/1/1），
--       取证只能读回 Lua 自己记的那份状态。
local function findPresenceRowEntry(rowFrame)
  if not rowFrame then
    return nil
  end
  for index26, presenceRow in ipairs(presenceRows) do
    if presenceRow.row == rowFrame then
      return presenceRow
    end
  end
  return nil
end
-- 功能：采一笔对照读数：这一格的显示状态 vs 手动 C_UnitAuras 扫描结果 vs 战斗锁定。
-- 入参：record 格子记录。
-- 出参：一行短字符串。
-- 说明：全程只读、pcall 包死。战斗中 spellId 可能是秘密值（见 refreshLocRows 的 issecretvalue 与 DebugAuras.lua:78），
--       读不到要在文本里明写出来，不能和「真的没光环」混成一笔。
local function presenceProbeSample(record)
  local cell = record.cell
  local text = cell and (string.format("格%s a%.2f L%d 父L%d", cell:IsShown() and "显" or "隐", cell:GetAlpha() or 1,
    cell:GetFrameLevel() or -1, cell:GetParent() and cell:GetParent():GetFrameLevel() or -1)) or "格无"
  local backdrop = record.backdrop
  local paintedEntry = findPresenceRowEntry(backdrop)
  local paintedText = paintedEntry and ((paintedEntry.green and "绿" or "灰") .. (paintedEntry.staleOut and "(读不出超时)" or "")) or "未登记"
  text = text .. (backdrop and string.format("｜底%s a%.2f L%d 涂%s", backdrop:IsShown() and "显" or "隐",
    (backdrop.dimTex and backdrop.dimTex:GetAlpha()) or -1, backdrop:GetFrameLevel() or -1, paintedText) or "｜底无")
  local idSet = buildSpellIdSet(record.slot)
  local found, walked, tail = 0, 0, ""
  local scanOK = pcall(function()
    local filter = getAuraFilter(record.slot)
    for index = 1, 40, 1 do
      local aura = C_UnitAuras.GetAuraDataByIndex(record.unit or "player", index, filter)
      if not aura then
        break
      end
      walked = walked + 1
      local readOK, hit = pcall(function()
        return idSet ~= nil and idSet[aura.spellId] == true
      end)
      if not readOK then
        tail = "ID是秘密值(中止)"
        break
      elseif hit then
        found = index
        local durOK, remain = pcall(function()
          return math.floor(((aura.expirationTime or 0) - GetTime()) * 10 + .5) / 10
        end)
        tail = durOK and ("剩" .. tostring(remain) .. "s") or "时长读不到"
        break
      end
    end
  end)
  if not scanOK then
    tail = "扫描抛错"
  end
  text = text .. string.format("｜手扫=%s/%d %s", found > 0 and ("有#" .. found) or "无", walked, tail)
  local verdictList = record.slot.spellIDs or (record.slot.spellID and { record.slot.spellID })
  if verdictList then
    local verdictOK, verdict = pcall(queryAuraPresence, record.unit or "player", getAuraFilter(record.slot), verdictList)
    text = text .. ("｜Lua判=" .. ((verdictOK and (verdict == nil and "读不出" or verdict and "有" or "无")) or "抛错"))
  end
  local combatOK, combat = pcall(InCombatLockdown)
  text = text .. (combatOK and (combat and "｜战斗" or "｜脱战") or "｜锁定读不到")
  local targetOK, targetName = pcall(function()
    return UnitExists("target") and (UnitName("target") or "?") or "无"
  end)
  text = text .. ("｜目标=" .. ((targetOK and targetName) or "读不到"))
  return text
end
SLASH_PMPROBE1 = "/pmsprobe"
-- 功能：/pmsprobe <行号或槽位名> 掉灰取证：每 0.1 秒采一笔对照读数，只在读数变化或每满 1 秒时记一行，结果写 SemrepDB.presenceProbe。
-- 入参：text 行号（如 157）、槽位 key（如 thorns）或中文名（如 荆棘术）；探针跑着时再敲一次本命令即停止。
-- 出参：无（落 SavedVariables；/reload 或退出才写盘，外部从 WTF 读，通道口径同 BuildCompat.lua:294）。
-- 说明：上限 600 笔 / 180 秒自动收尾，防止把存档撑大。用来分清掉灰是「容器判定光环没了」还是「绿贴图被同位置灰底衬盖住」。
SlashCmdList.PMPROBE = function(text)
  if presenceProbe then
    presenceProbe.frame:Hide()
    print(string.format("[PMS探针] 已停止，共 %d 笔 → WowBuddyDevDB.presenceProbe，敲 /reload 落盘", #presenceProbe.trace))
    presenceProbe = nil
    return
  end
  local wanted = (text or ""):match("^%s*(%S+)")
  local row = tonumber(wanted)
  if not row and wanted then
    local specPrefix = tostring(getSpecID()) .. ":"
    for cacheKey2, cachedRecord in pairs(presenceCellRecords) do
      if cacheKey2:sub(1, #specPrefix) == specPrefix and cachedRecord.slot
        and (cachedRecord.slot.key == wanted or cachedRecord.slot.name == wanted) then
        row = tonumber(cacheKey2:match(":(%d+)$"))
        break
      end
    end
  end
  if not row then
    print("用法：/pmsprobe <行号或槽位名>（如 /pmsprobe 157、/pmsprobe thorns、/pmsprobe 荆棘术；再敲一次停止）")
    return
  end
  local record = getPresenceRecord(row)
  if not record then
    print("[PMS探针] 行 " .. row .. " 没登记（这一行不是光环存在性行，或容器还没建起来）")
    return
  end
  WowBuddyDevDB = WowBuddyDevDB or {}
  local registeredIndex = 0
  for index25, presenceRow in ipairs(presenceRows) do
    if presenceRow.row == record.backdrop then
      registeredIndex = index25
      break
    end
  end
  local trace = { string.format("行=%d key=%s 单位=%s 过滤器=%s｜直查API 玩家=%s 任意=%s｜presenceRows 第%d/%d",
    row, tostring(record.slot.key), tostring(record.unit or "player"), tostring(getAuraFilter(record.slot)),
    tostring((C_UnitAuras and C_UnitAuras.GetPlayerAuraBySpellID) ~= nil),
    tostring((C_UnitAuras and C_UnitAuras.GetAuraDataBySpellID) ~= nil),
    registeredIndex, #presenceRows) }
  WowBuddyDevDB.presenceProbe = trace
  local started = GetTime()
  local elapsed, last, beat = 0, "", 10
  local probeFrame = CreateFrame("Frame")
  presenceProbe = { frame = probeFrame, trace = trace }
  probeFrame:SetScript("OnUpdate", function(self, delta)
    elapsed = elapsed + delta
    if elapsed < .1 then
      return
    end
    elapsed = 0
    local line = presenceProbeSample(record)
    local wallOK, wall = pcall(function()
      return date("%H:%M:%S")
    end)
    beat = beat + 1
    if line ~= last or beat >= 10 then
      last = line
      beat = 0
      trace[#trace + 1] = string.format("%.1f %s %s", GetTime() - started, (wallOK and wall) or "?", line)
    end
    if #trace >= 600 or GetTime() - started >= 180 then
      trace[#trace + 1] = "收尾"
      probeFrame:Hide()
      presenceProbe = nil
      print("[PMS探针] 采样到顶，已写 WowBuddyDevDB.presenceProbe，敲 /reload 落盘")
    end
  end)
  print("[PMS探针] 开始采行 " .. row .. "（" .. tostring(record.slot.key) .. "），打满 2 分钟后 /reload 落盘")
end
SLASH_PMSRAISE1 = "/pmsraise"
-- 功能：/pmsraise <行号> 对照实验：把这一格的容器（和格子本身）帧层高压到同位置灰底衬之上。
-- 入参：text 行号。
-- 出参：无（只改帧层高，敲 /reload 就复原）。
-- 说明：掉灰的两种可能里，这一条专门验「绿贴图被盖住」：抬完立刻不再掉灰 = 盖住；抬完照旧掉灰 = 容器自己判定没了。
SlashCmdList.PMSRAISE = function(text)
  local row = tonumber((text or ""):match("%d+"))
  local record = getPresenceRecord(row)
  if not record or not record.cell then
    print("[PMS抬高] 行 " .. tostring(row) .. " 没登记到容器格")
    return
  end
  local cell = record.cell
  local container = cell:GetParent()
  print(string.format("[PMS抬高] 格 L%s→%s 父 L%s→%s（底衬 L%s）", tostring(cell:GetFrameLevel()),
    "32768", tostring(container and container:GetFrameLevel()), "32767",
    tostring(record.backdrop and record.backdrop:GetFrameLevel())))
  cell:SetFrameLevel(32768)
  if container then
    container:SetFrameLevel(32767)
  end
end
SLASH_PMSROWS1 = "/pmsrows"
-- 功能：/pmsrows 命令：把当前天赋下所有已登记的格子「行号 → 槽位名/单位/过滤器/我涂的颜色」写进 SemrepDB.presenceRowMap。
-- 入参：无。
-- 出参：无（落 SavedVariables；/reload 或退出才写盘，外部从 WTF 读）。
-- 说明：行号是「公共字段数 + 契约顺序」推出来的，换天赋换版本就变；已经因为猜行号采错过一次
--       （158 采到的是 moonfire 而不是荆棘术），所以取证前先打这张表，别再猜。
SlashCmdList.PMSROWS = function()
  WowBuddyDevDB = WowBuddyDevDB or {}
  local specPrefix = tostring(getSpecID()) .. ":"
  local rowLines = {}
  for cacheKey3, cachedRecord in pairs(presenceCellRecords) do
    if cacheKey3:sub(1, #specPrefix) == specPrefix and cachedRecord.slot then
      local entry = findPresenceRowEntry(cachedRecord.backdrop)
      local paintText = "未登记"
      if entry then
        if not entry.luaDriven then
          paintText = "容器"
        else
          paintText = (entry.green and "绿" or "灰") .. (entry.staleOut and "(读不出超时)" or "")
        end
      end
      local cellText = "无"
      if cachedRecord.cell then
        cellText = cachedRecord.cell:IsShown() and "显" or "隐"
      end
      -- IDs/判 是本案取证用的：绿灰只由 entry.green 决定，判错就得看它到底拿哪批 ID 去查的。
      local idsText = "无登记"
      local liveText = "无登记"
      if entry then
        idsText = table.concat(entry.spellIDs or {}, "/")
        local okV, verdict = pcall(queryAuraPresence, entry.unit, entry.filter, entry.spellIDs)
        liveText = tostring(okV and verdict or ("抛错:" .. tostring(verdict)))
      end
      rowLines[#rowLines + 1] = string.format("行=%s key=%s 名=%s 单位=%s 过滤器=%s 涂=%s 格=%s IDs=%s 判=%s",
        tostring(cacheKey3:match(":(%d+)$")), tostring(cachedRecord.slot.key), tostring(cachedRecord.slot.name),
        tostring(cachedRecord.unit or "player"), tostring(getAuraFilter(cachedRecord.slot)),
        paintText, cellText, idsText, liveText)
    end
  end
  table.sort(rowLines, function(leftLine, rightLine)
    local leftRow = tonumber(leftLine:match("行=(%d+)")) or 0
    local rightRow = tonumber(rightLine:match("行=(%d+)")) or 0
    return leftRow < rightRow
  end)
  WowBuddyDevDB.presenceRowMap = rowLines
  print(string.format("[PMS行表] 天赋=%s 共 %d 行 → WowBuddyDevDB.presenceRowMap，敲 /reload 落盘",
    tostring(getSpecID()), #rowLines))
end
SLASH_PMSPX31 = "/pmspx3"
-- 功能：/pmspx3 命令：实时逐帧记录「玩家增益行」的判定、贴图颜色、帧几何，写进 SemrepDB.presencePixelTrace。
-- 入参：可选，空格分隔的 spellID 白名单；不填就记全部 luaDriven 行。
-- 出参：无（采满 400 行或 60 秒自动收尾；敲 /reload 落盘，再敲一次提前停）。
-- 说明：/pmsrows 那张表是靠「容器底衬」反查登记行的，而玩家增益行在 v4 里压根没有容器格子，
--       查到的 entry 不可信（实测出现过 mark_wild 绿 / thorns 灰同时只有一格绿）。这条探针不经过容器，
--       直接 ipairs(presenceRows) 把每条自己的 row 指针、GetCenterPoint、dimTex 顶点色、
--       以及 GetPlayerAuraBySpellID 逐个 ID 的命中情况一起记下来，一次分清楚三件事：
--       ①两条行是不是共用同一个帧（指针/中心相同 ⇒ 涂像素互相覆盖）；
--       ②判定是不是错（命中列表有 ID 但绿=否 ⇒ 判到涂之间断了）；
--       ③涂出来是不是绿（色=绿但引擎读灰 ⇒ 像素被别的东西盖住/位置对不上）。
_G.PMS3RUN = _G.PMS3RUN or nil
SlashCmdList.PMSPX3 = function(text)
  WowBuddyDevDB = WowBuddyDevDB or {}
  if _G.PMS3RUN then
    _G.PMS3RUN:Hide()
    _G.PMS3RUN = nil
    print("[PMS3] 已提前停止 → WowBuddyDevDB.presencePixelTrace，敲 /reload 落盘")
    return
  end
  -- 先把表挂到 SemrepDB 上再干活：中途抛错也要留得下已采的部分和那条错，
  -- 否则磁盘上一片空白，分不清是「命令没落地」还是「落地了但报错」。
  local trace = { "起:" .. tostring(WowBuddyDevDB.panelStamp or "?") }
  WowBuddyDevDB.presencePixelTrace = trace
  local okRun, errRun = pcall(function()
    local wanted = {}
    for idText in (text or ""):gmatch("%d+") do
      wanted[tonumber(idText)] = true
    end
    local seenRow = {}
    local collisionLines = {}
    for index34, presenceRow in ipairs(presenceRows) do
      local rowKey = tostring(presenceRow.row)
      if seenRow[rowKey] then
        collisionLines[#collisionLines + 1] = string.format("撞车:第%s条与第%s条同一个帧=%s",
          tostring(seenRow[rowKey]), tostring(index34), rowKey)
      else
        seenRow[rowKey] = index34
      end
    end
    trace[#trace + 1] = string.format("头:presenceRows=%s rowFrames=%s 撞车=%s barSize=%s luaDriven=%s",
      tostring(#presenceRows), tostring(#rowFrames), tostring(#collisionLines), tostring(barSize),
      tostring(presenceRows[1] and presenceRows[1].luaDriven))
    for index35, collisionLine in ipairs(collisionLines) do
      trace[#trace + 1] = collisionLine
    end
    local probeFrame = CreateFrame("Frame")
    _G.PMS3RUN = probeFrame
    local elapsed3 = 0
    local started3 = GetTime()
    local lastLine3 = ""
    local beat3 = 0
    probeFrame:SetScript("OnUpdate", function(self5, delta5)
      elapsed3 = elapsed3 + delta5
      if elapsed3 < .2 then
        return
      end
      elapsed3 = 0
      beat3 = beat3 + 1
      for index36, presenceRow in ipairs(presenceRows) do
        if presenceRow.luaDriven and presenceRow.row and presenceRow.row.dimTex then
          local include = (next(wanted) == nil)
          for index37, spellID3 in ipairs(presenceRow.spellIDs or {}) do
            if wanted[spellID3] then
              include = true
            end
          end
          if include then
            -- 单行包 pcall：任何一格取值抛错都不能把整轮采样带崩（那正是「只有一格会涂灰」最像的形态）。
            local okLine3, line3 = pcall(function()
              local hitText = {}
              for index38, spellID4 in ipairs(presenceRow.spellIDs or {}) do
                local callOK3, auraData3 = pcall(C_UnitAuras.GetPlayerAuraBySpellID, spellID4)
                if callOK3 and auraData3 ~= nil then
                  hitText[#hitText + 1] = tostring(spellID4)
                end
              end
              local center3, center4 = presenceRow.row:GetCenterPoint()
              local red3, green3, blue3 = presenceRow.row.dimTex:GetVertexColor()
              local liveVerdict = queryAuraPresence(presenceRow.unit, presenceRow.filter, presenceRow.spellIDs)
              return string.format("%.1f|行=%s 键=%s 绿=%s 判=%s 超时=%s 命中=%s 色=%s/%s/%s 中心=%s,%s 显=%s",
                GetTime() - started3, tostring(presenceRow.rowIndex), tostring(presenceRow.key or "?"),
                tostring(presenceRow.green), tostring(liveVerdict), tostring(presenceRow.staleOut),
                (#hitText > 0 and table.concat(hitText, "/")) or "无",
                string.format("%.2f", red3), string.format("%.2f", green3), string.format("%.2f", blue3),
                string.format("%.1f", center3 or -1), string.format("%.1f", center4 or -1),
                tostring(presenceRow.row:IsVisible()))
            end)
            if not okLine3 then
              line3 = "抛错:" .. tostring(line3)
            end
            if line3 ~= lastLine3 or beat3 >= 10 then
              lastLine3 = line3
              beat3 = 0
              trace[#trace + 1] = line3
            end
          end
        end
      end
      if #trace >= 400 or GetTime() - started3 >= 60 then
        trace[#trace + 1] = "收尾"
        probeFrame:Hide()
        _G.PMS3RUN = nil
        print(string.format("[PMS3] 采完 %d 行 → WowBuddyDevDB.presencePixelTrace，敲 /reload 落盘", #trace))
      end
    end)
    print(string.format("[PMS3] 开始采 %d 条玩家增益行（撞车 %d 条），60 秒后 /reload 落盘",
      #presenceRows, #collisionLines))
  end)
  if not okRun then
    trace[#trace + 1] = "整轮抛错:" .. tostring(errRun)
    print("[PMS3] 抛错 " .. tostring(errRun))
  end
end
SLASH_PERMESBINDTEST1 = "/pmsbindtest"
-- 功能：/pmsbindtest 命令：用「时长文本绑定」在屏幕中间上方摆两个测试框，对比自定义格式化器和默认格式化器哪个能出数字。
-- 入参：arg 命令行参数，可以给一个技能 ID；不填或不是数字时用 34861。
-- 出参：无。
-- 说明：用来验证 12.x 的 C_DurationUtil 时长绑定在当前客户端能不能用；缺 API 或拿不到时长对象时只打印提示就返回，不会建框。左框挂自定义格式化器、右框用默认格式化，哪边有数字一眼可见；测试框按固定全局帧名复用，重跑命令不会越点越多。
SlashCmdList.PERMESBINDTEST = function(arg)
  local spellID = tonumber(arg) or 34861
  -- 功能：取（或建）绑定自检用的测试框，并按水平偏移摆到屏幕中间上方。
  -- 入参：frameName 全局帧名；offsetX 水平偏移。
  -- 出参：测试框 Frame。
  -- 说明：帧名直接当全局名用，重跑命令复用同一个框，不会越点越多。
  local function ensureBindTestFrame(frameName, offsetX)
    local testFrame = _G[frameName]
    if not testFrame then
      testFrame = CreateFrame("Frame", frameName, UIParent)
      testFrame:SetSize(60, 60)
      testFrame:SetPoint("CENTER", UIParent, "CENTER", offsetX, 120)
      local backgroundTexture = testFrame:CreateTexture(nil, "ARTWORK")
      backgroundTexture:SetAllPoints(testFrame)
      backgroundTexture:SetColorTexture(0, 0, 0, 1)
      local labelText = testFrame:CreateFontString(nil, "OVERLAY")
      ensureFont(labelText)
      labelText:SetTextColor(1, 1, 1, 1)
      labelText:SetPoint("CENTER", testFrame, "CENTER", 0, 0)
      testFrame.fs = labelText
    end
    testFrame:Show()
    return testFrame
  end
  if not (C_DurationUtil and C_DurationUtil.CreateDurationTextBinding) then
    print("C_DurationUtil.CreateDurationTextBinding 不存在")
    return
  end
  local duration = C_Spell and (C_Spell.GetSpellCooldownDuration and C_Spell.GetSpellCooldownDuration(spellID, true))
  if not duration and (C_Spell and C_Spell.GetSpellChargeDuration) then
    duration = select(2, pcall(C_Spell.GetSpellChargeDuration, spellID))
  end
  print("durObj=" .. tostring(duration ~= nil), "secret=" .. tostring(issecretvalue and issecretvalue(duration)))
  if not duration then
    print("无时间对象，换个在冷却的技能 ID 再试")
    return
  end
  local leftFrame = ensureBindTestFrame("WowBuddyDevBindTestFrame1", -40)
  local leftBinding = C_DurationUtil.CreateDurationTextBinding()
  if leftBinding.SetUpdateInterval then
    leftBinding:SetUpdateInterval(.05)
  end
  local formatter = getNumberFormatter()
  if formatter and leftBinding.SetFormatter then
    leftBinding:SetFormatter(formatter)
  end
  leftBinding:SetFontString(leftFrame.fs)
  leftBinding:SetDuration(duration)
  if leftBinding.SetEnabled then
    leftBinding:SetEnabled(true)
  end
  local rightFrame = ensureBindTestFrame("WowBuddyDevBindTestFrame2", 40)
  local rightBinding = C_DurationUtil.CreateDurationTextBinding()
  if rightBinding.SetUpdateInterval then
    rightBinding:SetUpdateInterval(.05)
  end
  rightBinding:SetFontString(rightFrame.fs)
  rightBinding:SetDuration(duration)
  if rightBinding.SetEnabled then
    rightBinding:SetEnabled(true)
  end
  print("左框=自定义格式化器，右框=默认格式化，看哪边有数字")
end
-- 加载戳：证明这份 PanelV2.lua 真的被客户端执行到了（写在文件最后一行，中途抛错就不会有它）。
-- 用途：/pmspx3、/pmsrows 这类取证命令「没落地」时，先看这个戳在不在，就能把
--       「磁盘文件没被加载」和「命令根本没投进聊天框」这两种情况分开。
WowBuddyDevDB = WowBuddyDevDB or {}
WowBuddyDevDB.panelStamp = "P3-2026-10-09-1915"
