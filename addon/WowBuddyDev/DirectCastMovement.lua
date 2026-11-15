-- 恢复原移动意图状态机。按钮挂钩只用 IsMovingCast 做只读判断，
-- 不调用 MovementGate，因此不会登记停步后的补发意图。
local DC = WowBuddyDev.DirectCast
local pendingMove
local moveStillTicks = 0

local function macroCastTime(actionKey)
  local macro = DC.GetActionMacro(actionKey)
  if type(macro) ~= "string" then return nil end
  local name, unit = DC.ResolveMacro(macro)
  if not name then return nil end
  local sid, castTime = DC.ReadSpellMetadata(name)
  return castTime or 0, sid, unit
end

-- 只读：读条技能且正在移动时返回 true；读不出速度或读条时间一律返回 false。
function DC.IsMovingCast(actionKey)
  if not DC.enabled then return false end
  local castTime = macroCastTime(actionKey)
  if type(castTime) ~= "number" or castTime <= 0 then return false end
  local speed = GetUnitSpeed("player")
  if type(speed) ~= "number" or (issecretvalue and issecretvalue(speed)) then return false end
  return speed > 0
end

function DC.MovementGate(actionKey)
  if not DC.enabled then return false end
  local castTime, sid, unit = macroCastTime(actionKey)
  if not castTime or castTime <= 0 then return false end
  if GetUnitSpeed("player") <= 0 then return false end
  if sid then pendingMove = {sid=sid, unit=unit, at=GetTime()} end
  return true
end

-- 保留原边界：8秒整仍补发；off不清已有意图；未检查引导状态。
-- 不以pcall成功推断技能生效，API权限仍由游戏执行。
C_Timer.NewTicker(0.1, function()
  pcall(function()
    if not pendingMove then return end
    if GetTime() - pendingMove.at > 8 then pendingMove=nil; return end
    if GetUnitSpeed("player") > 0 then moveStillTicks=0; return end
    moveStillTicks=moveStillTicks+1
    if moveStillTicks < 2 then return end
    moveStillTicks=0
    local pending=pendingMove
    if UnitIsDeadOrGhost and UnitIsDeadOrGhost("player") then pendingMove=nil; return end
    if UnitCastingInfo and UnitCastingInfo("player") then return end
    local start,duration=GetSpellCooldown(pending.sid)
    if start and start>0 and duration and duration>0 and start+duration-GetTime()>0.1 then
      pendingMove=nil; return
    end
    pendingMove=nil
    local ok=false
    local slot=DC.EnsureSlotForSpell(pending.sid)
    if slot then ok=pcall(UseAction,slot,pending.unit or "target") end
    if not ok then pcall(CastSpellByID,pending.sid,pending.unit or "target") end
  end)
end)
