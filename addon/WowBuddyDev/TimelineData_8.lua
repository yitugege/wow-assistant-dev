-- ==========================================================================
-- 文件：0350c5.lua
-- 来源：P07483180.rar → P07483180/0350c5.lua（原插件 Permes 9.9.6 / Interface 120100）
-- 说明：由混淆源码自动还原：格式化缩进 + 作用域内局部变量重命名 + 字符串转义还原。
-- 注意：原始注释与原始变量名无法恢复；语句顺序、字符串、数字与原文件完全一致。
-- 重命名：0350c5.lua → TimelineData_8.lua（按功能重命名）
-- 作用：时间轴数据：首领机制计时
-- ==========================================================================
WowBuddyDev.TimelinePlannerEncounters = WowBuddyDev.TimelinePlannerEncounters or {}
-- 功能：把浮点秒数四舍五入成整数秒（本文件统一的取整口径）。
-- 入参：value 待取整的秒数。
-- 出参：整数秒。
-- 说明：机制表按整数秒写死，所有工厂判定前都先过这里，免得各函数各写一套取整规则。
local function roundToInt(value)
  return math.floor(value + .5)
end
-- 功能：构建注册键 328508（首领 3285 × 难度 8）的机制解析器——把整秒时长当键查一张常量映射表。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：6 / 16 / 25 / 31 秒对应四个机制；查不到就是 nil，规划器会把「认不出的时长」如实记进采集数据，方便事后补表。
local function createEncounter328508()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey = ({ [6] = "nether_dash", [16] = "umbral_rupture", [25] = "void_blast", [31] = "dark_bloom" })[durationRounded]
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 328608（首领 3286 × 难度 8）的机制解析器——按时长表换算机制，20 秒那条按出现次数交替。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：20 秒按出现次数奇偶在 poison_splash 与 hulking_claw 之间交替；15 / 30 秒是 noxious_breath，35 秒是 monstrous_roar。
local function createEncounter328608()
  local castCount = 0
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey
      if durationRounded == 5 or durationRounded == 20 and castCount % 2 == 1 then
        mechanicKey = "poison_splash"
      elseif durationRounded == 10 or durationRounded == 20 and castCount % 2 == 0 then
        mechanicKey = "hulking_claw"
      elseif durationRounded == 15 or durationRounded == 30 then
        mechanicKey = "noxious_breath"
      elseif durationRounded == 35 then
        mechanicKey = "monstrous_roar"
      end
      if durationRounded == 20 then
        castCount = castCount + 1
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 328708（首领 3287 × 难度 8）的机制解析器——把整秒时长当键查一张五条机制的常量映射表。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：5 / 17 / 28 / 34 / 43 秒对应五个机制，认不出的时长返回 nil。
local function createEncounter328708()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey = ({
        [5] = "unstable_singularity",
        [17] = "cosmic_crash",
        [28] = "gravitic_orbs",
        [34] = "dark_waves",
        [43] = "void_cascade",
      })[durationRounded]
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 345608（首领 3456 × 难度 8）的机制解析器——按时间轴时长直接查表报机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：8 / 24 秒是 triple_shot，25 / 45 秒是 ssscavenging，13 秒是 regurgitate，23 秒是 ravenous_stomp；其余时长返回 nil。
local function createEncounter345608()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey
      if durationRounded == 8 or durationRounded == 24 then
        mechanicKey = "triple_shot"
      elseif durationRounded == 25 or durationRounded == 45 then
        mechanicKey = "ssscavenging"
      elseif durationRounded == 13 then
        mechanicKey = "regurgitate"
      elseif durationRounded == 23 then
        mechanicKey = "ravenous_stomp"
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 345708（首领 3457 × 难度 8）的机制解析器——按时长表换算机制，10 秒那条按出现次数交替，阶段码由 assimilation 与 death_rattle 推动。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：10 秒按出现次数奇偶在 synchronized_venom 与 toxic_atrophy 之间交替；25 秒的 assimilation 把阶段码置 2，death_rattle 在阶段码已是 2 时把它复位成 1。阶段码随机制一起返回给规划器，用来说明机制处在首领的第几段。
local function createEncounter345708()
  local castCount, stageCode = 0, 1
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey
      if durationRounded == 1 or durationRounded == 10 and castCount % 2 == 0 then
        mechanicKey = "synchronized_venom"
      elseif durationRounded == 7 or durationRounded == 16 then
        mechanicKey = "tail_scythe"
      elseif durationRounded == 14 or durationRounded == 23 then
        mechanicKey = "preparing_toxin"
      elseif durationRounded == 30 or durationRounded == 39 then
        mechanicKey = "vindictive_onslaught"
      elseif durationRounded == 44 or durationRounded == 53 then
        mechanicKey = "death_rattle"
        if stageCode == 2 then
          stageCode = 1
        end
      elseif durationRounded == 10 and castCount % 2 == 1 then
        mechanicKey = "toxic_atrophy"
      elseif durationRounded == 25 then
        mechanicKey, stageCode = "assimilation", 2
      end
      if durationRounded == 10 then
        castCount = castCount + 1
      end
      return mechanicKey, stageCode
    end,
  }
