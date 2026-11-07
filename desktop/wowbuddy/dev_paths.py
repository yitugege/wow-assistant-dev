"""独立数据目录：仅已验证的自有外层可将数据移出释放缓存。"""
import os
from pathlib import Path
import sys
from .release_identity import validated_outer_target


def default_data_dir(application, *, frozen=None, executable=None, environment=None):
    fallback=Path(application)/'.local'
    frozen=bool(getattr(sys,'frozen',False)) if frozen is None else frozen
    if not frozen:return fallback
    environment=os.environ if environment is None else environment
    outer=environment.get('WOWBUDDY_EXE','')
    home=environment.get('WOWBUDDY_HOME','')
    if not outer or not home:return fallback
    target=validated_outer_target(outer,Path(sys.executable if executable is None else executable))
    if target is None:return fallback
    try:
        home_path=Path(home)
        if not home_path.is_absolute() or home_path.resolve(strict=True)!=target.parent:
            return fallback
    except (OSError,ValueError):return fallback
    return target.parent/'.local'
