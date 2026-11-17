"""按地图懒加载 .local/walkgrid/<地图编号>.wgrid，把位置与目的地换成格子路线（不导入 Qt）。"""
from __future__ import annotations

from pathlib import Path
import time

from wowbuddy.core.walk_grid import WalkGrid

_SIZE_TOLERANCE = 0.01
# 撞墙记下的临时障碍 10 分钟后失效：怪物挡路、被定身等也会触发撞墙判定，不能永久封路。
_TEMPORARY_SECONDS = 600


class GridRoutes:
    def __init__(self, directory=None, *, grids=None):
        self.directory = Path(directory) if directory is not None else None
        self._grids = dict(grids or {})
        self._failed = {}
        self.last_plan = None

    def available_maps(self):
        maps = set(self._grids)
        if self.directory is not None and self.directory.is_dir():
            for path in self.directory.glob('*.wgrid'):
                if path.stem.isdigit():
                    maps.add(int(path.stem))
        return sorted(maps)

    def grid(self, map_id):
        if map_id in self._grids:
            return self._grids[map_id]
        if map_id in self._failed or self.directory is None:
            return None
        path = self.directory / f'{map_id}.wgrid'
        if not path.is_file():
            return None
        try:
            grid = WalkGrid.from_bytes(path.read_bytes())
        except (OSError, ValueError, KeyError) as error:
            self._failed[map_id] = f'{path.name} 无法读取：{error}'
            return None
        if grid.map_id != map_id:
            self._failed[map_id] = f'{path.name} 内的地图编号为 {grid.map_id}'
            return None
        self._grids[map_id] = grid
        return grid

    def load_error(self, map_id):
        return self._failed.get(map_id)

    def plan(self, position, destination, *, prefer=None, max_expansions=400_000):
        """返回 (路点元组, None) 或 (None, 原因)。路点为地图百分比，首点是当前位置，末点是目的地。"""
        if position is None or destination is None or position.map_id != destination.map_id:
            return None, '不在同一地图'
        grid = self.grid(position.map_id)
        if grid is None:
            return None, self.load_error(position.map_id) or '没有这张地图的格子文件'
        if (abs(grid.width - position.width) > grid.width * _SIZE_TOLERANCE
                or abs(grid.height - position.height) > grid.height * _SIZE_TOLERANCE):
            return None, f'地图尺寸 {position.width}×{position.height} 与格子文件 {grid.width:g}×{grid.height:g} 不符'
        grid.expire_temporary(time.monotonic())
        started = time.perf_counter()
        path, reason = grid.find_path((position.x, position.y), (destination.x, destination.y),
                                      prefer=prefer, max_expansions=max_expansions)
        retried = False
        if path is None and grid.temporary_count and '上限' not in reason:
            # 临时障碍可能把窄口整个堵死（也可能是怪物挡路误记）；忽略临时障碍再试一次。
            retried = True
            path, reason = grid.find_path((position.x, position.y), (destination.x, destination.y),
                                          prefer=prefer, max_expansions=max_expansions, ignore_temporary=True)
        self.last_plan = dict(map_id=position.map_id, start=[position.x, position.y],
                              goal=[destination.x, destination.y], ok=path is not None, reason=reason,
                              points=len(path.points) if path else 0, yards=round(path.yards) if path else None,
                              ms=round((time.perf_counter() - started) * 1000), retried=retried)
        if path is None:
            return None, reason
        return path.points, None

    def note_blocked(self, position, *, near=0.5, far=3.0, half_width=1.5):
        """撞墙时把朝向前方几码记为本次运行的临时障碍，返回标记的格数。"""
        grid = self.grid(position.map_id) if position is not None else None
        if grid is None:
            return 0
        now = time.monotonic()
        grid.expire_temporary(now)
        return grid.block_ahead(position.x, position.y, position.heading, near=near, far=far, half_width=half_width,
                                expires=now + _TEMPORARY_SECONDS)

    def status(self):
        temporary = sum(grid.temporary_count for grid in self._grids.values())
        return dict(maps=self.available_maps(), last_plan=self.last_plan, temporary_cells=temporary)
