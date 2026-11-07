-- ==========================================================================
-- 文件：ForeverCompat.lua
-- 作用：「魔兽世界:无限」(wow_classic_beta 1.60.1) 兼容层
--
-- 为什么需要（2026-09-18 实机取证，证据见 WTF SavedVariables）：
--   _classic_beta_ 的 compatReport.missingAPIs 实测为：
--     GetSpellInfo, GetSpellCooldown, GetSpellCharges, IsUsableSpell,
--     EditMode, GetSpecialization, GetSpecializationInfo, Enum.UnitAuraSlot
--   而同一份报告里 specID=1486（BuildCompat 走 C_SpecializationInfo 读得到），
--   插件自己的 DB.currentSpecID=0（插件主体走全局 GetSpecialization 读不到）。
--   这两行并排就是缺口的直接实证。
--
--   插件主体裸调 GetSpecialization（145 处）/ GetSpecializationInfo（94 处），
--   写法一律 `GetSpecialization and GetSpecialization() or 0`，
--   于是静默退化成 specIndex=0 -> specID=0 -> classes[0] 查不到 ->
--   classData=nil -> 技能表/像素字段/动作标签全空，
--   表现为「插件装了但面板空白、总开关无效」，且不报任何错。
--
-- 本文件做两件事：
--   A) 把缺失的旧全局函数用等价的 C_* 接口补回来（只在缺失时才定义，
--      正式服 120100 上本文件等价于空操作）。
--   B) 把无限服的 specID 归一化成「插件 classes 表的键」。
--
-- ★ 关键设计（别乱改）：归一化只做在 GetSpecializationInfo 的【第 1 个返回值】上。
--   实测阅读全库，所有 specID 消费点都只读第 1 个返回值：
--     Core.lua:1153  P07483180.classes[specID]        <- 装载职业数据的总入口
--     Core.lua:2443  GetSpecializationInfo(idx) == 66 <- 防骑判定
--     Core.lua:2499  MELEE_SPEC_IDS[...]              <- 近战/远程判定
--     Core.lua:2572  DB.currentSpecID = specID        <- 像素条读数
--     AutoTarget.lua:87 / ChargeDisplay.lua:88 / PanelV2.lua:1251 /
--     TimelinePlanner.lua:874
--   所以在这一处映射，等于同时修好以上全部调用点。
--
-- 加载顺序：TOC 放在 Core.lua 之前（第 12 行）。为免依赖顺序，
--          本文件在 _G.P07483180 不存在时会自行创建它。
-- ==========================================================================

local ADDON = _G.WowBuddyDev
if type(ADDON) ~= "table" then
    ADDON = {}
    _G.WowBuddyDev = ADDON
end

local diag = {}
ADDON.foreverCompat = diag
diag.patched = {}
diag.skipped = {}
diag.specMapHits = 0
diag.nameMapHits = 0
diag.observed = {}   -- [客户端specID] = 最近一次看到的名称（取证用）

