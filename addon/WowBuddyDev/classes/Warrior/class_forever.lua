-- 作用：无限战士 1491（练级输出，按已学技能和当前姿态启用）。
-- IDs: research/forever-warrior-20260919/warrior-spell-ids.json, build 1.60.1.69913.

WowBuddyDev.RegisterPixelStripV2(1491, {
  -- ==================== 横排 V2 数值格（OCR 读取通道）====================
  -- 只有四种 kind 会出现在横排面板上：
  --   cd_seconds   技能剩余冷却秒数（时长绑定；未学会显示 601）
  --   charge_lua   充能/层数（未学会显示 601）
  --   aura_seconds 光环剩余秒数（光环不在则隐藏）
  --   aura_stacks  光环层数（光环不在则隐藏）
  -- presence 类槽位走光环容器（竖排），不占横排格子。
  --
  -- ★ 顺序 = 面板上从左到右的格子顺序，改顺序会让读取端的格子编号跟着变。
  -- ★ PanelV2.lua:19 的 maxTextSlots = 16 是硬上限，超过则整块面板不渲染。
  { key = "v2_cd_100",      name = "冲锋",     kind = "cd_seconds", spellID = 100 },
  { key = "v2_cd_6552",     name = "拳击",     kind = "cd_seconds", spellID = 6552 },
  { key = "v2_cd_72",       name = "盾击",     kind = "cd_seconds", spellID = 72 },
  { key = "v2_cd_7384",     name = "压制",     kind = "cd_seconds", spellID = 7384 },
  { key = "v2_cd_6572",     name = "复仇",     kind = "cd_seconds", spellID = 6572 },
  { key = "v2_cd_2687",     name = "血性狂暴",  kind = "cd_seconds", spellID = 2687 },
  { key = "v2_cd_6343",     name = "雷霆一击",  kind = "cd_seconds", spellID = 6343 },
  { key = "v2_cd_1680",     name = "旋风斩",    kind = "cd_seconds", spellID = 1680 },
  { key = "v2_cd_12294",    name = "致死打击",  kind = "cd_seconds", spellID = 12294 },
  { key = "v2_cd_23881",    name = "嗜血",     kind = "cd_seconds", spellID = 23881 },
  { key = "v2_cd_23922",    name = "盾牌猛击",  kind = "cd_seconds", spellID = 23922 },
  { key = "v2_cd_12292",    name = "横扫攻击",  kind = "cd_seconds", spellID = 12292 },

  -- ==================== 光环存在性（竖排光环容器）====================
  { key = "battle_shout", name = "战斗怒吼", kind = "presence", unit = "player", spellIDs = { 6673, 5242, 6192, 11549, 11550, 11551, 25289 } },
  { key = "rend", name = "撕裂", kind = "presence", unit = "target", filter = "HARMFUL", spellIDs = { 772, 6546, 6547, 6548, 11572, 11573, 11574 } },
  { key = "sweeping_strikes", name = "横扫攻击", kind = "presence", unit = "player", spellID = 12292 },
  { key = "death_wish", name = "死亡之愿", kind = "presence", unit = "player", spellID = 12328 },

  -- BEGIN GENERATED FOREVER
  { key = "shield_block", name = "盾牌格挡", kind = "presence", unit = "player", filter = "HELPFUL", spellIDs = { 2565 } },
  { key = "sunder_armor", name = "破甲攻击", kind = "presence", unit = "target", filter = "HARMFUL", spellIDs = { 7386, 7405, 8380, 11596, 11597 } },
  { key = "demoralizing_shout", name = "挫志怒吼", kind = "presence", unit = "target", filter = "HARMFUL", spellIDs = { 1160, 6190, 11554, 11555, 11556 } },
  -- END GENERATED FOREVER
})

