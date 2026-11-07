-- 只供完整PixelBar离线测试：显式UI方法替身，不提供隐式游戏API兜底。
frames={}; textures={}; now=10; combat=false; targetAlive=true; typing=false
local methods={}
function object(kind,parent)
  local obj=setmetatable({kind=kind,parent=parent,scripts={},shown=true,width=100,height=100},{__index=methods})
  return obj
end
function CreateFrame(kind,name,parent)
  local obj=object(kind,parent);frames[#frames+1]=obj
  if name then _G[name]=obj end
  return obj
end
function methods:CreateTexture() local obj=object('Texture',self);textures[#textures+1]=obj;return obj end
function methods:CreateFontString() return object('FontString',self) end
function methods:SetScript(event,fn) self.scripts[event]=fn end
function methods:HookScript(event,fn) self.scripts[event]=fn end
function methods:SetSize(w,h) self.width=w;self.height=h end
function methods:GetWidth() return self.width end
function methods:GetHeight() return self.height end
function methods:GetEffectiveScale() return 1 end
function methods:GetScale() return 1 end
function methods:GetFrameLevel() return 1 end
function methods:SetPoint(...) self.point={...} end
function methods:SetColorTexture(r,g,b,a) self.color={r,g,b,a};self.writes=(self.writes or 0)+1 end
function methods:Show() self.shown=true end
function methods:Hide() self.shown=false end
function methods:SetShown(value) self.shown=value end
function methods:IsShown() return self.shown end
function methods:SetText(value) self.textValue=value end
function methods:GetText() return self.textValue end
function methods:SetParent(value) self.parent=value end
function methods:GetParent() return self.parent end
for _,name in ipairs({'ClearAllPoints','SetFrameStrata','SetFrameLevel','SetDrawLayer','SetBlendMode',
 'SetAlpha','SetFont','SetJustifyH','SetJustifyV','SetTextColor','RegisterEvent','SetTexture',
 'SetTexCoord','SetAllPoints','EnableMouse','SetMovable','RegisterForDrag','RegisterForClicks',
 'SetClampedToScreen','SetNormalTexture','SetHighlightTexture','SetPushedTexture','SetBackdrop',
 'SetBackdropColor','SetBackdropBorderColor','SetShadowOffset','SetShadowColor'}) do methods[name]=function() end end
UIParent=object('UIParent');Minimap=object('Minimap')
SlashCmdList={};C_Timer={After=function() end}
StaticPopupDialogs={}
GameFontNormal={GetFont=function() return 'fixture',12,'' end}
function GetScreenWidth() return 1920 end
function GetScreenHeight() return 1080 end
function CreateColor(r,g,b,a) return {GetRGB=function() return r,g,b end,GetRGBA=function() return r,g,b,a or 1 end} end
function wipe(t) for k in pairs(t) do t[k]=nil end end
function GetLocale() return 'zhCN' end
function PlaySoundFile(path,channel) lastSound={path,channel} end
function GetTime() return now end
function UnitDistanceSquared() return 100,true end
function UnitCastingInfo() return nil end
function UnitChannelInfo() return nil end
function UnitAffectingCombat() return combat end
function InCombatLockdown() return combat end
function UnitExists(unit) return unit=='player' or unit=='target' end
function UnitIsDeadOrGhost(unit) return unit=='target' and not targetAlive end
function UnitCanAttack(_,unit) return unit=='target' end
function UnitCanAssist(_,unit) return unit=='player' end
function GetCurrentKeyBoardFocus() if typing then return {} end end
function IsInRaid() return false end
function IsInInstance() return false,'none' end
C_NamePlate={GetNamePlates=function() return {} end}
function GetSpecialization() return 1 end
function GetSpecializationInfo() return 1482 end
WowBuddyDev={DB={masterSwitch=true,currentSpecID=1482},classData={},pixelData={},testData={},
 testSpells={},consumableItems={},fontFile='fixture'}
function WowBuddyDev.L(s) return s end
function WowBuddyDev.SafeNumber(n) return tonumber(n) or 0 end
function WowBuddyDev.IsHealingSpec() return false end
function WowBuddyDev.IsRangedDamageSpec() return true end
function WowBuddyDev.IsMeleeSpec() return false end
function WowBuddyDev.GetAutoTargetEnabled() return true end
function WowBuddyDev.IsBindPressed() return false end
function WowBuddyDev.IsAutoTargetGateOpen() return true end
function WowBuddyDev.GetTrinketSlotCooldownRemaining() return 0 end
function WowBuddyDev.IsGcdActive() return false end
function WowBuddyDev.GetPlayerCastState() return false,0,0,0 end
function WowBuddyDev.GetPlayerSucceededState() return 0,0 end
function WowBuddyDev.GetPackedGameIdentity() return 1482 end
local secure=object('SecureButton')
function WowBuddyDev.CreateSecureButton() return true end
function WowBuddyDev.GetSecureButton() return secure end
function tickPixelBar(delta)
  now=now+delta
  for _,f in ipairs(frames) do if f.scripts.OnUpdate then f.scripts.OnUpdate(f,delta) end end
end
function pixelAt(x,y)
  for _,texture in ipairs(textures) do
    if texture.parent==WowBuddyDev.pixelContainer and texture.point and
       texture.point[4]==x and texture.point[5]==y then return texture end
  end
end
function visiblePixelRectangles()
  local result={}
  if not WowBuddyDev.pixelContainer.shown then return result end
  for _,texture in ipairs(textures) do
    if texture.parent==WowBuddyDev.pixelContainer and texture.shown and texture.point and texture.color then
      result[#result+1]={x=texture.point[4],y=-texture.point[5],width=texture.width,height=texture.height,
                        r=texture.color[1],g=texture.color[2],b=texture.color[3]}
    end
  end
  return result
end
