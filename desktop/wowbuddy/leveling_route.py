"""联网读取无限版练级指南，输出具名地图据点供导航使用。"""

from dataclasses import asdict, dataclass, field
from functools import partial
from hashlib import sha256
from html.parser import HTMLParser
from http.client import HTTPException
import json
from os import fstat
from pathlib import Path
import math
import re
from tempfile import NamedTemporaryFile
from time import monotonic, time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from .walking_route import LOCH_DIG_STANDS, REDRIDGE_MURLOC_STAND


_ORIGIN = 'https://wowhandbook.com'
_LIMIT = 2_000_000
_CAMP_RETRY_MS = 180_000
_CAMP_DEATH_WINDOW_MS = 300_000
_CAMP_DEATH_RETRY_MS = 900_000
_GUIDE_CACHE_SECONDS = 15 * 60
_GUIDE_REQUEST_SECONDS = 12
_GUIDE_LOOKUP_SECONDS = 30
_TRAVEL_RESUME_SECONDS = 24 * 60 * 60
_LEVEL_RANGE = re.compile(r'^([0-9]{1,2})\s*[–—-]\s*([0-9]{1,2})')
_COORDINATES = re.compile(r'([0-9]{1,3}(?:\.[0-9]+)?),\s*([0-9]{1,3}(?:\.[0-9]+)?)')
_ZONE_LINK = re.compile(r'(/zh/zones/[a-z0-9-]+/[a-z0-9-]+/)(?:#route-(?:alliance|horde))?')
_DEADWIND_GUIDE = 'https://theforeverguides.com/leveling/grinding-50-60/'
_ASHENVALE_FELFIRE_SPAWN = (range(32, 35), '6073', 'https://forever-tavern.com/npcs/classic/6073-searing-infernal/')
_ASHENVALE_FELFIRE_CAMPS = (
    (32, 34, '屠魔峡谷东桥桥头地狱火区', 80.615, 68.224),
    (32, 34, '屠魔峡谷东桥东南地狱火区', 81.469, 69.206),
)
_HORDE_SPAWN_SOURCES = {
    '阿拉希高地': (
        (range(30, 33), '2559', 'https://forever-tavern.com/npcs/classic/2559-highland-strider/'),
        (range(33, 36), '2560', 'https://forever-tavern.com/npcs/classic/2560-highland-thrasher/'),
    ),
    '希尔斯布莱德丘陵': (
        (range(27, 30), '2385', 'https://forever-tavern.com/npcs/classic/2385-feral-mountain-lion/'),
    ),
    '灰谷': (
        (range(27, 32), '3825', 'https://forever-tavern.com/npcs/classic/3825-ghostpaw-alpha/'),
        _ASHENVALE_FELFIRE_SPAWN,
    ),
}
_SHARED_SPAWN_SOURCES = {
    '泰达希尔': (
        (range(1, 3), '1984', 'https://forever-tavern.com/npcs/classic/1984-young-thistle-boar/'),
        (range(3, 5), '1985', 'https://forever-tavern.com/npcs/classic/1985-thistle-boar/'),
        (range(5, 7), '2042', 'https://forever-tavern.com/npcs/classic/2042-nightsaber/'),
        (range(7, 10), '2043', 'https://forever-tavern.com/npcs/classic/2043-nightsaber-stalker/'),
        (range(10, 12), '2034', 'https://forever-tavern.com/npcs/classic/2034-feral-nightsaber/'),
    ),
    '凄凉之地': (
        (range(35, 39), '4692', 'https://forever-tavern.com/npcs/classic/4692-dread-swoop/'),
        (range(39, 43), '4693', 'https://forever-tavern.com/npcs/classic/4693-dread-flyer/'),
        (range(43, 46), '4694', 'https://forever-tavern.com/npcs/classic/4694-dread-ripper/'),
    ),
    '菲拉斯': (
        (range(46, 49), '5288', 'https://forever-tavern.com/npcs/classic/5288-rabid-longtooth/'),
        (range(49, 54), '5274', 'https://forever-tavern.com/npcs/classic/5274-ironfur-patriarch/'),
    ),
    '费伍德森林': (
        (range(54, 57), '7139', 'https://forever-tavern.com/npcs/classic/7139-irontree-stomper/'),
        (range(57, 61), '7157', 'https://forever-tavern.com/npcs/classic/7157-deadwood-avenger/'),
    ),
    '黑海岸': (
        (range(12, 14), '2321', 'https://forever-tavern.com/npcs/classic/2321-foreststrider-fledgling/'),
        (range(14, 16), '2069', 'https://forever-tavern.com/npcs/classic/2069-moonstalker/'),
        (range(16, 18), '2165', 'https://forever-tavern.com/npcs/classic/2165-grizzled-thistle-bear/'),
        (range(18, 20), '2237', 'https://forever-tavern.com/npcs/classic/2237-moonstalker-sire/'),
        (range(20, 22), '2071', 'https://forever-tavern.com/npcs/classic/2071-moonstalker-matriarch/'),
    ),
    '塔纳利斯': (
        (range(42, 45), '5618', 'https://forever-tavern.com/npcs/classic/5618-wastewander-bandit/'),
        (range(45, 48), '5623', 'https://forever-tavern.com/npcs/classic/5623-wastewander-assassin/'),
    ),
    '冬泉谷': (
        (range(55, 59), '7458', 'https://forever-tavern.com/npcs/classic/7458-ice-thistle-yeti/'),
    ),
}
_ALLIANCE_ASHENVALE_SOURCES = (
    (range(22, 25), '3823', 'https://forever-tavern.com/npcs/classic/3823-ghostpaw-runner/'),
    (range(25, 28), '3925', 'https://forever-tavern.com/npcs/classic/3925-thistlefur-avenger/'),
    (range(28, 32), '3825', 'https://forever-tavern.com/npcs/classic/3825-ghostpaw-alpha/'),
    _ASHENVALE_FELFIRE_SPAWN,
)
_SHARED_SPAWN_CAMPS = {
    '黑海岸': ('darkshore', (
        (12, 13, '奥伯丁南侧森林陆行雏鸟区', 38.953, 48.684),
        (12, 13, '亚米萨兰西侧森林陆行雏鸟区', 39.758, 57.378),
        (14, 15, '古树之林西侧月夜猛虎区', 40.045, 65.983),
        (14, 15, '急弯河北侧月夜猛虎区', 40.583, 70.028),
        (16, 17, '南部灰雾蓟熊北侧营地', 39.065, 69.96),
        (16, 17, '南部灰雾蓟熊南侧营地', 40.287, 75.878),
        (18, 19, '南部月夜猛虎北侧营地', 39.8, 70.691),
        (18, 19, '南部月夜猛虎南侧营地', 38.315, 77.167),
        (18, 19, '北部月夜猛虎营地', 60.068, 13.373),
        (20, 21, '北部月夜雌虎营地', 60.956, 11.87),
        (20, 21, '南部月夜雌虎西侧营地', 36.894, 89.675),
        (20, 21, '南部月夜雌虎东侧营地', 39.851, 90.339),
    )),
    '塔纳利斯': ('tanaris', (
        (42, 44, '废土强盗西侧营地', 59.402, 24.706),
        (42, 44, '废土强盗东侧营地', 60.854, 23.483),
        (45, 47, '废土刺客西侧营地', 58.745, 36.406),
        (45, 47, '废土刺客东侧营地', 60.092, 37.413),
    )),
    '冬泉谷': ('winterspring', (
        (55, 58, '冰蓟丘陵西侧雪人区', 65.305, 39.612),
        (55, 58, '冰蓟丘陵东侧雪人区', 66.272, 41.125),
    )),
    '凄凉之地': ('desolace', (
        (35, 38, '凄凉之地北部恐怖飞扑者区', 59.928, 13.372),
        (35, 38, '凄凉之地中北部恐怖飞扑者区', 59.774, 24.319),
        (39, 42, '凄凉之地中部恐怖飞鸟区', 61.922, 44.567),
        (39, 42, '凄凉之地中东部恐怖飞鸟区', 63.96, 45.64),
        (43, 45, '凄凉之地东南部恐怖撕裂者区', 62.723, 71.011),
        (43, 45, '凄凉之地东南部恐怖撕裂者备用区', 61.166, 74.452),
    )),
    '菲拉斯': ('feralas', (
        (46, 48, '菲拉斯北部狼群区', 44.503, 9.115),
        (46, 48, '菲拉斯北部狼群备用区', 44.373, 11.024),
        (49, 53, '菲拉斯北部铁鬃熊区', 44.461, 11.743),
        (49, 53, '菲拉斯北部铁鬃熊备用区', 43.033, 9.689),
    )),
    '费伍德森林': ('felwood', (
        (54, 56, '铁木森林践踏者西侧营地', 51.775, 24.167),
        (54, 56, '铁木森林践踏者东侧营地', 52.528, 24.57),
        (57, 60, '魔爪村死木复仇者西侧营地', 60.901, 8.419),
        (57, 60, '魔爪村死木复仇者南侧营地', 61.102, 9.042),
    )),
}
_DEADWIND_CAMPS = ('deadwind-pass', (
    (55, 60, '罪恶谷逆风蛮兵区', 54.6, 60.4),
    (55, 58, '西侧天空之影区', 38.6, 41.4),
))
_DEADWIND_MARKERS = {'7369': (54.6, 60.4), '7376': (38.6, 41.4)}

