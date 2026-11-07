"""075960/05d800 GUI 分阶段启动；纯编排，不联网授权、不创建真实窗口。"""
from __future__ import annotations
from dataclasses import dataclass
import time
from typing import Callable, Any

STAGE_NAMES = (
    "加载字段契约 contract.json", "加载循环规则 rules.json", "加载 readable 契约（可选）",
    "初始化霓虹界面", "探测游戏窗口", "装配发键通道", "就绪",
)
STAGE_INTERVAL_MS = 300
WARNING_DELAY_MS = 1500
AUTO_START_DELAY_MS = 600
SPLASH_SHOWN = "启动画面已显示"
BUILDING_TEXT = "正在构建界面…"
MAIN_CONSTRUCTION = "构造主窗口 MainWindow"
WARNING_CONSTRUCTION = "构造主窗口 MainWindow（提示之后）"
MAIN_SHOWN = "★ 主窗口已显示，启动完成（此后日志由界面发键面板接管）"
LOCAL_AUTHORIZATION = "本地测试授权：默认通过（未执行原版在线卡密验证）"
MISSING_CONTRACT = "找不到 contract.json"
MISSING_RULES = "找不到 rules.json（跑 export_cpp_rules.py 导出）"
MISSING_GAME = "未找到魔兽窗口（可在界面里手动选）"
SPLASH_CANCELLED = "★ 点了右上角「✕」—— 退出程序（本次未完成验证）"


def resource_candidates(name: str, application_dir: str, current_dir: str) -> tuple[str, ...]:
    """05ecf0 五处查找；不根据HOME或文件可解析性改变优先级。"""
    return (application_dir + "/resources/" + name, application_dir + "/" + name,
            current_dir + "/resources/" + name, current_dir + "/../resources/" + name,
            current_dir + "/cpp_monitor/resources/" + name)


def find_resource(name: str, *, application_dir: str, current_dir: str,
                  exists: Callable[[str], bool] | None = None,
                  absolute_path: Callable[[str], str] | None = None) -> str:
    """原版只检查exists，因此目录也会阻止搜索后续有效文件。"""
    if exists is None or absolute_path is None:
        from PySide6.QtCore import QFileInfo
        if exists is None: exists = QFileInfo.exists
        if absolute_path is None: absolute_path = lambda path: QFileInfo(path).absoluteFilePath()
    for candidate in resource_candidates(name, str(application_dir), str(current_dir)):
        if exists(candidate): return absolute_path(candidate)
    return ""


@dataclass(frozen=True)
class LoadOutcome:
    accepted: bool
    error: str = ""
    value: Any = None


class ResourceStageLoader:
    """六个lambda的编排。解析器显式注入；不以dict检查冒充原加载语义。

    必需加载器返回 LoadOutcome；可选加载器返回值不参与启动判定。
    加载器可持有原模块内部错误；这里只维护原 main 的共享 warning。
    """
    def __init__(self, *, resolve, load_contract, load_rules, load_readable_contract,
                 load_readable_rules, find_game_window):
        self.resolve = resolve
        self.load_contract = load_contract
        self.load_rules = load_rules
        self.load_readable_contract = load_readable_contract
        self.load_readable_rules = load_readable_rules
        self.find_game_window = find_game_window
        self.warning = ""
        self.paths = {}
        self.outcomes = {}
        self.game_window = None

    def _required(self, name, callback, missing):
        path = self.paths[name] = self.resolve(name)
        if not path:
            self.warning = missing
            self.outcomes[name] = LoadOutcome(False, missing)
            return False
        outcome = callback(path)
        if not isinstance(outcome, LoadOutcome):
            raise TypeError("必需资源加载回调须返回 LoadOutcome，不能猜测错误字段")
        self.outcomes[name] = outcome
        self.warning = "" if outcome.accepted else outcome.error
        return outcome.accepted

    def run(self, index: int):
        if index == 0:
            return self._required("contract.json", self.load_contract, MISSING_CONTRACT)
        if index == 1:
            return self._required("rules.json", self.load_rules, MISSING_RULES)
        if index == 2:
            for name, callback in (("contract_readable.json", self.load_readable_contract),
                                   ("rules_readable.json", self.load_readable_rules)):
                path = self.paths[name] = self.resolve(name)
                if path:
                    self.outcomes[name] = callback(path)
            return True
        if index == 4:
            self.game_window = self.find_game_window()
            self.warning = "" if self.game_window else MISSING_GAME
            return True
        if index in (3, 5, 6):
            # 3/5实际共用05e390恒true；6没有lambda。
            return True
        raise IndexError(index)


