-- ==========================================================================
-- 文件：BuildCompat.lua
-- 作用：客户端兼容自检 + 现场取证（重点面向 魔兽世界:无限 1.60.1 / wow_classic_beta）
-- 说明：
--   1) 本文件不改动任何既有逻辑，只做「读 + 报」：探测关键 API 是否存在、
--      当前客户端构建号 / Interface(TOC) 号、当前专精 ID 能不能在
--      P07483180.classes 里查到。
--   2) 登录进世界后自动把报告写进 SemrepDB.compatReport（SavedVariables），
--      所以即使不敲命令，外部也能从 WTF 存档里读到无限客户端的真实 Interface 号。
--   3) 手动命令：/pmb        打印报告
--              /pmb save   立刻把报告写进存档
-- 为什么需要它：
--   无限客户端走的是正式服框架，理论上 C_CurveUtil / EditMode / C_CooldownViewer /
--   C_Traits 这些都在；但「理论上在」不等于「实测在」。这些 API 一旦缺席，
--   血条层( PixelBar ) / 冷却导入( CDMImport ) / 天赋面板( PanelV2 ) 会静默失效。
--   本文件就是把这些静默失效变成一条能读到的报告。
-- ==========================================================================

local ADDON = _G.WowBuddyDev
if not ADDON then
    return
end

local WANTED_API = {
    -- 血条 / 百分比（PixelBar 的主力）
    "UnitHealthPercent",
    "UnitPowerPercent",
    "UnitHealth",
    "UnitPower",
    "UnitIsUnit",
    "UnitExists",
    "UnitGUID",
    "UnitClass",
    -- 曲线（血条渐变色的底座）
    "C_CurveUtil",
    "C_CurveUtil.CreateColorCurve",
    "C_CurveUtil.CreateCurve",
    -- 法术（冷却 / 可用性 / 名称）
    "C_Spell",
    "C_Spell.GetSpellInfo",
    "C_Spell.GetSpellName",
    "C_Spell.GetSpellTexture",
    "C_Spell.GetSpellCooldown",
    "C_Spell.GetSpellCharges",
    "C_Spell.IsSpellUsable",
    "GetSpellInfo",
    "GetSpellCooldown",
    "GetSpellCharges",
    "IsSpellKnown",
    "IsUsableSpell",
    -- 光环（DebugAuras / 触发判定）
    "C_UnitAuras",
    "C_UnitAuras.GetAuraDataByIndex",
    "C_UnitAuras.GetPlayerAuraBySpellID",
    "C_UnitAuras.GetAuraDataBySpellName",
    "AuraUtil",
    -- 物品 / 背包（消耗品、饰品）
    "C_Item",
    "C_Item.GetItemCount",
    "C_Item.GetItemInfo",
    "C_Item.GetItemIconByID",
    "GetInventoryItemID",
    "GetInventoryItemCount",
    "C_Container",
    "C_Container.GetContainerNumSlots",
    -- 编辑模式 / 冷却查看器（CDMImport 的两条导入通路）
    "EditMode",
    "C_EditMode",
    "C_EditMode.GetLayouts",
    "Enum.EditModeSystem.CooldownViewer",
    "C_CooldownViewer",
    "C_CooldownViewer.GetCooldownViewerCategorySet",
    "C_CooldownViewer.GetCooldownViewerCooldownInfo",
    -- 天赋树（PanelV2 读节点）
    "C_Traits",
    "C_Traits.GetNodeInfo",
    "C_Traits.GetTreeNodes",
    "C_ClassTalents",
    "C_ClassTalents.GetActiveConfigID",
    -- 专精
    "C_SpecializationInfo",
    "C_SpecializationInfo.GetSpecialization",
    "C_SpecializationInfo.GetSpecializationInfo",
    "GetSpecialization",
    "GetSpecializationInfo",
    "GetSpecializationInfoForClassID",
    "GetNumSpecializations",
    -- 计时 / 事件
    "C_Timer",
    "C_Timer.After",
    "C_Timer.NewTicker",
    -- 地图 / 其他
    "C_Map",
    "C_Map.GetBestMapForUnit",
    "C_SpellBook",
    "C_SpellBook.GetSpellBookSkillLineInfo",
    "C_SpellBook.GetSpellBookSlot",
    "Enum.SpellBookType",
    "Enum.SpellBookType.Player",
    "C_ActionBar",
    "C_ActionBar.GetActionCooldown",
    "C_AddOns",
    "C_AddOns.GetAddOnMetadata",
    "Enum",
    "Enum.PowerType",
    "Enum.UnitAuraSlot",
}

