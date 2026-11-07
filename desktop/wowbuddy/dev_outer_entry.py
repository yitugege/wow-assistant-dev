"""自有外层本地联测入口，复用原资源释放与启动宿主。"""
import os
import sys
from .outer_entry import SourceReleaseAPI
from .launcher import WindowsLauncherFiles,WindowsLauncherProcess
from .launcher_host import launch_host,WindowsHostAPI

PROJECT_URL='https://github.com/yitugege/wow-assistant-dev'
ERROR_TITLE='WowBuddyDev — 启动失败'


def show_development_failure(api,result):
    """保持原退出码、原因和路径；仅替换独立产品提示身份。"""
    if result.exit_code==2:
        text='解包失败：'+(result.error or '')+'\n\n缓存目录：\n'+result.release_directory
    elif result.exit_code==3:
        text=result.error or ''
    else:return
    api.message_box(None,text+'\n\n项目地址：'+PROJECT_URL,ERROR_TITLE,0x10)


def main():
    if not getattr(sys,'frozen',False):
        raise RuntimeError('需要包含资源200/203的冻结外层')
    api=None
    try:
        api=SourceReleaseAPI()
        api.cache_root.mkdir(parents=True,exist_ok=True)
        os.environ['PYINSTALLER_RESET_ENVIRONMENT']='1'
        result=launch_host(api,filesystem=WindowsLauncherFiles(api.cache_root),
            process=WindowsLauncherProcess(inherit_current_environment=True),show_errors=False)
    except (OSError,ValueError) as error:
        # 自有身份资源和缓存初始化在原核心之外；给出独立失败码及可见原因。
        (api or WindowsHostAPI()).message_box(None,'启动初始化失败：'+str(error)+
            '\n\n项目地址：'+PROJECT_URL,ERROR_TITLE,0x10)
        return 1
    show_development_failure(api,result)
    return result.exit_code
