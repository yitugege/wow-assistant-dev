-- ==========================================================================
-- 文件：0c91f0.lua
-- 来源：P07483180.rar → P07483180/0c91f0.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：0c91f0.lua → PixelBar.lua（按功能重命名）
-- 作用：竖排 V1 色块条：字段编码、曲线、坐标导出
-- ==========================================================================
local ADDON_NAME = ...
local pixelBarFrame = nil
local pixelBarTextures = {}
local fieldFrames = {}
local renderFields = {}
local valuesById = {}
local blockTextures = {}
local fiducialTexture = nil
local debugTexts = {}
local teamAvgLayers = {}
local healerLayers = {}
local ackTextures = {}
local raidHealthLayers = {}
local partyHealthLayers = {}
local partyIndexLayers = {}
local suppressedPixelFieldSet = {
  ttd = true,
  ttf = true,
  spec_id = true,
  addon_version_code = true,
  target_casting = true,
  focus_casting = true,
  player_health_pct = true,
  target_health_pct = true,
  team_avg_health = true,
  mouseover_health_pct = true,
  mouseover_npc_state = true,
  energy_runicpower = true,
  buff_loaded_dice = true,
  party_tank_index = true,
  empower_spell_id = true,
  player_succeeded_generation = true,
  player_succeeded_spell_id = true,
  player_cast_spell_id = true,
  player_cast_observation_code = true,
  target_revision = true,
  need_atonement = true,
  need_spread_renewing_mist = true,
}
-- 功能：判断某个像素字段是不是「被抑制」的 —— 这类字段由专精自己上色，调试面板不再给它们出文本行。
-- 入参：fieldID 字段 ID。
-- 出参：true/false。
-- 说明：判据三条 —— 在白名单集合里、或形如 partyN_health_pct、或形如 raid_health_NN。
local function isFieldSuppressed(a1)
  return suppressedPixelFieldSet[a1] or a1 and a1:match("^party%d+_health_pct$") or a1 and a1:match("^raid_health_%d%d$")
end

-- 只属于部分职业的字段：id -> 该字段真正有值的 specID 列表。
--
-- 为什么需要这张表：契约生成器把整套通用字段（含各职业独有项）无差别复制进每个职业的
-- pixelData，于是术士的调试文字行里也会出现「火焰图腾 / 水之图腾 / 连击点 / 怒气 /
-- 能量 / 潜行 / 形态」这些与术士毫无关系的行，把真正有用的行淹掉。
-- 调试行是按 COMMON_PIXEL_DATA + pixelData + testData 全量渲染的，只靠上面那张
-- 白名单挡不住，所以在这里按「当前职业是不是该字段的主人」再过滤一层。
--
-- ★ 只影响调试文字行的显示；色块照常铺、字段编号照常占位，
--   读取端的 index 与解码顺序都不受影响（改了编号就全盘错位）。
local classOnlyDebugFields = {
  -- 光环/形态
  stealthed = { 1488, 1484 },        -- 潜行：盗贼 / 德鲁伊
  form = { 1484 },                   -- 形态：德鲁伊
  fire_totem = { 1489 },             -- 火焰图腾：萨满
  water_totem = { 1489 },            -- 水之图腾：萨满
  -- 资源条
  energy = { 1488, 1484 },           -- 能量：盗贼 / 德鲁伊
  combo_points = { 1488, 1484 },     -- 连击点：盗贼 / 德鲁伊
  rage = { 1491, 1484 },             -- 怒气：战士 / 德鲁伊
  mana_pct = { 1482, 1484, 1485, 1486, 1487, 1489, 1490 },  -- 法力：除战士/潜行者
  -- 宠物
  -- 实测踩过：战士的调试行里出现「宠物血量」，但战士根本没有宠物。
  pet_valid = { 1485, 1490 },        -- 宠物存活：猎人 / 术士
  pet_on_target = { 1485, 1490 },    -- 宠物攻击当前目标
  pet_health = { 1485, 1490 },       -- 宠物血量
  -- 近战
  auto_attack_active = { 1484, 1485, 1486, 1488, 1491 },
}
-- 功能：判断某字段是不是「别的职业专属、当前职业用不上」。
-- 入参：fieldID 字段 ID。
-- 出参：true = 不属于当前职业（调试行应隐藏）；false = 通用或确属当前职业。
-- 说明：拿不到当前专精 ID 时一律返回 false（宁可多显示，也不要因为读不到专精而把行全藏了）。
local function isForeignClassField(fieldID)
  local owners = classOnlyDebugFields[fieldID]
  if not owners then
    return false
  end
  local currentSpecID = WowBuddyDev.DB and tonumber(WowBuddyDev.DB.currentSpecID)
  if not currentSpecID then
    return false
  end
  for _, ownerSpecID in ipairs(owners) do
    if ownerSpecID == currentSpecID then
      return false
    end
  end
  return true
end
-- 技能型调试字段的前缀：id 里带技能 ID 的都是「某个技能」的行。
local specScopedFieldPrefixes = { "^known_(%d+)", "^range_(%d+)", "^cd_(%d+)", "^charge_(%d+)", "^ready_(%d+)" }
-- 功能：判断某字段是不是「当前专精用不到」的技能字段。
-- 入参：field 渲染字段表（含 id，可能含 spellID）。
-- 出参：true = 该技能不属于当前专精（调试行应隐藏）；false = 无关字段或确属当前专精。
-- 说明：与按键页同一口径，判定统一走 Core.lua 的 IsSpellOfCurrentSpec（天赋树归属优先，
--       训练师技能看学没学会，读不到就放行），避免两处各判一套导致界面自相矛盾。
--       ★ 与 isForeignClassField 一样，**只影响调试文字行**：色块照常铺、字段编号照常
--         占位，读取端的 index 与解码顺序不受影响（改了编号就全盘错位）。
--       只认技能型 id（known_/range_/cd_/charge_ 前缀或契约自带的 spellID），
--       血量、距离、GCD、施法状态这些跟专精无关的字段照常显示。
local function isForeignSpecField(field)
  if type(field) ~= "table" or type(WowBuddyDev.IsSpellOfCurrentSpec) ~= "function" then
    return false
  end
  local spellID = tonumber(field.spellID)
  if not spellID and type(field.id) == "string" then
    for _, prefix in ipairs(specScopedFieldPrefixes) do
      spellID = tonumber(field.id:match(prefix))
      if spellID then
        break
      end
    end
  end
  if not spellID then
    return false
  end
  return not WowBuddyDev.IsSpellOfCurrentSpec(spellID)
end
-- 功能：整体重建像素条：按字段表把每个色块铺好，给特殊字段（治疗总开关、鼠标指向状态、团队血量、小队序号、团队焦点回执、队伍平均血量）建各自的叠加层，再重建调试文字行和渲染字段表。
-- 入参：无。
-- 出参：无。
-- 说明：先把旧纹理和旧叠加层全部隐藏或清空再重建，切专精或换字段表后必须调一次，否则会残留上一套字段的图层。色块固定在屏幕左上角、每格 4×4，坐标由外部读取工具按固定规则推算，所以这里不能随便改位置。P07483180._pixelBarPositions 也在这一步按当前屏幕尺寸重新归一化算好；帧本身的显隐跟随「整体隐藏」开关。
function WowBuddyDev.RebuildPixelBars()
  if pixelBarFrame then
    pixelBarFrame:Hide()
  end
  if WowBuddyDev.debugFrame then
    WowBuddyDev.debugFrame:Hide()
  end
  if testDebugFrame then
    testDebugFrame:Hide()
    testDebugFrame:SetParent(nil)
  end
  wipe(pixelBarTextures)
  wipe(fieldFrames)
  local allFields = {}
  for index, v in ipairs(WowBuddyDev.COMMON_PIXEL_DATA) do
    table.insert(allFields, v)
  end
  for index2, v2 in ipairs(WowBuddyDev.pixelData) do
    table.insert(allFields, v2)
  end
  local isRaidFocusEnabled = WowBuddyDev.classData and WowBuddyDev.classData.raidFocusEnabled == true
  local raidFocusAckPixelID = "focus_is_player"
  if isRaidFocusEnabled and WowBuddyDev.classData.raidFocusAckPixel == "party_tank_index" then
    raidFocusAckPixelID = "party_tank_index"
  end
  if not pixelBarFrame then
    pixelBarFrame = CreateFrame("Frame", nil, UIParent)
  end
  WowBuddyDev.pixelContainer = pixelBarFrame
  pixelBarFrame:ClearAllPoints()
  pixelBarFrame:SetSize(8, math.max(8 + #allFields * 4, 132))
  pixelBarFrame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)
  pixelBarFrame:SetFrameStrata("TOOLTIP")
  pixelBarFrame:SetFrameLevel(9999)
  local fieldCount = #allFields
  local screenWidth, screenHeight = GetScreenWidth(), GetScreenHeight()
  WowBuddyDev._pixelBarPositions = {}
  WowBuddyDev.teamAvgLayers = nil
  WowBuddyDev.teamAvgIndex = nil
  WowBuddyDev.healerMasterHealthLayers = nil
  WowBuddyDev.healingNpcFocusMatchLayer = nil
  WowBuddyDev.raidFocusHealthLayers = nil
  WowBuddyDev.raidFocusAckLayers = nil
  WowBuddyDev.raidFocusPartyUnavailableLayers = nil
  WowBuddyDev.raidFocusAckFrameSequence = nil
  WowBuddyDev.raidFocusAckCarrier = nil
  for index3, v3 in ipairs(blockTextures) do
    v3:Hide()
  end
  for index4, v4 in ipairs(teamAvgLayers) do
    v4:Hide()
    v4:SetColorTexture(0, 0, 0, 1)
  end
  for index5, v5 in ipairs(healerLayers) do
    v5:Hide()
    v5:SetAlpha(0)
  end
  for index6, v6 in ipairs(ackTextures) do
    v6:Hide()
    v6:SetAlpha(0)
  end
  for index7, v7 in ipairs(raidHealthLayers) do
    v7:Hide()
    v7:SetColorTexture(0, 0, 0, 1)
  end
  for index8, v8 in ipairs(partyHealthLayers) do
    v8:Hide()
    v8:SetColorTexture(0, 0, 0, 1)
    v8:SetAlpha(0)
  end
  for index9, v9 in ipairs(partyIndexLayers) do
    v9:Hide()
    v9:SetColorTexture(0, 0, 0, 1)
    v9:SetAlpha(0)
  end
  for i = 1, fieldCount, 1 do
    local blockTexture = blockTextures[i]
    if not blockTexture then
      blockTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
      blockTextures[i] = blockTexture
    end
    blockTexture:ClearAllPoints()
    blockTexture:SetSize(4, 4)
    blockTexture:SetDrawLayer("OVERLAY", 0)
    blockTexture:SetBlendMode("BLEND")
    blockTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 0, -(i - 1) * 4)
    local raidHealthIndex = tonumber(allFields[i].id:match("^raid_health_(%d%d)$"))
    if allFields[i].id == "master_switch" and WowBuddyDev.IsHealingSpec() then
      blockTexture:SetColorTexture(1, 0, 0, 1)
      for i2 = 1, 41, 1 do
        local healerTexture = healerLayers[i2]
        if not healerTexture then
          healerTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
          healerLayers[i2] = healerTexture
        end
        healerTexture:ClearAllPoints()
        healerTexture:SetAllPoints(blockTexture)
        healerTexture:SetDrawLayer("OVERLAY", 1)
        healerTexture:SetBlendMode("BLEND")
        healerTexture:SetColorTexture(0, 1, 0, 1)
        healerTexture:SetAlpha(0)
        healerTexture:Show()
      end
      WowBuddyDev.healerMasterHealthLayers = healerLayers
    elseif allFields[i].id == "mouseover_npc_state" then
      blockTexture:SetColorTexture(0, 0, 0, 1)
      local ackTexture = ackTextures[1]
      if not ackTexture then
        ackTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
        ackTextures[1] = ackTexture
      end
      ackTexture:ClearAllPoints()
      ackTexture:SetSize(4, 4)
      ackTexture:SetDrawLayer("OVERLAY", 1)
      ackTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 0, -(i - 1) * 4)
      ackTexture:SetBlendMode("ADD")
      ackTexture:SetColorTexture(.015686274509804, 0, 0, 1)
      ackTexture:SetAlpha(0)
      ackTexture:Show()
      WowBuddyDev.healingNpcFocusMatchLayer = ackTexture
    elseif raidHealthIndex then
      blockTexture:SetColorTexture(0, 0, 0, 1)
      if not WowBuddyDev.raidFocusHealthLayers then
        WowBuddyDev.raidFocusHealthLayers = {}
      end
      local raidHealthTextures = {}
      for i3 = 1, 3, 1 do
        local layerIndex = (raidHealthIndex - 1) * 3 + i3
        local raidHealthTexture = raidHealthLayers[layerIndex]
        if not raidHealthTexture then
          raidHealthTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
          raidHealthLayers[layerIndex] = raidHealthTexture
        end
        raidHealthTexture:ClearAllPoints()
        raidHealthTexture:SetSize(4, 4)
        raidHealthTexture:SetDrawLayer("OVERLAY", 1)
        raidHealthTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 0, -(i - 1) * 4)
        raidHealthTexture:SetBlendMode("ADD")
        raidHealthTexture:SetColorTexture(0, 0, 0, 1)
        raidHealthTexture:Show()
        raidHealthTextures[i3] = raidHealthTexture
      end
      WowBuddyDev.raidFocusHealthLayers[raidHealthIndex] = raidHealthTextures
    elseif isRaidFocusEnabled and tonumber(allFields[i].id:match("^party(%d)_health_pct$")) then
      local partyMemberIndex = tonumber(allFields[i].id:match("^party(%d)_health_pct$"))
      blockTexture:SetColorTexture(.2, .2, .2, 1)
      local partyIndexTexture = partyIndexLayers[partyMemberIndex]
      if not partyIndexTexture then
        partyIndexTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
        partyIndexLayers[partyMemberIndex] = partyIndexTexture
      end
      partyIndexTexture:ClearAllPoints()
      partyIndexTexture:SetSize(4, 4)
      partyIndexTexture:SetDrawLayer("OVERLAY", 1)
      partyIndexTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 0, -(i - 1) * 4)
      partyIndexTexture:SetBlendMode("ADD")
      partyIndexTexture:SetColorTexture(0, 0, .50196078431373, 1)
      partyIndexTexture:SetAlpha(0)
      partyIndexTexture:Show()
      if not WowBuddyDev.raidFocusPartyUnavailableLayers then
        WowBuddyDev.raidFocusPartyUnavailableLayers = {}
      end
      WowBuddyDev.raidFocusPartyUnavailableLayers[partyMemberIndex] = partyIndexTexture
    elseif allFields[i].id == raidFocusAckPixelID and isRaidFocusEnabled then
      blockTexture:SetColorTexture(0, 0, 0, 1)
      local raidFocusAckTexturePool = { raid = {}, party = {} }
      -- 功能：从共享纹理池里取（或新建）一张 4×4 的小队血量纹理，摆到当前像素格上并染成指定颜色。
      -- 入参：textureIndex 纹理池下标（1~30 是团队序号，31~35 是小队序号，36 是自己）；r/g/b 颜色的红、绿、蓝分量（0~1）。
      -- 出参：取到的纹理对象。
      -- 说明：纹理按池下标复用而不是每次新建，所以反复重建不会让纹理数一直涨。摆位用的是外层循环当前的行号，只能在本函数被调用的那个位置用；建出来先设成全透明，由渲染逻辑再控制显隐。
      local function acquirePartyHealthTexture(a12, a2, a3, a4)
        local partyHealthTexture = partyHealthLayers[a12]
        if not partyHealthTexture then
          partyHealthTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
          partyHealthLayers[a12] = partyHealthTexture
        end
        partyHealthTexture:ClearAllPoints()
        partyHealthTexture:SetSize(4, 4)
        partyHealthTexture:SetDrawLayer("OVERLAY", 1)
        partyHealthTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 0, -(i - 1) * 4)
        partyHealthTexture:SetBlendMode("ADD")
        partyHealthTexture:SetColorTexture(a2, a3, a4, 1)
        partyHealthTexture:SetAlpha(0)
        partyHealthTexture:Show()
        return partyHealthTexture
      end
      for i4 = 1, 30, 1 do
        raidFocusAckTexturePool.raid[i4] = acquirePartyHealthTexture(i4, i4 / 255, 0, 0)
      end
      for i5 = 1, 5, 1 do
        raidFocusAckTexturePool.party[i5] = acquirePartyHealthTexture(30 + i5, 0, i5 / 255, 0)
      end
      if raidFocusAckPixelID == "focus_is_player" then
        raidFocusAckTexturePool.self = acquirePartyHealthTexture(36, 0, 0, .50196078431373)
      end
      WowBuddyDev.raidFocusAckLayers = raidFocusAckTexturePool
    elseif allFields[i].id == "team_avg_health" then
      blockTexture:SetColorTexture(0, 0, 0, 1)
      WowBuddyDev.teamAvgIndex = i
      WowBuddyDev.teamAvgLayers = {}
      for i6 = 1, 40, 1 do
        local teamAvgTexture = teamAvgLayers[i6]
        if not teamAvgTexture then
          teamAvgTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
          teamAvgLayers[i6] = teamAvgTexture
        end
        teamAvgTexture:ClearAllPoints()
        teamAvgTexture:SetSize(4, 4)
        teamAvgTexture:SetDrawLayer("OVERLAY", 1)
        teamAvgTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 0, -(i - 1) * 4)
        teamAvgTexture:SetBlendMode("ADD")
        teamAvgTexture:SetColorTexture(0, 0, 0, 1)
        teamAvgTexture:Show()
        WowBuddyDev.teamAvgLayers[i6] = teamAvgTexture
      end
    else
      blockTexture:SetColorTexture(.2, .2, .2, 1)
    end
    blockTexture:Show()
    pixelBarTextures[i] = blockTexture
    local n = 0
    local blockTop = screenHeight - (i - 1) * 4
    local normX = (n + 2) / screenWidth
    local normY = (screenHeight - (blockTop - 2)) / screenHeight
    WowBuddyDev._pixelBarPositions[i] = { cx = normX, cy = normY }
  end
  if not fiducialTexture then
    fiducialTexture = pixelBarFrame:CreateTexture(nil, "OVERLAY")
  end
  fiducialTexture:ClearAllPoints()
  fiducialTexture:SetSize(4, 4)
  fiducialTexture:SetDrawLayer("OVERLAY", 0)
  fiducialTexture:SetBlendMode("BLEND")
  fiducialTexture:SetPoint("TOPLEFT", pixelBarFrame, "TOPLEFT", 4, -128)
  fiducialTexture:SetColorTexture(1, 0, 1, 1)
  fiducialTexture:Show()
  pixelBarFrame:SetShown(not (WowBuddyDev.DB and WowBuddyDev.DB.allOverlaysHidden))
  local n2 = 0
  for index10, v10 in ipairs(allFields) do
    if not v10.id:match("^placeholder") and not isFieldSuppressed(v10.id) then
      n2 = n2 + 1
    end
  end
  for index11, v11 in ipairs(WowBuddyDev.testData) do
    n2 = n2 + 1
  end
  if not WowBuddyDev.debugFrame then
    WowBuddyDev.debugFrame = CreateFrame("Frame", nil, UIParent)
  end
  WowBuddyDev.debugFrame:ClearAllPoints()
  WowBuddyDev.debugFrame:SetSize(160, math.max(60, n2 * 18 + 10))
  WowBuddyDev.debugFrame:SetPoint("LEFT", UIParent, "LEFT", 20, 0)
  WowBuddyDev.debugFrame:Hide()
  for index12, v12 in ipairs(debugTexts) do
    v12:Hide()
  end
  local debugRowCount = #allFields + #WowBuddyDev.testData
  for i7 = 1, debugRowCount, 1 do
    local debugText = debugTexts[i7]
    if not debugText then
      debugText = WowBuddyDev.debugFrame:CreateFontString(nil, "OVERLAY")
      debugTexts[i7] = debugText
    end
    debugText:ClearAllPoints()
    debugText:SetFont(WowBuddyDev.fontFile, 11, "")
    debugText:SetPoint("TOPLEFT", WowBuddyDev.debugFrame, "TOPLEFT", 0, -(i7 - 1) * 18)
    debugText:SetJustifyH("LEFT")
    debugText:SetText("--")
    debugText._vf_lastText = nil
    debugText._vf_lastPointY = nil
    debugText:Show()
    fieldFrames[i7] = debugText
  end
  wipe(renderFields)
  for index13, v13 in ipairs(WowBuddyDev.COMMON_PIXEL_DATA) do
    table.insert(renderFields, v13)
  end
  for index14, v14 in ipairs(WowBuddyDev.pixelData) do
    table.insert(renderFields, v14)
  end
  for index15, v15 in ipairs(WowBuddyDev.testData) do
    table.insert(renderFields, v15)
  end
