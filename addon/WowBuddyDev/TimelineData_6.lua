-- ==========================================================================
-- 文件：b57042.lua
-- 来源：P07483180.rar → P07483180/b57042.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：b57042.lua → TimelineData_6.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
WowBuddyDev.TimelinePlannerEncounters = WowBuddyDev.TimelinePlannerEncounters or {}
-- 功能：按指定小数位对秒数四舍五入（本文件统一的时长取整口径）。
-- 入参：value 待取整的秒数；decimals 保留的小数位数。
-- 出参：取整后的数。
-- 说明：scale 取 10 的 decimals 次幂；多数机制表按整数秒写（decimals = 0），少数按 0.1 秒写（decimals = 1），所以取整精度必须逐处指定，不能写死。
local function roundToDecimals(value, decimals)
  local scale = 10 ^ decimals
  return math.floor(value * scale + .5) / scale
end
-- 功能：构建注册键 213908（首领 2139 × 难度 8）的机制解析器——按时间轴时长换算机制，25 秒那条按出现次数交替。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：25 秒按出现次数奇偶在 spit_gold 与 tail_thrash 之间交替；5 秒是 spit_gold，14 / 28 秒是 serpentine_gust，54 秒是 lucres_call。
local function createEncounter213908()
  local castCount = 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToDecimals(duration, 0)
      local mechanicKey
      if durationRounded == 5 or durationRounded == 25 and castCount % 2 == 1 then
        mechanicKey = "spit_gold"
      elseif durationRounded == 8 or durationRounded == 25 and castCount % 2 == 0 then
        mechanicKey = "tail_thrash"
      elseif durationRounded == 14 or durationRounded == 28 then
        mechanicKey = "serpentine_gust"
      elseif durationRounded == 54 then
        mechanicKey = "lucres_call"
      end
      if durationRounded == 25 then
        castCount = castCount + 1
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 214208（首领 2142 × 难度 8）的机制解析器——先在「吸取体液」那一套时长表里报机制，被埋葬（entomb）后切到另一套，等事件暂停再切回来。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾）。
-- 说明：entomb 时记下事件 ID 和「观测时间 + 1 秒」的截止时刻，时刻一到就翻到另一套表；等 entomb 事件进入暂停状态再翻回「吸取体液」。每次 Resolve 开头先清过期记录，不清的话阶段永远切不回来。63 秒一律不上报。
local function createEncounter214208()
  local isDrainPhase, entombDeadlines, entombEventIDs = true, {}, {}
  -- 功能：把已经到点的埋葬截止时刻清掉，并顺手把阶段位翻到另一套时长表。
  -- 入参：now 当前时间（秒）；不是数字就直接返回。
  -- 出参：无。
  -- 说明：遍历截止时刻表，凡是不晚于 now 的记录都删掉并把阶段位翻过去——同一轮里有多条过期记录也一起清。
  local function expireEntombDeadlines(now)
    if type(now) ~= "number" then
      return
    end
    for eventID, deadline in pairs(entombDeadlines) do
      if now >= deadline then
        isDrainPhase, entombDeadlines[eventID] = false, nil
      end
    end
  end
  -- 功能：取当前时间（秒），只用高精度时钟 GetTimePreciseSec。
  -- 入参：无。
  -- 出参：秒数；客户端没有这个 API、pcall 失败、或读出来不是合法数字时返回 nil。
  -- 说明：观测时间要和客户端时间轴事件的时间戳对齐，所以宁可返回 nil 也不用低精度时钟顶替——时间对不上会把 cutoff 判早，机制就漏报了。
  local function nowSeconds()
    if type(GetTimePreciseSec) ~= "function" then
      return nil
    end
    local ok, value = pcall(GetTimePreciseSec)
    return ok and (type(value) == "number" and (value == value and value)) or nil
  end
  return {
    Resolve = function(duration, eventID, observedAt)
      expireEntombDeadlines(observedAt)
      local durationRounded = roundToDecimals(duration, 0)
      local mechanicKey
      if durationRounded == 63 then
        return nil, 1
      elseif isDrainPhase and durationRounded == 5 or not isDrainPhase and durationRounded == 32 then
        mechanicKey = "drain_fluids"
      elseif isDrainPhase and durationRounded == 20 or not isDrainPhase and durationRounded == 30 then
        mechanicKey = "burn_corruption"
      elseif isDrainPhase and durationRounded == 30 or not isDrainPhase and durationRounded == 102 then
        mechanicKey = "awakening_slam"
      elseif durationRounded == 60 then
        mechanicKey = "entomb"
        entombEventIDs[eventID] = true
        if type(observedAt) == "number" then
          entombDeadlines[eventID] = observedAt + 1
        end
      end
      return mechanicKey, 1
    end,
    OnEventClosed = function(eventID, state, reason)
      if not entombEventIDs[eventID] or reason ~= "state_changed" then
        return
      end
      expireEntombDeadlines(nowSeconds())
      if state == 2 then
        isDrainPhase, entombDeadlines[eventID] = true, nil
      elseif state == 3 then
        entombDeadlines[eventID] = nil
      end
      entombEventIDs[eventID] = nil
    end,
  }
