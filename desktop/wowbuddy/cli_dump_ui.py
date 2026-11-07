"""057AC0 的 --dump-ui 延迟执行体及 08A630 文字报告，不运行原 EXE。"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import QCoreApplication, QTimer, Qt, qWarning, QJsonDocument
from PySide6.QtWidgets import QWidget, QPushButton, QCheckBox, QLabel, QLineEdit

from .candidates import Rule, parse_rules
from .expressions import _int, _string
from .field_cell import FieldCell
from .rotation_selection import Profile


@dataclass(frozen=True)
class DumpUiOptions:
    rotations_path: str = ""
    rotation_key: str = ""
    specs: tuple[str, ...] = ()
    talent: str = "10/0/0"
    toggle_showall: bool = False

    @classmethod
    def parse(cls, arguments: Sequence[str]) -> "DumpUiOptions":
        rotations, rotation, talent = "", "", "10/0/0"
        specs = []
        for arg in arguments:
            if arg.startswith("--rotations="):
                rotations = arg[len("--rotations="):]
            elif arg.startswith("--rotation="):
                rotation = arg[len("--rotation="):]
            elif arg.startswith("--spec="):
                specs.append(arg[len("--spec="):])
            elif arg.startswith("--talent="):
                talent = arg[len("--talent="):]
        return cls(rotations, rotation, tuple(specs), talent, "--toggle-showall" in arguments)


@dataclass(frozen=True)
class DiagnosticRotation:
    spec_id: str
    spec_name: str
    sub_key: str
    profile_name: str
    rules: tuple[Rule, ...]

    @property
    def engine_name(self) -> str:
        return f"{self.spec_name} · {self.profile_name}"


def load_diagnostic_rotation(options: DumpUiOptions, *, read_bytes=Path.read_bytes,
                             warning: Callable[[str], None] = qWarning) -> DiagnosticRotation | None:
    """不要求 hub format；只匹配首个 specId/subKey/profileName，空 rules 也可套用。"""
    if not options.rotations_path or not options.rotation_key:
        return None
    parts = options.rotation_key.split("|")
    if len(parts) < 3:
        warning("--rotation 需要 specId|subKey|方案名")
        return None
    try:
        payload = read_bytes(Path(options.rotations_path))
    except OSError:
        warning(f"打不开循环库快照：{options.rotations_path}")
        return None
    # 057AC0 使用 Qt fromJson/object；保持其字节编码和数字接受性。
    document = QJsonDocument.fromJson(payload)
    if not document.isObject():
        return None
    # 不经 toVariant，避免 PySide 丢失孤立 UTF-16 代理字符。
    obj = json.loads(bytes(document.toJson(QJsonDocument.Compact)))
    entries = obj.get("rotations", []) if isinstance(obj, dict) else []
    if not isinstance(entries, list):
        return None
    name = "|".join(parts[2:])
    for raw in entries:
        entry = raw if isinstance(raw, dict) else {}
        if (str(_int(entry.get("specId"))) == parts[0]
                and _string(entry.get("subKey")) == parts[1]
                and _string(entry.get("profileName")) == name):
            return DiagnosticRotation(parts[0], _string(entry.get("specName")), parts[1],
                                      name, parse_rules(entry.get("rules")))
    return None


def _left_utf16(text: str, units: int) -> str:
    return text.encode("utf-16-le", "surrogatepass")[:units * 2].decode("utf-16-le", "surrogatepass")


def widget_report(window: QWidget, spec_id: str) -> str:
    """递归 QWidget，保持 Qt findChildren 顺序；min 为 minimumSizeHint 而非 minimumSize。"""
    lines = [f"window={window.width()}x{window.height()}  spec={spec_id}"]
    for widget in window.findChildren(QWidget):
        if isinstance(widget, (QPushButton, QCheckBox)):
            text = widget.text()
        elif isinstance(widget, QLabel):
            text = _left_utf16(widget.text(), 28)
        elif isinstance(widget, QLineEdit):
            text = _left_utf16(widget.text(), 120)
        else:
            text = ""
        hint, minimum = widget.sizeHint(), widget.minimumSizeHint()
        lines.append(
            f"{widget.metaObject().className()}#{widget.objectName()} "
            f"@({widget.x()},{widget.y()}) {widget.width()}x{widget.height()} "
            f"vis={int(widget.isVisible())} hint={hint.width()}x{hint.height()} "
            f"min={minimum.width()}x{minimum.height()}  {text}")
    return "\n".join(lines)


def showall_report(window: QWidget, checkbox: QCheckBox | None, enabled: bool,
                   current_field_cells: Callable[[], Sequence[FieldCell]], *,
                   warning: Callable[[str], None] = qWarning) -> str:
    # 0x140088990：切换前统计、同步 setChecked、区分本轮与旧格并输出警告。
    if checkbox is None:
        return "--toggle-showall：chkShowAll_ 为空，跳过\n"
    before = sum(not widget.isHidden() for widget in window.findChildren(FieldCell))
    checkbox.setChecked(enabled)
    # 立即统计；不 processEvents/deleteLater，保留旧控件尚未析构时的遗留数量。
    all_cells = window.findChildren(FieldCell)
    current = tuple(current_field_cells())
    matched = [cell for cell in all_cells if cell in current]
    stale = [cell for cell in all_cells if cell not in current]
    hidden = [cell for cell in stale if cell.isHidden()]
    explicit = sum(cell.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide) for cell in hidden)
    text = (f"--toggle-showall {'on' if enabled else 'off'}：本轮 {len(matched)} 格（期望 {len(current)}）；"
            f"上一轮遗留 {len(stale)} 格（已隐藏 {len(hidden)}，其中显式 hide 置位 {explicit}；"
            f"仍在显示 {len(stale) - len(hidden)}）；findChildren 共 {len(all_cells)}；"
            f"进入时在显示 {before} 格（为 0 = 窗口未过 show **或字段格已按需求隐藏**，"
            "此时只看「显式 hide 置位」）")
    warning(text)
    return text + "\n"


def _write_report(path: Path, text: str) -> bool:
    try:
        # QFile WriteOnly|Truncate，不加 BOM、Text 模式或结尾换行。
        normalized = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
        path.write_bytes(normalized.encode("utf-8"))
        return True
    except OSError:
        return False


class DumpUiRunner:
    """外层在窗口 show 后2600ms调用 start；这里只管理原版内层600ms。"""
    def __init__(self, window: QWidget, arguments: DumpUiOptions | Sequence[str],
                 output_dir: Path, *, apply_rotation: Callable[[DiagnosticRotation], None],
                 apply_spec: Callable[[str, str], None], spec_id: Callable[[], str],
                 current_field_cells: Callable[[], Sequence[FieldCell]],
                 show_all_checkbox: QCheckBox | None = None,
                 warning: Callable[[str], None] = qWarning,
                 schedule: Callable[[int, Callable[[], None]], None] | None = None,
                 read_bytes=Path.read_bytes, write_report=_write_report):
        self.window = window
        self.options = arguments if isinstance(arguments, DumpUiOptions) else DumpUiOptions.parse(arguments)
        self.output_dir = Path(output_dir)
        self.apply_rotation, self.apply_spec, self.spec_id = apply_rotation, apply_spec, spec_id
        self.current_field_cells, self.show_all_checkbox = current_field_cells, show_all_checkbox
        self.warning, self.read_bytes, self.write_report = warning, read_bytes, write_report
        self.schedule = schedule
        self.timer = None
        self.report_written: bool | None = None
        self.showall_written: bool | None = None

    def start(self) -> None:
        rotation = load_diagnostic_rotation(self.options, read_bytes=self.read_bytes, warning=self.warning)
        if rotation is not None:
            self.apply_rotation(rotation)
            self.warning(f"--rotation 已套用：{rotation.spec_name} / {rotation.profile_name}")
        for spec in self.options.specs:
            if spec:
                self.apply_spec(spec, self.options.talent)
        if self.options.toggle_showall:
            self.window.show()
            QCoreApplication.processEvents()
            text = "".join(showall_report(self.window, self.show_all_checkbox, state,
                                         self.current_field_cells, warning=self.warning)
                           for state in (True, False))
            self.showall_written = self.write_report(self.output_dir / "_showall.txt", text)
        if self.schedule is not None:
            self.schedule(600, self.write_ui)
        else:
            self.timer = QTimer(self.window)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.write_ui)
            self.timer.start(600)

    def write_ui(self) -> None:
        self.report_written = self.write_report(self.output_dir / "_ui.txt",
                                                 widget_report(self.window, self.spec_id()))

    def close(self) -> None:
        if self.timer is not None:
            self.timer.stop()


def make_runner_for_window(window, options: DumpUiOptions | Sequence[str], *,
                           application_dir: Path, **runner_options) -> DumpUiRunner:
    """显式接现有 AssistantWindow；保留列表选择，按09AA10持久化阈值迁移。"""
    controller = window.controller

    def apply_rotation(rotation: DiagnosticRotation) -> None:
        profile = Profile(0, int(rotation.spec_id), rotation.spec_name, rotation.sub_key,
                          rotation.profile_name, "", "", "", "", rotation.rules)
        # 对应引擎临时外部方案；不调用 select/update_hub，不改 combo/pending/current key。
        controller.selection = replace(controller.selection, active_profile=profile)

    def apply_spec(spec: str, talent: str) -> None:
        token = window.pipeline.engine.roles.get(spec, {}).get("token", "")
        controller.fields[token + "_talents" if token else ""] = talent
        controller.spec_id = spec
        name = window.assets.contract.get("classNames", {}).get(spec, "") or spec
        window.ui.spec_label.setText(f"专精：{name}")
        # 09AA10 的迁移/初始化照常通过 controller.persist 写入当前设置存储。
        controller.refresh_thresholds()
        window._render_thresholds()

    return DumpUiRunner(window, options, application_dir, apply_rotation=apply_rotation,
                        apply_spec=apply_spec, spec_id=lambda: controller.spec_id,
                        current_field_cells=lambda: window._field_widgets,
                        show_all_checkbox=window.ui.show_all_check, **runner_options)
