-- 原自Buff续挂调度；调用成功与否仍由游戏权限/状态决定。
local DC = WowBuddyDev.DirectCast
local nextTry = {}

local function keeperTick()
  if not DC.enabled then return end
  local iterator,groups,state = DC.IterGuardInfo()
  if not next(groups) then return end
  if UnitIsDeadOrGhost and UnitIsDeadOrGhost("player") then return end
  if UnitCastingInfo and UnitCastingInfo("player") then return end
  if UnitChannelInfo and UnitChannelInfo("player") then return end
  local now = GetTime()
  local seen = {}
  for _,info in iterator,groups,state do
    local key = tostring(info.ids[1])
    if not seen[key] then
      seen[key] = true
      if now >= (nextTry[key] or 0) and not DC.KeeperAuraPresent(info.ids) then
        local spellID = DC.SpellIDForName(info.name)
        if spellID then
          local start,duration = GetSpellCooldown(spellID)
          if not (start and start>0 and duration and duration>0 and start+duration-now>0.1) then
            local ok = false
            local slot = DC.FindSlotForSpell(spellID) or DC.EnsureSlotForSpell(spellID)
            if slot then ok = pcall(UseAction,slot,"player") end
            if not ok then ok = pcall(CastSpellByID,spellID,"player") end
            nextTry[key] = now+5
            print("|cff00ff88[DirectCast]|r " .. tostring(info.name)
              .. " 光环未找到，已尝试续挂（是否生效以游戏为准）")
          end
        end
      end
    end
  end
end

C_Timer.NewTicker(1.0,function() pcall(keeperTick) end)
