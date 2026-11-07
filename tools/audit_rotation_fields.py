"""检查循环规则的显式字段引用；动态派生字段单独列出，不据此判定可施法。"""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.assets import Assets


def references(expr):
    if not isinstance(expr,list) or not expr:return
    if expr[0] in ('and','or','not'):
        for child in expr[1:]:yield from references(child)
    elif expr[0] in ('flag','ready','num_at_least','num_below','interruptible'):
        if len(expr)>1 and isinstance(expr[1],str):yield expr[1]
    elif expr[0]=='enemies_at_least':yield 'active_enemies'


def main():
    assets=Assets.load(ROOT/'assets');pipeline=assets.pipeline()
    profiles=json.loads((ROOT/'assets/rotations.json').read_text('utf8'))['rotations']
    result=[]
    derived={'form','player_valid','target_valid','health_player','health_target'}
    for i in range(1,5):derived.update((f'health_party{i}',f'friendly_party{i}'))
    for profile in profiles:
        spec=str(profile['specId'])
        old={f['id'] for f in pipeline.old.field_definitions(spec)}
        readable={key for key,_,_ in pipeline.readable.field_definitions(spec)}
        refs={key for rule in profile['rules'] for key in references(rule.get('when'))}
        dynamic={key for key in refs if key.startswith(('sw_','ready_','spell_')) or key in derived}
        missing=sorted(refs-old-readable-dynamic)
        result.append({'id':profile['id'],'name':profile['profileName'],'spec':spec,
                       'explicit_reference_count':len(refs),'absent_from_both_contracts':missing,
                       'dynamic_references_not_verified':sorted(dynamic-old-readable)})
    report={'profiles':result,'profiles_with_missing_fields':sum(bool(p['absent_from_both_contracts']) for p in result),
      'scope':'显式字段在两份契约中的静态覆盖；动态字段和avail位映射仍需单独验证，未运行游戏。'}
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/rotation-field-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='profiles'},ensure_ascii=False))


if __name__=='__main__':main()
