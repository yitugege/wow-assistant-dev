"""原分阶段加载器到自有资源和主窗口的适配。"""
from copy import deepcopy
from pathlib import Path
from .assets import Assets
from .native_assets import NativeAssetStore
from .startup_stages import ResourceStageLoader
from .startup_splash import NeonSplash
from .qt_startup import QtStartup
from .game_windows import find_game_window
from .dev_version import VERSION


def create_staged_startup(app,assets_dir,windows,construct_main,record,*,auto_start=False):
    directory=Path(assets_dir)
    store=NativeAssetStore()
    loader=ResourceStageLoader(resolve=lambda name:str(directory/name) if (directory/name).exists() else '',
        load_contract=store.load_contract,load_rules=store.load_rules,
        load_readable_contract=store.load_readable_contract,load_readable_rules=store.load_readable_rules,
        find_game_window=lambda:find_game_window(windows))
    def construct():
        states=(store.contract,store.readable_contract,store.rules,store.readable_rules)
        assets=Assets(directory,*(deepcopy(state.raw_document or state.document) for state in states))
        return construct_main(assets)
    splash=NeonSplash(version=VERSION,website='https://github.com/yitugege/wow-assistant-dev',record=record)
    splash.setWindowTitle('WowBuddyDev — 启动')
    return QtStartup(app,splash,loader,construct_main=construct,record=record,auto_start=auto_start)
