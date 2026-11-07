"""从原EXE容器直接核对可读协议无效键；不运行原程序、不发送按键。"""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.audit_original_addon_origin import resource_inventory
from wowbuddy.packages import read_bundle
from wowbuddy.keybindings import parse_keybinding

def check():
    original=Path('D:/download/WOW战斗助手.exe').read_bytes()
    sha=hashlib.sha256(original).hexdigest()
    assert sha=='9694f988f740acd88402c6f0ddaaf6f9173525f8c8137941a553d2c74d97bf14'
    bundles=[raw for row,raw in resource_inventory(original) if row['wbd1']]
    assert len(bundles)==1
    members={m.name:m.data for m in read_bundle(bundles[0])}
    resources={}
    for name in ('rules.json','rules_readable.json'):
        raw=members[name]
        assert raw==(ROOT/'assets'/name).read_bytes(),name
        resources[name]={'sha256':hashlib.sha256(raw).hexdigest(),'source_equal':True}
    base=json.loads(members['rules.json'])
    readable=json.loads(members['rules_readable.json'])
    invalid=[]
    for spec,data in readable['specs'].items():
        actions={a['name']:a for a in base['specs'].get(spec,{}).get('actions',[])}
        for action in data['actions']:
            binding=parse_keybinding(action['key'])
            if binding.valid:continue
            prior=actions.get(action['name'])
            invalid.append({'spec':spec,'action':action['name'],'key':action['key'],
                            'key_codepoints':[ord(c) for c in action['key']],
                            'base_action_present':prior is not None,
                            'base_key':prior.get('key') if prior else None})
    return {'original_sha256':sha,'resources':resources,'invalid':invalid,
            'invalid_count':len(invalid),'native_execution':False,
            'scope':'原容器资源字节来源；非法判定使用独立解析器，原解析规则另见KEYBINDING-PARITY'}

if __name__=='__main__':
    result=check()
    (ROOT/'evidence/invalid-readable-bindings.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