-- 功能：只在目标全局缺失时才定义它，并记录诊断信息。
-- 入参：name 全局名；factory 返回该函数的工厂（惰性求值，避免无谓构造）。
-- 出参：true=本次新定义，false=原本就存在（跳过）。
local function defineIfMissing(name, factory)
    if type(_G[name]) == "function" then
        diag.skipped[#diag.skipped + 1] = name
        return false
    end
    local ok, fn = pcall(factory)
    if not ok or type(fn) ~= "function" then
        return false
    end
    _G[name] = fn
    diag.patched[#diag.patched + 1] = name
    return true
end

-- ---------------------------------------------------------------------------
-- 1) 专精 ID 归一化
-- ---------------------------------------------------------------------------
-- 无限服每职业保留一个 ID；三系按实际天赋点数识别（见 ForeverTalents.lua）。
--
-- 已实测（2026-09-18，见 WTF SavedVariables/ZZBuildProbe.lua）：
--   无限共 9 个职业：allClassIDs = 1,2,3,4,5,7,8,9,11
--   （无 死亡骑士6 / 武僧10 / 恶魔猎手12 / 唤魔师13）
--
--   角色 4 级时（天赋与专精选择均未解锁）：
--     playerLevel              = 4
--     specSelectionEnabled     = false      <- 专精选择未解锁
--     canPlayerUseTalentSpecUI = false
--     hasTalentPoint           = false
--     GetSpecIDs()             = 空表（specIDCount = 0）
--     GetNumSpecializationsForClassID(c) = 1（全职业，占位值）
--     每职业只枚举到 1 条：1482..1491 且 name 字段 = 【职业名】
--       c1 战士=1491  c2 圣骑士=1486  c3 猎人=1485  c4 潜行者=1488
--       c5 牧师=1487  c7 萨满=1489    c8 法师=1482  c9 术士=1490
--       c11 德鲁伊=1484
--
--   10 级之后职业 ID 不变，不能用正式服 253/254/255 区分猎人的加点。
--
-- 两条救援路径，按优先级：
--   路径 1（权威）：SPEC_MAP[客户端specID] = 插件canonical specID
--                   ID 由实机与当前版本 ChrSpecialization 数据确认。
--   路径 2（兜底，现在就能用）：按【classID + 专精名】查表。
--     非无限客户端保留旧版专精名匹配，再叠加 classID 消歧
--     （「神圣」既是圣骑士65也是牧师257，「防护」既是战士73也是圣骑士66，
--       「恢复」既是萨满264也是德鲁伊105 —— 单靠名字必然撞车）。
--     名字对不上 / 仍是占位职业名时，路径 2 自动放弃，不做任何猜测。

local SPEC_MAP = {
    -- [无限客户端 specID] = 插件 canonical specID
    --
    -- ★ 2026-09-18 实机取证（10 级圣骑）推翻「满 10 级出现三系专精」的旧假设：
    --   无限每职业只有 1 个 specID（1482..1491，name=职业名），**没有三系专精切换**，
    --   三系靠天赋树加点区分。
    --
    -- ★ 2026-09-22 修正：本表必须是【恒等映射】。
    --   历史上这里曾把 7 个职业映射到一套「临时ID」（法师1500 / 牧师1501 /
    --   术士1502 / 盗贼1503 / 萨满1505 / 德鲁伊1506），圣骑则映射到正式服三系
    --   65/66/70。但 classes/<职业>/class_forever.lua 全部用【真实ID】注册
    --   （RegisterClass(1482..1491)），于是 Core.lua:1153 的
    --   `P07483180.classes[specID]` 永远查不到 → classData=nil →
    --   技能表/像素字段/动作标签全空，表现为「插件装了但面板空白、总开关无效」。
    --   只有猎人 1485 与战士 1491 因为原本就是恒等映射才正常工作 ——
    --   这正是「识别不到专精」只发生在其余 7 个职业上的原因。
    --   现在 9 个职业一律原样返回客户端 ID，与注册键、ForeverTalentData 键、
    --   读取端 fields.json/actions.json 的键保持同一套。
    [1482] = 1482, -- 法师
    [1484] = 1484, -- 德鲁伊
    [1485] = 1485, -- 猎人
    [1486] = 1486, -- 圣骑士（三系靠天赋树区分，见 GetForeverSpecRole）
    [1487] = 1487, -- 牧师
    [1488] = 1488, -- 潜行者
    [1489] = 1489, -- 萨满祭司
    [1490] = 1490, -- 术士
    [1491] = 1491, -- 战士
}

-- ---------------------------------------------------------------------------
-- 1b) 无限职责表：按「职业 specID + 天赋主系名」定职责
-- ---------------------------------------------------------------------------
-- 为什么不能继续用正式服那套「专精ID → 职责」：无限每职业只有 1 个 specID，
-- 同一个 1487（牧师）既可能是戒律/神圣（治疗）也可能是暗影（输出）。
-- 客户端的 GetSpecializationRole 只会返回该职业唯一专精的固定职责，
-- 无法反映玩家实际点了哪一系，所以职责必须从天赋主系推。
--
-- 系名一律取自 ForeverTalentData.lua 的 groups[].name（权威来源，勿另行拼写）；
-- 德鲁伊无限只有三组，守护德并在「野性战斗」里，故按近战处理。
local FOREVER_SPEC_ROLES = {
    [1482] = { ["奥术"] = "RANGED",    ["火焰"] = "RANGED", ["冰霜"] = "RANGED" },
    [1484] = { ["平衡"] = "RANGED",    ["野性战斗"] = "MELEE", ["恢复"] = "HEALER" },
    [1485] = { ["野兽控制"] = "RANGED", ["射击"] = "RANGED", ["生存"] = "RANGED" },
    [1486] = { ["神圣"] = "HEALER",    ["防护"] = "TANK",   ["惩戒"] = "MELEE" },
    [1487] = { ["戒律"] = "HEALER",    ["神圣"] = "HEALER", ["暗影"] = "RANGED" },
    [1488] = { ["刺杀"] = "MELEE",     ["战斗"] = "MELEE",  ["敏锐"] = "MELEE" },
    [1489] = { ["元素"] = "RANGED",    ["增强"] = "MELEE",  ["恢复"] = "HEALER" },
    [1490] = { ["痛苦"] = "RANGED",    ["恶魔学识"] = "RANGED", ["毁灭"] = "RANGED" },
    [1491] = { ["武器"] = "MELEE",     ["狂怒"] = "MELEE",  ["防护"] = "TANK" },
}

