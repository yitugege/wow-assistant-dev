-- ==========================================================================
-- 文件：cc819c.lua
-- 来源：P07483180.rar → P07483180/cc819c.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：cc819c.lua → TimelineData_3.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
-- 功能：把浮点秒数四舍五入成整数秒（本文件统一的取整口径）。
-- 入参：value 待取整的秒数。
-- 出参：整数秒。
-- 说明：时间轴时长是浮点，机制表按整数秒写死，所有判定都先过这里，免得各函数各写一套取整规则。
local function roundToInt(value)
  return math.floor(value + .5)
end
-- 功能：构建注册键 345515（首领 3455 × 难度 15）的机制解析器——按时间轴时长直接查表，13 秒那条头一次算另一种机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：13 秒第一次是 plague_froth、之后都是 dripping_fangs；标志位用完即置 false，所以整场战斗里只会报一次 plague_froth。
local function createEncounter345515()
  local isFirstPlagueFroth = true
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded == 13 then
        if isFirstPlagueFroth then
          isFirstPlagueFroth = false
          return "plague_froth", 1
        end
        return "dripping_fangs", 1
      elseif durationRounded == 20 or durationRounded == 80 then
        return "imbibe", 1
      elseif durationRounded == 30 or durationRounded == 33 then
        return "plague_froth", 1
      elseif durationRounded == 8 or durationRounded == 27 or durationRounded == 28 then
        return "dripping_fangs", 1
      elseif durationRounded == 18 or durationRounded == 52 then
        return "adaptive_infection", 1
      elseif durationRounded == 6 or durationRounded == 39 then
        return "malignant_catalyst", 1
      end
      return nil, 1
    end,
  }
end
-- 功能：构建注册键 342015（首领 3420 × 难度 15）的机制解析器——固定时长查表，47 / 52 / 59 秒这三条按出现次数轮转机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：47 / 52 / 59 秒其实是同一组轮转点，按「这条时长出现过几次 % 3」依次给 apex_predator / venomous_surge / raging_crosswinds——同一个时长反复出现时三种机制都能轮到，不会永远只报一个。
local function createEncounter342015()
  local durationCounts = {}
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      if durationRounded == 100 or durationRounded == 111 or durationRounded == 125 then
        return "howling_maelstrom", 1
      elseif durationRounded == 5 or durationRounded == 6 then
        return "apex_predator", 1
      elseif durationRounded == 29 or durationRounded == 32 or durationRounded == 36 then
        return "venomous_surge", 1
      elseif durationRounded == 39 or durationRounded == 43 or durationRounded == 49 then
        return "raging_crosswinds", 1
      elseif durationRounded == 47 or durationRounded == 52 or durationRounded == 59 then
        local occurrenceCount = (durationCounts[durationRounded] or 0) + 1
        durationCounts[durationRounded] = occurrenceCount
        local rotationIndex = occurrenceCount % 3
        if rotationIndex == 1 then
          return "apex_predator", 1
        end
        if rotationIndex == 2 then
          return "venomous_surge", 1
        end
        return "raging_crosswinds", 1
      end
      return nil, 1
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[345515] = {
  Create = createEncounter345515,
  countIdentifiableAdds = true,
  mechanicCodes = { imbibe = 1, malignant_catalyst = 2, plague_froth = 3, dripping_fangs = 4, adaptive_infection = 5 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[342015] = {
  Create = createEncounter342015,
  countIdentifiableAdds = true,
  mechanicCodes = { howling_maelstrom = 1, apex_predator = 2, venomous_surge = 3, raging_crosswinds = 4 },
  unitEvents = {},
}
