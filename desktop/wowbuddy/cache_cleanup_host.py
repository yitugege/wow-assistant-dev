"""原清理顺序的本地执行宿主；删除仅限显式验证的源码缓存父目录。"""
import os
from pathlib import Path
import stat
import time
from .cache_cleanup import snapshot_qt_cleanup,plan_old_unpack_cleanup


def _reparse(path):
    return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) if os.name=='nt' else path.is_symlink()


def _checked_tree(path,parent,current):
    """在每次递归删除前核对最终绝对目标；不遍历链接进入其他目录。"""
    if path.parent!=parent or path==current or not path.name.startswith('app-'):
        return False
    if path.resolve(strict=True)!=path or not path.is_dir():return False
    for ancestor in (path,*path.parents):
        if _reparse(ancestor):return False
    for directory,dirs,files in os.walk(path,followlinks=False):
        if any(_reparse(Path(directory)/name) for name in dirs+files):return False
    return True


def execute_cleanup(application_directory,*,allowed_parent,record=lambda text:None,clock_ms=None):
    """只清理allowed_parent直属app-*；链接拒绝属于重建版明确范围限制。"""
    from PySide6.QtCore import QDir
    current=Path(application_directory).absolute()
    parent=Path(allowed_parent).resolve(strict=True)
    if current.parent!=parent or current.resolve(strict=True)!=current:
        raise ValueError('当前程序目录不在明确缓存范围内')
    plan=plan_old_unpack_cleanup(snapshot_qt_cleanup(str(current)))
    if plan.disabled_reason:return dict(deleted=0,attempts=[],stop_reason=plan.disabled_reason)
    if Path(plan.parent_directory)!=parent:raise ValueError('清理计划父目录变化')
    clock_ms=clock_ms or (lambda:time.perf_counter_ns()//1_000_000)
    start=clock_ms();cursor=plan.cursor();attempts=[]
    while (candidate:=cursor.next_candidate(clock_ms()-start)) is not None:
        path=Path(candidate.absolute_path).absolute()
        try:
            admitted=_checked_tree(path,parent,current)
            removed=bool(QDir(str(path)).removeRecursively()) if admitted else False
            attempts.append(dict(path=str(path),admitted=admitted,removed=removed))
        except OSError as error:
            removed=False;attempts.append(dict(path=str(path),removed=False,error=str(error)))
        cursor.finish_attempt(removed)
    if cursor.startup_log_text:record(cursor.startup_log_text)
    return dict(deleted=cursor.successes,attempts=attempts,stop_reason=cursor.stop_reason)


def cleanup_source_release(inner,outer,*,record=lambda text:None):
    """验证外层标识/内层摘要和独立缓存树；不清理用户原版或跨摘要目录。"""
    from .release_identity import validated_outer_target,read_release_identity,CACHE_NAMESPACE
    inner=Path(inner)
    target=validated_outer_target(outer,inner)
    if target is None:return dict(deleted=0,stop_reason='unverified_source_release')
    try:
        identity=read_release_identity(target)
        current=inner.resolve(strict=True).parent
        parent=current.parent
        if parent.parent.name!=identity.cache_key or parent.parent.parent.name!=CACHE_NAMESPACE:
            return dict(deleted=0,stop_reason='outside_source_cache')
        return execute_cleanup(current,allowed_parent=parent,record=record)
    except (OSError,ValueError) as error:
        # 验证后文件仍可能被移走或占用；旧缓存维护失败不能阻断主窗启动。
        return dict(deleted=0,stop_reason='cleanup_unavailable',error=str(error))
