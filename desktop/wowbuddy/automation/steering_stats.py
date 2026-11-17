"""沿录制轨迹回放时的转向指标：按段统计偏离轨迹的距离与转向动作，作为转向改进前后的对照。

设计：docs/design/20261115-path-steering.md（第 1 步）。只读统计，不影响移动。
计数来源为 MapNavigator.counters：stop_turns（停下原地转向）、steer_pulses（行进中转向修正）、stalls（直行受阻）。
"""
from math import hypot

COUNTER_NAMES = ('stop_turns', 'steer_pulses', 'stalls')


def cross_track_yards(position, road):
    """position 到折线 road 的最近距离（码）；road 为地图百分比坐标；road 为空返回 None。"""
    if not road:
        return None
    sx, sy = position.width / 100, position.height / 100
    px, py = position.x * sx, position.y * sy
    points = [(x * sx, y * sy) for x, y in road]
    if len(points) == 1:
        return hypot(px - points[0][0], py - points[0][1])
    best = None
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
        distance = hypot(px - (ax + t * dx), py - (ay + t * dy))
        best = distance if best is None else min(best, distance)
    return best


class _Totals:
    def __init__(self):
        self.duration_ms = 0
        self.samples = 0
        self.deviation_sum = 0.0
        self.deviation_max = 0.0
        self.counts = dict.fromkeys(COUNTER_NAMES, 0)

    def add(self, other):
        self.duration_ms += other.duration_ms
        self.samples += other.samples
        self.deviation_sum += other.deviation_sum
        self.deviation_max = max(self.deviation_max, other.deviation_max)
        for name in COUNTER_NAMES:
            self.counts[name] += other.counts[name]

    def describe(self):
        mean = self.deviation_sum / self.samples if self.samples else 0.0
        return (f'用时 {self.duration_ms / 1000:.1f} 秒，最大偏离 {self.deviation_max:.1f} 码，平均偏离 {mean:.1f} 码，'
                f'原地转向 {self.counts["stop_turns"]} 次，转向修正 {self.counts["steer_pulses"]} 次，'
                f'受阻 {self.counts["stalls"]} 次')


class SteeringStats:
    def __init__(self):
        self._segment = None
        self._lap = _Totals()

    def begin(self, index, count, road, *, now_ms, counters):
        """开始统计第 index/count 段（index 从 1 起）；未结束的同一段重新开始。"""
        self._segment = dict(index=index, count=count, road=tuple(road), start_ms=now_ms,
                             start=dict((name, counters.get(name, 0)) for name in COUNTER_NAMES),
                             totals=_Totals())

    @property
    def active(self):
        return self._segment is not None

    def progress(self, *, now_ms):
        """当前段进度（供状态快照）；未在统计时返回 None。"""
        segment = self._segment
        if segment is None:
            return None
        totals = segment['totals']
        return dict(index=segment['index'], count=segment['count'],
                    seconds=round((now_ms - segment['start_ms']) / 1000, 1),
                    max_deviation=round(totals.deviation_max, 1), samples=totals.samples)

    def segment_key(self):
        return None if self._segment is None else (self._segment['index'], self._segment['road'])

    def observe(self, position, *, now_ms):
        if self._segment is None or position is None or position.x is None:
            return
        deviation = cross_track_yards(position, self._segment['road'])
        if deviation is None:
            return
        totals = self._segment['totals']
        totals.samples += 1
        totals.deviation_sum += deviation
        totals.deviation_max = max(totals.deviation_max, deviation)

    def abandon(self, reason):
        """作废当前段（不计入整圈汇总）并返回日志文字；没有进行中的段返回 None。"""
        segment, self._segment = self._segment, None
        if segment is None:
            return None
        return f'转向统计 · 第 {segment["index"]}/{segment["count"]} 段：{reason}，本段不计入。'

    def finish(self, *, now_ms, counters):
        """结束当前段并返回日志文字；最后一段结束时附整圈汇总。没有进行中的段返回 None。"""
        segment, self._segment = self._segment, None
        if segment is None:
            return None
        totals = segment['totals']
        totals.duration_ms = max(0, now_ms - segment['start_ms'])
        for name in COUNTER_NAMES:
            totals.counts[name] = max(0, counters.get(name, 0) - segment['start'][name])
        self._lap.add(totals)
        text = f'转向统计 · 第 {segment["index"]}/{segment["count"]} 段：{totals.describe()}。'
        if segment['index'] == segment['count']:
            text += f'\n转向统计 · 整圈：{self._lap.describe()}。'
            self._lap = _Totals()
        return text