local function knownRanks(spellID)
  local result = {}
  local aliases = WowBuddyDev.classes[1491].spellReadyAliases
  for _, id in ipairs(aliases[spellID] or { spellID }) do
    local ok, known = pcall(WowBuddyDev.IsSpellKnown, id)
    if ok and known == true then result[#result + 1] = id end
  end
  return result
end

-- 功能：这一组技能 ID 里有没有任何一个正处于「当前技能」状态（如英勇打击已排队）。
-- 入参：ids 技能 ID 列表（含各等级别名）。
-- 出参：true / false —— ★ 必须是明确的 boolean，绝不返回 nil。
-- 说明：口径对齐上游 Core.lua:1594/1735 的 `C_Spell.IsCurrentSpell(spellID) == true`，
--   即「非 true 一律算不是当前技能」，不再区分「读不到」与「确认没有」。
--   原来这里在 unknown 分支走到函数末尾隐式返回 nil，而 strike_queued /
--   auto_attack_active 是 flag 字段，读取端与引擎都按【三态】处理：
--     Python action_dispatcher.py:_compile_cond  -> s.flag(field) is bool(want)
--     C++    engine.cpp:688  Engine::evalCond    -> got == (want ? 1 : 0)，读不到是 -1
--   nil/-1 永不等于 False ⇒ FLAG("strike_queued", False) 恒假 ⇒
--   英勇打击(78) 与顺劈斩(845) 两条规则永远不命中（2026-10-03 修复）。
local function currentSpell(ids)
  if not C_Spell or type(C_Spell.IsCurrentSpell) ~= "function" then return false end
  for _, id in ipairs(ids) do
    local ok, active = pcall(C_Spell.IsCurrentSpell, id)
    if ok and active == true then return true end
  end
  return false
end

-- Keep the original warrior color-curve path for protected power values.
local rageCurve
local function rageValue()
  local ok, color = pcall(function()
    if not (C_CurveUtil and C_CurveUtil.CreateColorCurve and UnitPowerPercent and Enum.LuaCurveType) then return nil end
    if not rageCurve then
      local curve = C_CurveUtil.CreateColorCurve()
      curve:SetType(Enum.LuaCurveType.Step)
      for i = 0, 100 do curve:AddPoint(i / 100, CreateColor(0, 0, i / 255, 1)) end
      rageCurve = curve
    end
    return UnitPowerPercent("player", Enum.PowerType.Rage, false, rageCurve)
  end)
  if ok and type(color) == "table" and color.GetRGB then return color end
  local numberOK, power = pcall(function()
    local value = UnitPower("player", Enum.PowerType.Rage)
    if type(value) == "number" and value >= 0 and value <= 100 then return value end
  end)
  return numberOK and power or 16777215
end

-- Immunity is feedback about one target, not a spell cooldown or a missing aura.
local rendImmuneUntil = {}
local rendAttempt, rendImmuneError
local REND_IMMUNITY_RETRY_SEC = 30
local REND_FEEDBACK_WINDOW_SEC = .6
local rendFeedback = { version = 1 }
WowBuddyDev.rendFeedback = rendFeedback

local function isRendSpell(spellID)
  -- All ranks of Rend
  return spellID == 772 or spellID == 6546 or spellID == 6547 or spellID == 6548
    or spellID == 11572 or spellID == 11573 or spellID == 11574
end

local function readableGUID(unit)
  local ok, guid = pcall(function()
    local value = UnitGUID(unit)
    if issecretvalue and issecretvalue(value) then return nil end
    if type(value) == "string" and value ~= "" then return value end
  end)
  if ok then return guid end
end

local function rememberRendImmunity(guid, source)
  if type(guid) ~= "string" or guid == "" then return end
  local now = GetTime()
  -- Drop expired entries; targets are keyed by GUID, never by creature name/type.
  for targetGUID, expires in pairs(rendImmuneUntil) do
    if expires <= now then rendImmuneUntil[targetGUID] = nil end
  end
  rendImmuneUntil[guid] = now + REND_IMMUNITY_RETRY_SEC
  rendFeedback.last = { targetGUID = guid, source = source, at = now,
    retryAt = rendImmuneUntil[guid] }
  if WowBuddyDev.DB then WowBuddyDev.DB.rendImmuneLast = rendFeedback.last end
end

local function pairRendImmunity()
  if not rendAttempt or not rendAttempt.outcomeAt or not rendImmuneError then return end
  if math.abs(rendAttempt.outcomeAt - rendImmuneError) > REND_FEEDBACK_WINDOW_SEC then return end
  if rendImmuneError < rendAttempt.sentAt or GetTime() - rendAttempt.sentAt > 2 then return end
  -- UI errors contain no target ID, so discard ambiguous feedback after switching.
  if readableGUID("target") ~= rendAttempt.targetGUID then return end
  rememberRendImmunity(rendAttempt.targetGUID, "spellcast+UI_ERROR_MESSAGE")
  rendAttempt, rendImmuneError = nil, nil
end

local function recordRendOutcome(spellID)
  pcall(function()
    if not isRendSpell(spellID) then
      rendAttempt, rendImmuneError = nil, nil
    elseif rendAttempt and rendAttempt.spellID == spellID and GetTime() - rendAttempt.sentAt <= 2 then
      rendAttempt.outcomeAt = GetTime()
      pairRendImmunity()
    end
  end)
end

local rendEvents = CreateFrame("Frame")
rendEvents:RegisterUnitEvent("UNIT_SPELLCAST_SENT", "player")
rendEvents:RegisterEvent("PLAYER_TARGET_CHANGED")
rendEvents:RegisterEvent("PLAYER_REGEN_ENABLED")
rendEvents:RegisterEvent("PLAYER_ENTERING_WORLD")
rendEvents:RegisterEvent("UI_ERROR_MESSAGE")
-- Some clients do not expose combat-log events; retain the existing cast/error path.
if type(CombatLogGetCurrentEventInfo) == "function" then
  local ok, registered = pcall(function()
    if C_EventUtils and C_EventUtils.IsEventValid and not C_EventUtils.IsEventValid("COMBAT_LOG_EVENT_UNFILTERED") then
      return false
    end
    rendEvents:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
    return true
  end)
  rendFeedback.combatLogAvailable = ok and registered == true
end
rendEvents:SetScript("OnEvent", function(_, event, ...)
  local args = {...}
  local ok = pcall(function()
    if event == "PLAYER_REGEN_ENABLED" or event == "PLAYER_ENTERING_WORLD" then
      wipe(rendImmuneUntil)
      rendAttempt, rendImmuneError = nil, nil
      return
    end
    if WowBuddyDev.classData ~= WowBuddyDev.classes[1491] then return end
    if event == "PLAYER_TARGET_CHANGED" then
      rendAttempt, rendImmuneError = nil, nil
    elseif event == "UNIT_SPELLCAST_SENT" then
      rendAttempt, rendImmuneError = nil, nil
      local unit, targetName, _, spellID = unpack(args)
      if unit ~= "player" or not isRendSpell(spellID) then return end
      local guid = readableGUID("target")
      local name = UnitName("target")
      if guid and name and targetName == name then
        rendAttempt = { targetGUID = guid, spellID = spellID, sentAt = GetTime() }
      end
    elseif event == "UI_ERROR_MESSAGE" then
      local message = args[2]
      if message and ((SPELL_FAILED_IMMUNE and message == SPELL_FAILED_IMMUNE)
        or (SPELL_FAILED_DAMAGE_IMMUNE and message == SPELL_FAILED_DAMAGE_IMMUNE)) then
        rendImmuneError = GetTime()
        pairRendImmunity()
      else
        rendImmuneError = nil
      end
    elseif event == "COMBAT_LOG_EVENT_UNFILTERED" then
      local _, kind, _, sourceGUID, _, _, _, targetGUID, _, _, _, spellID, _, _, missType = CombatLogGetCurrentEventInfo()
      if issecretvalue and (issecretvalue(targetGUID) or issecretvalue(sourceGUID) or issecretvalue(spellID)) then return end
      if kind == "UNIT_DIED" then
        if targetGUID then rendImmuneUntil[targetGUID] = nil end
        return
      end
      local playerGUID = readableGUID("player")
      if not playerGUID or sourceGUID ~= playerGUID or not isRendSpell(spellID) then return end
      if kind == "SPELL_MISSED" and missType == "IMMUNE" then
        rememberRendImmunity(targetGUID, "SPELL_MISSED:IMMUNE")
      elseif kind == "SPELL_AURA_APPLIED" or kind == "SPELL_AURA_REFRESH" or kind == "SPELL_PERIODIC_DAMAGE" then
        if targetGUID then rendImmuneUntil[targetGUID] = nil end
      end
    end
  end)
  if not ok then rendFeedback.lastUnreadableEvent = event end
end)

WowBuddyDev.RegisterClass(1491, {
  OnSpellCast = recordRendOutcome,
  OnSpellCastFailed = recordRendOutcome,
  OverrideIsSpellReady = function(spellID)
    if not isRendSpell(spellID) then return nil end
    local guid = readableGUID("target")
    local expires = guid and rendImmuneUntil[guid]
    if expires and GetTime() < expires then return false end
    if expires then rendImmuneUntil[guid] = nil end
    return nil
  end,
  -- ★ 2026-10-03：宏里一律不再写 [stance:N]。
  --   理由（对齐同客户端的上游 Permes 9.9.6 / Interface 120100，其 56 条战士宏
  --   里 stance 条件出现 0 次）：
  --     1) 姿态可用性已经由 avail 门覆盖 —— avail 取 P07483180.IsSpellReady →
  --        IsSpellReadyRaw → P07483180.IsSpellUsable = C_Spell.IsSpellUsable
  --        （Core.lua:437），客户端这个接口本身就含「姿态 / 武器 / 资源」语义。
  --     2) [stance:N] 是宏级静默失败：规则命中 → 键照发 → 游戏因姿态编号不符
  --        直接什么都不做，日志里只会看到「结果=成功 后台按键已发送」，
  --        表现为「有些技能就是不释放」且无任何报错，极难排查。
  --     3) stance 编号随客户端改版漂移（0 = 没点姿态天赋，此时任何 [stance:N]
  --        恒假）。切成防御姿态后放不出技能正是这一条。
  --   保留 /startattack、harm、nodead、nochanneling、nocombat/combat —— 这些与
  --   姿态无关，且上游同样在用。
  DEFAULT_MACROS = {
    start_attack = "/startattack [harm,nodead]",
    spell_100 = "/cast [nocombat,harm,nodead,nochanneling]冲锋",
    spell_6673 = "/cast [nochanneling]战斗怒吼",
    spell_2687 = "/cast [combat,nochanneling]血性狂暴",
    spell_6552 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]拳击",
    spell_72 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]盾击",
    spell_5308 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]斩杀",
    spell_7384 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]压制",
    spell_6572 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]复仇",
    spell_402927 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]乘胜追击",
    spell_12294 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]致死打击",
    spell_23881 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]嗜血",
    spell_23922 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]盾牌猛击",
    spell_1310222 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]穿刺打击",
    spell_12292 = "/cast [nochanneling]横扫攻击",
    spell_12328 = "/cast [nochanneling]死亡之愿",
    spell_772 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]撕裂",
    spell_1680 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]旋风斩",
    spell_6343 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]雷霆一击",
    spell_1240193 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]猛击",
    spell_845 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]!顺劈斩",
    spell_78 = "/startattack [harm,nodead]\\n/cast [harm,nodead,nochanneling]!英勇打击",
    spell_871 = "/cast [@player,nochanneling] 盾墙",
    spell_12975 = "/cast [@player,nochanneling] 破釜沉舟",
    spell_2565 = "/cast [@player,nochanneling] 盾牌格挡",
    spell_7386 = "/cast [harm,nodead,nochanneling] 破甲攻击",
    spell_1160 = "/cast [@player,nochanneling] 挫志怒吼",
    spell_355 = "/cast [harm,nodead,nochanneling] 嘲讽",
    spell_1464 = "/cast 猛击",
    spell_1719 = "/cast 鲁莽",
    spell_18499 = "/cast 狂暴之怒",
    spell_402913 = "/cast 狂怒回复",
    spell_402911 = "/cast 怒击",
    spell_2457 = "/cast 战斗姿态",
    spell_71 = "/cast 防御姿态",
    spell_2458 = "/cast 狂暴姿态",
    spell_412513 = "/cast 角斗姿态",
    spell_1715 = "/cast 断筋",
    spell_429765 = "/cast 迅捷打击",
    spell_20252 = "/cast 拦截",
    spell_676 = "/cast 缴械",
    spell_694 = "/cast 惩戒痛击",
    spell_1161 = "/cast 挑战怒吼",
    spell_5246 = "/cast 破胆怒吼",
    spell_403228 = "/cast 肉钩",
    spell_440488 = "/cast 震荡波",
    spell_20230 = "/cast 反击风暴",
    spell_403215 = "/cast 命令怒吼",
    spell_426490 = "/cast 集结呐喊",
    spell_426972 = "/cast 警戒",
    spell_461475 = "/cast 艾泽拉斯之勇",
    spell_2480 = "/cast 弓射击\\n/cast 枪械射击\\n/cast 弩射击\\n/cast 投掷",
    spell_12809 = "/cast 震荡猛击",
    spell_12323 = "/cast 刺耳怒吼",
    spell_6552_focus = "/cast [@focus,harm,nodead] 拳击",
    spell_6552_mouseover = "/cast [@mouseover,harm,nodead] 拳击",
    spell_72_focus = "/cast [@focus,harm,nodead] 盾击",
    spell_72_mouseover = "/cast [@mouseover,harm,nodead] 盾击",
  },
  -- ★ 2026-10-03 按同客户端上游 Permes 9.9.6（Interface 120100，
  --   C:\Users\Administrator\Desktop\无限服\P07483180）+ forever_spell_map.json 补齐别名。
  --   机制：IsSpellReady 先问本 ID，再逐个问别名，**任一可用即 true**（PixelBar.lua:807-826）。
  --   所以这里【只增不减】——保留经典旧世等级 ID（16001 客户端要用），
  --   再叠上 120100 客户端的真实 ID，两套客户端都能过 avail 门。
  --
  --   补齐前这 4 个动作的 avail 在 120100 上恒假 ⇒ 规则永不命中 ⇒ 技能永不释放：
  --     英勇打击 78      → 上游 1269383（class_arms.lua:88 heroicStrikeSpellID）
  --     斩杀    5308     → 上游三系统一 163201
  --     旋风斩  1680     → 上游 fury 190411（原来连别名条目都没有）
  --     横扫攻击 12292   → 上游 arms 260708（原来连别名条目都没有）
  --   复仇 6572 另补上游的 1215174 / 1264147。
  spellReadyAliases = {
    [78] = { 78, 284, 285, 1608, 11564, 11565, 11566, 11567, 25286, 1269383 },
    [100] = { 100, 6178, 11578 },
    [6673] = { 6673, 5242, 6192, 11549, 11550, 11551, 25289 },
    [772] = { 772, 6546, 6547, 6548, 11572, 11573, 11574 },
    [6343] = { 6343, 8198, 8204, 8205, 11580, 11581 },
    [7384] = { 7384, 7887, 11584, 11585 },
    [72] = { 72, 1671, 1672 },
    [6572] = { 6572, 6574, 7379, 11600, 11601, 25288, 1215174, 1264147 },
    [845] = { 845, 7369, 11608, 11609, 20569 },
    [1240193] = { 1240193, 1464, 8820, 11604, 11605 },
    [5308] = { 5308, 20658, 20660, 20661, 20662, 163201 },
    [6552] = { 6552, 6554 },
    [12294] = { 12294, 21551, 21552, 21553 },
    [23881] = { 23881, 23892, 23893, 23894 },
    [23922] = { 23922, 23923, 23924, 23925 },
    [1680] = { 1680, 190411 },
    [12292] = { 12292, 260708 },
  -- BEGIN GENERATED FOREVER
    [871] = { 871 },
    [12975] = { 12975, 12976 },
    [2565] = { 2565 },
    [7386] = { 7386, 7405, 8380, 11596, 11597 },
    [1160] = { 1160, 6190, 11554, 11555, 11556 },
    [355] = { 355 },
  -- END GENERATED FOREVER
  },
  -- 声明本职业支持「自动 / 单体 / 群体」模式切换 —— dock 按钮条上那个按钮的显隐开关。
  -- 原版 Permes 的 80 个职业文件全部有这一行；无限版重写时漏抄，导致按钮恒不显示（2026-10-02 修复）。
  showAoeModeButton = true,
  testSpells = { 78, 100, 6673, 772, 6343, 7384, 72, 2687, 6572, 845, 1240193, 402927, 5308, 1680, 6552, 12294, 23881, 23922, 1310222, 12292, 12328 },
  gcdProbeSpellIDs = { 25289, 11551, 11550, 11549, 6192, 5242, 6673,
    11574, 11573, 11572, 6548, 6547, 6546, 772 },
  actionAvailSpellIDs = { 78, 100, 6673, 772, 6343, 7384, 72, 2687, 6572, 845, 1240193, 402927, 5308, 1680, 6552, 12294, 23881, 23922, 1310222, 12292, 12328,
  -- BEGIN GENERATED FOREVER
871, 12975,
  -- END GENERATED FOREVER
  },
  pixelData = {
    { id = "player_valid", label = "玩家有效", type = "switch" },
    { id = "target_valid", label = "敌对目标", type = "switch" },
    { id = "player_in_combat", label = "玩家战斗中", type = "switch" },
    { id = "auto_attack_active", label = "自动攻击", type = "validity" },
    { id = "strike_queued", label = "英勇或顺劈已排队", type = "validity" },
    { id = "primary_known", label = "已学天赋主攻", type = "switch" },
    { id = "stance", label = "姿态", type = "number" },
    { id = "rage", label = "怒气", type = "number" },
    { id = "player_moving", label = "正在移动", type = "validity" },
    { id = "cd_100", label = "冲锋冷却", type = "cooldown" },
    { id = "cd_6343", label = "雷霆一击冷却", type = "cooldown" },
    { id = "cd_7384", label = "压制冷却", type = "cooldown" },
    { id = "cd_72", label = "盾击冷却", type = "cooldown" },
    { id = "cd_2687", label = "血性狂暴冷却", type = "cooldown" },
    { id = "cd_6572", label = "复仇冷却", type = "cooldown" },
    { id = "cd_1240193", label = "猛击冷却", type = "cooldown" },
    { id = "cd_1680", label = "旋风斩冷却", type = "cooldown" },
    { id = "cd_6552", label = "拳击冷却", type = "cooldown" },
    { id = "cd_12294", label = "致死打击冷却", type = "cooldown" },
    { id = "cd_23881", label = "嗜血冷却", type = "cooldown" },
    { id = "cd_23922", label = "盾牌猛击冷却", type = "cooldown" },
    { id = "cd_1310222", label = "穿刺打击冷却", type = "cooldown" },
    { id = "cd_12292", label = "横扫攻击冷却", type = "cooldown" },
    { id = "cd_12328", label = "死亡之愿冷却", type = "cooldown" },
  -- BEGIN GENERATED FOREVER
    { id = "pet_valid", label = "宠物存活", type = "validity" },
    { id = "pet_on_target", label = "宠物攻击当前目标", type = "validity" },
    { id = "stealthed", label = "潜行", type = "validity" },
    { id = "form", label = "形态", type = "number" },
    { id = "energy", label = "能量", type = "number" },
    { id = "combo_points", label = "连击点", type = "number" },
    { id = "mana_pct", label = "法力百分比", type = "number" },
    { id = "warrior_talents", label = "天赋", type = "talents" },
    { id = "pet_health", label = "宠物血量", type = "number" },
    { id = "fire_totem", label = "火焰图腾", type = "validity" },
    { id = "water_totem", label = "水之图腾", type = "validity" },
    { id = "known_871", label = "盾墙已学", type = "validity" },
    { id = "range_871", label = "盾墙射程", type = "validity" },
    { id = "known_12975", label = "破釜沉舟已学", type = "validity" },
    { id = "range_12975", label = "破釜沉舟射程", type = "validity" },
    { id = "known_2565", label = "盾牌格挡已学", type = "validity" },
    { id = "range_2565", label = "盾牌格挡射程", type = "validity" },
    { id = "ready_2565", label = "盾牌格挡可用", type = "validity" },
    { id = "known_7386", label = "破甲攻击已学", type = "validity" },
    { id = "range_7386", label = "破甲攻击射程", type = "validity" },
    { id = "ready_7386", label = "破甲攻击可用", type = "validity" },
    { id = "known_1160", label = "挫志怒吼已学", type = "validity" },
    { id = "range_1160", label = "挫志怒吼射程", type = "validity" },
    { id = "ready_1160", label = "挫志怒吼可用", type = "validity" },
    { id = "known_355", label = "嘲讽已学", type = "validity" },
    { id = "range_355", label = "嘲讽射程", type = "validity" },
    { id = "ready_355", label = "嘲讽可用", type = "validity" },
  -- END GENERATED FOREVER
  },
  ACTION_LABELS = {
    start_attack = "自动攻击",
    spell_100 = "冲锋",
    spell_6673 = "战斗怒吼",
    spell_2687 = "血性狂暴",
    spell_6552 = "拳击",
    spell_72 = "盾击",
    spell_5308 = "斩杀",
    spell_7384 = "压制",
    spell_6572 = "复仇",
    spell_402927 = "乘胜追击",
    spell_12294 = "致死打击",
    spell_23881 = "嗜血",
    spell_23922 = "盾牌猛击",
    spell_1310222 = "穿刺打击",
    spell_12292 = "横扫攻击",
    spell_12328 = "死亡之愿",
    spell_772 = "撕裂",
    spell_1680 = "旋风斩",
    spell_6343 = "雷霆一击",
    spell_1240193 = "猛击",
    spell_845 = "顺劈斩",
    spell_78 = "英勇打击",
    spell_871 = "盾墙",
    spell_12975 = "破釜沉舟",
    spell_2565 = "盾牌格挡",
    spell_7386 = "破甲攻击",
    spell_1160 = "挫志怒吼",
    spell_355 = "嘲讽",
    spell_1464 = "猛击",
    spell_1719 = "鲁莽",
    spell_18499 = "狂暴之怒",
    spell_402913 = "狂怒回复",
    spell_402911 = "怒击",
    spell_2457 = "战斗姿态",
    spell_71 = "防御姿态",
    spell_2458 = "狂暴姿态",
    spell_412513 = "角斗姿态",
    spell_1715 = "断筋",
    spell_429765 = "迅捷打击",
    spell_20252 = "拦截",
    spell_676 = "缴械",
    spell_694 = "惩戒痛击",
    spell_1161 = "挑战怒吼",
    spell_5246 = "破胆怒吼",
    spell_403228 = "肉钩",
    spell_440488 = "震荡波",
    spell_20230 = "反击风暴",
    spell_403215 = "命令怒吼",
    spell_426490 = "集结呐喊",
    spell_426972 = "警戒",
    spell_461475 = "艾泽拉斯之勇",
    spell_2480 = "远程武器攻击",
    spell_12809 = "震荡猛击",
    spell_12323 = "刺耳怒吼",
    spell_6552_focus = "焦点拳击",
    spell_6552_mouseover = "指向拳击",
    spell_72_focus = "焦点盾击",
    spell_72_mouseover = "指向盾击",
  },
  ACTION_TO_KEY = {
    start_attack = "NUMPAD1",
    spell_100 = "NUMPAD2",
    spell_6673 = "NUMPAD3",
    spell_2687 = "NUMPAD4",
    spell_6552 = "NUMPAD5",
    spell_72 = "NUMPAD6",
    spell_5308 = "NUMPAD7",
    spell_7384 = "NUMPAD8",
    spell_6572 = "NUMPAD9",
    spell_402927 = "NUMPAD0",
    spell_12294 = "CTRL-NUMPAD1",
    spell_23881 = "CTRL-NUMPAD2",
    spell_23922 = "CTRL-NUMPAD3",
    spell_1310222 = "CTRL-NUMPAD4",
    spell_12292 = "CTRL-NUMPAD5",
    spell_12328 = "CTRL-NUMPAD6",
    spell_772 = "CTRL-NUMPAD7",
    spell_1680 = "CTRL-NUMPAD8",
    spell_6343 = "CTRL-NUMPAD9",
    spell_1240193 = "CTRL-NUMPAD0",
    spell_845 = "ALT-NUMPAD1",
    spell_78 = "ALT-NUMPAD2",
    spell_871 = "ALT-NUMPAD3",
    spell_12975 = "ALT-NUMPAD4",
    spell_2565 = "ALT-NUMPAD5",
    spell_7386 = "ALT-NUMPAD6",
    spell_1160 = "ALT-NUMPAD7",
    spell_355 = "ALT-NUMPAD8",
    spell_1464 = "SHIFT-NUMPAD1",
    spell_1719 = "SHIFT-NUMPAD2",
    spell_18499 = "SHIFT-NUMPAD3",
    spell_402913 = "SHIFT-NUMPAD4",
    spell_402911 = "SHIFT-NUMPAD5",
    spell_2457 = "SHIFT-NUMPAD6",
    spell_71 = "SHIFT-NUMPAD7",
    spell_2458 = "SHIFT-NUMPAD8",
    spell_412513 = "SHIFT-NUMPAD9",
    spell_1715 = "SHIFT-NUMPAD0",
    spell_429765 = "SHIFT-F1",
    spell_20252 = "SHIFT-F2",
    spell_676 = "SHIFT-F3",
    spell_694 = "SHIFT-F4",
    spell_1161 = "SHIFT-F5",
    spell_5246 = "SHIFT-F6",
    spell_403228 = "SHIFT-F7",
    spell_440488 = "SHIFT-F8",
    spell_20230 = "SHIFT-F9",
    spell_403215 = "SHIFT-F10",
    spell_426490 = "SHIFT-F11",
    spell_426972 = "SHIFT-F12",
    spell_461475 = "SHIFT--",
    spell_2480 = "SHIFT-=",
    spell_12809 = "SHIFT-[",
    spell_12323 = "SHIFT-]",
    spell_6552_focus = "SHIFT-;",
    spell_6552_mouseover = "SHIFT-'",
    spell_72_focus = "SHIFT-,",
    spell_72_mouseover = "SHIFT-.",
  },
  macroOrder = {
    "start_attack",
    "spell_100",
    "spell_6673",
    "spell_2687",
    "spell_6552",
    "spell_72",
    "spell_5308",
    "spell_7384",
    "spell_6572",
    "spell_402927",
    "spell_12294",
    "spell_23881",
    "spell_23922",
    "spell_1310222",
    "spell_12292",
    "spell_12328",
    "spell_772",
    "spell_1680",
    "spell_6343",
    "spell_1240193",
    "spell_845",
    "spell_78",
    "spell_871",
    "spell_12975",
    "spell_2565",
    "spell_7386",
    "spell_1160",
    "spell_355",
    "spell_1464",
    "spell_1719",
    "spell_18499",
    "spell_402913",
    "spell_402911",
    "spell_2457",
    "spell_71",
    "spell_2458",
    "spell_412513",
    "spell_1715",
    "spell_429765",
    "spell_20252",
    "spell_676",
    "spell_694",
    "spell_1161",
    "spell_5246",
    "spell_403228",
    "spell_440488",
    "spell_20230",
    "spell_403215",
    "spell_426490",
    "spell_426972",
    "spell_461475",
    "spell_2480",
    "spell_12809",
    "spell_12323",
    "spell_6552_focus",
    "spell_6552_mouseover",
    "spell_72_focus",
    "spell_72_mouseover",
  },
  GetExtraValues = function(values)
    values.player_valid = UnitExists("player") == true and not UnitIsDeadOrGhost("player")
    values.target_valid = UnitExists("target") == true and not UnitIsDeadOrGhost("target") and UnitCanAttack("player", "target") == true
    values.player_in_combat = UnitAffectingCombat("player") == true
    values.auto_attack_active = currentSpell({ 6603 })
    local queuedIDs = knownRanks(78)
    for _, id in ipairs(knownRanks(845)) do queuedIDs[#queuedIDs + 1] = id end
    values.strike_queued = currentSpell(queuedIDs)
    values.primary_known = #knownRanks(12294) > 0 or #knownRanks(23881) > 0 or #knownRanks(23922) > 0
    values.rage = rageValue()
    -- Restore the original warrior's independent text display path.
    local displayOK, display = pcall(function()
      return tostring(UnitPower("player", Enum.PowerType.Rage))
    end)
    WowBuddyDev.rageDisplay = displayOK and display or "状态未确认"
    local stanceOK, stance = pcall(function() return WowBuddyDev.SafeNumber(GetShapeshiftForm()) end)
    values.stance = stanceOK and stance or 0
    local movingOK, moving = pcall(function() return GetUnitSpeed("player") > 0 end)
    values.player_moving = nil
    if movingOK then values.player_moving = moving end
    -- Read the learned rank through Core; no fixed cast timer or cooldown override.
    for _, id in ipairs({ 100, 6343, 7384, 72, 2687, 6572, 1240193, 1680, 6552, 12294, 23881, 23922, 1310222, 12292, 12328 }) do
      local ranks = knownRanks(id)
      local remaining = #ranks > 0 and 0 or 601
      for _, rankID in ipairs(ranks) do
        local ok, seconds = pcall(WowBuddyDev.GetSpellCooldownRemaining, rankID)
        if not ok or type(seconds) ~= "number" then
          remaining = 601
          break
        end
        remaining = math.max(remaining, seconds)
      end
      values["cd_" .. id] = remaining
    end
  end,
})

-- BEGIN FOREVER EXTENSION
local data = WowBuddyDev.classes[1491]
local original = data.GetExtraValues
data.foreverSpells = { 871, 12975, 2565, 7386, 1160, 355 }
data.GetExtraValues = function(values)
  original(values)
  if WowBuddyDev.FillForeverExtraValues then WowBuddyDev.FillForeverExtraValues(values, 1491) end
end
