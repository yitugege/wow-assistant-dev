"""062CD0 的完整六缩放几何子组；不是全部 --selftest。"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import struct
from typing import Callable, Sequence
from .pixel_geometry import RGBImage, locate_old_bar, sample_old_bar, refine_pitch
from .selftest_inputs_geometry import build_geometry_inputs


def render_argb(case: dict) -> tuple[tuple[int, ...], ...]:
    image = case["image"]
    rows = [[image["fill_argb"]] * image["width"] for _ in range(image["height"])]
    # 对应原QImage.fill→逐格setPixel→洋红基准setPixel；rect使用半开区间。
    for rectangle in [*case["cells"], case["marker"]]:
        x0,y0,x1,y1 = rectangle["rect"]
        if not (0 <= x0 <= x1 <= image["width"] and 0 <= y0 <= y1 <= image["height"]):
            raise ValueError("构图矩形越界")
        color = rectangle["argb"]
        if type(color) is not int or not 0 <= color <= 0xFFFFFFFF:
            raise ValueError("非法ARGB输入")
        for y in range(y0,y1):
            rows[y][x0:x1] = [color] * (x1-x0)
    return tuple(tuple(row) for row in rows)


def render_rgb(case: dict) -> RGBImage:
    pixels = render_argb(case)
    if any(color >> 24 != 255 for row in pixels for color in row):
        raise ValueError("当前RGB适配仅允许原自测全部不透明ARGB输入")
    return RGBImage([[color & 0xFFFFFF for color in row] for row in pixels])


@dataclass(frozen=True)
class SampleAssertion:
    wrong_rows: int
    first_wrong_index: int | None
    considered_rows: int
    actual_length: int

    @property
    def passed(self) -> bool:
        return self.wrong_rows == 0


def assert_argb_samples(expected: Sequence[int], actual: Sequence[int]) -> SampleAssertion:
    """073C83–073CB0：逐个完整uint32比，缺失算错，额外样本不参与。"""
    if len(expected) != 183:
        raise ValueError("原断言固定183行")
    wrong = [i for i in range(183) if i >= len(actual) or actual[i] != expected[i]]
    return SampleAssertion(len(wrong), wrong[0] if wrong else None, 183, len(actual))


def _qt_substitute(template: str, *values: object) -> str:
    # 本组格式最多8个占位符且替换值不含占位符，按编号下降避免%1碰到%10。
    for i in range(len(values), 0, -1):
        template = template.replace(f"%{i}", str(values[i-1]))
    return template


def replay_group(manifest: dict, *, locate: Callable = locate_old_bar,
                 sample: Callable = sample_old_bar, refine: Callable = refine_pitch) -> dict:
    """回调接纯RGBImage。返回静态原断言对重建实现的结果，不称原生动态观测。"""
    templates = manifest["report_templates"]
    lines = [templates["header"]["text"]]
    results = []
    passed = 0
    for case in manifest["cases"]:
        image = render_rgb(case)
        scale = struct.unpack("<d", bytes.fromhex(case["scale_ieee754_le"]))[0]
        geometry = locate(image)
        if geometry is None:
            line = _qt_substitute(templates["no_marker"]["text"], f"{scale:.6g}")
            results.append({"id": case["id"], "status": "no_marker", "passed": False, "line": line})
            lines.append(line)
            continue
        colors = sample(image, geometry, 183)
        # 原QImage Format_RGB32和本JSON的alpha全为FF；还原完整ARGB后执行原断言。
        argb = [value | 0xFF000000 for value in colors]
        assertion = assert_argb_samples(case["expected_argb"], argb)
        x = max(0, min(23, round(geometry.origin_x + geometry.cell_width * 0.5)))
        locked = refine(image, x, geometry.pitch, 183)
        passed += int(assertion.passed)
        suffix = "" if assertion.passed else _qt_substitute(
            templates["first_wrong"]["text"], assertion.first_wrong_index + 1)
        line = _qt_substitute(templates["case"]["text"],
            templates["pass_symbol"]["text"] if assertion.passed else templates["fail_symbol"]["text"],
            f"{scale:.4f}", f"{geometry.pitch:.5f}", f"{locked:.5f}", f"{scale * 4.0:.5f}",
            assertion.wrong_rows, 183, suffix)
        lines.append(line)
        results.append({"id": case["id"], "status": "sampled", "passed": assertion.passed,
                        "geometry": asdict(geometry), "refine_x": x, "diagnostic_locked_pitch": locked,
                        "assertion": asdict(assertion), "sampled_argb": argb, "line": line})
    lines.append(_qt_substitute(templates["summary"]["text"], passed, 6))
    if passed != 6:
        lines.append(templates["failure_warning"]["text"])
    return {"source_kind": "offline-reconstruction-replay-of-static-native-inputs",
            "pass_count": passed, "case_count": 6, "results": results,
            "report_text": "\n".join(lines),
            "native_dynamic_execution": False,
            "native_function_normal_return": 0}


@dataclass(frozen=True)
class GeometrySelftestResult:
    text: str
    passed: int
    total: int
    cases: tuple[dict, ...]


def run_geometry_selftest(*, inputs=None, locate=locate_old_bar,
                          sample=sample_old_bar, refine=refine_pitch):
    """纯离屏执行。text从组标题起；组间两个LF交由总报告拼接。"""
    result = replay_group(build_geometry_inputs() if inputs is None else inputs,
                          locate=locate, sample=sample, refine=refine)
    text = result['report_text']
    if text.startswith('\n\n'):
        text = text[2:]
    return GeometrySelftestResult(text, result['pass_count'], result['case_count'],
                                 tuple(result['results']))
