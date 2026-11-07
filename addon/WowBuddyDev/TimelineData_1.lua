-- ==========================================================================
-- 文件：3b0b39.lua
-- 来源：P07483180.rar → P07483180/3b0b39.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：3b0b39.lua → TimelineData_1.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
WowBuddyDev.TimelinePlannerEncounters = {}
-- 功能：构建注册键 347015（首领 3470 × 难度 15）的机制解析器——按时间轴时长换算阿曼尼系机制，并用单位施法事件推进读条阶段。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnUnitEvent 处理单位施法事件）。
-- 说明：阶段码用 1 / 1.5 / 2 表示，返回时映射成 1 / 2 / 3。第 1 阶段里 40、28、15 秒这几个时长第一次出现只计数不上报（当作开场预热），之后 40 秒按出现次数的奇偶在 restless_amani 与 essence_rend 之间切换；第 2 阶段换成另一套时长表。
local function createEncounter347015()
  local phaseStep, isCastCompleted, lastCastAt = 1, false, 0
  local durationCounts = {}
  -- 功能：把一条时间轴事件的时长换算成机制键（阿曼尼系）。
  -- 入参：duration 事件时长（秒，浮点）。
  -- 出参：mechanicKey 机制键（认不出来就是 nil）；stageCode 阶段码（1 / 2 / 3）。
  -- 说明：时长先四舍五入成整数秒再查表；第 1 阶段下 40 / 28 / 15 秒的首次出现直接返回 nil——首领开场那一次不是可预警的机制，报了会误导预警条。
  local function resolveMechanic(duration)
    local durationRounded = math.floor(duration + .5)
    local mechanicKey
    if phaseStep < 2 then
      if durationRounded == 40 or durationRounded == 28 or durationRounded == 15 then
        durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
        if durationCounts[durationRounded] == 1 then
          return nil
        end
      end
      if durationRounded == 40 then
        mechanicKey = durationCounts[durationRounded] % 2 == 0 and "restless_amani" or "essence_rend"
      elseif durationRounded == 28 or durationRounded == 36 then
        mechanicKey = "possession_barrage"
      elseif durationRounded == 15 then
        mechanicKey = "essence_rend"
      elseif durationRounded == 30 then
        mechanicKey = "restless_amani"
      end
    else
      if durationRounded == 28 then
        mechanicKey = "possession_barrage"
      elseif durationRounded == 40 then
        durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
        mechanicKey = durationCounts[durationRounded] % 2 == 1 and "possession_barrage" or "restless_amani"
      elseif durationRounded == 50 then
        mechanicKey = "essence_rend"
      elseif durationRounded == 20 then
        mechanicKey = "restless_amani"
      end
    end
    return mechanicKey, phaseStep == 1 and 1 or phaseStep == 1.5 and 2 or 3
  end
  -- 功能：处理 3470 的单位施法事件，推进读条阶段。
  -- 入参：eventName 事件名；now 当前时间（秒）。
  -- 出参：无。
  -- 说明：UNIT_SPELLCAST_START 只记下时刻；2 秒内收到 UNIT_SPELLCAST_SUCCEEDED 说明是瞬发／读条完成，置位并清空时长计数；紧接着的 UNIT_SPELLCAST_CHANNEL_START 在置位状态下把阶段从 1 推到 1.5，若本来已是 1.5 则推到 2 并清空计数（转阶段）。
  local function onUnitEvent(eventName, now)
    if eventName == "UNIT_SPELLCAST_START" then
      lastCastAt = now
    elseif eventName == "UNIT_SPELLCAST_SUCCEEDED" then
      if phaseStep == 1 and (lastCastAt > 0 and now - lastCastAt < 2) then
        isCastCompleted = true
        wipe(durationCounts)
      end
    elseif eventName == "UNIT_SPELLCAST_CHANNEL_START" then
      if phaseStep == 1 and isCastCompleted then
        phaseStep, isCastCompleted = 1.5, false
      elseif phaseStep == 1.5 then
        phaseStep = 2
        wipe(durationCounts)
      end
    end
  end
  return { Resolve = resolveMechanic, OnUnitEvent = onUnitEvent }
