"""复刻原生selftest合成图像，并检查定位/采样边界。"""

from dataclasses import replace
import unittest

from wowbuddy.pixel_geometry import (
    RGBImage, BarGeometry, nearbyint, lround, find_fiducial, locate_old_bar,
    refine_pitch, sample_cell, sample_old_bar,
)


def native_selftest_image(scale):
    # 原生大函数汇编 0x14007388A..0x140073B3D，见证据文档。
    width = 24
    height = nearbyint(732.0 * scale) + 16
    rows = [[0x0D0D0D] * width for _ in range(height)]
    colors = (0x00FF00, 0x333333, 0xFF0000)
    expected = []
    cell_width = max(1, nearbyint(4.0 * scale))
    for i in range(183):
        color = colors[(3 + i * 7) % 3]
        expected.append(color)
        for y in range(nearbyint(i * 4.0 * scale), nearbyint((i + 1) * 4.0 * scale)):
            for x in range(cell_width):
                rows[y][x] = color
    for y in range(nearbyint(128.0 * scale), nearbyint(132.0 * scale)):
        for x in range(nearbyint(4.0 * scale), nearbyint(8.0 * scale)):
            rows[y][x] = 0xFF00FF
    return RGBImage(rows), expected


class PixelGeometryTests(unittest.TestCase):
    def test_original_six_scale_baseline_replay(self):
        # locked值来自实际原版--selftest输出，仅保留原版显示的5位精度。
        fixtures = ((1.0, 4.0, 4.0), (1.125, 4.5, 4.5),
                    (1.2, 4.8125, 4.79999), (1.25, 5.0, 5.0),
                    (1.3333, 5.34375, 5.33413), (2.0, 8.0, 8.0))
        for scale, coarse, native_locked in fixtures:
            with self.subTest(scale=scale):
                image, expected = native_selftest_image(scale)
                geometry = locate_old_bar(image)
                self.assertIsNotNone(geometry)
                self.assertEqual(geometry.pitch, coarse)
                x = min(image.width - 1, max(0, nearbyint(geometry.origin_x + geometry.cell_width * 0.5)))
                self.assertEqual(f"{refine_pitch(image, x, coarse, 183):.5f}", f"{native_locked:.5f}")
                self.assertEqual(sample_old_bar(image, geometry, 183), expected)

    def test_rounding_distinction(self):
        self.assertEqual([nearbyint(x) for x in (-2.5, -1.5, .5, 1.5, 2.5)], [-2, -2, 0, 2, 2])
        self.assertEqual([lround(x) for x in (-2.5, -1.5, .5, 1.5, 2.5)], [-3, -2, 1, 2, 3])

    def test_first_exact_magenta_run_and_scan_limit(self):
        rows = [[0] * 30 for _ in range(130)]
        rows[2][0] = 0xFF00FF  # 单像素不够。
        rows[3][2:4] = [0xFE00FF] * 2  # 没有颜色容差。
        rows[4][24:26] = [0xFF00FF] * 2  # 超过左侧24像素扫描宽。
        rows[128][4:8] = [0xFF00FF] * 4
        image = RGBImage(rows)
        self.assertEqual(find_fiducial(image), (4, 128))
        self.assertEqual(locate_old_bar(image), BarGeometry(0, 0, 4, 4, 1, 4, 128))

    def test_zero_row_marker_rejected(self):
        image = RGBImage([[0xFF00FF, 0xFF00FF], [0, 0]])
        self.assertEqual(find_fiducial(image), (0, 0))
        self.assertIsNone(locate_old_bar(image))

    def test_cell_mode_tie_order_and_border_exclusion(self):
        # 内部为 y1..4；枚举 y3,y2,y4,y1，A/B平票保留y3的A。
        image = RGBImage([[0xFFFFFF], [2], [2], [1], [1], [0xFFFFFF]])
        self.assertEqual(sample_cell(image, 0, 0, 6), 1)
        image = RGBImage([[0xFFFFFF], [2], [2], [1], [2], [0xFFFFFF]])
        self.assertEqual(sample_cell(image, 0, 0, 6), 2)

    def test_small_cell_falls_back_to_center(self):
        image = RGBImage([[1], [2], [3]])
        self.assertEqual(sample_cell(image, 0, 0, 2), 2)
        self.assertEqual(sample_cell(image, 0, -3, -1), 1)

    def test_refine_without_enough_boundaries(self):
        image = RGBImage([[0] for _ in range(300)])
        self.assertEqual(refine_pitch(image, 0, 4.05, 50), 4.05)
        self.assertEqual(refine_pitch(image, -1, 4.05, 50), 4.05)
        self.assertEqual(refine_pitch(image, 0, 4.05, 0), 4.05)

    def test_sparse_long_strip_does_not_drift_into_background(self):
        # 原Lua布局：字段每4行、末尾背景。只有身份/版本造成少量边界，
        # 不能把微小评分改善当成足够证据，接受偏移后会丢最后一格。
        for count,spec in ((183,1484),(171,1487)):
            colors=[0xffffff]*count;colors[6]=spec;colors[18]=10576675
            rows=[[color]*4+[0x0d0d0d]*20 for color in colors for _ in range(4)]
            rows.extend([[0x0d0d0d]*24 for _ in range(24)])
            for y in range(128,132):rows[y][4:8]=[0xff00ff]*4
            image=RGBImage(rows)
            self.assertEqual(refine_pitch(image,2,4,count),4)
            self.assertEqual(sample_old_bar(image,locate_old_bar(image),count),colors)

    def test_whole_strip_bounds(self):
        image, _ = native_selftest_image(1.0)
        geometry = locate_old_bar(image)
        self.assertEqual(sample_old_bar(image, replace(geometry, origin_x=-.1), 183), [])
        self.assertEqual(sample_old_bar(image, replace(geometry, origin_y=-.1), 183), [])
        self.assertEqual(sample_old_bar(image, replace(geometry, cell_width=24.6), 183), [])
        self.assertEqual(sample_old_bar(image, geometry, 200), [])
        self.assertEqual(sample_old_bar(image, None, 183), [])

    def test_flat_rgb_and_malformed_inputs(self):
        image = RGBImage.from_flat(2, 1, [(1, 2, 3), 0xFF00FF])
        self.assertEqual(image.pixel(0, 0), 0x010203)
        self.assertEqual(image.pixel(1, 0), 0xFF00FF)
        for rows in ([[1, 2], [1]], [[0x1000000]], [[True]], [[(1, 2, 256)]]):
            with self.assertRaises(ValueError):
                RGBImage(rows)
        with self.assertRaises(ValueError):
            RGBImage.from_flat(2, 3, [0] * 5)
        self.assertIsNone(locate_old_bar(RGBImage([])))
        self.assertEqual(sample_old_bar(RGBImage([]), None, 1), [])


if __name__ == "__main__":
    unittest.main()
