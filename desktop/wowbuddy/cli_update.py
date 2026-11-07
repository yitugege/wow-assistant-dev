"""0744c0 更新CLI：局部事件循环、原版报告/退出码及限定源码EXE的交接。"""
from dataclasses import dataclass, field
import ntpath
import os
from pathlib import Path

from .updater import CURRENT_VERSION, resolve_target_path, resolve_update_url


@dataclass
class UpdateCommandState:
    update_now: bool
    lines: list[str] = field(default_factory=list)
    exit_code: int = -1
    done: bool = False

    def begin(self, version, url, target):
        self.lines.extend(("== 自动更新 ==", f"当前版本 {version}", f"清单地址 {url}",
                           "替换目标 " + (target or "（开发模式：只能检查，不能自动替换）")))

    def status(self, text):
        self.lines.append("· " + text)

    def checked(self, info):
        if not info.ok:
            self.lines.append("检查失败：" + info.error)
            self.exit_code, self.done = 1, True
            return False
        self.lines.extend((f"线上版本 {info.version}（通道 {info.channel} · {info.date}）",
                           f"下载地址 {info.download_url}", f"大小 {info.size} 字节 · sha256 {info.sha256}"))
        self.lines.append(f"★ 有新版本：{info.current_version} → {info.version}" if info.has_update else "已是最新版本")
        self.exit_code = 10 if info.has_update else 0
        if self.update_now and info.has_update:
            self.lines.append("开始下载并安装…")
            return True
        self.done = True
        return False

    def failed(self, text):
        self.lines.append("安装失败：" + text)
        self.exit_code, self.done = 1, True

    def replaced(self, text):
        # 05b7f0在尝试重启前记录安装成功并赋0；重启失败不改该退出码。
        self.lines.append("安装成功：" + text)
        self.exit_code = 0

    def restarted(self, *, skipped, started=False):
        self.lines.append("（已按 WOWBUDDY_UPDATE_NO_RESTART 跳过重启）" if skipped else
                          "已启动更新后的程序" if started else
                          "更新完成，但重启失败 —— 请手动打开程序")
        self.done = True

    def report(self):
        return "\n".join(self.lines) + "\n"


@dataclass(frozen=True)
class CliUpdateResult:
    exit_code: int
    report_path: Path
    report_text: str
    report_written: bool
    timed_out: bool
    report_error: str = ""


def run_update_command(options, *, application_dir, environment, application_arguments,
                       client, handoff=None, timeout_ms=300_000, write_report=None):
    """client归本次命令所有，结束时断开/关闭；测试可注入假网络和短超时。

    check-update不要求交接后端。update-now的真实目标必须匹配显式scope；
    这是本地重建范围约束，不能让WOWBUDDY_EXE任意文件获得写入授权。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from .cli_install import write_local_report
    if options.command not in ("check_update", "update_now"):
        raise ValueError("只接受原生更新命令")
    state = UpdateCommandState(options.command == "update_now")
    updater = client.updater
    state.begin(updater.current_version, resolve_update_url(environment, str(application_dir), updater.fs),
                resolve_target_path(environment))
    loop, timer = QEventLoop(), QTimer()
    timer.setSingleShot(True)
    timed_out, last_phase = False, None

    def expire():
        nonlocal timed_out
        timed_out = True
        loop.quit()  # 保留原当前退出码：尚未checked为-1；下载中可能是10。

    def ui_changed(ui):
        nonlocal last_phase
        if state.done:
            return
        if ui.phase != last_phase:
            last_phase = ui.phase
            if ui.phase in ("checking", "downloading", "verifying"):
                state.status(ui.text)
            elif ui.phase == "download_failed":
                state.failed(ui.text)
                loop.quit()

    def checked(info):
        if state.done:
            return
        if not state.checked(info):
            loop.quit()
            return
        target = resolve_target_path(environment)
        if target and (handoff is None or ntpath.normcase(ntpath.normpath(target)) !=
                       ntpath.normcase(ntpath.normpath(handoff.scope.executable))):
            state.failed("更新目标不属于此源码程序的测试 EXE 范围")
            loop.quit()
            return
        client.download()

    def verified(download):
        if state.done:
            return
        if handoff is None:
            state.failed("更新交接未配置：需要明确指定本地测试 EXE")
            loop.quit()
            return
        skip = "WOWBUDDY_UPDATE_NO_RESTART" in environment
        try:
            result = handoff.execute(download, application_arguments=application_arguments,
                quit_callback=loop.quit, restart=not skip, schedule_restart_exit=False,
                on_replaced=state.replaced,
                on_status=lambda text: state.status(text) if text == "正在替换程序文件…" else None)
            if result.phase == "replacement_failed":
                state.failed(result.text)
            else:
                state.restarted(skipped=skip, started=result.restart_started)
        except (OSError, ValueError) as error:
            state.failed("更新交接失败：" + str(error))
        loop.quit()

    slots = ((client.ui_changed, ui_changed), (client.checked, checked), (client.verified, verified))
    for signal, slot in slots:
        signal.connect(slot)
    timer.timeout.connect(expire)
    try:
        client.check(manual=False)
        timer.start(timeout_ms)
        if not state.done:
            loop.exec()
        timer.stop()
        report_path, text = Path(application_dir) / "_update.txt", state.report()
        error = ""
        try:
            written = bool((write_report or write_local_report)(report_path, text.encode("utf-8")))
        except OSError as exc:
            written, error = False, str(exc)
        return CliUpdateResult(state.exit_code, report_path, text, written, timed_out, error)
    finally:
        timer.stop()
        for signal, slot in slots:
            signal.disconnect(slot)
        client.close()


def run_local_update_command(options, *, application_dir, application_arguments,
                             environment=None, handoff=None):
    from .qt_updater import QtUpdaterClient
    env = dict(os.environ if environment is None else environment)
    client = QtUpdaterClient(env=env, application_dir=str(application_dir), current_version=CURRENT_VERSION)
    try:
        return run_update_command(options, application_dir=application_dir, environment=env,
            application_arguments=application_arguments, client=client, handoff=handoff)
    finally:
        client.deleteLater()