end
-- 功能：构建注册键 345808（首领 3458 × 难度 8）的机制解析器——按时间轴时长直接查表报机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：3 / 65 秒是 ritual_of_the_fang，18 秒是 axegrinder，26 / 30 秒是 chop_down，36 / 16 秒是 boneslicer；其余时长返回 nil。
local function createEncounter345808()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey
      if durationRounded == 3 or durationRounded == 65 then
        mechanicKey = "ritual_of_the_fang"
      elseif durationRounded == 18 then
        mechanicKey = "axegrinder"
      elseif durationRounded == 26 or durationRounded == 30 then
        mechanicKey = "chop_down"
      elseif durationRounded == 36 or durationRounded == 16 then
        mechanicKey = "boneslicer"
      end
      return mechanicKey, 1
    end,
  }
end
-- 功能：构建注册键 320008（首领 3200 × 难度 8）的机制解析器——按时间轴时长直接查表报机制。
-- 入参：无（工厂函数，只建状态机）。
-- 出参：状态机表（Resolve 判定机制）。
-- 说明：6 / 29 秒是 verdant_stomp，22 秒是 thorncaller_roar，50 秒是 bloodthirsty_gaze；其余时长返回 nil。
local function createEncounter320008()
  return {
    Resolve = function(duration)
      local durationRounded = roundToInt(duration)
      local mechanicKey
      if durationRounded == 6 or durationRounded == 29 then
        mechanicKey = "verdant_stomp"
      elseif durationRounded == 22 then
        mechanicKey = "thorncaller_roar"
      elseif durationRounded == 50 then
        mechanicKey = "bloodthirsty_gaze"
      end
      return mechanicKey, 1
    end,
  }
end
WowBuddyDev.TimelinePlannerEncounters[328508] = {
  Create = createEncounter328508,
  countIdentifiableAdds = true,
  mechanicCodes = { nether_dash = 1, umbral_rupture = 2, void_blast = 3, dark_bloom = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[328608] = {
  Create = createEncounter328608,
  countIdentifiableAdds = true,
  mechanicCodes = { poison_splash = 1, hulking_claw = 2, noxious_breath = 3, monstrous_roar = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[328708] = {
  Create = createEncounter328708,
  countIdentifiableAdds = true,
  mechanicCodes = { unstable_singularity = 1, cosmic_crash = 2, gravitic_orbs = 3, dark_waves = 4, void_cascade = 5 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[345608] = {
  Create = createEncounter345608,
  countIdentifiableAdds = true,
  mechanicCodes = { triple_shot = 1, ssscavenging = 2, regurgitate = 3, ravenous_stomp = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[345708] = {
  Create = createEncounter345708,
  countIdentifiableAdds = true,
  mechanicCodes = {
    synchronized_venom = 1,
    tail_scythe = 2,
    preparing_toxin = 3,
    vindictive_onslaught = 4,
    death_rattle = 5,
    toxic_atrophy = 6,
    assimilation = 7,
  },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[345808] = {
  Create = createEncounter345808,
  countIdentifiableAdds = true,
  mechanicCodes = { ritual_of_the_fang = 1, axegrinder = 2, chop_down = 3, boneslicer = 4 },
  unitEvents = {},
}
WowBuddyDev.TimelinePlannerEncounters[320008] = {
  Create = createEncounter320008,
  countIdentifiableAdds = true,
  mechanicCodes = { verdant_stomp = 1, thorncaller_roar = 2, bloodthirsty_gaze = 3 },
  unitEvents = {},
}
