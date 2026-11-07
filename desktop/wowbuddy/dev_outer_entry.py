"""自有外层本地联测入口，复用原资源释放与启动宿主。"""
import os
import sys
from .outer_entry import SourceReleaseAPI
from .launcher import WindowsLauncherFiles,WindowsLauncherProcess
from .launcher_host import launch_host


def main():
    if not getattr(sys,'frozen',False):
        raise RuntimeError('需要包含资源200/203的冻结外层')
    api=SourceReleaseAPI()
    api.cache_root.mkdir(parents=True,exist_ok=True)
    os.environ['PYINSTALLER_RESET_ENVIRONMENT']='1'
    result=launch_host(api,filesystem=WindowsLauncherFiles(api.cache_root),
        process=WindowsLauncherProcess(inherit_current_environment=True))
    return result.exit_code
