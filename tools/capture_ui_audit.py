"""离屏主窗审查：无游戏/网络后端，只为审查进程加载本机字体。"""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'desktop')]
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase,QFontMetrics
from wowbuddy.desktop import NoSystemBackend
import run_dev


def main():
    app=QApplication.instance() or QApplication([])
    fonts=Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'
    loaded={name:QFontDatabase.addApplicationFont(str(fonts/name))
            for name in ('msyh.ttc','msyhbd.ttc','segoeui.ttf') if (fonts/name).is_file()}
    output=ROOT/'dist/ui-audit';output.mkdir(parents=True,exist_ok=True)
    def capture():
        window=next(w for w in app.topLevelWidgets()
                    if w.windowTitle()=='WowBuddyDev — 独立开发版' and not getattr(w,'_closed',True))
        app.processEvents()
        if not window.grab().save(str(output/'main-window-fonts.png')):
            raise RuntimeError('无法写入主窗截图')
        report={'platform':app.platformName(),'test_fonts_loaded':loaded,
                'chinese_in_font':QFontMetrics(window.ui.title_label.font()).inFontUcs4(0x52a9),
                'project_button':window.ui.website_button.text(),'update_label':window.ui.update_status.text(),
                'monitor_active':window.session.is_active(),'game_tested':False}
        (output/'font-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(report))
        return 0
    with TemporaryDirectory() as directory,patch('wowbuddy.game_windows.CtypesWindowBackend',return_value=NoSystemBackend()),patch('wowbuddy.capture.make_win32_capture',return_value=NoSystemBackend()),patch('wowbuddy.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()),patch('PySide6.QtWidgets.QSystemTrayIcon.isSystemTrayAvailable',return_value=False),patch.object(QApplication,'exec',side_effect=capture):
        return run_dev.launch(directory,hub_online=False,client_online=False,addon_online=False)


if __name__=='__main__':raise SystemExit(main())
