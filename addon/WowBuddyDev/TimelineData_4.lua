-- ==========================================================================
-- 文件：47d6bd.lua
-- 来源：P07483180.rar → P07483180/47d6bd.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：47d6bd.lua → TimelineData_4.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
-- 功能：把浮点秒数换算成数据表里用的整数秒（先四舍五入到 0.1，再取整）。
-- 入参：value 待换算的秒数。
-- 出参：整数秒。
-- 说明：比直接四舍五入多一层 0.1 的收敛，是为了跟写表时的口径一致——时间轴时长拆批到达时有 0.1 秒级抖动，先归到 0.1 再进整数，边界上不会差 1 秒。
local function roundDuration(value)
  local tenthsRounded = math.floor(value * 10 + .5) / 10
  return math.floor(tenthsRounded + .5)
end
-- 功能：构建注册键 342115（首领 3421 × 难度 15）的机制解析器——固定时长查表，6 秒和 68 秒这两条按出现次数切换 / 轮转机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：6 秒按出现次数奇偶在 sanguine_storm 与 vile_flood 之间交替；68 秒沿 6 条机制的轮换表依次取（越界回绕），保证反复出现时六种机制都能轮到。
local function createEncounter342115()
  local durationCounts = {}
  local ROTATION_MECHANICS = {
    "caustic_deluge",
    "stone_breaker",
    "venomous_emergence",
    "coiling_ichor",
    "stir_the_depths",
    "ravenous_feast",
  }
  return {
    Resolve = function(duration)
      local durationRounded = roundDuration(duration)
      local mechanicKey
      if durationRounded == 144 then
        mechanicKey = "submerge"
      elseif durationRounded == 6 then
        durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
        mechanicKey = durationCounts[durationRounded] % 2 == 1 and "sanguine_storm" or "vile_flood"
      elseif durationRounded == 44 then
        mechanicKey = "coiling_ichor"
      elseif durationRounded == 63 then
        mechanicKey = "ravenous_feast"
      elseif durationRounded == 20 or durationRounded == 22 then
        mechanicKey = "stone_breaker"
      elseif durationRounded == 37 then
        mechanicKey = "venomous_emergence"
      elseif durationRounded == 9 then
        mechanicKey = "caustic_deluge"
      elseif durationRounded == 52 then
        mechanicKey = "stir_the_depths"
      elseif durationRounded == 68 then
        durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
        mechanicKey = ROTATION_MECHANICS[(durationCounts[durationRounded] - 1) % #ROTATION_MECHANICS + 1]
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 342915（首领 3429 × 难度 15）的三阶段机制解析器——阶段 1 记录「盘蛇祭坛之牙」事件后进入阶段 2，阶段 2 的「永恒夜幕」事件暂停后再靠 boss2 的引导事件推进到阶段 3。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（IsPhaseMarker 判阶段标记时长、PrepareBatch 纠正阶段、Resolve 判定机制、OnEventClosed 观测事件收尾、OnUnitEvent 处理引导事件）。
-- 说明：阶段 1 里记下转阶段那一刻的斧磨者（12 秒）计数，如果同一批里又出现斧磨者让计数超过它，就取消这次转阶段——首领还在放斧磨者说明没真进阶段 2。阶段 2.5 是潜水过渡段，期间不报机制。
local function createEncounter342915()
  local STATE_PAUSED, STATE_FINISHED = 2, 3
  local phaseCode = 1
  local durationCounts = {}
  local fangsEventIDs, nightfallEventIDs = {}, {}
  local isFangsPending, fangsOccurrence = false, nil
  local isNightfallPaused = false
  local axegrinderCount, fangsCount = 1, 1
  local PHASE_MARKER_DURATIONS = { [6] = true, [13] = true, [22] = true, [31] = true, [33] = true, [34] = true, [38] = true, [70] = true }
  -- 功能：清空当前阶段的时长出现次数统计。
  -- 入参：无。
  -- 出参：无。
  -- 说明：每次推进阶段都要清空，新阶段的同一条时长才会重新计数，不会被上一阶段的次数顶到封顶线上。
  local function resetDurationCounts()
    wipe(durationCounts)
  end
  -- 功能：阶段推进——新阶段码比当前大时才更新，并清空时长计数。
  -- 入参：newPhaseCode 新阶段码。
  -- 出参：无。
  -- 说明：只前不后是刻意的：同一批时长里可能同时出现阶段 2 和阶段 3 的标记，退回去会让已经识别过的机制按旧表重报一次。
  local function advancePhase(newPhaseCode)
    if newPhaseCode > phaseCode then
      phaseCode = newPhaseCode
      resetDurationCounts()
    end
  end
  -- 功能：把阶段 2 推进到 2.5（潜水过渡段）并清空时长计数。
  -- 入参：无。
  -- 出参：无。
  -- 说明：只在阶段还等于 2 时生效，同时把「夜幕事件已暂停」的位置回 false；随后要靠 OnEventClosed 里的标记才能再推进到阶段 3，避免跳过过渡段。
  local function enterIntermission()
    if phaseCode == 2 then
      phaseCode = 2.5
      isNightfallPaused = false
      resetDurationCounts()
    end
  end
  return {
    IsPhaseMarker = function(duration)
      local durationRounded = roundDuration(duration)
      return phaseCode == 1 and (durationRounded ~= 70 and PHASE_MARKER_DURATIONS[durationRounded] == true)
    end,
    PrepareBatch = function(batch)
      if phaseCode ~= 1 or not isFangsPending or not fangsOccurrence then
        return
      end
      local axegrinderInBatch = 0
      for index, entry in ipairs(batch) do
        if roundDuration(entry.duration) == 12 then
          axegrinderInBatch = axegrinderInBatch + 1
        end
      end
      if axegrinderCount + axegrinderInBatch > fangsOccurrence then
        isFangsPending, fangsOccurrence = false, nil
      end
    end,
    Resolve = function(duration, eventID)
      local durationRounded = roundDuration(duration)
      if phaseCode == 1 and (isFangsPending and PHASE_MARKER_DURATIONS[durationRounded]) then
        advancePhase(2)
        isFangsPending = false
      end
      local mechanicKey
      if phaseCode == 1 then
        if durationRounded == 2 then
          mechanicKey = "toxic_deluge"
        elseif durationRounded == 12 then
          axegrinderCount = axegrinderCount + 1
          mechanicKey = "axegrinder"
        elseif durationRounded == 28 or durationRounded == 35 then
          mechanicKey = "venomfang"
        elseif durationRounded == 43 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          mechanicKey = durationCounts[durationRounded] % 2 == 1 and "guillotine" or "toxic_deluge"
        elseif durationRounded == 20 or durationRounded == 17 or durationRounded == 21 or durationRounded == 16 then
          mechanicKey = "sever"
        elseif durationRounded == 85 then
          fangsCount = fangsCount + 1
          fangsEventIDs[eventID] = fangsCount
          mechanicKey = "fangs_of_the_coiled_altar"
        end
      elseif phaseCode == 2 then
        if durationRounded == 13 or durationRounded == 33 then
          mechanicKey = "spiritcackle"
        elseif durationRounded == 70 then
          nightfallEventIDs[eventID] = true
          mechanicKey = "eternal_nightfall"
        elseif durationRounded == 6 then
          mechanicKey = "dreadmarch"
        elseif durationRounded == 22 or durationRounded == 38 then
          mechanicKey = "gloombomb"
        elseif durationRounded == 31 then
          mechanicKey = "soul_sever"
        elseif durationRounded == 34 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          mechanicKey = durationCounts[durationRounded] % 2 == 1 and "soul_sever" or "dreadmarch"
        end
      elseif phaseCode == 3 then
        if durationRounded == 61 or durationRounded == 101 or durationRounded == 44 or durationRounded == 108 then
          mechanicKey = "dreadmarch"
        elseif durationRounded == 39 or durationRounded == 100 then
          mechanicKey = "eternal_nightfall"
        elseif durationRounded == 26 or durationRounded == 51 or durationRounded == 67 or durationRounded == 86 then
          mechanicKey = "gloombomb"
        elseif durationRounded == 2 or durationRounded == 47 or durationRounded == 57 or durationRounded == 43 or durationRounded == 62 then
          mechanicKey = "toxic_deluge"
        elseif durationRounded == 32 or durationRounded == 34 or durationRounded == 38 then
          mechanicKey = "blighted_sever"
        elseif durationRounded == 17 or durationRounded == 170 then
          mechanicKey = "grim_guillotine"
        elseif durationRounded == 106 or durationRounded == 105 then
          mechanicKey = "defilement_of_the_coiled_altar"
        elseif durationRounded == 33 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          local occurrenceCount = durationCounts[durationRounded]
          if occurrenceCount == 1 or occurrenceCount == 3 then
            mechanicKey = "blighted_sever"
          elseif occurrenceCount == 2 then
            mechanicKey = "gloombomb"
          end
        elseif durationRounded == 60 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          local occurrenceIndex = durationCounts[durationRounded]
          if occurrenceIndex == 1 then
            mechanicKey = "defilement_of_the_coiled_altar"
          elseif occurrenceIndex == 2 then
            mechanicKey = "toxic_deluge"
          end
        end
      end
      return mechanicKey, phaseCode == 2.5 and 2 or phaseCode
    end,
    OnEventClosed = function(eventID, state)
      local closedFangsOccurrence = fangsEventIDs[eventID]
      if closedFangsOccurrence then
        fangsEventIDs[eventID] = nil
        if state == STATE_FINISHED and phaseCode == 1 then
          isFangsPending, fangsOccurrence = true, closedFangsOccurrence
          if axegrinderCount > closedFangsOccurrence then
            isFangsPending, fangsOccurrence = false, nil
          end
        end
      end
      if nightfallEventIDs[eventID] then
        nightfallEventIDs[eventID] = nil
        if phaseCode == 2 then
          if state == STATE_FINISHED then
            enterIntermission()
          elseif state == STATE_PAUSED then
            isNightfallPaused = true
          end
        end
      end
    end,
    OnUnitEvent = function(eventName, now, unit)
      if unit ~= "boss2" then
        return
      end
      if eventName == "UNIT_SPELLCAST_CHANNEL_START" and (phaseCode == 2 and isNightfallPaused) then
        enterIntermission()
      elseif eventName == "UNIT_SPELLCAST_CHANNEL_STOP" and phaseCode == 2.5 then
        advancePhase(3)
      end
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[342115] = {
  Create = createEncounter342115,
  countIdentifiableAdds = true,
  mechanicCodes = {
    caustic_deluge = 1,
    sanguine_storm = 2,
    vile_flood = 3,
    coiling_ichor = 4,
    ravenous_feast = 5,
    stone_breaker = 6,
    venomous_emergence = 7,
    stir_the_depths = 8,
    submerge = 9,
  },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[342915] = {
  Create = createEncounter342915,
  batchSeconds = .1,
  countIdentifiableAdds = true,
  mechanicCodes = {
    fangs_of_the_coiled_altar = 1,
    toxic_deluge = 2,
    axegrinder = 3,
    venomfang = 4,
    guillotine = 5,
    sever = 6,
    spiritcackle = 7,
    eternal_nightfall = 8,
    dreadmarch = 9,
    gloombomb = 10,
    soul_sever = 11,
    defilement_of_the_coiled_altar = 12,
    grim_guillotine = 13,
    blighted_sever = 14,
  },
  unitEvents = { "UNIT_SPELLCAST_CHANNEL_START", "UNIT_SPELLCAST_CHANNEL_STOP" },
  unitEventUnits = { UNIT_SPELLCAST_CHANNEL_START = { "boss2" }, UNIT_SPELLCAST_CHANNEL_STOP = { "boss2" } },
}