# 按地区攻略核对过的野外刷怪区。等级表示本工具允许进入的角色等级。
_STARTER_COMBAT_CAMPS = {
    ('alliance', '泰达希尔'): ('teldrassil', (
        (1, 2, '幽影谷西侧幼野猪区', 58.508, 45.665),
        (1, 2, '幽影谷南口幼野猪区', 60.613, 46.26),
        (3, 4, '幽影谷东北蓟皮野猪区', 61.825, 38.655),
        (3, 4, '幽影谷北侧蓟皮野猪区', 60.151, 39.088),
        (5, 6, '多兰纳尔西侧夜刃豹区', 53.628, 55.608),
        (5, 6, '多兰纳尔西南夜刃豹区', 50.981, 57.426),
        (7, 9, '西部夜刃捕猎者东侧营地', 40.504, 55.571),
        (7, 9, '西部夜刃捕猎者西侧营地', 40.129, 55.841),
        (10, 11, '神谕林地南侧凶猛的夜刃豹区', 39.91, 28.687),
        (10, 11, '神谕林地东侧凶猛的夜刃豹区', 40.652, 27.366),
    )),
    ('alliance', '丹莫罗'): ('dun-morogh', (
        (1, 3, '寒脊山谷蓬毛幼狼区', 30.79, 72.95),
        (1, 3, '寒脊山谷石腭穴居人区', 31.05, 73.95),
        (3, 4, '寒脊山谷小型峭壁野猪区', 22.74, 72.42),
        (4, 5, '霜鬃巨魔幼崽山坡', 25.86, 78.26),
        (6, 7, '灰色洞穴外', 42.9, 49.6),
        (7, 9, '雾松避难所冰元素区', 55.1, 45.4),
        (8, 10, '古博拉采掘场石腭击颅者区', 69.65, 57.08),
        (9, 11, '古博拉采掘场石腭断骨者区', 70.67, 56.64),
    )),
    ('alliance', '艾尔文森林'): ('elwynn-forest', (
        (1, 3, '北郡狗头人歹徒区', 48.1, 36.96),
        (1, 3, '北郡路边林狼区', 50.89, 44.37),
        (3, 5, '回音山矿洞外', 50.83, 37.92),
        (4, 5, '北郡路东盗贼区', 51.82, 47.4),
        (5, 7, '马科伦葡萄园野猪区', 42.9, 86.56),
        (7, 9, '大路东侧林狼区', 58.44, 62.13),
        (8, 10, '东桥南侧狼熊区', 75.49, 76.54),
        (9, 11, '西泉要塞南侧河爪豺狼人区', 27.45, 79.89),
        (10, 11, '东谷北侧迪菲亚流浪巫师区', 73.95, 55.64),
    )),
    ('horde', '杜隆塔尔'): ('durotar', (
        (1, 3, '试炼谷杂斑野猪区', 44.49, 65.1),
        (3, 5, '试炼谷工蝎区', 41.83, 65.81),
        (5, 7, '提拉加德城堡外水手区', 57.4, 56.4),
        (6, 8, '剃刀岭南侧野猪人区', 51.0, 48.2),
        (7, 9, '剃刀岭南侧野猪人斥候区', 50.8, 48.8),
        (8, 10, '剃刀岭西侧野猪人传令兵区', 44.6, 40.6),
        (10, 11, '枯水谷鹰身人区', 51.43, 20.86),
        (10, 11, '雷霆山蜥蜴区', 43.63, 24.14),
    )),
    ('horde', '提瑞斯法林地'): ('tirisfal-glades', (
        (1, 2, '丧钟镇无脑的僵尸区', 30.7, 64.17),
        (2, 3, '丧钟镇断骨骷髅区', 32.98, 63.0),
        (2, 4, '夜行蜘蛛洞外', 29.4, 59.42),
        (3, 4, '丧钟镇食腐狼区', 34.56, 62.55),
        (4, 5, '丧钟镇东侧血色农场', 35.94, 68.59),
        (5, 7, '布瑞尔南侧黑暗犬区', 58.3, 58.28),
        (6, 8, '布瑞尔北侧腐皮盗墓贼区', 56.5, 46.09),
        (8, 9, '布瑞尔北侧混血腐皮豺狼人区', 58.59, 37.5),
        (9, 11, '东部墓地血僵尸区', 74.16, 62.79),
    )),
}
_COMBAT_CAMPS = {
    **_SHARED_SPAWN_CAMPS,
    '灰谷': ('ashenvale', (
        (22, 24, '灰谷北路东侧幽爪奔跑者营地', 29.803, 19.749),
        (22, 24, '灰谷北路西侧幽爪奔跑者营地', 27.094, 18.591),
        (22, 24, '灰谷北路南侧幽爪奔跑者营地', 27.021, 26.203),
        (25, 27, '灰谷西部蓟皮复仇者南侧营地', 31.378, 45.238),
        (25, 27, '灰谷西部蓟皮复仇者山坡营地', 32.045, 43.145),
        (25, 27, '灰谷西部蓟皮复仇者北侧营地', 32.633, 42.161),
        (28, 31, '灰谷东南幽爪前锋西侧营地', 66.573, 70.074),
        (28, 31, '灰谷东南幽爪前锋东侧营地', 68.2, 69.161),
        *_ASHENVALE_FELFIRE_CAMPS,
    )),
    '西部荒野': ('westfall', (
        (12, 14, '詹戈洛德矿洞外', 44.8, 23.12),
        (12, 14, '北海岸鱼人区', 52.97, 11.3),
        (13, 15, '萨丁农场南边的田野', 43.97, 39.63),
        (14, 15, '摩尔森农场', 46.1, 38.2),
        (15, 16, '月溪镇', 45.4, 70.2),
        (16, 18, '匕首岭', 51.66, 77.21),
    )),
    '赤脊山': ('redridge-mountains', (
        (15, 17, '三角路口以东的山丘', 11.65, 62.18),
        (16, 18, '赤脊山偷猎者营地', 23.25, 79.41),
        (18, 20, '湖南岸鱼人区', 30.7, 56.46),
        (19, 22, '奥瑟尔伐木场周围的山坡', 42.74, 38.46),
        (24, 26, '撕裂者山谷', 23.51, 17.25),
    )),
    '洛克莫丹': ('loch-modan', (
        (11, 13, '碎石穴居人前哨', 31.5, 72.1),
        (13, 15, '碎石怪击颅者营地', 35.6, 84.2),
        (15, 18, '碎石怪萨满祭司营地', 37.5, 90.1),
        (15, 19, '碎石怪断骨者营地', 37.9, 87.0),
        (15, 17, '旅行者营地西侧山鹫区', 76.8, 70.5),
        (16, 18, '东岸老山猪区', 65.4, 39.6),
        (17, 19, '铁环挖掘场地卜师营地', 70.0, 63.3),
        (18, 19, '铁环挖掘场掘地工营地', 70.1, 66.0),
    )),
    '湿地': ('wetlands', (
        (20, 23, '藓皮豺狼人营地', 60.51, 63.71),
        (21, 24, '混血藓皮豺狼人营地', 60.74, 64.31),
        (24, 27, '绿带草地沼泽爬行者区', 54.0, 41.37),
    )),
    '暮色森林': ('duskwood', (
        (19, 21, '乌鸦岭以东蜘蛛区', 33.96, 24.6),
        (20, 22, '亚伯克隆比附近恐狼区', 33.14, 29.35),
        (22, 25, '静谧花园墓场', 78.03, 67.01),
        (25, 27, '静谧花园骷髅区', 78.25, 68.18),
        (27, 29, '夜行织影狼人区', 64.95, 45.75),
    )),
    '荆棘谷': ('stranglethorn-vale', (
        (30, 32, '荆棘谷猛虎幼崽区', 35.65, 12.14),
        (30, 32, '猎豹幼崽区', 36.62, 13.76),
        (32, 34, '成年荆棘谷猛虎区', 36.4, 13.8),
        (32, 34, '黑豹活动区', 30.4, 8.8),
        (33, 35, '荆棘谷迅猛龙区', 27.79, 14.32),
        (34, 36, '老年荆棘谷猛虎区', 31.29, 16.62),
        (35, 37, '鞭尾迅猛龙区', 31.97, 20.68),
        (37, 40, '深喉猎豹区', 48.09, 20.2),
    )),
    '悲伤沼泽': ('swamp-of-sorrows', (
        # 路边南岸。蜘蛛区和虎区在水道另一侧，当前步行协议进入游泳会停走。
        (36, 44, '西部小盐齿鳄鱼区', 27.1, 55.13),
    )),
    '诅咒之地': ('blasted-lands', (
        # 44 级西部鳄鱼营地耗尽后，先到北部主路边的秃鹫区。
        (44, 48, '北部主路秃鹫区', 50.2, 17.2),
        (45, 48, '北部西侧秃鹫区', 46.8, 19.4),
        (46, 50, '北部石化蜥蜴区', 48.46, 20.34),
        (47, 51, '东侧石化蜥蜴区', 55.02, 29.05),
        (48, 52, '中部灰鬃野猪区', 52.27, 27.39),
        (49, 53, '北部弯牙土狼区', 48.3, 17.84),
        (50, 54, '北部厚甲蝎区', 48.2, 17.4),
    )),
    '逆风小径': _DEADWIND_CAMPS,
}
_HORDE_COMBAT_CAMPS = {
    **_SHARED_SPAWN_CAMPS,
    '银松森林': ('silverpine-forest', (
        (12, 14, '玛尔丁果园外杂斑座狼区', 54.88, 13.61),
        (14, 18, '安伯米尔外围达拉然守卫区', 54.85, 54.4),
    )),
    '希尔斯布莱德丘陵': ('hillsbrad-foothills', (
        (19, 21, '塔伦米尔西侧灰熊区', 57.63, 23.63),
        (22, 24, '希尔斯布莱德雇农田地', 36.82, 39.58),
        (23, 26, '希尔斯布莱德农夫田地', 36.38, 39.77),
        (27, 29, '河东岸北侧野生山地狮区', 60.983, 50.923),
        (27, 29, '奈杉德哨岗西侧野生山地狮区', 58.522, 55.591),
    )),
    '阿拉希高地': ('arathi-highlands', (
        (30, 32, '阿拉希西部北侧迅猛龙区', 23.663, 35.371),
        (30, 32, '阿拉希西部主路旁迅猛龙区', 24.477, 40.65),
        (33, 35, '阿拉希西部丘陵北侧迅猛龙区', 22.028, 47.682),
        (33, 35, '阿拉希西部丘陵南侧迅猛龙区', 21.641, 49.413),
    )),
    '贫瘠之地': ('the-barrens', (
        (12, 15, '十字路口北侧陆行鸟区', 53.12, 30.42),
        (13, 17, '十字路口南侧迅猛龙区', 52.93, 33.04),
        (12, 15, '十字路口西南斑马区', 50.79, 34.14),
        (15, 18, '草原徘徊者区', 55.6, 16.32),
        (17, 20, '赤鳞镰爪龙巢穴', 52.46, 46.56),
        (21, 22, '刺背地卜师营地', 43.81, 48.17),
    )),
    '灰谷': ('ashenvale', (
        (23, 26, '碎木岗哨南侧先驱者活动区', 72.52, 69.5),
        (27, 31, '夜歌森林东侧幽爪前锋区', 68.2, 69.161),
        (27, 31, '夜歌森林西侧幽爪前锋区', 66.573, 70.074),
        *_ASHENVALE_FELFIRE_CAMPS,
    )),
    '逆风小径': _DEADWIND_CAMPS,
}
# 攻略标记在水边或陡坡时，用同一营地内能步行接入的位置寻怪。
_CAMP_WALKABLE_POSITIONS = {
    **{('洛克莫丹', *marker): stand for marker, stand in LOCH_DIG_STANDS.items()},
    ('丹莫罗', 42.9, 49.6): (43.6, 49.6),
    ('丹莫罗', 55.1, 45.4): (54.4, 45.85),
    ('赤脊山', 30.7, 56.46): REDRIDGE_MURLOC_STAND,
    ('悲伤沼泽', 27.1, 55.13): (27.1, 56.7),
    ('逆风小径', 38.6, 41.4): (38.6, 42.15),
}


