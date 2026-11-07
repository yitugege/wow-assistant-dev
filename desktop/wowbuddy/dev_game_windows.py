"""独立产品名包含wow：过滤本产品其他实例，避免被原子串规则误选。"""
import ntpath
from pathlib import Path
import json
import re
from functools import lru_cache
from .launcher import APPLICATION_NAME,BUSINESS_EXE
from .release_identity import CACHE_NAMESPACE,file_sha256


def _cache_namespace(executable):
    """只识别自有外层固定缓存层级；不按中文EXE名称全局排除。"""
    if not executable:return None
    path=Path(executable)
    if not path.is_absolute() or path.name.casefold()!=BUSINESS_EXE.casefold():return None
    if (not path.parent.name.startswith('app-') or path.parent.parent.name!=APPLICATION_NAME
            or not re.fullmatch(r'[0-9a-f]{16}',path.parent.parent.parent.name)):
        return None
    namespace=path.parent.parent.parent.parent
    return namespace if namespace.name==CACHE_NAMESPACE else None


@lru_cache(maxsize=128)
def _verified_cached_business(path,signature):
    # signature含文件与清单元数据，普通替换后重验；不是数字签名或授权凭证。
    business=Path(path);manifest=business.parent/'build-manifest.json'
    try:
        with manifest.open('rb') as stream:raw=stream.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:return False
        value=json.loads(raw)
        return (isinstance(value,dict) and value.get('passed') is True
                and isinstance(value.get('source_files'),dict)
                and 'run_dev.py' in value['source_files']
                and 'desktop/wowbuddy/dev_version.py' in value['source_files']
                and value.get('executable_sha256')==file_sha256(business))
    except (OSError,ValueError):return False


def is_cached_assistant(path,namespace):
    if namespace is None or _cache_namespace(path)!=namespace:return False
    business=Path(path);manifest=business.parent/'build-manifest.json'
    try:
        # 链接到其他目录的文件不凭缓存外观分类。
        if business.resolve()!=business or manifest.resolve()!=manifest:return False
        states=[business.stat(),manifest.stat()]
        signature=tuple((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns) for s in states)
        return _verified_cached_business(str(business),signature)
    except OSError:return False


class AssistantWindowFilter:
    def __init__(self,backend,*,current_executable=None):
        self.backend=backend
        self.current_executable=(ntpath.normcase(ntpath.normpath(str(current_executable)))
                                 if current_executable else None)
        self.cache_namespace=_cache_namespace(current_executable)

    def __getattr__(self,name):
        return getattr(self.backend,name)

    def enum_windows(self,visitor):
        def visit(hwnd):
            pid=self.backend.window_pid(hwnd)
            if pid and pid==self.backend.current_pid():
                return
            path=self.backend.process_path(pid) if pid else ''
            if ntpath.basename(path).casefold()=='wowbuddydev.exe':
                return
            if path and self.current_executable and ntpath.normcase(ntpath.normpath(path))==self.current_executable:
                return
            if path and is_cached_assistant(path,self.cache_namespace):
                return
            visitor(hwnd)
        self.backend.enum_windows(visit)