end
-- 功能：构建注册键 214008（首领 2140 × 难度 8）的机制解析器——按 0.1 秒精度的时长表换算机制，并用「冲撞」事件推进阶段码。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾）。
-- 说明：isBarrelPhase 为真时 20 秒算 barrel_through（并把阶段码升到 2），紧接着的 arc_lightning 再把阶段码升到 3；阶段位为假时 20 秒落到 call_of_the_elements。冲撞这一轮报过之后再遇到同类事件只做记录不重复上报。
local function createEncounter214008()
  local isBarrelPhase, phaseCode, barrelEventIDs = true, 1, {}
  return {
    Resolve = function(duration, eventID)
      local durationTenths = roundToDecimals(duration, 1)
      local mechanicKey
      if durationTenths == 8 or durationTenths == 14.8 then
        mechanicKey = "whirling_axes"
      elseif durationTenths == 15 or durationTenths == 16.5 then
        mechanicKey = "severing_axe"
      elseif durationTenths == 5 or isBarrelPhase and durationTenths == 20 then
        mechanicKey = "barrel_through"
      elseif durationTenths == 14 or durationTenths == 22 then
        mechanicKey = "debilitating_backhand"
      elseif durationTenths == 2 or durationTenths == 7 then
        mechanicKey = "arc_lightning"
      elseif durationTenths == 10 or durationTenths == 24 or durationTenths == 24.4 or durationTenths == 25.2 then
        mechanicKey = "poison_nova"
      elseif durationTenths == 20 or durationTenths == 52.5 then
        mechanicKey = "call_of_the_elements"
      end
      if mechanicKey == "barrel_through" then
        if phaseCode == 1 then
          phaseCode = 2
        end
        barrelEventIDs[eventID] = true
      elseif mechanicKey == "arc_lightning" and phaseCode == 2 then
        phaseCode = 3
      end
      return mechanicKey, phaseCode
    end,
    OnEventClosed = function(eventID, state, reason)
      if barrelEventIDs[eventID] and (reason == "state_changed" and state == 3) then
        isBarrelPhase = false
      end
      if reason ~= "added" then
        barrelEventIDs[eventID] = nil
      end
    end,
  }
end
-- 功能：构建注册键 214308（首领 2143 × 难度 8）的机制解析器——按时长表换算机制，10 秒那条按出现次数交替，并靠「死亡咆哮」事件收尾。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾）。
-- 说明：10 秒按出现次数奇偶在 hunting_leap 与 deathly_roar 之间交替；阶段码为 1 时 30 秒算 gilded_destruction，死亡咆哮事件进入完成状态后阶段码升到 2，30 秒那条就不再上报（该机制一场只会放一次）。
local function createEncounter214308()
  local phaseCode, castCount, deathlyRoarEventIDs = 1, 1, {}
  return {
    Resolve = function(duration, eventID)
      local durationRounded = roundToDecimals(duration, 0)
      local mechanicKey
      if durationRounded == 8 or durationRounded == 10 and castCount % 2 == 1 or durationRounded == 28 then
        mechanicKey = "hunting_leap"
      elseif durationRounded == 14 or durationRounded == 10 and castCount % 2 == 0 or durationRounded == 27 then
        mechanicKey = "deathly_roar"
      elseif durationRounded == 15 then
        mechanicKey = "aerial_smash"
      elseif durationRounded == 23 or durationRounded == 38 then
        mechanicKey = "blade_combo"
      elseif phaseCode == 1 and durationRounded == 30 or durationRounded == 24 then
        mechanicKey = "gilded_destruction"
      elseif durationRounded == 9 then
        mechanicKey = "quaking_leap"
      elseif durationRounded == 36 then
        mechanicKey = "savage_maul"
      end
      if durationRounded == 10 then
        castCount = castCount + 1
      end
      if mechanicKey == "deathly_roar" then
        deathlyRoarEventIDs[eventID] = true
      end
      return mechanicKey, phaseCode
    end,
    OnEventClosed = function(eventID, state, reason)
      if deathlyRoarEventIDs[eventID] and (reason == "state_changed" and state == 3) then
        phaseCode = 2
      end
      if reason ~= "added" then
        deathlyRoarEventIDs[eventID] = nil
      end
    end,
  }