-- 功能：按点号路径在 _G 里逐级取值，用来判断某个 API 是否真的存在。
-- 入参：path，形如 "C_CurveUtil.CreateColorCurve"。
-- 出参：值 + 是否取到（布尔）。
-- 说明：全程用 type 判表，路径中间出现非表就直接判为不存在，不抛错。
local function resolvePath(path)
    local node = _G
    for seg in tostring(path):gmatch("[^.]+") do
        if type(node) ~= "table" then
            return nil, false
        end
        local nxt = node[seg]
        if nxt == nil then
            return nil, false
        end
        node = nxt
    end
    return node, true
end

-- 功能：安全调 GetBuildInfo，返回四个返回值。
-- 入参：无。
-- 出参：version, build, date, tocVersion（任一读不到就是 nil）。
-- 说明：tocVersion 就是客户端「期望的 Interface 号」——判 TOC 该写多少就看它。
local function readBuildInfo()
    if type(GetBuildInfo) ~= "function" then
        return nil, nil, nil, nil
    end
    local ok, v, b, d, t = pcall(GetBuildInfo)
    if not ok then
        return nil, nil, nil, nil
    end
    return v, b, d, t
end

-- 功能：把 P07483180.classes 已注册的专精 ID 拼成升序字符串。
-- 入参：无。
-- 出参：形如 "62, 63, 64" 的串；一个都没注册时返回 "-"。
local function listRegisteredSpecs()
    local ids = {}
    if type(ADDON.classes) == "table" then
        for k in pairs(ADDON.classes) do
            if type(k) == "number" then
                ids[#ids + 1] = k
            end
        end
    end
    table.sort(ids)
    if #ids == 0 then
        return "-", 0
    end
    local parts = {}
    for i = 1, #ids do
        parts[i] = tostring(ids[i])
    end
    return table.concat(parts, ","), #ids
end

-- 功能：读当前专精（下标 / 原始 specID / 名称 / 归一化后 specID）。
-- 入参：无。
-- 出参：specIndex, rawSpecID, specName, resolvedSpecID（读不到就是 nil）。
-- 说明：这里必须区分两个 specID，否则会误报：
--   rawSpecID      = 客户端直读值（走 C_SpecializationInfo，绕过兼容层）
--   resolvedSpecID = 插件实际使用的值（走全局 GetSpecializationInfo，即兼容层打过补丁的那个）
--   插件装载职业数据用的是 resolvedSpecID，所以 classDataMatched 必须以它为准。
--   早期版本直接读 C_* 来判 classDataMatched，结果在兼容层已生效的情况下
--   仍然报 false —— 因为 C_* 拿到的是无限服的原始占位 ID。
local function readCurrentSpec()
    local getSpec = (C_SpecializationInfo and C_SpecializationInfo.GetSpecialization) or GetSpecialization
    local getSpecRaw = (C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfo) or GetSpecializationInfo
    if type(getSpec) ~= "function" or type(getSpecRaw) ~= "function" then
        return nil, nil, nil, nil
    end
    local ok, specIndex = pcall(getSpec)
    if not ok or type(specIndex) ~= "number" or specIndex <= 0 then
        return nil, nil, nil, nil
    end
    local ok2, rawSpecID, specName = pcall(getSpecRaw, specIndex)
    if not ok2 then
        return specIndex, nil, nil, nil
    end

    -- 插件实际使用的值：全局函数（兼容层可能已把 specID 归一化过）
    local resolvedSpecID = rawSpecID
    local getSpecUsed = _G.GetSpecializationInfo
    if type(getSpecUsed) == "function" then
        local ok3, usedID = pcall(getSpecUsed, specIndex)
        if ok3 and usedID ~= nil then
            resolvedSpecID = usedID
        end
    end

    return specIndex, tonumber(rawSpecID), specName, tonumber(resolvedSpecID)
end

-- 功能：组装一份完整的兼容报告。
-- 入参：无。
-- 出参：report 表。
-- 说明：所有字段都可能为 nil —— 报告的意义就是「哪些读到了、哪些没读到」。
local function buildReport()
    local report = {}
    local version, build, date, tocVersion = readBuildInfo()
    report.buildVersion = version
    report.buildNumber = build
    report.buildDate = date
    report.tocVersion = tonumber(tocVersion)
    report.addonVersionCode = tonumber(ADDON.addonVersionCode) or 0
    report.projectID = tonumber(_G.WOW_PROJECT_ID)
    report.locale = type(GetLocale) == "function" and GetLocale() or nil
    report.timestamp = type(time) == "function" and time() or nil

    local _, classFile, classID = nil, nil, nil
    if type(UnitClass) == "function" then
        local ok, cName, cFile, cID = pcall(UnitClass, "player")
        if ok then
            report.className = cName
            classFile = cFile
            classID = tonumber(cID)
        end
    end
    report.classFileName = classFile
    report.classID = classID

    local specIndex, specID, specName, resolvedSpecID = readCurrentSpec()
    report.specIndex = specIndex
    report.specID = specID
    report.specName = specName
    report.resolvedSpecID = resolvedSpecID
    -- 判定用 resolvedSpecID（插件实际使用的值），不是客户端直读的原始值。
    report.classDataMatched = (resolvedSpecID ~= nil
        and type(ADDON.classes) == "table"
        and ADDON.classes[resolvedSpecID] ~= nil) and true or false

    local specList, specCount = listRegisteredSpecs()
    report.registeredSpecIDs = specList
    report.registeredSpecCount = specCount

    local present, missing = {}, {}
    for i = 1, #WANTED_API do
        local _, ok = resolvePath(WANTED_API[i])
        if ok then
            present[#present + 1] = WANTED_API[i]
        else
            missing[#missing + 1] = WANTED_API[i]
        end
    end
    report.presentAPIs = table.concat(present, ",")
    report.missingAPIs = table.concat(missing, ",")
    report.apiPresentCount = #present
    report.apiTotalCount = #WANTED_API

    -- TOC 号自洽性：和本插件 TOC 里写的 16001（无限）比对；不是 16001 时标出来。
    report.tocMatchesForever = (report.tocVersion == 16001) and true or false
    report.tocMatchesRetail = (report.tocVersion == 120100) and true or false

    -- 兼容层（ForeverCompat.lua）诊断：把「到底补了哪些缺失接口」记进存档。
    -- 这些字段一旦写进去，外部不用截图、不用看聊天框就能判断兼容层是否生效。
    if type(ADDON.DescribeForeverCompat) == "function" then
        local okP, patched, skipped, mapHits = pcall(ADDON.DescribeForeverCompat)
        if okP then
            report.foreverPatched = patched
            report.foreverSkipped = skipped
            report.foreverSpecMapHits = tonumber(mapHits) or 0
        end
    end
    if type(ADDON.DescribeObservedSpecs) == "function" then
        local okO, observed = pcall(ADDON.DescribeObservedSpecs)
        if okO then
            report.foreverObservedSpecs = observed
        end
    end
    report.foreverNameMapHits = tonumber(ADDON.foreverCompat
        and ADDON.foreverCompat.nameMapHits) or 0
    -- 原始 specID -> 归一化后 specID 的对照（兼容层诊断）
    local fc = ADDON.foreverCompat
    if type(fc) == "table" then
        report.foreverRawSpecID = tonumber(fc.lastRaw)
        report.foreverResolvedSpecID = tonumber(fc.lastResolved)
        report.foreverResolvedName = fc.lastName
        report.palaTree = fc.palaTree
        report.palaDebug = fc.palaDebug
    end

    return report
end

-- 功能：把报告写进 SemrepDB（SavedVariables），外部可直接从 WTF 读。
-- 入参：无。
-- 出参：report 表。
local function saveReport()
    local report = buildReport()
    if ADDON.DB then
        ADDON.DB.compatReport = report
    end
    return report
end

-- 功能：把报告打到聊天框。
-- 入参：无。
-- 出参：无。
local function printReport()
    local r = buildReport()
    if ADDON.DB then
        ADDON.DB.compatReport = r
    end
    local function line(fmt, ...)
        print("|cff33ff99[PMB]|r " .. string.format(fmt, ...))
    end
    line("插件版本码 = %s（读取端期望值见 pixel_reader/field_defs.py）", tostring(r.addonVersionCode))
    line("客户端版本 = %s  构建 = %s  日期 = %s", tostring(r.buildVersion), tostring(r.buildNumber), tostring(r.buildDate))
    line("客户端 Interface(TOC 期望号) = %s", tostring(r.tocVersion))
    line("WOW_PROJECT_ID = %s  locale = %s", tostring(r.projectID), tostring(r.locale))
    line("角色职业 = %s(%s)  classID = %s", tostring(r.className), tostring(r.classFileName), tostring(r.classID))
    line("当前专精 = 下标%s  specID=%s  名称=%s", tostring(r.specIndex), tostring(r.specID), tostring(r.specName))
    line("归一化后 specID = %s（插件按这个值装载职业数据）", tostring(r.resolvedSpecID))
    line("专精数据命中 = %s（WowBuddyDev.classes 已注册 %s 个：%s）",
        tostring(r.classDataMatched), tostring(r.registeredSpecCount), tostring(r.registeredSpecIDs))
    line("API 探测 = %s/%s 可用", tostring(r.apiPresentCount), tostring(r.apiTotalCount))
    if r.missingAPIs and r.missingAPIs ~= "" then
        line("|cffff5555缺失 API|r = %s", tostring(r.missingAPIs))
    else
        line("缺失 API = 无")
    end
    line("TOC 号自洽 = 无限?%s 正式服?%s", tostring(r.tocMatchesForever), tostring(r.tocMatchesRetail))
    if r.foreverPatched then
        line("兼容层已补接口 = %s", tostring(r.foreverPatched))
    end
    if r.foreverObservedSpecs and r.foreverObservedSpecs ~= "-" then
        line("专精观测(客户端ID=名称) = %s", tostring(r.foreverObservedSpecs))
    end
    line("专精归一化 = 原始%s -> 解析%s（名称%s）",
        tostring(r.foreverRawSpecID), tostring(r.foreverResolvedSpecID),
        tostring(r.foreverResolvedName))
    line("报告已写入 WowBuddyDevDB.compatReport")
end

-- 命令注册
SLASH_PMSBUILD1 = "/pmb"
SlashCmdList["PMSBUILD"] = function(msg)
    msg = tostring(msg or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
    if msg == "save" then
        saveReport()
        print("|cff33ff99[PMB]|r 报告已写入 WowBuddyDevDB.compatReport，可在 WTF 存档中读取。")
        return
    end
    printReport()
end

-- 进世界自动取证：专精信息只有进世界后才读得到。
local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:SetScript("OnEvent", function()
    saveReport()
end)
