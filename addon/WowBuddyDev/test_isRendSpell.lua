-- 测试 isRendSpell 函数
local spellReadyAliases = {
  [772] = { 772, 6546, 6547, 6548, 11572, 11573, 11574 }
}

local function isRendSpell(spellID)
  local data = { spellReadyAliases = spellReadyAliases }
  for _, id in ipairs(data and data.spellReadyAliases[772] or {}) do
    if spellID == id then return true end
  end
  return false
end

print("isRendSpell(772) =", isRendSpell(772))
print("isRendSpell(6546) =", isRendSpell(6546))
print("isRendSpell(11574) =", isRendSpell(11574))
print("isRendSpell(78) =", isRendSpell(78))
