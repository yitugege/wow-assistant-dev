-- Shared class observations through the existing spell and color-curve APIs.
local ADDON = WowBuddyDev
local UNKNOWN = 16777215
local units = {"player", "target", "party1", "party2", "party3", "party4"}
local curves = {}

local function observe(fn, ...)
  if type(fn) ~= "function" then return nil end
  local ok, value = pcall(fn, ...)
  if ok then return value end
end

local function colorPercent(unit, powerType, health)
  local ok, value = pcall(function()
    if C_CurveUtil and C_CurveUtil.CreateColorCurve and Enum and Enum.LuaCurveType then
      if not curves.percent then
        local curve = C_CurveUtil.CreateColorCurve()
        curve:SetType(Enum.LuaCurveType.Step)
        for i = 0, 100 do curve:AddPoint(i / 100, CreateColor(0, 0, i / 255, 1)) end
        curves.percent = curve
      end
      local color
      if health and UnitHealthPercent then color = UnitHealthPercent(unit, true, curves.percent)
      elseif not health and UnitPowerPercent then color = UnitPowerPercent(unit, powerType, false, curves.percent) end
      if type(color) == "table" and color.GetRGB then return color end
    end
    local amount = health and UnitHealth(unit) or UnitPower(unit, powerType)
    local maximum = health and UnitHealthMax(unit) or UnitPowerMax(unit, powerType)
    if maximum > 0 then return math.floor(100 * amount / maximum) end
  end)
  return ok and value or UNKNOWN
end

local function alive(unit)
  return observe(function() return UnitExists(unit) == true and not UnitIsDeadOrGhost(unit) end)
end

local function learnedRank(data, spell)
  local found, unknown
  for _, id in ipairs(data.spellReadyAliases[spell] or {spell}) do
    local known = observe(ADDON.IsSpellKnown, id)
    if known == true then found = id elseif known == nil then unknown = true end
  end
  if found then return found, true end
  if not unknown then return nil, false end
end

local function inRange(rank, known, unit)
  if known == false then return false end
  if not rank then return nil end
  return observe(function()
    if alive(unit) ~= true then return false end
    if unit == "player" then return true end
    if not (C_Spell and C_Spell.IsSpellInRange) then return nil end
    local result = C_Spell.IsSpellInRange(rank, unit)
    if result == true or result == 1 then return true end
    if result == false or result == 0 then return false end
  end)
end

