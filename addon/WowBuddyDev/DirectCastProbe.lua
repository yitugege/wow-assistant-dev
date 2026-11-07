-- 保留原 EnvCloakCast 入口：在当前 Lua 环境编译并尝试一次普通 API 调用。
-- 不提供解锁器，不改变游戏权限；true仍只表示调用没有抛错。
local DC = WowBuddyDev.DirectCast
function DC.EnvCloakCast(spellID, unit)
  local source = string.format("return CastSpellByID(%d, %q)", spellID, unit or "target")
  local chunk, err = loadstring(source, "DCC")
  if not chunk then return nil, "compile: " .. tostring(err) end
  local environment = getfenv and getfenv() or _G
  if setfenv then setfenv(chunk, environment) end
  local ok, result = pcall(chunk)
  if ok then return true, spellID end
  return nil, result
end
