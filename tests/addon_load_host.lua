-- 接在pixelbar_host.lua之后，仅模拟加载阶段；未声明API继续报错。
WowBuddyDev=nil; P07483180=nil
strmatch=string.match; gmatch=string.gmatch; strfind=string.find
strsub=string.sub; strlower=string.lower; strupper=string.upper
tinsert=table.insert; tremove=table.remove
sort=table.sort
-- 测试选择经典分支；各项目 ID 保持互异，避免 nil == nil 误入全部分支。
WOW_PROJECT_MAINLINE=1; WOW_PROJECT_CLASSIC=2; WOW_PROJECT_ID=2
WOW_PROJECT_BURNING_CRUSADE_CLASSIC=5; WOW_PROJECT_WRATH_CLASSIC=11
WOW_PROJECT_CATACLYSM_CLASSIC=14
function UnitClass() return '法师','MAGE',8 end
function UnitRace() return '人类','Human',1 end
-- 只记录定时器，不执行登录后或周期回调。
loadTickers={}
function C_Timer.NewTicker(interval, callback)
  local ticker={interval=interval,callback=callback}
  function ticker:Cancel() self.cancelled=true end
  table.insert(loadTickers,ticker)
  return ticker
end
function IsLoggedIn() return false end
function GetBuildInfo() return '1.60.1','60000','fixture',16001 end
BOOKTYPE_SPELL='spell'
C_SpellBook={}
function GetSpellBookItemName() return nil end
function GetSpellBookItemInfo() return nil end
function GetInventorySlotInfo(name)
  local slots={TRINKET0SLOT=13,TRINKET1SLOT=14,HANDSSLOT=10}
  assert(slots[string.upper(name)], '未声明装备槽：'..tostring(name))
  return slots[string.upper(name)]
end
bit={}
function bit.band(a,b)
  local result,power=0,1
  for i=1,32 do
    if a%2==1 and b%2==1 then result=result+power end
    a=math.floor(a/2);b=math.floor(b/2);power=power*2
  end
  return result
end
local methods=getmetatable(UIParent).__index
local createBaseFrame=CreateFrame
function CreateFrame(kind,name,parent,template)
  local frame=createBaseFrame(kind,name,parent)
  frame.name=name; frame.template=template
  return frame
end
function methods:GetName() return self.name end
function methods:GetNormalTexture() return nil end
function methods:GetHighlightTexture() return nil end
function methods:GetPushedTexture() return nil end
function methods:GetThumbTexture() return nil end
function methods:SetFontString(value) self.fontString=value end
function methods:GetFontString() return self.fontString end
function methods:SetWidth(value) self.width=value end
function methods:SetHeight(value) self.height=value end
function methods:SetChecked(value) self.checked=value end
function methods:GetChecked() return self.checked end
-- 布局占位值，不验证真实字体尺寸或画面。
function methods:GetStringWidth() return #(self.textValue or '')*6 end
function methods:RegisterEvent(event)
  self.events=self.events or {}; self.events[event]=true
end
for _,name in ipairs({'EnableMouseWheel','UnregisterAllEvents','UnregisterEvent','SetScrollChild',
  'EnableKeyboard','SetPropagateKeyboardInput','Enable','Disable','SetAutoFocus','SetMultiLine','SetMaxLetters','SetTextInsets',
  'SetNumeric','SetMinMaxValues','SetValueStep','SetObeyStepOnDrag','SetOrientation','SetThumbTexture'}) do
  methods[name]=function() end
end
function print() end
os=nil; io=nil; package=nil; require=nil
