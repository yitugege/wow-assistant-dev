"""独立入口的离屏界面诊断；保留原报告与延迟，增加完成后退出及错误报告。"""
import json
from PySide6.QtCore import QTimer
from .cli_dump_ui import make_runner_for_window


def run_dump(app, window, options, output_dir):
    errors=[]
    warnings=[]
    runner=None
    done=False
    def write_report(path, text):
        try:
            normalized=text.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace')
            path.write_bytes(normalized.encode('utf8'))
            return True
        except OSError as error:
            errors.append(str(error))
            return False

    def finish():
        nonlocal done
        try:
            runner.write_ui()
            done=True
        except Exception as error:
            errors.append(repr(error))
        app.exit(0 if done and not errors else 1)

    def start():
        try:
            runner.start()
        except Exception as error:
            errors.append(repr(error))
            app.exit(1)

    delay=QTimer(window);delay.setSingleShot(True)
    completion=QTimer(window);completion.setSingleShot(True)
    completion.timeout.connect(finish)
    timeout=QTimer(window);timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: app.exit(1))
    runner=make_runner_for_window(window,options,application_dir=output_dir,
        warning=warnings.append,write_report=write_report,
        schedule=lambda milliseconds, callback: completion.start(milliseconds))
    delay.timeout.connect(start)
    delay.start(2600)
    timeout.start(10000)
    try:
        code=app.exec()
    finally:
        delay.stop();completion.stop();timeout.stop();runner.close()
    passed=(code==0 and done and runner.report_written and not errors
            and (not options.toggle_showall or runner.showall_written)
            and not window.session.is_active() and not window.watch_timer.isActive())
    report={'passed':bool(passed),'completed':done,'errors':errors,'warnings':warnings,
            'spec':window.controller.spec_id,'ui_written':runner.report_written,
            'showall_written':runner.showall_written,
            'monitor_active':window.session.is_active(),'watch_active':window.watch_timer.isActive(),
            'backend':type(window.monitor.backend).__name__,
            'scope':'离屏Qt界面诊断；不抓屏、不发键、不联网，不证明游戏功能完成'}
    (output_dir/'dump-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return int(not passed)