end
-- 功能：构建注册键 212408（首领 2124 × 难度 8）的机制解析器——四种机制各只报一次，且只在开场观测窗口内上报。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：第一次拿到数字观测时间时把窗口末尾记为「观测时间 + 1 秒」，此后观测时间超过窗口的时长一律返回 nil——这个首领的机制集中在开场一秒内，后面的时间轴事件是同批重复数据；seenMechanics 保证每个机制名只报一次。
local function createEncounter212408()
  local seenMechanics, burstWindowEnd = {}, nil
  return {
    Resolve = function(duration, eventID, observedAt)
      local durationRounded = roundToDecimals(duration, 3)
      if not burstWindowEnd and type(observedAt) == "number" then
        burstWindowEnd = observedAt + 1
      end
      if burstWindowEnd and (type(observedAt) == "number" and observedAt > burstWindowEnd) then
        return nil, 1
      end
      if durationRounded == 5 and not seenMechanics.gale_force then
        seenMechanics.gale_force = true
        return "gale_force", 1
      elseif durationRounded == 9 and not seenMechanics.thunder_and_lightning then
        seenMechanics.thunder_and_lightning = true
        return "thunder_and_lightning", 1
      elseif durationRounded == 29 and not seenMechanics.tempest_winds then
        seenMechanics.tempest_winds = true
        return "tempest_winds", 1
      elseif durationRounded == 39 and not seenMechanics.overload then
        seenMechanics.overload = true
        return "overload", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 212508（首领 2125 × 难度 8）的机制解析器——按时间轴时长直接查表。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：5 / 13 / 25 / 36 / 44 / 49 秒各自对应一个机制，认不出的时长返回 nil。
local function createEncounter212508()
  return {
    Resolve = function(duration)
      local durationRounded = roundToDecimals(duration, 0)
      if durationRounded == 5 then
        return "lightning_bite", 1
      elseif durationRounded == 13 then
        return "a_knot_of_snakes", 1
      elseif durationRounded == 25 then
        return "thunder_spit", 1
      elseif durationRounded == 36 then
        return "serpentstorm", 1
      elseif durationRounded == 44 then
        return "hatch", 1
      elseif durationRounded == 49 then
        return "burrow", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 212608（首领 2126 × 难度 8）的机制解析器——22 秒那条按出现次数交替两种机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：5 秒固定是 lightning_spire；22 秒按出现次数奇偶在 lightning_spire 与 induction 之间交替，其余时长返回 nil。
local function createEncounter212608()
  local castCount = 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToDecimals(duration, 0)
      local mechanicKey
      if durationRounded == 5 or durationRounded == 22 and castCount % 2 == 1 then
        mechanicKey = "lightning_spire"
      elseif durationRounded == 20 or durationRounded == 22 and castCount % 2 == 0 then
        mechanicKey = "induction"
      end
      if durationRounded == 22 then
        castCount = castCount + 1
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 212708（首领 2127 × 难度 8）的机制解析器——按 0.1 秒精度的时长表换算机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：15 秒是 defiling_taint、32.5 秒是 stage_one（转阶段标记），其余时长返回 nil。
local function createEncounter212708()
  return {
    Resolve = function(duration)
      local durationTenths = roundToDecimals(duration, 1)
      if durationTenths == 15 then
        return "defiling_taint", 1
      end
      if durationTenths == 32.5 then
        return "stage_one", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 260908（首领 2609 × 难度 8）的机制解析器——按时长表换算机制，24 秒那条按出现次数交替。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：24 秒按出现次数奇偶在 hailburst 与 chillstorm 之间交替；5 / 15 秒是 hailburst，12 秒是 frost_overload。
local function createEncounter260908()
  local castCount = 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToDecimals(duration, 0)
      local mechanicKey
      if durationRounded == 5 or durationRounded == 24 and castCount % 2 == 1 then
        mechanicKey = "hailburst"
      elseif durationRounded == 15 or durationRounded == 24 and castCount % 2 == 0 then
        mechanicKey = "chillstorm"
      elseif durationRounded == 12 then
        mechanicKey = "frost_overload"
      end
      if durationRounded == 24 then
        castCount = castCount + 1
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 260608（首领 2606 × 难度 8）的机制解析器——按时长表换算机制，40 秒那条按出现次数交替。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：40 秒按出现次数奇偶在 ritual_of_blazebinding 与 searing_blows 之间交替；8 秒固定 ritual_of_blazebinding，19 / 20 秒是 molten_boulder。
local function createEncounter260608()
  local castCount = 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToDecimals(duration, 0)
      local mechanicKey
      if durationRounded == 8 or durationRounded == 40 and castCount % 2 == 1 then
        mechanicKey = "ritual_of_blazebinding"
      elseif durationRounded == 19 or durationRounded == 20 then
        mechanicKey = "molten_boulder"
      elseif durationRounded == 28 or durationRounded == 40 and castCount % 2 == 0 then
        mechanicKey = "searing_blows"
      end
      if durationRounded == 40 then
        castCount = castCount + 1
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 262308（首领 2623 × 难度 8）的机制解析器——按 0.1 秒精度的时长表换算机制，三条计时各按自己的出现次数分流。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：state 为 1（进行中）的事件直接返回 nil，只认刚落地的。5 秒第一次是 stormslam、之后都算 roaring_firebreath（stormslamCount 记录）；20 秒按 cloudburstCount 奇偶在 roaring_firebreath 与 inferno_spit 之间分；16 秒按 infernoCount 奇偶同理。
local function createEncounter262308()
  local stormslamCount, cloudburstCount, infernoCount = 1, 1, 1
  return {
    Resolve = function(duration, eventID, observedAt, state)
      if state == 1 then
        return nil, 1
      end
      local durationTenths = roundToDecimals(duration, 1)
      local mechanicKey
      if durationTenths == 1 or stormslamCount > 1 and durationTenths == 5 or durationTenths == 20 and cloudburstCount % 2 == 1 or durationTenths == 16 and infernoCount % 2 == 1 then
        mechanicKey = "roaring_firebreath"
      elseif stormslamCount == 1 and durationTenths == 5 or durationTenths == 22.5 then
        mechanicKey = "stormslam"
        stormslamCount = stormslamCount + 1
      elseif durationTenths == 10 or durationTenths == 21.5 then
        mechanicKey = "winds_of_change"
      elseif durationTenths == 12 or durationTenths == 20 and cloudburstCount % 2 == 0 or durationTenths == 13 or durationTenths == 16 and infernoCount % 2 == 0 then
        mechanicKey = "inferno_spit"
      elseif durationTenths == 21 or durationTenths == 25 then
        mechanicKey = "interrupting_cloudburst"
      end
      if durationTenths == 20 then
        cloudburstCount = cloudburstCount + 1
      end
      if durationTenths == 16 then
        infernoCount = infernoCount + 1
      end
      return mechanicKey, 1
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[213908] = {
  Create = createEncounter213908,
  countIdentifiableAdds = true,
  mechanicCodes = { spit_gold = 1, tail_thrash = 2, serpentine_gust = 3, lucres_call = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[214208] = {
  Create = createEncounter214208,
  countIdentifiableAdds = true,
  mechanicCodes = { drain_fluids = 1, burn_corruption = 2, awakening_slam = 3, entomb = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[214008] = {
  Create = createEncounter214008,
  countIdentifiableAdds = true,
  mechanicCodes = {
    whirling_axes = 1,
    severing_axe = 2,
    barrel_through = 3,
    debilitating_backhand = 4,
    arc_lightning = 5,
    poison_nova = 6,
    call_of_the_elements = 7,
  },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[214308] = {
  Create = createEncounter214308,
  countIdentifiableAdds = true,
  mechanicCodes = {
    hunting_leap = 1,
    deathly_roar = 2,
    aerial_smash = 3,
    blade_combo = 4,
    gilded_destruction = 5,
    quaking_leap = 6,
    savage_maul = 7,
  },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[212408] = {
  Create = createEncounter212408,
  countIdentifiableAdds = true,
  mechanicCodes = { gale_force = 1, thunder_and_lightning = 2, tempest_winds = 3, overload = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[212508] = {
  Create = createEncounter212508,
  countIdentifiableAdds = true,
  mechanicCodes = { lightning_bite = 1, a_knot_of_snakes = 2, thunder_spit = 3, hatch = 4, serpentstorm = 5, burrow = 6 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[212608] = {
  Create = createEncounter212608,
  countIdentifiableAdds = true,
  mechanicCodes = { lightning_spire = 1, induction = 2 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[212708] = {
  Create = createEncounter212708,
  countIdentifiableAdds = true,
  mechanicCodes = { defiling_taint = 1, stage_one = 2 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[260908] = {
  Create = createEncounter260908,
  countIdentifiableAdds = true,
  mechanicCodes = { hailburst = 1, chillstorm = 2, frost_overload = 3 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[260608] = {
  Create = createEncounter260608,
  countIdentifiableAdds = true,
  mechanicCodes = { ritual_of_blazebinding = 1, molten_boulder = 2, searing_blows = 3 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[262308] = {
  Create = createEncounter262308,
  countIdentifiableAdds = true,
  mechanicCodes = {
    roaring_firebreath = 1,
    stormslam = 2,
    winds_of_change = 3,
    inferno_spit = 4,
    interrupting_cloudburst = 5,
  },
  unitEvents = {},
}