end
local colorRed = CreateColor(1, 0, 0)
local colorCyan = CreateColor(0, 1, 1)
local elapsedCurve = nil
-- 功能：懒建「已过时长」用的阶梯色曲线，并返回这条曲线能不能用。
-- 入参：无。
-- 出参：true 曲线可用；false 当前客户端没有 C_CurveUtil 或缺少曲线类型枚举。
-- 说明：曲线是 0~100 个阶梯点、蓝分量随进度递增，只建一次之后一直复用。旧客户端没有 C_CurveUtil，所以调用方必须先看返回值再拿曲线去用。
local function ensureElapsedCurve()
  if elapsedCurve then
    return true
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and (Enum and Enum.LuaCurveType))) then
    return false
  end
  elapsedCurve = C_CurveUtil.CreateColorCurve()
  elapsedCurve:SetType(Enum.LuaCurveType.Step)
  for i8 = 0, 100, 1 do
    elapsedCurve:AddPoint(i8 / 100, CreateColor(0, 1, i8 / 255, 1))
  end
  return true
end
-- 功能：取某个单位「读条/引导已进行的百分比」，交给颜色曲线算出颜色；取不到就返回备用色。
-- 入参：unit 单位令牌；durationAPI 取值函数（UnitCastingDuration / UnitChannelDuration）。
-- 出参：颜色对象；任何一步失败都返回 colorCyan。
-- 说明（为什么这么绕）：12.x 里读条进度是「秘密值」，插件自己不能比较不能算，只能交给客户端曲线去求值。
local function getElapsedColor(a13, a22)
  if not a22 or not ensureElapsedCurve() then
    return colorCyan
  end
  local ok, color = pcall(function()
    local elapsedDuration = a22(a13)
    return elapsedDuration:EvaluateElapsedPercent(elapsedCurve)
  end)
  if ok and color then
    return color
  end
  return colorCyan
end
-- 功能：把单位读条/引导画成颜色：可打断为绿（蓝色通道为进度），其余为红。
-- 入参：unit 单位令牌（target / focus / 名字板单位…）。
-- 出参：颜色对象；没在施法返回 colorRed。
-- 说明：先查 UnitCastingInfo（读条），没有再查 UnitChannelInfo（引导）。
local function getUnitCastingColor(a14)
  if not UnitExists(a14) then
    return colorRed
  end
  local castName, _, _, _, _, _, _, castUninterruptible = UnitCastingInfo(a14)
  local durationAPI = UnitCastingDuration
  if not castName then
    local channelName, _, _, _, _, _, channelUninterruptible = UnitChannelInfo(a14)
    castName = channelName
    castUninterruptible = channelUninterruptible
    durationAPI = UnitChannelDuration
  end
  if not castName then return colorRed end
  -- Forever has no castBarID; the original spell name already identifies a cast.
  local ok, color = pcall(function()
    local elapsedColor = getElapsedColor(a14, durationAPI)
    if C_CurveUtil and C_CurveUtil.EvaluateColorFromBoolean then
      return C_CurveUtil.EvaluateColorFromBoolean(castUninterruptible, colorRed, elapsedColor)
    end
    if castUninterruptible == false then return elapsedColor end
    return colorRed
  end)
  return ok and color or colorRed
end
-- 功能：可攻击 + 活着 + 在施法的单位才给颜色，其余一律返回 colorRed。
-- 入参：unit 单位令牌。
-- 出参：颜色对象。
-- 说明：对外导出为 P07483180.GetHostileUnitCastingColor，供专精文件判断「目标在读条」。
local function getHostileUnitCastingColor(a15)
  if not a15 or not UnitExists(a15) or not UnitCanAttack("player", a15) or UnitIsDeadOrGhost(a15) then
    return colorRed
  end
  return getUnitCastingColor(a15)
end
WowBuddyDev.GetHostileUnitCastingColor = getHostileUnitCastingColor
-- 功能：目标在读条时的颜色。
-- 入参：无。
-- 出参：颜色对象。
local function getTargetCastingColor()
  return getUnitCastingColor("target")
end
-- 功能：焦点在读条时的颜色。
-- 入参：无。
-- 出参：颜色对象。
local function getFocusCastingColor()
  return getUnitCastingColor("focus")
end
-- 功能：算玩家到某单位的距离（码）。
-- 入参：unit 单位令牌。
-- 出参：距离数字；单位不存在或算不出来返回 nil。
-- 说明：先用 UnitDistanceSquared 开根；被「秘密值」挡住时退回 LibRangeCheck 估一个中值。
local function getUnitDistance(a16)
  if not a16 or not UnitExists(a16) then
    return nil
  end
  local distanceSquared, distanceFlag = UnitDistanceSquared(a16)
  distanceSquared = WowBuddyDev.SafeNumber(distanceSquared)
  if distanceFlag and distanceSquared > 0 then
    return math.sqrt(distanceSquared)
  end
  if WowBuddyDev.LibRangeCheck then
    -- 无限客户端会把 UnitGUID 之类的字符串变成 secret，LibRangeCheck 内部拿它当
    -- table 键 → "cannot be indexed with secret keys" 每帧抛错，把整帧像素渲染打断
    -- （症状：进本后像素条冻结、不放技能）。这里包 pcall，让它降级为「距离未知」
    -- 而不是崩掉整帧。
    local rangeOK, rangeMin, rangeMax = pcall(WowBuddyDev.LibRangeCheck.GetRange, WowBuddyDev.LibRangeCheck, a16, true)
    if not rangeOK then
      return nil
    end
    rangeMin = WowBuddyDev.SafeNumber(rangeMin)
    rangeMax = WowBuddyDev.SafeNumber(rangeMax)
    if rangeMin > 0 and rangeMax > 0 then
      return (rangeMin + rangeMax) / 2
    elseif rangeMax > 0 then
      return rangeMax
    elseif rangeMin > 0 then
      return rangeMin
    end
  end
  return nil
end
-- 功能：当前是不是团队副本。
-- 入参：无。
-- 出参：true/false。
local function isInRaidInstance()
  local inInstance, instanceType = IsInInstance()
  return inInstance == true and instanceType == "raid"
end
local specialEncounterActive = false
local encounterEventFrame = CreateFrame("Frame")
encounterEventFrame:RegisterEvent("ENCOUNTER_START")
encounterEventFrame:RegisterEvent("ENCOUNTER_END")
encounterEventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
encounterEventFrame:SetScript("OnEvent", function(self, event, a32)
  specialEncounterActive = false
  if event ~= "ENCOUNTER_START" then
    return
  end
  local encounterCheckOk, encounterIsTarget = pcall(function()
    if type(issecretvalue) ~= "function" or issecretvalue(a32) then
      return false
    end
    return type(a32) == "number" and a32 == 3200
  end)
  specialEncounterActive = encounterCheckOk and encounterIsTarget == true
end)
-- 功能：判断当前场景要不要按「全团」口径扫描（团队副本 / 特定首领战 / 小队副本）。
-- 入参：无。
-- 出参：true/false。
local function needsAllUnitScan()
  if isInRaidInstance() then
    return true
  end
  if not specialEncounterActive then
    return false
  end
  local inInstance2, instanceType2 = IsInInstance()
  return inInstance2 == true and instanceType2 == "party"
end
-- 功能：按名字板统计附近的敌对单位数量与距离，用于「8 码内敌人」这类字段。
-- 入参：距离上限（码）。
-- 出参：数量（上限 100）。
local function countNearbyEnemies(a17)
  local n3 = 0
  local n4 = 0
  local needsAllUnits = needsAllUnitScan()
  local namePlates = C_NamePlate and (C_NamePlate.GetNamePlates and C_NamePlate.GetNamePlates()) or {}
  for index16, v16 in ipairs(namePlates) do
    local namePlateUnit = v16.namePlateUnitToken or v16.unitToken or v16.unit
    local namePlateOk, namePlateHostileAlive, namePlateCounted = pcall(function()
      if not namePlateUnit or not UnitExists(namePlateUnit) or not UnitCanAttack("player", namePlateUnit) or UnitIsDeadOrGhost(namePlateUnit) then
        return false, false
      end
      return true, needsAllUnits or (UnitAffectingCombat(namePlateUnit) and true or false)
    end)
    if namePlateOk and namePlateHostileAlive then
      if namePlateCounted then
        n4 = math.min(100, n4 + 1)
      end
      if n3 < 10 then
        local distanceOk, withinRange = pcall(function()
          local unitDistance = getUnitDistance(namePlateUnit)
          if unitDistance then
            return unitDistance <= a17
          end
          if WowBuddyDev.LibRangeCheck then
            local v83, rangeUpper = WowBuddyDev.LibRangeCheck:GetRange(namePlateUnit, true)
            rangeUpper = WowBuddyDev.SafeNumber(rangeUpper)
            return rangeUpper > 0 and rangeUpper <= a17
          end
          return false
        end)
        if distanceOk and withinRange then
          n3 = n3 + 1
        end
      end
    end
  end
  return n3, n4
end
local friendlyCreatureIDs = { ["243208"] = true, ["225982"] = true }
local friendlyScanLimit = 5
-- 功能：把统计出来的敌人数做一次友善修正：目标是友善生物时直接压到上限值。
-- 入参：count 原始计数。
-- 出参：修正后的计数。
-- 说明：有些首领战会召唤友方 NPC（243208 / 225982 这种），按姓名板全量统计会把它们算成敌人；命中这两个 ID 就直接返回 5，等于「当 5 个敌人」。取不到 target 或 GUID 拆不开时原样返回。
local function clampFriendlyCount(a18)
  local friendlyCheckOk, friendlyAdjusted = pcall(function()
    if type(UnitGUID) ~= "function" or type(strsplit) ~= "function" then
      return a18
    end
    local targetGUID = UnitGUID("target")
    if not targetGUID then
      return a18
    end
    local targetGUIDParts = { strsplit("-", targetGUID) }
    if targetGUIDParts[1] == "Creature" and friendlyCreatureIDs[targetGUIDParts[6]] then
      return friendlyScanLimit
    end
    return a18
  end)
  return friendlyCheckOk and friendlyAdjusted or a18
end
-- 功能：对外暴露的「8 码内敌人数」入口：算一遍再过一次友善修正。
-- 入参：range 距离上限（码）。
-- 出参：修正后的敌人数。
-- 说明：导出为 P07483180.GetNearbyEnemiesCount。
local function getAndApplyNearbyEnemyCount(a19)
  local nearbyEnemyCount = countNearbyEnemies(a19)
  return nearbyEnemyCount
