-- ==========================================================================
-- 文件：001fcd.lua
-- 来源：P07483180.rar → P07483180/001fcd.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：001fcd.lua → TimelineData_2.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
WowBuddyDev.TimelinePlannerEncounters = WowBuddyDev.TimelinePlannerEncounters or {}
-- 功能：构建注册键 344515（首领 3445 × 难度 15）的机制解析器——按时间轴时长换算毒液系机制，并对会反复出现的时长做「本阶段只认第 3 次以后」的封顶。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾）。
-- 说明：20 秒的 vitriolic_stasis 上报后记下事件 ID，等它进入暂停状态时把「可以转阶段」的位置真，下一次 Resolve 才把阶段码 +1 并清空计数——首领这一段打不完就不能进下一阶段。
local function createEncounter344515()
  local phaseCode, isVitriolicClosed = 1, false
  local durationCounts, vitriolicEventIDs = {}, {}
  local REPEAT_CAPPED_DURATIONS = { [12] = true, [8] = true, [4] = true, [16] = true, [40] = true, [6] = true }
  -- 功能：清空当前阶段的时长出现次数统计。
  -- 入参：无。
  -- 出参：无。
  -- 说明：阶段切换时清空，新阶段的同一条时长才会重新从头计数，不会被上一阶段的次数顶到封顶线上。
  local function resetDurationCounts()
    wipe(durationCounts)
  end
  -- 功能：毒液系阶段推进——把阶段码 +1 并清空时长计数。
  -- 入参：无（只认上一次战斗里置的「vitriolic_stasis 已暂停」标记）。
  -- 出参：无。
  -- 说明：在每次 Resolve 开头调用；标记一次只生效一次，处理完立刻置回 false，避免同一次暂停被反复推进阶段。
  local function advancePhase()
    if isVitriolicClosed then
      phaseCode, isVitriolicClosed = phaseCode + 1, false
      resetDurationCounts()
    end
  end
  return {
    Resolve = function(duration, eventID)
      advancePhase()
      local durationTenths = math.floor(duration * 10 + .5) / 10
      local durationRounded = math.floor(durationTenths + .5)
      durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
      if phaseCode > 1 and (REPEAT_CAPPED_DURATIONS[durationRounded] and durationCounts[durationRounded] < 3) then
        return nil, phaseCode
      end
      local mechanicKey
      if durationRounded == 12 or durationRounded == 32 then
        mechanicKey = "toxic_droplets"
      elseif durationRounded == 8 or durationRounded == 10 or durationTenths == 51.5 then
        mechanicKey = "venom_coagulation"
      elseif durationRounded == 4 then
        mechanicKey = "empowering_slam"
      elseif durationRounded == 16 or durationRounded == 41 then
        mechanicKey = "unstable_miasma"
      elseif durationRounded == 40 or durationRounded == 52 then
        mechanicKey = "blighted_blood"
      elseif durationRounded == 6 then
        mechanicKey = "bloodvenom_injection"
      elseif durationRounded == 15 then
        mechanicKey = "berserk"
      elseif durationRounded == 20 then
        mechanicKey = "vitriolic_stasis"
        vitriolicEventIDs[eventID] = true
      end
      return mechanicKey, phaseCode
    end,
    OnEventClosed = function(eventID, state)
      if not vitriolicEventIDs[eventID] then
        return
      end
      vitriolicEventIDs[eventID] = nil
      if state == 2 then
        isVitriolicClosed = true
      end
    end,
  }
