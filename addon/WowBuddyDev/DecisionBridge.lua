-- ============================================================================
-- DecisionBridge.lua — 插件侧循环决策层（外部软件只负责发送按键）
--
-- 分工：
--   插件（本文件）：每帧做循环决策 —— 战斗判定 + 按 actionAvailSpellIDs
--   优先级 + IsSpellReady 动态识别已学/可用/未冷却技能 → 决策出"下一个技能"
--   → 映射成按键（ACTION_TO_KEY）→ 写进独立桥 DB1|key=...,spell=...
--   外部软件：只读 DB1 桥 → 把按键发出去 → 游戏施法。
--
-- 为什么要插件决策：插件有 IsSpellKnown/IsSpellUsable/冷却三重动态识别，
--   外部静态表永远跟不上角色实际学的技能；插件自己知道该放什么。
--
-- 桥格式：DB1|t=秒,combat=0/1,key=NUMPAD7,spell=2136,stage=attack|buff|idle
-- ============================================================================
local P = _G.WowBuddyDev
if not P then
    print("|cffff6666[DecisionBridge]|r Core.lua 未加载")
    return
end

local DB = { enabled = true, interval = 0.10, frame = nil, last = 0 }
P.DecisionBridge = DB

local function InCombat()
    return UnitAffectingCombat and UnitAffectingCombat("player") or false
end

-- 玩家自 buff 光环表: spellID → 该 presence 槽位的完整 spellIDs 列表
-- （来源 _pixelStripV2BySpec 里 unit=player + HELPFUL 的 presence 槽位）
local selfBuffBySpell = nil
local function BuildSelfBuffTable()
    selfBuffBySpell = {}
    local bySpec = P._pixelStripV2BySpec
    if not bySpec then return end
    for _, slots in pairs(bySpec) do
        for _, slot in ipairs(slots) do
            if slot.kind == "presence" and slot.unit == "player"
                and slot.filter == "HELPFUL" and slot.spellIDs then
                for _, sid in ipairs(slot.spellIDs) do
                    selfBuffBySpell[sid] = slot.spellIDs
                end
            end
        end
    end
end

-- 判玩家身上这批 ID 里有没有任意一个光环在场
-- true = 确定在（不该再上）; false/nil = 不在或查不出来（放行决策）
local function IsSelfBuffPresent(sid)
    if not selfBuffBySpell then BuildSelfBuffTable() end
    local ids = selfBuffBySpell[sid]
    if not ids then return false end
    if not (C_UnitAuras and C_UnitAuras.GetPlayerAuraBySpellID) then
        return false
    end
    for _, id in ipairs(ids) do
        local ok, aura = pcall(C_UnitAuras.GetPlayerAuraBySpellID, id)
        if ok and aura then
            return true
        end
    end
    return false
end

-- 该技能此刻要不要被决策层拦下:
--   自 buff 类（玩家 HELPFUL presence）—— 脱战一律拦（选中目标只该起手攻击，
--   不该顺手给自己上 buff）；战斗中只在光环已在场时拦（掉了的 buff 允许补）
local function DecisionBlocked(sid, combat)
    if not selfBuffBySpell then BuildSelfBuffTable() end
    if not selfBuffBySpell[sid] then return false end
    if not combat then return true end
    return IsSelfBuffPresent(sid)
end

-- 决策: 按 actionAvailSpellIDs 优先级找第一个就绪技能
-- 自 buff 走 DecisionBlocked 拦截 —— IsSpellReady 只看已学+可用+无冷却，
-- 荆棘术这类无冷却 buff 会永远"就绪"，不拦就会一选目标先上 buff
-- 而不是攻击、或者战斗中一遍遍重复上 buff
local function Decide()
    local cd = P.classData
    if not cd then return nil end
    local ids = cd.actionAvailSpellIDs
    if not ids or #ids == 0 then return nil end
    local combat = InCombat()
    for i = 1, #ids do
        local sid = ids[i]
        if P.IsSpellReady and P.IsSpellReady(sid) and not DecisionBlocked(sid, combat) then
            -- 映射按键
            local key = nil
            if cd.ACTION_TO_KEY then
                key = cd.ACTION_TO_KEY["spell_" .. sid]
            end
            if not key then
                -- 默认: start_attack 键
                key = cd.ACTION_TO_KEY and cd.ACTION_TO_KEY.start_attack
            end
            return sid, key
        end
    end
    return nil
end

local lastKey, lastT = nil, 0

local function Tick()
    if not DB.enabled then return end
    if not P.classData then
        _G.DECISION_BRIDGE = "DB1|t=" .. tostring(GetTime() or 0) .. ",combat=0,key=,spell=0,stage=no-classdata"
        return
    end
    local combat = InCombat() and 1 or 0
    local sid, key = Decide()
    if not sid then
        _G.DECISION_BRIDGE = "DB1|t=" .. tostring(GetTime() or 0) .. ",combat=" .. combat .. ",key=,spell=0,stage=idle"
        return
    end
    -- 节流: 同键 400ms
    local now = GetTime() or 0
    if key == lastKey and now - lastT < 0.4 then
        _G.DECISION_BRIDGE = "DB1|t=" .. tostring(now) .. ",combat=" .. combat .. ",key=" .. tostring(key or "") .. ",spell=" .. sid .. ",stage=throttle"
        return
    end
    lastKey, lastT = key, now
    -- 宏体判定 stage: 攻击/其他
    local stage = "other"
    local macro = P.classData.DEFAULT_MACROS and P.classData.DEFAULT_MACROS["spell_" .. sid] or ""
    if type(macro) == "string" and (macro:find("%[harm") or macro:find("startattack")) then
        stage = "attack"
    end
    _G.DECISION_BRIDGE = "DB1|t=" .. tostring(now) .. ",combat=" .. combat .. ",key=" .. tostring(key or "") .. ",spell=" .. sid .. ",stage=" .. stage
end

local function EnsureFrame()
    if DB.frame then return end
    DB.frame = CreateFrame("Frame")
    DB.frame:SetScript("OnUpdate", function(self, elapsed)
        DB.last = DB.last + elapsed
        if DB.last < DB.interval then return end
        DB.last = 0
        pcall(Tick)
    end)
end

EnsureFrame()
print("|cff00ff88[DecisionBridge]|r 插件决策层就绪 — 决策已写入 DB1 桥")