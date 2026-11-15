-- 在世界地图记录玩家点击的路线坐标。路线编辑只使用普通控件。
local WowBuddyDev = (_G.WowBuddyDev and _G.WowBuddyDev.Namespace) and _G.WowBuddyDev.Namespace("ManualRoutes", {  }) or _G.WowBuddyDev -- @@注册表命名空间@@
local limit = 48
local function readable(value)
  return not issecretvalue or not issecretvalue(value)
end

local function coordinate(value)
  if not readable(value) or type(value) ~= "number" or not (value >= 0 and value <= 1) then return end
  return math.floor(value * 10000 + 0.5)
end

local function currentZone(map)
  local mapID = map:GetMapID()
  if not readable(mapID) or type(mapID) ~= "number" or mapID < 1 or mapID > 999999 then return end
  local info = C_Map.GetMapInfo(mapID)
  local zone = Enum and Enum.UIMapType and Enum.UIMapType.Zone or 3
  if type(info) == "table" and readable(info.mapType) and info.mapType == zone then return mapID end
end

local function draft(mapID, create)
  if not mapID or type(WowBuddyDevDB) ~= "table" then return end
  if type(WowBuddyDevDB.manualRouteDrafts) ~= "table" then
    if not create then return end
    WowBuddyDevDB.manualRouteDrafts = {}
  end
  local drafts = WowBuddyDevDB.manualRouteDrafts
  if type(drafts[mapID]) ~= "table" then
    if not create then return end
    drafts[mapID] = {}
  end
  return drafts[mapID]
end

local function createPanel(map)
  local selectingMap
  local supportsMapClick = type(map.AddCanvasClickHandler) == "function"
  local panel = CreateFrame("Frame", nil, map)
  panel:SetSize(426, 76)
  panel:SetPoint("BOTTOMLEFT", map, "BOTTOMLEFT", 16, 32)
  panel:SetFrameStrata("DIALOG")

  local status = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  status:SetPoint("TOPLEFT", 0, 0)
  local export = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
  export:SetSize(334, 22)
  export:SetPoint("BOTTOMLEFT", panel, "TOPLEFT", 8, 4)
  export:SetAutoFocus(false)
  export:SetMaxLetters(720)
  export:SetScript("OnEscapePressed", function(self) self:Hide() end)
  export:Hide()

  local function report(message)
    local points = draft(currentZone(map))
    status:SetText(("%s · %d 个路点"):format(message or "世界地图路线", points and #points or 0))
  end

  local function button(label, x, action, y)
    local control = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    control:SetSize(102, 22)
    control:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", x, y or 31)
    control:SetText(label)
    control:SetScript("OnClick", function()
      export:Hide()
      local wasSelecting = selectingMap ~= nil
      selectingMap = nil
      action(currentZone(map), wasSelecting)
    end)
  end

  local function copy(text)
    export:SetText(text)
    export:Show()
    export:SetFocus()
    export:HighlightText()
    report("按 Ctrl+C 后到桌面助手导入")
  end

  local function addPoint(mapID, rawX, rawY)
    local x, y = coordinate(rawX), coordinate(rawY)
    if x == nil or y == nil then return report("未读到有效坐标") end
    local points = draft(mapID, true)
    if not points then return report("路线设置尚未加载") end
    local point = ("%d,%d"):format(x, y)
    if points[#points] == point then return report("这个点已经加入") end
    if #points >= limit then return report("每张地图草稿最多 48 点") end
    points[#points + 1] = point
    report(("已加 (%.2f, %.2f)"):format(x / 100, y / 100))
  end

  if supportsMapClick then
    map:AddCanvasClickHandler(function(_, mouseButton, x, y)
      if not selectingMap or mouseButton ~= "LeftButton" then return false end
      local expected = selectingMap
      selectingMap = nil
      if currentZone(map) ~= expected then return false end
      addPoint(expected, x, y)
      return true
    end, 100)
  end

  button("加入路点", 0, function(mapID, wasSelecting)
    if not mapID then return report("请打开区域地图") end
    if supportsMapClick then
      if wasSelecting then return report("已取消标点") end
      selectingMap = mapID
      return report("请左键点击地图上的路点位置")
    end
    local ok, pin = pcall(C_Map.GetUserWaypoint)
    if not ok or not readable(pin) or type(pin) ~= "table" or not readable(pin.uiMapID)
        or pin.uiMapID ~= mapID or not readable(pin.position) or type(pin.position) ~= "table" then
      return report("请先在这张地图放置游戏标记")
    end
    addPoint(mapID, pin.position.x, pin.position.y)
  end)

  button("撤销路点", 106, function(mapID)
    local points = draft(mapID)
    if points and #points > 0 then table.remove(points) end
    report("已撤销最后一点")
  end)

  button("复制路线", 212, function(mapID)
    local points = draft(mapID)
    if not points or #points < 2 then return report("路线至少需要两个点") end
    local info = C_Map.GetMapInfo(mapID)
    local name = type(info) == "table" and info.name
    local prefix = "WBDROUTE1|" .. mapID .. "|"
    if readable(name) and type(name) == "string" and name ~= "" and #name <= 72
        and not name:find("[%c|]") then
      prefix = "WBDROUTE2|" .. mapID .. "|" .. name .. "|"
    end
    copy(prefix .. table.concat(points, "|"))
  end)

  button("复制打怪点", 0, function(mapID)
    local points = draft(mapID)
    if not points or #points == 0 then return report("请先加入一个路点") end
    copy("WBDPOINT1|" .. mapID .. "|" .. points[#points])
  end, 7)

  button("加入当前位置", 318, function(mapID)
    if not mapID then return report("请打开区域地图") end
    local mapOK, playerMap = pcall(C_Map.GetBestMapForUnit, "player")
    if not mapOK or not readable(playerMap) or playerMap ~= mapID then
      return report("请打开角色所在的区域地图")
    end
    local ok, x, y = pcall(function()
      local position = C_Map.GetPlayerMapPosition(mapID, "player")
      if readable(position) and position then return position:GetXY() end
    end)
    if not ok or not readable(x) or not readable(y) or (x == 0 and y == 0) then
      return report("未读到角色当前位置")
    end
    addPoint(mapID, x, y)
  end)

  local function resetSelection()
    selectingMap = nil
    export:Hide()
  end
  panel:SetScript("OnShow", function() resetSelection(); report() end)
  panel:SetScript("OnHide", resetSelection)
  if hooksecurefunc then
    hooksecurefunc(map, "OnMapChanged", function() resetSelection(); report() end)
  end
  report()
end

local function install()
  if not (WorldMapFrame and WorldMapFrame.GetMapID and C_Map and C_Map.GetMapInfo) then return false end
  createPanel(WorldMapFrame)
  return true
end

if not install() then
  local events = CreateFrame("Frame")
  events:RegisterEvent("ADDON_LOADED")
  events:SetScript("OnEvent", function(self, _, name)
    if name == "Blizzard_WorldMap" and install() then self:UnregisterEvent("ADDON_LOADED") end
  end)
end
