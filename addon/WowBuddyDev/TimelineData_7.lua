-- ==========================================================================
-- 文件：f0d58a.lua
-- 来源：P07483180.rar → P07483180/f0d58a.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：f0d58a.lua → TimelineData_7.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
WowBuddyDev.TimelinePlannerEncounters = WowBuddyDev.TimelinePlannerEncounters or {}
-- 功能：把浮点秒数四舍五入成整数秒。
-- 入参：value 待取整的秒数。
-- 出参：整数秒。
-- 说明：本文件大部分机制表按整数秒写，判定前统一走这里，免得各函数各写一套取整规则。
local function roundToInt(value)
  return math.floor(value + .5)
end
-- 功能：把浮点秒数四舍五入到 0.1 秒。
-- 入参：value 待取整的秒数。
-- 出参：0.1 秒精度的时间轴时长。
-- 说明：有个别机制表是按 0.1 秒写的（8 和 27.5 这种），那些工厂要用这个口径，不能套整数取整。
local function roundToTenths(value)
  return math.floor(value * 10 + .5) / 10
end
-- 功能：记下某个机制最近一次出现的事件 ID 与观测时间，并把上一次的事件 ID 交回去。
-- 入参：registry 按机制键记最近一次的登记表；mechanicKey 机制键；eventID 本次事件 ID；observedAt 本次观测时间；maxGap 允许当成「同一次机制」的最大间隔（秒）。
-- 出参：上一次的事件 ID；没有上一条、或两次间隔不小于 maxGap 时返回 nil。
-- 说明：间隔要两次观测时间都有值且差值落在 [0, maxGap) 内才算同一次；登记表无论结果如何都覆盖成本次的值，上一轮信息不会留在里面——规划器拿到旧事件 ID 才能退掉被顶替的那条预警。
local function rememberOccurrence(registry, mechanicKey, eventID, observedAt, maxGap)
  local previous = registry[mechanicKey]
  local previousEventID
  if previous and (previous.observedAt and observedAt) then
    local elapsed = observedAt - previous.observedAt
    if elapsed >= 0 and elapsed < maxGap then
      previousEventID = previous.eventID
    end
  end
  registry[mechanicKey] = { eventID = eventID, observedAt = observedAt }
  return previousEventID
end
-- 功能：按事件 ID 把登记表里对应的记录删掉。
-- 入参：registry 登记表；eventID 要删的事件 ID。
-- 出参：无。
-- 说明：事件结束（OnEventClosed）时调用；不删的话这个事件 ID 会一直挂在登记表里，后面同名机制会被误判成「上一次出现过」。
local function forgetOccurrence(registry, eventID)
  for key, entry in pairs(registry) do
    if entry.eventID == eventID then
      registry[key] = nil
    end
  end
end
-- 功能：构建注册键 310108（首领 3101 × 难度 8）的机制解析器——按 0.1 秒精度的时长表换算机制，同一次机制重复计时时把上一次的事件 ID 交回给规划器。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾）。
-- 说明：时间轴会为同一次机制下发多条事件，3 秒内的重复计时按同上一次处理；机制事件收尾时按事件 ID 清掉登记，免得多轮之后误判。
local function createEncounter310108()
  local lastByMechanic = {}
  return {
    Resolve = function(duration, eventID, observedAt)
      local durationTenths, mechanicKey = roundToTenths(duration), nil
      if durationTenths == 8 or durationTenths == 27.5 then
        mechanicKey = "fel_spray"
      elseif durationTenths == 15 or durationTenths == 30 then
        mechanicKey = "mirror_images"
      elseif durationTenths == 12 or durationTenths == 25 then
        mechanicKey = "fel_nova"
      end
      if not mechanicKey then
        return nil, 1
      end
      return mechanicKey, 1, rememberOccurrence(lastByMechanic, mechanicKey, eventID, observedAt, 3)
    end,
    OnEventClosed = function(eventID)
      forgetOccurrence(lastByMechanic, eventID)
    end,
  }
end
-- 功能：构建注册键 310208（首领 3102 × 难度 8）的机制解析器——按时间轴时长直接查表报机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：8 秒是 killing_spree，12 / 16 秒是 same_day_delivery，18 秒是 fire_bomb，26 秒是 envenom，36 秒是 murder_in_a_row；其余时长返回 nil。
local function createEncounter310208()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded == 8 then
        return "killing_spree", 1
      end
      if durationRounded == 12 or durationRounded == 16 then
        return "same_day_delivery", 1
      end
      if durationRounded == 18 then
        return "fire_bomb", 1
      end
      if durationRounded == 26 then
        return "envenom", 1
      end
      if durationRounded == 36 then
        return "murder_in_a_row", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 310308（首领 3103 × 难度 8）的机制解析器——27 秒那条按出现次数交替报与不报。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：27 秒按出现次数奇偶在 legion_strike 与「不报」之间交替（同一个机制被时间轴拆成了两条计时，只有一条是真的）；时长不在 1~100 秒之间的一律不上报。
