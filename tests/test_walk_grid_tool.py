"""地图格子生成工具（tools/walkgrid、tools/build_walk_grid.py）的合成数据测试；不读游戏文件。"""
import math
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'desktop')]

try:
    import numpy as np
except ImportError:     # numpy 只是生成工具的依赖（requirements-dev.txt）
    np = None

from walkgrid.casc import blte, jenkins_hashlittle2, name_hash  # noqa: E402
import build_walk_grid  # noqa: E402


class CascTests(unittest.TestCase):
    def test_jenkins_reference_vector(self):
        # lookup3.c 的自检向量
        self.assertEqual(jenkins_hashlittle2(b'Four score and seven years ago'), (0x17770551, 0xCE7226E6))
        self.assertEqual(jenkins_hashlittle2(b''), (0xDEADBEEF, 0xDEADBEEF))

    def test_name_hash_normalizes_case_and_separators(self):
        self.assertEqual(name_hash('world/maps/azeroth/azeroth.wdt'), name_hash('WORLD\\MAPS\\AZEROTH\\AZEROTH.WDT'))

    def test_blte_plain_and_zlib_chunks(self):
        self.assertEqual(blte(b'BLTE' + struct.pack('>I', 0) + b'Nhello'), b'hello')
        first, second = b'N' + b'abc', b'Z' + zlib.compress(b'defg')
        header = struct.pack('>I', 2)[1:]
        table = struct.pack('>II', len(first), 3) + b'\0' * 16 + struct.pack('>II', len(second), 4) + b'\0' * 16
        header_size = 8 + 4 + len(table)
        data = b'BLTE' + struct.pack('>I', header_size) + b'\x0f' + header + table + first + second
        self.assertEqual(blte(data), b'abcdefg')


class CalibrationTests(unittest.TestCase):
    def test_two_points_solve_redridge_bounds(self):
        bounds = build_walk_grid.solve_bounds([
            (-9089.2998046875, -2407.8000488281, 0.33470886945724, 0.3551858663559),
            (-9233.2001953125, -2190.4001464844, 0.23454654216766, 0.45459395647049)])
        self.assertAlmostEqual(bounds['width'], 2170.5, delta=1)
        self.assertAlmostEqual(bounds['height'], 1447.6, delta=1)
        self.assertAlmostEqual(bounds['left'], -1681.3, delta=0.5)
        self.assertAlmostEqual(bounds['top'], -8575.1, delta=0.5)
        self.assertLess(bounds['residual'], 0.01)

    def test_single_point_needs_yards(self):
        point = (-9089.3, -2407.8, 0.3347, 0.3552)
        with self.assertRaises(ValueError):
            build_walk_grid.solve_bounds([point])
        bounds = build_walk_grid.solve_bounds([point], (2171, 1448))
        self.assertAlmostEqual(bounds['left'], -2407.8 + 0.3347 * 2171, places=3)

    def test_walked_tracks_and_check(self):
        with TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.ini'
            settings.write_text('patrolRoute="WBDLOOP1|1433|2171.0,1448.0|1000,1000|2000,1000"\n'
                                'other="WBDROUTE1|1429|100,100|200,200"\n', encoding='utf-8')
            tracks = build_walk_grid.walked_tracks(settings, 1433)
        self.assertEqual(tracks, [[(10.0, 10.0), (20.0, 10.0)]])
        if np is None:
            return
        cost = np.full((100, 100), 10, np.uint8)
        cost[10, 15] = 0
        check = build_walk_grid.track_check(cost, tracks)
        self.assertEqual(check['cells'], 11)
        self.assertAlmostEqual(check['blocked'], 1 / 11)


@unittest.skipIf(np is None, '没有 numpy（只在生成工具中使用）')
class TerrainTests(unittest.TestCase):
    def test_interpolation_hits_vertices_and_is_continuous(self):
        from walkgrid.terrain import interpolate, split_mcvt
        heights = [float(i) for i in range(145)]
        outer, inner = split_mcvt(heights)
        self.assertEqual(outer[0, 0], 0)
        self.assertEqual(inner[0, 0], 9)
        self.assertEqual(outer[1, 0], 17)
        values = interpolate(outer, inner, np.array([0.0, 0.5, 1.0, 0.25]), np.array([0.0, 0.5, 0.0, 0.5]))
        self.assertAlmostEqual(values[0], outer[0, 0])
        self.assertAlmostEqual(values[1], inner[0, 0])
        self.assertAlmostEqual(values[2], outer[1, 0])
        line = interpolate(outer, inner, np.linspace(0, 7.99, 400), np.full(400, 3.3))
        self.assertLess(np.abs(np.diff(line)).max(), 1.0)

    def test_identity_placement_maps_to_world_axes(self):
        from walkgrid.terrain import ORIGIN, placement_transform
        world = placement_transform(np.array([[1.0, 2.0, 3.0]]), (100.0, 50.0, 200.0), (0, 0, 0), 1.0)
        self.assertTrue(np.allclose(world[0], [ORIGIN - 200 - 1, ORIGIN - 100 - 2, 53]))
        turned = placement_transform(np.array([[1.0, 0, 0]]), (0.0, 0.0, 0.0), (0, 90, 0), 2.0)
        self.assertAlmostEqual(math.hypot(turned[0, 0] - ORIGIN, turned[0, 1] - ORIGIN), 2.0)

    def test_cost_layers(self):
        from walkgrid.rasterize import NEAR_WALL, dilate
        mask = np.zeros((7, 7), bool)
        mask[3, 3] = True
        grown = dilate(mask)
        self.assertEqual(int(grown.sum()), 9)
        self.assertEqual(NEAR_WALL, 255)


if __name__ == '__main__':
    unittest.main()