end
-- 功能：构建注册键 349715（首领 3497 × 难度 8）的四阶段机制解析器——每批时长里探测阶段标记，四个阶段各有一套时长表。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（IsPhaseMarker 恒真、PrepareBatch 按整批时长定阶段、Resolve 判定机制、OnUnitEvent 处理引导事件）。
-- 说明：批次里出现 60 / 27 / 11 / 16 秒（±0.5 秒）就分别切到阶段 1 / 2 / 3 / 4，并要求整批至少 3 条事件才敢定阶段；阶段一变就清空时长计数。boss2 的引导开始会记下技能 ID，同一条引导结束时把阶段复位回 1。
local function createEncounter349715()
  local phaseCode, durationCounts, channelSpellID = 1, {}, nil
  -- 功能：清空当前阶段的时长出现次数统计。
  -- 入参：无。
  -- 出参：无。
  -- 说明：阶段切换时清空，新阶段的同一条时长才会重新从头计数，不会被上一阶段的次数顶到封顶线上。
  local function resetDurationCounts()
    wipe(durationCounts)
  end
  -- 功能：判断一批事件里有没有哪个时长落在目标秒数的 ±0.5 秒内。
  -- 入参：batch 本批事件表（每项带 duration）；targetDuration 目标秒数。
  -- 出参：true 命中；false 没命中。
  -- 说明：用区间而不是等值比较，因为时间轴时长是浮点秒，直接比等值会漏判。
  local function batchHasDuration(batch, targetDuration)
    for index, entry in ipairs(batch) do
      if entry.duration > targetDuration - .5 and entry.duration < targetDuration + .5 then
        return true
      end
    end
    return false
  end
  -- 功能：按一批事件里的标记时长判定首领当前处在第几阶段。
  -- 入参：batch 本批事件表（每项带 duration）。
  -- 出参：1 / 2 / 3 / 4 阶段码；判不出来返回 nil。
  -- 说明：整批少于 3 条时不做判断（样本太少容易误判）；60 秒对应阶段 1、27 秒阶段 2、11 秒阶段 3、16 秒阶段 4，按顺序先命中先返回。
  local function detectPhase(batch)
    if #batch < 3 then
      return nil
    end
    if batchHasDuration(batch, 60) then
      return 1
    end
    if batchHasDuration(batch, 27) then
      return 2
    end
    if batchHasDuration(batch, 11) then
      return 3
    end
    if batchHasDuration(batch, 16) then
      return 4
    end
  end
  -- 功能：读一个可能被客户端标记成机密（secret）的技能 ID。
  -- 入参：value 待读的值。
  -- 出参：原值（字符串或数字）；机密值、其它类型、nan 一律返回 nil。
  -- 说明：机密值一碰就抛错，所以先过 issecretvalue；只放行字符串和数字，别让 table 之类的脏值进到后面的相等比较里。
  local function readableSpellID(value)
    if issecretvalue(value) then
      return nil
    end
    local valueType = type(value)
    if valueType == "string" then
      return value
    end
    if valueType == "number" and value == value then
      return value
    end
    return nil
  end
  return {
    IsPhaseMarker = function()
      return true
    end,
    PrepareBatch = function(batch)
      local detectedPhase = detectPhase(batch)
      if detectedPhase and detectedPhase ~= phaseCode then
        phaseCode = detectedPhase
        resetDurationCounts()
      end
    end,
    Resolve = function(duration)
      local durationRounded = math.floor(duration + .5)
      local mechanicKey
      if phaseCode == 1 then
        if durationRounded == 60 then
          mechanicKey = "final_ascension"
        elseif durationRounded == 20 or durationRounded == 4 or durationRounded == 27 or durationRounded == 23 then
          mechanicKey = "throw_junk"
        elseif durationRounded == 30 then
          mechanicKey = "shredding_shards"
        elseif durationRounded == 10 then
          mechanicKey = "blink_nova"
        elseif durationRounded == 18 or durationRounded == 16 or durationRounded == 15 then
          mechanicKey = "shell_spin"
        elseif durationRounded == 5 then
          mechanicKey = "icebound_flames"
        elseif durationRounded == 31 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          mechanicKey = durationCounts[durationRounded] % 2 == 1 and "icebound_flames" or "blink_nova"
        end
      elseif phaseCode == 2 then
        if durationRounded == 30 then
          mechanicKey = "shredding_shards"
        elseif durationRounded == 2 or durationRounded == 16 then
          mechanicKey = "icebound_flames"
        elseif durationRounded == 3 then
          mechanicKey = "mushroom_toss"
        elseif durationRounded == 27 or durationRounded == 4 then
          mechanicKey = "throw_junk"
        elseif durationRounded == 13 then
          mechanicKey = "explosive_surprise"
        elseif durationRounded == 11 or durationRounded == 17 or durationRounded == 15 or durationRounded == 7 then
          mechanicKey = "shell_spin"
        elseif durationRounded == 32 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          local occurrenceCount = durationCounts[durationRounded]
          if occurrenceCount == 1 then
            mechanicKey = "mushroom_toss"
          elseif occurrenceCount == 2 then
            mechanicKey = "shell_spin"
          elseif occurrenceCount == 3 then
            mechanicKey = "explosive_surprise"
          elseif occurrenceCount == 4 then
            mechanicKey = "icebound_flames"
          end
        end
      elseif phaseCode == 3 then
        if durationRounded == 20 or durationRounded == 4 or durationRounded == 27 then
          mechanicKey = "throw_junk"
        elseif durationRounded == 3 or durationRounded == 32 then
          mechanicKey = "mighty_thud"
        elseif durationRounded == 30 then
          mechanicKey = "shredding_shards"
        elseif durationRounded == 11 or durationRounded == 5 or durationRounded == 22 then
          mechanicKey = "icebound_flames"
        end
      elseif phaseCode == 4 then
        if durationRounded == 7 or durationRounded == 4 or durationRounded == 11 or durationRounded == 23 then
          mechanicKey = "throw_junk"
        elseif durationRounded == 30 then
          mechanicKey = "shredding_shards"
        elseif durationRounded == 21 then
          mechanicKey = "blink_nova"
        elseif durationRounded == 2 or durationRounded == 13 then
          mechanicKey = "icebound_flames"
        elseif durationRounded == 17 or durationRounded == 16 then
          mechanicKey = "shell_spin"
        elseif durationRounded == 8 then
          mechanicKey = "frostfire_volley"
        elseif durationRounded == 27 then
          durationCounts[durationRounded] = (durationCounts[durationRounded] or 0) + 1
          local occurrenceIndex = durationCounts[durationRounded]
          if occurrenceIndex == 1 then
            mechanicKey = "frostfire_volley"
          elseif occurrenceIndex == 2 then
            mechanicKey = "icebound_flames"
          elseif occurrenceIndex == 3 then
            mechanicKey = "shell_spin"
          end
        end
      end
      return mechanicKey, phaseCode
    end,
    OnUnitEvent = function(eventName, now, unit, spellID)
      if unit ~= "boss2" then
        return
      end
      local readableID = readableSpellID(spellID)
      if eventName == "UNIT_SPELLCAST_CHANNEL_START" then
        channelSpellID = readableID
      elseif eventName == "UNIT_SPELLCAST_CHANNEL_STOP" and (readableID and readableID == channelSpellID) then
        channelSpellID = nil
        if phaseCode ~= 1 then
          phaseCode = 1
          resetDurationCounts()
        end
      end
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[344515] = {
  Create = createEncounter344515,
  countIdentifiableAdds = true,
  mechanicCodes = {
    venom_coagulation = 1,
    toxic_droplets = 2,
    empowering_slam = 3,
    bloodvenom_injection = 4,
    blighted_blood = 5,
    unstable_miasma = 6,
    vitriolic_stasis = 7,
    berserk = 8,
  },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[349715] = {
  Create = createEncounter349715,
  batchSeconds = .1,
  countIdentifiableAdds = true,
  mechanicCodes = {
    final_ascension = 1,
    blink_nova = 2,
    icebound_flames = 3,
    shredding_shards = 4,
    frostfire_volley = 5,
    shell_spin = 6,
    mighty_thud = 7,
    throw_junk = 8,
    mushroom_toss = 9,
    explosive_surprise = 10,
  },
  unitEvents = { "UNIT_SPELLCAST_CHANNEL_START", "UNIT_SPELLCAST_CHANNEL_STOP" },
  unitEventUnits = { UNIT_SPELLCAST_CHANNEL_START = { "boss2" }, UNIT_SPELLCAST_CHANNEL_STOP = { "boss2" } },
}