@dataclass
class StartupCallbacks:
    show_splash: Callable[[], None]
    process_events: Callable[[], None]
    record: Callable[[str], None]
    progress: Callable[[float, str], None]
    start_timer: Callable[[int], None]
    stop_timer: Callable[[], None]
    schedule: Callable[[int, Callable[[], None]], None]
    construct_main: Callable[[], Any]
    close_splash: Callable[[], None]
    delete_splash_later: Callable[[], None]
    show_main: Callable[[Any], None]
    auto_start: Callable[[Any], None]
    after_main: Callable[[Any], None]
    local_authorized: Callable[[], None] = lambda: None
    quit_application: Callable[[], None] | None = None


class StageTiming:
    """01a530/01ab00：开始覆盖同名时刻，完成删除；缺开始时耗时=-1。"""
    def __init__(self, record, clock_ms=None):
        self.record = record
        self.clock_ms = clock_ms or (lambda: int(time.perf_counter() * 1000))
        self.started = {}

    def begin(self, name):
        self.started[name] = self.clock_ms()
        self.record("▶ 开始：" + name)

    def end(self, name):
        start = self.started.pop(name, None)
        elapsed = -1 if start is None else self.clock_ms() - start
        self.record(f"■ 完成：{name}（耗时 {elapsed} ms）")


class StartupStages:
    """显示→显式本地测试授权→每tick一步→正常或1500ms提示后建主窗。

    返回bool不控制流程，遵守05d800共享warning条件；未知Python异常原样抛出。
    不安装计时器；callbacks由宿主接Qt或测试事件记录器。
    """
    def __init__(self, loader: ResourceStageLoader, callbacks: StartupCallbacks, *, auto_start=False, clock_ms=None):
        self.loader, self.callbacks = loader, callbacks
        self.auto_start_requested = bool(auto_start)
        self.timing = StageTiming(callbacks.record, clock_ms)
        self.index = 0
        self.phase = "created"
        self.main_window = None

    def show_splash(self):
        if self.phase != "created": raise RuntimeError("启动画面已显示")
        self.callbacks.show_splash()
        self.callbacks.process_events()
        self.callbacks.record(SPLASH_SHOWN)
        # processEvents可重入右上角取消回调，不能把cancelled覆盖成继续启动。
        if self.phase != "cancelled":
            self.phase = "awaiting_local_authorization"

    def accept_local_authorization(self):
        if self.phase != "awaiting_local_authorization": raise RuntimeError("不在本地测试授权等待阶段")
        self.callbacks.record(LOCAL_AUTHORIZATION)
        self.callbacks.local_authorized()
        self.phase = "loading"
        self.callbacks.start_timer(STAGE_INTERVAL_MS)

    def cancel_from_splash(self):
        """05f740关闭信号：记录后退出；不把用户关闭当成资源错误。"""
        if self.callbacks.quit_application is None:
            raise RuntimeError("关闭启动画面要求宿主提供 quit_application")
        self.callbacks.record(SPLASH_CANCELLED)
        self.phase = "cancelled"
        self.callbacks.quit_application()

    def tick(self):
        if self.phase != "loading": return
        cb = self.callbacks
        if self.index < len(STAGE_NAMES):
            name = STAGE_NAMES[self.index]
            cb.progress(self.index / len(STAGE_NAMES), name)
            self.timing.begin(name)
            self.loader.run(self.index)
            self.timing.end(name)
            if self.loader.warning and self.index >= 2:
                cb.stop_timer()
                cb.progress((self.index + 1) / len(STAGE_NAMES), "提示：" + self.loader.warning)
                cb.record("启动步骤提示（不中断启动）：" + self.loader.warning)
                self.phase = "warning_delay"
                cb.schedule(WARNING_DELAY_MS, self.complete_warning)
            else:
                self.index += 1
            return
        cb.stop_timer()
        cb.progress(1.0, BUILDING_TEXT)
        cb.process_events()
        if self.phase == "cancelled": return
        self._construct(MAIN_CONSTRUCTION)
        if self.phase == "cancelled": return
        self._show_main()
        cb.record(MAIN_SHOWN)
        if self.auto_start_requested:
            cb.schedule(AUTO_START_DELAY_MS, lambda: cb.auto_start(self.main_window))
        cb.after_main(self.main_window)

    def _construct(self, name):
        self.timing.begin(name)
        self.main_window = self.callbacks.construct_main()
        self.timing.end(name)

    def _show_main(self):
        self.callbacks.close_splash()
        self.callbacks.delete_splash_later()
        self.callbacks.show_main(self.main_window)
        self.phase = "shown"

    def complete_warning(self):
        if self.phase != "warning_delay": return
        if self.main_window is None:
            self._construct(WARNING_CONSTRUCTION)
        if self.phase == "cancelled": return
        self._show_main()
        # 05fd00没有MAIN_SHOWN日志、没有600ms --auto；仍执行05d290。
        self.callbacks.after_main(self.main_window)
