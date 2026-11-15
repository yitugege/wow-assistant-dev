"""独立版离线方案初始化；已有用户快照不覆盖。"""
from pathlib import Path
from wowbuddy.engine.rotation_selection import load_snapshot


def read_local_library(path, previous):
    """先校验文件，失败不改变调用者持有的库。允许明确的空快照。"""
    payload = Path(path).read_bytes()
    parsed = load_snapshot(payload, previous, from_cache=True)
    if not parsed.accepted:
        from .hub_sync import snapshot_error_text
        raise ValueError(snapshot_error_text(parsed.state.error, payload))
    return parsed.state


def runtime_profile_action(spec_id, profile_id, action, reason):
    # 术士方案 33 的双 DOT 规则明确要求魔杖，原术士动作表没有 start_attack。
    if (spec_id == 1490 and profile_id == 33 and action == 'start_attack'
            and reason == '填充：双DOT齐全，使用魔杖自动射击'):
        return 'shoot_wand'
    return action


def profile_action_gaps(profile, *documents):
    """报告所有协议动作表均未注册的动作；动态目标动作单独处理。"""
    if profile is None:
        return ()
    available = set()
    for document in documents:
        spec = document.get('specs', {}).get(str(profile.spec_id), {})
        available.update(action.get('name') for action in spec.get('actions', []))
    missing = []
    for rule in profile.rules:
        action = rule.action
        if 'shoot_wand' in available:
            action = runtime_profile_action(profile.spec_id, getattr(profile, 'id', None), action,
                                            getattr(rule, 'reason', ''))
        for name in (action, rule.pre):
            if (not name or name in available or name == 'auto_target'
                    or name.startswith('focus_') or name in missing):
                continue
            missing.append(name)
    return tuple(missing)


def seed_library(assets, data_dir):
    target = Path(data_dir) / 'hub' / 'rotations.json'
    if target.exists():
        return False
    payload = (Path(assets) / 'rotations.json').read_bytes()
    parsed = load_snapshot(payload)
    if not parsed.accepted or not parsed.state.profiles:
        raise ValueError('内置循环方案快照无效或为空')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('xb') as stream:
            stream.write(payload)
    except FileExistsError:
        return False
    return True