ADDON.FOREVER_SPEC_ROLES = FOREVER_SPEC_ROLES

-- 功能：取当前角色的无限职责。
-- 出参："HEALER" / "TANK" / "MELEE" / "RANGED"；读不到天赋或不在表里返回 nil。
-- 说明：主系由 ForeverTalents 的天赋点数算出，**点数最多者为唯一主系**，所以
--       这里正常只会拿到单个系名（「点一点就识别」，三系都点时取最多的那系）。
--       仍保留按 "/" 拆分的循环：一是不必让这里依赖上游的「已唯一化」这个假设
--       （两者解耦，改一边不会静默弄坏另一边），二是万一将来上游又拼多系名，
--       这里也能取到第一个能命中职责表的，而不是直接返回 nil 退化到保守分支。
function ADDON.GetForeverSpecRole()
    local specIndex = (_G.GetSpecialization and _G.GetSpecialization()) or 0
    if type(specIndex) ~= "number" or specIndex <= 0 or not _G.GetSpecializationInfo then
        return nil
    end
    local ok, specID = pcall(_G.GetSpecializationInfo, specIndex)
    if not ok or type(specID) ~= "number" then
        return nil
    end
    local roles = FOREVER_SPEC_ROLES[specID]
    if not roles then
        return nil
    end
    if type(ADDON.GetForeverTalentState) ~= "function" then
        return nil
    end
    local okState, state = pcall(ADDON.GetForeverTalentState, specID)
    local main = okState and type(state) == "table" and state.main or nil
    if type(main) ~= "string" or main == "" then
        return nil
    end
    -- ★ 「未加点」（三系都是 0）必须当成「读不到」返回 nil，不能去查职责表
    --   （表里没有这个键，gmatch 会一个都不命中然后返回 nil —— 结果一样，但
    --    这里显式挡掉更清楚，也避免以后往表里加名字时误命中）。
    if main == "未加点" then
        return nil
    end
    for name in string.gmatch(main, "[^/]+") do
        local role = roles[name]
        if role then
            diag.lastRole = role
            return role
        end
    end
    return nil
end

-- 功能：当前是不是「圣骑士 + 天赋主修防护」。
-- 出参：true/false。
-- 说明：替代旧的 `GetSpecializationInfo(specIndex) == 66`。无限圣骑恒为 1486，
--       正式服三系 ID 在这里永远不成立，只能按天赋主系判。
function ADDON.IsForeverProtectionPaladin()
    local specIndex = (_G.GetSpecialization and _G.GetSpecialization()) or 0
    if type(specIndex) ~= "number" or specIndex <= 0 or not _G.GetSpecializationInfo then
        return false
    end
    local ok, specID = pcall(_G.GetSpecializationInfo, specIndex)
    if not ok or specID ~= 1486 then
        return false
    end
    return ADDON.GetForeverSpecRole() == "TANK"
end

