"""生成地图格子文件 .local/walkgrid/<地图编号>.wgrid（docs/design/20261116-walk-grid-pathing.md）。

只读本机客户端 Data 目录，不读游戏进程；结果只留在本机，不提交、不发布。

标定点来自游戏内（站在原地依次输入）：
    /dump UnitPosition("player")                              → 世界 X、Y
    /dump C_Map.GetPlayerMapPosition(<地图编号>, "player"):GetXY() → 地图 x、y（0–1）

用法：
    python tools/build_walk_grid.py --map 1433 --game-dir "<游戏目录>" --calibrate -9089.30,-2407.80,0.334709,0.355186 \\
        --calibrate -9233.20,-2190.40,0.234547,0.454594
    python tools/build_walk_grid.py --map 1433            # 复用 .local/walkgrid/calibration.json
"""
import argparse
import json
from pathlib import Path
import re
import struct
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'desktop')]



def solve_bounds(points, yards=None):
    """标定点 [(世界X, 世界Y, 地图x 0–1, 地图y 0–1)] → 世界边界与尺寸（码）。

    两点以上用最小二乘求比例与偏移；只有一点时须给 yards=(宽, 高)。
    """
    if not points:
        raise ValueError('缺少标定点')
    if len(points) == 1 and yards is None:
        raise ValueError('只有一个标定点时须给出地图尺寸 --yards 宽,高')

    def fit(values, ratios, size):
        if size is not None:
            scale = -size
        else:
            mean_r = sum(ratios) / len(ratios)
            mean_v = sum(values) / len(values)
            spread = sum((r - mean_r) ** 2 for r in ratios)
            if spread < 1e-6:
                raise ValueError('标定点太近，无法求出尺寸；请换一个远一点的点或给出 --yards')
            scale = sum((r - mean_r) * (v - mean_v) for r, v in zip(ratios, values)) / spread
        offset = sum(v - r * scale for r, v in zip(ratios, values)) / len(values)
        residual = max(abs(offset + r * scale - v) for r, v in zip(ratios, values))
        return offset, scale, residual

    width, height = (yards if yards is not None else (None, None))
    left, scale_y, res_y = fit([p[1] for p in points], [p[2] for p in points], width)
    top, scale_x, res_x = fit([p[0] for p in points], [p[3] for p in points], height)
    return dict(left=left, right=left + scale_y, top=top, bottom=top + scale_x,
                width=-scale_y, height=-scale_x, residual=max(res_x, res_y))


def walked_tracks(settings_path, map_id):
    """从助手设置中取本地图的实走轨迹（循环路线、跑尸轨迹、接入路线），返回地图百分比点列的列表。"""
    if not settings_path.is_file():
        return []
    tracks = []
    text = settings_path.read_text(encoding='utf-8', errors='ignore')
    for token in re.findall(r'WBD(?:LOOP|ROUTE|CORPSE)1\|[^"\n]*', text):
        for segment in token.split(':'):
            parts = segment.split('|')
            if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != map_id:
                continue
            points = []
            for part in parts[2:]:
                match = re.fullmatch(r'(-?\d+),(-?\d+)', part)
                if match:
                    points.append((int(match[1]) / 100, int(match[2]) / 100))
            if len(points) >= 2:
                tracks.append(points)
    return tracks


def track_check(cost, tracks):
    """实走轨迹经过的格子中原始受阻、贴墙的比例。"""
    rows, cols = cost.shape
    cells = set()
    for track in tracks:
        for (x1, y1), (x2, y2) in zip(track, track[1:]):
            steps = max(2, int(max(abs(x2 - x1) / 100 * cols, abs(y2 - y1) / 100 * rows) * 2))
            for k in range(steps + 1):
                x = x1 + (x2 - x1) * k / steps
                y = y1 + (y2 - y1) * k / steps
                r, c = int(y / 100 * rows), int(x / 100 * cols)
                if 0 <= r < rows and 0 <= c < cols:
                    cells.add((r, c))
    if not cells:
        return None
    values = [int(cost[r, c]) for r, c in cells]
    return dict(cells=len(cells), blocked=sum(v == 0 for v in values) / len(values),
                near_wall=sum(v == 255 for v in values) / len(values))


