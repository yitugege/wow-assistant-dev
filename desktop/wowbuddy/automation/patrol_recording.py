"""录制循环打怪路线：记录用户手动走过的轨迹，供无人托管沿轨迹循环打怪。

设计：docs/design/20261115-recorded-patrol.md（阶段 1）。
- 采样规则与跑尸录制（death_recovery.CorpseTrail）一致：与上一点相距 ≥8 码才记点，直线上的点合并，
  两次可用坐标相差 >90 码视为定位中断；但不做“回到原路截断折返”，环线允许交叉。
- 只记录同一地图、存活状态的定位；换地图或定位中断即停止录制。
- 编码为 WBDLOOP1|地图|宽,高|x,y|…（坐标为地图百分比 ×100 的整数，宽高为录制时地图的码数），
  由 manual_routes.parse_patrol_route 读回。
"""
from math import hypot

SAMPLE_YARDS = 8
JUMP_YARDS = 90
COLLINEAR_SLACK_YARDS = 0.18
NEAR_START_YARDS = 15
NEAR_START_MIN_LENGTH = 60
MAX_POINTS = 256


class PatrolRecorder:
    def __init__(self):
        self._points = []
        self._map_id = None
        self._scale = None
        self.length = 0.0
        self.stopped = False
        self.reason = ''
        self.near_start = False
        self._near_notified = False

    @property
    def points(self):
        return tuple(self._points)

    @property
    def map_id(self):
        return self._map_id

    def _yards(self, a, b):
        width, height = self._scale
        return hypot((a[0] - b[0]) * width / 100, (a[1] - b[1]) * height / 100)

    def _stop(self, reason):
        self.stopped, self.reason = True, reason
        return reason

    def observe(self, position):
        """记录一帧定位；返回需要提示用户的文字（没有则为 None）。"""
        if (self.stopped or position is None or getattr(position, 'life', None) != 'alive'
                or position.x is None or position.y is None):
            return None
        point = round(position.x, 2), round(position.y, 2)
        if self._map_id is None:
            self._map_id, self._scale = position.map_id, (position.width, position.height)
            self._points.append(point)
            return f'已开始录制循环路线（地图 {position.map_id}），请手动沿循环走一圈。'
        if position.map_id != self._map_id:
            return self._stop(f'录制中切换了地图（{self._map_id} → {position.map_id}），已停止录制，本次未保存。')
        notice = None
        last = self._points[-1]
        distance = self._yards(last, point)
        if distance > JUMP_YARDS:
            return self._stop(f'定位中断，两次可用坐标相差 {distance:.0f} 码，已停止录制，本次未保存。')
        if distance >= SAMPLE_YARDS:
            if len(self._points) > 1:
                start, corner = self._points[-2:]
                direct = self._yards(start, point)
                via = self._yards(start, corner) + distance
                if via - direct <= COLLINEAR_SLACK_YARDS:
                    self.length += direct - self._yards(start, corner)
                    self._points[-1] = point
                    point = None
            if point is not None:
                if len(self._points) >= MAX_POINTS:
                    return self._stop(f'已录满 {MAX_POINTS} 个路点，已停止录制；请结束录制保存已录部分。')
                self._points.append(point)
                self.length += distance
        current = round(position.x, 2), round(position.y, 2)
        self.near_start = (len(self._points) >= 3 and self.length >= NEAR_START_MIN_LENGTH
                           and self._yards(current, self._points[0]) <= NEAR_START_YARDS)
        if self.near_start and not self._near_notified:
            self._near_notified = True
            notice = (f'已回到起点附近（{len(self._points)} 点，约 {self.length:.0f} 码），'
                      '可以点“结束录制并保存”。')
        return notice

    def encode(self):
        """编码为 WBDLOOP1 文本；不足 3 个点时抛出 ValueError。"""
        if self._map_id is None or len(self._points) < 3:
            raise ValueError('录制的路点不足 3 个，无法保存为循环路线。')
        width, height = self._scale
        coordinates = '|'.join(f'{round(x * 100)},{round(y * 100)}' for x, y in self._points)
        return f'WBDLOOP1|{self._map_id}|{width:.1f},{height:.1f}|{coordinates}'
