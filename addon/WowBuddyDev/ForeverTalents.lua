-- Native class identity and committed talent allocation are separate values.
local ADDON = _G.WowBuddyDev
local definitions = ADDON.ForeverTalentData
local cached, cachedAt, cachedSpec
local nodeGroups = {}
for specID, definition in pairs(definitions) do
  local index = {}
  for group, data in ipairs(definition.groups) do
    for _, nodeID in ipairs(data.nodes) do index[nodeID] = group end
  end
  nodeGroups[specID] = index
end

function ADDON.InvalidateForeverTalents()
  cached, cachedAt, cachedSpec = nil, nil, nil
end

function ADDON.GetForeverTalentState(specID)
  local now = GetTime()
  if cached and cachedSpec == specID and cachedAt and now - cachedAt < 1 then return cached end
  local definition = definitions[specID]
  local ok, result = pcall(function()
    local _, class = UnitClass("player")
    if not definition or class ~= definition.token then return { readable = false, reason = "class mismatch" } end
    if UnitLevel and UnitLevel("player") < 10 then return { readable = true, points = {0, 0, 0} } end
    if not (C_ClassTalents and C_ClassTalents.GetActiveConfigID and C_Traits
      and C_Traits.GetConfigInfo and C_Traits.GetTreeNodes and C_Traits.GetNodeInfo) then
      return { readable = false, reason = "missing trait API" }
    end
    local configID = C_ClassTalents.GetActiveConfigID()
    if not configID then return { readable = false, reason = "no active config" } end
    local info = C_Traits.GetConfigInfo(configID)
    local foundTree = false
    for _, treeID in ipairs(info and info.treeIDs or {}) do
      if treeID == definition.tree then foundTree = true end
    end
    if not foundTree then return { readable = false, reason = "class tree unavailable" } end
    local nodes = C_Traits.GetTreeNodes(definition.tree)
    if type(nodes) ~= "table" or #nodes == 0 then return { readable = false, reason = "nodes unavailable" } end
    local points, seen, knownNodes, unknownAllocated = {0, 0, 0}, {}, 0, 0
    for _, nodeID in ipairs(nodes) do
      if not seen[nodeID] then
        seen[nodeID] = true
        local node = C_Traits.GetNodeInfo(configID, nodeID)
        if type(node) ~= "table" then return { readable = false, reason = "node unavailable" } end
        local rank = node.activeRank
        if rank == nil then rank = node.currentRank end
        if type(rank) ~= "number" or rank < 0 or rank % 1 ~= 0 then
          return { readable = false, reason = "rank unavailable" }
        end
        local group = nodeGroups[specID][nodeID]
        if group then
          knownNodes = knownNodes + 1
          points[group] = points[group] + rank
        elseif rank > 0 then
          -- ★ 不再一票否决。
          --   以前这里 `return { readable = false, reason = "unmapped allocated node" }`，
          --   只要有一个「已加点但我们表里没登记」的节点，整次读取就判定失败 ⇒ main 拿不到
          --   ⇒ 专精识别不出来。而无限服上一定存在这类节点（每个职业天赋树根部的
          --   基础/通用节点，玩家 10 级一进游戏就自动点上了），所以表现就是
          --   **「天赋点了一点，但软件认不出专精」**。
          --   现在的处理：忽略这个节点（它的点数不计入任何系），只累计个数留作诊断。
          --   代价是极端情况下某系点数会被少算；但相比「整条识别链断掉」，这个代价小得多，
          --   而且天赋树本身按三系分区，未映射节点通常是三系共享的基础节点，对谁都不偏。
          unknownAllocated = unknownAllocated + 1
        end
      end
    end
    if knownNodes == 0 then return { readable = false, reason = "no mapped nodes" } end
    for _, count in ipairs(points) do
      if count > 100 then return { readable = false, reason = "invalid point total" } end
    end
    return { readable = true, points = points, configID = configID, treeID = definition.tree,
             unknownAllocated = unknownAllocated }
  end)
  if not ok then result = { readable = false, reason = "trait query unreadable" } end
  if result.readable then
    local p = result.points
    -- ★ 主系 = 点数最多的**唯一**一系。
    --
    -- 用户要的行为：天赋点了一点就能认出当前专精；三系都点时，用点数最多的作为主专精。
    --   · 点 1 点：p 形如 {0,1,0} ⇒ 主系唯一 ⇒ 直接识别（这就是「点一点就识别」的依据）。
    --   · 三系都点：任取最大值 ⇒ 主系 = 最大者。
    --   · 平票（如 5/5/0）：**必须挑一个**，不能拼成 "神圣/惩戒"。
    --     以前拼多系名，下游 GetForeverSpecRole 只能按系索引顺序取第一个命中的 ——
    --     等于「按系顺序」而不是「按点数」，与「用天赋最多的」这个要求相悖，
    --     而且拼出来的字符串会让职责/近战/远程判定随系顺序漂移。
    --     现在定死一个稳定优先级：三系点数相同时按 groups 的书写顺序取第一个
    --     （即 definition.groups 的声明顺序，可在数据里调整），行为可预期、可复现。
    local highest, best = 0, nil
    for index, count in ipairs(p) do
      if count > highest then highest, best = count, index end
    end
    if best and highest > 0 then
      result.main = definition.groups[best].name
      result.mainIndex = best
      result.mainPoints = highest
    else
      result.main = "未加点"
      result.mainIndex = 0
      result.mainPoints = 0
    end
    result.allocation = string.format("%d/%d/%d", p[1], p[2], p[3])
    result.packet = p[1] * 65536 + p[2] * 256 + p[3]
    result.display = result.main .. " (" .. result.allocation .. ")"
  else
    result.packet, result.display = 16777215, "天赋未读到"
  end
  cached, cachedAt, cachedSpec = result, now, specID
  ADDON.foreverTalentState = result
  if specID == 1485 then ADDON.hunterTalentState = result end
  if ADDON.DB then
    ADDON.DB.foreverTalentState = result
    if specID == 1485 then ADDON.DB.hunterTalentState = result end
    if ADDON.DB.currentSpecID == specID and definition then
      ADDON.DB.currentSpecName = definition.class .. " - " .. result.display
    end
  end
  return result
end

function ADDON.GetHunterTalentState() return ADDON.GetForeverTalentState(1485) end
function ADDON.GetHunterTalentPacket() return ADDON.GetHunterTalentState().packet end
function ADDON.GetForeverSpecDisplayName(specID, fallback)
  local definition = definitions[specID]
  if definition then return definition.class .. " - " .. ADDON.GetForeverTalentState(specID).display end
  return fallback
end

local watcher = CreateFrame("Frame")
for _, event in ipairs({"PLAYER_ENTERING_WORLD", "PLAYER_LEVEL_UP", "PLAYER_TALENT_UPDATE",
  "TRAIT_CONFIG_UPDATED", "TRAIT_CONFIG_LIST_UPDATED", "ACTIVE_TALENT_GROUP_CHANGED"}) do
  pcall(watcher.RegisterEvent, watcher, event)
end
watcher:SetScript("OnEvent", ADDON.InvalidateForeverTalents)
