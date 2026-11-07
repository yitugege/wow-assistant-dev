-- 只记录客户端报告的受保护操作；不尝试重试或绕过被拦截的调用。
local addonName = ...
local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_ACTION_BLOCKED")
frame:RegisterEvent("ADDON_ACTION_FORBIDDEN")
frame:SetScript("OnEvent", function(_, event, blamedAddon, functionName)
    if blamedAddon ~= addonName then return end
    if type(WowBuddyDevDiagnostics) ~= "table" then WowBuddyDevDiagnostics = {} end
    local records = WowBuddyDevDiagnostics
    records[#records + 1] = {
        event = event,
        addon = blamedAddon,
        operation = tostring(functionName or "unknown"),
        -- 这是事件到达时的调用上下文，不替代客户端报告的operation。
        directCastContext = WowBuddyDev and WowBuddyDev.DirectCast
            and WowBuddyDev.DirectCast.activeCall or nil,
        timestamp = type(time) == "function" and time() or 0,
        inCombat = type(InCombatLockdown) == "function" and InCombatLockdown() or false,
        stack = type(debugstack) == "function" and debugstack(2, 12, 8) or "",
    }
    while #records > 50 do table.remove(records, 1) end
    print("|cffff6666[WowBuddyDev]|r 客户端拦截：" .. tostring(functionName or "unknown") .. "（已记录诊断）")
end)
