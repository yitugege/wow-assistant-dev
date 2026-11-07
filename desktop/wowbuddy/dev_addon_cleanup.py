"""独立入口的旧插件清理，复用原三个特征文件判定及删除结果。"""
from pathlib import Path
from .addon_actions import LocalAddonFiles, CleanupResult
from .dev_addon_install import client_directory, _plain_path
from .dev_addon_update import installed_name


def cleanup_old_addons(selected):
    client=client_directory(selected)
    addons=client/'Interface/AddOns'
    return cleanup_addons_directory(addons,installed_name(addons))


def cleanup_addons_directory(addons,keep):
    addons=Path(addons).absolute()
    _plain_path(addons)
    files=LocalAddonFiles()
    # 固定开发目录即使安装记录损坏也不作为旧商业插件清理。
    names=tuple(name for name in files.entries(str(addons)) if name.casefold()!='wowbuddydev')
    plan=files.plan_cleanup(str(addons),keep=keep,names=names)
    # 独立安装边界不跟随链接；原删除器保留供行为对照。
    for name in plan.names:
        target=addons/name
        _plain_path(target)
        if target.resolve().parent!=addons.resolve():
            raise ValueError('旧插件目录超出所选AddOns边界')
    if any(links for _,links in plan.link_targets):
        raise ValueError('旧插件目录包含链接或目录联接，未执行清理')
    if not plan.names:return CleanupResult(notes='没有发现需要清理的旧插件目录。')
    return files.execute_cleanup(plan,selected_path=str(addons))
