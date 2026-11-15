-- ==========================================================================
-- 文件：CoreCastState.lua
-- 来源：2026-11-15 从 Core.lua 原样移出（原第 1555-1936 行），语句与顺序未改。
-- 作用：读条/引导/施法成功代次与蓄力状态查询。
-- 加载：TOC 中紧跟 Core.lua；不依赖 Core.lua 的文件级 local。
-- ==========================================================================
-- ---- 以下为原 Core.lua 内容 ----
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("CoreCastState", { "CoreState" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local castGenerationCounter = 1
local lastCastSpellID = nil
local lastCastKind = nil
WowBuddyDev.playerCastGeneration = 1
-- 功能：取玩家当前读条/引导状态，输出给像素编码用的四个值。
-- 入参：includeChannel 为 true 时才把「引导」也算作正在施法。
-- 出参：isCasting, 读条剩余十分位秒数, 读条技能 ID, 观测状态码。
-- 说明：观测状态码是一套诊断码，用来区分「没读条 / 正常 / 被秘密值挡住 / 缺少字段 / 派发异常」等不同情况，方便读取端判断这个值能不能信。无限客户端没有新版 castBarID 时，沿用同一接口里的 castID 或开始时间标识本次读条。
-- 说明2：按 12.x 的 UnitCastingInfo 签名，第 11 个返回值是 delayTimeMs（施法被推迟的累计毫秒），这一版没有解构它，所以读条时长里不含推迟量。
function WowBuddyDev.GetPlayerCastState(includeChannel)
  local isCasting = false
  local castRemainingTenths = 0
  local observedCastSpellID = 0
  local castObservationCode = 0
  local callOK = pcall(function()
    local castName, castText, castTexture, castStartMs, castEndMs, castIsTradeSkill, castID, castUninterruptible, castSpellID, castBarID = UnitCastingInfo("player")
    local castKind = "cast"
    if not castName and includeChannel == true then
      local channelName, channelText, channelTexture, channelStartMs, channelEndMs, channelIsTradeSkill, channelUninterruptible, channelSpellID, channelIsEmpowered, channelEmpowerStages, channelCastBarID = UnitChannelInfo("player")
      if channelName and channelIsEmpowered ~= true then
        castName = channelName
        castStartMs = channelStartMs
        castEndMs = channelEndMs
        castID = nil
        castSpellID = channelSpellID
        castBarID = channelCastBarID
        castKind = "channel"
      elseif channelName then
        if channelIsEmpowered == true then
          lastCastSpellID = nil
          lastCastKind = nil
          if issecretvalue and issecretvalue(channelSpellID) then
            castObservationCode = 19
          elseif type(channelSpellID) == "number" and (channelSpellID > 1 and (channelSpellID < 16777215 and channelSpellID % 1 == 0)) then
            observedCastSpellID = channelSpellID
            castObservationCode = 3
          else
            castObservationCode = 18
          end
          return
        end
      end
    end
    if not castName then
      lastCastSpellID = nil
      lastCastKind = nil
      return
    end
    if not castEndMs then
      WowBuddyDev.playerCastGeneration = 0
      castObservationCode = castKind == "channel" and 5 or 4
      return
    end
    if castName and castEndMs then
      if issecretvalue and issecretvalue(castEndMs) then
        WowBuddyDev.playerCastGeneration = 0
        castObservationCode = castKind == "channel" and 7 or 6
        return
      end
      local castRemainingSec = (castEndMs - GetTime() * 1000) / 1000
      if castRemainingSec > 0 then
        local castIdentity = castBarID
        if issecretvalue and issecretvalue(castIdentity) then
          castIdentity = nil
        end
        if type(castIdentity) ~= "number" and type(castIdentity) ~= "string" then
          castIdentity = castID
          if issecretvalue and issecretvalue(castIdentity) then
            castIdentity = nil
          end
        end
        if type(castIdentity) ~= "number" and type(castIdentity) ~= "string" then
          castIdentity = castStartMs
          if issecretvalue and issecretvalue(castIdentity) then
            castIdentity = nil
          end
        end
        if type(castIdentity) ~= "number" and type(castIdentity) ~= "string" then
          WowBuddyDev.playerCastGeneration = 0
          castObservationCode = castKind == "channel" and 11 or 10
          return
        end
        if castIdentity ~= lastCastSpellID or castKind ~= lastCastKind then
          castGenerationCounter = castGenerationCounter % 99 + 1
          lastCastSpellID = castIdentity
          lastCastKind = castKind
        end
        WowBuddyDev.playerCastGeneration = castGenerationCounter
        isCasting = true
        castRemainingTenths = math.floor(castRemainingSec * 10 + .5)
        if issecretvalue and issecretvalue(castSpellID) then
          castObservationCode = castKind == "channel" and 17 or 16
        elseif type(castSpellID) == "number" and (castSpellID > 1 and (castSpellID < 16777215 and castSpellID % 1 == 0)) then
          observedCastSpellID = castSpellID
          castObservationCode = castKind == "channel" and 2 or 1
        else
          castObservationCode = castKind == "channel" and 15 or 14
        end
      else
        castObservationCode = castKind == "channel" and 9 or 8
      end
    end
  end)
  if not callOK then
    WowBuddyDev.playerCastGeneration = 0
    castObservationCode = 20
  end
  return isCasting, castRemainingTenths, observedCastSpellID, castObservationCode
end
-- 功能：给外部读取端做「引导时间窗」判定：当前是否落在引导的某个百分比区间内。
-- 入参：spellID 期望的技能 ID；windowStartPercent 区间起点百分比；windowEndPercent 区间终点百分比。
-- 出参：是否在引导, 是否落在窗口内, 数据是否可读。
-- 说明：要求传入的技能 ID 和实际引导技能一致，否则直接不算。只要时间字段是秘密值或类型不对，就把「数据可读」置假返回，让读取端知道这次判定无效而不是误判成「不在窗口内」。区间是按引导总时长的百分比换算成绝对毫秒后和当前时间比较的。
function WowBuddyDev.GetPlayerChannelWindowState(spellID, windowStartPercent, windowEndPercent)
  local inWindow = false
  local isWindowOpen = false
  local valuesReadable = true
  local callOK = pcall(function()
    local channelName, channelText, channelTexture, channelStartMs, channelEndMs, channelIsTradeSkill, channelUninterruptible, channelSpellID, channelIsEmpowered = UnitChannelInfo("player")
    if not channelName then
      return
    end
    if issecretvalue and (issecretvalue(channelStartMs) or issecretvalue(channelEndMs) or issecretvalue(channelSpellID) or issecretvalue(channelIsEmpowered)) then
      valuesReadable = false
      return
    end
    if channelIsEmpowered == true then
      return
    end
    if type(channelSpellID) ~= "number" then
      valuesReadable = false
      return
    end
    if channelSpellID ~= spellID then
      return
    end
    inWindow = true
    if type(channelStartMs) ~= "number" or type(channelEndMs) ~= "number" or type(windowStartPercent) ~= "number" or type(windowEndPercent) ~= "number" or windowEndPercent <= 0 or windowStartPercent < 0 or windowStartPercent >= windowEndPercent or channelEndMs <= channelStartMs then
      valuesReadable = false
      return
    end
    local windowStartMs = channelStartMs + (channelEndMs - channelStartMs) * windowStartPercent / windowEndPercent
    local nowMs = GetTime() * 1000
    isWindowOpen = nowMs >= windowStartMs and nowMs < channelEndMs
  end)
  if not callOK then
    return false, false, false
  end
  return inWindow, isWindowOpen, valuesReadable
end
-- 功能：取「最近一次成功施法」的代次号和技能 ID，并做范围校验。
-- 入参：无。
-- 出参：代次号（1 到 99 的整数）, 技能 ID；不合法时对应项为 0。
-- 说明：这两个值要编码进颜色通道，通道容量有限，所以超出范围或非整数一律置 0 表示「本次无有效值」，而不是截断成一个假的 ID。
function WowBuddyDev.GetPlayerSucceededState()
  local generation = tonumber(WowBuddyDev.playerSucceededGeneration) or 0
  local spellID = tonumber(WowBuddyDev.playerSucceededSpellID) or 0
  if generation < 1 or generation > 99 or generation % 1 ~= 0 then
    generation = 0
  end
  if spellID <= 1 or spellID >= 16777215 or spellID % 1 ~= 0 then
    spellID = 0
  end
  return generation, spellID
end
local empowerGenerationCounter = 0
local activeEmpower = nil
local lastEmpowerOutcome = nil
local empowerSpellIDs = nil
local EMPOWER_OUTCOME_TTL_SEC = .35
-- 功能：在当前专精的蓄力技能列表里找「正在蓄力」的那一个。
-- 入参：无（列表由取蓄力状态时传入并缓存在本地）。
-- 出参：技能 ID；没有正在蓄力的返回 nil。
-- 说明：查询本身会抛错，所以逐个包保护调用；只要有一个命中就直接返回，不再继续查。
local function findCurrentEmpowerSpell()
  if type(empowerSpellIDs) ~= "table" or not C_Spell or type(C_Spell.IsCurrentSpell) ~= "function" then
    return nil
  end
  for index10, spellID in ipairs(empowerSpellIDs) do
    local callOK, isCurrent = pcall(function()
      return C_Spell.IsCurrentSpell(spellID) == true
    end)
    if callOK and isCurrent then
      return spellID
    end
  end
  return nil
end
-- 功能：把蓄力相关的施法事件统一解析成一条「蓄力事件」记录。
-- 入参：eventName 事件名；... 事件参数（蓄力层数、施法 GUID、1/0 标记、技能 ID 等）。
-- 出参：事件记录（技能 ID、施法 GUID、施法条 ID、是否成功）；无法识别的事件或参数全是秘密值时返回 nil。
-- 说明：不同事件的参数位置不一样，开始/停止/失败/被打断各自取不同位置的值，所以要按事件名分别取。所有参数都必须先过秘密值检查：当前客户端里读条相关字段可能是「秘密值」，插件既不能比较也不能存，只能整条丢弃，否则后续判断会报错。
local function parseEmpowerCastEvent(eventName, ...)
  local v200, v201, v202, v203, v204, v205 = ...
  return pcall(function()
    local rawCastBarID = nil
    local succeeded = nil
    if eventName == "UNIT_SPELLCAST_EMPOWER_START" then
      rawCastBarID = v203
    elseif eventName == "UNIT_SPELLCAST_EMPOWER_STOP" then
      if issecretvalue and issecretvalue(v203) then
        succeeded = false
      else
        succeeded = v203 == true
      end
      rawCastBarID = v205
    elseif eventName == "UNIT_SPELLCAST_FAILED" or eventName == "UNIT_SPELLCAST_FAILED_QUIET" then
      succeeded = false
      rawCastBarID = v203
    elseif eventName == "UNIT_SPELLCAST_INTERRUPTED" then
      succeeded = false
      rawCastBarID = v204
    else
      return nil
    end
    local castGUID = nil
    if not (issecretvalue and issecretvalue(v201)) and (type(v201) == "string" and v201 ~= "") then
      castGUID = v201
    end
    local castBarID = nil
    if not (issecretvalue and issecretvalue(rawCastBarID)) and type(rawCastBarID) == "number" then
      castBarID = rawCastBarID
    end
    if not castGUID and not castBarID then
      return nil
    end
    local spellID = nil
    if not (issecretvalue and issecretvalue(v202)) and (type(v202) == "number" and v202 > 1) then
      spellID = math.floor(v202)
    end
    if eventName == "UNIT_SPELLCAST_EMPOWER_START" and not spellID then
      spellID = findCurrentEmpowerSpell()
    end
    return { spellID = spellID, castGUID = castGUID, castBarID = castBarID, succeeded = succeeded }
  end)
end
-- 功能：判断两条蓄力事件记录说的是不是同一次施法（先比施法 GUID，再比施法条 ID）。
-- 入参：left 记录甲；right 记录乙。
-- 出参：true/false。
-- 说明：有些事件只给施法条 ID、不给施法 GUID，所以两个字段都要试；这正是「开始」事件能被后续「停止/失败」事件认出来的依据。
local function isSameCast(left, right)
  if left.castGUID and (right.castGUID and left.castGUID == right.castGUID) then
    return true
  end
  return left.castBarID and (right.castBarID and left.castBarID == right.castBarID)
end
local empowerEventFrame = CreateFrame("Frame")
empowerEventFrame:SetScript("OnEvent", function(self3, eventName, ...)
  local callOK, castEvent = parseEmpowerCastEvent(eventName, ...)
  if not callOK or type(castEvent) ~= "table" then
    return
  end
  if eventName == "UNIT_SPELLCAST_EMPOWER_START" then
    if activeEmpower and isSameCast(activeEmpower, castEvent) then
      if not activeEmpower.spellID then
        activeEmpower.spellID = castEvent.spellID
      end
      return
    end
    empowerGenerationCounter = empowerGenerationCounter % 99 + 1
    activeEmpower = { spellID = castEvent.spellID, castGUID = castEvent.castGUID, castBarID = castEvent.castBarID, generation = empowerGenerationCounter }
    lastEmpowerOutcome = nil
    return
  end
  if not activeEmpower or not isSameCast(activeEmpower, castEvent) then
    return
  end
  if castEvent.spellID then
    if activeEmpower.spellID and activeEmpower.spellID ~= castEvent.spellID then
      return
    end
    activeEmpower.spellID = castEvent.spellID
  end
  lastEmpowerOutcome = {
    spellID = activeEmpower.spellID,
    generation = activeEmpower.generation,
    succeeded = castEvent.succeeded == true,
    expiresAt = GetTime() + EMPOWER_OUTCOME_TTL_SEC,
  }
  activeEmpower = nil
end)
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_EMPOWER_START", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_EMPOWER_STOP", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_FAILED", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_FAILED_QUIET", "player")
empowerEventFrame:RegisterUnitEvent("UNIT_SPELLCAST_INTERRUPTED", "player")
-- 功能：判断技能 ID 是否在给定列表里。
-- 入参：spellList 技能 ID 列表；spellID 待查技能 ID。
-- 出参：true/false。
local function isSpellIDInList(spellList, spellID)
  for index11, listedSpellID in ipairs(spellList) do
    if listedSpellID == spellID then
      return true
    end
  end
  return false
end
-- 功能：取玩家当前的蓄力状态：技能 ID、已经完成的蓄力层数、本次蓄力要读的总层数。
-- 入参：spellIDs 当前专精的蓄力技能 ID 列表。
-- 出参：技能 ID, 已完成层数, 总层数。
-- 说明：先看最近一次蓄力结果是否还在有效期内、且技能在本次列表里，命中就直接用记录（客户端在蓄力结束瞬间读不到当前技能，只能靠事件补）。否则再逐个问客户端当前施法。层数只能从逐层时长对象上反推：对象带秘密值或查询抛错就无法确定，这时退回「已完成层数 0」，但仍把总层数告诉读取端。
-- 说明2：引导的第 9、10 个返回值分别是 isEmpowered（是否蓄力）和 numEmpowerStages（蓄力层数），这两个字段是 NeverSecret 的，所以能用；同函数里对它们做了 issecretvalue 兜底只是因为客户端不同版本行为不一致。
function WowBuddyDev.GetPlayerEmpowerState(spellIDs)
  if type(spellIDs) ~= "table" then
    return 1, 0, 0
  end
  empowerSpellIDs = spellIDs
  if lastEmpowerOutcome then
    if GetTime() > lastEmpowerOutcome.expiresAt then
      lastEmpowerOutcome = nil
    elseif isSpellIDInList(spellIDs, lastEmpowerOutcome.spellID) then
      local outcomeBase = lastEmpowerOutcome.succeeded and 100 or 200
      return lastEmpowerOutcome.spellID, outcomeBase + lastEmpowerOutcome.generation, 0
    end
  end
  if not C_Spell or type(C_Spell.IsCurrentSpell) ~= "function" then
    return 1, 0, 0
  end
  local currentSpellID = 0
  for index12, spellID in ipairs(spellIDs) do
    local callOK, isCurrent = pcall(function()
      return C_Spell.IsCurrentSpell(spellID) == true
    end)
    if not callOK then
      return 1, 0, 0
    end
    if isCurrent then
      currentSpellID = spellID
      break
    end
  end
  if currentSpellID > 0 and (activeEmpower and not activeEmpower.spellID) then
    activeEmpower.spellID = currentSpellID
  end
  if not UnitChannelInfo then
    return currentSpellID > 0 and currentSpellID or 1, 0, 0
  end
  local callOK, isEmpowered, stagesToRead = pcall(function()
    local v212, v213, v214, v215, v216, v217, v218, v219, channelIsEmpowered, channelEmpowerStages = UnitChannelInfo("player")
    if channelIsEmpowered ~= true then
      return false, 0
    end
    if issecretvalue and issecretvalue(channelEmpowerStages) then
      return true, 0
    end
    return true, math.floor(tonumber(channelEmpowerStages) or 0)
  end)
  if not callOK then
    return currentSpellID > 0 and currentSpellID or 1, 0, 0
  end
  if not isEmpowered then
    return currentSpellID, 0, 0
  end
  if currentSpellID == 0 then
    return 1, 0, 0
  end
  if stagesToRead < 1 or not UnitEmpoweredStageDurations then
    return currentSpellID, 0, 0
  end
  local callOK, stageDurations = pcall(UnitEmpoweredStageDurations, "player")
  if not callOK or type(stageDurations) ~= "table" or #stageDurations < stagesToRead then
    return currentSpellID, 0, stagesToRead
  end
  local callOK, completedStages = pcall(function()
    local completedStages = 0
    for i3 = 1, stagesToRead, 1 do
      local stageDuration = stageDurations[i3]
      if not stageDuration or stageDuration:HasSecretValues() then
        return nil
      end
      if not stageDuration:HasExpired() then
        break
      end
      completedStages = i3
    end
    return completedStages
  end)
  if not callOK or type(completedStages) ~= "number" then
    return currentSpellID, 0, stagesToRead
  end
  return currentSpellID, completedStages, stagesToRead
end
WowBuddyDev.RegisterModule("CoreCastState", { "Core" })
