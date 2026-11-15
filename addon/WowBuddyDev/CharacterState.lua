-- 在原色条右侧发布角色和地图读数，原色格的顺序保持不变。
local addon = WowBuddyDev
local textures = {}
local sessionTextures = {}
local travelIdentityTextures = {}
local progressTextures = {}
local mobTextures = {}
local vendorTextures = {}
local repairTextures = {}
local questTextures = {}
local questDialogTextures = {}
local deathTextures = {}
local navigationTextures = {}
local pullTextures = {}
local targetTextures = {}
local wandTextures = {}
local retargetTextures = {}
local discardTextures = {}
local sightTextures = {}
local precisePositionTextures = {}
local elevationTextures = {}
local taxiTextures = {}
local targetRejectionTextures = {}
local castFeedbackTextures = {}
local combatFacingTextures = {}
local novaSpacingTextures = {}
local nextUpdate = 0
local signature = 0x57424E
local sessionSignature = 0x574245
local travelIdentitySignature = 0x574255
local progressSignature = 0x574249
local mobSignature = 0x574251
local vendorSignature = 0x574273
local repairSignature = 0x574272
local questSignature = 0x574276
local questDialogSignature = 0x574277
local deathSignature = 0x574244
local navigationSignature = 0x57424D
local pullSignature = 0x574250
local targetSignature = 0x574254
local targetWorldSignature = 0x574248
local wandSignature = 0x574257
local retargetSignature = 0x574252
local discardSignature = 0x574243
local sightSignature = 0x574253
local precisePositionSignature = 0x574246
local elevationSignature = 0x574274
local taxiSignature = 0x574275
local targetRejectionSignature = 0x57424B
local castFeedbackSignature = 0x574256
local combatFacingSignature = 0x574259
local combatFacingActionSignature = 0x57425A
local novaSpacingSignature = 0x574247
local novaSpacingEventSignature = 0x57424C
local novaSpacingBlockedSignature = 0x57424F
local discardAction = "discard_unreachable_target"
local discardMacro = "/cleartarget [nocombat,nochanneling,harm,nodead]"
local discardKey, discardIndex
local lootTargetAction = "restore_loot_target"
local function lootTargetMacro(name)
  local exact = name and "/targetexact [noexists] " .. name .. "\n" or ""
  return "/stopmacro [combat][channeling][exists]\n/targetlasttarget\n"
    .. "/cleartarget [exists,nodead]\n" .. exact
    .. "/targetlastenemy [noexists]\n/cleartarget [exists,nodead]"
end
local lootTargetKey, lootTargetIndex, combatLootTarget
local questClearAction, questClearMacro = "clear_quest_corpse_target", "/cleartarget [nocombat,dead]"
local questClearKey, questClearIndex
local vendorAction = "select_supply_vendor"
local vendorKey, vendorIndex, vendorMacro
local groveVendorAction = "select_grove_supply_vendor"
local groveVendorNames = { zhCN = "提亚尼", zhTW = "提亞尼", enUS = "Tiyani", enGB = "Tiyani" }
local groveVendorKey, groveVendorIndex, groveVendorMacro
local repairVendorAction = "select_auberdine_repair_vendor"
local repairVendorNames = { zhCN = "艾丽萨·钢拳", enUS = "Elisa Steelhand", enGB = "Elisa Steelhand" }
local repairVendorKey, repairVendorIndex, repairVendorMacro
local taxiAction = "select_ruttheran_flight_master"
local taxiMasterNames = { zhCN = "维斯派塔斯", enUS = "Vesprystus", enGB = "Vesprystus" }
local taxiKey, taxiIndex, taxiMacro
-- 不使用原色条的洋红定位色 FF00FF。
local checksumMod = 0xFEFFFD
local sessionWords
local travelIdentityWords
local missingPosition = 0xFFFFFF
local factionCode = { Alliance = 1, Horde = 2 }
local corpseMapID, corpseX, corpseY
local deathSequence = 0
local navigationSequence = 0
local targetRevision = 0
local arrowKeys = { UP = 0x26, LEFT = 0x25, RIGHT = 0x27, DOWN = 0x28 }
local targetEvents = CreateFrame("Frame")
local namePlateUnits = {}
targetEvents:RegisterEvent("PLAYER_TARGET_CHANGED")
targetEvents:RegisterEvent("NAME_PLATE_UNIT_ADDED")
targetEvents:RegisterEvent("NAME_PLATE_UNIT_REMOVED")
targetEvents:RegisterEvent("PLAYER_ENTERING_WORLD")

local function readable(value)
  return not issecretvalue or not issecretvalue(value)
end

local function read(func, ...)
  if type(func) ~= "function" then return nil end
  local ok, value = pcall(func, ...)
  if ok and readable(value) then return value end
end

local function unitGuid(unit)
  local guid = read(UnitGUID, unit)
  if type(guid) == "string" and guid ~= "" then return guid end
end

targetEvents:SetScript("OnEvent", function(_, event, unit)
  if event == "PLAYER_TARGET_CHANGED" then
    targetRevision = (targetRevision + 1) % 65521
    if combatLootTarget then
      local exists = read(UnitExists, "target")
      if exists == false then
        combatLootTarget.clearedRevision = targetRevision
        combatLootTarget.clearedAt = GetTime()
      elseif (exists ~= true or unitGuid("target") ~= combatLootTarget.guid)
          and (not combatLootTarget.requested or GetTime() - combatLootTarget.requested > 2) then
        -- 安全重选宏可能先切到上一个目标再清除。短时保留原 GUID，拾取仍要求逐项验证。
        combatLootTarget = nil
      end
    end
  elseif event == "PLAYER_ENTERING_WORLD" then
    namePlateUnits = {}
    travelIdentityWords = nil
    combatLootTarget = nil
  elseif readable(unit) and type(unit) == "string" then
    namePlateUnits[unit] = event == "NAME_PLATE_UNIT_ADDED" or nil
  end
end)

local targetCast, sightErrorAt, targetFailureAt, lastSightFailure
local sightFailures, sightUntil = 0, 0

local function clearSightFeedback()
  targetCast, sightErrorAt, targetFailureAt, lastSightFailure = nil, nil, nil, nil
  sightFailures, sightUntil = 0, 0
end

local function pairSightFailure(now)
  if not sightErrorAt or not targetFailureAt or math.abs(sightErrorAt - targetFailureAt) > 0.6 then return end
  sightErrorAt, targetFailureAt = nil, nil
  if not lastSightFailure or now - lastSightFailure > 6 then sightFailures = 0 end
  sightFailures, lastSightFailure = sightFailures + 1, now
  if sightFailures >= 2 then sightUntil = now + 8 end
end

local function isSightTarget()
  return read(UnitAffectingCombat, "player") == false and read(UnitCanAttack, "player", "target") == true
    and read(UnitIsDeadOrGhost, "target") == false and read(UnitPlayerControlled, "target") == false
end

function addon.RecordTargetSightError()
  if not isSightTarget() then return end
  local now = GetTime()
  sightErrorAt = now
  pairSightFailure(now)
end

local sightEvents = CreateFrame("Frame")
sightEvents:RegisterEvent("PLAYER_TARGET_CHANGED")
sightEvents:RegisterEvent("PLAYER_ENTERING_WORLD")
sightEvents:RegisterEvent("PLAYER_REGEN_DISABLED")
sightEvents:RegisterUnitEvent("UNIT_SPELLCAST_SENT", "player")
sightEvents:RegisterUnitEvent("UNIT_SPELLCAST_FAILED", "player")
sightEvents:RegisterUnitEvent("UNIT_SPELLCAST_SUCCEEDED", "player")
sightEvents:SetScript("OnEvent", function(_, event, unit, arg2, arg3, arg4)
  if event == "PLAYER_TARGET_CHANGED" or event == "PLAYER_ENTERING_WORLD" or event == "PLAYER_REGEN_DISABLED" then
    clearSightFeedback()
  elseif readable(unit) and unit == "player" then
    if event == "UNIT_SPELLCAST_SENT" then
      targetCast, targetFailureAt = nil, nil
      if isSightTarget() and readable(arg2) and type(arg2) == "string" and arg2 ~= ""
          and arg2 == read(UnitName, "target") and readable(arg3) and type(arg3) == "string" and arg3 ~= ""
          and readable(arg4) and type(arg4) == "number" then
        targetCast = { arg3, arg4, GetTime() }
      end
    elseif targetCast and readable(arg2) and readable(arg3) and arg2 == targetCast[1] and arg3 == targetCast[2] then
      local now = GetTime()
      local castAt = targetCast[3]
      targetCast = nil
      if event == "UNIT_SPELLCAST_SUCCEEDED" then
        clearSightFeedback()
      elseif now - castAt <= 8 and isSightTarget() then
        targetFailureAt = now
        if sightErrorAt and sightErrorAt < castAt then sightErrorAt = nil end
        pairSightFailure(now)
      end
    end
  end
end)

local function integer(value, minValue, maxValue)
  return type(value) == "number" and value >= minValue and value <= maxValue and value % 1 == 0
end

local function lifeState()
  if read(UnitExists, "player") ~= true then return 0 end
  local dead = read(UnitIsDeadOrGhost, "player")
  if dead == false then return 1 end
  if dead ~= true then return 0 end
  local ghost = read(UnitIsGhost, "player")
  if ghost == true then return 3 end
  return ghost == false and 2 or 0
end

local function encodePosition(x, y)
  if not (readable(x) and readable(y) and type(x) == "number" and type(y) == "number"
      and x >= 0 and x <= 1 and y >= 0 and y <= 1) or (x == 0 and y == 0) then
    return missingPosition, missingPosition
  end
  return math.floor(x * 10000 + 0.5), math.floor(y * 10000 + 0.5)
end

local function vectorPosition(position)
  if not position then return missingPosition, missingPosition end
  local x, y = position:GetXY()
  local px, py = encodePosition(x, y)
  return px, py, x, y
end