-- 正式服 zhCN 专精名 -> canonical specID，按 classID 分组消歧。
local SPEC_BY_CLASS_NAME = {
    [1]  = { ["武器"] = 71,  ["狂怒"] = 72,  ["防护"] = 73 },
    [2]  = { ["神圣"] = 65,  ["防护"] = 66,  ["惩戒"] = 70 },
    [3]  = { ["野兽控制"] = 253, ["射击"] = 254, ["生存"] = 255 },
    [4]  = { ["奇袭"] = 259, ["狂徒"] = 260, ["敏锐"] = 261 },
    [5]  = { ["戒律"] = 256, ["神圣"] = 257, ["暗影"] = 258 },
    [7]  = { ["元素"] = 262, ["增强"] = 263, ["恢复"] = 264 },
    [8]  = { ["奥术"] = 62,  ["火焰"] = 63,  ["冰霜"] = 64 },
    [9]  = { ["痛苦"] = 265, ["恶魔学识"] = 266, ["毁灭"] = 267 },
    [11] = { ["平衡"] = 102, ["野性"] = 103, ["守护"] = 104, ["恢复"] = 105 },
}

ADDON.FOREVER_SPEC_MAP = SPEC_MAP

-- 功能：取当前角色的 classID（拿不到返回 nil）。
-- 说明：路径 2 用它消歧，读不到就退回「不做名字映射」。
local function playerClassID()
    if type(UnitClass) ~= "function" then
        return nil
    end
    local ok, _, _, classID = pcall(UnitClass, "player")
    if ok and classID ~= nil then
        return tonumber(classID)
    end
    return nil
end