local function createEncounter310308()
  local castCount = 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded < 1 or durationRounded > 100 then
        return nil, 1
      end
      if durationRounded == 6 then
        return "legion_strike", 1
      end
      if durationRounded == 27 then
        local mechanicKey = castCount % 2 == 1 and "legion_strike" or nil
        castCount = castCount + 1
        return mechanicKey, 1
      end
      if durationRounded == 15 then
        return "axe_toss", 1
      end
      if durationRounded == 30 then
        return "infernal_crush", 1
      end
      if durationRounded == 35 then
        return "demonic_rage", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 310508（首领 3105 × 难度 8）的机制解析器——按时间轴时长直接查表报机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：10 / 57 秒是 summon_vilefiend，15 / 55 秒是 fingers_of_guldan，24 / 59 秒是 malefic_wave；其余时长返回 nil。
local function createEncounter310508()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded == 10 or durationRounded == 57 then
        return "summon_vilefiend", 1
      end
      if durationRounded == 15 or durationRounded == 55 then
        return "fingers_of_guldan", 1
      end
      if durationRounded == 24 or durationRounded == 59 then
        return "malefic_wave", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 320708（首领 3207 × 难度 8）的机制解析器——按时间轴时长直接查表报机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：6 秒是 ravenous_bellow，16 秒是 earthshatter_slam，30 秒是 spoiled_supplies；其余时长返回 nil。
local function createEncounter320708()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded == 6 then
        return "ravenous_bellow", 1
      end
      if durationRounded == 16 then
        return "earthshatter_slam", 1
      end
      if durationRounded == 30 then
        return "spoiled_supplies", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 320808（首领 3208 × 难度 8）的机制解析器——超过 59 秒的时长不算本场机制，同一次机制重复计时时交回上一次的事件 ID。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制、OnEventClosed 观测事件收尾）。
-- 说明：7 / 13 / 25 / 50 秒各自对应一个机制；2 秒内（maxGap 传 2）重复出现的同名机制按同上一次处理。
local function createEncounter320808()
  local lastByMechanic = {}
  return {
    Resolve = function(duration, eventID, observedAt)
      local durationRounded, mechanicKey = roundToInt(duration), nil
      if durationRounded > 59 then
        return nil, 1
      end
      if durationRounded == 7 then
        mechanicKey = "glacial_torment"
      elseif durationRounded == 13 then
        mechanicKey = "raging_squall"
      elseif durationRounded == 25 then
        mechanicKey = "shattering_frostspike"
      elseif durationRounded == 50 then
        mechanicKey = "frozen_tempest"
      end
      if not mechanicKey then
        return nil, 1
      end
      return mechanicKey, 1, rememberOccurrence(lastByMechanic, mechanicKey, eventID, observedAt, 2)
    end,
    OnEventClosed = function(eventID)
      forgetOccurrence(lastByMechanic, eventID)
    end,
  }
end
-- 功能：构建注册键 320908（首领 3209 × 难度 8）的机制解析器——25 秒那条按出现次数交替两种机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：25 秒按出现次数奇偶在 echoing_maul 与 overwhelming_onslaught 之间交替；5 / 13 / 54 秒各自对应一个固定机制。
local function createEncounter320908()
  local castCount = 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded == 5 then
        return "echoing_maul", 1
      end
      if durationRounded == 13 then
        return "overwhelming_onslaught", 1
      end
      if durationRounded == 54 then
        return "fury_of_the_war_god", 1
      end
      if durationRounded == 25 then
        local mechanicKey = castCount % 2 == 1 and "echoing_maul" or "overwhelming_onslaught"
        castCount = castCount + 1
        return mechanicKey, 1
      end
      return nil, 1
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[310108] = {
  Create = createEncounter310108,
  countIdentifiableAdds = true,
  mechanicCodes = { fel_spray = 1, mirror_images = 2, fel_nova = 3 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[310208] = {
  Create = createEncounter310208,
  countIdentifiableAdds = true,
  mechanicCodes = { killing_spree = 1, same_day_delivery = 2, fire_bomb = 3, envenom = 4, murder_in_a_row = 5 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[310308] = {
  Create = createEncounter310308,
  countIdentifiableAdds = true,
  mechanicCodes = { legion_strike = 1, axe_toss = 2, infernal_crush = 3, demonic_rage = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[310508] = {
  Create = createEncounter310508,
  countIdentifiableAdds = true,
  mechanicCodes = { summon_vilefiend = 1, fingers_of_guldan = 2, malefic_wave = 3 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[320708] = {
  Create = createEncounter320708,
  countIdentifiableAdds = true,
  mechanicCodes = { ravenous_bellow = 1, earthshatter_slam = 2, spoiled_supplies = 3 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[320808] = {
  Create = createEncounter320808,
  countIdentifiableAdds = true,
  mechanicCodes = { glacial_torment = 1, raging_squall = 2, shattering_frostspike = 3, frozen_tempest = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[320908] = {
  Create = createEncounter320908,
  countIdentifiableAdds = true,
  mechanicCodes = { echoing_maul = 1, overwhelming_onslaught = 2, fury_of_the_war_god = 3 },
  unitEvents = {},
}
