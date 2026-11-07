-- 手动取证工具：安全按钮只点击本插件记录按钮，不施法、不绑定按键。
local addonName = ...
local probe, marker
local sequence = 0
local function record(phase, button, down)
  local report = WowBuddyDevHookProbe
  if type(report) ~= "table" then return end
  local events = report.events
  events[#events+1] = {sequence=sequence, phase=phase, button=tostring(button),
    down=down==true, time=GetTime(), inCombat=InCombatLockdown()}
  while #events>60 do table.remove(events,1) end
end

local function report()
  local data = WowBuddyDevHookProbe
  if type(data) ~= "table" or type(data.events) ~= "table" then
    print("[WowBuddyDev] 尚无点击顺序记录。输入 /wbdhookprobe 显示测试按钮。")
    return
  end
  print("[WowBuddyDev] 点击顺序（只记录，不判断施法是否可用）：")
  for _,event in ipairs(data.events) do
    print(tostring(event.sequence).." "..event.phase.." "..event.button.." down="..tostring(event.down))
  end
  local sawDefault=false
  for _,event in ipairs(data.events) do if event.phase=="default-marker" then sawDefault=true end end
  if not sawDefault then print("[WowBuddyDev] 未观察到默认记录动作，本次不能判断默认动作与挂钩的顺序。") end
end

local function show()
  if InCombatLockdown() then print("[WowBuddyDev] 请脱战后打开点击顺序测试。") return end
  if not probe then
    marker = CreateFrame("Button", "WowBuddyDevHookOrderMarker", UIParent)
    marker:SetSize(1,1)
    marker:SetPoint("TOPLEFT",UIParent,"BOTTOMRIGHT",1,-1)
    marker:SetScript("OnClick",function(_,button,down) record("default-marker",button,down) end)
    probe = CreateFrame("Button", "WowBuddyDevHookOrderProbe", UIParent, "SecureActionButtonTemplate")
    probe:SetSize(320,64)
    probe:SetPoint("CENTER",UIParent,"CENTER",0,0)
    probe:SetNormalTexture("Interface\\Buttons\\UI-Panel-Button-Up")
    local label=probe:CreateFontString(nil,"OVERLAY","GameFontNormal")
    label:SetPoint("CENTER",probe,"CENTER",0,0)
    label:SetText("点击记录顺序（不施法）\n/wbdhookprobe hide 关闭")
    probe:RegisterForClicks("AnyDown","AnyUp")
    probe:SetAttribute("type","click")
    probe:SetAttribute("clickbutton",marker)
    probe:SetScript("PreClick",function(_,button,down)
      sequence=sequence+1;record("pre",button,down)
    end)
    -- 不覆盖模板默认OnClick，不修改点击中的安全属性。
    probe:HookScript("OnClick",function(_,button,down) record("hook",button,down) end)
    probe:SetScript("PostClick",function(_,button,down)
      record("post",button,down)
      print("[WowBuddyDev] 已记录。输入 /wbdhookprobe report 查看；退出或重载UI后保存到WTF。")
    end)
  end
  local version,build,_,interface = GetBuildInfo()
  WowBuddyDevHookProbe={addon=addonName,version=version,build=build,interface=interface,
    events={},scope="own-button-click-order; not-game-casting"}
  sequence=0
  marker:Show();probe:Show()
  print("[WowBuddyDev] 请手动点击中央测试按钮。每次重新打开会开始新记录。")
end

SLASH_WBDHOOKPROBE1 = "/wbdhookprobe"
SlashCmdList.WBDHOOKPROBE = function(message)
  message=string.lower(message or ""):match("^%s*(.-)%s*$")
  if message=="report" then report()
  elseif message=="hide" then
    if InCombatLockdown() then print("[WowBuddyDev] 请脱战后关闭测试按钮。") return end
    if probe then probe:Hide();marker:Hide() end
  elseif message=="" then show()
  else print("用法：/wbdhookprobe [report|hide]") end
end
