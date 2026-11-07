"""显式 QSettings 包装，默认工厂隔离原版配置；不在导入时访问注册表。"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Mapping

from .expressions import _trim

if TYPE_CHECKING:
    from .controller import SettingsChange

ORGANIZATION = "wowbuddy.cn"
ORIGINAL_APPLICATION = "WOW战斗助手"
TEST_APPLICATION = "WOW战斗助手-重建本地测试"


@dataclass(frozen=True)
class SpinSetting:
    minimum: int
    maximum: int
    step: int
    default: int

    def clamp(self, value: int) -> int:
        return max(self.minimum, min(self.maximum, value))


POLL_INTERVAL = SpinSetting(20, 500, 10, 25)
SEND_INTERVAL = SpinSetting(50, 5000, 50, 100)


@lru_cache(maxsize=1)
def _converter_type():
    from PySide6.QtCore import QObject, Property

    class Converter(QObject):
        """使用 Qt 元类型转换，避免 PySide QSettings.value(type=int) 的截断差异。"""
        def __init__(self):
            super().__init__()
            self.i, self.w, self.s, self.b, self.a = 0, 0, "", False, []

        integer = Property(int, lambda self: self.i, lambda self, value: setattr(self, "i", value))
        wide = Property("qlonglong", lambda self: self.w, lambda self, value: setattr(self, "w", value))
        string = Property(str, lambda self: self.s, lambda self, value: setattr(self, "s", value))
        boolean = Property(bool, lambda self: self.b, lambda self, value: setattr(self, "b", value))
        strings = Property("QStringList", lambda self: self.a, lambda self, value: setattr(self, "a", value))

    return Converter


def qt_convert(value: object, kind: str):
    """失败与 QVariant::toX(ok=nullptr) 一样返回该类型默认值。"""
    if kind not in {"integer", "wide", "string", "boolean", "strings"}:
        raise ValueError(f"未知 Qt 转换类型: {kind}")
    converter = _converter_type()()
    converter.setProperty(kind, value)
    return converter.property(kind)


@dataclass(frozen=True)
class StartupSnapshot:
    selection_settings: dict[str, str]
    switch_settings: dict[str, int]
    addon_last_dir: str
    addon_history: tuple[str, ...]
    update_auto_check: bool
    update_last_check_ms: int
    poll_interval_ms: int = POLL_INTERVAL.default
    send_interval_ms: int = SEND_INTERVAL.default

    def automatic_update_delay_ms(self, now_ms: int, *, selftest: bool = False) -> int | None:
        # 原构造：严格大于6小时，延迟4秒；这是程序更新，不是循环库同步。
        if self.update_auto_check and not selftest and now_ms - self.update_last_check_ms > 21_600_000:
            return 4000
        return None


class SettingsStore:
    """注入处于根 group 的 QSettings；不隐式替换调用方的存储位置。"""
    def __init__(self, qsettings):
        if qsettings.group():
            raise ValueError("QSettings 必须处于根 group")
        self.qsettings = qsettings

    def _read(self, key: str, default: object, kind: str):
        return qt_convert(self.qsettings.value(key, default), kind)

    def load_switches(self, existing: Mapping[str, int] | None = None) -> dict[str, int]:
        # 08dcb0 不 clear 原内存 hash；只遍历 switch 直接 childKeys。
        # 原版每次新建QSettings；常驻实例须先同步，才能看到其他进程修改。
        self.qsettings.sync()
        values = dict(existing or {})
        self.qsettings.beginGroup("switch")
        try:
            for key in self.qsettings.childKeys():
                values[key] = self._read(key, 0, "integer")
        finally:
            self.qsettings.endGroup()
        return values

    def snapshot(self) -> StartupSnapshot:
        selection = {key: self._read(key, "", "string") for key in self.qsettings.allKeys()
                     if key == "hub/selection" or key.startswith("hub/by-spec/")}
        selection.setdefault("hub/selection", "")
        return StartupSnapshot(selection, self.load_switches(),
            _trim(self._read("addon/lastDir", "", "string")),
            tuple(self._read("addon/history", [], "strings")),
            self._read("update/autoCheck", True, "boolean"),
            self._read("update/lastCheckMs", 0, "wide"))

    def load_spec_selection(self, spec_id: str) -> str:
        """092C90/095410身份改变时重新读取目标专精，不重读全局pending。"""
        self.qsettings.sync()
        return self._read(f"hub/by-spec/{spec_id}", "", "string")

    def apply_change(self, change: SettingsChange) -> None:
        """controller.persist 回调。先核验全部输入，按写入→删除顺序应用。"""
        for key, value in change.selection.items():
            if not (key == "hub/selection" or key.startswith("hub/by-spec/")) or not isinstance(value, str):
                raise ValueError("selection 只接受 hub/selection 与 hub/by-spec/* 字符串")
        for key, value in change.switches.items():
            self._switch_key(key)
            if type(value) is not int or not -(2**31) <= value < 2**31:
                raise ValueError("switch 值必须是 int32，不能自动按布尔或浮点转换")
        for key in change.removed_switches:
            self._switch_key(key)
        for key, value in change.selection.items():
            self.qsettings.setValue(key, value)
        for key, value in change.switches.items():
            self.qsettings.setValue("switch/" + key, value)
        for key in change.removed_switches:
            self.qsettings.remove("switch/" + key)

    @staticmethod
    def _switch_key(key: str) -> None:
        if not isinstance(key, str) or not key or key.startswith("switch/"):
            raise ValueError("switch key 应为非空且不含 switch/ 前缀的内部 key")

    def save_addon_dir(self, directory: str) -> None:
        """09fe00：非空路径 cleanPath，历史精确去重、置顶、最多8条。"""
        if not _trim(directory):
            return
        from PySide6.QtCore import QDir
        path = QDir.cleanPath(directory)
        history = self._read("addon/history", [], "strings")
        history = [path] + [item for item in history if item != path]
        self.qsettings.setValue("addon/lastDir", path)
        self.qsettings.setValue("addon/history", history[:8])

    def save_auto_check(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是 bool")
        self.qsettings.setValue("update/autoCheck", enabled)

    def clear_addon_history(self) -> None:
        self.qsettings.remove("addon/history")

    def save_last_check_ms(self, timestamp_ms: int) -> None:
        if type(timestamp_ms) is not int or not -(2**63) <= timestamp_ms < 2**63:
            raise ValueError("时间戳必须是 int64")
        self.qsettings.setValue("update/lastCheckMs", timestamp_ms)

    def sync(self) -> None:
        """显式落盘并报告失败；原版的临时 QSettings 在析构时隐式提交。"""
        from PySide6.QtCore import QSettings
        self.qsettings.sync()
        if self.qsettings.status() != QSettings.Status.NoError:
            raise OSError(f"QSettings 同步失败: {self.qsettings.status()}")


def open_test_settings() -> SettingsStore:
    """本地重建差异：独立应用名，保持原版 registry 配置不被覆盖。"""
    from PySide6.QtCore import QSettings
    return SettingsStore(QSettings(ORGANIZATION, TEST_APPLICATION))


def open_ini_settings(path: str) -> SettingsStore:
    from PySide6.QtCore import QSettings
    return SettingsStore(QSettings(path, QSettings.Format.IniFormat))