end
-- 功能：构建注册键 320108（首领 3201 × 难度 8）的机制解析器——按 0.1 秒的批次识别阶段标记，并在三个阶段各自的时长表之间切换四机制轮换。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（IsPhaseMarker 判阶段标记、PrepareBatch 整批预判阶段、Resolve 判定机制）。
-- 说明：2.5 秒进入阶段 3，3 或 9 秒进入阶段 2；阶段只能前进不能后退。阶段 1 / 2 用 5、18、3、9 秒这四个固定时长，20~21 秒这种拆批发来的时长按轮换序号奇偶在两对机制间交替；阶段 3 换成 7.3 / 15.3 / 23.3 / 31.1 / 31.3 的固定表和 32 秒的轮换表。
local function createEncounter320108()
  local phaseCode, rotationIndex = 1, 1
  local ROTATION_MECHANICS = { "lightfire", "grievous_thrash", "lightfall", "pulverizing_strikes" }
  -- 功能：阶段推进——新阶段码比当前大时才更新，并把轮换序号复位。
  -- 入参：newPhaseCode 新阶段码。
  -- 出参：无。
  -- 说明：只前不后是刻意的：同一批时长里可能既有阶段 2 标记又有阶段 3 标记，退回去会让已经识别过的机制重新按旧表上报。
  local function advancePhase(newPhaseCode)
    if newPhaseCode > phaseCode then
      phaseCode, rotationIndex = newPhaseCode, 1
    end
  end
  return {
    IsPhaseMarker = function(duration)
      local durationTenths = math.floor(duration * 10 + .5) / 10
      return durationTenths == 2.5 or durationTenths == 3 or durationTenths == 9
    end,
    PrepareBatch = function(batch)
      for index, entry in ipairs(batch) do
        local entryDurationTenths = math.floor(entry.duration * 10 + .5) / 10
        if entryDurationTenths == 2.5 then
          advancePhase(3)
        elseif entryDurationTenths == 3 or entryDurationTenths == 9 then
          advancePhase(2)
        end
      end
    end,
    Resolve = function(duration)
      local durationTenths = math.floor(duration * 10 + .5) / 10
      local mechanicKey
      if phaseCode == 1 and (durationTenths == 3 or durationTenths == 9) then
        advancePhase(2)
      end
      if durationTenths == 2.5 then
        advancePhase(3)
      elseif durationTenths == .5 then
        return nil
      elseif phaseCode == 3 then
        if durationTenths == 7.3 then
          mechanicKey = "lightfire"
        elseif durationTenths == 15.3 then
          mechanicKey = "grievous_thrash"
        elseif durationTenths == 23.3 then
          mechanicKey = "lightfall"
        elseif durationTenths == 31.1 or durationTenths == 31.3 then
          mechanicKey = "pulverizing_strikes"
        elseif durationTenths == 32 then
          mechanicKey = ROTATION_MECHANICS[(rotationIndex - 1) % 4 + 1]
        end
      elseif durationTenths == 5 or phaseCode == 1 and (durationTenths >= 19.9 and (durationTenths <= 21 and rotationIndex % 2 == 1)) then
        mechanicKey = "lightfire"
      elseif durationTenths == 18 or phaseCode == 1 and (durationTenths >= 19.9 and (durationTenths <= 21 and rotationIndex % 2 == 0)) then
        mechanicKey = "lightfall"
      elseif durationTenths == 3 or phaseCode == 2 and (durationTenths >= 19.9 and (durationTenths <= 21 and rotationIndex % 2 == 1)) then
        mechanicKey = "grievous_thrash"
      elseif durationTenths == 9 or phaseCode == 2 and (durationTenths >= 19.9 and (durationTenths <= 21 and rotationIndex % 2 == 0)) then
        mechanicKey = "pulverizing_strikes"
      end
      if durationTenths >= 20 and durationTenths <= 21 or durationTenths == 32 then
        rotationIndex = rotationIndex + 1
      end
      return mechanicKey, phaseCode
    end,
  }
end
-- 功能：构建注册键 320208（首领 3202 × 难度 8）的机制解析器——少数时长查固定表，50 秒按轮换表依次出四种机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：4 / 14 / 26 / 40 秒固定对应四个机制；50 秒每出现一次就把轮换序号往后推一格（越界回绕），保证同一时长反复出现时四种机制都能轮到。
local function createEncounter320208()
  local ROTATION_MECHANICS = { "awaken_lightbloom", "lightblooms_essence", "thornspike", "concentrated_lightbeam" }
  local MECHANIC_BY_DURATION = { [4] = ROTATION_MECHANICS[1], [14] = ROTATION_MECHANICS[2], [26] = ROTATION_MECHANICS[3], [40] = ROTATION_MECHANICS[4] }
  local rotationIndex = 0
  return {
    Resolve = function(duration)
      if duration == 50 then
        rotationIndex = rotationIndex % #ROTATION_MECHANICS + 1
        return ROTATION_MECHANICS[rotationIndex], 1
      end
      return MECHANIC_BY_DURATION[duration], 1
    end,
  }
