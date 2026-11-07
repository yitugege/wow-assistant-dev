-- 原 DirectCast 的宏解析与只读光环判断，供 Actions 等模块使用。
local ADDON = WowBuddyDev
local DC = ADDON.DirectCast
local spellCache = {}

function DC.ResolveMacro(macroBody)
  if type(macroBody) ~= "string" then return nil end
  local unit = "target"
  local selfCast = macroBody:match("@player") or macroBody:match("%[noharm%]")
  local spellName = macroBody:match("%]%s*([^;]+)$") or macroBody:match("/cast%s+(.+)$")
  if spellName then
    spellName = spellName:gsub("%s+", " "):gsub("^%s+", ""):gsub("%s+$", "")
    if selfCast then unit = "player" end
    return spellName, unit
  end
  return nil
end

function DC.SpellIDForName(name)
  if not name then return nil end
  if spellCache[name] then return spellCache[name] end
  local ok, id = pcall(function()
    local _, _, _, _, _, _, sid = GetSpellInfo(name)
    return sid
  end)
  spellCache[name] = ok and id or nil
  return spellCache[name]
end

local guardInfo
local function buildGuardIDs()
  guardInfo = {}
  if not ADDON._pixelStripV2BySpec then return end
  for _, slots in pairs(ADDON._pixelStripV2BySpec) do
    for _, slot in ipairs(slots) do
      if slot.kind == "presence" and slot.unit == "player"
          and slot.filter == "HELPFUL" and slot.spellIDs then
        for _, sid in ipairs(slot.spellIDs) do
          guardInfo[sid] = {ids=slot.spellIDs, name=slot.name}
        end
      end
    end
  end
end

local function byIDAuraPresent(ids)
  if not (C_UnitAuras and C_UnitAuras.GetPlayerAuraBySpellID) then return false end
  for _, id in ipairs(ids) do
    local ok, aura = pcall(C_UnitAuras.GetPlayerAuraBySpellID, id)
    if ok and aura then return true end
  end
  return false
end

local function nameScanAuraPresent(ids)
  if not (C_UnitAuras and C_UnitAuras.GetAuraDataByIndex) then return nil end
  local getSpellName = C_Spell and C_Spell.GetSpellName
  local wanted = {}
  for _, id in ipairs(ids) do
    if getSpellName then
      local ok, name = pcall(getSpellName, id)
      if ok and type(name) == "string" and name ~= "" then wanted[name] = true end
    end
  end
  if not next(wanted) then return nil end
  local found, complete = false, false
  pcall(function()
    for i = 1, 40 do
      local aura = C_UnitAuras.GetAuraDataByIndex("player", i, "HELPFUL")
      if not aura then complete = true; return end
      if aura.name and wanted[aura.name] then found = true; return end
    end
  end)
  if found then return true end
  if complete then return false end
  return nil
end

function DC.GuardBlocked(spellName)
  if not spellName then return false end
  if not guardInfo then buildGuardIDs() end
  if not next(guardInfo) then return false end
  local _, _, _, _, _, _, sid = GetSpellInfo(spellName)
  if not sid or not guardInfo[sid] then return false end
  local ids = guardInfo[sid].ids
  if byIDAuraPresent(ids) then return true end
  return nameScanAuraPresent(ids) == true
end

-- 与原续挂判断一致：未知也按存在处理，仅确认不存在时返回 false。
function DC.KeeperAuraPresent(ids)
  if byIDAuraPresent(ids) then return true end
  return nameScanAuraPresent(ids) ~= false
end

-- 内部模块共享同一份惰性快照，保留原空快照不重建的行为。
function DC.IterGuardInfo()
  if not guardInfo then buildGuardIDs() end
  return pairs(guardInfo)
end
