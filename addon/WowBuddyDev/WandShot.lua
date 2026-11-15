-- 独立版的魔杖填充动作，沿用现有安全宏与有效绑定检查。
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("WandShot", { "CoreSettings", "CoreButtons", "AutoTarget" }) or _G.WowBuddyDev -- @@注册表命名空间@@
local addon = WowBuddyDev
local spellID = 5019
local classes = { MAGE = true, PRIEST = true, WARLOCK = true }
local bindingKey, bindingIndex, macroBody

local function read(func, ...)
  if type(func) ~= "function" then return nil end
  local ok, value = pcall(func, ...)
  if ok and (not issecretvalue or not issecretvalue(value)) then return value end
end

function addon.ApplyWandBinding()
  bindingKey, bindingIndex, macroBody = nil, nil, nil
  local _, class = UnitClass("player")
  if not classes[class] or not C_Spell then return end
  local name = read(C_Spell.GetSpellName, spellID)
  if type(name) ~= "string" or name == "" or name:find("[%c;]") then return end
  local reserved = {}
  for _ = 1, 81 do
    local key, index = addon.FindFreeAutomationKey(reserved)
    if not key or index > 81 then return end
    reserved[key] = true
    if read(GetBindingAction, key, false) == "" and read(GetBindingAction, key, true) == "" then
      local body = "/cast [harm,nodead,nochanneling] !" .. name
      if addon.CreateSecureButton("shoot_wand", key, body) then
        bindingKey, bindingIndex, macroBody = key, index, body
      end
      return
    end
  end
end

function addon.GetReadyWandKey()
  if not bindingIndex or not addon.DB or addon.DB.masterSwitch ~= true or not (C_Item and C_Spell) then return end
  local weaponType = read(C_Item.GetItemSubClassInfo, 2, 19) -- 武器类别中的魔杖子类
  if type(weaponType) ~= "string" or weaponType == "" or read(C_Item.IsEquippedItemType, weaponType) ~= true then return end
  if read(UnitExists, "target") ~= true or read(UnitCanAttack, "player", "target") ~= true
      or read(UnitIsDeadOrGhost, "player") ~= false or read(UnitIsDeadOrGhost, "target") ~= false
      or read(UnitPlayerControlled, "target") ~= false or read(UnitIsTapDenied, "target") ~= false
      or read(GetUnitSpeed, "player") ~= 0 or read(C_Spell.IsSpellInRange, spellID, "target") ~= true
      or read(C_Spell.IsSpellUsable, spellID) ~= true or read(C_Spell.IsCurrentSpell, spellID) ~= false then return end
  local focusOK, focus = pcall(GetCurrentKeyBoardFocus)
  if not focusOK or (issecretvalue and issecretvalue(focus)) or focus ~= nil then return end
  local button = addon.GetSecureButton("shoot_wand")
  if not button or button:GetAttribute("type") ~= "macro" or button:GetAttribute("macrotext") ~= macroBody
      or read(GetBindingAction, bindingKey, false) ~= ""
      or read(GetBindingAction, bindingKey, true) ~= "CLICK " .. button:GetName() .. ":LeftButton" then return end
  return bindingIndex
end