end
-- 功能：构建注册键 319908（首领 3199 × 难度 8）的机制解析器——固定时长查表，40~45 秒那一档按轮换表出机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：5 / 8 / 20 / 35 秒固定对应四个机制；时长落在 40 秒之后、45 秒以内时按轮换序号取表，每出现一次推一格。
local function createEncounter319908()
  local ROTATION_MECHANICS = { "bedrock_slam", "thornblade", "lightsower_dash", "lightblossom_beam" }
  local MECHANIC_BY_DURATION = { [5] = ROTATION_MECHANICS[1], [8] = ROTATION_MECHANICS[2], [20] = ROTATION_MECHANICS[3], [35] = ROTATION_MECHANICS[4] }
  local rotationIndex = 0
  return {
    Resolve = function(duration)
      local durationRounded = math.floor(duration + .5)
      if durationRounded > 40 and durationRounded <= 45 then
        rotationIndex = rotationIndex % #ROTATION_MECHANICS + 1
        return ROTATION_MECHANICS[rotationIndex], 1
      end
      return MECHANIC_BY_DURATION[durationRounded], 1
    end,
  }
end
-- 功能：构建注册键 307408（首领 3074 × 难度 8）的机制解析器——固定时长查表，22 / 24 秒按轮换表出机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：3 / 9 / 15 秒固定对应三个机制；22 或 24 秒按轮换序号取表（越界回绕），只在这三个机制之间循环。
local function createEncounter307408()
  local ROTATION_MECHANICS = { "hulking_fragment", "devouring_entropy", "unstable_void_essence" }
  local MECHANIC_BY_DURATION = { [3] = ROTATION_MECHANICS[1], [9] = ROTATION_MECHANICS[2], [15] = ROTATION_MECHANICS[3] }
  local rotationIndex = 0
  return {
    Resolve = function(duration)
      local durationRounded = math.floor(duration + .5)
      if durationRounded == 22 or durationRounded == 24 then
        rotationIndex = rotationIndex % #ROTATION_MECHANICS + 1
        return ROTATION_MECHANICS[rotationIndex], 1
      end
      return MECHANIC_BY_DURATION[durationRounded], 1
    end,
  }