local function zoneName(mapID)
  local info = read(C_Map.GetMapInfo, mapID)
  local zoneType = Enum and Enum.UIMapType and Enum.UIMapType.Zone or 3
  if type(info) ~= "table" or not readable(info.mapType) or info.mapType ~= zoneType then return "" end
  local name = info.name
  if not readable(name) or type(name) ~= "string" or #name > 72 or name:find("[%z\1-\31\127\255]") then
    return ""
  end
  return name
end

local nextQuestRead, questMap, questPin = 0
local turnedInID, turnedInGeneration = 0, 0
local questEvents = CreateFrame("Frame")
questEvents:RegisterEvent("QUEST_TURNED_IN")
questEvents:SetScript("OnEvent", function(_, _, questID)
  if integer(questID, 1, checksumMod - 1) then
    turnedInID, turnedInGeneration = questID, (turnedInGeneration + 1) % 65536
    nextQuestRead = 0
  end
end)

local function findTurnInPin(mapID, x, y)
  local log = C_QuestLog
  if type(log) ~= "table" then return end
  local count = read(log.GetNumQuestLogEntries)
  if type(count) ~= "number" or count < 1 then return end

  local ready, maps, seen = {}, {}, {}
  local function addMap(id)
    if not readable(id) or type(id) ~= "number" or id <= 0 or id >= checksumMod or seen[id] then return end
    if zoneName(id) == "" then return end
    seen[id] = true
    maps[#maps + 1] = id
  end
  addMap(mapID)
  if WorldMapFrame then addMap(read(WorldMapFrame.GetMapID, WorldMapFrame)) end
  for index = 1, math.min(count, 256) do
    local id = read(log.GetQuestIDForLogIndex, index)
    if type(id) == "number" and id > 0 and id < checksumMod and read(log.ReadyForTurnIn, id) == true then
      ready[id] = true
      addMap(read(log.GetNextWaypoint, id))
    end
  end
  if not next(ready) then return end

  for _, id in ipairs(maps) do
    local pins = read(log.GetQuestsOnMap, id)
    if type(pins) == "table" then
      local best, score
      for _, pin in ipairs(pins) do
        local questID = pin.questID
        if readable(questID) and ready[questID] and readable(pin.isMapIndicatorQuest)
            and not pin.isMapIndicatorQuest then
          local px, py = encodePosition(pin.x, pin.y)
          if px > 0 and px < 10000 and py > 0 and py < 10000 then
            local distance = id == mapID and x < 10000 and y < 10000 and (px - x)^2 + (py - y)^2 or 0
            if not best or distance < score or (distance == score and questID < best[1]) then
              best, score = { questID, id, px, py }, distance
            end
          end
        end
      end
      if best then return best end
    end
  end
end

local function appendChecksum(words)
  local check = 0
  for _, word in ipairs(words) do check = (check * 31 + word) % checksumMod end
  words[#words + 1] = check
  return words
end

local function collectQuestPin(now, mapID, x, y)
  -- 地图切换后清除上一张地图的读数，任务日志最多每秒查一次。
  if now >= nextQuestRead or mapID ~= questMap then
    nextQuestRead, questMap, questPin = now + 1, mapID, nil
    questPin = findTurnInPin(mapID, x, y)
  end
  if not questPin or type(C_QuestLog) ~= "table"
      or read(C_QuestLog.ReadyForTurnIn, questPin[1]) ~= true then return end
  return appendChecksum({ questSignature, deathSequence, questPin[1], questPin[2], questPin[3], questPin[4] })
end

local function travelIdentity()
  local guid = read(UnitGUID, "player")
  if type(guid) ~= "string" or guid == "" then return end
  local first, second = 0, 0
  for index = 1, #guid do
    local value = guid:byte(index)
    first = (first * 131 + value) % checksumMod
    second = (second * 137 + value) % checksumMod
  end
  return appendChecksum({ travelIdentitySignature, sessionWords[2], first, second })
end

local combatXpNotices, lastCombatXpAt
local progressEvents = CreateFrame("Frame")
if not (C_EventUtils and C_EventUtils.IsEventValid)
    or read(C_EventUtils.IsEventValid, "CHAT_MSG_COMBAT_XP_GAIN") == true then
  if pcall(progressEvents.RegisterEvent, progressEvents, "CHAT_MSG_COMBAT_XP_GAIN") then
    combatXpNotices = 0
    progressEvents:SetScript("OnEvent", function()
      combatXpNotices = (combatXpNotices + 1) % 65536
      lastCombatXpAt = GetTime()
    end)
  end
end

local function collectProgress()
  local level = read(UnitLevel, "player")
  if not integer(level, 1, 255) then return end
  local current, maximum = read(UnitXP, "player"), read(UnitXPMax, "player")
  if not integer(maximum, 1, checksumMod - 1) or not integer(current, 0, maximum) then
    if combatXpNotices == nil then return end
    current, maximum = missingPosition, missingPosition
  end
  return appendChecksum({ progressSignature, sessionWords[2], level, current, maximum,
    combatXpNotices or missingPosition })
end

-- 读条反馈独立于 Windows 发键与公共冷却。记录一次游戏施法实际出现过的阶段。
local castEvents = CreateFrame("Frame")
local castStages = {
  UNIT_SPELLCAST_SENT = 1, UNIT_SPELLCAST_START = 2, UNIT_SPELLCAST_SUCCEEDED = 4,
  UNIT_SPELLCAST_FAILED = 8, UNIT_SPELLCAST_INTERRUPTED = 16,
}
local castSequence = 0
local castFeedback
local castErrorWindow = 0.35
local castErrorKinds = {
  SPELL_FAILED_UNIT_NOT_INFRONT = 1, SPELL_FAILED_NOT_INFRONT = 1, ERR_BADATTACKFACING = 1,
  SPELL_FAILED_LINE_OF_SIGHT = 2, ERR_LINE_OF_SIGHT = 2,
  SPELL_FAILED_OUT_OF_RANGE = 3, ERR_SPELL_OUT_OF_RANGE = 3, ERR_OUT_OF_RANGE = 3,
  SPELL_FAILED_MOVING = 4, ERR_CANT_DO_WHILE_MOVING = 4,
  SPELL_FAILED_NO_POWER = 5, ERR_OUT_OF_MANA = 5,
  SPELL_FAILED_NOT_READY = 6, ERR_SPELL_COOLDOWN = 6, ERR_ABILITY_COOLDOWN = 6,
}

local function recordCastError(errorType, message)
  local cast = castFeedback
  if not cast or not cast.sentAt or not readable(errorType) or not integer(errorType, 1, 65535) then return end
  if math.floor(cast.stages / 4) % 2 == 1 or math.floor(cast.stages / 16) % 2 == 1 then return end
  local now = GetTime()
  if cast.failedAt and now - cast.failedAt > castErrorWindow then return end
  local name = read(GetGameMessageInfo, errorType)
  local kind = castErrorKinds[name]
  if not kind and readable(message) and type(message) == "string" and message ~= "" then
    for key, value in pairs(castErrorKinds) do
      local localized = rawget(_G, key)
      if readable(localized) and localized == message then
        kind = value
        break
      end
    end
  end
  if not kind and (type(name) ~= "string" or not (name:find("^SPELL_FAILED_") or name:find("^ERR_SPELL_"))) then
    return
  end
  local reason = (kind or 0) * 65536 + errorType
  -- 同一失败附近出现不同原因时保留阶段，省略无法归属的原因。
  if cast.errorAt and math.abs(cast.errorAt - now) <= castErrorWindow and cast.reason ~= reason then
    reason = 0
  end
  cast.errorAt, cast.reason = now, reason
end

local function currentTargetAction(spell)
  local data = addon.classData
  if not data or not data.ACTION_TO_KEY then return end
  for action, key in pairs(data.ACTION_TO_KEY) do
    local base = tonumber(action:match("^spell_(%d+)$"))
    if base then
      local same = base == spell
      for _, rank in ipairs((data.spellReadyAliases or {})[base] or {}) do
        if rank == spell then same = true end
      end
      if same then
        local registered = read(addon.GetClassBindingAction, action, key) or action
        local body = read(addon.GetBoundMacro, registered)
        local button = read(addon.GetSecureButton, registered)
        local name = button and read(button.GetName, button)
        -- 只接受已绑定的单条当前敌对目标宏。焦点、鼠标指向及多条宏不可据此推断。
        if name and read(GetBindingAction, key, true) == "CLICK " .. name .. ":LeftButton"
            and body and body:match("^/cast %[harm,nodead,nochanneling%] [^;\r\n]+$") then
          return base
        end
      end
    end
  end
end

local function isFrostNova(spell)
  local aliases = addon.classData and addon.classData.cooldownEventAliases
  return spell == 122 or (aliases and aliases[spell] == 122)
end

local function recordNovaAuraEvent()
  local cast = castFeedback
  if not cast or not cast.novaPlayerGuid or not cast.novaTargetGuid
      or cast.novaTargetRevision ~= targetRevision then return end
  local now = GetTime()
  if now - cast.sentAt > 2 then return end
  local ok, _, kind, _, source, _, _, _, target, _, _, _, spell = pcall(CombatLogGetCurrentEventInfo)
  if not ok or not readable(kind) or not readable(target) or target ~= cast.novaTargetGuid then return end
  if kind == "UNIT_DIED" then
    cast.novaAuraRemoved = true
  elseif readable(spell) and integer(spell, 1, checksumMod - 1) and isFrostNova(spell) then
    if kind == "SPELL_AURA_REMOVED" or kind == "SPELL_AURA_BROKEN" or kind == "SPELL_AURA_BROKEN_SPELL" then
      cast.novaAuraRemoved = true
    elseif (kind == "SPELL_AURA_APPLIED" or kind == "SPELL_AURA_REFRESH")
        and readable(source) and source == cast.novaPlayerGuid then
      cast.novaAuraAppliedAt = now
    end
  end
end

castEvents:RegisterEvent("PLAYER_ENTERING_WORLD")
castEvents:RegisterEvent("UI_ERROR_MESSAGE")
if type(CombatLogGetCurrentEventInfo) == "function"
    and (not (C_EventUtils and C_EventUtils.IsEventValid)
      or read(C_EventUtils.IsEventValid, "COMBAT_LOG_EVENT_UNFILTERED") == true) then
  pcall(castEvents.RegisterEvent, castEvents, "COMBAT_LOG_EVENT_UNFILTERED")
end
for event in pairs(castStages) do castEvents:RegisterUnitEvent(event, "player") end
castEvents:SetScript("OnEvent", function(_, event, unit, arg2, arg3, arg4)
  if event == "PLAYER_ENTERING_WORLD" then
    castFeedback = nil
    return
  end
  if event == "UI_ERROR_MESSAGE" then
    recordCastError(unit, arg2)
    return
  end
  if event == "COMBAT_LOG_EVENT_UNFILTERED" then
    recordNovaAuraEvent()
    return
  end
  if not readable(unit) or unit ~= "player" then return end
  local sent = event == "UNIT_SPELLCAST_SENT"
  local guid, spell = arg2, arg3
  if sent then guid, spell = arg3, arg4 end
  if not readable(guid) or type(guid) ~= "string" or guid == ""
      or not readable(spell) or not integer(spell, 1, checksumMod - 1) then return end
  if not castFeedback or castFeedback.guid ~= guid or castFeedback.spell ~= spell then
    castSequence = (castSequence + 1) % 65521
    castFeedback = { guid = guid, spell = spell, stages = 0 }
  end
  local stage = castStages[event]
  if math.floor(castFeedback.stages / stage) % 2 == 0 then
    castFeedback.stages = castFeedback.stages + stage
    if sent then
      castFeedback.sentAt = GetTime()
      if read(UnitCanAttack, "player", "target") == true then
        if isFrostNova(spell) then
          castFeedback.novaTargetRevision = targetRevision
          castFeedback.novaPlayerGuid = unitGuid("player")
          castFeedback.novaTargetGuid = unitGuid("target")
        end
        local eventName = readable(arg2) and type(arg2) == "string" and arg2 ~= "" and arg2 or nil
        local currentName = read(UnitName, "target")
        if eventName and currentName and currentName ~= "" then
          if eventName == currentName then castFeedback.targetRevision = targetRevision end
        else
          castFeedback.targetRevision = targetRevision
          castFeedback.targetNameUnverified = true
        end
      end
    elseif event == "UNIT_SPELLCAST_FAILED" then
      castFeedback.failedAt = GetTime()
    end
  end
end)

local function collect()
  local life = lifeState()
  local outdoors = read(IsInInstance) == false
  local state = life
  if outdoors then state = state + 4 end
  if read(GetLocale) == "zhCN" then state = state + 8 end
  local level = read(UnitLevel, "player")
  if not integer(level, 1, 255) then level = 0 end
  local faction = factionCode[read(UnitFactionGroup, "player")] or 0
  local mapID = read(C_Map.GetBestMapForUnit, "player")
  if not integer(mapID, 1, 0xFEFFFF) then mapID = 0 end
  local x, y = missingPosition, missingPosition
  local rawX, rawY
  local name = ""
  if mapID ~= 0 then
    local ok, mapX, mapY, vectorX, vectorY = pcall(vectorPosition, read(C_Map.GetPlayerMapPosition, mapID, "player"))
    if ok then x, y, rawX, rawY = mapX, mapY, vectorX, vectorY end
    local nameOK, result = pcall(zoneName, mapID)
    if nameOK then name = result end
  end
  local words = { signature, state * 65536 + faction * 256 + level, mapID, x, y, #name }
  for offset = 1, #name, 3 do
    local r, g, b = name:byte(offset, offset + 2)
    words[#words + 1] = r * 65536 + (g or 0) * 256 + (b or 0)
  end
  return appendChecksum(words), life, mapID, outdoors, x, y, #name > 0, rawX, rawY
end

local function keyboardAvailable()
  if not addon.DB or addon.DB.masterSwitch ~= true then return false end
  local focusOK, focus = pcall(GetCurrentKeyBoardFocus)
  return focusOK and readable(focus) and focus == nil
end

local function mousePointsAt(button)
  local focus
  if type(GetMouseFoci) == "function" then
    local foci = read(GetMouseFoci)
    if type(foci) == "table" then focus = foci[1] end
  else
    focus = read(GetMouseFocus)
  end
  for _ = 1, 5 do
    if not readable(focus) or not focus then return false end
    if focus == button then return true end
    focus = read(focus.GetParent, focus)
  end
  return false
end

local function popupPosition(which)
  if read(UnitAffectingCombat, "player") ~= false or not keyboardAvailable() then return 1 end
  if type(StaticPopup_FindVisible) ~= "function" then return 4 end
  local ok, dialog = pcall(StaticPopup_FindVisible, which)
  if not ok or not readable(dialog) then return 4 end
  if not dialog or dialog.which ~= which or not dialog:IsVisible() then return 2 end
  -- 与游戏弹窗一样，以当前按钮是否可用为准。释放后是否可复活是另一项检查。
  local button = dialog.GetButton1 and dialog:GetButton1() or dialog:GetButton(1)
  if not button or not button:IsVisible() or not button:IsEnabled() then return 3 end
  local x, y = button:GetCenter()
  if not readable(x) or not readable(y) or type(x) ~= "number" or type(y) ~= "number" then return 4 end
  local scale = button:GetEffectiveScale() / UIParent:GetEffectiveScale()
  local px, py = encodePosition(x * scale / UIParent:GetWidth(), 1 - y * scale / UIParent:GetHeight())
  if px == missingPosition then return 4 end
  local hoverOK, hovered = pcall(mousePointsAt, button)
  return 5, px, py, hoverOK and hovered
end

local function corpsePosition(mapID)
  if mapID == 0 or not C_DeathInfo then return end
  local ok, px, py, x, y = pcall(vectorPosition, read(C_DeathInfo.GetCorpseMapPosition, mapID))
  if ok and px ~= missingPosition then return px, py, x, y end
end

local function corpseZoneFromContinent(mapID)
  if type(C_Map.GetMapInfoAtPosition) ~= "function" then return end
  local current = read(C_Map.GetMapInfo, mapID)
  local parentID = type(current) == "table" and current.parentMapID
  if not readable(parentID) or not integer(parentID, 1, 0xFEFFFF) then return end
  local parent = read(C_Map.GetMapInfo, parentID)
  local mapTypes = Enum and Enum.UIMapType
  local continentType = mapTypes and mapTypes.Continent or 2
  if type(parent) ~= "table" or not readable(parent.mapType) or parent.mapType ~= continentType then return end
  local _, _, x, y = corpsePosition(parentID)
  if not x then return end
  local zone = read(C_Map.GetMapInfoAtPosition, parentID, x, y)
  local zoneType = mapTypes and mapTypes.Zone or 3
  if type(zone) == "table" and readable(zone.mapType) and zone.mapType == zoneType
      and readable(zone.parentMapID) and zone.parentMapID == parentID
      and readable(zone.mapID) and integer(zone.mapID, 1, 0xFEFFFF) then
    return zone.mapID
  end
end

local function collectDeath(life, mapID, outdoors, x, y, isZone)
  if life == 1 then corpseMapID, corpseX, corpseY = nil, nil, nil end
  if life == 2 and outdoors and isZone and not corpseX then
    corpseMapID = mapID
    if x ~= missingPosition then corpseX, corpseY = x, y end
  end
  local phase = life == 0 and 3 or life - 1
  local which = life == 2 and "DEATH" or life == 3 and "RECOVER_CORPSE"
  local bx, by, hovered, popup = missingPosition, missingPosition, false, 0
  local corpseID, cx, cy, estimated = 0, missingPosition, missingPosition, false
  if which and outdoors then
    local ok, status, px, py, over = pcall(popupPosition, which)
    popup = ok and status or 4
    if popup == 5 then bx, by, hovered = px, py, over end
    -- 只看到灵魂时，墓地地图可能也能投影相邻区域的尸体坐标。
    local discoveredMap = life == 3 and isZone and not corpseMapID and corpseZoneFromContinent(mapID)
    local selectedMap = corpseMapID or discoveredMap or mapID
    local px, py = corpsePosition(selectedMap)
    if px then
      corpseID, cx, cy = selectedMap, px, py
      if discoveredMap then corpseMapID = discoveredMap end
    end
    if corpseID == 0 and corpseX then
      corpseID, cx, cy, estimated = corpseMapID, corpseX, corpseY, true
    end
  end
  deathSequence = (deathSequence + 1) % 256
  local flags = popup * 2 + (hovered and 1 or 0) + (estimated and 16 or 0)
  return appendChecksum({ deathSignature, phase * 65536 + deathSequence * 256 + flags,
    bx, by, corpseID, cx, cy })
end

local function bindingVirtualKey(key, functionKeys)
  if not readable(key) or type(key) ~= "string" then return end
  if functionKeys then
    local number = tonumber(key:match("^F(%d+)$"))
    if number and number >= 1 and number <= 12 then return 0x6F + number end
  end
  return arrowKeys[key] or (key:match("^[A-Z]$") and key:byte())
end

local function actionKey(action)
  local ok, primary, secondary = pcall(GetBindingKey, action)
  if not ok then return end
  local function vk(key)
    if not readable(key) or type(key) ~= "string" or read(GetBindingAction, key, true) ~= action then return end
    return bindingVirtualKey(key, action == "INTERACTTARGET" or action == "TARGETLASTTARGET")
      or (action == "TARGETNEARESTENEMY" and key == "TAB" and 9) or nil
  end
  return vk(primary) or vk(secondary)
end

local lootGeneration, lootOpen = 0, false
local targetWorldDirection
local lootEvents = CreateFrame("Frame")
lootEvents:RegisterEvent("LOOT_OPENED")
lootEvents:RegisterEvent("LOOT_CLOSED")
lootEvents:SetScript("OnEvent", function(_, event)
  lootOpen = event == "LOOT_OPENED"
  if not lootOpen then lootGeneration = (lootGeneration + 1) % 65521 end
end)

local function autoLootEnabled()
  return read(C_CVar and C_CVar.GetCVarBool or GetCVarBool, "autoLootDefault") == true
end

function addon.HasInterruptedLootTarget()
  local tracked = combatLootTarget
  if not tracked or not tracked.requested or GetTime() - tracked.requested > 15 then return false end
  local exists = read(UnitExists, "target")
  if exists == false then return tracked.clearedRevision == targetRevision end
  if exists ~= true then return false end
  local dead = read(UnitIsDeadOrGhost, "target")
  local guid = unitGuid("target")
  if dead == false or (guid and guid ~= tracked.guid) then return false end
  return (dead == true and guid == tracked.guid) or tracked.corpseRevision == targetRevision
end

local function restoreLootKey(tracked)
  local native = actionKey("TARGETLASTTARGET")
  local button = lootTargetKey and addon.GetSecureButton(lootTargetAction)
  if button and button:GetAttribute("type") == "macro" and read(GetBindingAction, lootTargetKey, false) == ""
      and read(GetBindingAction, lootTargetKey, true) == "CLICK " .. button:GetName() .. ":LeftButton" then
    local macro = lootTargetMacro(tracked.name)
    if button:GetAttribute("macrotext") ~= macro
        and (read(InCombatLockdown) ~= false
          or read(addon.CreateSecureButton, lootTargetAction, lootTargetKey, macro) ~= true) then
      return native
    end
    return 0x100 + lootTargetIndex
  end
  return native
end

local function targetIsTargetingUs()
  return read(UnitIsUnit, "targettarget", "player") == true
    or read(UnitIsUnit, "targettarget", "pet") == true
end

local function collectMob()
  local state, key, bearing, lootBlock, lootID = 0, 0, 0, 0, 0
  local exists = read(UnitExists, "target")
  local combat = read(UnitAffectingCombat, "player")
  local now = GetTime()
  local tracked = combatLootTarget
  local reacquired, softCorpse = false, false
  if exists == true then
    local dead = read(UnitIsDeadOrGhost, "target")
    local tap = read(UnitIsTapDenied, "target")
    local npc = read(UnitIsPlayer, "target") == false and read(UnitPlayerControlled, "target") == false
    if dead == false then
      local fighting = read(UnitAffectingCombat, "target") == true
      local ours = read(UnitThreatSituation, "player", "target")
        or read(UnitThreatSituation, "pet", "target")
      local ownCombat = type(ours) == "number" or targetIsTargetingUs()
      state = npc and tap == false and (not fighting or ownCombat)
        and read(UnitCanAttack, "player", "target") == true and 1 or 2
      if combat == true then
        local guid = state == 1 and unitGuid("target")
        if guid then
          if not tracked or tracked.guid ~= guid or tracked.clearedRevision then
            tracked = {guid = guid, xp = combatXpNotices}
          end
          if not tracked.name then
            local name = read(UnitName, "target")
            if type(name) == "string" and #name > 0 and #name <= 90 and not name:find("[%c%[%];|]") then
              tracked.name = name
            end
          end
          tracked.seen = now
          combatLootTarget = tracked
        else
          combatLootTarget = nil
        end
      end
    elseif dead == true then
      local guid = unitGuid("target")
      reacquired = guid ~= nil and tracked ~= nil and guid == tracked.guid and tracked.requested
        and now - tracked.requested <= 15 or false
      if reacquired then
        tracked.corpseRevision = targetRevision
        lootBlock = tap == true and 4 or 5
      end
      if guid and (npc and tap == false or reacquired and tap ~= true) and type(CanLootUnit) == "function" then
        state = 5 -- 当前尸体的掉落状态尚未确认。
        local ok, hasLoot, canLoot = pcall(CanLootUnit, guid)
        if ok and readable(hasLoot) and readable(canLoot)
            and type(hasLoot) == "boolean" and type(canLoot) == "boolean" then
          if reacquired then lootBlock = hasLoot and not canLoot and 4 or 0 end
          if not hasLoot then
            state = 4
          elseif not canLoot then
            state = 0
          else
            state = 3
            if keyboardAvailable() and combat == false and autoLootEnabled() then
              local binding = actionKey("INTERACTTARGET")
              if binding then
                local heading, distance = targetWorldDirection()
                local softMatches = read(UnitIsUnit, "softinteract", "target") == true
                local squaredOK, squared, known = pcall(UnitDistanceSquared, "target")
                local near = (distance and distance <= 450) or (squaredOK and readable(squared)
                  and readable(known) and known == true and type(squared) == "number" and squared <= 20.25)
                if read(GetUnitSpeed, "player") == 0 and (softMatches or
                    (near and read(UnitExists, "softinteract") == false)) then
                  key = binding
                elseif heading and distance > 450 and distance <= 4000 then
                  bearing = heading * 1024 + math.floor(distance / 25 + 0.5)
                end
              end
            end
          end
        end
      end
    end
  elseif combat == false and keyboardAvailable() then
    local recentXP = lastCombatXpAt and now - lastCombatXpAt <= 4
    local matched = exists == false and tracked and combatXpNotices ~= nil
      and targetRevision == tracked.clearedRevision and now - tracked.seen <= 4
    local stationary = read(GetUnitSpeed, "player") == 0
    local validKill = matched and recentXP and tracked.xp ~= combatXpNotices
    if matched and (validKill or now - tracked.clearedAt <= 0.8) then
      tracked.lootWaitSince = tracked.lootWaitSince or now
    end
    if recentXP and stationary and not validKill then
      lootBlock = 1
    elseif validKill and stationary then
      local interact = actionKey("INTERACTTARGET")
      if not autoLootEnabled() or not interact then
        lootBlock = 2
      elseif tracked.requestRevision == nil or tracked.requestRevision == targetRevision then
        local soft = "softinteract"
        if unitGuid(soft) == tracked.guid and read(UnitIsDeadOrGhost, soft) == true
            and read(UnitIsTapDenied, soft) ~= true and type(CanLootUnit) == "function" then
          local ok, hasLoot, canLoot = pcall(CanLootUnit, tracked.guid)
          if ok and readable(hasLoot) and readable(canLoot) and hasLoot == true and canLoot == true then
            state, key, softCorpse = 3, interact, true
            tracked.requested = tracked.requested or now
          end
        end
        if not softCorpse then
          local binding = restoreLootKey(tracked)
          if binding then
            tracked.requested = tracked.requested or now
            tracked.requestRevision = targetRevision
            state, key = 6, binding
          else
            lootBlock = 3
          end
        end
        if state == 6 or softCorpse then
          tracked.lootID = tracked.lootID or (combatXpNotices + 1)
          lootID = tracked.lootID
        end
      end
    end
    if state == 0 and matched and tracked.lootWaitSince and now - tracked.lootWaitSince <= 0.8
        and autoLootEnabled() and actionKey("INTERACTTARGET") then
      state, lootBlock = 7, 0 -- 只等待尸体状态稳定，不发送交互键。
    end
  end
  return appendChecksum({ mobSignature, deathSequence, targetRevision, state, key,
    lootGeneration * 2 + (lootOpen and 1 or 0) + (reacquired and 0x20000 or 0) + lootBlock * 0x40000
      + (softCorpse and 0x200000 or 0), lootID ~= 0 and lootID or bearing })
end

local function collectNavigation(life, mapID, outdoors, x, y, isZone)
  if (life ~= 1 and life ~= 3) or not outdoors or not isZone or x == missingPosition or not keyboardAvailable()
      or read(UnitOnTaxi, "player") == true or read(IsFlying) == true
      or read(IsFalling) == true or read(IsSwimming) == true then return end
  local combat = read(UnitAffectingCombat, "player")
  if combat ~= false and (combat ~= true or life ~= 1) then return end
  local moving
  if combat then
    moving = read(addon.ObservePlayerMoving)
    if type(moving) ~= "boolean" then return end
  else
    local speed = read(GetUnitSpeed, "player")
    if type(speed) ~= "number" or not (speed >= 0) then return end
    moving = speed > 0
  end
  if (WorldMapFrame and WorldMapFrame:IsShown()) or (GameMenuFrame and GameMenuFrame:IsShown()) then return end
  local reviveDialog = false
  if life == 3 then
    local ok, popup = pcall(StaticPopup_FindVisible, "RECOVER_CORPSE")
    if not ok or not readable(popup) then return end
    reviveDialog = popup ~= nil
  end
  local heading = read(GetPlayerFacing)
  if type(heading) ~= "number" or not (math.abs(heading) <= 2 * math.pi) then return end
  heading = heading % (2 * math.pi)
  local ok, width, height = pcall(C_Map.GetMapWorldSize, mapID)
  if not ok or not (readable(width) and readable(height) and type(width) == "number" and type(height) == "number"
      and width >= 1 and width <= 100000 and height >= 1 and height <= 100000) then return end
  local forward, left, right = actionKey("MOVEFORWARD"), actionKey("TURNLEFT"), actionKey("TURNRIGHT")
  if not (forward and left and right and forward ~= left and left ~= right and forward ~= right) then return end
  local idleKey = combat == false and life == 1 and not moving and read(addon.GetIdleAutoTargetKeyIndex) or 0
  if not integer(idleKey, 0, 81) then idleKey = 0 end
  navigationSequence = (navigationSequence + 1) % 256
  local motion = moving and 0x80 or 0
  if reviveDialog then motion = motion + 0x20 end
  return appendChecksum({ navigationSignature, (life + 0x40 + motion) * 256 + navigationSequence, mapID, x, y,
    math.floor(heading * 1000 + 0.5), math.floor(width + 0.5), math.floor(height + 0.5),
    forward * 65536 + left * 256 + right }), idleKey, combat == false and life == 1
end

local function collectRetarget()
  if read(addon.GetPostKillAutoTargetEnabled) ~= true or read(addon.GetAutoTargetEnabled) ~= true then return end
  return appendChecksum({ retargetSignature, navigationSequence, targetRevision, actionKey("TARGETNEARESTENEMY") or 0 })
end

local function bindUnusedTargetAction(action, macro, limit)
  local reserved = {}
  for _ = 1, limit do
    local key, index = addon.FindFreeAutomationKey(reserved)
    if not key or index > limit then return end
    reserved[key] = true
    if read(GetBindingAction, key, false) == "" and read(GetBindingAction, key, true) == "" then
      if addon.CreateSecureButton(action, key, macro) then return key, index end
      return
    end
  end
end

local function visible(frame)
  return frame and read(frame.IsVisible, frame) == true
end

local function questDialogHasPopup()
  local blocked = false
  if type(StaticPopup_ForEachShownDialog) == "function" then
    StaticPopup_ForEachShownDialog(function() blocked = true end)
    return blocked
  end
  for index = 1, 4 do
    if visible(_G["StaticPopup" .. index]) then return true end
  end
  return false
end

local function friendlyCreature(unit)
  local guid = unitGuid(unit)
  return guid and guid:match("^Creature%-") and read(UnitCanAssist, "player", unit) == true
    and read(UnitIsDeadOrGhost, unit) == false and guid or nil
end

local function findQuestListButton(questID)
  if visible(GossipFrame) and friendlyCreature("npc") then
    local box = GossipFrame.GreetingPanel and GossipFrame.GreetingPanel.ScrollBox
    local frames = box and read(box.GetFrames, box)
    if type(frames) ~= "table" or not GOSSIP_BUTTON_TYPE_ACTIVE_QUEST then return end
    for _, button in pairs(frames) do
      local data = read(button.GetElementData, button)
      if type(data) == "table" and data.buttonType == GOSSIP_BUTTON_TYPE_ACTIVE_QUEST
          and type(data.info) == "table" and data.info.questID == questID and data.info.isComplete == true then
        return button
      end
    end
  elseif visible(QuestFrameGreetingPanel) and friendlyCreature("questnpc") then
    local pool = QuestFrameGreetingPanel.titleButtonPool
    if not pool then return end
    for button in pool:EnumerateActive() do
      local index = read(button.GetID, button)
      if button.isActive == 1 and type(index) == "number" and read(GetActiveQuestID, index) == questID then
        return button
      end
    end
  end
end

local function clearedCorpseBinding()
  local guid = unitGuid("target")
  if not guid or not guid:match("^Creature%-")
      or read(UnitIsDeadOrGhost, "target") ~= true then return end
  local ok, hasLoot, canLoot = pcall(CanLootUnit, guid)
  if not ok or not readable(hasLoot) or not readable(canLoot)
      or hasLoot ~= false or type(canLoot) ~= "boolean" then return end
  local button = questClearKey and addon.GetSecureButton(questClearAction)
  if button and read(button.GetAttribute, button, "type") == "macro"
      and read(button.GetAttribute, button, "macrotext") == questClearMacro
      and read(GetBindingAction, questClearKey, false) == ""
      and read(GetBindingAction, questClearKey, true) == "CLICK " .. button:GetName() .. ":LeftButton" then
    return questClearIndex, guid
  end
end

local function questInteractionIdentity(guid)
  local identity = 0
  for i = 1, #guid do identity = (identity * 131 + guid:byte(i)) % (checksumMod - 1) end
  return identity + 1
end

local function questDialogAction(questID)
  local cursorOK, cursor = pcall(GetCursorInfo)
  if not keyboardAvailable() or read(UnitAffectingCombat, "player") ~= false
      or read(GetUnitSpeed, "player") ~= 0 or not cursorOK or not readable(cursor) or cursor ~= nil
      or lootOpen or questDialogHasPopup() or visible(WorldMapFrame) or visible(GameMenuFrame)
      or visible(MerchantFrame) or visible(LootFrame) then return 7 end
  if visible(QuestFrameRewardPanel) or visible(QuestFrameProgressPanel) then
    if not friendlyCreature("questnpc") or read(GetQuestID) ~= questID then return 7 end
    local money = read(GetQuestMoneyToGet)
    if type(money) == "number" and money > 0 then return 6 end
    if money ~= 0 then return 7 end
    if visible(QuestFrameRewardPanel) then
      local choices = read(GetNumQuestChoices)
      if type(choices) ~= "number" or choices < 0 then return 7 end
      if choices > 1 then return 5 end
      return 4, QuestFrameCompleteQuestButton
    end
    if read(IsQuestCompletable) == true then return 3, QuestFrameCompleteButton end
    return 7
  end
  if visible(GossipFrame) or visible(QuestFrame) then
    local button = findQuestListButton(questID)
    if button then return 2, button end
    return 7
  end
  local guid = friendlyCreature("softinteract")
  local key = actionKey("INTERACTTARGET")
  if guid and key then
    if read(UnitExists, "target") == false or read(UnitIsUnit, "softinteract", "target") == true then
      return 1, nil, key, questInteractionIdentity(guid)
    end
    local clear, corpse = clearedCorpseBinding()
    if clear then return 8, nil, clear, questInteractionIdentity(corpse) end
  end
  return 0
end

local function collectQuestDialog(questWords, mapID)
  local questID = questWords and questWords[4] == mapID and questWords[3] or 0
  if (visible(QuestFrameRewardPanel) or visible(QuestFrameProgressPanel)) and friendlyCreature("questnpc") then
    local dialogID = read(GetQuestID)
    if type(dialogID) == "number" and dialogID > 0 and dialogID < checksumMod and dialogID % 1 == 0 then
      questID = dialogID
    end
  end
  local stage, button, key, npc = 0
  local x, y, hovered = missingPosition, missingPosition, 0
  if questID ~= 0 then
    stage, button, key, npc = questDialogAction(questID)
    if stage >= 2 and stage <= 4 then
      if not visible(button) or read(button.IsEnabled, button) ~= true then
        stage = 7
      else
        local cx, cy = button:GetCenter()
        local scale = button:GetEffectiveScale() / UIParent:GetEffectiveScale()
        x, y = encodePosition(cx * scale / UIParent:GetWidth(), 1 - cy * scale / UIParent:GetHeight())
        if x <= 0 or x >= 10000 or y <= 0 or y >= 10000 then
          stage, x, y = 7, missingPosition, missingPosition
        elseif mousePointsAt(button) then
          hovered = 1
        end
      end
    end
  end
  return appendChecksum({ questDialogSignature, deathSequence, questID, stage * 2 + hovered,
    key or 0, npc or 0, x, y, turnedInID, turnedInGeneration })
end

local function vendorName()
  local name = type(WowBuddyDevDB) == "table" and WowBuddyDevDB.supplyVendor
  if readable(name) and type(name) == "string" and #name > 0 and #name <= 90
      and not name:find("[%c%[%];|]") then return name end
end

local function bindVendor()
  local name = vendorName()
  vendorKey, vendorIndex, vendorMacro = nil, nil, nil
  if name then
    vendorMacro = "/targetexact [nocombat] " .. name
    vendorKey, vendorIndex = bindUnusedTargetAction(vendorAction, vendorMacro, 81)
  end
end

if type(SlashCmdList) == "table" then
  SLASH_WBDSUPPLY1 = "/wbdvendor"
  SlashCmdList.WBDSUPPLY = function()
    local name = read(UnitName, "target")
    if read(UnitAffectingCombat, "player") ~= false or type(WowBuddyDevDB) ~= "table"
        or not MerchantFrame or not read(MerchantFrame.IsShown, MerchantFrame)
        or not name or name ~= read(UnitName, "npc") or type(name) ~= "string"
        or #name > 90 or name:find("[%c%[%];|]") then
      print("WowBuddyDev：请脱战选中商人并打开他的商店，再输入 /wbdvendor。")
      return
    end
    WowBuddyDevDB.supplyVendor = name
    WowBuddyDevDB.supplyVendorMap = read(C_Map.GetBestMapForUnit, "player")
    bindVendor()
    print("WowBuddyDev：已记录商人 " .. name .. "。")
  end
end

local function hasRedEquipment()
  if type(GetInventoryAlertStatus) ~= "function" then return end
  local unknown = false
  for slot = 1, 11 do
    local ok, status = pcall(GetInventoryAlertStatus, slot)
    if not ok or not readable(status) then unknown = true
    elseif status == 2 then return true
    elseif status ~= nil and status ~= 0 and status ~= 1 then unknown = true end
  end
  if not unknown then return false end
end

local function collectVendor(mapID, repair)
  if not C_MerchantFrame or not C_Container then return end
  local manualMap = type(WowBuddyDevDB) == "table" and WowBuddyDevDB.supplyVendorMap
  local catalogKey = repair and repairVendorKey or (not repair and groveVendorKey)
  local catalog = mapID == 1439 and catalogKey and manualMap ~= mapID
  local name = catalog and groveVendorNames[read(GetLocale)] or vendorName()
  local action = catalog and groveVendorAction or vendorAction
  local key = catalog and groveVendorKey or vendorKey
  local bindingIndex = catalog and groveVendorIndex or vendorIndex
  local macro = catalog and groveVendorMacro or vendorMacro
  if catalog and repair then
    name, action, key, bindingIndex, macro = repairVendorNames[read(GetLocale)], repairVendorAction,
      repairVendorKey, repairVendorIndex, repairVendorMacro
  end
  local free = read(addon.GetGeneralBagFreeSlots)
  local junk = read(C_MerchantFrame.GetNumJunkItems)
  if type(junk) ~= "number" or not integer(free, 0, 1023) or not integer(junk, 0, 1023) then return end
  local function matches(unit)
    if not name or name ~= read(UnitName, unit) then return false end
    if not catalog then return true end
    local guid = unitGuid(unit)
    local id = repair and "6300" or "4195"
    return guid ~= nil and guid:match("^Creature%-%d+%-%d+%-%d+%-%d+%-" .. id .. "%-") ~= nil
  end
  local selected = matches("target") and read(UnitIsPlayer, "target") == false
    and read(UnitCanAttack, "player", "target") == false
  local shown = MerchantFrame and read(MerchantFrame.IsShown, MerchantFrame) == true
  local shop = shown and matches("npc")
  local button = key and addon.GetSecureButton(action)
  local index = (button and button:GetAttribute("macrotext") == macro
    and read(GetBindingAction, key, true) == "CLICK " .. button:GetName() .. ":LeftButton") and bindingIndex or 0
  local flags = (selected and 1 or 0) + (shown and 2 or 0) + (shop and 4 or 0) + (catalog and 64 or 0)
  local x, y = missingPosition, missingPosition
  local red, repairStatus
  if repair then red, repairStatus = hasRedEquipment(), 0 end
  local popup, popupCount = nil, 0
  local function observePopup(dialog)
    popupCount = popupCount + 1
    popup = dialog
  end
  if type(StaticPopup_ForEachShownDialog) == "function" then
    StaticPopup_ForEachShownDialog(observePopup)
  else
    for i = 1, 4 do
      local dialog = _G["StaticPopup" .. i]
      if dialog and read(dialog.IsShown, dialog) == true then observePopup(dialog) end
    end
  end
  local confirm = false
  if shop and MerchantFrame.selectedTab == 1 then
    confirm = popupCount == 1 and popup.which == "GENERIC_CONFIRMATION"
      and type(MerchantFrame_OnSellAllJunkButtonConfirmed) == "function"
      and type(SELL_ALL_JUNK_ITEMS_POPUP) == "string" and type(popup.data) == "table"
      and popup.data.text == SELL_ALL_JUNK_ITEMS_POPUP
      and popup.data.callback == MerchantFrame_OnSellAllJunkButtonConfirmed
    if confirm then flags = flags + 16 end
    button = nil
    if repair and red == true and not confirm and popupCount == 0 then
      local canRepair = read(CanMerchantRepair)
      if canRepair == false then
        repairStatus = 1
      elseif canRepair == true and type(GetRepairAllCost) == "function" then
        local ok, cost, available = pcall(GetRepairAllCost)
        local money = read(GetMoney)
        if ok and readable(cost) and readable(available) and type(cost) == "number" and cost > 0
            and type(money) == "number" then
          if money < cost then
            repairStatus = 2
          elseif available == true and keyboardAvailable() and not read(GetCursorInfo) then
            repairStatus, button = 3, MerchantRepairAllButton
          end
        end
      end
    elseif junk > 0 and not read(GetCursorInfo) and read(C_MerchantFrame.IsSellAllJunkEnabled) == true then
      if confirm and keyboardAvailable() then
        button = read(popup.GetButton1, popup)
      elseif popupCount == 0 then
        button = MerchantSellAllJunkButton
      end
    end
    if button and read(button.IsVisible, button) == true and read(button.IsEnabled, button) == true then
      local cx, cy = button:GetCenter()
      local scale = button:GetEffectiveScale() / UIParent:GetEffectiveScale()
      x, y = encodePosition(cx * scale / UIParent:GetWidth(), 1 - cy * scale / UIParent:GetHeight())
      local preciseHover = confirm or repairStatus == 3
      if (preciseHover and mousePointsAt(button)) or (not preciseHover and read(button.IsMouseOver, button) == true) then
        flags = flags + 8
      end
    end
  end
  if popupCount > 0 and not confirm then flags = flags + 32 end
  if repair then
    return appendChecksum({ repairSignature, deathSequence, free, junk, flags, index,
      actionKey("INTERACTTARGET") or 0, x or missingPosition, y or missingPosition,
      red == nil and 2 or (red and 1 or 0), repairStatus })
  end
  return appendChecksum({ vendorSignature, deathSequence, free, junk, flags, index,
    actionKey("INTERACTTARGET") or 0, x or missingPosition, y or missingPosition })
end

local function taxiMaster(unit)
  local guid = unitGuid(unit)
  return guid and guid:match("^Creature%-%d+%-%d+%-%d+%-%d+%-3838%-") ~= nil
end

local function taxiDestinationSlot(mapID)
  local nodes = C_TaxiMap and read(C_TaxiMap.GetAllTaxiNodes, mapID)
  if type(nodes) ~= "table" then return end
  local source, destination
  for _, node in ipairs(nodes) do
    if node.nodeID == 27 and node.state == 0 and not node.isMapLayerTransition then
      if source ~= nil then return end
      source = node.slotIndex
    end
    if node.nodeID == 26 and node.state == 1 and not node.isMapLayerTransition
        and (node.specialIconCostString == nil or node.specialIconCostString == "") then
      if destination ~= nil then return end
      destination = node.slotIndex
    end
  end
  if not integer(source, 1, 1024) or not integer(destination, 1, 1024) or source == destination
      or read(TaxiIsDirectFlight, destination) ~= true or read(TaxiNodeCost, destination) ~= 0
      or read(TaxiGetNodeSlot, destination, 1, true) ~= source
      or read(TaxiGetNodeSlot, destination, 1, false) ~= destination then return end
  return source, destination
end

local function taxiDestinationButton(panel, modern)
  local mapID
  if modern then
    mapID = read(panel.GetMapID, panel)
  else
    mapID = read(GetTaxiMapID)
    if not integer(mapID, 1, 0xFEFFFF) then mapID = 1414 end
  end
  if not integer(mapID, 1, 0xFEFFFF) then return end
  local source, destination = taxiDestinationSlot(mapID)
  if not destination then return end
  if not modern then
    if read(TaxiNodeGetType, source) ~= "CURRENT" or read(TaxiNodeGetType, destination) ~= "REACHABLE" then return end
    local button = _G["TaxiButton" .. destination]
    if button and read(button.GetID, button) == destination and read(button.IsVisible, button) == true
        and read(button.IsEnabled, button) == true then return button end
    return
  end
  if type(panel.EnumeratePinsByTemplate) ~= "function" or read(GetNumRoutes, destination) ~= 1 then return end
  local button
  for pin in panel:EnumeratePinsByTemplate("FlightMap_FlightPointPinTemplate") do
    local data = pin.taxiNodeData
    if type(data) == "table" and data.nodeID == 26 and data.slotIndex == destination and data.state == 1
        and not pin.isMapLayerTransition and not data.isMapLayerTransition
        and (data.specialIconCostString == nil or data.specialIconCostString == "")
        and read(pin.GetMap, pin) == panel and read(pin.IsVisible, pin) == true
        and read(pin.IsMouseEnabled, pin) == true then
      if button then return end
      button = pin
    end
  end
  return button
end

local function collectTaxi(mapID, x, y)
  local riding = read(UnitOnTaxi, "player")
  if riding ~= true and riding ~= false then return end
  local atHarbor = mapID == 1438 and x >= 5820 and x <= 5860 and y >= 9370 and y <= 9420
  if not riding and not atHarbor and mapID ~= 1439 then return end
  local flags, index, vk = riding and 1 or 0, 0, 0
  local px, py = missingPosition, missingPosition
  if not riding and atHarbor then
    local selected = taxiMaster("target") and read(UnitIsPlayer, "target") == false
      and read(UnitCanAttack, "player", "target") == false
    local classic = TaxiFrame and read(TaxiFrame.IsShown, TaxiFrame) == true
    local modern = FlightMapFrame and read(FlightMapFrame.IsShown, FlightMapFrame) == true
    local shown = classic or modern
    flags = (selected and 2 or 0) + (shown and 4 or 0)
    local cursorOK, cursor = pcall(GetCursorInfo)
    local blocked = not keyboardAvailable() or read(UnitAffectingCombat, "player") ~= false
      or read(GetUnitSpeed, "player") ~= 0 or not cursorOK or not readable(cursor) or cursor ~= nil
      or (classic and modern) or visible(WorldMapFrame) or visible(GameMenuFrame)
      or visible(QuestFrame) or visible(GossipFrame) or visible(MerchantFrame) or visible(LootFrame)
    local function blockForPopup() blocked = true end
    if type(StaticPopup_ForEachShownDialog) == "function" then
      StaticPopup_ForEachShownDialog(blockForPopup)
    else
      for i = 1, 4 do
        local popup = _G["StaticPopup" .. i]
        if popup and read(popup.IsShown, popup) == true then blocked = true end
      end
    end
    if blocked then
      flags = flags + 16
    elseif shown then
      local button = selected and taxiDestinationButton(modern and FlightMapFrame or TaxiFrame, modern)
      if button then
        local cx, cy = button:GetCenter()
        local scale = button:GetEffectiveScale() / UIParent:GetEffectiveScale()
        px, py = encodePosition(cx * scale / UIParent:GetWidth(), 1 - cy * scale / UIParent:GetHeight())
        if px > 0 and px < 10000 and py > 0 and py < 10000 then
          if mousePointsAt(button) then flags = flags + 8 end
        else
          px, py = missingPosition, missingPosition
        end
      end
    else
      local button = taxiKey and addon.GetSecureButton(taxiAction)
      if button and button:GetAttribute("macrotext") == taxiMacro
          and read(GetBindingAction, taxiKey, true) == "CLICK " .. button:GetName() .. ":LeftButton" then
        index = taxiIndex
      end
      vk = actionKey("INTERACTTARGET") or 0
    end
  end
  return appendChecksum({ taxiSignature, deathSequence, mapID, flags, index, vk,
    px or missingPosition, py or missingPosition })
end

function addon.ApplyDiscardTargetBinding()
  discardKey, discardIndex = nil, nil
  if read(addon.GetPostKillAutoTargetEnabled) == true then
    discardKey, discardIndex = bindUnusedTargetAction(discardAction, discardMacro, 27)
  end
  lootTargetKey, lootTargetIndex = nil, nil
  if actionKey("INTERACTTARGET") then
    lootTargetKey, lootTargetIndex = bindUnusedTargetAction(lootTargetAction, lootTargetMacro(), 81)
  end
  bindVendor()
  groveVendorKey, groveVendorIndex, groveVendorMacro = nil, nil, nil
  local groveName = groveVendorNames[read(GetLocale)]
  if groveName and read(UnitFactionGroup, "player") == "Alliance" and actionKey("INTERACTTARGET") then
    groveVendorMacro = "/targetexact [nocombat] " .. groveName
    groveVendorKey, groveVendorIndex = bindUnusedTargetAction(groveVendorAction, groveVendorMacro, 81)
  end
  repairVendorKey, repairVendorIndex, repairVendorMacro = nil, nil, nil
  local repairName = repairVendorNames[read(GetLocale)]
  if repairName and read(UnitFactionGroup, "player") == "Alliance" and actionKey("INTERACTTARGET") then
    repairVendorMacro = "/targetexact [nocombat] " .. repairName
    repairVendorKey, repairVendorIndex = bindUnusedTargetAction(repairVendorAction, repairVendorMacro, 81)
  end
  taxiKey, taxiIndex, taxiMacro = nil, nil, nil
  local name = taxiMasterNames[read(GetLocale)]
  if name and read(UnitFactionGroup, "player") == "Alliance" and actionKey("INTERACTTARGET") then
    taxiMacro = "/targetexact [nocombat] " .. name
    taxiKey, taxiIndex = bindUnusedTargetAction(taxiAction, taxiMacro, 81)
  end
  questClearKey, questClearIndex = nil, nil
  if actionKey("INTERACTTARGET") then
    questClearKey, questClearIndex = bindUnusedTargetAction(questClearAction, questClearMacro, 81)
  end
end

local function targetRejection()
  if read(UnitExists, "target") ~= true or read(UnitCanAttack, "player", "target") ~= true
      or read(UnitIsDeadOrGhost, "target") ~= false then return end
  local player = read(UnitIsPlayer, "target")
  local controlled = read(UnitPlayerControlled, "target")
  if player == true or controlled == true then
    return 1
  end
  if read(UnitIsTapDenied, "target") == true then return 2 end
  if player ~= false or controlled ~= false then return end
  local combat = read(UnitAffectingCombat, "player")
  if combat == true and read(UnitAffectingCombat, "target") == true and targetIsTargetingUs() then return end
  local playerLevel = read(UnitLevel, "player")
  if combat == false and integer(playerLevel, 1, 59) then
    local classification = read(UnitClassification, "target")
    if classification == "elite" or classification == "rareelite" or classification == "worldboss" then return 4 end
  end
  if read(UnitIsTrivial, "target") == true then return 3 end
  local targetLevel = read(UnitLevel, "target")
  if not integer(playerLevel, 5, 255) or not integer(targetLevel, 1, 255)
      or targetLevel ~= playerLevel - 4 then return 5 end
end

local function collectDiscard(rejection)
  if not discardIndex or not addon.DB or addon.DB.masterSwitch ~= true
      or read(GetUnitSpeed, "player") ~= 0 or read(UnitCanAttack, "player", "target") ~= true
      or read(UnitIsDeadOrGhost, "target") ~= false
      or (rejection ~= 1 and read(UnitPlayerControlled, "target") ~= false) then return end
  local button = addon.GetSecureButton(discardAction)
  if button and button:GetAttribute("type") == "macro" and button:GetAttribute("macrotext") == discardMacro
      and read(GetBindingAction, discardKey, false) == ""
      and read(GetBindingAction, discardKey, true) == "CLICK " .. button:GetName() .. ":LeftButton" then
    return appendChecksum({ discardSignature, navigationSequence, discardIndex })
  end
end

local function visibleNamePlate(plate)
  return plate and not plate:IsForbidden() and plate:IsVisible()
end

local function targetNamePlate()
  if not C_NamePlate then return end
  local plate = read(C_NamePlate.GetNamePlateForUnit, "target", false)
  if visibleNamePlate(plate) then return plate end
  for unit in pairs(namePlateUnits) do
    if read(UnitIsUnit, unit, "target") == true then
      plate = read(C_NamePlate.GetNamePlateForUnit, unit, false)
      if visibleNamePlate(plate) then return plate end
    end
  end
  local plates = read(C_NamePlate.GetNamePlates)
  if type(plates) ~= "table" then return end
  for _, visiblePlate in ipairs(plates) do
    if readable(visiblePlate) and visibleNamePlate(visiblePlate) then
      local unit = read(visiblePlate.GetUnit, visiblePlate)
        or visiblePlate.unitToken or visiblePlate.namePlateUnitToken
      if readable(unit) and type(unit) == "string" and read(UnitIsUnit, unit, "target") == true then
        return visiblePlate
      end
    end
  end
end

local function worldPosition(unit)
  local ok, north, west, _, world = pcall(UnitPosition, unit)
  if ok and readable(north) and readable(west) and readable(world)
      and type(north) == "number" and type(west) == "number" and type(world) == "number" then
    return north, west, world
  end
end

targetWorldDirection = function()
  local north, west, world = worldPosition("player")
  local targetNorth, targetWest, targetWorld = worldPosition("target")
  if world == nil then return nil, nil, 1 end
  if targetWorld == nil then return nil, nil, 2 end
  if world ~= targetWorld then return nil, nil, 3 end
  local dn, dw = targetNorth - north, targetWest - west
  local distance = math.sqrt(dn * dn + dw * dw)
  if not (distance >= 0 and distance <= 100) then return nil, nil, 4 end
  local distanceHundredths = math.floor(distance * 100 + 0.5)
  -- 贴近尸体时仍能确认交互距离，转向调用方继续等待有效方位。
  if distance < 1 then return nil, distanceHundredths, 4 end
  local heading = (math.atan2 or math.atan)(dw, dn) % (2 * math.pi)
  return math.floor(heading * 1000 + 0.5), distanceHundredths
end

local function targetWorldBearing()
  local heading, distance = targetWorldDirection()
  if heading then return appendChecksum({ targetWorldSignature, navigationSequence, targetRevision, heading, distance }) end
end

local function collectCombatFacing(now, cast)
  if cast.targetRevision ~= targetRevision or now - cast.failedAt > 1.5 or not keyboardAvailable()
      or read(UnitAffectingCombat, "player") ~= true or read(UnitCanAttack, "player", "target") ~= true
      or read(UnitIsDeadOrGhost, "target") ~= false or read(UnitPlayerControlled, "target") ~= false
      or read(IsFalling) == true or read(IsSwimming) == true or read(UnitOnTaxi, "player") == true
      or (WorldMapFrame and WorldMapFrame:IsShown()) or (GameMenuFrame and GameMenuFrame:IsShown()) then return end
  local action = cast.targetNameUnverified and currentTargetAction(cast.spell) or nil
  if cast.targetNameUnverified and not action then return end
  local forward, left, right = actionKey("MOVEFORWARD"), actionKey("TURNLEFT"), actionKey("TURNRIGHT")
  if not (forward and left and right and forward ~= left and forward ~= right and left ~= right) then return end
  local heading = read(GetPlayerFacing)
  local world = targetWorldBearing()
  local facing, goal = 65535, 65535
  if world and type(heading) == "number" and math.abs(heading) <= 2 * math.pi then
    facing, goal = math.floor((heading % (2 * math.pi)) * 1000 + 0.5), world[4]
  end
  local words = { action and combatFacingActionSignature or combatFacingSignature, castSequence, targetRevision,
    forward * 65536 + left * 256 + right, facing, goal }
  if action then words[#words + 1] = action end
  return appendChecksum(words)
end

local function ownNovaRoot(now)
  if not C_UnitAuras or type(C_UnitAuras.GetAuraDataByIndex) ~= "function" then return false, 1 end
  local issue = 2
  for index = 1, 40 do
    local ok, aura = pcall(C_UnitAuras.GetAuraDataByIndex, "target", index, "HARMFUL|PLAYER")
    if not ok or not readable(aura) then return false, 1 end
    if type(aura) ~= "table" then break end
    local spell, source, expires = aura.spellId, aura.sourceUnit, aura.expirationTime
    if not readable(spell) or type(spell) ~= "number" then
      if issue == 2 then issue = 3 end
    elseif isFrostNova(spell) then
      if not readable(source) or type(source) ~= "string" or source == "" then
        issue = 4
      elseif source ~= "player" and read(UnitIsUnit, source, "player") ~= true then
        issue = 5
      elseif not readable(expires) or type(expires) ~= "number" then
        issue = 6
      elseif expires - now >= 0.65 then
        return true
      else
        issue = 7
      end
    end
  end
  return false, issue
end

local function collectNovaSpacing(now, cast)
  if not cast or not cast.sentAt or now - cast.sentAt > 2 or not isFrostNova(cast.spell)
      or math.floor(cast.stages / 4) % 2 ~= 1 or cast.stages >= 8 then return end
  local blocked = 0
  if not keyboardAvailable() or read(UnitAffectingCombat, "player") ~= true
      or read(UnitOnTaxi, "player") == true or read(IsFlying) == true or read(IsFalling) == true
      or read(IsSwimming) == true or (WorldMapFrame and WorldMapFrame:IsShown())
      or (GameMenuFrame and GameMenuFrame:IsShown()) then blocked = blocked + 1 end
  if read(addon.ObservePlayerMoving) ~= false then blocked = blocked + 2 end
  local validTarget = cast.novaTargetRevision == targetRevision and read(UnitCanAttack, "player", "target") == true
    and read(UnitIsDeadOrGhost, "target") == false and read(UnitPlayerControlled, "target") == false
  if not validTarget then blocked = blocked + 4 end
  local backward, forward = actionKey("MOVEBACKWARD"), actionKey("MOVEFORWARD")
  local left, right = actionKey("TURNLEFT"), actionKey("TURNRIGHT")
  if not (backward and forward and left and right and backward ~= forward and backward ~= left
      and backward ~= right and forward ~= left and forward ~= right and left ~= right) then blocked = blocked + 8 end
  local facing = read(GetPlayerFacing)
  if type(facing) ~= "number" or not (math.abs(facing) <= 2 * math.pi) then
    facing, blocked = nil, blocked + 16
  end
  local heading, distance, directionIssue, rootIssue, eventOnly
  if validTarget then
    heading, distance, directionIssue = targetWorldDirection()
    if not heading then
      blocked = blocked + 32
    elseif distance > 850 or (facing and math.abs((heading / 1000 - facing + math.pi) % (2 * math.pi) - math.pi) > 0.6) then
      blocked = blocked + 64
    end
    local rooted
    rooted, rootIssue = ownNovaRoot(now)
    if not rooted and rootIssue ~= 5 and rootIssue ~= 7 and cast.novaAuraAppliedAt and not cast.novaAuraRemoved
        and now - cast.novaAuraAppliedAt <= 1.2 and unitGuid("target") == cast.novaTargetGuid then
      rooted, rootIssue, eventOnly = true, nil, true
    end
    if not rooted then blocked = blocked + 128 end
  end
  if blocked ~= 0 then
    local words = appendChecksum({ novaSpacingBlockedSignature, castSequence, blocked })
    if directionIssue or rootIssue then
      words[#words + 1] = (directionIssue or 0) * 256 + (rootIssue or 0)
      appendChecksum(words)
    end
    return words
  end
  return appendChecksum({ eventOnly and novaSpacingEventSignature or novaSpacingSignature,
    castSequence, targetRevision, deathSequence,
    backward, forward * 65536 + left * 256 + right, distance })
end

local function collectTarget()
  if read(UnitExists, "target") ~= true or read(UnitCanAttack, "player", "target") ~= true
      or read(UnitIsDeadOrGhost, "target") ~= false or read(UnitIsPlayer, "target") ~= false
      or read(UnitPlayerControlled, "target") ~= false or read(UnitIsTapDenied, "target") ~= false then return end
  local world = targetWorldBearing()
  if world then return world end
  local plate = targetNamePlate()
  if not plate then return end
  local x, y = plate:GetCenter()
  if not readable(x) or not readable(y) or type(x) ~= "number" or type(y) ~= "number" then return end
  local scale = plate:GetEffectiveScale() / UIParent:GetEffectiveScale()
  local px, py = encodePosition(x * scale / UIParent:GetWidth(), 1 - y * scale / UIParent:GetHeight())
  if px <= 0 or px >= 10000 or py <= 0 or py >= 10000 then return end
  local words = appendChecksum({ targetSignature, navigationSequence, targetRevision, px, py })
  local ok, squared, known = pcall(UnitDistanceSquared, "target")
  local exact = ok and readable(squared) and readable(known) and known == true
    and type(squared) == "number" and squared > 0
  words[7] = exact and 0x574241 or 0x574242
  return words
end

local function attachTextures(parent, pool, count, offset)
  for index = 1, count do
    local texture = parent:CreateTexture(nil, "OVERLAY")
    texture:SetSize(4, 4)
    texture:SetPoint("TOPLEFT", parent, "TOPLEFT", 4, -(offset + (index - 1) * 4))
    texture:Hide()
    pool[index] = texture
  end
end

function addon.AttachCharacterState(parent)
  if type(C_Map) ~= "table" or type(C_Map.GetBestMapForUnit) ~= "function" then return end
  if #textures == 0 then
    attachTextures(parent, textures, 31, 0)
    attachTextures(parent, deathTextures, 8, 136)
    attachTextures(parent, navigationTextures, 10, 172)
    attachTextures(parent, pullTextures, 4, 216)
    attachTextures(parent, targetTextures, 7, 236)
    attachTextures(parent, wandTextures, 3, 264)
    attachTextures(parent, retargetTextures, 5, 280)
    attachTextures(parent, discardTextures, 4, 300)
    attachTextures(parent, sightTextures, 4, 316)
    attachTextures(parent, precisePositionTextures, 6, 332)
    attachTextures(parent, targetRejectionTextures, 5, 356)
    attachTextures(parent, sessionTextures, 3, 376)
    attachTextures(parent, castFeedbackTextures, 7, 388)
    attachTextures(parent, combatFacingTextures, 8, 416)
    attachTextures(parent, novaSpacingTextures, 8, 448)
    attachTextures(parent, travelIdentityTextures, 5, 480)
    attachTextures(parent, progressTextures, 7, 500)
    attachTextures(parent, mobTextures, 8, 528)
    attachTextures(parent, vendorTextures, 10, 560)
    attachTextures(parent, elevationTextures, 6, 600)
    attachTextures(parent, taxiTextures, 9, 624)
    attachTextures(parent, repairTextures, 12, 660)
    attachTextures(parent, questTextures, 7, 708)
    attachTextures(parent, questDialogTextures, 11, 736)
  end
end

local function renderWords(pool, words)
  for index, texture in ipairs(pool) do
    local word = words and words[index]
    if word then
      local r = math.floor(word / 65536)
      local g = math.floor(word / 256) % 256
      texture:SetColorTexture(r / 255, g / 255, (word % 256) / 255, 1)
      texture:Show()
    else
      texture:Hide()
    end
  end
end

local function renderTravelDetails(hasNavigation, hasDeath, life, mapID, x, y)
  local elevationWords
  if hasNavigation and hasDeath and mapID == 1439 and x >= 3600 and x <= 3750 and y >= 4480 and y <= 4620 then
    local positionOK, _, _, height, world = pcall(UnitPosition, "player")
    if positionOK and readable(world) and world == 1 and readable(height)
        and type(height) == "number" and height >= -2048 and height <= 8192 then
      elevationWords = appendChecksum({ elevationSignature, navigationSequence, deathSequence, mapID,
        math.floor(height * 100 + 204800 + 0.5) })
    end
  end
  renderWords(elevationTextures, elevationWords)
  local taxiOK, taxiWords
  if hasDeath and life == 1 then taxiOK, taxiWords = pcall(collectTaxi, mapID, x, y) end
  renderWords(taxiTextures, taxiOK and taxiWords)
end

local function renderQuestDetails(hasDeath, life, now, mapID, x, y)
  local pin, dialog
  if hasDeath and life == 1 then
    pin = read(collectQuestPin, now, mapID, x, y)
    dialog = read(collectQuestDialog, pin, mapID)
  end
  renderWords(questTextures, pin)
  renderWords(questDialogTextures, dialog)
end

function addon.UpdateCharacterState()
  if #textures == 0 then return end
  local now = GetTime()
  if now < nextUpdate then return end
  nextUpdate = now + 0.2
  -- 进角色或重载界面会重建 Lua 环境；普通切图沿用同一个标记。
  if not sessionWords then
    sessionWords = appendChecksum({ sessionSignature, math.floor(now * 1000) % checksumMod })
  end
  renderWords(sessionTextures, sessionWords)
  if not travelIdentityWords and read(UnitAffectingCombat, "player") == false then
    travelIdentityWords = travelIdentity()
  end
  renderWords(travelIdentityTextures, travelIdentityWords)
  renderWords(progressTextures, collectProgress())
  local castWords, facingWords
  if castFeedback then
    castWords = appendChecksum({ castFeedbackSignature, castSequence, castFeedback.spell, castFeedback.stages })
    local cast = castFeedback
    if cast.failedAt and cast.errorAt and cast.reason > 0 and cast.sentAt <= cast.errorAt
        and math.abs(cast.errorAt - cast.failedAt) <= castErrorWindow
        and math.floor(cast.stages / 4) % 2 == 0 and math.floor(cast.stages / 16) % 2 == 0 then
      castWords[#castWords + 1] = cast.reason
      appendChecksum(castWords)
      if math.floor(cast.reason / 65536) == 1 then
        local facingOK, packet = pcall(collectCombatFacing, now, cast)
        if facingOK then facingWords = packet end
      end
    end
  end
  renderWords(castFeedbackTextures, castWords)
  renderWords(combatFacingTextures, facingWords)
  local ok, words, life, mapID, outdoors, x, y, isZone, rawX, rawY = pcall(collect)
  renderWords(textures, ok and words)
  local deathOK, deathWords
  if ok then deathOK, deathWords = pcall(collectDeath, life, mapID, outdoors, x, y, isZone) end
  renderWords(deathTextures, deathOK and deathWords)
  renderWords(mobTextures, deathOK and deathWords and life == 1 and collectMob())
  local vendorOK, vendorWords
  if deathOK and deathWords and life == 1 then vendorOK, vendorWords = pcall(collectVendor, mapID) end
  renderWords(vendorTextures, vendorOK and vendorWords)
  local repairOK, repairWords
  if deathOK and deathWords and life == 1 then repairOK, repairWords = pcall(collectVendor, mapID, true) end
  renderWords(repairTextures, repairOK and repairWords)
  renderQuestDetails(deathOK and deathWords, life, now, mapID, x, y)
  local rejection, rejectionWords
  if deathOK and deathWords and life == 1 then
    rejection = targetRejection()
    if rejection then
      rejectionWords = appendChecksum({ targetRejectionSignature, deathSequence, targetRevision, rejection })
    end
  end
  renderWords(targetRejectionTextures, rejectionWords)
  local navigationOK, navigationWords, idleKey, canRetarget
  if ok then
    navigationOK, navigationWords, idleKey, canRetarget = pcall(collectNavigation, life, mapID, outdoors, x, y, isZone)
  end
  renderWords(navigationTextures, navigationOK and navigationWords)
  local spacingOK, spacingWords
  if deathOK and deathWords and life == 1 and outdoors then
    spacingOK, spacingWords = pcall(collectNovaSpacing, now, castFeedback)
  end
  renderWords(novaSpacingTextures, spacingOK and spacingWords)
  local preciseWords
  if navigationOK and navigationWords then
    preciseWords = appendChecksum({ precisePositionSignature, navigationSequence, mapID,
      math.floor(rawX * 1000000 + 0.5), math.floor(rawY * 1000000 + 0.5) })
  end
  renderWords(precisePositionTextures, preciseWords)
  renderTravelDetails(navigationOK and navigationWords, deathOK and deathWords, life, mapID, x, y)
  local pullWords
  if navigationOK and idleKey and idleKey > 0 then
    pullWords = appendChecksum({ pullSignature, navigationSequence, idleKey })
  end
  renderWords(pullTextures, pullWords)
  local targetOK, targetWords
  if navigationOK and navigationWords and life == 1 then
    targetOK, targetWords = pcall(collectTarget)
  end
  renderWords(targetTextures, targetOK and targetWords)
  local wandIndex = read(addon.GetReadyWandKey)
  local wandWords
  if integer(wandIndex, 1, 81) then wandWords = appendChecksum({ wandSignature, wandIndex }) end
  renderWords(wandTextures, wandWords)
  local retargetOK, retargetWords
  if navigationOK and canRetarget then retargetOK, retargetWords = pcall(collectRetarget) end
  renderWords(retargetTextures, retargetOK and retargetWords)
  local discardOK, discardWords
  if retargetOK and retargetWords then discardOK, discardWords = pcall(collectDiscard, rejection) end
  renderWords(discardTextures, discardOK and discardWords)
  local sightWords
  if retargetOK and retargetWords and now < sightUntil and isSightTarget() then
    sightWords = appendChecksum({ sightSignature, navigationSequence, targetRevision })
  end
  renderWords(sightTextures, sightWords)
end
