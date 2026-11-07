-- 恢复原 DirectCast 的槽位登记与只读索引部分。
-- 不执行施法/自动占槽；其余 DirectCast 分支仍待接入，见完整性清单。
local ADDON = WowBuddyDev
local DC = ADDON.DirectCast or {}
ADDON.DirectCast = DC
DC.slots = DC.slots or {}

local slotBySpell = {}
local function buildSlotIndex()
  wipe(slotBySpell)
  for slot = 1, 144 do
    local ok, kind, spellID = pcall(GetActionInfo, slot)
    if ok and kind == "spell" and spellID then
      slotBySpell[spellID] = slot
    end
  end
end

-- 原实现同技能取最后一个槽；非空索引不自动刷新，保留原对照行为。
function DC.FindSlotForSpell(spellID)
  if not next(slotBySpell) then buildSlotIndex() end
  return slotBySpell[spellID]
end

SLASH_DCBIND1 = "/dcbind"
SlashCmdList.DCBIND = function(msg)
  local key, slot = msg:match("^(%S+)%s+(%d+)$")
  if key and slot then
    DC.slots[key] = tonumber(slot)
    print(string.format("|cff00ff88[DirectCast]|r %s → 动作条槽位 %d", key, tonumber(slot)))
  else
    print("用法: /dcbind <动作键> <槽位号>  例: /dcbind spell_403 61")
  end
end
