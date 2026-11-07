"""核对原参考插件与独立版治疗宏，不执行游戏或修改绑定。"""
import hashlib
import json
from pathlib import Path
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=Path('D:/reverse-analysis/wow-assistant/addon-source/classes/Druid/Druid-Bindings.lua')


def bindings(path,name):
    lua=LuaRuntime()
    lua.execute('''captured={};addon={}
    function addon.BindKey(key,body) assert(captured[key]==nil);captured[key]=body end
    function addon.RegisterClassMacros(class,fn) assert(class=='DRUID');fn() end''')
    lua.globals()[name]=lua.globals().addon
    lua.execute(path.read_text('utf8'))
    return dict(lua.globals().captured.items())


def audit():
    current=ROOT/'addon/WowBuddyDev/classes/Druid/Druid-Bindings.lua'
    original=bindings(REFERENCE,'P07483180');rebuilt=bindings(current,'WowBuddyDev')
    rules=json.loads((ROOT/'assets/rules.json').read_bytes())
    profiles=json.loads((ROOT/'assets/rotations.json').read_bytes())['rotations']
    actions={a['name']:a for a in rules['specs']['1484']['actions']}
    rows=[]
    for spell in (8936,774,5185,18562,408120):
        for suffix in ('','_focus'):
            name=f'spell_{spell}{suffix}';key=actions[name]['key']
            assert original[key]==rebuilt[key],name
            rows.append({'action':name,'key':key,'macro':rebuilt[key],
                         'same_as_reference':True,
                         'profile_ids':[p['id'] for p in profiles if p['specId']==1484 and
                                        any(r.get('action')==name for r in p['rules'])]})
    assert all(not row['profile_ids'] for row in rows if not row['action'].endswith('_focus'))
    result={'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (REFERENCE,current)},'macros':rows,
            'profile_count':len(profiles),'game_verified':False,
            'scope':'绑定回调文本及当前方案引用，不判断实际游戏宏执行结果'}
    (ROOT/'dist/druid-heal-macro-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'matched_macros':len(rows),'ordinary_heal_profile_references':0,
                      'profile_count':len(profiles)}))


if __name__=='__main__':audit()
