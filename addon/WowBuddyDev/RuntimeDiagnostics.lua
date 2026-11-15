-- 登出/重载时把只在运行时存在的诊断写入 SavedVariable WowBuddyDevRuntimeLog，供桌面端“导出诊断”收集。
-- 设计与验收：docs/design/20261115-diagnostic-export.md。只读其他模块的表并复制，不调用受保护接口。
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("RuntimeDiagnostics", { "Core", "CoreLocale" }) or _G.WowBuddyDev -- @@注册表命名空间@@

local MODULE_ERROR_LIMIT = 100 -- 模块越界记录：保留最新的
local LUA_ERROR_LIMIT = 10     -- Lua 错误收集器本身最多 10 种（新→旧）
local ERROR_LOG_LIMIT = 50     -- 插件错误日志（新→旧）

local function copyRecord(record)
  if type(record) ~= "table" then
    return record
  end
  local copy = {}
  for key, value in pairs(record) do
    local kind = type(value)
    if kind == "string" or kind == "number" or kind == "boolean" then
      copy[key] = value
    end
  end
  return copy
end

local function head(list, limit)
  local result = {}
  if type(list) == "table" then
    for index = 1, math.min(#list, limit) do
      result[index] = copyRecord(list[index])
    end
  end
  return result
end

local function tail(list, limit)
  local result = {}
  if type(list) == "table" then
    for index = math.max(1, #list - limit + 1), #list do
      result[#result + 1] = copyRecord(list[index])
    end
  end
  return result
end

local function snapshot()
  local luaErrors = WowBuddyDev.GetCapturedLuaErrors and WowBuddyDev.GetCapturedLuaErrors() or nil
  WowBuddyDevRuntimeLog = {
    savedAt = type(time) == "function" and time() or 0,
    addonVersionCode = WowBuddyDev.addonVersionCode,
    moduleErrors = tail(WowBuddyDev.moduleErrors, MODULE_ERROR_LIMIT),
    luaErrors = head(luaErrors, LUA_ERROR_LIMIT),
    errorLogs = head(WowBuddyDev.errorLogs, ERROR_LOG_LIMIT),
  }
end

-- 快照失败只记录原因，不影响登出与其他模块。
local function safeSnapshot()
  local ok, err = pcall(snapshot)
  if not ok then
    WowBuddyDevRuntimeLog = {
      savedAt = type(time) == "function" and time() or 0,
      snapshotError = tostring(err),
    }
  end
  return ok
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:SetScript("OnEvent", function()
  safeSnapshot()
end)

SLASH_WBDDIAG1 = "/wbddiag"
SlashCmdList.WBDDIAG = function()
  safeSnapshot()
  print("|cff33ff99[WowBuddyDev]|r 已刷新运行时诊断；游戏只在 /reload 或登出时写入磁盘，请 /reload 后再在助手中导出诊断。")
end

WowBuddyDev.SnapshotRuntimeDiagnostics = safeSnapshot