end
WowBuddyDev.GetNearbyEnemiesCount = getAndApplyNearbyEnemyCount
WowBuddyDev.ScanVisibleHostileEnemies = countNearbyEnemies
SLASH_MKLACTIVE1 = "/mklactive"
-- 功能：/mklactive 命令：统计当前姓名板上的敌对存活数和正在战斗的敌人数，并打印一行汇总。
-- 入参：无。
-- 出参：无。
-- 说明：每个姓名板都单独套 pcall 探测——部分单位信息在当前客户端里是受限的，读失败只累加「状态受限」计数，不影响其余姓名板的统计。统计口径由 needsAllUnitScan() 决定：需要按整团识别时用「敌对存活数」，否则用「战斗中敌人数」，最后再夹到合法范围。
SlashCmdList.MKLACTIVE = function()
  local slashNamePlates = C_NamePlate and (C_NamePlate.GetNamePlates and C_NamePlate.GetNamePlates()) or {}
  local hostileAliveCount = 0
  local inCombatCount = 0
  local probeRestrictedCount = 0
  local needsRaidFrames = needsAllUnitScan()
  for index17, v17 in ipairs(slashNamePlates) do
    local slashNamePlateUnit = v17.namePlateUnitToken or v17.unitToken or v17.unit
    local slashProbeOk, slashProbeState = pcall(function()
      if not slashNamePlateUnit or not UnitExists(slashNamePlateUnit) or not UnitCanAttack("player", slashNamePlateUnit) or UnitIsDeadOrGhost(slashNamePlateUnit) then
        return "skip"
      end
      return UnitAffectingCombat(slashNamePlateUnit) and "active" or "idle"
    end)
    if slashProbeOk then
      if slashProbeState ~= "skip" then
        hostileAliveCount = hostileAliveCount + 1
      end
      if slashProbeState == "active" then
        inCombatCount = inCombatCount + 1
      end
    else
      probeRestrictedCount = probeRestrictedCount + 1
    end
  end
  local effectiveCombatCount = needsRaidFrames and hostileAliveCount or inCombatCount
  effectiveCombatCount = clampFriendlyCount(effectiveCombatCount)
  print(string.format("|cff00ff88[WowBuddyDev 敌人统计]|r 战斗中=%d 原始战斗中=%d 敌对存活=%d 空闲=%d 姓名板=%d 状态受限=%d", effectiveCombatCount, inCombatCount, hostileAliveCount, hostileAliveCount - inCombatCount, #slashNamePlates, probeRestrictedCount))
end
local targetProbePrefix = "|cff00ff88[WowBuddyDev 目标探测]|r"
local detectReport = {
  elite = "精英",
  rare = "稀有",
  rareelite = "稀有精英",
  worldboss = "世界首领",
  normal = "普通",
  trivial = "低劣",
  minus = "杂鱼",
}
-- 功能：把一个探测到的值转成给人看的中文文本（调试命令输出用）。
-- 入参：value 任意值。
-- 出参：字符串 —— nil / 受限 / 是 / 否 / tostring 结果。
-- 说明：12.x 的「秘密值」不能读也不能比；issecretvalue 判真时统一显示「受限」，免得把受限值当正常值打进日志。
local function classifyProbeValue(a110)
  if a110 == nil then
    return "nil"
  end
  local secretCheckOk, isSecret = pcall(function()
    return issecretvalue and issecretvalue(a110) or false
  end)
  if not secretCheckOk or isSecret then
    return "受限"
  end
  if a110 == true then
    return "是"
  end
  if a110 == false then
    return "否"
  end
  local tostringOk, valueText = pcall(function()
    return tostring(a110) .. ""
  end)
  return tostringOk and valueText or "受限"
end
-- 功能：pcall 调一个 API 并把结果转成文本，供 /mkltarget 逐项打印。
-- 入参：fn 目标函数；... 透传实参。
-- 出参：字符串；不是函数给「不可用」，调用失败给「调用失败」。
local function safeProbeCall(a111, ...)
  if type(a111) ~= "function" then
    return "不可用"
  end
  local callOk, callResult = pcall(a111, ...)
  if not callOk then
    return "调用失败"
  end
  return classifyProbeValue(callResult)
end
-- 功能：拆开 target 的 GUID，给出「类型 / NPC_ID / 刷新ID」三段文本。
-- 入参：无。
-- 出参：四段字符串（GUID 全文 + 三段拆分）。
-- 说明：GUID 形如 Creature-0-3673-2522-243208-0000123456-0，第 1/6/7 段分别是类型、NPC ID、刷新 ID；拆不出来时三段都给「解析失败」。
local function probeTargetIdentity()
  if type(UnitGUID) ~= "function" then
    return "不可用", "不可用", "不可用", "不可用"
  end
  local guidOk, focusUnit = pcall(UnitGUID, "target")
  if not guidOk then
    return "调用失败", "调用失败", "调用失败", "调用失败"
  end
  local focusGUID = classifyProbeValue(focusUnit)
  local splitOk, guidType, guidNpcID, guidSpawnID = pcall(function()
    local focusGUIDParts = { strsplit("-", focusUnit) }
    return focusGUIDParts[1], focusGUIDParts[6], focusGUIDParts[7]
  end)
  if not splitOk then
    return focusGUID, "解析失败", "解析失败", "解析失败"
  end
  return focusGUID, classifyProbeValue(guidType), classifyProbeValue(guidNpcID), classifyProbeValue(guidSpawnID)
end
-- 功能：找出与 target 指向同一个单位的所有姓名板，拼成一行令牌列表。
-- 入参：无。
-- 出参：两段字符串 —— 令牌列表（没有就给「未找到」）、姓名板总数。
-- 说明：用来判断目标在屏幕上被几个姓名板画出来（多姓名板会让读屏类读取端重复计数）。
local function listTargetNameplates()
  if not (C_NamePlate and C_NamePlate.GetNamePlates) then
    return "不可用", "不可用"
  end
  local platesOk, plateList = pcall(C_NamePlate.GetNamePlates)
  if not platesOk or type(plateList) ~= "table" then
    return "调用失败", "调用失败"
  end
  local targetNameplateUnits = {}
  for index18, v18 in ipairs(plateList) do
    local targetNamePlateUnit = v18.namePlateUnitToken or v18.unitToken or v18.unit
    local isTargetOk, isTargetPlate = pcall(function()
      return targetNamePlateUnit and (UnitIsUnit(targetNamePlateUnit, "target") and true) or false
    end)
    if isTargetOk and isTargetPlate then
      table.insert(targetNameplateUnits, targetNamePlateUnit)
    end
  end
  return #targetNameplateUnits > 0 and table.concat(targetNameplateUnits, ",") or "未找到", tostring(#plateList)
end
SLASH_MKLTARGET1 = "/mkltarget"
-- 功能：/mkltarget 命令：把当前目标的身份、类型、分级、战斗状态和附近敌人数逐条打印出来。
-- 入参：无。
-- 出参：无。
-- 说明：所有取值都走 safeProbeCall 或 pcall，某个接口读不到时只显示失败占位，不会中断后面的输出。没目标就直接返回。最后会顺带调一次 /mklactive 的统计，方便和目标信息对着看。
SlashCmdList.MKLTARGET = function()
  local existsOk, targetExists = pcall(function()
    return UnitExists("target") and true or false
  end)
  if not existsOk or not targetExists then
    print(targetProbePrefix .. " 错误=无目标")
    return
  end
  local guideText, guideTypeText, npcIDText, spawnIDText = probeTargetIdentity()
  local plateNameText, plateCountText = listTargetNameplates()
  local enemyProbeOk, enemyProbeValue = pcall(getAndApplyNearbyEnemyCount, 8)
  print(string.format("%s 名字=%s 全名=%s 单元名=%s", targetProbePrefix, safeProbeCall(UnitName, "target"), safeProbeCall(UnitFullName, "target"), safeProbeCall(GetUnitName, "target", true)))
  print(string.format("%s guid=%s 类型=%s NPC_ID=%s 刷新ID=%s", targetProbePrefix, guideText, guideTypeText, npcIDText, spawnIDText))
  print(string.format("%s 分级=%s 生物类型=%s 种族=%s 科=%s 等级=%s", targetProbePrefix, (function()
    local targetClassification = safeProbeCall(UnitClassification, "target")
    return detectReport[targetClassification] or targetClassification
  end)(), safeProbeCall(UnitCreatureType, "target"), safeProbeCall(UnitRace, "target"), safeProbeCall(UnitCreatureFamily, "target"), safeProbeCall(UnitLevel, "target")))
  print(string.format("%s 存在=%s 可攻击=%s 死亡=%s 战斗中=%s 归属被拒=%s 仇恨=%s", targetProbePrefix, safeProbeCall(UnitExists, "target"), safeProbeCall(UnitCanAttack, "player", "target"), safeProbeCall(UnitIsDeadOrGhost, "target"), safeProbeCall(UnitAffectingCombat, "target"), safeProbeCall(UnitIsTapDenied, "target"), safeProbeCall(UnitThreatSituation, "player", "target")))
  print(string.format("%s 姓名板=%s 可见姓名板=%s 8码敌人=%s", targetProbePrefix, plateNameText, plateCountText, enemyProbeOk and classifyProbeValue(enemyProbeValue) or "调用失败"))
  if SlashCmdList and type(SlashCmdList.MKLACTIVE) == "function" then
    SlashCmdList.MKLACTIVE()
  end
end
-- 功能：判断某个技能玩家（或宠物）会不会。
-- 入参：spellID 技能 ID。
-- 出参：true/false。
-- 说明：宠物技能要分两种情况——宠物在场就查宠物技能书（宠物死亡或不存在则不认），宠物不在场就改查该技能对应的「玩家版本」替代技能（classData.petSpellPlayerWrappers），因为宠物技能在玩家的技能书里查不到。法术书接口按版本新老依次兜底，都取不到时退回旧全局接口。
function WowBuddyDev.IsSpellKnown(a112)
  local isPetSpell = WowBuddyDev.IsPetSpell and WowBuddyDev.IsPetSpell(a112)
  if isPetSpell then
    if UnitExists("pet") then
      if UnitIsDeadOrGhost("pet") then
        return false
      end
      if C_SpellBook and C_SpellBook.IsSpellKnownOrInSpellBook then
        if not (Enum and (Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Pet)) then
          return false
        end
        return C_SpellBook.IsSpellKnownOrInSpellBook(a112, Enum.SpellBookSpellBank.Pet, true)
      end
      return IsSpellKnown(a112, true)
    end
    local petSpellPlayerWrappers = WowBuddyDev.classData and (WowBuddyDev.classData.petSpellPlayerWrappers and WowBuddyDev.classData.petSpellPlayerWrappers[a112])
    if not petSpellPlayerWrappers then
      return false
    end
    if C_SpellBook and C_SpellBook.IsSpellKnownOrInSpellBook then
      local playerSpellBank = Enum and (Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player) or "player"
      for index19, v19 in ipairs(petSpellPlayerWrappers) do
        if C_SpellBook.IsSpellKnownOrInSpellBook(v19, playerSpellBank, true) then
          return true
        end
      end
      return false
    end
    for index20, v20 in ipairs(petSpellPlayerWrappers) do
      if IsSpellKnown(v20) then
        return true
      end
    end
    return false
  end
  if C_SpellBook and C_SpellBook.IsSpellKnown then
    return C_SpellBook.IsSpellKnown(a112)
  end
  if C_SpellBook and C_SpellBook.IsSpellKnownOrInSpellBook then
    local playerSpellBank2 = Enum and (Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player) or "player"
    return C_SpellBook.IsSpellKnownOrInSpellBook(a112, playerSpellBank2, true)
  end
  return IsSpellKnown(a112)
end
-- 功能：判断某个冷却字段对应的技能是否已学会（有豁免表）。
-- 入参：spellID 技能 ID。
-- 出参：true/false；false 时该字段写哨兵 601。
local function isSpellKnownForField(a113)
  local cooldownKnownExemptions = WowBuddyDev.classData and WowBuddyDev.classData.cooldownKnownCheckExemptions
  if cooldownKnownExemptions and cooldownKnownExemptions[a113] == true then
    return true
  end
  return WowBuddyDev.IsSpellKnown(a113)
end
-- 功能：不做任何职业特判地判断技能此刻能不能放。
-- 入参：spellID 技能 ID。
-- 出参：true/false。
-- 说明：先看强制可用名单（调试和兜底用），再依次要求「已学会」「当前可用」「不在冷却」三条全过。这是最底层的一层判断，职业差异请放在 IsSpellReady 上，不要往这里塞特判。
function WowBuddyDev.IsSpellReadyRaw(a114)
  if WowBuddyDev.forceAvailableState[a114] then
    return true
  end
  if not WowBuddyDev.IsSpellKnown(a114) then
    return false
  end
  local spellReady = true
  if WowBuddyDev.IsSpellUsable then
    spellReady = WowBuddyDev.IsSpellUsable(a114)
  end
  if not spellReady then
    return false
  end
  local remaining = WowBuddyDev.GetSpellCooldownRemaining(a114)
  if remaining and remaining > 0 then
    return false
  end
  return true
end
-- 功能：判断技能能不能放，带职业特判，是对外常用的那一层。
-- 入参：spellID 技能 ID。
-- 出参：true/false。
-- 说明：优先问职业模块的 OverrideIsSpellReady，它返回 nil 才算「不表态」、继续往下走。配置了 spellReadyAliases 的技能，把它自己和别名技能逐个拿去问 Raw 版，任意一个可用就算可用——共享冷却或同名替代技能靠这张表对齐。
function WowBuddyDev.IsSpellReady(a115)
  if WowBuddyDev.classData and WowBuddyDev.classData.OverrideIsSpellReady then
    local overrideReady = WowBuddyDev.classData.OverrideIsSpellReady(a115)
    if overrideReady ~= nil then
      return overrideReady
    end
  end
  local spellReadyAliases = WowBuddyDev.classData and WowBuddyDev.classData.spellReadyAliases
  if spellReadyAliases and spellReadyAliases[a115] then
    if WowBuddyDev.IsSpellReadyRaw(a115) then
      return true
    end
    for index21, v21 in ipairs(spellReadyAliases[a115]) do
      if WowBuddyDev.IsSpellReadyRaw(v21) then
        return true
      end
    end
    return false
  end
  return WowBuddyDev.IsSpellReadyRaw(a115)
end
-- 功能：给纹理设纯色。
-- 入参：texture；r/g/b（0~1）。
-- 出参：无。
local function setTextureColor(a116, a24, a33, a42)
  a116:SetColorTexture(a24, a33, a42, 1)
end
-- 功能：把整数写成 24 位 RGB 颜色（R=高 8 位、G=中 8 位、B=低 8 位）。
-- 入参：value 数值。
-- 出参：r/g/b 三个 0~1 分量。
-- 说明：这是插件把「精确整数」传给外部读取端的核心编码，取不到时返回 0,0,0。
local function rgbFromInt(a117)
  local v125, roundedValue = pcall(function()
    local clampedInt = math.floor(a117 + .5)
    if clampedInt > 16777215 then
      clampedInt = 16777215
    end
    if clampedInt < 0 then
      clampedInt = 0
    end
    return clampedInt
  end)
  if not v125 or type(roundedValue) ~= "number" then
    return 0, 0, 0
  end
  local redPart = math.floor(roundedValue / 65536) / 255
  local greenPart = math.floor(roundedValue % 65536 / 256) / 255
  local bluePart = roundedValue % 256 / 255
  return redPart, greenPart, bluePart
end
local maxRgbValue = 16777215
local noValueRgbSentinel = 16777215
-- 功能：十分位编码：rgbFromInt(value × 10)，用于冷却（0.1 秒精度）。
-- 入参：value 秒数；nil 时写无值哨兵 (255,255,255)。
-- 出参：r/g/b。
local function rgbFromTenths(a118)
  if not a118 then
    return rgbFromInt(maxRgbValue)
  end
  return rgbFromInt(a118 * 10)
end
-- 功能：计数编码：rgbFromInt(value)，nil 时写无值哨兵。
-- 入参：value 数量。
-- 出参：r/g/b。
local function rgbFromCount(a119)
  if a119 == nil then
    return rgbFromInt(noValueRgbSentinel)
  end
  return rgbFromInt(a119)
end
-- 功能：建（并缓存）血量百分比 → 颜色的曲线：蓝通道就是百分比本身。
-- 入参：无。
-- 出参：true/false（曲线可用与否）。
local function ensureHealthCurve()
  if WowBuddyDev.healthColorCurve then
    return true
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitHealthPercent)) then
    return false
  end
  WowBuddyDev.healthColorCurve = C_CurveUtil.CreateColorCurve()
  WowBuddyDev.healthColorCurve:SetType(Enum.LuaCurveType.Step)
  for i9 = 0, 100, 1 do
    WowBuddyDev.healthColorCurve:AddPoint(i9 / 100, CreateColor(0, 0, i9 / 255, 1))
  end
  return true
end
local raidAckCurve = nil
-- 功能：建一条「真/假」两点的颜色曲线。
-- 入参：无。
-- 出参：曲线对象。
local function createBinaryCurve()
  if raidAckCurve then
    return raidAckCurve
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitHealthPercent)) then
    return nil
  end
  local binaryCurve = C_CurveUtil.CreateColorCurve()
  binaryCurve:SetType(Enum.LuaCurveType.Step)
  binaryCurve:AddPoint(0, CreateColor(0, 0, 1, 1))
  binaryCurve:AddPoint(1, CreateColor(0, 0, 0, 1))
  raidAckCurve = binaryCurve
  return binaryCurve
end
-- 功能：取某个单位血量百分比换算出来的 alpha 值（0~1），用来把治疗者血条层叠显示。
-- 入参：unit 单位令牌；curve 血量百分比 → 颜色的曲线（蓝通道装百分比）。
-- 出参：alpha 数字（GetRGB 的第 3 位）；单位不存在或读不到时返回 0。
-- 说明：UnitHealthPercent 返回的是颜色对象，要经 GetRGB 取出蓝通道才是 0~1 的数值；调用方拿它直接喂 SetAlpha，所以这里返回的是数字不是颜色对象。
local function getHealthPercentAlpha(a120, a25)
  if not UnitExists(a120) then
    return 1
  end
  if UnitIsDeadOrGhost(a120) or not UnitIsConnected(a120) then
    return 0
  end
  local healthPercentColor = UnitHealthPercent(a120, true, a25)
  if not healthPercentColor or not healthPercentColor.GetRGB then
    return 1
  end
  local healthR, healthG, healthB = healthPercentColor:GetRGB()
  return healthB