-- 功能：读无限圣骑的天赋树，判断当前主修哪一系（神圣/防护/惩戒）。
-- 依据：C_Traits.GetNodeInfo 的 currentRank（已点等级）+ posX（坐标分三系：
--       x<5000 神圣 / 5000≤x<8000 防护 / x≥8000 惩戒，实测探针取证）。
-- 出参：主系对应的 canonical specID（65 神圣 / 66 防护 / 70 惩戒）；读不到返回 nil。
-- 说明：无限每职业只有 1 个 specID（无三系切换），三系靠天赋树加点区分，
--       所以必须动态读天赋树判断主系，不能写死。
function ADDON.DetectPaladinMainTree()
    local dbg = {}
    if type(_G.C_ClassTalents) ~= "table" or type(_G.C_Traits) ~= "table" then
        diag.palaDebug = "no C_ClassTalents/C_Traits"
        return nil
    end
    local getActiveConfig = _G.C_ClassTalents.GetActiveConfigID
    local getConfigInfo = _G.C_Traits.GetConfigInfo
    local getNodes = _G.C_Traits.GetTreeNodes
    local getNodeInfo = _G.C_Traits.GetNodeInfo
    if not (getActiveConfig and getConfigInfo and getNodes and getNodeInfo) then
        diag.palaDebug = "missing api"
        return nil
    end
    local okC, configID = pcall(getActiveConfig)
    dbg[#dbg + 1] = "cfg=" .. tostring(okC) .. ":" .. tostring(configID)
    if not okC or not configID then
        diag.palaDebug = table.concat(dbg, " ")
        return nil
    end
    local treeID = nil
    local okCi, ci = pcall(getConfigInfo, configID)
    if okCi and type(ci) == "table" and type(ci.treeIDs) == "table" and #ci.treeIDs > 0 then
        treeID = ci.treeIDs[1]
    end
    dbg[#dbg + 1] = "tree=" .. tostring(treeID)
    if not treeID then
        diag.palaDebug = table.concat(dbg, " ")
        return nil
    end
    local okN, nodes = pcall(getNodes, treeID)
    dbg[#dbg + 1] = "nodes=" .. tostring(okN) .. ":" .. (type(nodes) == "table" and #nodes or "nil")
    if not okN or type(nodes) ~= "table" then
        diag.palaDebug = table.concat(dbg, " ")
        return nil
    end
    local holy, prot, ret = 0, 0, 0
    for i = 1, #nodes do
        local okNi, ni = pcall(getNodeInfo, configID, nodes[i])
        if okNi and type(ni) == "table" then
            local rank = tonumber(ni.currentRank) or 0
            if rank > 0 then
                local x = tonumber(ni.posX) or 0
                if x < 5000 then
                    holy = holy + rank
                elseif x < 8000 then
                    prot = prot + rank
                else
                    ret = ret + rank
                end
            end
        end
    end
    diag.palaTree = string.format("holy=%d prot=%d ret=%d", holy, prot, ret)
    diag.palaDebug = table.concat(dbg, " ") .. " | " .. diag.palaTree
    -- 主系 = 已点总点数最多的系（平票时 防护 > 惩戒 > 神圣）
    if prot > 0 and prot >= holy and prot >= ret then
        return 66
    elseif ret > 0 and ret >= holy and ret >= prot then
        return 70
    elseif holy > 0 then
        return 65
    end
    return nil
end

-- 功能：把当前客户端的 specID 解析成「插件 classes 表里的键」。
-- 入参：specID 客户端给的专精 ID；specName 客户端给的专精名（可空）。
-- 出参：可用的 specID（映射命中返回映射值，否则原样返回）。
-- 说明：宁可不匹配，也不要错匹配 —— 两条路径都不命中时原样返回，
--       让上层走「查不到职业数据」的既有安全分支，而不是灌错数据。
function ADDON.ResolveSpecID(specID, specName)
    -- 路径 1：静态 ID 映射。无限 9 职业一律恒等映射（见 SPEC_MAP 注释）：
    -- 客户端报的 1482..1491 就是 classes 表的注册键，不需要改写。
    --
    -- ★ 这里原先有「路径 0：圣骑 1486 → DetectPaladinMainTree() → 65/66/70」，
    --   已删除。无限没有任何模块注册 65/66/70（那三个正式服专精的契约在
    --   classes_retail_only/，TOC 不加载），映射过去等于查不到职业数据。
    --   圣骑三系的差异改由 GetForeverSpecRole()（职责）与
    --   ForeverTalents 的天赋包（数值）表达，specID 恒为 1486。
    --   DetectPaladinMainTree() 仍保留：它读的是天赋树坐标分档，
    --   /pmstest 与取证还会用它交叉验证天赋主系。
    local mapped = SPEC_MAP[specID]
    if mapped then
        diag.specMapHits = diag.specMapHits + 1
        diag.lastRaw = specID
        diag.lastName = specName
        diag.lastResolved = mapped
        return mapped
    end

    -- 记录观测，方便外部取证时确认「无限到底报的什么 ID/名字」
    if specID ~= nil then
        diag.observed[specID] = tostring(specName)
        diag.lastRaw = specID
        diag.lastName = specName
    end

    -- 路径 2：classID + 专精名 兜底（仅对**正式服**客户端有意义：那边一个职业
    -- 有三条专精，名字能区分。无限上报的是职业名，SPEC_BY_CLASS_NAME 里查不到，
    -- 自动放弃、原样返回，不做任何猜测。）
    --
    -- 注：无限 9 个 specID 现已全部收进 SPEC_MAP，路径 1 必然命中并提前返回，
    --     所以这段在无限上**不可达**。保留它只为正式服客户端（120100）共用本文件。
    local resolved = specID
    if type(specName) == "string" and specName ~= "" then
        local classID = playerClassID()
        local byName = classID and SPEC_BY_CLASS_NAME[classID]
        local hit = byName and byName[specName]
        if hit then
            diag.nameMapHits = diag.nameMapHits + 1
            resolved = hit
        end
    end
    diag.lastResolved = resolved
    return resolved
end

-- ---------------------------------------------------------------------------
-- 2) 专精接口垫片
-- ---------------------------------------------------------------------------
-- 无限上 C_SpecializationInfo 家族齐全（实测 hasSpecializationInfo=true），
-- 只是不再把同名旧全局导出。这里做转发，不改语义。
-- ★ 实测该表【没有】 GetSpecializationRole / GetSpecializationInfoForSpecID，
--   这两个不能直接转发，改为从 GetSpecializationInfo 派生。

-- GetSpecialization() -> specIndex（配置下标，非 specID）
defineIfMissing("GetSpecialization", function()
    local impl = C_SpecializationInfo and C_SpecializationInfo.GetSpecialization
    if type(impl) ~= "function" then
        return nil
    end
    return function()
        local ok, specIndex = pcall(impl)
        if ok and type(specIndex) == "number" then
            return specIndex
        end
        return 0
    end
end)

-- GetSpecializationInfo(specIndex) -> specID, name, description, icon, role, ...
-- ★ 本兼容层的核心：第 1 个返回值做归一化，一行修好全部 specID 消费点。
defineIfMissing("GetSpecializationInfo", function()
    local impl = C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfo
    if type(impl) ~= "function" then
        return nil
    end
    return function(specIndex)
        if type(specIndex) ~= "number" or specIndex <= 0 then
            return nil
        end
        local ok, specID, name, desc, icon, role = pcall(impl, specIndex)
        if not ok then
            return nil
        end
        return ADDON.ResolveSpecID(specID, name), name, desc, icon, role
    end
end)

-- GetSpecializationRole(specIndex) -> "HEALER"/"DAMAGER"/"TANK"
-- C_SpecializationInfo 里【没有】这个函数，从 GetSpecializationInfo 第 5 个返回值派生。
-- 缺它会让 IsHealingSpec / IsRangedDamageSpec 永远返回 false，自动选目标走错分支。
defineIfMissing("GetSpecializationRole", function()
    return function(specIndex)
        if type(specIndex) ~= "number" or specIndex <= 0 then
            return nil
        end
        local getInfo = _G.GetSpecializationInfo
        if type(getInfo) ~= "function" then
            return nil
        end
        local ok, _, _, _, _, role = pcall(getInfo, specIndex)
        if ok then
            return role
        end
        return nil
    end
end)

-- 其余同族接口：客户端已导出全局的直接跳过（实测 GetNumSpecializations /
-- GetSpecializationInfoForClassID 在无限上【本来就有】）。
defineIfMissing("GetSpecializationInfoForSpecID", function()
    return function(specID)
        if type(specID) ~= "number" then
            return nil
        end
        local getInfo = _G.GetSpecializationInfo
        if type(getInfo) ~= "function" then
            return nil
        end
        -- 先问客户端总数，问不到就按 8 个下标兜底扫
        local count = 0
        local getNum = _G.GetNumSpecializations
        if type(getNum) == "function" then
            local okNum, n = pcall(getNum)
            if okNum and type(n) == "number" then
                count = n
            end
        end
        if count <= 0 then
            count = 8
        end
        for idx = 1, count do
            local ok, id, name, desc, icon, role = pcall(getInfo, idx)
            if ok and id == specID then
                return name, desc, icon, role
            end
        end
        return nil
    end
end)

-- ---------------------------------------------------------------------------
-- 3) 法术接口垫片
-- ---------------------------------------------------------------------------
-- 实测无限上 GetSpellInfo / GetSpellCooldown / GetSpellCharges / IsUsableSpell
-- 四个旧全局全缺。插件多数地方已改用 C_Spell，但 DebugAuras.lua:422 仍裸调
-- GetSpellInfo（表现为技能名一律「未知」）。这里补上，是纯收益。
defineIfMissing("GetSpellInfo", function()
    if not C_Spell or type(C_Spell.GetSpellInfo) ~= "function" then
        return nil
    end
    return function(spellID)
        -- 旧接口也接受技能名；DirectCast的宏解析按名称查询，不能仅放行数字。
        if type(spellID) ~= "number" and type(spellID) ~= "string" then
            return nil
        end
        local ok, info = pcall(C_Spell.GetSpellInfo, spellID)
        if not ok or type(info) ~= "table" then
            return nil
        end
        return info.name, nil, info.iconID, info.castTime,
               info.minRange, info.maxRange, info.spellID, info.originalIconID
    end
end)

defineIfMissing("GetSpellCooldown", function()
    if not C_Spell or type(C_Spell.GetSpellCooldown) ~= "function" then
        return nil
    end
    return function(spellID)
        local ok, info = pcall(C_Spell.GetSpellCooldown, spellID)
        if not ok or type(info) ~= "table" then
            return nil
        end
        return info.startTime, info.duration, info.isEnabled, info.modRate
    end
end)

defineIfMissing("GetSpellCharges", function()
    if not C_Spell or type(C_Spell.GetSpellCharges) ~= "function" then
        return nil
    end
    return function(spellID)
        local ok, info = pcall(C_Spell.GetSpellCharges, spellID)
        if not ok or type(info) ~= "table" then
            return nil
        end
        return info.currentCharges, info.maxCharges, info.cooldownStartTime,
               info.cooldownDuration, info.chargeModRate
    end
end)

defineIfMissing("IsUsableSpell", function()
    if not C_Spell or type(C_Spell.IsSpellUsable) ~= "function" then
        return nil
    end
    return function(spellID)
        local ok, usable, noMana = pcall(C_Spell.IsSpellUsable, spellID)
        if not ok then
            return false
        end
        return usable, noMana
    end
end)

-- 注：EditMode 全局缺失【不补】。实测 Enum.EditModeSystem.CooldownViewer 与
-- C_EditMode.GetLayouts/SaveLayouts 都在，CDMImport.lua:442 的
-- isEditModeApiAvailable() 判的就是这三样；无脑补一个 EditMode 全局反而可能
-- 让别的库误判 API 可用。

-- ---------------------------------------------------------------------------
-- 4) 诊断输出（供 /pmb 与外部取证使用）
-- ---------------------------------------------------------------------------
function ADDON.DescribeForeverCompat()
    local patched = table.concat(diag.patched, ",")
    local skipped = table.concat(diag.skipped, ",")
    if patched == "" then
        patched = "-"
    end
    if skipped == "" then
        skipped = "-"
    end
    return patched, skipped, diag.specMapHits
