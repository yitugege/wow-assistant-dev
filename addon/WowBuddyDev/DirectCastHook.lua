-- DirectCast 的按钮点击挂钩（独立实现，不沿用原 OnClick 后置挂钩）。
-- 依据实机点击顺序 PreClick → 默认动作 → OnClick 挂钩 → PostClick：
-- 只有 PreClick 能赶在宏之前，所以判断放在 PreClick，属性在 PostClick 还原。
-- 只做两件事：读条技能在移动中、或自 Buff 光环仍在时，让这一次点击不触发宏。
-- 不调用 UseAction / CastSpellByID，也不登记停步补发；重发由桌面端循环重新决策。
-- 战斗中游戏禁止插件改写安全按钮属性，此时不做任何改动，点击照常走宏。
local ADDON = WowBuddyDev
local DC = ADDON.DirectCast
local SWALLOW_TYPE = "emptybutton"
local RELEASE_WINDOW = 1.0
local LOG_LIMIT = 200
local EVENT_WINDOW = 1.5
local EVENTS_PER_PRESS = 8

local hooked = {}
local active = {}
local stats = {installed = 0, swallowed = 0, combatSkipped = 0, errors = 0}
DC.hookEnabled = true

local function readable(value)
  if issecretvalue and issecretvalue(value) then return "secret" end
  if value == nil then return nil end
  return tostring(value)
end

local function inCombat()
  -- 读不到明确的 false 就按战斗处理，宁可不拦也不去碰安全属性。
  return type(InCombatLockdown) ~= "function" or InCombatLockdown() ~= false
end

-- 实机验收用的按键记录；只写本插件的存档变量，不影响点击判断。
local lastEntry
local function hookLog()
  if type(WowBuddyDevHookLog) ~= "table" or type(WowBuddyDevHookLog.presses) ~= "table" then
    local version, build, _, interface = GetBuildInfo()
    WowBuddyDevHookLog = {version = readable(version), build = readable(build),
      interface = readable(interface), started = time and time() or 0, presses = {}}
  end
  return WowBuddyDevHookLog
end