def write_png(path, rgb):
    height, width, _ = rgb.shape
    raw = b''.join(b'\0' + rgb[y].tobytes() for y in range(height))

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def main(argv=None):
    parser = argparse.ArgumentParser(description='从本机客户端文件生成地图格子（只读）。')
    parser.add_argument('--map', type=int, required=True, help='地图编号（UiMapID），如赤脊山 1433')
    parser.add_argument('--game-dir', type=Path, help='游戏目录（含 .build.info）；第一次须给出，之后记在 calibration.json')
    parser.add_argument('--product', default='wowf')
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.local')
    parser.add_argument('--calibrate', action='append', default=[],
                        help='世界X,世界Y,地图x,地图y（地图坐标为 0–1）；可给多次')
    parser.add_argument('--yards', help='地图尺寸 宽,高（码）；只有一个标定点时必填')
    parser.add_argument('--continent', choices=['eastern_kingdoms', 'kalimdor'])
    parser.add_argument('--slope', type=float, default=55.0, help='最大可走坡度（度）')
    args = parser.parse_args(argv)

    import numpy as np
    from walkgrid.casc import Casc
    from walkgrid.rasterize import build, preview
    from walkgrid.terrain import MAP_CONTINENT, World
    from wowbuddy.core.walk_grid import WalkGrid

    out_dir = args.data_dir / 'walkgrid'
    out_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = out_dir / 'calibration.json'
    calibration = json.loads(calibration_path.read_text(encoding='utf-8')) if calibration_path.is_file() else {}
    entry = calibration.get(str(args.map), {})
    if args.calibrate:
        entry['points'] = [[float(v) for v in item.split(',')] for item in args.calibrate]
    if args.yards:
        entry['yards'] = [float(v) for v in args.yards.split(',')]
    points = [tuple(p) for p in entry.get('points', [])]
    bounds = solve_bounds(points, tuple(entry['yards']) if entry.get('yards') else None)
    calibration[str(args.map)] = entry
    if args.game_dir:
        calibration['game_dir'] = str(args.game_dir)
    if not calibration.get('game_dir'):
        parser.error('请用 --game-dir 指定游戏目录（含 .build.info）')
    calibration_path.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"边界：左 {bounds['left']:.1f} 右 {bounds['right']:.1f} 上 {bounds['top']:.1f} 下 {bounds['bottom']:.1f}；"
          f"尺寸 {bounds['width']:.1f}×{bounds['height']:.1f} 码；标定残差 {bounds['residual']:.2f} 码")

    continent = args.continent or MAP_CONTINENT.get(args.map)
    if continent is None:
        parser.error('未知地图所在大陆，请用 --continent 指定')
    started = time.time()
    casc = Casc(Path(calibration['game_dir']), args.product)
    world = World(casc, continent)
    rows, cols = round(bounds['height']), round(bounds['width'])
    result = build(world, bounds, rows, cols, slope_limit=args.slope)
    cost = result['cost']
    meta = dict(product=args.product, client=casc.version, bounds={k: round(bounds[k], 2) for k in
                                                                   ('left', 'right', 'top', 'bottom')},
                slope_limit=args.slope, generated=time.strftime('%Y-%m-%d %H:%M:%S'), stats=result['stats'])
    grid = WalkGrid(map_id=args.map, rows=rows, cols=cols, width=round(bounds['width'], 1),
                    height=round(bounds['height'], 1), cost=cost.tobytes(), meta=meta)
    target = out_dir / f'{args.map}.wgrid'
    target.write_bytes(grid.to_bytes())
    write_png(out_dir / f'{args.map}.png', preview(cost, result['ground']))
    stats = result['stats']
    print(f"客户端 {casc.version}；{rows}×{cols} 格；地块 {stats['tiles']}；小物件 {stats['m2']}、建筑 {stats['wmo']}、"
          f"三角形 {stats['triangles']}；原始受阻 {stats['blocked']:.1%}；用时 {time.time() - started:.0f} 秒")
    print(f'已写入 {target}（{target.stat().st_size / 1e6:.2f} MB）与预览图 {target.with_suffix(".png")}')
    check = track_check(np.asarray(cost), walked_tracks(args.data_dir / 'settings.ini', args.map))
    if check is None:
        print('实走轨迹自检：设置中没有这张地图的循环路线或跑尸轨迹，跳过。')
    else:
        print(f"实走轨迹自检：{check['cells']} 格，原始受阻 {check['blocked']:.1%}，贴墙 {check['near_wall']:.1%}")
        if check['blocked'] + check['near_wall'] > 0.10:
            print('警告：实走轨迹受阻比例超过 10%，标定点可能有误。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