end

-- 功能：把观测到的 (客户端specID -> 名称) 拼成一行，供存档取证。
-- 出参：形如 "1486=圣骑士,1491=战士" 的串；没有观测时返回 "-"。
function ADDON.DescribeObservedSpecs()
    local keys = {}
    for k in pairs(diag.observed) do
        if type(k) == "number" then
            keys[#keys + 1] = k
        end
    end
    table.sort(keys)
    if #keys == 0 then
        return "-"
    end
    local parts = {}
    for i = 1, #keys do
        parts[i] = tostring(keys[i]) .. "=" .. tostring(diag.observed[keys[i]])
    end
    return table.concat(parts, ",")
end

-- 功能：报告当前专精解析结果（进世界 / 切专精后各报一次）。
-- 说明：专精数据拿不到时必须说清楚原因，否则用户看到的是「插件没反应」。
local function reportSpecResolution()
    local getSpec = _G.GetSpecialization
    local getInfo = _G.GetSpecializationInfo
    local specIndex = (type(getSpec) == "function") and getSpec() or 0
    local specID, specName
    if type(getInfo) == "function" and type(specIndex) == "number" and specIndex > 0 then
        specID, specName = getInfo(specIndex)
    end
    if ADDON.GetForeverSpecDisplayName then
        specName = ADDON.GetForeverSpecDisplayName(specID, specName)
    end
    local classData = (specID ~= nil) and ADDON.classes and ADDON.classes[specID] or nil
    if classData then
        -- 匹配成功静默（用户要求不刷登录播报）
    else
        print(string.format("|cff33ff99[PMB-Forever]|r |cffffcc00专精未匹配|r: 下标%s specID=%s 名称=%s",
            tostring(specIndex), tostring(specID), tostring(specName)))
        print("|cff33ff99[PMB-Forever]|r 当前职业 ID 尚未匹配循环数据；职业宏独立注册，可用 /pmbind 检查按键。")
    end
end

-- 启动补接口改为静默（用户要求不刷登录播报）；diag.patched 仍可经 /mklerr 等取证路径排查。
if #diag.patched > 0 then
    -- 静默：仅保留收集，不打印
end

-- 专精相关事件后延迟报告：职业文件是在登录后才注册的，
-- 所以要等 classes 表填完（延迟 3 秒）再判定，否则必然误报「未匹配」。
local watcher = CreateFrame("Frame")
watcher:RegisterEvent("PLAYER_ENTERING_WORLD")
watcher:RegisterEvent("ACTIVE_TALENT_GROUP_CHANGED")
watcher:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_ENTERING_WORLD" then
        self:UnregisterEvent("PLAYER_ENTERING_WORLD")
    end
    if type(C_Timer) == "table" and type(C_Timer.After) == "function" then
        C_Timer.After(3, reportSpecResolution)
    else
        reportSpecResolution()
    end
end)
