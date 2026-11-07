"""对照离线方案、桌面动作表和真实Lua职业注册表；不执行游戏回调。"""
from pathlib import Path
import json
import sys
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.candidates import CandidateEngine
from wowbuddy.keybindings import parse_keybinding


def main():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
    WowBuddyDev={classes={}}
    function WowBuddyDev.RegisterPixelStripV2() end
    function WowBuddyDev.RegisterClass(id,data) WowBuddyDev.classes[id]=data end
    function CreateFrame() return {RegisterUnitEvent=function() end,
      RegisterEvent=function() end,SetScript=function() end} end
    function UnitClass() return '测试职业', CURRENT_CLASS end
    function WowBuddyDev.LocalizeMacroBody(text) return text end
    applied={}
    function WowBuddyDev.CreateSecureButton(action,key,body) applied[key]=body; return true end
    ''')
    lua.execute((ROOT/'addon/WowBuddyDev/Bindings.lua').read_text('utf8'))
    class_tokens={}
    for path in sorted((ROOT/'addon/WowBuddyDev/classes').glob('*/class_forever.lua')):
        before=set(lua.globals().WowBuddyDev.classes.keys())
        lua.execute(path.read_text('utf8'))
        for spec in set(lua.globals().WowBuddyDev.classes.keys())-before:
            class_tokens[str(spec)]=path.parent.name.upper()
        lua.execute((path.parent/(path.parent.name+'-Bindings.lua')).read_text('utf8'))
    library=json.loads((ROOT/'assets/rotations.json').read_text('utf8'))
    rules=json.loads((ROOT/'assets/rules.json').read_text('utf8'))
    engine=CandidateEngine(rules)
    profiles=[]
    availability=[]
    registered=[]
    for spec in sorted({str(p['specId']) for p in library['rotations']}):
        addon=lua.globals().WowBuddyDev.classes[int(spec)]
        ids=addon['actionAvailSpellIDs'] if addon is not None else None
        addon_ids=[ids[i] for i in range(1,len(ids)+1)] if ids is not None else []
        desktop_ids=rules['specs'].get(spec,{}).get('actionAvailSpellIDs',[])
        availability.append({'spec':spec,'addon_ids':addon_ids,'desktop_ids':desktop_ids,
                             'same_order':addon_ids==desktop_ids})
        keys=dict(addon['ACTION_TO_KEY'].items())
        macros=dict(addon['DEFAULT_MACROS'].items())
        desktop_actions={a['name']:a for a in rules['specs'].get(spec,{}).get('actions',[])}
        lua.globals().CURRENT_CLASS=class_tokens[spec]
        lua.execute('applied={}; assert(WowBuddyDev.ApplyClassMacros())')
        applied=dict(lua.globals().applied.items())
        collisions={}
        for action,key in keys.items():
            collisions.setdefault(key,[]).append(action)
        registered.append({'spec':spec,'desktop_action_count':len(desktop_actions),
            'addon_action_count':len(keys),
            'missing_macros':sorted(a for a in keys if not macros.get(a)),
            'invalid_keys':{a:k for a,k in keys.items() if not parse_keybinding(k).valid},
            'key_collisions':{k:sorted(v) for k,v in collisions.items() if len(v)>1},
            'addon_only_actions':sorted(set(keys)-set(desktop_actions)),
            'desktop_only_actions':sorted(set(desktop_actions)-set(keys)),
            'key_mismatches':{a:{'desktop':v.get('key'),'addon':keys.get(a)}
                for a,v in desktop_actions.items() if a in keys and v.get('key')!=keys[a]},
            'applied_class_macro_count':len(applied),
            'desktop_missing_applied_macro':sorted(a for a,v in desktop_actions.items() if not applied.get(v.get('key'))),
            'desktop_applied_macro_differences':{a:{'expected':macros.get(a),'applied':applied.get(v.get('key'))}
                for a,v in desktop_actions.items() if applied.get(v.get('key')) != macros.get(a)},
            'addon_actions_without_class_macro':sorted(a for a,k in keys.items() if not applied.get(k))})
    for profile in library['rotations']:
        spec=str(profile['specId'])
        actions={a['name']:a for a in rules['specs'].get(spec,{}).get('actions',[])}
        addon=lua.globals().WowBuddyDev.classes[int(spec)]
        keys=addon['ACTION_TO_KEY'] if addon is not None else None
        findings=[]
        for rule in profile['rules']:
            for action in filter(None,(rule.get('action'),rule.get('pre'))):
                # Focus/自动选怪由专用绑定模块生成，不属于静态职业技能表。
                if action.startswith('focus_') or action=='auto_target':
                    continue
                desktop=actions.get(action)
                addon_key=keys[action] if keys is not None else None
                if desktop is None or not addon_key or desktop.get('key') != addon_key:
                    item={'action':action,'desktop_key':desktop.get('key') if desktop else None,
                          'addon_key':addon_key}
                    if desktop is None:
                        candidates=engine.generate(spec,{'master_switch':'ON','player_casting':'空闲','gcd':'OFF'},
                            selected_rules=[{'action':action,'when':['always']}])
                        item['absent_even_with_unconditional_rule']=not any(c.action==action for c in candidates)
                    if item not in findings:findings.append(item)
        profiles.append({'id':profile['id'],'spec':spec,'name':profile['profileName'],
                         'rules':len(profile['rules']),'findings':findings})
    report={'profiles':profiles,'profile_count':len(profiles),
            'availability_tables':availability,
            'registered_action_audit':registered,
            'availability_tables_match':all(row['same_order'] for row in availability),
            'profiles_with_findings':sum(bool(p['findings']) for p in profiles),
            'scope':'职业键表及真实Lua注册/应用流程；游戏API和本地化为替身，不证明宏目标条件、游戏执行或动态焦点绑定正确'}
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/rotation-binding-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('profiles','availability_tables','registered_action_audit')},ensure_ascii=False))


if __name__=='__main__':main()

