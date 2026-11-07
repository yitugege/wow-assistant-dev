"""旧条定位、pitch 校正和众数采样的纯 Python 重建。

依据 FUN_14001ead0/01f740/0207c0/0201b0/01f1d0。
只处理调用者提供的 RGB 图像，不调用屏幕、窗口或键盘 API。
"""

from collections.abc import Sequence
from dataclasses import dataclass
import math


def _packed(pixel: int | Sequence[int]) -> int:
    if isinstance(pixel, int) and not isinstance(pixel, bool) and 0 <= pixel <= 0xFFFFFF:
        return pixel
    if isinstance(pixel, Sequence) and not isinstance(pixel, (str, bytes)) and len(pixel) == 3:
        if all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in pixel):
            return (pixel[0] << 16) | (pixel[1] << 8) | pixel[2]
    raise ValueError("像素须为24位RGB整数或三个0..255整数分量")


class RGBImage:
    """矩形 RGB 图像；接受逐行像素，也可用 from_flat 构造。"""

    def __init__(self, rows: Sequence[Sequence[int | Sequence[int]]]):
        width = len(rows[0]) if len(rows) else 0
        if any(len(row) != width for row in rows):
            raise ValueError("像素行长度不同")
        self.rows = tuple(tuple(_packed(pixel) for pixel in row) for row in rows)
        self.width = width
        self.height = len(self.rows)

    @classmethod
    def from_flat(cls, width: int, height: int, pixels: Sequence[int | Sequence[int]]):
        if (not isinstance(width, int) or not isinstance(height, int)
                or width < 0 or height < 0 or len(pixels) != width * height):
            raise ValueError("图像尺寸与扁平像素数组不匹配")
        return cls([pixels[y * width:(y + 1) * width] for y in range(height)])

    def pixel(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("采样坐标超出图像")
        return self.rows[y][x]


@dataclass(frozen=True, slots=True)
class BarGeometry:
    origin_x: float
    origin_y: float
    pitch: float
    cell_width: float
    scale: float
    anchor_x: int
    anchor_y: int


def nearbyint(value: float) -> int:
    """原版默认浮点舍入模式 FE_TONEAREST：最近整数，半整数取偶数。"""
    return round(value)


def lround(value: float) -> int:
    """原生 lround：半整数远离零；用于整条垂直边界检查。"""
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def find_fiducial(image: RGBImage, scan_width: int = 24, min_run: int = 2) -> tuple[int, int] | None:
    """FUN_14001f740：左侧扫描首个横向连续洋红段的最左点。"""
    for y, row in enumerate(image.rows):
        run = 0
        for x in range(min(image.width, max(scan_width, 0))):
            run = run + 1 if row[x] == 0xFF00FF else 0
            if run >= min_run:
                return x - run + 1, y
    return None


def locate_old_bar(image: RGBImage) -> BarGeometry | None:
    """FUN_14001ead0：以逻辑(4,128)洋红基准点恢复旧条粗几何。"""
    found = find_fiducial(image)
    if found is None or found[1] <= 0:
        return None
    x, y = found
    scale = y * 0.0078125
    pitch = scale * 4.0
    return BarGeometry(max(x - pitch, 0.0), 0.0, pitch, pitch, scale, x, y)


def refine_pitch(image: RGBImage, sample_x: int, coarse_pitch: float, count: int) -> float:
    """FUN_1400207c0：按颜色边界命中数、距离惩罚校正pitch。

    粗搜初值±1.2%（60×0.02%），细搜粗搜最优值±0.02%（10×0.002%）。
    同分时保留先前候选，不用真值、字段语义或特殊测试数据修正结果。
    """
    if (image.width == 0 or image.height <= 1 or not math.isfinite(coarse_pitch)
            or coarse_pitch <= 0 or count <= 0 or not 0 <= sample_x < image.width):
        return coarse_pitch
    max_y = image.height - 1
    boundaries_to_score = max(count, 120)
    while boundaries_to_score > 40 and nearbyint(boundaries_to_score * coarse_pitch) > max_y:
        boundaries_to_score -= 1
    if boundaries_to_score < 40:
        return coarse_pitch
    column = [row[sample_x] for row in image.rows]
    boundaries = {y for y in range(1, image.height) if column[y] != column[y - 1]}
    if len(boundaries) < 4:
        return coarse_pitch
    # 与原版双向扫相同；开头缺少左边界时用 -(height+1)。
    sentinel = image.height + 1
    distances = [sentinel] * image.height
    previous = -sentinel
    for y in range(image.height):
        if y in boundaries:
            previous = y
        distances[y] = y - previous
    following = sentinel
    for y in range(max_y, -1, -1):
        if y in boundaries:
            following = y
        if following < sentinel and following - y < distances[y]:
            distances[y] = following - y

    def score(pitch: float) -> tuple[int, int]:
        hits = penalty = 0
        for i in range(1, boundaries_to_score + 1):
            y = nearbyint(i * pitch)
            if not 0 <= y <= max_y:
                penalty += 6
            elif distances[y] == 0:
                hits += 1
            else:
                penalty += min(distances[y], 6)
        return hits, -penalty

    best_pitch = coarse_pitch
    best_score = score(coarse_pitch)
    baseline_hits = best_score[0]
    for step in range(1, 61):
        for candidate in ((step * 0.0002 + 1.0) * coarse_pitch,
                          (1.0 - step * 0.0002) * coarse_pitch):
            candidate_score = score(candidate)
            if candidate_score > best_score:
                best_pitch, best_score = candidate, candidate_score
    fine_center = best_pitch
    for step in range(1, 11):
        for candidate in ((step * 0.00002 + 1.0) * fine_center,
                          (1.0 - step * 0.00002) * fine_center):
            candidate_score = score(candidate)
            if candidate_score > best_score:
                best_pitch, best_score = candidate, candidate_score
    # 021025–021073：反编译错误void返回类型会丢掉这段返回值选择。
    # 只有偏移不超过1.2%、至少多命中2条边界且命中率>=25%才接受。
    if (abs(best_pitch - coarse_pitch) / coarse_pitch > 0.012
            or best_score[0] < baseline_hits + 2
            or best_score[0] < boundaries_to_score * 0.25):
        return coarse_pitch
    return best_pitch


def sample_cell(image: RGBImage, sample_x: int, start_y: int, end_y: int) -> int:
    """FUN_14001f1d0：排除格边，按中部向外枚举的众数取样。"""
    if image.height == 0 or not 0 <= sample_x < image.width:
        raise ValueError("图像为空或x超出图像")
    clamp = lambda y: max(0, min(image.height - 1, y))
    low = clamp(start_y + 1)
    high = clamp(end_y - 2)
    if high < low:
        # 对负数必须截断到零，不能使用Python负数整除。
        return image.pixel(sample_x, clamp(math.trunc((start_y + end_y) / 2)))
    left = (low + high) // 2
    right = left + 1
    frequencies: dict[int, int] = {}
    while left >= low or right <= high:
        if right <= high:
            color = image.pixel(sample_x, right)
            frequencies[color] = frequencies.get(color, 0) + 1
            right += 1
        if left >= low:
            color = image.pixel(sample_x, left)
            frequencies[color] = frequencies.get(color, 0) + 1
            left -= 1
    # dict顺序保留首次遇到的颜色，等票时不替换。
    return max(frequencies, key=frequencies.get)


def sample_old_bar(image: RGBImage, geometry: BarGeometry | None, count: int) -> list[int]:
    """FUN_1400201b0：验证粗几何范围，校正pitch，再连续采样count格。"""
    if image.width == 0 or image.height == 0 or geometry is None or count <= 0:
        return []
    g = geometry
    if not all(math.isfinite(n) for n in (g.origin_x, g.origin_y, g.pitch, g.cell_width)):
        raise ValueError("几何参数必须为有限数")
    bottom = lround((count - 1) * g.pitch + g.origin_y + g.pitch)
    if (g.origin_y < 0 or bottom > image.height or g.origin_x < 0
            or g.cell_width + g.origin_x > image.width + 0.5):
        return []
    x = max(0, min(image.width - 1, nearbyint(g.cell_width * 0.5 + g.origin_x)))
    pitch = refine_pitch(image, x, g.pitch, count)
    y_origin = nearbyint(g.origin_y)
    return [sample_cell(image, x, nearbyint(i * pitch) + y_origin,
                        nearbyint((i + 1) * pitch) + y_origin) for i in range(count)]