end
-- 功能：构建注册键 307308（首领 3073 × 难度 8）的机制解析器——按时间轴时长直接换算机制，5 秒那条头一次算另一种。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：5 秒第一次是 triplicate、之后都是 cosmic_sting（靠计数区分）；超过 60 秒的时长一律不上报。
local function createEncounter307308()
  local castCount = 0
  return {
    Resolve = function(duration)
      local durationTenths = math.floor(duration * 10 + .5) / 10
      if durationTenths > 60 then
        return nil, 1
      end
      if durationTenths == 5 then
        castCount = castCount + 1
        return castCount == 1 and "triplicate" or "cosmic_sting", 1
      elseif durationTenths == 8 then
        return "cosmic_sting", 1
      elseif durationTenths == 16 then
        return "neural_link", 1
      elseif durationTenths == 29 then
        return "astral_grasp", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 307208（首领 3072 × 难度 8）的机制解析器——按时间轴时长换算机制，重复出现的同名机制把上一次的事件 ID 交回给规划器。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 清理被顶替事件）。
-- 说明：7 / 29 秒对应 runic_mark，若与上一次同名机制的观测时间间隔小于 3 秒，就把上一次的 eventID 当第三个返回值返回——规划器据此退掉被顶替的旧事件，条上只留最新那次。超过 90 秒不上报。
local function createEncounter307208()
  local lastDuration, lastEventID, lastObservedAt = 0, nil, nil
  return {
    Resolve = function(duration, eventID, observedAt)
      local durationRounded = math.floor(duration + .5)
      if durationRounded > 90 then
        return nil, 1
      end
      if durationRounded == 7 or durationRounded == 29 then
        if durationRounded == lastDuration then
          return nil, 1
        end
        local replacementEventID
        if lastEventID and (lastObservedAt > 0 and observedAt > 0) then
          local elapsedSinceLast = observedAt - lastObservedAt
          if elapsedSinceLast >= 0 and elapsedSinceLast < 3 then
            replacementEventID = lastEventID
          end
        end
        lastDuration = durationRounded
        lastEventID, lastObservedAt = eventID, observedAt
        return "runic_mark", 1, replacementEventID
      elseif durationRounded == 17 then
        return "suppression_zone", 1
      elseif durationRounded == 26 then
        return "hastening_ward", 1
      elseif durationRounded == 51 then
        return "wave_of_silence", 1
      end
      return nil, 1
    end,
    OnEventClosed = function(eventID)
      if eventID == lastEventID then
        lastEventID, lastObservedAt = nil, nil
      end
    end,
  }
end
-- 功能：构建注册键 307108（首领 3071 × 难度 8）的机制解析器——活动中的事件不上报，只认刚落地的；并统计 repulsing_slam / arcane_expulsion 的剩余次数以判断能否再报。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 回滚计数）。
-- 说明：state 为 1（进行中）或本阶段已出现过同名机制时返回 nil，避免同一次机制被反复上报。22.5 / 23 秒那两条要看计数器是否还大于「轮次 × 2」，超出就不再报。45 / 48 秒是阶段分界：45 秒把阶段码复位成 1，48 秒把阶段码置 2 并让轮次 +1。
local function createEncounter307108()
  local phaseCode, cycleCount = 1, 1
  local mechanicCounters = { repulsing_slam = 1, arcane_expulsion = 1 }
  local mechanicByEventID = {}
  local resolvedMechanics, isRefuelingPhase = {}, false
  return {
    Resolve = function(duration, eventID, observedAt, state)
      if state == 1 or isRefuelingPhase then
        return nil, phaseCode
      end
      local durationTenths = math.floor(duration * 10 + .5) / 10
      local mechanicKey
      if durationTenths > 50 then
        return nil, phaseCode
      end
      if durationTenths == 5 or durationTenths == 22.5 then
        if durationTenths == 22.5 and mechanicCounters.repulsing_slam > cycleCount * 2 then
          return nil, phaseCode
        end
        mechanicKey = "repulsing_slam"
      elseif durationTenths == 15 or durationTenths == 23 then
        if durationTenths == 23 and mechanicCounters.arcane_expulsion > cycleCount * 2 then
          return nil, phaseCode
        end
        mechanicKey = "arcane_expulsion"
      elseif durationTenths == 22 then
        mechanicKey = "ethereal_shackles"
      elseif duration == 45 then
        mechanicKey = "refueling_protocol"
      end
      if state == nil then
        if duration == 45 or duration == 48 then
          isRefuelingPhase = true
        elseif mechanicKey then
          resolvedMechanics[mechanicKey] = true
        end
        return nil, phaseCode
      end
      if mechanicKey and resolvedMechanics[mechanicKey] then
        return nil, phaseCode
      end
      if duration == 45 then
        phaseCode = 1
      elseif duration == 48 then
        phaseCode, cycleCount = 2, cycleCount + 1
      end
      if mechanicKey and mechanicCounters[mechanicKey] then
        mechanicCounters[mechanicKey] = mechanicCounters[mechanicKey] + 1
        mechanicByEventID[eventID] = mechanicKey
      end
      return mechanicKey, phaseCode
    end,
    OnEventClosed = function(eventID, state, reason)
      if reason == "added" then
        return
      end
      local closedMechanic = mechanicByEventID[eventID]
      if not closedMechanic then
        return
      end
      mechanicByEventID[eventID] = nil
      if state == 3 then
        mechanicCounters[closedMechanic] = mechanicCounters[closedMechanic] - 1
      end
    end,
  }
end
-- 功能：构建注册键 349215（首领 3492 × 难度 15）的三阶段机制解析器——阶段 1 / 2 用一套时长表，2.5 是潜水等待段，阶段 3 换成另一套。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾、OnUnitEvent 处理可攻击状态变化）。
-- 说明：52 秒第一次是 mephitic_thrash、第二次才是 caustic_waves（靠计数区分）；118 / 129 秒是 rage_of_the_shackled，129 秒那次记下事件 ID，等它进入暂停状态后记一个 6.5 秒后的可攻击截止时刻。阶段 3 里 60 秒按出现次数依次给 circling_prey / call_of_the_serpent / submerge_p3 / serpents_bite，其余时长按新表查。
local function createEncounter349215()
  local phaseCode, isMarkedEventPaused = 1, false
  local durationCounts = {}
  local rageEventIDs, submergeEventIDs = {}, {}
  local targetableDeadline
  -- 功能：清空当前阶段的时长出现次数统计。
  -- 入参：无。
  -- 出参：无。
  -- 说明：每次推进阶段都必须清空——不清的话新阶段里同一条时长会被当成旧阶段的重复出现而被「首次不上报」的规则吃掉。
  local function resetDurationCounts()
    wipe(durationCounts)
  end
  -- 功能：阶段推进——新阶段码比当前大时才更新，并把轮换序号复位。
  -- 入参：newPhaseCode 新阶段码。
  -- 出参：无。
  -- 说明：只前不后是刻意的：同一批时长里可能既有阶段 2 标记又有阶段 3 标记，退回去会让已经识别过的机制重新按旧表上报。
  local function advancePhase(newPhaseCode)
    if newPhaseCode > phaseCode then
      phaseCode = newPhaseCode
      resetDurationCounts()
    end
  end
  -- 功能：把阶段 2 推进到 2.5（潜水等待段）并清空时长计数。
  -- 入参：无。
  -- 出参：无。
  -- 说明：只在阶段还小于 2.5 时生效，同时把「标记事件已暂停」的位置回 false；随后要靠 OnEventClosed 里的标记才能再推进到阶段 3，避免跳过潜水段。
  local function enterIntermission()
    if phaseCode < 2.5 then
      phaseCode, isMarkedEventPaused = 2.5, false
      resetDurationCounts()
    end
  end
  return {
    Resolve = function(duration, eventID)
      local durationRounded = math.floor(duration + .5)
      if phaseCode == 1 and durationRounded == 118 then
        advancePhase(2)
      elseif phaseCode == 2 and durationRounded == 10 then
        enterIntermission()
      elseif phaseCode == 2.5 and isMarkedEventPaused then
        advancePhase(3)
        isMarkedEventPaused = false
      end
      if phaseCode == 1 or phaseCode == 2 then
        local mechanicKey
        if durationRounded == 5 or durationRounded == 70 then
          mechanicKey = "gore_rattle"
        elseif durationRounded == 10 or durationRounded == 37 or durationRounded == 67 then
          mechanicKey = "mothers_wrath"
        elseif durationRounded == 20 or durationRounded == 94 or durationRounded == 95 then
          mechanicKey = "spectral_coils"
        elseif durationRounded == 35 then
          mechanicKey = "mephitic_thrash"
        elseif durationRounded == 42 then
          mechanicKey = "caustic_waves"
        elseif durationRounded == 62 then
          mechanicKey = "submerge_p1"
        elseif durationRounded == 72 then
          mechanicKey = "call_of_the_serpent"
        elseif durationRounded == 129 or durationRounded == 118 then
          mechanicKey = "rage_of_the_shackled"
          if phaseCode == 1 and durationRounded == 129 then
            rageEventIDs[eventID] = true
          end
        elseif durationRounded == 52 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          if durationCounts[durationRounded] == 1 then
            mechanicKey = "mephitic_thrash"
          elseif durationCounts[durationRounded] == 2 then
            mechanicKey = "caustic_waves"
          end
        elseif durationRounded == 30 or durationRounded == 40 then
          mechanicKey = "virulent_spit"
        end
        return mechanicKey, phaseCode
      end
      if phaseCode == 2.5 then
        if durationRounded == 10 then
          submergeEventIDs[eventID] = true
        end
        return nil, 2
      end
      durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
      local occurrenceCount = durationCounts[durationRounded]
      if (durationRounded == 235 or durationRounded == 205 or durationRounded == 67 or durationRounded == 60 or durationRounded == 50 or durationRounded == 25 or durationRounded == 10 or durationRounded == 5) and occurrenceCount == 1 then
        return nil, 3
      end
      if durationRounded == 235 then
        return "fury_unleashed", 3
      end
      if durationRounded == 205 then
        return "rage_of_the_shackled", 3
      end
      if durationRounded == 5 or durationRounded == 30 or durationRounded == 45 then
        return "call_of_the_serpent", 3
      end
      if durationRounded == 10 or durationRounded == 75 or durationRounded == 76 then
        return "mothers_wrath", 3
      end
      if durationRounded == 25 or durationRounded == 71 or durationRounded == 37 then
        return "serpents_bite", 3
      end
      if durationRounded == 50 or durationRounded == 55 or durationRounded == 44 then
        return "caustic_waves", 3
      end
      if durationRounded == 51 or durationRounded == 61 or durationRounded == 52 then
        return "circling_prey", 3
      end
      if durationRounded == 67 or durationRounded == 53 then
        return "submerge_p3", 3
      end
      if durationRounded == 60 then
        if occurrenceCount == 2 then
          return "circling_prey", 3
        end
        if occurrenceCount == 3 then
          return "call_of_the_serpent", 3
        end
        if occurrenceCount == 4 then
          return "submerge_p3", 3
        end
        if occurrenceCount == 5 then
          return "serpents_bite", 3
        end
      end
      return nil, 3
    end,
    OnEventClosed = function(eventID, state)
      if rageEventIDs[eventID] then
        rageEventIDs[eventID] = nil
        if state == 2 and phaseCode == 1 then
          targetableDeadline = GetTimePreciseSec() + 6.5
        end
      end
      if submergeEventIDs[eventID] then
        submergeEventIDs[eventID] = nil
        if state == 2 and phaseCode == 2.5 then
          isMarkedEventPaused = true
        end
      end
    end,
    OnUnitEvent = function(eventName, now)
      if eventName == "UNIT_TARGETABLE_CHANGED" and (phaseCode == 1 and (targetableDeadline and (now >= targetableDeadline and (type(UnitCanAttack) == "function" and UnitCanAttack("player", "boss1") == false)))) then
        advancePhase(2)
        targetableDeadline = nil
      end
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[347015] = {
  Create = createEncounter347015,
  mechanicCodes = { essence_rend = 1, possession_barrage = 2, restless_amani = 3 },
  unitEvents = { "UNIT_SPELLCAST_START", "UNIT_SPELLCAST_SUCCEEDED", "UNIT_SPELLCAST_CHANNEL_START" },
}
WowBuddyDev.TimelinePlannerEncounters[320108] = {
  Create = createEncounter320108,
  batchSeconds = .1,
  mechanicCodes = { lightfire = 1, lightfall = 2, grievous_thrash = 3, pulverizing_strikes = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[320208] = {
  Create = createEncounter320208,
  countIdentifiableAdds = true,
  mechanicCodes = { awaken_lightbloom = 1, lightblooms_essence = 2, thornspike = 3, concentrated_lightbeam = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[319908] = {
  Create = createEncounter319908,
  countIdentifiableAdds = true,
  mechanicCodes = { bedrock_slam = 1, thornblade = 2, lightsower_dash = 3, lightblossom_beam = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[307408] = {
  Create = createEncounter307408,
  countIdentifiableAdds = true,
  mechanicCodes = { hulking_fragment = 1, devouring_entropy = 2, unstable_void_essence = 3 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[307308] = {
  Create = createEncounter307308,
  countIdentifiableAdds = true,
  mechanicCodes = { triplicate = 1, cosmic_sting = 2, neural_link = 3, astral_grasp = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[307208] = {
  Create = createEncounter307208,
  countIdentifiableAdds = true,
  mechanicCodes = { runic_mark = 1, suppression_zone = 2, hastening_ward = 3, wave_of_silence = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[307108] = {
  Create = createEncounter307108,
  countIdentifiableAdds = true,
  mechanicCodes = { repulsing_slam = 1, arcane_expulsion = 2, ethereal_shackles = 3, refueling_protocol = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[349215] = {
  Create = createEncounter349215,
  countIdentifiableAdds = true,
  mechanicCodes = {
    gore_rattle = 1,
    mothers_wrath = 2,
    spectral_coils = 3,
    mephitic_thrash = 4,
    caustic_waves = 5,
    submerge_p1 = 6,
    call_of_the_serpent = 7,
    rage_of_the_shackled = 8,
    virulent_spit = 9,
    fury_unleashed = 10,
    serpents_bite = 11,
    circling_prey = 12,
    submerge_p3 = 13,
  },
  unitEvents = { "UNIT_TARGETABLE_CHANGED" },
}