function ADDON.FillForeverExtraValues(values, specID)
  local data = ADDON.classes[specID]
  local definition = ADDON.ForeverTalentData[specID]
  values[definition.token:lower() .. "_talents"] = ADDON.GetForeverTalentState(specID).packet
  if values.player_valid == nil then values.player_valid = alive("player") end
  if values.target_valid == nil then
    values.target_valid = observe(function() return alive("target") == true and UnitCanAttack("player", "target") == true end)
  end
  if values.player_in_combat == nil then values.player_in_combat = observe(UnitAffectingCombat, "player") end
  if values.player_moving == nil then values.player_moving = observe(function() return GetUnitSpeed("player") > 0 end) end
  -- ★ 2026-10-03：明确 boolean（== true），不再让 observe 的 nil 漏出去。
  --   auto_attack_active 被 start_attack 规则用 FLAG(x,False) 消费（「没在自动攻击才发」），
  --   而 C_Spell.IsCurrentSpell 在无限客户端可能读不到（与战士 strike_queued 同源缺陷）：
  --   nil 经引擎三态判定「读不到永不等于 False」⇒ start_attack 永不触发（近战不出手）。
  --   兜底 false = 读不到当作「没在自动攻击」⇒ 发 /startattack（幂等，hold_ms 压制下每秒至多一次）。
  if values.auto_attack_active == nil then values.auto_attack_active = observe(C_Spell and C_Spell.IsCurrentSpell, 6603) == true end
  values.stealthed = observe(IsStealthed)
  values.form = observe(function() return GetShapeshiftFormID() or 0 end) or UNKNOWN
  values.energy = observe(function()
    local power = UnitPower("player", 3)
    if power >= 0 and power <= 200 then return power end
  end) or UNKNOWN
  values.combo_points = observe(function()
    local power = UnitPower("player", 4)
    if power >= 0 and power <= 5 then return power end
  end) or UNKNOWN
  values.mana_pct = colorPercent("player", 0)
  -- ★ 2026-10-04：法力百分比「?/状态未确认」两轮返场后的最终修法。
  --   实测本客户端 colorPercent 的曲线路（UnitPowerPercent+curve）拿不到法力 ⇒
  --   values.mana_pct 恒 UNKNOWN(16777215) ⇒ 面板显示坏 + 引擎回蓝规则（mana<30% 等）恒跳过。
  --   而战士 rageValue 的 UnitPower 直读路（pcall + type/range 检查）实测可用 ⇒ 照抄口径：
  --   ① colorPercent 结果是颜色表 → 原样用（引擎同源）；② 是数字且 ≠UNKNOWN → 原样用；
  --   ③ 其余（UNKNOWN/nil）→ UnitPower/UnitPowerMax 直算百分比兜底（救活引擎规则）。
  --   显示文字 manaDisplay 同样三态接住，9 职业公共一处。
  if type(values.mana_pct) ~= "table" then
    local okPct, pct = pcall(function()
      local cur = UnitPower("player", 0)
      local max = UnitPowerMax("player", 0)
      if type(cur) == "number" and type(max) == "number" and max > 0 and cur >= 0 and cur <= max then
        return math.floor(100 * cur / max + 0.5)
      end
    end)
    if okPct and type(pct) == "number" then values.mana_pct = pct end
  end
  do
    -- ★ 2026-10-04 终版（15g）：用户截图实锤 table.concat 报 'invalid value (secret)'
    --   ⇒ 本客户端对资源类 API 返回值故意投毒（反作弊：禁止 lua 读资源数值），
    --   连 tostring 的结果都带毒 ⇒ 任何拼接触炸。教训：诊断探针绝不能把游戏返回值
    --   拼进 table（每帧炸 2039 次且中断 Fill 后续字段）。
    --   终版策略：整体一个 pcall 保证永不外泄；先试常规直算，再试 tostring→tonumber
    --   往返解毒；都不通则显「已隐藏」（引擎侧走像素条不受影响，纯显示问题）。
    local okDisp, disp = pcall(function()
      local calcOK, calc = pcall(function()
        local cur, max = UnitPower("player", 0), UnitPowerMax("player", 0)
        if type(cur) == "number" and type(max) == "number" and max > 0 and cur >= 0 and cur <= max then
          return math.floor(100 * cur / max + 0.5)
        end
      end)
      if calcOK and type(calc) == "number" then return string.format("%d%%", calc) end
      local recOK, rec = pcall(function()
        local curS = tonumber(tostring(UnitPower("player", 0)))
        local maxS = tonumber(tostring(UnitPowerMax("player", 0)))
        if type(curS) == "number" and type(maxS) == "number" and maxS > 0 then
          return math.floor(100 * curS / maxS + 0.5)
        end
      end)
      if recOK and type(rec) == "number" then return string.format("%d%%", rec) end
      return "已隐藏(客户端保密)"
    end)
    WowBuddyDev.manaDisplay = okDisp and disp or "已隐藏"
  end
  if values.rage == nil then values.rage = colorPercent("player", 1) end
  values.pet_valid = alive("pet")
  values.pet_on_target = observe(function()
    return alive("pet") == true and UnitIsUnit("pettarget", "target") == true and UnitAffectingCombat("pet") == true
  end)
  values.pet_health = alive("pet") == true and colorPercent("pet", nil, true) or UNKNOWN
  for key, slot in pairs({fire_totem=1, water_totem=3}) do
    values[key] = observe(function()
      local have, _, start, duration = GetTotemInfo(slot)
      return have == true and start + duration > GetTime()
    end)
  end
  for _, unit in ipairs(units) do
    values["friendly_" .. unit] = observe(function()
      return alive(unit) == true and UnitCanAssist("player", unit) == true
    end)
    values["health_" .. unit] = values["friendly_" .. unit] == true and colorPercent(unit, nil, true) or UNKNOWN
  end
  -- 当前焦点落在哪个单位上：0=自己，1..4=party1..4，5=不是队友（含敌人）或没有焦点。
  -- 为什么需要它：软件侧每帧只知道「该治谁」，不知道焦点**现在**是谁。没有这个
  -- 字段，「切焦点键要不要重发」只能靠时间窗猜，猜错就是治疗打到别人身上。
  -- 只声明给带治疗动作的专精（见 tools/build_forever_profiles.py 的 pixelData）。
  -- 全程走 observe/pcall：12.1 的 secret value 连比较都会抛错，抛错就按「不是它」算。
  values.focus_index = observe(function()
    if type(UnitIsUnit) ~= "function" then return nil end
    if UnitExists("focus") ~= true then return 5 end
    if UnitIsUnit("focus", "player") == true then return 0 end
    for index = 1, 4 do
      if UnitIsUnit("focus", "party" .. index) == true then return index end
    end
    return 5
  end)
  if values.focus_index == nil then values.focus_index = UNKNOWN end
  for _, spell in ipairs(data.foreverSpells or {}) do
    local rank, known = learnedRank(data, spell)
    values["known_" .. spell] = known
    values["ready_" .. spell] = observe(ADDON.IsSpellReady, spell)
    values["range_" .. spell] = inRange(rank, known, "target")
    for _, unit in ipairs(units) do
      values["range_" .. spell .. "_" .. unit] = inRange(rank, known, unit)
    end
  end
end