@dataclass(frozen=True)
class MapPoint:
    zone: str
    zone_path: str
    name: str
    x: float
    y: float


@dataclass
class RouteStage:
    number: int | None
    levels: tuple[int, int] | None = None
    points: list[MapPoint] = field(default_factory=list)


class _GuideParser(HTMLParser):
    """只消费路线正文的等级、地图链接和明确标出的游戏坐标。"""

    def __init__(self):
        super().__init__()
        self.stages = []
        self.starters = {}
        self._stage = None
        self._zone_path = ''
        self._zone = ''
        self._in_zone_heading = False
        self._in_hubs = False
        self._point = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if tag == 'article':
            if 'lvs-start' in classes:
                self._stage = RouteStage(None)
                return
            if 'lvs' in classes:
                number = attrs.get('data-step') or ''
                if number.isascii() and number.isdecimal():
                    self._stage = RouteStage(int(number))
                return
        if self._stage is None:
            return
        starter = self._stage.number is None
        if (tag == 'small' and starter and self._in_zone_heading
                or tag == 'p' and 'lvs-meta' in classes and not starter):
            self._capture = (tag, 'levels', [])
        elif tag == 'div' and 'lvs-leg__text' in classes:
            self._zone = self._zone_path = ''
        elif tag == ('h3' if starter else 'h4'):
            self._in_zone_heading = True
        elif tag == 'a' and self._in_zone_heading and not self._zone_path:
            if link := _ZONE_LINK.fullmatch(attrs.get('href') or ''):
                self._zone_path = link[1]
                self._capture = (tag, 'zone', [])
        elif tag == 'ol' and 'lvs-hubs' in classes:
            self._in_hubs = True
        elif self._in_hubs and tag == 'li':
            self._point = {}
        elif self._point is not None:
            if tag == 'span' and 'lvs-hub-name' in classes:
                self._capture = (tag, 'name', [])
            elif tag == 'code':
                self._capture = (tag, 'coords', [])

    def handle_data(self, data):
        if self._capture is not None:
            self._capture[2].append(data)

    def handle_endtag(self, tag):
        if self._stage is None:
            return
        if self._capture is not None and self._capture[0] == tag:
            _, kind, parts = self._capture
            self._capture = None
            value = ''.join(parts).strip()
            if kind == 'levels':
                if match := _LEVEL_RANGE.match(value):
                    self._stage.levels = (int(match[1]), int(match[2]))
            elif kind == 'zone':
                self._zone = value
            elif self._point is not None:
                self._point[kind] = value
        if tag == 'li' and self._point is not None:
            if (self._zone and self._point.get('name')
                    and (coords := _COORDINATES.fullmatch(self._point.get('coords', '')))):
                x, y = float(coords[1]), float(coords[2])
                if 0 <= x <= 100 and 0 <= y <= 100:
                    self._stage.points.append(MapPoint(self._zone, self._zone_path, self._point['name'], x, y))
            self._point = None
        elif tag == 'ol':
            self._in_hubs = False
        elif tag == ('h3' if self._stage.number is None else 'h4'):
            self._in_zone_heading = False
        elif tag == 'article':
            if self._stage.number is not None:
                self.stages.append(self._stage)
            elif self._zone and self._stage.levels and 1 <= self._stage.levels[0] <= self._stage.levels[1] <= 60:
                self.starters[self._zone] = (self._zone_path, self._stage.levels)
            self._stage = self._point = self._capture = None
            self._zone = self._zone_path = ''
            self._in_zone_heading = self._in_hubs = False


