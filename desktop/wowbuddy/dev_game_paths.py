"""独立入口路径适配；原检测模块保留用于行为对照。"""
from pathlib import Path
import json
import re
from .dev_addon_install import client_directory

VARIANTS=('_classic_beta_','_cn_beta_','_forever_')


def normalize_client(selected):
    path=Path(selected).absolute()
    if path.name.lower()=='interface':path=path.parent
    try:return client_directory(path)
    except ValueError:
        for variant in VARIANTS:
            try:return client_directory(path/variant)
            except ValueError:pass
        raise ValueError('未找到客户端：请选择游戏根目录、客户端、Interface 或 AddOns 目录')


def discover_clients(settings,*,running_executable='',search_roots=(),environment=None):
    if environment is not None and 'WOWBUDDY_NO_GAME_SCAN' in environment:return ()
    candidates=[]
    running=Path(running_executable).absolute().parent if running_executable else None
    if running:candidates.append(running)
    snapshot=settings.snapshot()
    candidates.extend(Path(p) for p in (snapshot.addon_last_dir,*snapshot.addon_history) if p)
    candidates.extend(Path(p) for p in settings._read('game/roots',[],'strings') if p)
    candidates.extend(Path(p) for p in search_roots)
    result=[];seen=set()
    for candidate in candidates:
        for path in (candidate,*(candidate/v for v in VARIANTS)):
            try:client=normalize_client(path)
            except (ValueError,OSError):continue
            key=str(client).casefold()
            if key in seen:continue
            seen.add(key)
            installed=False
            try:
                record=json.loads((client/'.wowbuddy-install.json').read_text('utf8'))
                name=record.get('addon_directory','')
                if record.get('product')=='wowbuddy-dev' and (name=='WowBuddyDev' or re.fullmatch(r'w[0-9a-f]{12}',name)):
                    installed=(client/'Interface/AddOns'/name/(name+'.toc')).is_file()
            except (OSError,ValueError,TypeError):pass
            result.append((client, running is not None and str(client).casefold()==str(running).casefold(),installed))
    result.sort(key=lambda item:(not item[1],not item[2]))
    return tuple(item[0] for item in result)


def common_roots():
    return tuple(Path(f'{drive}:/')/suffix for drive in 'CDEFGHIJ'
                 for suffix in ('World of Warcraft','Games/World of Warcraft','Blizzard/World of Warcraft',
                                'Program Files (x86)/World of Warcraft','Program Files/World of Warcraft'))