end
-- 功能：取 mouseover 单位血量百分比换算出来的 alpha 值（0~1），用于治疗者主血条那一层。
-- 入参：curve 血量百分比 → 颜色的曲线。
-- 出参：alpha 数字；没有 mouseover 治疗 NPC 或读不到时返回 0。
-- 说明：函数名里的「物品冷却」是早先误解 —— 函数体只做 UnitHealthPercent(mouseover) + GetRGB，和物品/冷却无关。会先问 HasHealingNpcMouseover 确认鼠标指着的确实是需要关照的治疗 NPC，避免把鼠标扫过任意单位时的血量当成团队血量。
local function getMouseoverHealthAlpha(a121)
  if type(WowBuddyDev.HasHealingNpcMouseover) ~= "function" or not WowBuddyDev.HasHealingNpcMouseover() then
    return 0
  end
  local mouseHealthOk, mouseHealthColor = pcall(UnitHealthPercent, "mouseover", true, a121)
  if not mouseHealthOk or not mouseHealthColor or not mouseHealthColor.GetRGB then
    return 0
  end
  local mouseR, mouseG, mouseB = mouseHealthColor:GetRGB()
  return mouseB
end
-- 功能：治疗专精的层叠血条 —— 按队伍人数逐层设 alpha，让每层透明度等于对应队员的血量百分比。
-- 入参：enabled 是否允许渲染（总开关）。
-- 出参：true/false；true 表示这次渲染了治疗层（调用方据此把总开关那一格画成红色）。
-- 说明：战斗中不出（战斗中 alpha 受客户端限制）、非治疗专精不出。1..N 层对应 raidN / player / partyN；第 41 层是主层，用 mouseover 那个单位的血量，对着治疗 NPC 就能一眼看出团队整体血量。
local function renderHealerHealthLayers(a122)
  local healerLayerPool = WowBuddyDev.healerMasterHealthLayers
  if not healerLayerPool then
    return false
  end
  for index22, v22 in ipairs(healerLayerPool) do
    v22:SetAlpha(0)
  end
  if not a122 or not WowBuddyDev.IsHealingSpec() then
    return false
  end
  if UnitAffectingCombat("player") then
    return false
  end
  local healerLayerCurve = createBinaryCurve()
  if not healerLayerCurve then
    return false
  end
  local isRaid = IsInRaid()
  local groupSize = math.max(GetNumGroupMembers(), 1)
  groupSize = math.min(groupSize, isRaid and 40 or 5)
  for i10 = 1, groupSize, 1 do
    local unitToken = isRaid and "raid" .. i10 or (i10 == 1 and "player" or "party" .. i10 - 1)
    local alphaOk, alphaValue = pcall(getHealthPercentAlpha, unitToken, healerLayerCurve)
    if alphaOk then
      healerLayerPool[i10]:SetAlpha(alphaValue)
    else
      healerLayerPool[i10]:SetAlpha(1)
    end
  end
  local healerMasterLayer = healerLayerPool[41]
  if healerMasterLayer then
    healerMasterLayer:SetAlpha(getMouseoverHealthAlpha(healerLayerCurve))
  end
  return true
end
local teamAvgCurveCache = nil
local teamAvgCurveGroupSize = 0
-- 功能：建（并缓存）「团队均值百分比 → 颜色」曲线，曲线按当前人数缩放。
-- 入参：无。
-- 出参：曲线对象 + 当前人数；客户端没有曲线 API 时曲线为 nil。
-- 说明：蓝通道 = 百分比 / 人数，所以单个格子的颜色本身就编码了「人均血量」；人数变了必须重建，否则读出来的数会偏。
local function ensureTeamAvgCurve()
  local groupMemberCount = GetNumGroupMembers and GetNumGroupMembers() or 0
  if groupMemberCount < 1 then
    groupMemberCount = 1
  end
  if teamAvgCurveCache and teamAvgCurveGroupSize == groupMemberCount then
    return teamAvgCurveCache, groupMemberCount
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitHealthPercent)) then
    return nil, groupMemberCount
  end
  local teamAvgCurve = C_CurveUtil.CreateColorCurve()
  teamAvgCurve:SetType(Enum.LuaCurveType.Step)
  for i11 = 0, 100, 1 do
    teamAvgCurve:AddPoint(i11 / 100, CreateColor(0, 0, i11 / groupMemberCount / 255, 1))
  end
  teamAvgCurveCache = teamAvgCurve
  teamAvgCurveGroupSize = groupMemberCount
  return teamAvgCurve, groupMemberCount
end
-- 功能：建（并缓存）符能百分比 → 颜色曲线（蓝通道 = 百分比）。
-- 入参：无。
-- 出参：true/false（曲线可用与否）。
local function ensureRunicPowerCurve()
  if WowBuddyDev.runicPowerColorCurve then
    return true
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitPowerPercent)) then
    return false
  end
  WowBuddyDev.runicPowerColorCurve = C_CurveUtil.CreateColorCurve()
  WowBuddyDev.runicPowerColorCurve:SetType(Enum.LuaCurveType.Step)
  for i12 = 0, 100, 1 do
    WowBuddyDev.runicPowerColorCurve:AddPoint(i12 / 100, CreateColor(0, 0, i12 / 255, 1))
  end
  return true
end
-- 功能：建（并缓存）能量百分比 → 颜色曲线（蓝通道 = 百分比）。
-- 入参：无。
-- 出参：true/false（曲线可用与否）。
local function ensureEnergyCurve()
  if WowBuddyDev.energyColorCurve then
    return true
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitPowerPercent)) then
    return false
  end
  WowBuddyDev.energyColorCurve = C_CurveUtil.CreateColorCurve()
  WowBuddyDev.energyColorCurve:SetType(Enum.LuaCurveType.Step)
  for i13 = 0, 100, 1 do
    WowBuddyDev.energyColorCurve:AddPoint(i13 / 100, CreateColor(0, 0, i13 / 255, 1))
  end
  return true
end
-- 功能：建（并缓存）恶魔之怒百分比 → 颜色曲线（蓝通道 = 百分比）。
-- 入参：无。
-- 出参：true/false（曲线可用与否）。
local function ensureDemonicFuryCurve()
  if WowBuddyDev.demonicFuryColorCurve then
    return true
  end
  if not (C_CurveUtil and (C_CurveUtil.CreateColorCurve and UnitPowerPercent)) then
    return false
  end
  WowBuddyDev.demonicFuryColorCurve = C_CurveUtil.CreateColorCurve()
  WowBuddyDev.demonicFuryColorCurve:SetType(Enum.LuaCurveType.Step)
  for i14 = 0, 100, 1 do
    WowBuddyDev.demonicFuryColorCurve:AddPoint(i14 / 100, CreateColor(0, 0, i14 / 255, 1))
  end
  return true
end
local footerInterval = .02
local footerElapsed = 0
local consumableCooldownCache = {}
local consumableRefreshInterval = 5
local alertMasterText, alertBurstText
local alertUntilMaster, alertUntilBurst, alertUntilAoe = 0, 0, 0
local consumableRefreshElapsed = 0
local enemyScanInterval = .1
local enemyCount8yd = 0
local enemyCountAdjusted = 0
local encounterPending = nil
local toggleLabelTable = { [0] = "单/|cff00ff00自|r", [1] = "|cff00ff00单|r/自" }
local aoeModeLabelTable = { [0] = "自动", [1] = "单体", [2] = "群体" }
-- 功能：显示一行大字提示，并给三个固定提示各自记住到期时间。
-- 入参：fontString 目标文本对象；text 要显示的文本（会过 L() 本地化）；duration 显示时长，默认 1 秒。
-- 出参：无。
-- 说明：总开关/爆发/AOE 三个提示各有自己的计时变量（到点由主循环统一隐藏）；其他临时 FontString 直接走 C_Timer.After，不进这套计时。DB.disableTextAlert 打开时整段跳过。
local function showAlertText(a123, a26, a34)
  if not a123 then
    return
  end
  if WowBuddyDev.DB and WowBuddyDev.DB.disableTextAlert then
    return
  end
  a123:SetText(WowBuddyDev.L(a26))
  a123:Show()
  local alertDuration = a34 or 1
  if a123 == alertMasterText then
    alertUntilMaster = GetTime() + alertDuration
  elseif a123 == alertBurstText then
    alertUntilBurst = GetTime() + alertDuration
  elseif a123 == alertAoeMode then
    alertUntilAoe = GetTime() + alertDuration
  else
    C_Timer.After(alertDuration, function()
      if a123 then
        a123:Hide()
      end
    end)
  end
end
-- 功能：开关切换时播音效（开=on、关=off、爆发=baofa）。
-- 入参：enable 是否开启；isBurst 是否爆发。
-- 出参：无。
-- 说明：音效文件放在插件目录下，路径用 ... 拿到的插件名拼出来。
local function playToggleSound(a124, a27)
  if WowBuddyDev.DB and WowBuddyDev.DB.disableSound then
    return
  end
  local soundPath
  if a27 then
    soundPath = a124 and "Interface\\AddOns\\" .. ADDON_NAME .. "\\toggle_baofa.ogg" or "Interface\\AddOns\\" .. ADDON_NAME .. "\\toggle_off.ogg"
  else
    soundPath = a124 and "Interface\\AddOns\\" .. ADDON_NAME .. "\\toggle_on.ogg" or "Interface\\AddOns\\" .. ADDON_NAME .. "\\toggle_off.ogg"
  end
  PlaySoundFile(soundPath)
end
-- 功能：在「自动」和「单体」之间来回切换 AOE 模式，刷新状态灯并给一行提示。
-- 入参：无。
-- 出参：无。
-- 说明：只切 0↔1；「群体」由专精配置决定能不能选，这个键不参与 2。
local function toggleAoeMode()
  local nextAoeMode = WowBuddyDev.DB.aoeMode == 0 and 1 or 0
  WowBuddyDev.DB.aoeMode = nextAoeMode
  if WowBuddyDev.RefreshStateLogo then
    WowBuddyDev.RefreshStateLogo()
  end
  if WowBuddyDev.alertAoeMode then
    showAlertText(WowBuddyDev.alertAoeMode, "|cff00ff00" .. WowBuddyDev.L(aoeModeLabelTable[nextAoeMode]) .. "|r", 1)
  end
  playToggleSound(false)
end
-- 功能：反转总开关并同步 UI。
-- 入参：无。
-- 出参：无。
local function toggleMasterSwitch()
  WowBuddyDev.DB.masterSwitch = not WowBuddyDev.DB.masterSwitch
  WowBuddyDev.UpdateMasterSwitchUI(WowBuddyDev.DB.masterSwitch)
end
-- 功能：反转爆发开关。
-- 入参：无。
-- 出参：无。
local function toggleBurstSwitch()
  WowBuddyDev.SetBurstSwitch(not WowBuddyDev.DB.burstSwitch)
