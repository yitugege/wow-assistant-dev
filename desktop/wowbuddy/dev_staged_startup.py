"""原分阶段加载器到自有资源和主窗口的适配。"""
from pathlib import Path
from .native_assets import NativeAssetStore
from .startup_stages import ResourceStageLoader
from .startup_splash import NeonSplash
from .qt_startup import QtStartup
from wowbuddy.win32.game_windows import find_game_window
from .dev_version import REPOSITORY, VERSION


def create_staged_startup(app,assets_dir,windows,construct_main,record,*,auto_start=False,after_main=lambda window:None,after_authorization=lambda:None):
    directory=Path(assets_dir)
    store=NativeAssetStore()
    loader=ResourceStageLoader(resolve=lambda name:str(directory/name) if (directory/name).exists() else '',
        load_contract=store.load_contract,load_rules=store.load_rules,
        load_readable_contract=store.load_readable_contract,load_readable_rules=store.load_readable_rules,
        find_game_window=lambda:find_game_window(windows))
    def construct():
        return construct_main(store.to_assets(directory))
    splash=NeonSplash(version=VERSION,website='https://github.com/'+REPOSITORY,record=record)
    splash.setWindowTitle('WowBuddyDev — 启动')
    return QtStartup(app,splash,loader,construct_main=construct,record=record,auto_start=auto_start,
                     after_main=after_main,after_authorization=after_authorization)
