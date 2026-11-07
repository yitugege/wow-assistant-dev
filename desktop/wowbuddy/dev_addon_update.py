"""独立GitHub包到原插件重装策略的桥接；不自行扫描游戏或启动定时器。"""
import json
import re
from pathlib import Path
from .addon_update import AddonUpdater, ReinstallResult
from .dev_addon_install import install_addons_directory, read_package
from .github_addon import download_latest


def installed_name(addons):
    addons=Path(addons)
    record=addons.parent.parent/'.wowbuddy-install.json'
    try:
        value=json.loads(record.read_text('utf8'))
        name=value.get('addon_directory','')
        if value.get('product')!='wowbuddy-dev':return ''
        if name!='WowBuddyDev' and not re.fullmatch(r'w[0-9a-f]{12}',name):return ''
    except FileNotFoundError:name='WowBuddyDev'
    except (OSError,ValueError,TypeError):return ''
    return name if (addons/name/(name+'.toc')).is_file() else ''


def refresh_package(data_dir, *, fetch_package=download_latest):
    """工作线程下载校验；原子提交缓存指针，失败保留上次可用包。"""
    root=Path(data_dir)
    root.mkdir(parents=True,exist_ok=True)
    pointer=root/'addon-release.json'
    try:cached=json.loads(pointer.read_text('utf8'))
    except (OSError,ValueError):cached=None
    if not isinstance(cached,dict):cached=None
    release=fetch_package(root,cached=cached)
    read_package(release['package'])
    temporary=pointer.with_suffix('.tmp')
    temporary.write_text(json.dumps(release,ensure_ascii=False),'utf8')
    temporary.replace(pointer)
    return release


def apply_release(release, pending, *, games, installed_name, on_log=None, install=None):
    """主线程调用；games每次返回新快照，安装前仍使用当前包完整校验。"""
    read_package(release['package'])
    def reinstall(path):
        try:
            result=install_addons_directory(release['package'],path)
            return ReinstallResult(True,result['addon_directory'])
        except Exception as error:
            return ReinstallResult(False,error=str(error))
    policy=AddonUpdater(None,None,pending,env={},application_dir='.',games=games,
                        installed_name=installed_name,install=install or reinstall,on_log=on_log)
    if release['changed']:
        return policy.reinstall_games()
    policy.retry_pending()
    return policy.state
