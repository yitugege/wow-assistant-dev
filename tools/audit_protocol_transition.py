"""在新仓库重放各职业的旧条→可读条，记录未还原边界而非吞掉异常。"""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
sys.path.insert(0,str(ROOT/'tests/core'))
from test_old_protocol import render_old
from test_pipeline import render_readable
from wowbuddy.assets import Assets
from wowbuddy.controller import FrameController
from wowbuddy.rotation_selection import HubState
from wowbuddy.readable_protocol import UnverifiedDescriptorTable
from wowbuddy.pipeline import DecisionPipeline


def main():
    assets=Assets.load(ROOT/'assets')
    rows=[]
    for spec in sorted(set(assets.contract['specs']) & set(assets.readable_contract['specs'])):
        controller=FrameController(assets.pipeline(),HubState())
        old,_=render_old(int(spec))
        first=controller.prepare(old).frame
        row={'spec':spec,'old_status':first.status,'old_field_count':len(first.rows)}
        second=None
        try:
            second=controller.prepare(render_readable(int(spec))).frame
            row.update(transition_status=second.status,readable_field_count=len(second.rows))
        except UnverifiedDescriptorTable as error:
            row.update(transition_status='descriptor_unverified',error=str(error))
        fresh=FrameController(assets.pipeline(),HubState()).prepare(render_readable(int(spec))).frame
        row.update(fresh_readable_status=fresh.status,fresh_readable_field_count=len(fresh.rows))
        legacy=FrameController(DecisionPipeline(assets.contract,assets.readable_contract,
            assets.rules,assets.readable_rules,legacy_descriptor_cache=True),HubState())
        legacy.prepare(old)
        try:
            prior=legacy.prepare(render_readable(int(spec))).frame
            row.update(legacy_transition_status=prior.status,legacy_field_count=len(prior.rows))
        except UnverifiedDescriptorTable as error:
            row.update(legacy_transition_status='descriptor_unverified',legacy_error=str(error))
        row['matches_fresh_readable'] = second == fresh
        rows.append(row)
    report={'rows':rows,'assets_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'assets').glob('*contract*.json')},
            'blocked_transitions':sum(r['transition_status']=='descriptor_unverified' for r in rows),
            'legacy_blocked_transitions':sum(r['legacy_transition_status']=='descriptor_unverified' for r in rows),
            'scope':'当前源码合成帧的控制器生命周期；没有运行原EXE或游戏，没有发键。'}
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/protocol-transition-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