local function record(actionKey, decision, reason, button)
  local ok, speed = pcall(GetUnitSpeed, "player")
  local entry = {
    action = actionKey, decision = decision, reason = reason,
    at = GetTime(), wall = time and time() or 0,
    speed = ok and readable(speed) or "error",
    combat = inCombat(), typeAtClick = readable(button:GetAttribute("type")),
    events = {},
  }
  local presses = hookLog().presses
  presses[#presses + 1] = entry
  while #presses > LOG_LIMIT do table.remove(presses, 1) end
  lastEntry = entry
  return entry
end

local function swallowReason(actionKey)
  if DC.IsMovingCast and DC.IsMovingCast(actionKey) then return "moving-cast" end
  local macro = DC.GetActionMacro and DC.GetActionMacro(actionKey)
  if type(macro) ~= "string" then return nil end
  local spellName = DC.ResolveMacro(macro)
  if spellName and DC.GuardBlocked(spellName) then return "blocked-aura-present" end
  return nil
end

local function restore(button)
  local state = active[button]
  if not state or not state.applied then return true end
  if inCombat() then return false end
  if button:GetAttribute("type") == SWALLOW_TYPE then
    button:SetAttribute("type", state.previous or "macro")
  end
  state.applied = false
  return true
end

local function apply(button, state)
  local current = button:GetAttribute("type")
  if current ~= SWALLOW_TYPE then state.previous = current end
  button:SetAttribute("type", SWALLOW_TYPE)
  state.applied = true
end

local function preClick(button, _, down)
  local actionKey = hooked[button]
  if not actionKey then return end
  if not (DC.enabled and DC.hookEnabled) then
    if down then record(actionKey, "disabled", nil, button) end
    return
  end
  if down then
    active[button] = nil
    local reason = swallowReason(actionKey)
    if not reason then
      record(actionKey, "pass", nil, button)
      return
    end
    if inCombat() then
      stats.combatSkipped = stats.combatSkipped + 1
      stats.lastSkipped = reason
      record(actionKey, "combat-pass", reason, button)
      return
    end
    local state = {reason = reason, at = GetTime()}
    active[button] = state
    apply(button, state)
    stats.swallowed = stats.swallowed + 1
    stats.lastReason, stats.lastAction = reason, actionKey
    state.entry = record(actionKey, "swallow", reason, button)
    return
  end
  -- 抬起阶段：同一次按键的按下已被拦下时，抬起也不放行。
  local state = active[button]
  if not state then return end
  if GetTime() - state.at > RELEASE_WINDOW or inCombat() then
    active[button] = nil
    return
  end
  apply(button, state)
end

local function postClick(button, _, down)
  local state = active[button]
  if not state then return end
  restore(button)
  if state.entry and down then state.entry.typeAfterPost = readable(button:GetAttribute("type")) end
  if not down and not state.applied then active[button] = nil end
end

local function guarded(fn)
  return function(...)
    local ok = pcall(fn, ...)
    if not ok then stats.errors = stats.errors + 1 end
  end
end

-- Core 在按钮成功绑定后回调；同一按钮重绑只更新动作键，不重复挂钩。
function DC.AttachButton(button, actionKey)
  if type(button) ~= "table" or type(button.HookScript) ~= "function"
      or type(actionKey) ~= "string" or actionKey == "" then
    return false
  end
  if hooked[button] then
    hooked[button] = actionKey
    return true
  end
  hooked[button] = actionKey
  button:HookScript("PreClick", guarded(preClick))
  button:HookScript("PostClick", guarded(postClick))
  stats.installed = stats.installed + 1
  return true
end
ADDON.OnSecureButtonBound = DC.AttachButton

local SPELL_EVENTS = {
  UNIT_SPELLCAST_SENT = true, UNIT_SPELLCAST_START = true, UNIT_SPELLCAST_SUCCEEDED = true,
  UNIT_SPELLCAST_FAILED = true, UNIT_SPELLCAST_FAILED_QUIET = true, UNIT_SPELLCAST_INTERRUPTED = true,
}

-- 把按键后短时间内的施法事件和红字错误挂到最近一次按键上，供离线分析。
local function attachEvent(event, ...)
  if not lastEntry or GetTime() - lastEntry.at > EVENT_WINDOW then return end
  local events = lastEntry.events
  if #events >= EVENTS_PER_PRESS then return end
  local item = {event = event, dt = GetTime() - lastEntry.at}
  if SPELL_EVENTS[event] then
    local unit = ...
    if unit ~= "player" then return end
    local count = select("#", ...)
    item.spell = readable(select(count, ...))
  else
    local _, message = ...
    item.message = readable(message)
  end
  events[#events + 1] = item
end

-- 兜底：如果属性因故没在 PostClick 还原，脱战后统一还原。
local watcher = CreateFrame("Frame")
watcher:RegisterEvent("PLAYER_REGEN_ENABLED")
watcher:RegisterEvent("UI_ERROR_MESSAGE")
for event in pairs(SPELL_EVENTS) do watcher:RegisterEvent(event) end
watcher:SetScript("OnEvent", function(_, event, ...)
  if event ~= "PLAYER_REGEN_ENABLED" then
    pcall(attachEvent, event, ...)
    return
  end
  for button, state in pairs(active) do
    if state.applied then pcall(restore, button) end
    if not state.applied then active[button] = nil end
  end
end)

function DC.HookStatus()
  local presses = type(WowBuddyDevHookLog) == "table" and type(WowBuddyDevHookLog.presses) == "table"
      and #WowBuddyDevHookLog.presses or 0
  return {
    enabled = DC.enabled and DC.hookEnabled or false,
    installed = stats.installed, swallowed = stats.swallowed,
    combatSkipped = stats.combatSkipped, errors = stats.errors,
    lastReason = stats.lastReason, lastAction = stats.lastAction,
    lastSkipped = stats.lastSkipped, logged = presses,
  }
end

function DC.ClearHookLog()
  WowBuddyDevHookLog = nil
  lastEntry = nil
end