def _read_guide(url, *, deadline=None):
    start = monotonic()
    stop = start + _GUIDE_REQUEST_SECONDS if deadline is None else min(deadline, start + _GUIDE_REQUEST_SECONDS)
    if stop <= start:
        raise TimeoutError('练级指南读取超时')
    request = Request(url, headers={'User-Agent': 'WowBuddyDev/leveling-lookup'})
    try:
        with urlopen(request, timeout=stop - start) as response:
            if response.geturl() != url:
                raise ValueError('练级指南的地址或内容类型已变化')
            if response.status == 206 or response.headers.get('Content-Range'):
                raise OSError('练级指南未完整接收')
            if response.headers.get_content_type() != 'text/html':
                raise ValueError('练级指南的地址或内容类型已变化')
            length = response.headers.get('Content-Length', '').strip()
            transfer_encoding = response.headers.get('Transfer-Encoding')
            # read1 让持续分批返回的正文也能定期检查总读取时间。
            data = bytearray()
            while len(data) <= _LIMIT and monotonic() < stop:
                chunk = response.read1(min(64 * 1024, _LIMIT + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if monotonic() >= stop:
                raise TimeoutError('练级指南读取超时')
    except HTTPException as error:
        raise OSError('练级指南未完整接收') from error
    if len(data) > _LIMIT:
        raise ValueError('练级指南超过读取限制')
    if not transfer_encoding and length.isdecimal() and len(data) != int(length):
        raise OSError('练级指南未完整接收')
    return data.decode('utf8')


class LevelingGuideCache:
    """短时断网时重新解析最近核验过的攻略，包括重启后的查询。"""

    def __init__(self, clock=monotonic, *, directory=None, wall_clock=time):
        self._clock = clock
        self._wall_clock = wall_clock
        self._directory = Path(directory) if directory is not None else None
        self._pages = {}

    def _path(self, url):
        if self._directory is not None:
            return self._directory / (sha256(url.encode('utf8')).hexdigest() + '.html')
        return None

    def _forget(self, url, path):
        self._pages.pop(url, None)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _cached_page(self, url, path):
        cached = self._pages.get(url)
        if cached and self._clock() - cached[0] <= _GUIDE_CACHE_SECONDS:
            return cached[1]
        if path is not None:
            try:
                with path.open('rb') as file:
                    age = self._wall_clock() - fstat(file.fileno()).st_mtime
                    if 0 <= age <= _GUIDE_CACHE_SECONDS:
                        content = file.read(_LIMIT + 1)
                        if len(content) <= _LIMIT:
                            return content.decode('utf8')
            except (OSError, UnicodeError):
                pass
        return None

    def load(self, url, fetch, parse):
        path = self._path(url)
        try:
            html = fetch(url)
        except OSError as error:
            if isinstance(error, HTTPError) and error.code < 500 and error.code not in (408, 429):
                self._forget(url, path)
                raise
            cached = self._cached_page(url, path)
            if cached is not None:
                data = parse(cached)
                if data:
                    return data, True
            raise
        except ValueError:
            self._forget(url, path)
            raise
        try:
            data = parse(html)
        except ValueError:
            self._forget(url, path)
            raise
        if data:
            self._pages[url] = self._clock(), html
            if path is not None:
                try:
                    _replace_text_file(path, html)
                except OSError:
                    pass
        else:
            self._forget(url, path)
        return data, False


def _load_guide_data(url, fetch, parse, cache):
    if cache is not None:
        return cache.load(url, fetch, parse)
    return parse(fetch(url)), False


def _guide_stages(html):
    parser = _GuideParser()
    parser.feed(html)
    parser.close()
    stages = parser.stages
    if (not stages or [stage.number for stage in stages] != list(range(1, len(stages) + 1))
            or any(not stage.levels or not 1 <= stage.levels[0] <= stage.levels[1] <= 60 for stage in stages)):
        raise ValueError('练级指南结构已变化，无法可靠定位等级段')
    if not any(stage.points for stage in stages):
        raise ValueError('没有可核对的下一个据点坐标')
    return tuple(stages), parser.starters


def _select_leveling_point(faction, level, current_zone, completed_point, fetch, cache, *, allow_starter=False):
    if faction not in ('alliance', 'horde'):
        raise ValueError('阵营必须为 alliance 或 horde')
    if type(level) is not int or not 1 <= level <= 60 or not current_zone.strip():
        raise ValueError('请提供 1–60 级及当前地图名称')
    current_zone = current_zone.strip()
    url = f'{_ORIGIN}/zh/leveling/{faction}/'
    (stages, starters), cached = _load_guide_data(url, fetch, _guide_stages, cache)
    starter = None
    path, levels = starters.get(current_zone, ('', (0, 0)))
    if allow_starter and path and levels[0] <= level <= levels[1]:
        # 网页标记按裁剪后的图排版，这里只采用区域与等级。
        starter = {'faction': faction, 'level': level, 'current_zone': current_zone,
                   'stage': 0, 'level_range': levels, 'cross_zone': False,
                   'point': {'zone': current_zone, 'zone_path': path, 'name': current_zone},
                   'source_url': f'{url}#lv-1', 'zone_url': _ORIGIN + path}
        if cached:
            starter['cached_sources'] = [url]

    eligible = [stage for stage in stages if stage.levels[0] <= level <= stage.levels[1]]
    current = next((stage for stage in eligible if any(point.zone == current_zone for point in stage.points)), None)
    if completed_point and current is None:
        raise ValueError('当前等级和地图未匹配已完成据点所属路线')
    if current is not None:
        later = next((stage for stage in eligible if stage.number == current.number + 1), None)
        stage = current
        points = [point for point in stage.points if point.zone == current_zone]
        if completed_point:
            matches = [index for index, point in enumerate(stage.points)
                       if point.zone == current_zone and point.name == completed_point]
            if len(matches) != 1:
                raise ValueError('当前地图中找不到唯一的已完成据点')
            points = stage.points[matches[0] + 1:]
        if later is not None and (not points or (not completed_point and level == current.levels[1])):
            stage, points = later, later.points
    elif eligible:
        stage = eligible[0]
        points = stage.points
    elif starter:
        return starter, eligible, None
    else:
        raise ValueError('指南正文没有该等级的带坐标路线，无法选择下一点')
    if not points:
        raise ValueError('没有可核对的下一个据点坐标')
    point = points[0]
    result = {
        'faction': faction, 'level': level, 'current_zone': current_zone,
        'stage': stage.number, 'level_range': stage.levels, 'point': asdict(point),
        'cross_zone': point.zone != current_zone, 'source_url': f'{url}#step-{stage.number}',
        'zone_url': _ORIGIN + point.zone_path,
    }
    if cached:
        result['cached_sources'] = [url]
    return result, eligible, starter


def find_leveling_point(faction, level, current_zone, *, completed_point='', fetch=_read_guide, cache=None):
    result, _, _ = _select_leveling_point(faction, level, current_zone, completed_point, fetch, cache)
    return result


class _CombatMarkers(HTMLParser):
    def __init__(self, zone_path, section):
        super().__init__()
        self.zone_path = zone_path
        self.section = section
        self.sections = []
        self.coordinates = set()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'section':
            self.sections.append(attrs.get('id'))
        if (tag != 'a' or self.section not in self.sections
                or 'route-coords' not in (attrs.get('class') or '').split()):
            return
        link = urlsplit(attrs.get('href') or '')
        if link.scheme or link.netloc or link.path != self.zone_path or link.fragment != 'map':
            return
        pin = parse_qs(link.query).get('pin', [])
        if len(pin) == 1 and (match := _COORDINATES.fullmatch(pin[0])):
            self.coordinates.add((float(match[1]), float(match[2])))

    def handle_endtag(self, tag):
        if tag == 'section' and self.sections:
            self.sections.pop()


def _known_marker_coordinates(html, path, section, known):
    parser = _CombatMarkers(path, section)
    parser.feed(html)
    parser.close()
    return frozenset((px, py) for _, _, _, px, py in known if (px, py) in parser.coordinates)


class _DeadwindCampTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.row = None
        self.column = None
        self.coordinates = set()

    def handle_starttag(self, tag, attributes):
        if tag == 'tr':
            self.row = {}
            self.column = None
        elif tag == 'td' and self.row is not None:
            self.column = dict(attributes).get('data-label')
            if self.column:
                self.row.setdefault(self.column, [])

    def handle_data(self, data):
        if self.row is not None and self.column:
            self.row[self.column].append(data)

    def handle_endtag(self, tag):
        if tag == 'td':
            self.column = None
        elif tag == 'tr' and self.row is not None:
            cells = {key: ''.join(tokens).strip() for key, tokens in self.row.items()}
            self.row = self.column = None
            coords = _COORDINATES.fullmatch(cells.get('Densest camp', ''))
            levels = _LEVEL_RANGE.fullmatch(cells.get('Level', ''))
            if (coords and levels and (int(levels[1]), int(levels[2])) == (55, 56)
                    and cells.get('Zone') == 'Deadwind Pass' and cells.get('Elite?') == 'No'):
                point = float(coords[1]), float(coords[2])
                if _DEADWIND_MARKERS.get(cells.get('NPC ID')) == point:
                    self.coordinates.add(point)


def _deadwind_marker_coordinates(html):
    parser = _DeadwindCampTable()
    parser.feed(html)
    parser.close()
    return frozenset(parser.coordinates)


def _camp_spawn_source(faction, zone, level):
    sources = _SHARED_SPAWN_SOURCES.get(zone, ())
    if faction == 'alliance' and zone == '灰谷':
        sources = _ALLIANCE_ASHENVALE_SOURCES
    elif not sources and faction == 'horde':
        sources = _HORDE_SPAWN_SOURCES.get(zone, ())
    return next(((npc, url) for levels, npc, url in sources if level in levels), None)


def _spawn_marker_coordinates(html, npc, map_id):
    coordinates = set()
    map_id = str(map_id)

    class SpawnPins(HTMLParser):
        def handle_starttag(self, tag, attributes):
            if tag != 'a':
                return
            attrs = dict(attributes)
            if ('data-entity-pin' not in attrs or attrs.get('data-zone') != map_id
                    or attrs.get('data-source-id') != npc or attrs.get('data-pin-label') != 'Source spawn'):
                return
            raw = f"{attrs.get('data-source-x')},{attrs.get('data-source-y')}"
            if match := _COORDINATES.fullmatch(raw):
                coordinates.add((float(match[1]), float(match[2])))

    parser = SpawnPins()
    parser.feed(html)
    parser.close()
    return frozenset(coordinates)


def _camp_endpoint(routes, map_id, x, y):
    from .manual_routes import manual_camp_road
    from .navigation import MapDestination

    road = manual_camp_road(routes, MapDestination(map_id, x, y, 'alive', '刷怪点'))
    return road[-1] if road else None


def _camp_x_bounds(map_id, x, y):
    if map_id == 1432 and x is not None and y is not None and y >= 20:
        if x <= 41.5:
            return 0, 41.5
        if x >= 56.5:
            return 56.5, 100
    return 0, 100


def local_camp_on_current_shore(character, destination):
    if character.map_id != destination.map_id:
        return True
    if character.map_id == 1438:
        from .walking_route import _ruttheran_area

        return _ruttheran_area(character.x, character.y) == _ruttheran_area(destination.x, destination.y)
    if character.map_id == 1439:
        from .walking_route import auberdine_overlapping_floor, darkshore_camp_origin

        if auberdine_overlapping_floor(character.x, character.y):
            return darkshore_camp_origin(character.x, character.y, elevation=character.elevation)
    low, high = _camp_x_bounds(character.map_id, character.x, character.y)
    return low <= destination.x <= high


def _marked_camps(guide, source, x, y, zone_ids, routes, excluded, blocked, connections, faction):
    from .walking_route import plan_walking_route

    guide_point = guide['point']
    zone = guide_point['zone']
    map_id = zone_ids.get(zone)
    endpoints = [route.endpoint for route in routes if route.map_id == map_id]
    if not endpoints:
        return None
    if source is None or plan_walking_route(source, map_id, guide['level'], 'alive',
                                           blocked_legs=blocked, connections=connections, faction=faction) is None:
        raise ValueError(f'没有到达{zone}自定营地的可用陆路。')
    if zone == guide['current_zone']:
        low, high = _camp_x_bounds(map_id, x, y)
        endpoints = [point for point in endpoints if low <= point[0] <= high]
    points = [MapPoint(zone, guide_point['zone_path'], f'自定刷怪点 ({px:.2f}, {py:.2f})', px, py)
              for px, py in endpoints if (zone, px, py) not in excluded]
    if not points:
        raise ValueError(f'{zone}的自定营地暂不可达或正在等待重试。')
    if zone == guide['current_zone'] and x is not None and y is not None:
        points.sort(key=lambda point: math.hypot(point.x - x, point.y - y))
    return dict(guide, guide_point=guide_point, point=asdict(points[0]),
                alternatives=[asdict(point) for point in points[1:]], manual_camp=True)


def _marked_camp_guides(primary, stages):
    yield primary
    seen = {primary['point']['zone']}
    url = primary['source_url'].split('#', 1)[0]
    for stage in sorted(stages, key=lambda item: item.number != primary['stage']):
        for point in stage.points:
            if point.zone in seen:
                continue
            seen.add(point.zone)
            yield dict(primary, point=asdict(point), stage=stage.number, level_range=stage.levels,
                       cross_zone=point.zone != primary['current_zone'],
                       source_url=f'{url}#step-{stage.number}', zone_url=_ORIGIN + point.zone_path,
                       primary_guide_point=primary['point'])


def _horde_camp_road_gap(map_id, level, x, y):
    from .walking_route import ashenvale_camp_origin, ashenvale_felwood_origin, camp_corridor_origin

    if map_id == 1440 and not ashenvale_camp_origin(x, y):
        if level >= 54 and ashenvale_felwood_origin(x, y):
            return ''
        return '当前尚未接入灰谷东南的已核对陆路'
    if map_id == 1424 and level >= 27 and not camp_corridor_origin(map_id, x, y):
        return '当前尚未接入希尔斯布莱德丘陵的已核对陆路'
    zones = {1417: '阿拉希高地西部', 1443: '凄凉之地', 1444: '菲拉斯北部', 1448: '费伍德森林'}
    if map_id in zones and not camp_corridor_origin(map_id, x, y):
        zone = zones[map_id]
        return f'当前尚未接入{zone}的已核对陆路'
    return ''


def find_grinding_point(faction, level, current_zone, x, y, *, excluded=frozenset(),
                        blocked_legs=frozenset(), connections=(), camp_routes=(), current_map_id=None,
                        fetch=_read_guide, cache=None, elevation=None, allow_taxi=False):
    """在线核对可达的野外刷怪区或玩家标记的营地。"""
    from .walking_route import (_RUTTHERAN_TAXI, _ruttheran_area, ashenvale_north_camp_origin, auberdine_overlapping_floor,
                                camp_travel_distance, connection_map_ids,
                                darkshore_camp_origin, darkshore_south_camp, loch_dig_camp_origin,
                                plan_walking_route, redridge_camp_origin, redridge_camp_requires_road,
                                source_road_blocks, teldrassil_camp_origin)

    if fetch is _read_guide:
        fetch = partial(fetch, deadline=monotonic() + _GUIDE_LOOKUP_SECONDS)
    current_zone = current_zone.strip()
    zone_ids = connection_map_ids(connections, camp_routes=camp_routes)
    source = zone_ids.get(current_zone)
    if source is not None and current_map_id is not None and source != current_map_id:
        raise ValueError('当前游戏地图编号与区域名称不符。')
    starter_zone = current_zone
    if faction == 'alliance' and current_zone == '达纳苏斯' and type(level) is int and 1 <= level <= 11:
        starter_zone = '泰达希尔'
    starter_camps = _STARTER_COMBAT_CAMPS.get((faction, starter_zone))
    guide, stages, starter = _select_leveling_point(faction, level, starter_zone, '', fetch, cache,
                                                   allow_starter=bool(camp_routes or starter_camps))
    if starter_zone != current_zone:
        guide = dict(guide, current_zone=current_zone, cross_zone=guide['point']['zone'] != current_zone)
        if starter:
            starter = dict(starter, current_zone=current_zone, cross_zone=True)
    source_blocks = source_road_blocks(source, x, y, elevation=elevation)
    blocked = blocked_legs | source_blocks
    guide_zone = guide['point']['zone']
    if camp_routes and excluded:
        excluded = excluded | {(zone, *endpoint) for zone, px, py in excluded
                               if (endpoint := _camp_endpoint(camp_routes, zone_ids.get(zone), px, py)) is not None}
    marked = None
    marked_errors = []
    if camp_routes:
        candidates = list(_marked_camp_guides(guide, stages))
        if starter and guide['cross_zone']:
            target = zone_ids.get(guide_zone)
            if target is None or plan_walking_route(source, target, level, 'alive', blocked_legs=blocked,
                                                    connections=connections, faction=faction) is None:
                candidates.append(dict(starter, primary_guide_point=guide['point']))
        for candidate in candidates:
            try:
                marked = _marked_camps(candidate, source, x, y, zone_ids, camp_routes, excluded, blocked, connections,
                                       faction)
            except ValueError as error:
                marked_errors.append(str(error))
            if marked:
                break
    starter_stage = guide['stage'] == 0
    if starter_stage:
        if marked:
            return marked
        if source is None or not starter_camps:
            raise ValueError('。'.join(marked_errors) or '当前新手区域没有已导入的自定营地。')
        catalog = {starter_zone: starter_camps}
        zones = (starter_zone,)
    else:
        if marked and (faction != 'alliance' or guide_zone not in _COMBAT_CAMPS):
            return marked
        catalog = _COMBAT_CAMPS if faction == 'alliance' else _HORDE_COMBAT_CAMPS
        catalog_fallback = (faction == 'alliance' or current_zone in catalog or guide_zone in catalog
                            or current_zone in ('石爪山脉', '提瑞斯法林地'))
        zones = tuple(dict.fromkeys((current_zone, guide_zone, *(catalog if catalog_fallback else ()))))
        if faction == 'horde' and level >= 55 and current_zone in ('诅咒之地', '悲伤沼泽'):
            zones = tuple(dict.fromkeys((*zones, '逆风小径')))
    if source is None or not catalog.keys() & zones:
        if marked_errors:
            raise ValueError(' '.join(marked_errors))
        raise ValueError('攻略提供了路线据点，但当前没有可达的已核对刷怪坐标。')
    if source == 1439 and auberdine_overlapping_floor(x, y) and not darkshore_camp_origin(x, y, elevation=elevation):
        if marked:
            return marked
        raise ValueError('奥伯丁飞行台尚未确认接入坡道，等待角色到达已核对的下坡段。')
    taxi_origin = (x, y) if allow_taxi and source in (1438, 1457) and x is not None and y is not None else None
    harbor = source == 1438 and _ruttheran_area(x, y)
    continent = 'eastern-kingdoms' if faction == 'alliance' else 'kalimdor'
    section = f'route-{faction}'
    failures = []
    for zone in zones:
        if zone not in catalog:
            continue
        legs = plan_walking_route(source, zone_ids[zone], level, 'alive',
                                  blocked_legs=blocked, connections=connections, faction=faction,
                                  origin=taxi_origin, allow_taxi=allow_taxi)
        if legs is None:
            continue
        if faction == 'horde' and source == 1439 and zone == '灰谷' and legs and not legs[0].manual:
            continue
        if (faction == 'alliance' and zone == '灰谷' and legs and legs[-1].source not in (1439, 1442)
                and not legs[-1].manual):
            continue
        slug, known = catalog[zone]
        deadwind = zone == '逆风小径'
        spawn = _camp_spawn_source(faction, zone, level)
        if zone == current_zone == '泰达希尔' and not harbor and not teldrassil_camp_origin(x, y):
            failures.append('当前位置尚未接入泰达希尔的已核对陆路')
            continue
        if (spawn and (faction == 'horde' or source in (1443, 1444, 1448))
                and (road_gap := _horde_camp_road_gap(source, level, x, y))):
            failures.append(road_gap)
            continue
        if (spawn and faction == 'alliance' and zone == '灰谷' and source == 1440
                and not ashenvale_north_camp_origin(x, y)):
            failures.append('当前位置尚未接入灰谷北部的已核对陆路')
            continue
        if zone in _SHARED_SPAWN_CAMPS or zone in ('灰谷', '泰达希尔'):
            zone_continent = 'kalimdor'
        elif deadwind or zone in ('提瑞斯法林地', '银松森林', '希尔斯布莱德丘陵', '阿拉希高地'):
            zone_continent = 'eastern-kingdoms'
        else:
            zone_continent = continent
        path = f'/zh/zones/{zone_continent}/{slug}/'
        eligible = []
        for low, high, name, px, py in known:
            if not low <= level <= high:
                continue
            marker = px, py
            stand = _CAMP_WALKABLE_POSITIONS.get((zone, *marker), marker)
            if zone == '洛克莫丹' and marker in LOCH_DIG_STANDS:
                if camp_routes and _camp_endpoint(camp_routes, zone_ids[zone], *marker) is not None:
                    stand = marker
                elif zone == current_zone and not loch_dig_camp_origin(x, y):
                    continue
            if ((zone, *stand) in excluded or (zone, px, py) in excluded
                    or (excluded and camp_routes and (endpoint := _camp_endpoint(camp_routes, zone_ids[zone], *stand))
                        and (zone, *endpoint) in excluded)):
                continue
            eligible.append(((px, py), MapPoint(zone, path, name, *stand)))
        if zone == current_zone:
            low, high = _camp_x_bounds(source, x, y)
            eligible = [(marker, point) for marker, point in eligible if low <= point.x <= high]
            if harbor:
                eligible = [(marker, point) for marker, point in eligible if plan_walking_route(
                    source, source, level, 'alive', blocked_legs=blocked, connections=connections,
                    faction=faction, origin=(x, y), destination_xy=(point.x, point.y)) is not None]
            if source == 1439 and darkshore_camp_origin(x, y, elevation=elevation):
                eligible = [(marker, point) for marker, point in eligible if darkshore_south_camp(point.x, point.y)]
            if source == 1433 and x is not None and y is not None and not redridge_camp_origin(x, y):
                before = len(eligible)
                eligible = [(marker, point) for marker, point in eligible if not redridge_camp_requires_road(point.x, point.y)]
                if before and not eligible:
                    failures.append('当前位置尚未接入赤脊山的已核对陆路。')
        elif legs and not legs[-1].manual and (legs[-1].source, legs[-1].destination) == (1426, 1432):
            eligible = [(marker, point) for marker, point in eligible if point.x <= 41.5]
        elif legs and legs[-1].taxi:
            eligible = [(marker, point) for marker, point in eligible if darkshore_south_camp(point.x, point.y)]
        if not eligible:
            continue
        if starter_stage and path != guide['point']['zone_path']:
            failures.append(f'{zone}攻略的区域链接与已核对的区域不一致')
            continue
        zone_url = _ORIGIN + path
        if deadwind:
            source_url, parse = _DEADWIND_GUIDE, _deadwind_marker_coordinates
        elif spawn:
            npc, source_url = spawn
            parse = lambda html: _spawn_marker_coordinates(html, npc, zone_ids[zone])
        else:
            source_url = zone_url
            parse = lambda html: _known_marker_coordinates(html, path, section, known)
        try:
            coordinates, cached = _load_guide_data(source_url, fetch, parse, cache)
        except (OSError, ValueError) as error:
            failures.append(f'{zone}攻略读取失败。{error}')
            continue
        points = [point for marker, point in eligible if marker in coordinates]
        if not points:
            failures.append(f'{zone}攻略没有已核对的刷怪区坐标')
            continue
        if zone == current_zone and x is not None and y is not None:
            points.sort(key=lambda point: camp_travel_distance(source, x, y, point.x, point.y))
        result = dict(guide, guide_point=guide['point'], point=asdict(points[0]),
                      alternatives=[asdict(point) for point in points[1:]],
                      cross_zone=zone != current_zone or (harbor and not _ruttheran_area(points[0].x, points[0].y)),
                      source_url=source_url if source_url != zone_url else f'{source_url}#{section}',
                      zone_url=zone_url)
        if cached:
            result['cached_sources'] = [*guide.get('cached_sources', ()), source_url]
        return result
    if marked:
        return marked
    if (harbor and faction == 'alliance' and current_zone == '泰达希尔' and level in (12, 13)
            and _RUTTHERAN_TAXI in blocked_legs):
        # 只有航线已被本次查询排除时，才回到仍适合练级的高地营地。
        fallback = find_grinding_point(faction, 11, current_zone, x, y, excluded=excluded,
                                       blocked_legs=blocked_legs, connections=connections,
                                       current_map_id=current_map_id, fetch=fetch, cache=cache, elevation=elevation)
        return dict(fallback, level=level, primary_guide_point=guide['point'])
    failures.extend(marked_errors)
    if source == 1453 and source_blocks:
        failures.append('当前位置尚未接入暴风城贸易区至正门的已核对陆路。')
    if source == 1457 and source_blocks:
        failures.append('当前位置尚未接入达纳苏斯的已核对城内道路。')
    if failures:
        raise ValueError('。'.join(failures))
    if excluded or blocked_legs:
        raise ValueError('当前没有可达的已核对刷怪点，受阻路段或营地仍在等待重试。')
    if starter_stage:
        raise ValueError('当前等级没有已核对的新手区刷怪点。')
    if current_zone == '洛克莫丹':
        raise ValueError('当前等级和湖岸没有已核对的可达刷怪点。')
    if faction == 'alliance' and current_zone in ('泰达希尔', '达纳苏斯', '黑海岸', '灰谷'):
        raise ValueError('当前位置和等级没有已核对的可达刷怪点。')
    if (current_zone in ('湿地', '悲伤沼泽', '诅咒之地', '逆风小径', '提瑞斯法林地', '银松森林', '希尔斯布莱德丘陵')
            or faction == 'horde' and current_zone == '阿拉希高地'):
        raise ValueError('当前等级没有已核对的可达刷怪点。')
    return guide


def write_leveling_result(path, result):
    _replace_text_file(path, json.dumps(result, ensure_ascii=False, indent=2) + '\n')


def read_recent_travel(path):
    try:
        with Path(path).open('rb') as stream:
            age = time() - fstat(stream.fileno()).st_mtime
            if not 0 <= age <= _TRAVEL_RESUME_SECONDS:
                return None
            raw = stream.read(32_769)
        if len(raw) > 32_768:
            return None
        record = json.loads(raw)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def read_leveling_travel(path, identity, map_id, *, allow_level_increase=False):
    """接续同一角色近期尚未抵达营地的步行或飞行路线。"""
    record = read_recent_travel(path)
    if record is None:
        return None
    saved_identity = record.get('character')
    if saved_identity != identity and not (
            allow_level_increase and isinstance(saved_identity, list)
            and saved_identity[:-1] == identity[:-1]
            and type(identity[-1]) is int
            and type(saved_identity[-1]) is int and 0 < saved_identity[-1] < identity[-1]):
        return None
    maps, point = record.get('walking_maps'), record.get('point')
    if (not isinstance(maps, list) or not 1 <= len(maps) <= 32
            or any(type(value) is not int or value <= 0 for value in maps)
            or map_id not in maps or not isinstance(point, dict)):
        return None
    if (not all(isinstance(point.get(key), str) and 0 < len(point[key]) <= 160 for key in ('zone', 'name'))
            or not all(type(point.get(key)) in (int, float) and 0 < point[key] < 100 for key in ('x', 'y'))):
        return None
    blocked = record.get('blocked_connections')
    if (not isinstance(blocked, list) or len(blocked) > 64
            or any(not isinstance(road, list) or len(road) not in (7, 8)
                   or any(type(value) not in (int, float, bool) for value in road[:7])
                   or (len(road) == 8 and (not isinstance(road[7], str) or len(road[7]) != 64))
                   for road in blocked)):
        return None
    return record


def _replace_text_file(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf8', newline='', dir=path.parent, delete=False) as temp:
            temporary = Path(temp.name)
            temp.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_leveling_lookup(data_dir, faction, level, current_zone, completed_point, *, read_character=None):
    try:
        character = read_character() if read_character else None
        if character is not None:
            faction, level, current_zone = character.faction, character.level, character.zone
        result = find_leveling_point(faction, level, current_zone, completed_point=completed_point)
    except (OSError, ValueError, NotImplementedError) as error:
        result = {'ok': False, 'error': str(error)}
    else:
        result['ok'] = True
        if character is not None:
            result['character'] = asdict(character)
    write_leveling_result(Path(data_dir) / 'leveling-next.json', result)
    return int(not result['ok'])


class AutomaticLeveling:
    """由监控帧驱动，联网任务在后台执行。"""

    def __init__(self, submit, *, cache=None):
        self._submit = submit
        self._cache = cache
        self._observed = None
        self._first_seen = 0
        self._pending = None
        self._last_result = None
        self._last_camp_death = None
        self._camp_context = None
        self._retired_camps = {}
        self._blocked_legs = {}

    def _camp_exclusions(self, session, character, now_ms):
        context = session, character.faction, character.level
        if context != self._camp_context:
            self._camp_context = context
            self._retired_camps.clear()
            self._blocked_legs.clear()
        self._retired_camps = {camp: retry for camp, retry in self._retired_camps.items() if now_ms < retry}
        self._blocked_legs = {leg: retry for leg, retry in self._blocked_legs.items() if now_ms < retry}
        return frozenset(self._retired_camps)

    def retire_camp(self, session, character, destination, now_ms, *, zone=None, after_deaths=False):
        self.retire_point(session, character, zone or character.zone, destination.x, destination.y, now_ms,
                          after_deaths=after_deaths)

    def retire_point(self, session, character, zone, x, y, now_ms, *, after_deaths=False):
        self._camp_exclusions(session, character, now_ms)
        key = zone, x, y
        retry = now_ms + (_CAMP_DEATH_RETRY_MS if after_deaths else _CAMP_RETRY_MS)
        self._retired_camps[key] = max(retry, self._retired_camps.get(key, 0))
        self.request_replan()

    def request_replan(self):
        self._last_result = None
        if self._pending is not None:
            # 旧查询可继续完成网络请求，但不能再提交选点结果。
            self._pending = None, self._pending[1]

    def record_camp_death(self, session, character, destination, now_ms):
        """同一监控会话、等级和营地在五分钟内两次阵亡时换点。"""
        key = session, character.route_key, destination
        previous = self._last_camp_death
        if previous and previous[0] == key and now_ms - previous[1] <= _CAMP_DEATH_WINDOW_MS:
            self._last_camp_death = None
            return True
        self._last_camp_death = key, now_ms
        return False

    def retire_travel(self, session, character, destination, zone, blocked_legs, now_ms):
        self.retire_camp(session, character, destination, now_ms, zone=zone)
        for leg in blocked_legs:
            self._blocked_legs[leg] = now_ms + _CAMP_RETRY_MS

    def observe(self, session, character, now_ms, *, grinding=False, connections=(), camp_routes=(), allow_taxi=False):
        from .walking_route import (ashenvale_north_camp_origin, loch_dig_camp_origin, redridge_camp_origin,
                                    source_road_blocks, teldrassil_camp_origin)

        excluded = self._camp_exclusions(session, character, now_ms) if grinding and character else frozenset()
        blocked = frozenset(self._blocked_legs) if grinding and character else frozenset()
        key = None
        if character and character.simplified_chinese:
            location = None
            if grinding:
                # 只在可达范围发生变化时作废查询，同一湖岸的移动不会重复联网。
                location = (source_road_blocks(character.map_id, character.x, character.y, elevation=character.elevation),
                            _camp_x_bounds(character.map_id, character.x, character.y))
                if character.map_id == 1432:
                    location += (loch_dig_camp_origin(character.x, character.y),)
                if character.map_id == 1433:
                    location += (redridge_camp_origin(character.x, character.y),)
                if character.map_id == 1438:
                    location += (teldrassil_camp_origin(character.x, character.y),)
                if character.faction == 'alliance' and character.map_id == 1440:
                    location += (ashenvale_north_camp_origin(character.x, character.y),)
                if (character.map_id in (1443, 1444, 1448)
                        or character.faction == 'horde' and character.map_id in (1417, 1424, 1440)):
                    location += (not _horde_camp_road_gap(character.map_id, character.level,
                                                         character.x, character.y),)
            key = session, character.route_key, excluded, blocked, connections, camp_routes, location, allow_taxi
        if key != self._observed:
            self._observed = key
            self._first_seen = now_ms
        if key is None or now_ms - self._first_seen < 250:
            return None
        if self._pending is not None:
            pending_key, future = self._pending
            if not future.done():
                return None
            self._pending = None
            if pending_key == key:
                try:
                    result = dict(future.result(), ok=True)
                    retry_at = None
                except (OSError, ValueError) as error:
                    result = {'ok': False, 'error': str(error)}
                    retry_at = now_ms + 60_000
                self._last_result = key, retry_at
                result['character'] = asdict(character)
                if blocked:
                    result['blocked_roads'] = sorted({(leg.source, leg.destination) for leg in blocked})
                    result['blocked_connections'] = sorted({leg.blocked_key for leg in blocked})
                return result
        if self._last_result is not None:
            last_key, retry_at = self._last_result
            if key == last_key and (retry_at is None or now_ms < retry_at):
                return None
        args = character.faction, character.level, character.zone
        options = {'cache': self._cache} if self._cache is not None else {}
        if grinding:
            if allow_taxi:
                options['allow_taxi'] = True
            if character.elevation is not None:
                options['elevation'] = character.elevation
            if blocked:
                options['blocked_legs'] = blocked
            if connections:
                options['connections'] = connections
            if camp_routes:
                options['camp_routes'] = camp_routes
            future = self._submit(find_grinding_point, *args, character.x, character.y, excluded=excluded,
                                  current_map_id=character.map_id, **options)
        else:
            future = self._submit(find_leveling_point, *args, **options)
        self._pending = key, future
        return None
