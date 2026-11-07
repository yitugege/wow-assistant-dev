"""构建输入身份：每次重新枚举，覆盖新增、删除及插件内容变化。"""
import hashlib
from pathlib import Path


def snapshot_sources(root):
    root=Path(root)
    paths=[root/'run_dev.py',*sorted((root/'desktop/wowbuddy').rglob('*.py'))]
    for directory in ('assets','addon'):
        paths.extend(p for p in sorted((root/directory).rglob('*')) if p.is_file())
    result={}
    for path in paths:
        if path.is_symlink() or path.is_junction():
            raise ValueError('构建源码包含链接：'+str(path))
        result[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def require_matching_sources(root, recorded):
    current=snapshot_sources(root)
    if recorded!=current:
        changed=sorted(name for name in set(recorded)|set(current) if recorded.get(name)!=current.get(name))
        raise ValueError('业务源码或构建清单覆盖范围已变化，先重建：'+', '.join(changed[:8]))
    return current
