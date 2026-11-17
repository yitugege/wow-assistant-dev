"""用本机地图格子（.local/walkgrid/<地图>.wgrid）规划两点间的步行路线，输出可粘贴到助手的路线文字。

用途：生成“设置商人路线…”（固定打怪点 → 商人）或起点接入路线。只读格子文件，不碰游戏。

    python tools/grid_route_text.py --map 1433 --zone 赤脊山 --from 29.08,27.39 --to 26.6,44.3
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy.core.walk_grid import WalkGrid  # noqa: E402

MAX_POINTS = 48


def route_text(grid, map_id, zone, start, goal):
    path, reason = grid.find_path(start, goal)
    if path is None:
        raise ValueError(reason)
    points = list(path.points)
    if len(points) > MAX_POINTS:
        raise ValueError(f'路线有 {len(points)} 个路点，超过 {MAX_POINTS} 个；请分段生成')
    coords = []
    for x, y in points:
        coord = f'{round(x * 100)},{round(y * 100)}'
        if not coords or coords[-1] != coord:
            coords.append(coord)
    head = f'WBDROUTE2|{map_id}|{zone}' if zone else f'WBDROUTE1|{map_id}'
    return head + '|' + '|'.join(coords), path


def main(argv=None):
    parser = argparse.ArgumentParser(description='按地图格子生成路线文字。')
    parser.add_argument('--map', type=int, required=True)
    parser.add_argument('--zone', default='')
    parser.add_argument('--from', dest='start', required=True, help='x,y（地图百分比）')
    parser.add_argument('--to', dest='goal', required=True, help='x,y（地图百分比）')
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.local')
    args = parser.parse_args(argv)
    grid = WalkGrid.from_bytes((args.data_dir / 'walkgrid' / f'{args.map}.wgrid').read_bytes())
    start = tuple(float(v) for v in args.start.split(','))
    goal = tuple(float(v) for v in args.goal.split(','))
    text, path = route_text(grid, args.map, args.zone, start, goal)
    print(f'约 {path.yards:.0f} 码，{len(path.points)} 个路点。')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
