"""真实Lua位图/RGB函数→桌面字段解码→技能可用性；不调用游戏。"""
import json
import hashlib
import random
from pathlib import Path
import sys
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
sys.path.insert(0,str(ROOT/'tests/core'))
from wowbuddy.expressions import EvaluationContext
from wowbuddy.assets import Assets
from wowbuddy.dev_protocol import DEV_VERSION, MAX_AVAILABILITY_SPELLS
from test_old_protocol import render_old
from test_pipeline import render_readable


def main():
    source=(ROOT/'addon/WowBuddyDev/PixelBar.lua').read_text('utf8')
    start=source.index('local function rgbFromInt(')
    end=source.index('\nlocal maxRgbValue',start)
    lua=LuaRuntime(unpack_returned_tuples=True)
    rgb=lua.execute(source[start:end]+'\nreturn rgbFromInt')
    start=source.index('  local actionAvailBitmap = 0')
    end=source.index('  valuesById.action_avail = actionAvailBitmap',start)
    bitmap=lua.execute('return function()\n'+source[start:end]+'\nreturn actionAvailBitmap end')
    rules=json.loads((ROOT/'assets/rules.json').read_text('utf8'))
    total=0
    frame_rows=[];frame_total=0
    assets=Assets.load(ROOT/'assets')
    for spec,config in rules['specs'].items():
        ids=config.get('actionAvailSpellIDs',[])
        if len(ids)>MAX_AVAILABILITY_SPELLS:
            raise ValueError(f'{spec} 超出24项协议容量')
        rng=random.Random(int(spec))
        cases=[('none',set()),('all',set(ids)),*[(f'only_{sid}',{sid}) for sid in ids],
               ('all_but_first',set(ids[1:])),('all_but_last',set(ids[:-1])),('last_two',set(ids[-2:]))]
        cases.extend((f'random_{i}',{sid for sid in ids if rng.randrange(2)}) for i in range(16))
        for label,ready in cases:
            lua.globals().WowBuddyDev=lua.table_from({'actionAvailSpellIDs':lua.table_from(ids),
                                                     'IsSpellReady':lambda sid: sid in ready})
            value=bitmap();color=tuple(round(c*255) for c in rgb(value))
            total+=1
            packed=(color[0]<<16)|(color[1]<<8)|color[2]
            if packed!=value:
                raise ValueError(f'{spec}/{label} RGB编码截断')
            overrides={'action_avail':packed,'master_switch':0x00FF00,
                       'addon_version_code':DEV_VERSION,
                       'player_casting':0xFF0000,'gcd':0xFF0000}
            for sid in ids:
                for key in (f'spell_{sid}',f'ready_{sid}',f'spell_{sid}_ready'):
                    overrides[key]=0x00FF00 if sid in ready else 0xFF0000
            for protocol,image in (('old',render_old(int(spec),overrides)[0]),
                                   ('readable',render_readable(int(spec),overrides))):
                frame=assets.pipeline().prepare(image).frame
                if not frame.ok:
                    raise RuntimeError(f'{spec}/{protocol}: {frame.status}')
                full_context=EvaluationContext(frame.values,tuple(ids),
                    allow_unknown_availability=frame.allow_unknown_availability)
                mismatches=[{'spell':sid,'expected':int(sid in ready),'actual':full_context.availability(sid)}
                    for sid in ids if full_context.availability(sid)!=int(sid in ready)]
                frame_total+=1
                if mismatches:
                    frame_rows.append({'spec':spec,'case':label,'protocol':protocol,
                        'bitmap_field_type':next(row.type for row in frame.rows if row.key=='action_avail'),
                        'decoded_bitmap':frame.values.get('action_avail'),
                        'allow_unknown_availability':frame.allow_unknown_availability,
                        'mismatches':mismatches})
    report={'cases':total,'protocol_version':DEV_VERSION,
            'frame_cases':frame_total,'failed_frame_cases':len(frame_rows),'frame_failures':frame_rows,
            'inputs_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [ROOT/'addon/WowBuddyDev/PixelBar.lua',ROOT/'addon/WowBuddyDev/Core.lua',ROOT/'assets/contract.json',
                             ROOT/'assets/contract_readable.json',ROOT/'assets/rules.json']},
            'scope':'真实Lua编码到字段解码，以及合成完整旧/可读图像到当前管线和可用性判断；不证明游戏中的出现频率。'}
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/availability-pixel-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'cases':total,
                      'frame_cases':frame_total,'failed_frame_cases':len(frame_rows),
                      'affected_specs':sorted({r['spec'] for r in frame_rows})}))
    return int(bool(frame_rows))


if __name__=='__main__':raise SystemExit(main())
