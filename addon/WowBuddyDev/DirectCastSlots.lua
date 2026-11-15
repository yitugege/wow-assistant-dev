-- 恢复原 DirectCast 的槽位登记与只读索引部分。
-- 本文件不执行施法/占槽，由 Actions 消费；其余分支见完整性清单。
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("DirectCastSlots", { "CoreButtons" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local ADDON = WowBuddyDev
local DC = ADDON.DirectCast or {}
ADDON.DirectCast = DC
DC.slots = DC.slots or {}
local classSlots = {}

function DC.GetManualSlot(actionKey)
  local classAction = ADDON.NormalizeClassActionKey and ADDON.NormalizeClassActionKey(actionKey)
  return (classAction and (classSlots[classAction] or DC.slots[classAction])) or DC.slots[actionKey]
end

local slotBySpell = {}

local function spellInSlot(slot)
  local ok, kind, spellID = pcall(GetActionInfo, slot)
  if not ok or (issecretvalue and (issecretvalue(kind) or issecretvalue(spellID))) then return nil end
  if kind == "spell" and type(spellID) == "number" then return spellID end
end

function DC.IsSpellInSlot(slot, spellID)
  local current = spellInSlot(slot)
  return current ~= nil and current == spellID
end

local function buildSlotIndex()
  wipe(slotBySpell)
  for slot = 1, 144 do
    local spellID = spellInSlot(slot)
    if spellID then slotBySpell[spellID] = slot end
  end
end

-- 同技能仍优先选最后一个槽，缓存命中后核对动作条当前内容。
function DC.FindSlotForSpell(spellID)
  local cached = slotBySpell[spellID]
  if cached and DC.IsSpellInSlot(cached, spellID) then return cached end
  buildSlotIndex()
  return slotBySpell[spellID]
end

SLASH_DCBIND1 = "/dcbind"
SlashCmdList.DCBIND = function(msg)
  local key, slot = msg:match("^(%S+)%s+(%d+)$")
  if key and slot then
    local number = tonumber(slot)
    DC.slots[key] = number
    local classAction = ADDON.NormalizeClassActionKey and ADDON.NormalizeClassActionKey(key)
    if classAction then classSlots[classAction] = number end
    print(string.format("|cff00ff88[DirectCast]|r %s → 动作条槽位 %d", key, number))
  else
    print("用法: /dcbind <动作键> <槽位号>  例: /dcbind spell_403 61")
  end
end