end
local footerTickerFrame = CreateFrame("Frame")
footerTickerFrame:SetScript("OnUpdate", function(self2, deltaTime)
  footerElapsed = footerElapsed + deltaTime
  if footerElapsed < footerInterval then
    return
  end
  footerElapsed = footerElapsed - footerInterval
  ensureHealthCurve()
  ensureRunicPowerCurve()
  ensureEnergyCurve()
  ensureDemonicFuryCurve()
  local mouseoverStateValue = 0
  if type(WowBuddyDev.UpdateHealingNpcMouseover) == "function" then
    local mouseoverOk, mouseoverResult = pcall(WowBuddyDev.UpdateHealingNpcMouseover)
    if mouseoverOk and type(mouseoverResult) == "number" then
      mouseoverStateValue = mouseoverResult
    end
  end
  local loggedOnce = false
  if type(GetCurrentKeyBoardFocus) == "function" then
    local focusOk, focusWidget = pcall(GetCurrentKeyBoardFocus)
    loggedOnce = focusOk and focusWidget ~= nil
  end
  if not WowBuddyDev.waitingForKey then
    if WowBuddyDev.IsBindPressed(WowBuddyDev.DB.masterKey) then
      if not WowBuddyDev.masterKeyPressed then
        WowBuddyDev.masterKeyPressed = true
        if not loggedOnce then
          toggleMasterSwitch()
        end
      end
    else
      WowBuddyDev.masterKeyPressed = false
    end
    if WowBuddyDev.IsBindPressed(WowBuddyDev.DB.burstKey) then
      if not WowBuddyDev.burstKeyPressed then
        WowBuddyDev.burstKeyPressed = true
        if not loggedOnce then
          toggleBurstSwitch()
        end
      end
    else
      WowBuddyDev.burstKeyPressed = false
    end
    if WowBuddyDev.IsBindPressed(WowBuddyDev.DB.aoeKey) then
      if not WowBuddyDev.aoeKeyPressed then
        WowBuddyDev.aoeKeyPressed = true
        if not loggedOnce then
          toggleAoeMode()
        end
      end
    else
      WowBuddyDev.aoeKeyPressed = false
    end
  end
  consumableRefreshElapsed = consumableRefreshElapsed - deltaTime
  if consumableRefreshElapsed <= 0 then
    consumableRefreshElapsed = enemyScanInterval
    enemyCount8yd, enemyCountAdjusted = countNearbyEnemies(8)
    enemyCountAdjusted = clampFriendlyCount(enemyCountAdjusted)
  end
  local aoeMode = WowBuddyDev.DB and WowBuddyDev.DB.aoeMode or 0
  local masterSwitch = WowBuddyDev.DB.masterSwitch
  if loggedOnce then
    masterSwitch = false
  end
  if _G.PermesCharuExpire and GetTime() < _G.PermesCharuExpire then
    masterSwitch = false
  end
  -- ★ 本层是每帧渲染，必须自己吃掉异常：本函数体内任何一处抛错都会直接冒到插件外层
  --   （同文件的 UpdateHealingNpcMouseover / GetAutoTargetPacket 调用都已用 pcall 兜底，
  --    这一处此前漏了）。pcall 失败时按「闸门关闭」处理，等于停发，是安全侧。
  local gateOk, gateOpen = pcall(WowBuddyDev.IsAutoTargetGateOpen, enemyCount8yd)
  if not gateOk or gateOpen ~= true then
    masterSwitch = false
  end
  local forceRedTeamRow = false
  if renderHealerHealthLayers(masterSwitch) then
    forceRedTeamRow = true
  end
  local targetDistance = getUnitDistance("target")
  wipe(valuesById)
  valuesById.master_switch = masterSwitch
  valuesById.mouseover_npc_state = mouseoverStateValue
  valuesById.burst = WowBuddyDev.DB.burstSwitch
  valuesById.aoe_mode = aoeMode
  local ttdValue = 0
  if type(WowBuddyDev.GetAutoTargetPacket) == "function" then
    local packetOk, packetValue = pcall(WowBuddyDev.GetAutoTargetPacket)
    if packetOk and type(packetValue) == "number" then
      ttdValue = packetValue
    end
  end
  valuesById.ttd = ttdValue
  valuesById.ttf = 0
  valuesById.distance = targetDistance
  if aoeMode == 1 then
    valuesById.active_enemies = 1
  elseif aoeMode == 2 then
    valuesById.active_enemies = 5
  else
    valuesById.active_enemies = enemyCountAdjusted
  end
  valuesById.enemies_8yd = enemyCount8yd
  valuesById.trinket1_cd = WowBuddyDev.GetTrinketSlotCooldownRemaining(13)
  valuesById.trinket2_cd = WowBuddyDev.GetTrinketSlotCooldownRemaining(14)
  valuesById.gcd = WowBuddyDev.IsGcdActive()
  local playerCasting, castRemaining, playerCastSpellID, playerCastObservationCode = WowBuddyDev.GetPlayerCastState(true)
  valuesById.player_casting = playerCasting
  valuesById.cast_remaining = castRemaining
  valuesById.player_cast_spell_id = playerCastSpellID
  valuesById.player_cast_observation_code = playerCastObservationCode
  local succeededGeneration, succeededSpellID = WowBuddyDev.GetPlayerSucceededState()
  valuesById.player_succeeded_generation = succeededGeneration
  valuesById.player_succeeded_spell_id = succeededSpellID
  if UnitAffectingCombat("player") then
    local now = GetTime()
    if not encounterPending then
      encounterPending = now
    end
    valuesById.combat_time = math.floor(now - encounterPending)
  else
    encounterPending = nil
    valuesById.combat_time = 0
  end
  valuesById.class = WowBuddyDev.DB.currentClass or "UNKNOWN"
  valuesById.specIndex = WowBuddyDev.DB.currentSpecIndex or 0
  valuesById.specID = WowBuddyDev.DB.currentSpecID or 0
  valuesById.specName = WowBuddyDev.DB.currentSpecName or WowBuddyDev.L("未知")
  valuesById.spec_id = WowBuddyDev.GetPackedGameIdentity()
  valuesById.target_casting = getTargetCastingColor()
  valuesById.focus_casting = getFocusCastingColor()
  local playerHealthColor, targetHealthColor = nil, nil
  local partyHealthColorById = {}
  if ensureHealthCurve() then
    local playerHealthOk, playerHealthResult = pcall(UnitHealthPercent, "player", true, WowBuddyDev.healthColorCurve)
    if playerHealthOk and playerHealthResult then
      playerHealthColor = playerHealthResult
    end
    local targetHealthOk, targetHealthResult = pcall(UnitHealthPercent, "target", true, WowBuddyDev.healthColorCurve)
    if targetHealthOk and targetHealthResult then
      targetHealthColor = targetHealthResult
    end
    for i15 = 1, 4, 1 do
      local partyUnit = "party" .. i15
      if UnitExists(partyUnit) and not UnitIsDeadOrGhost(partyUnit) then
        local partyHealthOk, partyHealthResult = pcall(UnitHealthPercent, partyUnit, true, WowBuddyDev.healthColorCurve)
        if partyHealthOk and partyHealthResult then
          partyHealthColorById[i15] = partyHealthResult
        end
      end
    end
  end
  valuesById.player_health_pct = playerHealthColor and 0 or 255
  valuesById.target_health_pct = targetHealthColor and 0 or 255
  for i16 = 1, 4, 1 do
    local partyHealthKey = "party" .. i16 .. "_health_pct"
    if partyHealthColorById[i16] then
      valuesById[partyHealthKey] = partyHealthColorById[i16]
    else
      valuesById[partyHealthKey] = 100
    end
  end
  -- 功能：把某个字段的当前值转成「给人看的说明文本」（调试面板用）。
  -- 入参：field 字段定义；value 当前值；index 字段序号。
  -- 出参：说明字符串（已经本地化）。
  local function describeField(a125, a28, a35)
    if a125.id == "master_switch" and forceRedTeamRow then
      return "", true
    end
    if isFieldSuppressed(a125.id) then
      return "", true
    end
    -- 别的职业专属的字段（术士表面的火焰图腾/连击点/怒气/潜行/形态…）直接不出行，
    -- 见 classOnlyDebugFields。只影响调试文字，不动色块与编号。
    if isForeignClassField(a125.id) then
      return "", true
    end
    -- 本职业、但不属于当前专精的技能字段也不出行（按键页同款口径，见 isForeignSpecField）。
    if isForeignSpecField(a125) then
      return "", true
    end
    -- 单位不存在时整组不出行：solo 时 party1-4 的有效/血量/逐技能射程、无目标时的
    -- target 行全是「OFF/无值」噪音；进组/选目标后行自动回来。player 行不受影响。
    local lineUnit = a125.id:match("^friendly_(.+)$") or a125.id:match("^health_(.+)$") or a125.id:match("^range_%d+_(.+)$")
    if lineUnit and lineUnit ~= "player" and not UnitExists(lineUnit) then
      return "", true
    end
    -- 没学会的技能整组不出行（已学/射程/可用/冷却一起藏）：
    -- 低等级号天赋未解锁、专精判不出来时，「已学会」就是「当前专精技能」的事实口径；
    -- 判定按 base ID + spellReadyAliases 等级组任一会了就算会，防高等级替换误杀。
    local lineSpellID = tonumber(a125.spellID)
    if not lineSpellID and type(a125.id) == "string" then
      for _, linePrefix in ipairs(specScopedFieldPrefixes) do
        lineSpellID = tonumber(a125.id:match(linePrefix))
        if lineSpellID then
          break
        end
      end
    end
    if lineSpellID and WowBuddyDev.IsSpellKnown then
      local lineKnown = false
      local baseOK, baseKnown = pcall(WowBuddyDev.IsSpellKnown, lineSpellID)
      if baseOK and baseKnown then
        lineKnown = true
      else
        local aliases = WowBuddyDev.classData and WowBuddyDev.classData.spellReadyAliases
        local aliasList = aliases and aliases[lineSpellID]
        if type(aliasList) == "table" then
          for _, aliasID in ipairs(aliasList) do
            local aliasOK, aliasKnown = pcall(WowBuddyDev.IsSpellKnown, aliasID)
            if aliasOK and aliasKnown then
              lineKnown = true
              break
            end
          end
        end
      end
      if not lineKnown then
        return "", true
      end
    end
    if not WowBuddyDev.isClassActive and a35 > #WowBuddyDev.pixelData + #WowBuddyDev.COMMON_PIXEL_DATA then
      return WowBuddyDev.L(a125.label) .. ": --"
    end
    if a125.id == "isMoving" then
      return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.movementBindingProfile or "--")
    elseif (a125.id == "target_casting" or a125.id == "focus_casting" or a125.id == "mouseover_casting") and (type(a28) == "table" and a28.GetRGB) then
      return WowBuddyDev.L(a125.label) .. ": 颜色编码"
    elseif a125.id == "gcd" then
      local text = a28 == nil and "|cffffff00状态未确认|r" or (a28 and "|cff00ff00ON|r" or "|cffff0000OFF|r")
      return "GCD: " .. text
    elseif a125.type == "talents" then
      local state = WowBuddyDev.GetHunterTalentState()
      return WowBuddyDev.L(a125.label) .. ": " .. state.display
    elseif a125.type == "aura_state" or a125.type == "validity" then
      if a28 == true then
        return WowBuddyDev.L(a125.label) .. ": |cff00ff00" .. WowBuddyDev.L("开启") .. "|r"
      elseif a28 == false then
        return WowBuddyDev.L(a125.label) .. ": |cffff0000" .. WowBuddyDev.L("关闭") .. "|r"
      else
        return WowBuddyDev.L(a125.label) .. ": |cffffff00" .. WowBuddyDev.L("状态未确认") .. "|r"
      end
    elseif a125.type == "switch" or a125.type == "bool" then
      if a28 == true then
        return WowBuddyDev.L(a125.label) .. ": |cff00ff00ON|r"
      elseif a28 == false then
        return WowBuddyDev.L(a125.label) .. ": |cffff0000OFF|r"
      else
        return WowBuddyDev.L(a125.label) .. ": |cffffff00" .. WowBuddyDev.L("状态未确认") .. "|r"
      end
    elseif a125.type == "distance" then
      return WowBuddyDev.L(a125.label) .. ": " .. (a28 and string.format("%.1f", a28) .. "码" or WowBuddyDev.L("未知"))
    elseif a125.type == "count" then
      if a125.enumMap then
        local enumLabel = a125.enumMap[a28] or a125.enumMap[tostring(a28)] or tostring(a28 or 0)
        return WowBuddyDev.L(a125.label) .. ": " .. enumLabel
      elseif a125.id == "highlight427453" then
        local highlightValue = a28 or 0
        if highlightValue == 2 then
          return WowBuddyDev.L(a125.label) .. ": |cff00ccff收费|r"
        elseif highlightValue == 1 then
          return WowBuddyDev.L(a125.label) .. ": |cff00ff00免费|r"
        else
          return WowBuddyDev.L(a125.label) .. ": |cffff0000OFF|r"
        end
      else
        if a125.id == "aoe_mode" then
          local aoeModeLabels = { WowBuddyDev.L("自动"), WowBuddyDev.L("单体"), WowBuddyDev.L("群体") }
          return WowBuddyDev.L(a125.label) .. ": " .. (aoeModeLabels[(a28 or 0) + 1] or tostring(a28))
        elseif a125.id == "eclipse_state" then
          local eclipseStateLabels = { "无", "日蚀", "月蚀", "双蚀" }
          return WowBuddyDev.L(a125.label) .. ": " .. (eclipseStateLabels[(a28 or 0) + 1] or tostring(a28 or 0))
        elseif a125.id == "bear_form" then
          local druidFormLabels = { "人形", "熊", "水栖", "猎豹", "旅行", "枭兽/树" }
          return WowBuddyDev.L(a125.label) .. ": " .. (druidFormLabels[(a28 or 0) + 1] or tostring(a28 or 0))
        else
          return WowBuddyDev.L(a125.label) .. ": " .. tostring(a28 or 0)
        end
      end
    elseif a125.type == "number" then
      if a125.id == "player_health_pct" and playerHealthColor then
        return "", true
      elseif a125.id == "target_health_pct" and targetHealthColor then
        return "", true
      elseif a125.id:match("^party%d+_health_pct$") and partyHealthColorById then
        return "", true
      elseif a125.id == "team_avg_health" then
        return "", true
      elseif a125.id == "energy_runicpower" and (type(a28) == "table" and a28.GetRGB) then
        return "", true
      elseif a125.id == "demonic_fury" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.demonicFuryDisplay or "?")
      elseif a125.id == "fury" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.furyDisplay or "?")
      elseif a125.id == "mana_pct" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.manaDisplay or "?")
      elseif a125.id == "energy" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.energyDisplay or "?")
      elseif a125.id == "energy_holypower" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.holyPowerDisplay or "?")
      elseif a125.id == "insanity" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.insanityDisplay or "?")
      elseif a125.id == "astral_power" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.astralPowerDisplay or "?")
      elseif a125.id == "rage" then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.rageDisplay or "?")
      elseif a125.id == "focus" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.focusDisplay or "?")
      elseif a125.id == "energy_maelstrom" and (type(a28) == "table" and a28.GetRGB) then
        return WowBuddyDev.L(a125.label) .. ": " .. (WowBuddyDev.maelstromDisplay or "?")
      elseif a125.id == "combo_strike" then
        local monkComboLabels = {
          "无",
          "猛虎掌",
          "幻灭踢",
          "怒雷破",
          "升龙霸",
          "神鹤引项踢",
          "轮回之触",
          "乾元之巅",
          "碎玉闪电",
        }
        local comboIndex = (a28 or 0) + 1
        return WowBuddyDev.L(a125.label) .. ": " .. (monkComboLabels[comboIndex] or tostring(a28 or 0))
      else
        -- ★ 数字字段的值可能是 Color 对象（如 pet_health 走 colorPercent 返回颜色曲线），
        --   直接 tostring 会打成 "table: 0x00000255684A"，既看不懂也暴露地址。
        --
        -- ★★ 但**绝不能用它做算术**：无限（12.x）里颜色分量是「秘密值」（secret number），
        --    只允许直接赋给贴图/比较，一旦参与 + - * / 就报
        --    "attempt to perform arithmetic on local 'colorB' (a secret number value)"。
        --    实测踩过：这里算出百分比后刷了 4475 条报错。
        --    所以两道防护：① 有 issecretvalue 就先问它；② 算术整体包 pcall 兜底。
        --    两者都过不去就老实显示 "--"，不要为了好看去动秘密值。
        if type(a28) == "table" and a28.GetRGB then
          local colorOK, colorR, colorG, colorB = pcall(function() return a28:GetRGB() end)
          local isSecretValue = false
          if colorOK and issecretvalue then
            local secretOK, secret = pcall(issecretvalue, colorB)
            isSecretValue = secretOK and secret == true
          end
          if colorOK and not isSecretValue and type(colorB) == "number" then
            local percentOK, percentText = pcall(function()
              return string.format("%d%%", math.floor(colorB * 100 + 0.5))
            end)
            if percentOK and type(percentText) == "string" then
              return WowBuddyDev.L(a125.label) .. ": " .. percentText
            end
          end
          -- 秘密值 / 取不到：只给占位符。绝不尝试换算。
          return WowBuddyDev.L(a125.label) .. ": --"
        end
        return WowBuddyDev.L(a125.label) .. ": " .. tostring(a28 or 0)
      end
    elseif a125.type == "spell" then
      return WowBuddyDev.L(a125.label) .. ": " .. (a28 and "|cff00ff00可用|r" or "|cffff0000不可用|r")
    elseif a125.type == "cooldown" then
      local cooldownValue = a28 or 0
      local cooldownSecondsRounded = math.ceil(cooldownValue)
      if cooldownValue == 601 then
        return WowBuddyDev.L(a125.label) .. ": " .. WowBuddyDev.L("|cffff0000不可用|r")
      elseif cooldownValue > 0 then
        return WowBuddyDev.L(a125.label) .. ": |cffff0000" .. cooldownSecondsRounded .. "|r"
      else
        return WowBuddyDev.L(a125.label) .. ": |cff00ff000|r"
      end
    elseif a125.type == "string" then
      return WowBuddyDev.L(a125.label) .. ": " .. tostring(a28 or "--")
    end
    return WowBuddyDev.L(a125.label) .. ": --"
  end
  for index23, v23 in ipairs(WowBuddyDev.testSpells) do
    valuesById["spell_" .. v23] = WowBuddyDev.IsSpellReady(v23)
  end
  if WowBuddyDev.cooldowns then
    for k, v24 in pairs(WowBuddyDev.cooldowns) do
      if isSpellKnownForField(k) then
        valuesById["cd_" .. k] = WowBuddyDev.GetSpellCooldownRemaining(k)
      else
        valuesById["cd_" .. k] = 601
      end
    end
  end
  -- 【改装】专精自选的"额外冷却字段"：这些技能原本只在横排显示成文字（要 OCR），
  -- 现在也写成竖排颜色格，读取端直接解颜色，准得多而且带 0.1 秒精度。
  -- 故意不加进 cooldowns 表：那样会走"记录施放时间"的推算路径（没记录到就返回 0），
  -- 不加才走 API 路径，读的是客户端自己的真实冷却。
  if WowBuddyDev.classData and WowBuddyDev.classData.extraCooldownFields then
    for _, k8 in ipairs(WowBuddyDev.classData.extraCooldownFields) do
      if isSpellKnownForField(k8) then
        valuesById["cd_" .. k8] = WowBuddyDev.GetSpellCooldownRemaining(k8)
      else
        valuesById["cd_" .. k8] = 601
      end
    end
  end
  -- 独立0.2协议用bit0..23承载24项状态，不再占用一位作为固定标记。
  local actionAvailBitmap = 0
  if WowBuddyDev.actionAvailSpellIDs then
    for i17 = 1, #WowBuddyDev.actionAvailSpellIDs, 1 do
      if WowBuddyDev.IsSpellReady(WowBuddyDev.actionAvailSpellIDs[i17]) then
        actionAvailBitmap = actionAvailBitmap + 2 ^ (i17 - 1)
      end
    end
  end
  valuesById.action_avail = actionAvailBitmap
  -- 圣骑士：圣疗术(633) 与 圣盾术(642) 互斥 —— 其中一个处于长冷却时，另一个标 601。
  -- ★ 原判定写死正式服三系 ID（70 惩戒 / 66 防护）。无限圣骑 specID 恒为 1486，
  --   该条件永不成立，这段在无限上等于死代码。改为同时支持两套：
  --   正式服仍按 specID 分档；无限按天赋主系职责分档（惩戒=MELEE → 390 秒，
  --   防护=TANK → 270 秒），阈值与原正式服行为逐一对应。
  --   无限圣骑模块目前未声明 cd_633 / cd_642，读到 nil 按 0 处理，
  --   两个阈值都不满足 → 不改写任何值，行为安全。
  local paladinCd633Threshold = nil
  if WowBuddyDev.DB.currentSpecID == 70 then
    paladinCd633Threshold = 390
  elseif WowBuddyDev.DB.currentSpecID == 66 then
    paladinCd633Threshold = 270
  elseif WowBuddyDev.DB.currentSpecID == 1486 and WowBuddyDev.GetSpecRole then
    local paladinRole = WowBuddyDev.GetSpecRole()
    if paladinRole == "MELEE" then
      paladinCd633Threshold = 390
    elseif paladinRole == "TANK" then
      paladinCd633Threshold = 270
    end
  end
  if paladinCd633Threshold then
    local cd642 = valuesById.cd_642 or 0
    local cd633 = valuesById.cd_633 or 0
    if cd642 > 180 then
      valuesById.cd_633 = 601
    end
    if cd633 > paladinCd633Threshold then
      valuesById.cd_642 = 601
    end
  end
  consumableRefreshInterval = consumableRefreshInterval + deltaTime
  if consumableRefreshInterval >= 5 then
    consumableRefreshInterval = 0
    wipe(consumableCooldownCache)
    for index24, v25 in ipairs(WowBuddyDev.consumableItems) do
      consumableCooldownCache[v25.id] = WowBuddyDev.GetConsumableCooldownRemaining(v25)
    end
  end
  for index25, v26 in ipairs(WowBuddyDev.consumableItems) do
    local consumableCachedCd = consumableCooldownCache[v26.id] or 0
    if consumableCachedCd == 601 then
      valuesById[v26.id] = 601
    else
      valuesById[v26.id] = WowBuddyDev.GetConsumableCooldownFast(v26)
    end
  end
  if WowBuddyDev.trinketItemID then
    valuesById.trinketCD = WowBuddyDev.GetTrinketCooldownRemaining()
  end
  if WowBuddyDev.extraValueRules then
    for index26, v27 in ipairs(WowBuddyDev.extraValueRules) do
      valuesById[v27.id] = WowBuddyDev.GetExtraValueByRule(v27)
    end
  end
  if WowBuddyDev.classData and WowBuddyDev.classData.GetExtraValues then
    WowBuddyDev.classData.GetExtraValues(valuesById)
  end
  if WowBuddyDev.healingNpcFocusMatchLayer and WowBuddyDev.RenderHealingNpcFocusMatch then
    pcall(WowBuddyDev.RenderHealingNpcFocusMatch, WowBuddyDev.healingNpcFocusMatchLayer)
  end
  local raidPacket = WowBuddyDev.GetRaidFocusPacket and WowBuddyDev.GetRaidFocusPacket() or nil
  if raidPacket and (WowBuddyDev.raidFocusAckLayers and ((raidPacket.frameSequence ~= WowBuddyDev.raidFocusAckFrameSequence or raidPacket.ackPixel ~= WowBuddyDev.raidFocusAckCarrier) and WowBuddyDev.RenderRaidFocusAcknowledgement)) then
    pcall(WowBuddyDev.RenderRaidFocusAcknowledgement, WowBuddyDev.raidFocusAckLayers, raidPacket)
    WowBuddyDev.raidFocusAckFrameSequence = raidPacket.frameSequence
    WowBuddyDev.raidFocusAckCarrier = raidPacket.ackPixel
  end
  valuesById.addon_version_code = WowBuddyDev.addonVersionCode
  valuesById.isMoving = WowBuddyDev.isMoving or false
  _G.PermesValues = valuesById
  -- 【数据桥】把字段集序列化成紧凑 KV 串，供外部软件 RWM 直读（绕开截图/OCR）
  -- 格式: magic|field1=val1,field2=val2,...   magic = "P74BRIDGE1"
  -- v2: 追加 avail_ids=当前已学且就绪技能ID列表(逗号分隔) + spell_<id> 就绪状态(1/0)
  do
    local parts = {}
    for k, v in pairs(valuesById) do
      if type(k) == "string" then
        local tv = type(v)
        if tv == "number" then
          parts[#parts + 1] = k .. "=" .. tostring(v)
        elseif tv == "boolean" and k:match("^spell_") then
          parts[#parts + 1] = k .. "=" .. (v and "1" or "0")
        end
      end
    end
    -- 当前已学且就绪的技能 ID 列表（动态，插件自识别）
    local avail = {}
    if WowBuddyDev.actionAvailSpellIDs then
      for _, sid in ipairs(WowBuddyDev.actionAvailSpellIDs) do
        if WowBuddyDev.IsSpellReady(sid) then
          avail[#avail + 1] = sid
        end
      end
    end
    parts[#parts + 1] = "avail_ids=" .. table.concat(avail, ",")
    _G.PermesValuesBridge = "P74BRIDGE1|" .. table.concat(parts, ",")
  end
  local hiddenCount = 0
  local debugShown = WowBuddyDev.debugFrame and WowBuddyDev.debugFrame:IsShown()
  for fieldIndex, field in ipairs(renderFields) do
    local value = valuesById[field.id]
    local chargeSpellID = field.id:match("^charge_(%d+)$")
    if chargeSpellID and not WowBuddyDev.IsSpellKnown(tonumber(chargeSpellID)) then
      value = 601
    end
    local r, g, b = .2, .2, .2
    if not WowBuddyDev.isClassActive and fieldIndex > #WowBuddyDev.pixelData + #WowBuddyDev.COMMON_PIXEL_DATA then

    else
      local raidIndex = raidPacket and tonumber(field.id:match("^raid_health_(%d%d)$"))
      if field.id == "master_switch" and forceRedTeamRow then
        r, g, b = 1, 0, 0
      elseif raidPacket and field.id == raidPacket.ackPixel then
        local frameSequence = raidPacket.frameSequence or 1
        r = .003921568627451
        g = .003921568627451
        if raidPacket.ackPixel == "party_tank_index" then
          local tankSlot = tonumber(value) or 0
          if tankSlot < 0 or tankSlot > 4 or tankSlot % 1 ~= 0 then
            tankSlot = 0
          end
          b = (frameSequence * 8 + tankSlot) / 255
        else
          b = frameSequence / 255
        end
      elseif raidPacket and field.id == "focus_cast_unreachable" then
        r = (raidPacket.rosterEpoch or 0) / 255
        local raidCount = tonumber(raidPacket.raidCount) or 0
        if raidCount < 0 or raidCount > 40 or raidCount % 1 ~= 0 then
          raidCount = 0
        end
        local feedbackKind = tonumber(raidPacket.feedbackKind) or 0
        if feedbackKind < 0 or feedbackKind > 3 or feedbackKind % 1 ~= 0 then
          feedbackKind = 0
        end
        local feedbackSequence = tonumber(raidPacket.feedbackSequence) or 0
        if feedbackSequence < 0 or feedbackSequence > 31 or feedbackSequence % 1 ~= 0 then
          feedbackSequence = 0
        end
        g = (128 + raidCount) / 255
        b = ((raidPacket.focusUnreachable and 128 or 0) + feedbackKind * 32 + feedbackSequence) / 255
      elseif raidIndex then
        local colorBase = (raidIndex - 1) * 3
        local healthColors = raidPacket.healthColors
        local tankBySlot = raidPacket.tankBySlot
        local raidLayers = WowBuddyDev.raidFocusHealthLayers and WowBuddyDev.raidFocusHealthLayers[raidIndex]
        local color1 = healthColors and healthColors[colorBase + 1]
        local color2 = healthColors and healthColors[colorBase + 2]
        local color3 = healthColors and healthColors[colorBase + 3]
        if raidLayers and raidLayers[1] then
          if color1 and color1.GetRGB then
            raidLayers[1]:SetColorTexture(color1:GetRGB())
          else
            raidLayers[1]:SetColorTexture(0, 0, 0, 1)
          end
        end
        if raidLayers and raidLayers[2] then
          if color2 and color2.GetRGB then
            raidLayers[2]:SetColorTexture(color2:GetRGB())
          else
            raidLayers[2]:SetColorTexture(0, 0, 0, 1)
          end
        end
        if raidLayers and raidLayers[3] then
          if color3 and color3.GetRGB then
            raidLayers[3]:SetColorTexture(color3:GetRGB())
          else
            raidLayers[3]:SetColorTexture(0, 0, 0, 1)
          end
        end
        r = tankBySlot and (tankBySlot[colorBase + 1] and .50196078431373) or 0
        g = tankBySlot and (tankBySlot[colorBase + 2] and .50196078431373) or 0
        b = tankBySlot and (tankBySlot[colorBase + 3] and .50196078431373) or 0
      elseif field.id == "team_avg_health" then
        local teamAvgColorCurve, teamAvgMemberCount = ensureTeamAvgCurve()
        local teamAvgTexturePool = WowBuddyDev.teamAvgLayers
        if teamAvgColorCurve and teamAvgTexturePool then
          local layer1 = 0
          -- 功能：写「团队均值」那一格的第 N 层颜色。
          -- 入参：unit 单位令牌。
          -- 出参：无（层号由闭包里的计数器推进）。
          -- 说明：三层语义 —— 存活写它的血量颜色；存在但死了写 100/人数/255（即人均 0%）；不存在写黑。
          local function renderTeamAvgLayer(a126)
            layer1 = layer1 + 1
            local layerTexture = teamAvgTexturePool[layer1]
            if not layerTexture then
              return
            end
            if UnitExists(a126) and not UnitIsDeadOrGhost(a126) then
              local layerHealthOk, layerHealthColor = pcall(UnitHealthPercent, a126, true, teamAvgColorCurve)
              if layerHealthOk and (layerHealthColor and layerHealthColor.GetRGB) then
                layerTexture:SetColorTexture(layerHealthColor:GetRGB())
              else
                layerTexture:SetColorTexture(0, 0, 0, 1)
              end
            elseif UnitExists(a126) then
              layerTexture:SetColorTexture(0, 0, 100 / teamAvgMemberCount / 255, 1)
            else
              layerTexture:SetColorTexture(0, 0, 0, 1)
            end
          end
          if IsInRaid and IsInRaid() then
            for i18 = 1, teamAvgMemberCount, 1 do
              renderTeamAvgLayer("raid" .. i18)
            end
          else
            renderTeamAvgLayer("player")
            for i19 = 1, 4, 1 do
              renderTeamAvgLayer("party" .. i19)
            end
          end
          for i20 = layer1 + 1, #teamAvgTexturePool, 1 do
            teamAvgTexturePool[i20]:SetColorTexture(0, 0, 0, 1)
          end
        end
        r, g, b = 0, 0, 0
      elseif field.id == "isMoving" then
        local isMovingValue = type(value) == "number" and value or 3527951
        r, g, b = rgbFromInt(isMovingValue)
      elseif field.id == "player_casting" then
        local layer2 = tonumber(WowBuddyDev.playerCastGeneration) or 0
        if layer2 < 1 or layer2 > 99 or layer2 % 1 ~= 0 then
          layer2 = 0
        end
        if value then
          r, g, b = 0, 1, layer2 / 255
        else
          r, g, b = 1, 0, layer2 / 255
        end
      elseif (field.id == "target_casting" or field.id == "focus_casting" or field.id == "mouseover_casting") and (type(value) == "table" and value.GetRGB) then
        r, g, b = value:GetRGB()
      elseif field.id == "burst" then
        if value then
          r, g, b = 0, 0, 1
        else
          r, g, b = 1, 1, 0
        end
      elseif field.type == "aura_state" or field.type == "validity" then
        -- 三态字段：绿色=确认成立，红色=确认不成立，黄色=接口不可读。
        -- 黄色不能被读取端当成“没有光环”，避免旧状态反复补放。
        if value == true then
          r, g, b = 0, 1, 0
        elseif value == false then
          r, g, b = 1, 0, 0
        else
          r, g, b = 1, 1, 0
        end
      elseif field.type == "switch" or field.type == "bool" then
        -- ★ 2026-10-04 改三态：原来 `if value then 绿 else 红` 会把 nil 也画成红=OFF，
        --   上游「判不出 → nil」的三态语义在这里被吞掉（组队只按宠物攻击的帮凶）。
        --   黄=未知：读取端按「未知开关色」(#FFFF00) 解码 ⇒ 引擎 triFlag=-1 ⇒ 规则跳过。
        if value == true then
          r, g, b = 0, 1, 0
        elseif value == false then
          r, g, b = 1, 0, 0
        else
          r, g, b = 1, 1, 0
        end
      elseif field.type == "distance" then
        r, g, b = rgbFromTenths(value)
      elseif field.type == "count" then
        if field.id == "highlight427453" then
          local highlight427453Value = value or 0
          if highlight427453Value == 2 then
            r, g, b = 0, 0, 1
          elseif highlight427453Value == 1 then
            r, g, b = 0, 1, 0
          else
            r, g, b = 1, 0, 0
          end
        else
          r, g, b = rgbFromCount(value)
        end
      elseif field.type == "talents" then
        r, g, b = rgbFromInt(value or 16777215)
      elseif field.type == "number" then
        if type(value) == "table" and value.GetRGB then
          r, g, b = value:GetRGB()
        elseif field.pixelEncoding == "tenths" then
          local tenthsValue = value or 0
          local tenthsOk, tenthsR, tenthsG, tenthsB = pcall(function()
            return rgbFromInt(tenthsValue * 10)
          end)
          if tenthsOk then
            r, g, b = tenthsR, tenthsG, tenthsB
          else
            r, g, b = 0, 0, 0
          end
        elseif field.id == "player_health_pct" and playerHealthColor then
          r, g, b = playerHealthColor:GetRGB()
        elseif field.id == "target_health_pct" and targetHealthColor then
          r, g, b = targetHealthColor:GetRGB()
        elseif field.id:match("^party%d+_health_pct$") and (type(value) == "table" and value.GetRGB) then
          r, g, b = value:GetRGB()
        elseif field.id == "combo_strike" then
          local comboValue = value or 0
          local comboOk, comboR, comboG, comboB = pcall(rgbFromInt, comboValue)
          if comboOk then
            r, g, b = comboR, comboG, comboB
          else
            r, g, b = 0, 0, 0
          end
        else
          local numberValue = value or 0
          local numberOk, numberR, numberG, numberB = pcall(rgbFromInt, numberValue)
          if numberOk then
            r, g, b = numberR, numberG, numberB
          else
            r, g, b = 0, 0, 0
          end
        end
      elseif field.type == "spell" then
        if value then
          r, g, b = 0, 1, 0
        else
          r, g, b = 1, 0, 0
        end
      elseif field.type == "cooldown" then
        -- 【改装】冷却改写成十分位（0.1 秒精度），原来是 math.ceil(秒) 只给整秒。
        --   value == 601 是"读不到 / 未学会"的哨兵，这里换成 (255,255,255) 无值哨兵，
        --   否则 601 会和"还剩 601.0 秒"撞车。
        --   读取端（Permes读取工具）把 cooldown 字段按 value = int24 / 10 解，见 protocol.json
        --   里的 pixelEncoding = "tenths"。
        if value == 601 then
          r, g, b = rgbFromTenths(nil)
        else
          r, g, b = rgbFromTenths(value)
        end
      elseif field.type == "string" then

      end
    end
    local partyHealthSlot = tonumber(field.id:match("^party(%d)_health_pct$"))
    if partyHealthSlot and WowBuddyDev.raidFocusPartyUnavailableLayers then
      local partyUnavailableTexture = WowBuddyDev.raidFocusPartyUnavailableLayers[partyHealthSlot]
      local partyUnavailable = raidPacket and (raidPacket.partyUnavailableByIndex and raidPacket.partyUnavailableByIndex[partyHealthSlot] == true)
      if partyUnavailableTexture then
        partyUnavailableTexture:SetAlpha(partyUnavailable and 1 or 0)
      end
    end
    if pixelBarTextures[fieldIndex] then
      setTextureColor(pixelBarTextures[fieldIndex], r, g, b)
    end
    if debugShown and fieldFrames[fieldIndex] then
      if field.id:match("^placeholder") then
        if fieldFrames[fieldIndex]:IsShown() then
          fieldFrames[fieldIndex]:Hide()
        end
      else
        local debugLineText, suppressLine = describeField(field, value, fieldIndex)
        if suppressLine then
          if fieldFrames[fieldIndex]:IsShown() then
            fieldFrames[fieldIndex]:Hide()
          end
        else
          hiddenCount = hiddenCount + 1
          local debugLineY = -(hiddenCount - 1) * 18
          if fieldFrames[fieldIndex]._vf_lastPointY ~= debugLineY then
            fieldFrames[fieldIndex]:SetPoint("TOPLEFT", WowBuddyDev.debugFrame, "TOPLEFT", 0, debugLineY)
            fieldFrames[fieldIndex]._vf_lastPointY = debugLineY
          end
          local textChangedOk, textChanged = pcall(function()
            return fieldFrames[fieldIndex]._vf_lastText ~= debugLineText
          end)
          if not textChangedOk or textChanged then
            fieldFrames[fieldIndex]:SetText(debugLineText)
            fieldFrames[fieldIndex]._vf_lastText = debugLineText
          end
          if not fieldFrames[fieldIndex]:IsShown() then
            fieldFrames[fieldIndex]:Show()
          end
        end
      end
    end
  end
  if debugShown then
    if WowBuddyDev.debugFrame._lastRows ~= hiddenCount then
      WowBuddyDev.debugFrame._lastRows = hiddenCount
      WowBuddyDev.debugFrame:SetSize(160, math.max(60, hiddenCount * 18 + 10))
    end
  end
  if alertUntilMaster > 0 and GetTime() >= alertUntilMaster then
    if alertMasterText then
      alertMasterText:Hide()
    end
    alertUntilMaster = 0
  end
  if alertUntilBurst > 0 and GetTime() >= alertUntilBurst then
    if alertBurstText then
      alertBurstText:Hide()
    end
    alertUntilBurst = 0
  end
  if alertUntilAoe > 0 and GetTime() >= alertUntilAoe then
    if alertAoeMode then
      alertAoeMode:Hide()
    end
    alertUntilAoe = 0
  end
end)
local stateLogoButton = CreateFrame("Button", "WowBuddyDevStateLogo", UIParent)
WowBuddyDev.stateLogo = stateLogoButton
-- 功能：取状态灯的边长。
-- 入参：无。
-- 出参：24..96 之间的像素数（默认 48）。
local function getLogoSize()
  local logoSizeSetting = WowBuddyDev.DB and tonumber(WowBuddyDev.DB.logoSize) or 48
  return math.min(96, math.max(24, logoSizeSetting))
end
-- 功能：拼状态灯的贴图路径。
-- 入参：state blind/red/normal；isAoe 是否群体模式。
-- 出参：完整贴图路径。
-- 说明：三态 × 两种模式共 6 张贴图，前缀是 PermesLogo。
local function getLogoTexturePath(a127, a29)
  local logoTexturePath = "Interface\\AddOns\\" .. ADDON_NAME .. "\\PermesLogo"
  if a127 == "blind" then
    return logoTexturePath .. (a29 and "BlindR" or "Blind")
  elseif a127 == "red" then
    return logoTexturePath .. (a29 and "RedR" or "Red")
  end
  return logoTexturePath .. (a29 and "NormalR" or "Normal")
end
stateLogoButton:SetSize(getLogoSize(), getLogoSize())
local logoPoint = WowBuddyDev.DB and WowBuddyDev.DB.logoPoint
if logoPoint and (type(logoPoint) == "table" and #logoPoint >= 5) then
  pcall(function()
    stateLogoButton:ClearAllPoints()
    stateLogoButton:SetPoint(unpack(logoPoint))
  end)
else
  stateLogoButton:SetPoint("LEFT", UIParent, "LEFT", 30, 0)
end
stateLogoButton:SetFrameStrata("LOW")
stateLogoButton:SetClampedToScreen(true)
stateLogoButton:EnableMouse(true)
stateLogoButton:SetMovable(true)
stateLogoButton:RegisterForDrag("LeftButton")
stateLogoButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
stateLogoButton:SetScript("OnDragStart", stateLogoButton.StartMoving)
stateLogoButton:SetScript("OnDragStop", function(self3)
  self3:StopMovingOrSizing()
  self3._didDrag = true
  local anchorPoint, anchorRelativeTo, anchorRelativePoint, anchorOffsetX, anchorOffsetY = self3:GetPoint(1)
  if WowBuddyDev.DB then
    WowBuddyDev.DB.logoPoint = { anchorPoint, anchorRelativeTo and anchorRelativeTo:GetName() or nil, anchorRelativePoint, anchorOffsetX, anchorOffsetY }
  end
end)
stateLogoButton:SetScript("OnClick", function(self4, mouseButton)
  if self4._didDrag then
    self4._didDrag = nil
    return
  end
  if mouseButton == "RightButton" then
    toggleBurstSwitch()
  else
    WowBuddyDev.ToggleDock()
  end
end)
local logoTexture = stateLogoButton:CreateTexture(nil, "ARTWORK")
logoTexture:SetAllPoints(stateLogoButton)
stateLogoButton.tex = logoTexture
local dockButtonStrip = CreateFrame("Frame", nil, UIParent)
dockButtonStrip:SetPoint("LEFT", stateLogoButton, "RIGHT", 4, 0)
dockButtonStrip:SetSize(58, 66)
dockButtonStrip:SetFrameStrata("LOW")
-- 功能：造一个统一风格的切换按钮。
-- 入参：offsetY 相对 strip 顶部的纵向偏移；onClick 点击回调。
-- 出参：按钮对象（带 .text 文本串）。
-- 说明：56×19、白底 8×8 贴图做边框、半透明黑底，贴在 dockButtonStrip 上。
local function createDockButton(a128, a210)
  local dockButton = CreateFrame("Button", nil, dockButtonStrip, BackdropTemplateMixin and "BackdropTemplate")
  dockButton:SetSize(56, 19)
  dockButton:SetPoint("TOPLEFT", dockButtonStrip, "TOPLEFT", 0, a128)
  dockButton:SetBackdrop({
    bgFile = "Interface\\Buttons\\WHITE8X8",
    edgeFile = "Interface\\Buttons\\WHITE8X8",
    tile = false,
    tileSize = 0,
    edgeSize = 1,
    insets = { left = 0, right = 0, top = 0, bottom = 0 },
  })
  dockButton:SetBackdropColor(0, 0, 0, .5)
  dockButton:SetBackdropBorderColor(.3, .3, .3, .8)
  dockButton.text = dockButton:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  dockButton.text:SetPoint("CENTER", dockButton, "CENTER", 0, 0)
  dockButton:SetScript("OnClick", a210)
  return dockButton
end
-- 功能：中英二选一。
-- 入参：zh 中文串；en 英文串。
-- 出参：当前客户端语言对应的串。
local function localizeText(a129, a211)
  local locale = GetLocale()
  return (locale == "zhCN" or locale == "zhTW") and a129 or a211
end
local stateLogoToggleButton = createDockButton(0, toggleMasterSwitch)
local burstToggleButton = createDockButton(-23, toggleBurstSwitch)
local aoeToggleButton = createDockButton(-46, toggleAoeMode)
-- 功能：按「整体隐藏 / 隐藏图标 / 隐藏文字」三个开关同步像素条、状态图标和底部按钮条的显示。
-- 入参：无。
-- 出参：无。
-- 说明：存档还没读出来（DB 为空）时按钮条直接隐藏，避免开局闪一下。面板那部分的可见性交给 P07483180.RefreshV2SurfaceVisibility，存在才调，避免面板没加载时报错。
function WowBuddyDev.RefreshAllOverlayVisibility()
  local allOverlaysHidden = WowBuddyDev.DB and WowBuddyDev.DB.allOverlaysHidden
  if pixelBarFrame then
    pixelBarFrame:SetShown(not allOverlaysHidden)
  end
  if WowBuddyDev.RefreshV2SurfaceVisibility then
    WowBuddyDev.RefreshV2SurfaceVisibility()
  end
  if WowBuddyDev.stateLogo and WowBuddyDev.DB then
    WowBuddyDev.stateLogo:SetShown(not allOverlaysHidden and not WowBuddyDev.DB.logoHidden)
  end
  if WowBuddyDev.DB then
    dockButtonStrip:SetShown(not allOverlaysHidden and WowBuddyDev.DB.showLogoText ~= false)
  else
    dockButtonStrip:Hide()
  end
end
-- 功能：切换「整体隐藏」；隐藏时顺带把总开关按灭。
-- 入参：无。
-- 出参：无。
-- 说明：/hide 命令直接挂在这个函数上。隐藏时清总开关是为了让输出同步停下——否则界面看不见了插件还在打，玩家会以为已经停手。
function WowBuddyDev.ToggleAllOverlayVisibility()
  if not WowBuddyDev.DB then
    WowBuddyDev.InitDB()
  end
  WowBuddyDev.DB.allOverlaysHidden = not WowBuddyDev.DB.allOverlaysHidden
  if WowBuddyDev.DB.allOverlaysHidden then
    WowBuddyDev.DB.masterSwitch = false
    WowBuddyDev.UpdateMasterSwitchUI(false)
  end
  WowBuddyDev.RefreshAllOverlayVisibility()
end
SLASH_PERMESHIDE1 = "/hide"
SlashCmdList.PERMESHIDE = WowBuddyDev.ToggleAllOverlayVisibility
-- 功能：按当前开关状态刷新状态图标（贴图、三个按钮的文字和配色）以及全局显示。
-- 入参：无。
-- 出参：无。
-- 说明：图标状态由总开关和爆发开关决定（总开关关=盲眼、爆发开=红、其余=常态），AOE 单体模式再换一套贴图；AOE 按钮只在职业模块允许时才显示。任何开关变化最后都要落到这里才会同步到小地图角标，所以别的刷新入口基本都转发给它。
function WowBuddyDev.RefreshStateLogo()
  if not WowBuddyDev.stateLogo then
    return
  end
  local masterSwitchActive = WowBuddyDev.DB and WowBuddyDev.DB.masterSwitch
  local burstSwitch = WowBuddyDev.DB and WowBuddyDev.DB.burstSwitch
  local isAoeSingle = WowBuddyDev.DB and WowBuddyDev.DB.aoeMode == 1
  local logoState = not masterSwitchActive and "blind" or (burstSwitch and "red" or "normal")
  local logoTexturePathFull = getLogoTexturePath(logoState, isAoeSingle)
  logoTexture:SetTexture(logoTexturePathFull)
  if WowBuddyDev.minimapButton and WowBuddyDev.minimapButton.icon then
    WowBuddyDev.minimapButton.icon:SetTexture(logoTexturePathFull)
  end
  stateLogoToggleButton.text:SetText(localizeText("总开关", "Master"))
  stateLogoToggleButton.text:SetTextColor(masterSwitchActive and .2 or .8, masterSwitchActive and 1 or .2, .2, 1)
  burstToggleButton.text:SetText(localizeText("爆发", "Burst"))
  burstToggleButton.text:SetTextColor(burstSwitch and .2 or .8, burstSwitch and 1 or .2, .2, 1)
  local isAoeSingle2 = WowBuddyDev.DB and WowBuddyDev.DB.aoeMode == 1
  local isAoeGroup = WowBuddyDev.DB and WowBuddyDev.DB.aoeMode == 2
  aoeToggleButton.text:SetText(isAoeGroup and localizeText("群体", "AoE") or localizeText(isAoeSingle2 and "单体" or "自动", isAoeSingle2 and "ST" or "Auto"))
  aoeToggleButton.text:SetTextColor(isAoeSingle2 and 1 or .2, isAoeSingle2 and .2 or 1, .2, 1)
  local showAoeModeButton = WowBuddyDev.classData and WowBuddyDev.classData.showAoeModeButton
  aoeToggleButton:SetShown(not not showAoeModeButton)
  stateLogoButton:SetSize(getLogoSize(), getLogoSize())
  WowBuddyDev.RefreshAllOverlayVisibility()
end
WowBuddyDev.RefreshStateLogo()
local defaultRadius = 220
local minBaselineOffset = 80
local minimapButton
local minimapAngleDeg = defaultRadius
-- 功能：把角度归一化到 0..360。
-- 入参：angle 角度（nil 时沿用当前角度）。
-- 出参：0..360 的小数。
local function normalizeAngle(a130)
  return (tonumber(a130) or defaultRadius) % 360
end
-- 功能：算小地图角标该离中心多远。
-- 入参：无。
-- 出参：半径；小地图拿不到尺寸时返回最小基线值。
local function getMinimapButtonRadius()
  local minimapWidth = Minimap and Minimap:GetWidth() or 0
  local minimapHeight = Minimap and Minimap:GetHeight() or 0
  local minimapMinSide = math.min(minimapWidth or 0, minimapHeight or 0)
  if minimapMinSide <= 0 then
    return minBaselineOffset
  end
  return minimapMinSide / 2 + 10
end
-- 功能：按角度把小地图角标摆到小地图圆周上。
-- 入参：angle 角度（度）。
-- 出参：无。
-- 说明：没有小地图、或角标还没建时直接返回。
local function setMinimapButtonAngle(a131)
  if not minimapButton or not Minimap then
    return
  end
  minimapAngleDeg = normalizeAngle(a131)
  local angleRadians = math.rad(minimapAngleDeg)
  local buttonRadius = getMinimapButtonRadius()
  minimapButton:ClearAllPoints()
  minimapButton:SetPoint("CENTER", Minimap, "CENTER", math.cos(angleRadians) * buttonRadius, math.sin(angleRadians) * buttonRadius)
end
-- 功能：拖动中按光标相对小地图中心的角度实时重摆角标。
-- 入参：无。
-- 出参：无。
-- 说明：光标坐标要先除以小地图有效缩放，才和 GetCenter 在同一坐标系。
local function updateMinimapButtonAngleFromCursor()
  local minimapCenterX, minimapCenterY = Minimap:GetCenter()
  if not minimapCenterX or not minimapCenterY then
    return
  end
  local cursorX, cursorY = GetCursorPosition()
  local effectiveScale = Minimap:GetEffectiveScale()
  if not effectiveScale or effectiveScale <= 0 then
    return
  end
  cursorX = cursorX / effectiveScale
  cursorY = cursorY / effectiveScale
  setMinimapButtonAngle(math.deg(math.atan2(cursorY - minimapCenterY, cursorX - minimapCenterX)))
end
-- 功能：拖动结束后把角标角度落库。
-- 入参：无。
-- 出参：无。
local function persistMinimapButtonAngle()
  if not WowBuddyDev.DB and WowBuddyDev.InitDB then
    WowBuddyDev.InitDB()
  end
  if WowBuddyDev.DB then
    WowBuddyDev.DB.minimapButtonAngle = normalizeAngle(minimapAngleDeg)
  end
end
-- 功能：角标的 tooltip（左键呼出设置 / 右键隐藏全部界面 / 拖动移动角标）。
-- 入参：button 角标按钮。
-- 出参：无。
-- 说明：按角标在屏幕左半还是右半决定 tooltip 朝哪边展开。
local function showMinimapTooltip(a132)
  local minimapCenter = a132:GetCenter()
  local tooltipAnchor = minimapCenter and (minimapCenter < UIParent:GetWidth() / 2 and "ANCHOR_RIGHT") or "ANCHOR_LEFT"
  GameTooltip:SetOwner(a132, tooltipAnchor)
  GameTooltip:SetText("WowBuddyDev", 1, 1, 1)
  GameTooltip:AddLine(WowBuddyDev.L("左键：呼出/隐藏设置"), .82, .82, .82)
  GameTooltip:AddLine(WowBuddyDev.L("右键：显示/隐藏全部界面"), .82, .82, .82)
  GameTooltip:AddLine(WowBuddyDev.L("拖动：移动小地图角标"), .82, .82, .82)
  GameTooltip:Show()
end
if Minimap then
  minimapButton = CreateFrame("Button", "WowBuddyDevMinimapButton", Minimap)
  minimapButton:SetSize(32, 32)
  minimapButton:SetFrameStrata("MEDIUM")
  minimapButton:SetFrameLevel(Minimap:GetFrameLevel() + 8)
  minimapButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  minimapButton:RegisterForDrag("LeftButton")
  minimapButton.icon = minimapButton:CreateTexture(nil, "ARTWORK")
  minimapButton.icon:SetPoint("CENTER")
  minimapButton.icon:SetSize(32, 32)
  minimapButton.icon:SetTexture("Interface\\AddOns\\" .. ADDON_NAME .. "\\PermesIcon")
  local minimapHighlightTexture = minimapButton:CreateTexture(nil, "HIGHLIGHT")
  minimapHighlightTexture:SetPoint("CENTER")
  minimapHighlightTexture:SetSize(42, 42)
  minimapHighlightTexture:SetTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  minimapHighlightTexture:SetBlendMode("ADD")
  minimapButton:SetScript("OnEnter", showMinimapTooltip)
  minimapButton:SetScript("OnLeave", function()
    GameTooltip:Hide()
  end)
  minimapButton:SetScript("OnHide", function(self5)
    self5:SetScript("OnUpdate", nil)
    self5.icon:SetSize(32, 32)
  end)
  minimapButton:SetScript("OnMouseDown", function(self6)
    self6._didDrag = false
    self6.icon:SetSize(30, 30)
  end)
  minimapButton:SetScript("OnMouseUp", function(self7)
    self7.icon:SetSize(32, 32)
  end)
  minimapButton:SetScript("OnDragStart", function(self8)
    self8._didDrag = true
    GameTooltip:Hide()
    self8:SetScript("OnUpdate", updateMinimapButtonAngleFromCursor)
  end)
  minimapButton:SetScript("OnDragStop", function(self9)
    updateMinimapButtonAngleFromCursor()
    self9:SetScript("OnUpdate", nil)
    self9.icon:SetSize(32, 32)
    persistMinimapButtonAngle()
  end)
  minimapButton:SetScript("OnClick", function(self10, clickedButton)
    if self10._didDrag then
      return
    end
    if clickedButton == "RightButton" then
      WowBuddyDev.ToggleAllOverlayVisibility()
    else
      WowBuddyDev.ToggleDock()
    end
  end)
  if type(Minimap.HookScript) == "function" then
    Minimap:HookScript("OnSizeChanged", function()
      setMinimapButtonAngle(minimapAngleDeg)
    end)
  end
  WowBuddyDev.minimapButton = minimapButton
  setMinimapButtonAngle(WowBuddyDev.DB and WowBuddyDev.DB.minimapButtonAngle)
  local loginEventFrame = CreateFrame("Frame")
  loginEventFrame:RegisterEvent("PLAYER_LOGIN")
  loginEventFrame:SetScript("OnEvent", function(self11)
    self11:UnregisterEvent("PLAYER_LOGIN")
    if not WowBuddyDev.DB and WowBuddyDev.InitDB then
      WowBuddyDev.InitDB()
    end
    setMinimapButtonAngle(WowBuddyDev.DB and WowBuddyDev.DB.minimapButtonAngle)
  end)
end
local cvarTuning = {
  { key = "RenderScale", target = 1, name = "渲染倍数", scale = nil },
  { key = "Gamma", target = 1, name = "伽马值", scale = nil },
  { key = "Brightness", target = .5, name = "亮度", scale = 100 },
  { key = "Contrast", target = .5, name = "对比度", scale = 100 },
  { key = "nameplateShowEnemies", target = 1, name = "敌方姓名板", scale = nil },
  { key = "nameplateShowEnemyMinions", target = 1, name = "敌方仆从姓名板", scale = nil },
  { key = "nameplateShowEnemyMinus", target = 1, name = "敌方杂兵姓名板", scale = nil },
  { key = "nameplateShowAll", target = 1, name = "显示所有姓名板", scale = nil },
  { key = "screenEdgeFlash", target = 0, name = "屏幕边缘闪光", scale = nil },
  { key = "doNotFlashLowHealthWarning", target = 1, name = "生命值过低时不闪烁屏幕", scale = nil },
}
-- 功能：读一个 CVar 并转成数字。
-- 入参：name CVar 名。
-- 出参：数字；读不到或空串返回 nil。
local function readCvarNumber(a133)
  local cvarOk, cvarValue = pcall(GetCVar, a133)
  if not cvarOk or cvarValue == nil or cvarValue == "" then
    return nil
  end
  return tonumber(cvarValue)
end
-- 功能：把校准用的游戏设置一次性写成推荐值（渲染倍数、伽马、亮度、对比度、各类姓名板、屏幕边缘闪光）。
-- 入参：无。
-- 出参：无（成功时打一行日志）。
-- 说明：这些设置会直接影响外部读取工具认色块，所以插件主动拉齐。战斗中它们受保护，直接拒绝并提示脱战后重试。
local function applyAdjustmentsTuning()
  if InCombatLockdown() then
    print("|cffff0000[WowBuddyDev]|r 战斗中无法修改受保护的游戏设置，请脱战后重试")
    return
  end
  local adjustedSettingNames = {}
  for index28, v29 in ipairs(cvarTuning) do
    local targetCvarValue = v29.scale and v29.target * v29.scale or v29.target
    local setCvarOk = pcall(SetCVar, v29.key, tostring(targetCvarValue))
    if setCvarOk then
      table.insert(adjustedSettingNames, WowBuddyDev.L(v29.name))
    end
  end
  -- 校准在后台静默完成（用户要求不再播报「已将校准所需设置为推荐值」）。
end
local tuningEventFrame = CreateFrame("Frame")
tuningEventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
tuningEventFrame:SetScript("OnEvent", function()
  applyAdjustmentsTuning()
end)
do
  local uiScaleWarnFrame = CreateFrame("Frame")
  local sawEnterWorld, needRecheckAfterCombat, recheckPending, cvarWriteInFlight = false, false, false, false
  local autoDisabledNotified, manualWarned, combatDeferNotified = false, false, false
  StaticPopupDialogs.PERMES_UI_SCALE_WARNING = { text = "%s", button1 = OKAY, timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3 }
  -- 功能：检查并关闭「使用 UI 缩放」—— UI 缩放会改变色块的实际像素间距，让外部读取失准。
  -- 入参：无。
  -- 出参：无。
  -- 说明：四条路径 —— useUiScale 已是 0 就什么都不做；战斗中只记标记、脱战后复查；能写就写 0 并回读确认，成功提示一次；写不动（或回读不为 0）就弹窗让玩家手动关，避免出现「团队血量 N/A、自动选焦点停止」。
  local function reconcileUiScaleCvar()
    local useUiScaleValue = readCvarNumber("useUiScale")
    if useUiScaleValue == 0 then
      needRecheckAfterCombat = false
      if manualWarned then
        StaticPopup_Hide("PERMES_UI_SCALE_WARNING")
      end
      return
    end
    if InCombatLockdown() then
      needRecheckAfterCombat = true
      if not combatDeferNotified then
        combatDeferNotified = true
        print(WowBuddyDev.L("|cffffff00[WowBuddyDev]|r UI 缩放可能影响色块识别，将在脱战后自动关闭“使用 UI 缩放”。"))
      end
      return
    end
    needRecheckAfterCombat = false
    local writeVerified = false
    if useUiScaleValue == 1 then
      cvarWriteInFlight = true
      local writeOk, writeResult = pcall(SetCVar, "useUiScale", "0")
      writeVerified = writeOk and (writeResult ~= false and readCvarNumber("useUiScale") == 0)
      cvarWriteInFlight = false
    end
    if writeVerified then
      if manualWarned then
        StaticPopup_Hide("PERMES_UI_SCALE_WARNING")
      end
      if not autoDisabledNotified then
        autoDisabledNotified = true
        print(WowBuddyDev.L("|cff00ff88[WowBuddyDev]|r 已自动关闭“使用 UI 缩放”，以避免色块读数异常。界面大小可能变化，原缩放比例已保留。"))
      end
    elseif not manualWarned then
      manualWarned = true
      local warnMessage = WowBuddyDev.L("|cffff8800[WowBuddyDev]|r 无法自动关闭“使用 UI 缩放”。请在游戏设置中搜索“UI 缩放”，手动取消勾选“使用 UI 缩放”；否则可能出现团队血量 N/A、自动选择焦点停止。")
      print(warnMessage)
      StaticPopup_Show("PERMES_UI_SCALE_WARNING", warnMessage)
    end
  end
  -- 功能：把 UI 缩放复查排到下一帧，并做防抖。
  -- 入参：无。
  -- 出参：无。
  -- 说明：CVAR_UPDATE / UI_SCALE_CHANGED / PLAYER_REGEN_ENABLED 可能连着来好几发，这里保证同一时刻只排一次。
  local function scheduleUiScaleRecheck()
    if recheckPending or cvarWriteInFlight or not sawEnterWorld then
      return
    end
    recheckPending = true
    C_Timer.After(0, function()
      recheckPending = false
      reconcileUiScaleCvar()
    end)
  end
  uiScaleWarnFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
  uiScaleWarnFrame:RegisterEvent("CVAR_UPDATE")
  uiScaleWarnFrame:RegisterEvent("UI_SCALE_CHANGED")
  uiScaleWarnFrame:RegisterEvent("PLAYER_REGEN_ENABLED")
  uiScaleWarnFrame:SetScript("OnEvent", function(self12, eventName, a36)
    if eventName == "PLAYER_ENTERING_WORLD" then
      sawEnterWorld = true
    elseif eventName == "CVAR_UPDATE" then
      a36 = type(a36) == "string" and string.lower(a36) or ""
      if a36 ~= "useuiscale" and a36 ~= "uiscale" then
        return
      end
    elseif eventName == "PLAYER_REGEN_ENABLED" and not needRecheckAfterCombat then
      return
    end
    scheduleUiScaleRecheck()
  end)
end
-- 功能：刷新停靠区布局。
-- 入参：无。
-- 出参：无。
-- 说明：目前只是把工作转给 RefreshStateLogo，尺寸和配色都归它管，因此和 RefreshDockButtonColors 完全等价；当前源码里没找到调用点，保留它是给外部或旧调用点当布局刷新入口用。
function WowBuddyDev.UpdateDockLayout()
  WowBuddyDev.RefreshStateLogo()
end
-- 功能：刷新停靠区按钮配色。
-- 入参：无。
-- 出参：无。
-- 说明：同样只转发给 RefreshStateLogo，与 UpdateDockLayout 等价。改名、切专精、切 AOE 模式等多处都在调它，所以入口要一直留着。
function WowBuddyDev.RefreshDockButtonColors()
  WowBuddyDev.RefreshStateLogo()
end
local alertTextFrame = CreateFrame("Frame", nil, UIParent)
alertTextFrame:SetSize(600, 220)
alertTextFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 120)
alertTextFrame:SetFrameStrata("HIGH")
-- 功能：造一行大字提示用的 FontString。
-- 入参：parent 父框；offsetY 相对父框顶部的纵向偏移。
-- 出参：FontString。
-- 说明：字体沿用 P07483180.fontFile（顺手从 GameFontNormal 读一次），56 号带描边和阴影，4K 下也看得清。
local function createAlertFontString(a134, a212)
  local alertFontString = a134:CreateFontString(nil, "OVERLAY")
  WowBuddyDev.fontFile, _, fontFlags = GameFontNormal:GetFont()
  alertFontString:SetFont(WowBuddyDev.fontFile, 56, "OUTLINE")
  alertFontString:SetShadowOffset(2, -2)
  alertFontString:SetShadowColor(0, 0, 0, .8)
  alertFontString:SetPoint("TOP", a134, "TOP", 0, a212)
  return alertFontString
end
alertMasterText = createAlertFontString(alertTextFrame, -10)
alertMasterText:Hide()
alertBurstText = createAlertFontString(alertTextFrame, -70)
alertBurstText:Hide()
alertAoeMode = createAlertFontString(alertTextFrame, -130)
alertAoeMode:Hide()
WowBuddyDev.alertAoeMode = alertAoeMode
-- 功能：总开关的界面反馈：放提示音、弹一行开关提示，再刷新状态图标。
-- 入参：enabled 新的开关状态（真值即开）。
-- 出参：无。
-- 说明：打开总开关时如果处在「整体隐藏」状态，会先把整体隐藏清掉——否则界面刚要显示又被隐藏逻辑盖回去。入参用 not not 归一成布尔再决定放哪个音。
function WowBuddyDev.UpdateMasterSwitchUI(a135)
  if a135 and (WowBuddyDev.DB and WowBuddyDev.DB.allOverlaysHidden) then
    WowBuddyDev.DB.allOverlaysHidden = false
  end
  playToggleSound(not not a135)
  showAlertText(alertMasterText, a135 and "|cff00ff00开|r" or "|cffff0000关|r", 1)
  WowBuddyDev.RefreshStateLogo()
end
-- 功能：爆发开关的界面反馈：放提示音、弹一行「爆发开/爆发关」，再刷新状态图标。
-- 入参：enabled 新的开关状态（真值即开）。
-- 出参：无。
-- 说明：第二个实参传 true，表示用爆发专用的提示音，和总开关的音效区分开。
function WowBuddyDev.UpdateBurstSwitchUI(a136)
  playToggleSound(not not a136, true)
  showAlertText(alertBurstText, a136 and "|cff00ff00爆发开|r" or "|cffff0000爆发关|r", 1)
  WowBuddyDev.RefreshStateLogo()
end
-- 功能：AOE 模式的界面反馈：刷新状态图标，并弹一行当前模式的提示。
-- 入参：aoeMode 模式值（0 自动、1 单体、2 群体）。
-- 出参：无。
-- 说明：取值不在标签表里时按 0（自动）处理，避免把 nil 拼进提示文字。提示框不存在时只刷新图标，不报错。
function WowBuddyDev.UpdateAoeModeUI(a137)
  local validAoeMode = aoeModeLabelTable[a137] and a137 or 0
  WowBuddyDev.RefreshStateLogo()
  if WowBuddyDev.alertAoeMode then
    local aoeModeText = WowBuddyDev.L(aoeModeLabelTable[validAoeMode])
    showAlertText(WowBuddyDev.alertAoeMode, "|cff00ff00" .. aoeModeText .. "|r", 1)
  end
end
-- 功能：按像素条当前的实际屏幕位置，重算每个色块的归一化中心坐标。
-- 入参：无。
-- 出参：true 坐标算好了；false 像素条没建出来或取不到位置。
-- 说明：和 RebuildPixelBars 里那次预算不同，这里读的是 GetLeft/GetTop 的实时值，所以像素条被挪过之后要以这次的结果为准。归一化按当前屏幕尺寸算，换分辨率后必须重算，否则外部读取端会用旧比例去认色块。
function WowBuddyDev.RefreshPixelBarPositions()
  if not pixelBarFrame or not pixelBarTextures or #pixelBarTextures == 0 then
    return false
  end
  local exportScreenWidth = GetScreenWidth()
  local exportScreenHeight = GetScreenHeight()
  local exportFieldCount = #pixelBarTextures
  local barLeft = pixelBarFrame:GetLeft()
  local barTop = pixelBarFrame:GetTop()
  if not barLeft or not barTop then
    return false
  end
  WowBuddyDev._pixelBarPositions = {}
  for i21 = 1, exportFieldCount, 1 do
    local v2452 = barLeft
    local blockTopEdge = barTop - (i21 - 1) * 4
    local normCx = (v2452 + 2) / exportScreenWidth
    local normCy = (exportScreenHeight - (blockTopEdge - 2)) / exportScreenHeight
    WowBuddyDev._pixelBarPositions[i21] = { cx = normCx, cy = normCy }
  end
  return true
end
-- 功能：把每个像素格的理论中心坐标导出到存档 SemrepDB.pixelBarCenters，并附上屏幕尺寸和时间戳。
-- 入参：无。
-- 出参：无（成功时打一行第一个坐标的日志）。
-- 说明：坐标是按「屏幕左上角起、每格 4 像素」的固定规则直接算出来的，不读实际框体位置，所以像素条没建出来时只提示、不写存档，免得外部工具拿着一份空数据。
function WowBuddyDev.ExportPixelBarCenters()
  if not pixelBarTextures or #pixelBarTextures == 0 then
    print("|cffff0000[WowBuddyDev]|r Pixel Bar 未创建，请先激活职业模块")
    return
  end
  local exportScreenWidth2, exportScreenHeight2 = GetScreenWidth(), GetScreenHeight()
  local pixelBarCenterTable = {}
  for i22 = 1, #pixelBarTextures, 1 do
    local centerCx = 2 / exportScreenWidth2
    local centerCy = (2 + (i22 - 1) * 4) / exportScreenHeight2
    table.insert(pixelBarCenterTable, { cx = centerCx, cy = centerCy })
  end
  WowBuddyDevDB = WowBuddyDevDB or {}
  WowBuddyDevDB.pixelBarCenters = pixelBarCenterTable
  WowBuddyDevDB.pixelBarScreenInfo = { screenW = exportScreenWidth2, screenH = exportScreenHeight2, timestamp = time() }
  if pixelBarCenterTable[1] then
    print(string.format("[WowBuddyDev] 第一个 PixelBar 归一化坐标: (%.6f, %.6f)", pixelBarCenterTable[1].cx, pixelBarCenterTable[1].cy))
  end
end
-- 功能：返回像素条的分辨率相关信息（屏幕宽高和色块数量）。
-- 入参：无。
-- 出参：表 { screenW, screenH, count }；像素条没建出来时返回 nil。
-- 说明：只给数量和屏幕尺寸，不吐每个格子的坐标，接收方自己按固定规则推算位置。
function WowBuddyDev.ExportPixelBarsAsRel()
  if not pixelBarTextures or #pixelBarTextures == 0 then
    return nil
  end
  local relScreenWidth = GetScreenWidth()
  local relScreenHeight = GetScreenHeight()
  return { screenW = relScreenWidth, screenH = relScreenHeight, count = #pixelBarTextures }
end

-- ==================== 调试过滤自检（2026-10-10）====================
-- 目的：把「未学技能过滤」的生效情况变成肉眼可见——
--   1) /reload 后聊天框必须出现加载横幅；没有横幅 = 游戏还在跑旧代码。
--   2) /pmslearned 逐技能打印已学判定（base ID + 等级组任一会了就算会），
--      与 describeField 的过滤判据完全同源；某条该隐藏却没隐藏时看这里。
print("|cff00ff88[WowBuddyDev]|r 像素条调试过滤已加载：未学技能不占格/不出行（/pmslearned 查看逐技能判定）")

local function filterLearnedSpellID(vf)
  local sid = tonumber(vf.spellID)
  if not sid and type(vf.id) == "string" then
    for _, pfx in ipairs(specScopedFieldPrefixes) do
      sid = tonumber(vf.id:match(pfx))
      if sid then
        break
      end
    end
  end
  return sid
end

local function filterIsSpellLearned(sid)
  if not (sid and WowBuddyDev.IsSpellKnown) then
    return true
  end
  local baseOK, baseKnown = pcall(WowBuddyDev.IsSpellKnown, sid)
  if baseOK and baseKnown then
    return true
  end
  local aliases = WowBuddyDev.classData and WowBuddyDev.classData.spellReadyAliases
  local aliasList = aliases and aliases[sid]
  if type(aliasList) == "table" then
    for _, aliasID in ipairs(aliasList) do
      local aliasOK, aliasKnown = pcall(WowBuddyDev.IsSpellKnown, aliasID)
      if aliasOK and aliasKnown then
        return true
      end
    end
  end
  return false
end

SLASH_PMSLEARNED1 = "/pmslearned"
SlashCmdList["PMSLEARNED"] = function()
  local fields = {}
  for _, v in ipairs(WowBuddyDev.COMMON_PIXEL_DATA or {}) do
    fields[#fields + 1] = v
  end
  for _, v in ipairs(WowBuddyDev.pixelData or {}) do
    fields[#fields + 1] = v
  end
  local bySpell, order = {}, {}
  for _, vf in ipairs(fields) do
    local sid = filterLearnedSpellID(vf)
    if sid and not bySpell[sid] then
      bySpell[sid] = vf.label or tostring(sid)
      order[#order + 1] = sid
    end
  end
  print("|cff00ff88[WowBuddyDev]|r /pmslearned：技能已学判定（与调试过滤同判据）")
  local shownN, hiddenN = 0, 0
  for _, sid in ipairs(order) do
    if filterIsSpellLearned(sid) then
      shownN = shownN + 1
      print(string.format("  |cff00ff00已学·显示|r %s (%d)", tostring(bySpell[sid]), sid))
    else
      hiddenN = hiddenN + 1
      print(string.format("  |cffff0000未学·隐藏|r %s (%d)", tostring(bySpell[sid]), sid))
    end
  end
  print(string.format("小结：已学 %d 个显示 / 未学 %d 个隐藏", shownN, hiddenN))
end
