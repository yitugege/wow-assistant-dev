-- ==========================================================================
-- 文件：18ec96.lua
-- 来源：P07483180.rar → P07483180/18ec96.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：18ec96.lua → TimelineData_5.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
-- 功能：构建注册键 337915（首领 3379 × 难度 15）的机制解析器——固定时长查表，44 秒那条按轮转序号依次出三种机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：44 秒每出现一次就把轮转序号 +1（1→2→3 回绕），依次报 alluring_bubble_adds / chilling_frost / abyssal_rain；18 秒那条按原始秒数比较，不做取整。
local function createEncounter337915()
  local rotationIndex = 0
  return {
    Resolve = function(duration)
      local durationRounded = math.floor(duration + .5)
      if durationRounded == 44 then
        rotationIndex = rotationIndex % 3 + 1
        if rotationIndex == 1 then
          return "alluring_bubble_adds", 1
        end
        if rotationIndex == 2 then
          return "chilling_frost", 1
        end
        return "abyssal_rain", 1
      elseif duration == 18 then
        return "alluring_bubble", 1
      elseif durationRounded == 8 or durationRounded == 23 or durationRounded == 33 then
        return "abyssal_rain", 1
      elseif durationRounded == 22 or durationRounded == 27 or durationRounded == 9 then
        return "iceblade_flurry", 1
      elseif durationRounded == 25 or durationRounded == 7 then
        return "alluring_bubble_adds", 1
      elseif durationRounded == 107 or durationRounded == 89 then
        return "swirling_whirlpools", 1
      elseif durationRounded == 35 or durationRounded == 17 then
        return "chilling_frost", 1
      end
      return nil, 1
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[337915] = {
  Create = createEncounter337915,
  countIdentifiableAdds = true,
  mechanicCodes = {
    alluring_bubble_adds = 1,
    alluring_bubble = 2,
    swirling_whirlpools = 3,
    abyssal_rain = 4,
    iceblade_flurry = 5,
    chilling_frost = 6,
  },
  unitEvents = {},
}
