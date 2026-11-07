"""自有插件0.2协议：24位无占位可用性位图，经版本标记转换为引擎旧布局。"""
from dataclasses import replace

DEV_VERSION = 0x574201
MAX_AVAILABILITY_SPELLS = 24


def normalize_availability(frame):
    if not frame.ok or frame.version_code != DEV_VERSION:
        return frame
    row = next((row for row in frame.rows if row.key == 'action_avail'), None)
    if row is None:
        return replace(frame, status='missing_availability')
    # 新版明确规定全白为24项全就绪，不是未知哨兵；旧版绝不走此转换。
    wire = row.decoded.raw_value
    text = str((wire << 1) | 1)
    decoded = replace(row.decoded, value_text=text,
                      detail='开发协议24位技能状态；已转换为引擎位图')
    rows = tuple(replace(item, decoded=decoded) if item is row else item for item in frame.rows)
    values = dict(frame.values, action_avail=text)
    return replace(frame, values=values, rows=rows)
