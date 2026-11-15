from concurrent.futures import Future
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'desktop')]

import run_dev
from tests import test_addon_full_load as full_load
from wowbuddy.automation.arrival_pull import ArrivalPull
from wowbuddy.engine.assets import Assets
from wowbuddy.core.auto_target import PACKET_BASE
from wowbuddy.win32.capture import Rect
from wowbuddy.engine.character_state import (CharacterState, DeathState, MobState, NavigationState, TargetBearing, decode_character_session,
                                      decode_character_state,
                                      decode_death_state, decode_navigation_state, decode_target_rejection)
from wowbuddy.automation.corpse_loot import CorpseLoot
from wowbuddy.automation.death_recovery import AutomaticRevival, CorpseAccess
from wowbuddy.automation.leveling_route import AutomaticLeveling, LevelingGuideCache, find_grinding_point, find_leveling_point
from wowbuddy.automation.navigation import ForegroundMovement, MapDestination, MapNavigator, TargetApproach
from wowbuddy.core.old_protocol import OldFrame
from wowbuddy.core.pixel_geometry import RGBImage
from wowbuddy.engine.pipeline import Decision
from wowbuddy.engine.scheduler import TickResult
from wowbuddy.automation.walking_route import ZONE_MAP_IDS, WalkingTrip, camp_access_road, plan_walking_route
from wowbuddy.win32.windows_mouse import Win32Mouse


def leg(zone, slug, points):
    return (
        '<div class="lvs-leg__text"><h4>'
        f'<a href="/zh/zones/eastern-kingdoms/{slug}/#route-alliance">{zone}</a></h4>'
        '<ol class="lvs-hubs">' + ''.join(
            f'<li><span class="lvs-hub-name">{name}</span><code>{coords}</code></li>'
            for name, coords in points) + '</ol></div>')


def stage(number, levels, *legs):
    return (f'<article class="lvs" data-step="{number}">'
            f'<p class="lvs-meta">{levels} 级<span>你在这里</span></p>'
            + ''.join(legs) + '</article>')


GUIDE = '<div class></div>' + stage(1, '12–17', leg('西部荒野', 'westfall', [
    ('哨兵岭', '57.0, 47.2'), ('无坐标点', ''), ('无效坐标', '120.0, 55.0'),
    ('萨丁农场', '56.0, 31.2')])) + stage(2, '16–21', leg('黑海岸', 'darkshore', [
    ('奥伯丁', '37.0, 44.1')]))


class LevelingLookupTests(unittest.TestCase):
    def test_teldrassil_starter_selects_verified_camps_and_waits_for_transport_at_twelve(self):
        guide = ('<article class="lvs-start"><h3><a href="/zh/zones/kalimdor/teldrassil/#route-alliance">'
                 '泰达希尔</a><small>1–11</small></h3></article>' + GUIDE)
        levels = ((1, '1984', 'young-thistle-boar', (58.508, 45.665)),
                  (3, '1985', 'thistle-boar', (61.825, 38.655)),
                  (5, '2042', 'nightsaber', (53.628, 55.608)),
                  (7, '2043', 'nightsaber-stalker', (40.504, 55.571)),
                  (10, '2034', 'feral-nightsaber', (39.91, 28.687)))
        pages = {'https://wowhandbook.com/zh/leveling/alliance/': guide}
        for _, npc, slug, (x, y) in levels:
            pages[f'https://forever-tavern.com/npcs/classic/{npc}-{slug}/'] = (
                f'<a data-entity-pin data-zone="1438" data-source-id="{npc}" '
                f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>')
        position = 58.7, 44.3
        for level, npc, slug, point in levels:
            with self.subTest(level=level):
                result = find_grinding_point('alliance', level, '泰达希尔', *position, fetch=pages.__getitem__)
                self.assertEqual(result['stage'], 0)
                self.assertEqual((result['point']['x'], result['point']['y']), point)
                self.assertIn(f'{npc}-{slug}', result['source_url'])
                position = point
        with self.assertRaisesRegex(ValueError, '未接入泰达希尔'):
            find_grinding_point('alliance', 7, '泰达希尔', 67, 25, fetch=pages.__getitem__)
        with self.assertRaisesRegex(ValueError, '没有已核对的可达刷怪点'):
            find_grinding_point('alliance', 12, '泰达希尔', *position, fetch=pages.__getitem__)
        result = find_grinding_point('alliance', 10, '达纳苏斯', 81.76657, 40.28688, current_map_id=1457,
                                     fetch=pages.__getitem__)
        self.assertEqual(result['current_zone'], '达纳苏斯')
        self.assertTrue(result['cross_zone'])
        self.assertEqual((result['point']['zone'], result['point']['x'], result['point']['y']),
                         ('泰达希尔', 39.91, 28.687))
        result = find_grinding_point('alliance', 10, '泰达希尔', 58.40098, 93.91529, current_map_id=1438,
                                     fetch=pages.__getitem__)
        self.assertTrue(result['cross_zone'])
        self.assertEqual((result['point']['x'], result['point']['y']), (39.91, 28.687))
        with self.assertRaisesRegex(ValueError, '尚未接入达纳苏斯'):
            find_grinding_point('alliance', 10, '达纳苏斯', 29.13, 41.21, fetch=pages.__getitem__)

    def test_darkshore_early_camps_requery_spawn_sources_after_upgrading(self):
        guide = stage(1, '12–16', leg('黑海岸', 'darkshore', [('奥伯丁', '37,44.1')]))
        choices = (
            (12, '2321', 'foreststrider-fledgling', (38.953, 48.684), (39.758, 57.378)),
            (14, '2069', 'moonstalker', (40.045, 65.983), (40.583, 70.028)),
            (16, '2165', 'grizzled-thistle-bear', (39.065, 69.96), (40.287, 75.878)),
        )
        pages = {'https://wowhandbook.com/zh/leveling/alliance/': guide}
        for _, npc, slug, first, second in choices:
            pages[f'https://forever-tavern.com/npcs/classic/{npc}-{slug}/'] = ''.join(
                f'<a data-entity-pin data-zone="1439" data-source-id="{npc}" '
                f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>'
                for x, y in (first, second))
        position = 39.98, 48
        for level, npc, slug, first, second in choices:
            with self.subTest(level=level):
                result = find_grinding_point('alliance', level, '黑海岸', *position, fetch=pages.__getitem__)
                self.assertIn(f'{npc}-{slug}', result['source_url'])
                self.assertEqual((result['point']['x'], result['point']['y']), first)
                self.assertEqual([(p['x'], p['y']) for p in result['alternatives']], [second])
                position = first

        result = find_grinding_point('alliance', 12, '泰达希尔', 39.91, 28.687,
                                     fetch=pages.__getitem__, allow_taxi=True)
        self.assertTrue(result['cross_zone'])
        self.assertEqual(result['point']['zone'], '黑海岸')
        self.assertEqual((result['point']['x'], result['point']['y']), choices[0][3])

    def test_failed_ruttheran_flight_reselects_a_reachable_highland_camp(self):
        from wowbuddy.automation.walking_route import _RUTTHERAN_FLIGHT_ROAD, _RUTTHERAN_TAXI

        starter = ('<article class="lvs-start"><h3><a href="/zh/zones/kalimdor/teldrassil/#route-alliance">'
                   '泰达希尔</a><small>1–11</small></h3></article>')
        guide = starter + stage(1, '12–16', leg('黑海岸', 'darkshore', [('奥伯丁', '37,44.1')]))
        spawn = ('<a data-entity-pin data-zone="1438" data-source-id="2034" '
                 'data-source-x="39.91" data-source-y="28.687" data-pin-label="Source spawn"></a>')
        pages = {'https://wowhandbook.com/zh/leveling/alliance/': guide,
                 'https://forever-tavern.com/npcs/classic/2034-feral-nightsaber/': spawn}
        harbor = _RUTTHERAN_FLIGHT_ROAD[-1]
        options = dict(fetch=pages.__getitem__, current_map_id=1438, allow_taxi=True,
                       blocked_legs=frozenset((_RUTTHERAN_TAXI,)))
        for level in (12, 13):
            result = find_grinding_point('alliance', level, '泰达希尔', *harbor, **options)
            self.assertEqual(result['level'], level)
            self.assertTrue(result['cross_zone'])
            self.assertEqual(result['point']['zone'], '泰达希尔')
            self.assertEqual(result['primary_guide_point']['zone'], '黑海岸')
            legs = plan_walking_route(1438, 1438, level, 'alive', faction='alliance', origin=harbor,
                                      destination_xy=(result['point']['x'], result['point']['y']))
            self.assertEqual([leg.destination for leg in legs], [1457, 1438])
        with self.assertRaisesRegex(ValueError, '没有可达'):
            find_grinding_point('alliance', 14, '泰达希尔', *harbor, **options)

    def test_darkshore_selects_nearby_verified_spawns_and_changes_species_at_level_twenty(self):
        guide = stage(1, '16–21', leg('黑海岸', 'darkshore', [('奥伯丁', '37,44.1')]))
        sire = 'https://forever-tavern.com/npcs/classic/2237-moonstalker-sire/'
        matriarch = 'https://forever-tavern.com/npcs/classic/2071-moonstalker-matriarch/'

        def pins(npc, points, map_id=1439):
            return ''.join(
                f'<a data-entity-pin data-zone="{map_id}" data-source-id="{npc}" data-source-x="{x}" '
                f'data-source-y="{y}" data-pin-label="Source spawn"></a>'
                for x, y in points
            )

        pages = {
            'https://wowhandbook.com/zh/leveling/alliance/': guide,
            sire: pins('2237', ((39.8, 70.691), (38.315, 77.167), (60.068, 13.373))),
            matriarch: pins('2071', ((36.894, 89.675), (39.851, 90.339), (60.956, 11.87))),
        }
        args = '黑海岸', 43.3, 57.6
        options = {'fetch': pages.__getitem__, 'current_map_id': 1439}
        current = find_grinding_point('alliance', 18, *args, **options)
        self.assertEqual((current['point']['x'], current['point']['y']), (39.8, 70.691))
        self.assertEqual(current['source_url'], sire)
        self.assertEqual(current['zone_url'], 'https://wowhandbook.com/zh/zones/kalimdor/darkshore/')
        self.assertFalse(current['cross_zone'])
        self.assertEqual([(p['x'], p['y']) for p in current['alternatives']], [(38.315, 77.167)])
        alternative = find_grinding_point('alliance', 18, *args, **options,
                                          excluded={('黑海岸', 39.8, 70.691)})
        self.assertEqual((alternative['point']['x'], alternative['point']['y']), (38.315, 77.167))
        upgraded = find_grinding_point('alliance', 20, *args, **options)
        self.assertEqual(upgraded['source_url'], matriarch)
        self.assertTrue(all('雌虎' in point['name'] for point in (upgraded['point'], *upgraded['alternatives'])))
        pages[sire] = pins('2237', ((39.8, 70.691),), map_id=1440)
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            find_grinding_point('alliance', 18, *args, **options)

    def test_darkshore_upgrade_selects_an_ashenvale_spawn_instead_of_the_unreachable_guide_hub(self):
        guide = (stage(1, '16–21', leg('黑海岸', 'darkshore', [('奥伯丁', '37,44.1')]))
                 + stage(2, '22–24', leg('赤脊山', 'redridge-mountains', [('三角路口', '10.2,71.5')])))
        wolf = 'https://forever-tavern.com/npcs/classic/3823-ghostpaw-runner/'
        points = ((29.803, 19.749), (27.094, 18.591), (27.021, 26.203))
        pages = {
            'https://wowhandbook.com/zh/leveling/alliance/': guide,
            wolf: ''.join(
                f'<a data-entity-pin data-zone="1440" data-source-id="3823" data-source-x="{x}" '
                f'data-source-y="{y}" data-pin-label="Source spawn"></a>' for x, y in points),
        }
        options = {'fetch': pages.__getitem__}
        self.assertEqual(find_leveling_point('alliance', 22, '黑海岸', **options)['point']['zone'], '赤脊山')
        result = find_grinding_point('alliance', 22, '黑海岸', 39.851, 90.339, **options)
        self.assertTrue(result['cross_zone'])
        self.assertEqual(result['guide_point']['zone'], '赤脊山')
        self.assertEqual(result['source_url'], wolf)
        self.assertEqual(result['point']['zone_path'], '/zh/zones/kalimdor/ashenvale/')
        self.assertEqual((result['point']['x'], result['point']['y']), points[0])
        with self.assertRaisesRegex(ValueError, '没有已核对的可达刷怪点'):
            find_grinding_point('alliance', 22, '黑海岸', 60.956, 11.87, **options)
        resumed = find_grinding_point('alliance', 22, '灰谷', *points[0], **options,
                                       excluded={('灰谷', *points[0])})
        self.assertFalse(resumed['cross_zone'])
        self.assertEqual((resumed['point']['x'], resumed['point']['y']), points[1])

    def test_alliance_ashenvale_level_changes_requery_the_spawn_map(self):
        guide = stage(1, '23–35', leg('灰谷', 'ashenvale', [('阿斯特兰纳', '36.6,49.6')]))
        camps = ((31.378, 45.238), (32.045, 43.145), (32.633, 42.161))
        felfire = ((80.615, 68.224), (81.469, 69.206))
        dread_swoop = ((59.928, 13.372), (59.774, 24.319))
        sources = {
            'https://wowhandbook.com/zh/leveling/alliance/': guide,
            'https://forever-tavern.com/npcs/classic/3823-ghostpaw-runner/':
                '<a data-entity-pin data-zone="1440" data-source-id="3823" '
                'data-source-x="27.021" data-source-y="26.203" data-pin-label="Source spawn"></a>',
            'https://forever-tavern.com/npcs/classic/3925-thistlefur-avenger/': ''.join(
                f'<a data-entity-pin data-zone="1440" data-source-id="3925" data-source-x="{x}" '
                f'data-source-y="{y}" data-pin-label="Source spawn"></a>' for x, y in camps),
            'https://forever-tavern.com/npcs/classic/3825-ghostpaw-alpha/':
                '<a data-entity-pin data-zone="1440" data-source-id="3825" '
                'data-source-x="66.573" data-source-y="70.074" data-pin-label="Source spawn"></a>',
            'https://forever-tavern.com/npcs/classic/6073-searing-infernal/': ''.join(
                f'<a data-entity-pin data-zone="1440" data-source-id="6073" data-source-x="{x}" '
                f'data-source-y="{y}" data-pin-label="Source spawn"></a>' for x, y in felfire),
            'https://forever-tavern.com/npcs/classic/4692-dread-swoop/': ''.join(
                f'<a data-entity-pin data-zone="1443" data-source-id="4692" data-source-x="{x}" '
                f'data-source-y="{y}" data-pin-label="Source spawn"></a>' for x, y in dread_swoop),
        }
        args = '灰谷', 27.021, 26.203
        options = {'fetch': sources.__getitem__, 'current_map_id': 1440}
        current = find_grinding_point('alliance', 24, *args, **options)
        self.assertIn('幽爪奔跑者', current['point']['name'])
        upgraded = find_grinding_point('alliance', 25, *args, **options)
        self.assertFalse(upgraded['cross_zone'])
        self.assertIn('3925-thistlefur-avenger', upgraded['source_url'])
        choices = upgraded['point'], *upgraded['alternatives']
        self.assertEqual({(p['x'], p['y']) for p in choices}, set(camps))
        picked = upgraded['point']
        self.assertEqual((picked['x'], picked['y']), camps[0])
        alternate = find_grinding_point('alliance', 27, *args, **options,
                                        excluded={('灰谷', picked['x'], picked['y'])})
        self.assertNotEqual(alternate['point'], picked)
        renewed = find_grinding_point('alliance', 28, '灰谷', *camps[0], **options)
        self.assertEqual((renewed['point']['x'], renewed['point']['y']), (66.573, 70.074))
        self.assertIn('3825-ghostpaw-alpha', renewed['source_url'])
        infernals = find_grinding_point('alliance', 32, '灰谷', 66.573, 70.074, **options)
        self.assertIn('6073-searing-infernal', infernals['source_url'])
        choices = infernals['point'], *infernals['alternatives']
        self.assertEqual(tuple((p['x'], p['y']) for p in choices), felfire)
        alternate = find_grinding_point('alliance', 34, '灰谷', *felfire[0], **options,
                                        excluded={('灰谷', *felfire[0])})
        self.assertEqual((alternate['point']['x'], alternate['point']['y']), felfire[1])
        onward = find_grinding_point('alliance', 35, '灰谷', *felfire[0], **options)
        self.assertTrue(onward['cross_zone'])
        self.assertIn('4692-dread-swoop', onward['source_url'])
        self.assertEqual((onward['point']['x'], onward['point']['y']), dread_swoop[0])
        with self.assertRaisesRegex(ValueError, '灰谷北部'):
            find_grinding_point('alliance', 25, '灰谷', 73.0, 61.0, **options)

    def test_grinding_uses_reachable_guide_points_when_the_next_stage_has_no_land_route(self):
        guide = (
            stage(1, '40–44', leg('塔纳利斯', 'tanaris', [('加基森', '51.8,27')]))
            + stage(2, '44–50', leg('悲伤沼泽', 'swamp-of-sorrows', [('斯通纳德', '46,54')]))
        )
        source = 'https://forever-tavern.com/npcs/classic/5618-wastewander-bandit/'
        pins = ''.join(
            f'<a data-entity-pin data-zone="1446" data-source-id="5618" data-source-x="{x}" '
            f'data-source-y="{y}" data-pin-label="Source spawn"></a>'
            for x, y in ((59.402, 24.706), (60.854, 23.483))
        )
        fetch = Mock(side_effect=lambda url: pins if url == source else guide)
        self.assertEqual(find_leveling_point('horde', 44, '塔纳利斯', fetch=fetch)['point']['zone'], '悲伤沼泽')
        args = 'horde', 44, '塔纳利斯', 58, 25
        result = find_grinding_point(*args, fetch=fetch)
        self.assertEqual((result['cross_zone'], result['point']['name']), (False, '废土强盗西侧营地'))
        self.assertEqual(result['source_url'], source)
        result = find_grinding_point(*args, fetch=fetch, excluded=frozenset({('塔纳利斯', 59.402, 24.706)}))
        self.assertEqual(result['point']['name'], '废土强盗东侧营地')
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point(*args, fetch=fetch,
                                excluded=frozenset({('塔纳利斯', 59.402, 24.706), ('塔纳利斯', 60.854, 23.483)}))
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            find_grinding_point(*args, fetch=lambda url: '' if url == source else guide)
        with self.assertRaisesRegex(ValueError, '没有可达的已核对刷怪坐标'):
            find_grinding_point('horde', 30, '千针石林', 58, 25,
                                fetch=lambda _: stage(1, '25–35', leg('千针石林', 'thousand-needles',
                                                                      [('乱风岗', '45.7,50.7')])))

    def test_starter_guide_prioritizes_marked_camps_in_the_current_zone(self):
        from wowbuddy.automation.manual_routes import parse_manual_route

        starter = ('<article class="lvs-start"><figure class="lvs-map"><span class="lvs-marker" '
                   'style="left:20%;top:30%" title="北郡修道院">1</span></figure><h3>'
                   '<a href="/zh/zones/eastern-kingdoms/elwynn-forest/#route-alliance">艾尔文森林</a> '
                   '<small>1–13</small></h3></article>')
        fetch = Mock(return_value=starter + GUIDE)
        routes = tuple(map(parse_manual_route, ('WBDROUTE1|1429|4000,5000|4200,5100',
                                                'WBDROUTE2|1429|艾尔文森林|4500,5500|4700,5700',
                                                'WBDROUTE2|1436|西部荒野|4000,4000|4200,4200')))
        opts = {'camp_routes': routes, 'current_map_id': 1429, 'fetch': fetch}
        result = find_grinding_point('alliance', 6, '艾尔文森林', 42, 50, **opts)
        self.assertTrue(result['manual_camp'])
        self.assertFalse(result['cross_zone'])
        self.assertEqual((result['point']['x'], result['point']['y']), (42, 51))
        self.assertEqual((result['alternatives'][0]['x'], result['alternatives'][0]['y']), (47, 57))
        self.assertEqual(result['level_range'], (1, 13))
        self.assertTrue(result['source_url'].endswith('#lv-1'))
        fetch.assert_called_once_with('https://wowhandbook.com/zh/leveling/alliance/')
        alternate = find_grinding_point('alliance', 6, '艾尔文森林', 42, 50, **opts,
                                        excluded=frozenset({('艾尔文森林', 42, 51)}))
        self.assertEqual((alternate['point']['x'], alternate['point']['y']), (47, 57))
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point('alliance', 6, '艾尔文森林', 42, 50, **opts,
                               excluded=frozenset({('艾尔文森林', 42, 51), ('艾尔文森林', 47, 57)}))
        with self.assertRaisesRegex(ValueError, '地图编号'):
            find_grinding_point('alliance', 6, '艾尔文森林', 42, 50, **dict(opts, current_map_id=1436))
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            find_grinding_point('alliance', 6, '艾尔文森林', 42, 50, **dict(opts, camp_routes=routes[-1:]))
        with self.assertRaisesRegex(ValueError, '带坐标路线'):
            find_grinding_point('alliance', 6, '西部荒野', 42, 50, **dict(opts, current_map_id=1436))
        with self.assertRaisesRegex(ValueError, '带坐标路线'):
            find_leveling_point('alliance', 6, '艾尔文森林', fetch=fetch)
        self.assertEqual(find_leveling_point('alliance', 12, '艾尔文森林', fetch=fetch)['point']['zone'], '西部荒野')

    def test_builtin_starter_camps_match_level_and_verified_faction_markers(self):
        path = '/zh/zones/kalimdor/durotar/'
        guide = (f'<article class="lvs-start"><h3><a href="{path}#route-horde">杜隆塔尔</a>'
                 '<small>1–12</small></h3></article>'
                 + stage(1, '12–17', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')])))

        def marker(x, y):
            return f'<a class="route-coords" href="{path}?pin={x},{y}#map">标点</a>'

        zone = ('<section id="route-horde">' + marker(44.49, 65.1) + marker(41.83, 65.81)
                + marker(51.43, 20.86) + '</section>'
                '<section id="route-alliance">' + marker(43.63, 24.14) + '</section>')
        fetch = Mock(side_effect=lambda url: zone if url.endswith(path) else guide)
        options = {'current_map_id': 1411, 'fetch': fetch}

        def select(level, **extra):
            return find_grinding_point('horde', level, '杜隆塔尔', 43.3, 68.5, **(options | extra))

        first = select(1)
        self.assertEqual(first['stage'], 0)
        self.assertFalse(first['cross_zone'])
        self.assertEqual((first['point']['x'], first['point']['y']), (44.49, 65.1))
        self.assertTrue(first['source_url'].endswith(path + '#route-horde'))
        alternate = select(3, excluded=frozenset({('杜隆塔尔', 44.49, 65.1)}))
        self.assertEqual((alternate['point']['x'], alternate['point']['y']), (41.83, 65.81))
        later = select(11)
        self.assertEqual((later['point']['x'], later['point']['y']), (51.43, 20.86))
        self.assertEqual(later['alternatives'], [])
        with self.assertRaisesRegex(ValueError, '等待重试'):
            select(1, excluded=frozenset({('杜隆塔尔', 44.49, 65.1)}))
        with self.assertRaisesRegex(ValueError, '地图编号'):
            select(1, current_map_id=1413)
        with self.assertRaisesRegex(ValueError, '攻略的区域链接'):
            select(1, fetch=lambda _: guide.replace('/durotar/', '/mulgore/'))
        fetch.reset_mock()
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            select(12)
        self.assertTrue(all(not call.args[0].endswith(path) for call in fetch.call_args_list))

    def test_dun_morogh_starter_camps_and_loch_modan_handoff(self):
        dun = '/zh/zones/eastern-kingdoms/dun-morogh/'
        loch = '/zh/zones/eastern-kingdoms/loch-modan/'
        guide = (f'<article class="lvs-start"><h3><a href="{dun}#route-alliance">丹莫罗</a>'
                 '<small>1–13</small></h3></article>' + GUIDE)

        def page(path, points):
            return '<section id="route-alliance">' + ''.join(
                f'<a class="route-coords" href="{path}?pin={x},{y}#map">营地</a>' for x, y in points) + '</section>'

        markers = ((30.79, 72.95), (31.05, 73.95), (22.74, 72.42), (25.86, 78.26),
                   (42.9, 49.6), (55.1, 45.4), (69.65, 57.08), (70.67, 56.64))
        pages = {'/zh/leveling/alliance/': guide, dun: page(dun, markers), loch: page(loch, ((31.5, 72.1),))}
        x, y = 29.9, 71.2
        for level in range(1, 13):
            with self.subTest(level=level):
                result = find_grinding_point('alliance', level, '丹莫罗', x, y, current_map_id=1426,
                                             fetch=lambda url: pages[url.removeprefix('https://wowhandbook.com')])
                point = result['point']
                self.assertEqual(point['zone'], '丹莫罗' if level < 12 else '洛克莫丹')
                if level < 12:
                    self.assertEqual(result['stage'], 0)
                    x, y = point['x'], point['y']
        self.assertEqual((x, y), (70.67, 56.64))
        with self.assertRaisesRegex(ValueError, '地图编号'):
            find_grinding_point('alliance', 1, '丹莫罗', 29.9, 71.2, current_map_id=1432, fetch=lambda _: guide)

    def test_tirisfal_levels_into_silverpine_using_checked_land_camps(self):
        tirisfal = '/zh/zones/eastern-kingdoms/tirisfal-glades/'
        silverpine = '/zh/zones/eastern-kingdoms/silverpine-forest/'
        guide = (f'<article class="lvs-start"><h3><a href="{tirisfal}#route-horde">提瑞斯法林地</a>'
                 '<small>1–13</small></h3></article>'
                 + stage(1, '12–18', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')])))

        def page(path, points):
            return '<section id="route-horde">' + ''.join(
                f'<a class="route-coords" href="{path}?pin={x},{y}#map">营地</a>' for x, y in points) + '</section>'

        markers = ((30.7, 64.17), (32.98, 63.0), (29.4, 59.42), (34.56, 62.55), (35.94, 68.59),
                   (58.3, 58.28), (56.5, 46.09), (58.59, 37.5), (74.16, 62.79))
        pages = {'/zh/leveling/horde/': guide, tirisfal: page(tirisfal, markers),
                 silverpine: page(silverpine, ((54.88, 13.61), (54.85, 54.4)))}

        def fetch(url):
            return pages[url.removeprefix('https://wowhandbook.com')]

        zone, map_id, x, y = '提瑞斯法林地', 1420, 30.22, 71.65
        for level in range(1, 19):
            with self.subTest(level=level):
                result = find_grinding_point('horde', level, zone, x, y, current_map_id=map_id, fetch=fetch)
                point = result['point']
                self.assertEqual(point['zone'], '提瑞斯法林地' if level < 12 else '银松森林')
                self.assertEqual(result['cross_zone'], level == 12)
                if level == 12:
                    zone, map_id = '银松森林', 1421
                x, y = point['x'], point['y']
        self.assertEqual((x, y), (54.85, 54.4))
        blocked = frozenset(plan_walking_route(1420, 1421, 12, 'alive'))
        with self.assertRaisesRegex(ValueError, '当前没有可达'):
            find_grinding_point('horde', 12, '提瑞斯法林地', 74.16, 62.79, blocked_legs=blocked, fetch=fetch)

    def test_silverpine_levels_into_hillsbrad_using_checked_outdoor_camps(self):
        silverpine = '/zh/zones/eastern-kingdoms/silverpine-forest/'
        hillsbrad = '/zh/zones/eastern-kingdoms/hillsbrad-foothills/'
        guide = (stage(1, '18–20', leg('银松森林', 'silverpine-forest', [('瑟伯切尔', '44.0,40.9')]))
                 + stage(2, '21–23', leg('贫瘠之地', 'the-barrens', [('棘齿城', '62.4,37.6')]))
                 + stage(3, '24–30', leg('希尔斯布莱德丘陵', 'hillsbrad-foothills', [('塔伦米尔', '63.2,20.7')])))

        def page(path, points):
            return '<section id="route-horde">' + ''.join(
                f'<a class="route-coords" href="{path}?pin={x},{y}#map">营地</a>' for x, y in points) + '</section>'

        bear, farm, farmers = (57.63, 23.63), (36.82, 39.58), (36.38, 39.77)
        ambermill = (54.85, 54.4)
        pages = {'/zh/leveling/horde/': guide, silverpine: page(silverpine, (ambermill,)),
                 hillsbrad: page(hillsbrad, (bear, farm, farmers))}

        north, south = (60.983, 50.923), (58.522, 55.591)
        lion_source = 'https://forever-tavern.com/npcs/classic/2385-feral-mountain-lion/'
        pins = ''.join(f'<a data-entity-pin data-zone="1424" data-source-id="2385" '
                       f'data-pin-label="Source spawn" data-source-x="{x}" data-source-y="{y}"></a>'
                       for x, y in (north, south))

        def fetch(url):
            if url == lion_source:
                return pins
            return pages[url.removeprefix('https://wowhandbook.com')]

        zone, map_id, point = '银松森林', 1421, ambermill
        for level, expected in enumerate((ambermill, bear, bear, bear, farm, farm, farm, farmers, farmers,
                                           north, north, north), 18):
            with self.subTest(level=level):
                result = find_grinding_point('horde', level, zone, *point, current_map_id=map_id, fetch=fetch)
                self.assertEqual(result['cross_zone'], level == 19)
                point = result['point']['x'], result['point']['y']
                self.assertEqual(point, expected)
                if level == 19:
                    self.assertEqual(result['point']['zone'], '希尔斯布莱德丘陵')
                    zone, map_id = '希尔斯布莱德丘陵', 1424
        blocked = frozenset(plan_walking_route(1424, 1417, 30, 'alive'))
        with self.assertRaisesRegex(ValueError, '当前没有可达的已核对刷怪点'):
            find_grinding_point('horde', 30, zone, *point, current_map_id=map_id, fetch=fetch, blocked_legs=blocked)
        with self.assertRaisesRegex(ValueError, '尚未接入希尔斯布莱德丘陵'):
            find_grinding_point('horde', 27, zone, 47, 64, current_map_id=map_id, fetch=fetch)
        result = find_grinding_point('horde', 27, zone, *north, current_map_id=map_id,
                                     excluded=frozenset({(zone, *north)}), fetch=fetch)
        self.assertEqual((result['point']['x'], result['point']['y']), south)
        self.assertEqual(result['source_url'], lion_source)

    def test_horde_progresses_from_hillsbrad_to_verified_arathi_camps(self):
        guide_url = 'https://wowhandbook.com/zh/leveling/horde/'
        horde = stage(1, '29–35', leg('希尔斯布莱德丘陵', 'hillsbrad-foothills', [('塔伦米尔', '63.2,20.7')]))

        def spawns(npc, map_id, points):
            return ''.join(f'<a data-entity-pin data-zone="{map_id}" data-source-id="{npc}" '
                           f'data-pin-label="Source spawn" data-source-x="{x}" data-source-y="{y}"></a>'
                           for x, y in points)

        strider_url = 'https://forever-tavern.com/npcs/classic/2559-highland-strider/'
        thrasher_url = 'https://forever-tavern.com/npcs/classic/2560-highland-thrasher/'
        lion_url = 'https://forever-tavern.com/npcs/classic/2385-feral-mountain-lion/'
        lions = ((60.983, 50.923), (58.522, 55.591))
        striders = ((23.663, 35.371), (24.477, 40.65))
        thrashers = ((22.028, 47.682), (21.641, 49.413))
        pages = {guide_url: horde, lion_url: spawns(2385, 1424, lions),
                 strider_url: spawns(2559, 1417, striders), thrasher_url: spawns(2560, 1417, thrashers)}
        zone, point = '希尔斯布莱德丘陵', lions[0]
        for level in range(29, 36):
            with self.subTest(level=level):
                result = find_grinding_point('horde', level, zone, *point, fetch=pages.__getitem__)
                self.assertEqual(result['cross_zone'], level == 30)
                zone = result['point']['zone']
                point = result['point']['x'], result['point']['y']
                expected, source = ((lions, lion_url) if level == 29 else
                                    (striders, strider_url) if level <= 32 else (thrashers, thrasher_url))
                self.assertEqual((point, result['source_url']), (expected[0], source))
                backup, = result['alternatives']
                self.assertEqual((backup['x'], backup['y']), expected[1])
        with self.assertRaisesRegex(ValueError, '尚未接入阿拉希高地西部'):
            find_grinding_point('horde', 33, zone, 50, 50, fetch=pages.__getitem__)

    def test_first_numbered_stage_uses_local_starter_camp_when_the_road_is_unavailable(self):
        from wowbuddy.automation.manual_routes import parse_manual_connection, parse_manual_route

        starter = ('<article class="lvs-start"><h3><a href="/zh/zones/kalimdor/durotar/#route-horde">杜隆塔尔</a>'
                   '<small>1–12</small></h3></article>')
        guide = starter + stage(1, '12–17', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')]))
        fetch = Mock(return_value=guide)
        local = 'WBDROUTE2|1411|杜隆塔尔|4000,5000|4300,5200'
        next_camp = 'WBDROUTE2|1413|贫瘠之地|4000,4000|4200,4200'
        routes = tuple(map(parse_manual_route, (local, next_camp)))
        connection = parse_manual_connection(local + '\n' + next_camp)
        builtin = frozenset(plan_walking_route(1411, 1413, 12, 'alive'))
        options = {'camp_routes': routes, 'current_map_id': 1411, 'fetch': fetch}
        for roads, blocked in (((), builtin), ((connection,), frozenset({connection}))):
            with self.subTest(roads=roads, blocked=blocked):
                fetch.reset_mock()
                result = find_grinding_point('horde', 12, '杜隆塔尔', 40, 50,
                                             connections=roads, blocked_legs=blocked, **options)
                self.assertTrue(result['manual_camp'])
                self.assertFalse(result['cross_zone'])
                self.assertEqual((result['point']['x'], result['point']['y']), (43, 52))
                self.assertEqual(result['primary_guide_point']['zone'], '贫瘠之地')
                self.assertTrue(result['source_url'].endswith('#lv-1'))
                fetch.assert_called_once()
        next_point = find_grinding_point('horde', 12, '杜隆塔尔', 40, 50, connections=(connection,), **options)
        self.assertTrue(next_point['cross_zone'])
        self.assertEqual(next_point['point']['zone'], '贫瘠之地')
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point('horde', 12, '杜隆塔尔', 40, 50, blocked_legs=builtin, **options,
                               excluded=frozenset({('杜隆塔尔', 43, 52)}))
        with self.assertRaisesRegex(ValueError, '没有到达'):
            find_grinding_point('horde', 13, '杜隆塔尔', 40, 50, blocked_legs=builtin, **options)

    def test_barrens_lookup_checks_horde_camps_after_planning_the_builtin_road(self):
        path = '/zh/zones/kalimdor/the-barrens/'
        guide = stage(1, '12–17', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')]))
        zone = (f'<section id="route-horde"><a class="route-coords" href="{path}?pin=53.12,30.42#map">'
                f'53.1, 30.4</a><a class="route-coords" href="{path}?pin=50.79,34.14#map">斑马</a></section>'
                f'<section id="route-alliance"><a class="route-coords" href="{path}?pin=52.93,33.04#map">'
                '其他路线</a></section>')
        fetch = Mock(side_effect=lambda url: zone if url.endswith(path) else guide)
        args = ('horde', 14, '杜隆塔尔', 51.9, 42.4)
        result = find_grinding_point(*args, fetch=fetch)
        self.assertTrue(result['cross_zone'])
        self.assertEqual(result['guide_point']['name'], '十字路口')
        self.assertEqual((result['point']['x'], result['point']['y']), (53.12, 30.42))
        self.assertEqual([(p['x'], p['y']) for p in result['alternatives']], [(50.79, 34.14)])
        self.assertEqual(result['source_url'], f'https://wowhandbook.com{path}#route-horde')
        fetch.reset_mock()
        blocked = frozenset(plan_walking_route(1411, 1413, 14, 'alive'))
        with self.assertRaisesRegex(ValueError, '受阻路段'):
            find_grinding_point(*args, blocked_legs=blocked, fetch=fetch)
        fetch.assert_called_once_with('https://wowhandbook.com/zh/leveling/horde/')

    def test_barrens_level_up_moves_to_a_verified_ashenvale_camp(self):
        barrens = '/zh/zones/kalimdor/the-barrens/'
        ashenvale = '/zh/zones/kalimdor/ashenvale/'
        guide = stage(1, '19–24', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.0,31.6')]))
        pages = {barrens: ((43.81, 48.17),), ashenvale: ((72.52, 69.5), (50.92, 67.42))}

        def fetch(url):
            for path, markers in pages.items():
                if url.endswith(path):
                    return '<section id="route-horde">' + ''.join(
                        f'<a class="route-coords" href="{path}?pin={x},{y}#map">营地</a>' for x, y in markers
                    ) + '</section>'
            return guide

        level_22 = find_grinding_point('horde', 22, '贫瘠之地', 52.46, 46.56, fetch=fetch)
        self.assertEqual((level_22['point']['x'], level_22['point']['y']), (43.81, 48.17))
        self.assertFalse(level_22['cross_zone'])
        args = ('horde', 23, '贫瘠之地', 43.81, 48.17)
        level_23 = find_grinding_point(*args, fetch=fetch)
        self.assertEqual(level_23['guide_point']['zone'], '贫瘠之地')
        self.assertTrue(level_23['cross_zone'])
        self.assertEqual((level_23['point']['zone'], level_23['point']['x'], level_23['point']['y']),
                         ('灰谷', 72.52, 69.5))
        with self.assertRaisesRegex(ValueError, '营地仍在等待重试'):
            find_grinding_point(*args, fetch=fetch, excluded=frozenset({('灰谷', 72.52, 69.5)}))
        blocked = frozenset(plan_walking_route(1413, 1440, 23, 'alive'))
        with self.assertRaisesRegex(ValueError, '受阻路段'):
            find_grinding_point(*args, fetch=fetch, blocked_legs=blocked)

    def test_horde_ashenvale_level_27_uses_online_wolf_locations_and_cooldown(self):
        source = 'https://forever-tavern.com/npcs/classic/3825-ghostpaw-alpha/'
        guide = stage(1, '27–31', leg('灰谷', 'ashenvale', [('碎木岗哨', '73.3,61.7')]))

        def pin(x, y, *, npc='3825', zone='1440'):
            return (f'<a class="entity-map-pin" data-entity-pin data-source-x="{x}" data-source-y="{y}" '
                    f'data-zone="{zone}" data-source-id="{npc}" data-pin-label="Source spawn">•</a>')

        pins = pin('68.2', '69.161') + pin('66.573', '70.074')
        fetch = Mock(side_effect=lambda url: pins if url == source else guide)
        args = ('horde', 27, '灰谷', 72.52, 69.5)
        result = find_grinding_point(*args, fetch=fetch)
        self.assertEqual((result['point']['x'], result['point']['y']), (68.2, 69.161))
        self.assertEqual([(p['x'], p['y']) for p in result['alternatives']], [(66.573, 70.074)])
        self.assertEqual(result['source_url'], source)
        alternate = find_grinding_point(*args, fetch=fetch, excluded=frozenset({('灰谷', 68.2, 69.161)}))
        self.assertEqual((alternate['point']['x'], alternate['point']['y']), (66.573, 70.074))
        self.assertTrue(find_grinding_point('horde', 31, '贫瘠之地', 43.81, 48.17, fetch=fetch)['cross_zone'])

        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            wrong = pin('68.2', '69.161', npc='3826') + pin('66.573', '70.074', zone='1413')
            find_grinding_point(*args, fetch=lambda url: wrong if url == source else guide)
        with self.assertRaisesRegex(ValueError, '灰谷东南'):
            find_grinding_point('horde', 27, '灰谷', 23, 60, fetch=fetch)

    def test_live_invalid_guide_and_removed_page_invalidate_the_offline_copy(self):
        from tempfile import TemporaryDirectory
        from urllib.error import HTTPError

        for live_error in (None, HTTPError('https://wowhandbook.com/zh/leveling/alliance/', 404, 'missing', {}, None)):
            with self.subTest(live_error=live_error), TemporaryDirectory() as directory:
                if live_error is not None:
                    self.addCleanup(live_error.close)
                cache = LevelingGuideCache(clock=lambda: 0, directory=directory)
                find_leveling_point('alliance', 15, '西部荒野', fetch=lambda _: GUIDE, cache=cache)
                fetch = Mock(side_effect=live_error, return_value='<p>页面已改版</p>')
                with self.assertRaises((ValueError, HTTPError)):
                    find_leveling_point('alliance', 15, '西部荒野', fetch=fetch, cache=cache)
                with self.assertRaisesRegex(OSError, 'offline'):
                    find_leveling_point('alliance', 15, '西部荒野',
                                       fetch=Mock(side_effect=OSError('offline')),
                                       cache=LevelingGuideCache(directory=directory))

    def test_guide_disk_cache_reparses_for_the_current_lookup_and_expires(self):
        from tempfile import TemporaryDirectory

        url = 'https://wowhandbook.com/zh/zones/kalimdor/ashenvale/'
        offline = Mock(side_effect=OSError('offline'))
        with TemporaryDirectory() as directory:
            cache = LevelingGuideCache(directory=directory)
            self.assertEqual(cache.load(url, lambda _: 'horde,alliance', lambda page: page.split(',')[0]),
                             ('horde', False))
            self.assertEqual(cache.load(url, offline, lambda page: page.split(',')[1]), ('alliance', True))
            saved = next(Path(directory).glob('*.html'))
            fetched = saved.stat().st_mtime
            restarted = LevelingGuideCache(directory=directory, wall_clock=lambda: fetched + 600)
            self.assertEqual(restarted.load(url, offline, lambda page: page.split(',')[1]), ('alliance', True))
            for timestamp in (fetched - 1, fetched + 901):
                with self.subTest(timestamp=timestamp), self.assertRaisesRegex(OSError, 'offline'):
                    LevelingGuideCache(directory=directory, wall_clock=lambda: timestamp).load(url, offline, str)

    def test_truncated_response_reuses_complete_guide_for_the_new_level(self):
        from email.message import Message
        from http.client import IncompleteRead
        from unittest.mock import MagicMock

        full = GUIDE.encode('utf-8')
        prefix = GUIDE[:GUIDE.index('<article class="lvs" data-step="2"')].encode('utf-8')
        url = 'https://wowhandbook.com/zh/leveling/alliance/'
        for chunked in (False, True):
            with self.subTest(chunked=chunked):
                response = MagicMock()
                response.__enter__.return_value = response
                response.geturl.return_value = url
                response.headers = Message()
                response.headers['Content-Type'] = 'text/html; charset=utf-8'
                response.headers['Content-Length'] = str(len(full))
                cache = LevelingGuideCache()
                with patch('wowbuddy.automation.leveling_route.urlopen', return_value=response):
                    response.read1.side_effect = [full, b'']
                    initial = find_leveling_point('alliance', 15, '西部荒野', cache=cache)
                    self.assertEqual(initial['point']['name'], '哨兵岭')
                    if chunked:
                        del response.headers['Content-Length']
                        response.headers['Transfer-Encoding'] = 'chunked'
                        response.read1.side_effect = IncompleteRead(prefix)
                    else:
                        response.read1.side_effect = [prefix, b'', prefix, b'']
                    upgraded = find_leveling_point('alliance', 17, '西部荒野', cache=cache)
                    self.assertEqual(upgraded['point']['name'], '奥伯丁')
                    self.assertEqual(upgraded['cached_sources'], [url])
                    with self.assertRaisesRegex(OSError, '未完整接收'):
                        find_leveling_point('alliance', 17, '西部荒野')

    def test_partial_http_response_does_not_replace_validated_guide(self):
        from email.message import Message
        from tempfile import TemporaryDirectory
        from unittest.mock import MagicMock

        url = 'https://wowhandbook.com/zh/leveling/alliance/'
        full = GUIDE.encode('utf8')
        prefix = GUIDE[:GUIDE.index('<article class="lvs" data-step="2"')].encode('utf8')
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = url
        with TemporaryDirectory() as directory, patch('wowbuddy.automation.leveling_route.urlopen', return_value=response):
            cache = LevelingGuideCache(directory=directory)
            response.status = 200
            response.headers = Message()
            response.headers['Content-Type'] = 'text/html'
            response.headers['Content-Length'] = str(len(full))
            response.read1.side_effect = [full, b'']
            self.assertEqual(find_leveling_point('alliance', 15, '西部荒野', cache=cache)['point']['name'], '哨兵岭')
            saved = next(Path(directory).glob('*.html'))

            for status, content_range in ((206, None), (206, 'range'), (200, 'range')):
                with self.subTest(status=status, content_range=content_range):
                    response.status = status
                    response.headers.replace_header('Content-Length', str(len(prefix)))
                    if content_range:
                        response.headers['Content-Range'] = f'bytes 0-{len(prefix) - 1}/{len(full)}'
                    response.read1.reset_mock()
                    response.read1.side_effect = [prefix, b'']
                    result = find_leveling_point('alliance', 17, '西部荒野', cache=LevelingGuideCache(directory=directory))
                    self.assertEqual(result['point']['name'], '奥伯丁')
                    self.assertEqual(result['cached_sources'], [url])
                    self.assertEqual(saved.read_bytes(), full)
                    with self.assertRaisesRegex(OSError, '未完整接收'):
                        find_leveling_point('alliance', 17, '西部荒野')
                    response.read1.assert_not_called()
                    del response.headers['Content-Range']

            response.status = 200
            response.headers.replace_header('Content-Length', str(len(full)))
            response.read1.side_effect = [full, b'']
            result = find_leveling_point('alliance', 17, '西部荒野', cache=cache)
            self.assertNotIn('cached_sources', result)

    def test_slow_stream_reuses_validated_guide_instead_of_waiting_for_eof(self):
        from email.message import Message
        from unittest.mock import MagicMock

        url = 'https://wowhandbook.com/zh/leveling/alliance/'
        cache = LevelingGuideCache(clock=lambda: 0)
        find_leveling_point('alliance', 15, '西部荒野', fetch=lambda _: GUIDE, cache=cache)
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = url
        response.headers = Message()
        response.headers['Content-Type'] = 'text/html'
        elapsed = 0

        def read_chunk(size):
            nonlocal elapsed
            elapsed += 4
            return b'partial'

        response.read1.side_effect = read_chunk
        with (patch('wowbuddy.automation.leveling_route.urlopen', return_value=response),
              patch('wowbuddy.automation.leveling_route.monotonic', side_effect=lambda: elapsed)):
            cached = find_leveling_point('alliance', 17, '西部荒野', cache=cache)
            self.assertEqual(cached['point']['name'], '奥伯丁')
            self.assertEqual(cached['cached_sources'], [url])
            self.assertEqual(response.read1.call_count, 3)
            with self.assertRaisesRegex(TimeoutError, '读取超时'):
                find_leveling_point('alliance', 17, '西部荒野')

    def test_online_grind_lookup_shares_the_reading_budget_between_sources(self):
        from email.message import Message
        from unittest.mock import MagicMock

        guide_url = 'https://wowhandbook.com/zh/leveling/alliance/'
        path = '/zh/zones/eastern-kingdoms/westfall/'
        zone_url = 'https://wowhandbook.com' + path
        markers = f'<section id="route-alliance"><a class="route-coords" href="{path}?pin=46.1,38.2#map">营地</a></section>'
        cache = LevelingGuideCache(clock=lambda: 0)
        args = ('alliance', 15, '西部荒野', 46.1, 38.2)
        find_grinding_point(*args, fetch=lambda url: markers if url == zone_url else GUIDE, cache=cache)
        elapsed = 0
        timeouts = []

        def open_page(request, *, timeout):
            url = request.full_url
            response = MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = url
            response.headers = Message()
            response.headers['Content-Type'] = 'text/html'
            timeouts.append((url, timeout))

            def read_chunk(size):
                nonlocal elapsed
                elapsed += 0.3 if url == guide_url else 0.5
                return GUIDE.encode('utf8') if response.read1.call_count == 1 else b''

            response.read1.side_effect = read_chunk
            return response

        with (patch('wowbuddy.automation.leveling_route.urlopen', side_effect=open_page),
              patch('wowbuddy.automation.leveling_route.monotonic', side_effect=lambda: elapsed),
              patch('wowbuddy.automation.leveling_route._GUIDE_LOOKUP_SECONDS', 1)):
            result = find_grinding_point(*args, cache=cache)
        self.assertEqual(result['point']['name'], '摩尔森农场')
        self.assertEqual(result['cached_sources'], [zone_url])
        self.assertEqual([url for url, _ in timeouts], [guide_url, zone_url])
        self.assertAlmostEqual(timeouts[0][1], 1)
        self.assertAlmostEqual(timeouts[1][1], 0.4)

    def test_horde_ashenvale_level_32_uses_the_new_spawn_source(self):
        source = 'https://forever-tavern.com/npcs/classic/6073-searing-infernal/'
        guide = stage(1, '32–34', leg('灰谷', 'ashenvale', [('碎木岗哨', '73.3,61.7')]))

        def pin(x, y, npc='6073', zone='1440'):
            return (f'<a data-entity-pin data-zone="{zone}" data-source-id="{npc}" '
                    f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>')

        near, far = (80.615, 68.224), (81.469, 69.206)
        pins = pin(*near) + pin(*far)
        fetch = Mock(side_effect=lambda url: pins if url == source else guide)
        args = ('horde', 32, '灰谷', 68.2, 69.161)
        result = find_grinding_point(*args, fetch=fetch)
        self.assertEqual(result['source_url'], source)
        self.assertEqual((result['point']['x'], result['point']['y']), near)
        self.assertEqual([(p['x'], p['y']) for p in result['alternatives']], [far])
        alternate = find_grinding_point(*args, fetch=fetch, excluded=frozenset({('灰谷', *near)}))
        self.assertEqual((alternate['point']['x'], alternate['point']['y']), far)
        east = find_grinding_point('horde', 33, '灰谷', *far, fetch=fetch)
        self.assertEqual((east['point']['x'], east['point']['y']), far)
        self.assertTrue(find_grinding_point('horde', 34, '贫瘠之地', 43.81, 48.17, fetch=fetch)['cross_zone'])

        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            wrong = pin(*near, npc='3825') + pin(*far, zone='1413')
            find_grinding_point(*args, fetch=lambda url: wrong if url == source else guide)
        with self.assertRaisesRegex(ValueError, '灰谷东南'):
            find_grinding_point('horde', 32, '灰谷', 79.4, 74, fetch=fetch)

    def test_horde_at_level_35_checks_desolace_spawns_before_travel(self):
        source = 'https://forever-tavern.com/npcs/classic/4692-dread-swoop/'
        guide = stage(1, '35–38', leg('荆棘谷', 'stranglethorn-vale', [('格罗姆高营地', '32.2,27.7')]))
        near, far = (59.928, 13.372), (59.774, 24.319)

        def pin(point, npc='4692', zone='1443'):
            x, y = point
            return (f'<a data-entity-pin data-zone="{zone}" data-source-id="{npc}" '
                    f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>')

        fetch = Mock(side_effect=lambda url: pin(near) + pin(far) if url == source else guide)
        result = find_grinding_point('horde', 35, '灰谷', 81.469, 69.206, fetch=fetch)
        self.assertTrue(result['cross_zone'])
        self.assertEqual(result['source_url'], source)
        self.assertEqual((result['point']['zone'], result['point']['x'], result['point']['y']), ('凄凉之地', *near))
        stone = find_grinding_point('horde', 36, '石爪山脉', 63.1, 84.7, fetch=fetch)
        self.assertEqual(stone['point'], result['point'])
        alternate = find_grinding_point('horde', 38, '凄凉之地', *near, fetch=fetch,
                                       excluded=frozenset({('凄凉之地', *near)}))
        self.assertEqual((alternate['point']['x'], alternate['point']['y']), far)
        self.assertFalse(alternate['cross_zone'])
        with self.assertRaisesRegex(ValueError, '凄凉之地的已核对陆路'):
            find_grinding_point('horde', 36, '凄凉之地', 48.5, 60, fetch=fetch)
        with self.assertRaisesRegex(ValueError, '灰谷东南'):
            find_grinding_point('horde', 35, '灰谷', 40, 55, fetch=fetch)
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            wrong = pin(near, zone='1442') + pin(far, npc='4697')
            find_grinding_point('horde', 35, '灰谷', 81.469, 69.206,
                                fetch=lambda url: wrong if url == source else guide)

    def test_both_factions_desolace_switches_spawn_sources_at_levels_39_and_43(self):
        north_url = 'https://forever-tavern.com/npcs/classic/4692-dread-swoop/'
        central_url = 'https://forever-tavern.com/npcs/classic/4693-dread-flyer/'
        south_url = 'https://forever-tavern.com/npcs/classic/4694-dread-ripper/'
        guide = stage(1, '38–45', leg('凄凉之地', 'desolace', [('鬼魂岗哨', '56.2,59.6')]))
        north, central, east = (59.774, 24.319), (61.922, 44.567), (63.96, 45.64)
        south, alternate_south = (62.723, 71.011), (61.166, 74.452)

        def pin(npc, point):
            x, y = point
            return (f'<a data-entity-pin data-zone="1443" data-source-id="{npc}" '
                    f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>')

        for faction in ('alliance', 'horde'):
            with self.subTest(faction=faction):
                pages = {north_url: pin('4692', north), central_url: pin('4693', central) + pin('4693', east),
                         south_url: pin('4694', south) + pin('4694', alternate_south)}
                fetch = Mock(side_effect=lambda url: pages.get(url, guide))
                earlier = find_grinding_point(faction, 38, '凄凉之地', *north, fetch=fetch)
                self.assertEqual(earlier['source_url'], north_url)
                next_camp = find_grinding_point(faction, 39, '凄凉之地', *north, fetch=fetch)
                self.assertEqual(next_camp['source_url'], central_url)
                self.assertEqual((next_camp['point']['x'], next_camp['point']['y']), central)
                alternate = find_grinding_point(faction, 42, '凄凉之地', *central, fetch=fetch,
                                               excluded=frozenset({('凄凉之地', *central)}))
                self.assertEqual((alternate['point']['x'], alternate['point']['y']), east)
                next_camp = find_grinding_point(faction, 43, '凄凉之地', *east, fetch=fetch)
                self.assertEqual(next_camp['source_url'], south_url)
                self.assertEqual((next_camp['point']['x'], next_camp['point']['y']), south)
                alternate = find_grinding_point(faction, 45, '凄凉之地', *south, fetch=fetch,
                                               excluded=frozenset({('凄凉之地', *south)}))
                self.assertEqual((alternate['point']['x'], alternate['point']['y']), alternate_south)
                pages[central_url] = pin('4692', central)
                with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
                    find_grinding_point(faction, 39, '凄凉之地', *north, fetch=fetch)

    def test_both_factions_feralas_uses_local_spawns_instead_of_overseas_guide_point(self):
        wolf_url = 'https://forever-tavern.com/npcs/classic/5288-rabid-longtooth/'
        bear_url = 'https://forever-tavern.com/npcs/classic/5274-ironfur-patriarch/'
        guide = stage(1, '46–53', leg('悲伤沼泽', 'swamp-of-sorrows', [('斯通纳德', '47.9,54.8')]))
        wolf, alternate_wolf = (44.503, 9.115), (44.373, 11.024)
        bear, alternate_bear = (44.461, 11.743), (43.033, 9.689)

        def pin(npc, point, map_id=1444):
            x, y = point
            return (f'<a data-entity-pin data-zone="{map_id}" data-source-id="{npc}" '
                    f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>')

        for faction in ('alliance', 'horde'):
            with self.subTest(faction=faction):
                pages = {wolf_url: pin('5288', wolf) + pin('5288', alternate_wolf),
                         bear_url: pin('5274', bear) + pin('5274', alternate_bear)}
                fetch = Mock(side_effect=lambda url: pages.get(url, guide))
                result = find_grinding_point(faction, 46, '凄凉之地', 61.166, 74.452, fetch=fetch)
                self.assertTrue(result['cross_zone'])
                self.assertEqual(result['source_url'], wolf_url)
                self.assertEqual((result['point']['zone'], result['point']['x'], result['point']['y']), ('菲拉斯', *wolf))
                result = find_grinding_point(faction, 49, '菲拉斯', *wolf, fetch=fetch)
                self.assertEqual(result['source_url'], bear_url)
                self.assertEqual((result['point']['x'], result['point']['y']), bear)
                alternate = find_grinding_point(faction, 53, '菲拉斯', *bear, fetch=fetch,
                                               excluded=frozenset({('菲拉斯', *bear)}))
                self.assertEqual((alternate['point']['x'], alternate['point']['y']), alternate_bear)
                with self.assertRaisesRegex(ValueError, '菲拉斯北部'):
                    find_grinding_point(faction, 49, '菲拉斯', 70, 50, fetch=fetch)
                pages[wolf_url] = pin('5288', wolf, map_id=1443) + pin('5274', alternate_wolf)
                with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
                    find_grinding_point(faction, 46, '凄凉之地', 61.166, 74.452, fetch=fetch)

    def test_both_factions_felwood_camps_switch_online_sources_at_54_and_57(self):
        tree_url = 'https://forever-tavern.com/npcs/classic/7139-irontree-stomper/'
        furbolg_url = 'https://forever-tavern.com/npcs/classic/7157-deadwood-avenger/'
        guide = stage(1, '54–60', leg('冬泉谷', 'winterspring', [('永望镇', '61.4,39.0')]))
        tree, alternate_tree = (51.775, 24.167), (52.528, 24.57)
        furbolg, alternate_furbolg = (60.901, 8.419), (61.102, 9.042)

        def pin(npc, point, map_id=1448):
            x, y = point
            return (f'<a data-entity-pin data-zone="{map_id}" data-source-id="{npc}" '
                    f'data-source-x="{x}" data-source-y="{y}" data-pin-label="Source spawn"></a>')

        for faction in ('alliance', 'horde'):
            with self.subTest(faction=faction):
                pages = {tree_url: pin('7139', tree) + pin('7139', alternate_tree),
                         furbolg_url: pin('7157', furbolg) + pin('7157', alternate_furbolg)}
                fetch = Mock(side_effect=lambda url: pages.get(url, guide))
                result = find_grinding_point(faction, 54, '菲拉斯', 44.461, 11.743, fetch=fetch)
                self.assertTrue(result['cross_zone'])
                self.assertEqual(result['source_url'], tree_url)
                self.assertEqual((result['point']['zone'], result['point']['x'], result['point']['y']), ('费伍德森林', *tree))
                ash = find_grinding_point(faction, 55, '灰谷', 63.35, 49.8, fetch=fetch)
                self.assertEqual(ash['point'], result['point'])
                self.assertEqual([(p['x'], p['y']) for p in ash['alternatives']], [alternate_tree])
                result = find_grinding_point(faction, 57, '费伍德森林', *alternate_tree, fetch=fetch)
                self.assertEqual(result['source_url'], furbolg_url)
                self.assertEqual((result['point']['x'], result['point']['y']), furbolg)
                alternate = find_grinding_point(faction, 60, '费伍德森林', *furbolg, fetch=fetch,
                                               excluded=frozenset({('费伍德森林', *furbolg)}))
                self.assertEqual((alternate['point']['x'], alternate['point']['y']), alternate_furbolg)
                pages[tree_url] = pin('7139', tree, map_id=1440) + pin('7157', alternate_tree)
                with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
                    find_grinding_point(faction, 54, '菲拉斯', 44.461, 11.743, fetch=fetch)

    def test_marked_camps_fall_back_to_other_areas_in_eligible_guide_stages(self):
        from wowbuddy.automation.manual_routes import parse_manual_connection, parse_manual_route

        guide = (stage(1, '12–17', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')]),
                       leg('石爪山脉', 'stonetalon-mountains', [('烈日石居', '47,61')]))
                 + stage(2, '15–19', leg('灰谷', 'ashenvale', [('碎木岗哨', '73,62')]))
                 + stage(3, '18–22', leg('千针石林', 'thousand-needles', [('乱风岗', '46,50')])))
        source = 'WBDROUTE2|1411|杜隆塔尔|4900,5000|4800,5100'
        regions = ('WBDROUTE2|1413|贫瘠之地|4000,4000|4200,4200',
                   'WBDROUTE2|1442|石爪山脉|4200,5000|4300,5200',
                   'WBDROUTE2|1440|灰谷|5000,5800|5200,5900',
                   'WBDROUTE2|1441|千针石林|4000,4900|4300,5200')
        connections = tuple(parse_manual_connection(source + '\n' + region) for region in regions)
        routes = tuple(map(parse_manual_route, regions))
        fetch = Mock(return_value=guide)
        options = {'connections': connections, 'camp_routes': routes, 'current_map_id': 1411, 'fetch': fetch}
        primary = find_grinding_point('horde', 16, '杜隆塔尔', 49, 50, **options)
        self.assertEqual(primary['point']['zone'], '贫瘠之地')
        same_stage = find_grinding_point('horde', 16, '杜隆塔尔', 49, 50,
            excluded=frozenset({('贫瘠之地', 42, 42)}), **options)
        self.assertEqual((same_stage['point']['zone'], same_stage['stage']), ('石爪山脉', 1))
        fetch.reset_mock()
        next_stage = find_grinding_point('horde', 16, '杜隆塔尔', 49, 50,
            blocked_legs=frozenset(connections[:2]), **options)
        self.assertEqual((next_stage['point']['zone'], next_stage['stage']), ('灰谷', 2))
        self.assertTrue(next_stage['source_url'].endswith('#step-2'))
        self.assertEqual(next_stage['primary_guide_point']['zone'], '贫瘠之地')
        fetch.assert_called_once()
        with self.assertRaisesRegex(ValueError, '没有到达'):
            find_grinding_point('horde', 16, '杜隆塔尔', 49, 50,
                               blocked_legs=frozenset(connections[:3]), **options)

    def test_marked_and_catalog_coordinates_share_the_failed_camp_cooldown(self):
        from wowbuddy.automation.manual_routes import parse_manual_route

        path = '/zh/zones/eastern-kingdoms/redridge-mountains/'
        guide = stage(1, '15–17', leg('赤脊山', 'redridge-mountains', [('湖畔镇', '25.5,59.4')]))
        markers = (f'<section id="route-alliance"><a class="route-coords" '
                   f'href="{path}?pin=11.65,62.18#map">山丘</a></section>')
        routes = tuple(map(parse_manual_route, ('WBDROUTE1|1433|1100,6200|1160,6250',
                                                'WBDROUTE1|1433|1450,6300|1500,6400')))
        for coords in ((11.65, 62.18), (11.6, 62.5)):
            with self.subTest(coords=coords):
                result = find_grinding_point('alliance', 15, '赤脊山', 11.6, 62.5, camp_routes=routes,
                    excluded=frozenset({('赤脊山', *coords)}), fetch=lambda url: markers if url.endswith(path) else guide)
                self.assertTrue(result['manual_camp'])
                self.assertEqual((result['point']['x'], result['point']['y']), (15, 64))

    def test_marked_camp_requires_matching_stage_map_and_reachable_land_connection(self):
        from wowbuddy.automation.manual_routes import parse_manual_connection, parse_manual_route

        guide = (stage(1, '12–17', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')]))
                 + stage(2, '18–22', leg('石爪山脉', 'stonetalon-mountains', [('烈日石居', '47,61')])))
        route = parse_manual_route('WBDROUTE2|1413|贫瘠之地|4000,4000|4200,4200')
        origin = parse_manual_route('WBDROUTE2|1411|杜隆塔尔|5000,5000|5100,5100')
        connector = parse_manual_connection(
            'WBDROUTE2|1411|杜隆塔尔|4900,5000|4800,5100\nWBDROUTE2|1413|贫瘠之地|6200,4000|6100,4100')
        options = {'camp_routes': (origin, route), 'current_map_id': 1411, 'fetch': lambda _: guide}
        with self.assertRaisesRegex(ValueError, '没有到达'):
            blocked = frozenset(plan_walking_route(1411, 1413, 15, 'alive'))
            find_grinding_point('horde', 15, '杜隆塔尔', 49, 50, blocked_legs=blocked, **options)
        result = find_grinding_point('horde', 15, '杜隆塔尔', 49, 50, connections=(connector,), **options)
        self.assertTrue(result['cross_zone'] and result['manual_camp'])
        self.assertEqual((result['point']['x'], result['point']['y']), (42, 42))
        self.assertEqual(result['guide_point']['name'], '十字路口')
        with self.assertRaisesRegex(ValueError, '没有到达'):
            find_grinding_point('horde', 15, '杜隆塔尔', 49, 50, connections=(connector,),
                                blocked_legs=frozenset({connector}), **options)
        with self.assertRaisesRegex(ValueError, '没有可达的已核对刷怪坐标'):
            find_grinding_point('horde', 18, '杜隆塔尔', 49, 50, connections=(connector,), **options)
        with self.assertRaisesRegex(ValueError, '地图编号'):
            find_grinding_point('horde', 15, '杜隆塔尔', 49, 50,
                                **dict(options, current_map_id=999))

    def test_grind_changes_from_both_verified_loch_modan_roads_to_wetlands(self):
        loch = '/zh/zones/eastern-kingdoms/loch-modan/'
        wetlands = '/zh/zones/eastern-kingdoms/wetlands/'
        guide = stage(1, '19–25', leg('赤脊山', 'redridge-mountains', [('湖畔镇', '25.5, 59.4')]))

        def markers(path, *points):
            return '<section id="route-alliance">' + ''.join(
                f'<a class="route-coords" href="{path}?pin={point}#map">营地</a>' for point in points) + '</section>'

        sources = {'/zh/leveling/alliance/': guide, loch: markers(loch, '37.9,87.0'),
                   wetlands: markers(wetlands, '60.51,63.71', '60.74,64.31', '54,41.37')}
        fetch = lambda url: sources[url.removeprefix('https://wowhandbook.com')]
        at_19 = find_grinding_point('alliance', 19, '洛克莫丹', 37.9, 87.0, fetch=fetch)
        self.assertEqual(at_19['point']['zone'], '洛克莫丹')
        at_20 = find_grinding_point('alliance', 20, '洛克莫丹', 37.9, 87.0, fetch=fetch)
        self.assertTrue(at_20['cross_zone'])
        self.assertEqual(at_20['point']['name'], '藓皮豺狼人营地')
        self.assertEqual(at_20['zone_url'], 'https://wowhandbook.com' + wetlands)
        east_access = find_grinding_point('alliance', 20, '洛克莫丹', 65.4, 39.6, fetch=fetch)
        self.assertEqual(east_access['point'], at_20['point'])
        with self.assertRaisesRegex(ValueError, '湖岸'):
            find_grinding_point('alliance', 20, '洛克莫丹', 78, 35, fetch=fetch)
        later = find_grinding_point('alliance', 25, '湿地', 60.51, 63.71, fetch=fetch)
        self.assertEqual(later['point']['name'], '绿带草地沼泽爬行者区')

    def test_dig_camp_upgrade_keeps_online_marker_checks_and_uses_the_north_road(self):
        from wowbuddy.automation.manual_routes import parse_manual_route

        loch = '/zh/zones/eastern-kingdoms/loch-modan/'
        wetlands = '/zh/zones/eastern-kingdoms/wetlands/'
        guide = stage(1, '19–25', leg('湿地', 'wetlands', [('米奈希尔港', '10,60')]))
        pages = {
            loch: '<section id="route-alliance">' + ''.join(
                f'<a class="route-coords" href="{loch}?pin={pin}#map">营地</a>'
                for pin in ('70.0,63.3', '70.1,66.0')) + '</section>',
            wetlands: f'<section id="route-alliance"><a class="route-coords" href="{wetlands}?pin=60.51,63.71#map">营地</a></section>',
        }
        fetch = lambda url: pages.get(url.removeprefix('https://wowhandbook.com'), guide)
        start = ('alliance', 19, '洛克莫丹', 65.4, 39.6)
        at_19 = find_grinding_point(*start, fetch=fetch)
        point = at_19['point']
        self.assertEqual((point['x'], point['y']), (67.869, 59.098))
        self.assertEqual([(p['x'], p['y']) for p in at_19['alternatives']], [(67.015, 59.412)])
        for point in (point, *at_19['alternatives']):
            at_20 = find_grinding_point('alliance', 20, '洛克莫丹', point['x'], point['y'], fetch=fetch)
            self.assertEqual((at_20['point']['zone'], at_20['point']['x']), ('湿地', 60.51))
        with self.assertRaisesRegex(ValueError, '湖岸'):
            find_grinding_point('alliance', 20, '洛克莫丹', 70.1, 66, fetch=fetch)

        manual = parse_manual_route('WBDROUTE1|1432|6800,6400|7010,6600')
        old = find_grinding_point('alliance', 19, '洛克莫丹', 70.1, 66, fetch=fetch, camp_routes=(manual,))
        self.assertEqual((old['point']['x'], old['point']['y']), (70.1, 66))

    def test_grind_uses_verified_camps_on_the_same_loch_modan_shore(self):
        path = '/zh/zones/eastern-kingdoms/loch-modan/'
        markers = ('<section id="route-alliance">'
                   + ''.join(f'<a class="route-coords" href="{path}?pin={pin}#map">营地</a>'
                             for pin in ('37.5,90.1', '37.9,87.0', '65.4,39.6'))
                   + '</section>')
        fetch = lambda url: markers if url.endswith(path) else GUIDE
        west = find_grinding_point('alliance', 16, '洛克莫丹', 33.53, 49.38, fetch=fetch)
        self.assertEqual(west['guide_point']['zone'], '西部荒野')
        self.assertEqual(west['point']['name'], '碎石怪断骨者营地')
        self.assertEqual([camp['name'] for camp in west['alternatives']], ['碎石怪萨满祭司营地'])
        self.assertFalse(west['cross_zone'])
        east = find_grinding_point('alliance', 16, '洛克莫丹', 68.0, 49.38, fetch=fetch)
        self.assertEqual(east['point']['name'], '东岸老山猪区')
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point('alliance', 16, '洛克莫丹', 33.53, 49.38, fetch=fetch,
                                excluded=frozenset({('洛克莫丹', 37.5, 90.1), ('洛克莫丹', 37.9, 87.0)}))

    def test_grind_moves_from_duskwood_to_stranglethorn_at_level_30(self):
        duskwood = '/zh/zones/eastern-kingdoms/duskwood/'
        stranglethorn = '/zh/zones/eastern-kingdoms/stranglethorn-vale/'
        guide = stage(1, '25–31', leg('暮色森林', 'duskwood', [('夜色镇', '75.8, 45.3')]))
        sources = {
            '/zh/leveling/alliance/': guide,
            duskwood: (f'<section id="route-alliance"><a class="route-coords" '
                       f'href="{duskwood}?pin=64.95,45.75#map">狼人</a></section>'),
            stranglethorn: (f'<section id="route-alliance"><a class="route-coords" '
                           f'href="{stranglethorn}?pin=35.65,12.14#map">猛虎幼崽</a></section>'),
        }
        fetch = lambda url: sources[url.removeprefix('https://wowhandbook.com')]
        at_29 = find_grinding_point('alliance', 29, '暮色森林', 66.0, 45.0, fetch=fetch)
        self.assertEqual(at_29['point']['name'], '夜行织影狼人区')
        self.assertFalse(at_29['cross_zone'])
        at_30 = find_grinding_point('alliance', 30, '暮色森林', 66.0, 45.0, fetch=fetch)
        self.assertEqual(at_30['point']['name'], '荆棘谷猛虎幼崽区')
        self.assertTrue(at_30['cross_zone'])

    def test_level_41_leaves_stranglethorn_for_verified_swamp_camps(self):
        swamp = '/zh/zones/eastern-kingdoms/swamp-of-sorrows/'
        stranglethorn = '/zh/zones/eastern-kingdoms/stranglethorn-vale/'
        guide = stage(1, '40–43', leg('荆棘谷', 'stranglethorn-vale', [('藏宝海湾', '26.9, 77.2')]))
        pages = {
            '/zh/leveling/alliance/': guide,
            stranglethorn: f'<section id="route-alliance"><a class="route-coords" href="{stranglethorn}?pin=48.09,20.2#map">猎豹</a></section>',
            swamp: (f'<section id="route-alliance"><a class="route-coords" href="{swamp}?pin=27.1,55.13#map">鳄鱼</a>'
                    f'<a class="route-coords" href="{swamp}?pin=29.34,53.26#map">蛛</a>'
                    f'<a class="route-coords" href="{swamp}?pin=32.03,49.96#map">虎</a></section>'),
        }
        fetch = Mock(side_effect=lambda url: pages[url.removeprefix('https://wowhandbook.com')])
        old = find_grinding_point('alliance', 40, '荆棘谷', 48.09, 20.2, fetch=fetch)
        self.assertEqual(old['point']['name'], '深喉猎豹区')
        fetch.reset_mock()
        args = ('alliance', 41, '荆棘谷', 48.09, 20.2)
        chosen = find_grinding_point(*args, fetch=fetch)
        self.assertEqual(chosen['point']['zone'], '悲伤沼泽')
        self.assertEqual((chosen['point']['x'], chosen['point']['y']), (27.1, 56.7))
        self.assertEqual(chosen['alternatives'], [])
        self.assertTrue(chosen['cross_zone'])
        self.assertTrue(chosen['source_url'].endswith(swamp + '#route-alliance'))
        for unavailable in ((27.1, 55.13), (27.1, 56.7)):
            with self.assertRaisesRegex(ValueError, '等待重试'):
                find_grinding_point(*args, fetch=fetch,
                                    excluded=frozenset({('悲伤沼泽', *unavailable)}))
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            find_grinding_point(*args, fetch=lambda url: fetch(url).replace('27.1,55.13', '27.1,56.7'))
        blocked = frozenset(plan_walking_route(1434, 1435, 41, 'alive')[-1:])
        fetch.reset_mock()
        with self.assertRaisesRegex(ValueError, '受阻路段'):
            find_grinding_point(*args, fetch=fetch, blocked_legs=blocked)
        fetch.assert_called_once_with('https://wowhandbook.com/zh/leveling/alliance/')

    def test_swamp_connects_to_level_matched_blasted_lands_camps(self):
        swamp = '/zh/zones/eastern-kingdoms/swamp-of-sorrows/'
        blasted = '/zh/zones/eastern-kingdoms/blasted-lands/'
        guide = stage(1, '43–55', leg('诅咒之地', 'blasted-lands', [('守望堡', '66.9,19.47')]))

        def markers(path, pins):
            return '<section id="route-alliance">' + ''.join(
                f'<a class="route-coords" href="{path}?pin={pin}#map">营地</a>' for pin in pins) + '</section>'

        pages = {'/zh/leveling/alliance/': guide,
                 swamp: markers(swamp, ('27.1,55.13',)),
                 blasted: markers(blasted, ('50.2,17.2', '46.8,19.4', '52.27,27.39', '48.2,17.4'))}
        fetch = Mock(side_effect=lambda url: pages[url.removeprefix('https://wowhandbook.com')])
        at_44 = find_grinding_point('alliance', 44, '悲伤沼泽', 27.1, 56.7, fetch=fetch)
        self.assertFalse(at_44['cross_zone'])
        cooldown = frozenset({('悲伤沼泽', 27.1, 56.7)})
        args = ('alliance', 44, '悲伤沼泽', 27.1, 56.7)
        fallback = find_grinding_point(*args, fetch=fetch, excluded=cooldown)
        self.assertTrue(fallback['cross_zone'])
        self.assertEqual(fallback['point']['name'], '北部主路秃鹫区')
        self.assertEqual(fallback['alternatives'], [])
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point('alliance', 43, '悲伤沼泽', 27.1, 56.7,
                                fetch=fetch, excluded=cooldown)
        blocked = frozenset(plan_walking_route(1435, 1419, 44, 'alive'))
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point(*args, fetch=fetch, excluded=cooldown, blocked_legs=blocked)
        with self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
            find_grinding_point(*args, excluded=cooldown,
                                fetch=lambda url: fetch(url).replace('50.2,17.2', '50.3,17.2'))
        at_45 = find_grinding_point('alliance', 45, '悲伤沼泽', 27.1, 56.7, fetch=fetch)
        self.assertTrue(at_45['cross_zone'])
        self.assertEqual(at_45['point']['name'], '北部主路秃鹫区')
        self.assertEqual([point['name'] for point in at_45['alternatives']], ['北部西侧秃鹫区'])
        for level, x, y, name in ((48, 52.27, 27.39, '中部灰鬃野猪区'),
                                  (54, 48.2, 17.4, '北部厚甲蝎区')):
            point = find_grinding_point('alliance', level, '诅咒之地', x, y, fetch=fetch)['point']
            self.assertEqual(point['name'], name)

    def test_deadwind_camps_require_matching_nonelite_rows_and_a_land_route(self):
        source = 'https://theforeverguides.com/leveling/grinding-50-60/'
        guide = stage(1, '55–60', leg('东瘟疫之地', 'eastern-plaguelands', [('礼拜堂', '81,59')]))

        def row(npc, coords, *, elite='No', zone='Deadwind Pass', levels='55–56'):
            cells = {'NPC ID': npc, 'Densest camp': coords, 'Elite?': elite,
                     'Zone': f'<a href="/zones/deadwind-pass/">{zone}</a>', 'Level': levels}
            return '<tr>' + ''.join(f'<td data-label="{key}">{value}</td>' for key, value in cells.items()) + '</tr>'

        ogre = row('7369', '54.6, 60.4')
        shadow = row('7376', '38.6, 41.4')
        html = '<table>' + ogre + shadow + '</table>'
        fetch = Mock(side_effect=lambda url: html if url == source else guide)
        for faction in ('alliance', 'horde'):
            result = find_grinding_point(faction, 55, '诅咒之地', 48.2, 17.4, fetch=fetch)
            self.assertTrue(result['cross_zone'])
            self.assertEqual(result['source_url'], source)
            self.assertTrue(result['zone_url'].endswith('/eastern-kingdoms/deadwind-pass/'))
            self.assertEqual((result['point']['x'], result['point']['y']), (54.6, 60.4))
            self.assertEqual([(p['x'], p['y']) for p in result['alternatives']], [(38.6, 42.15)])
        last = find_grinding_point('alliance', 60, '逆风小径', 38.6, 42.15, fetch=fetch)
        self.assertEqual(last['point']['name'], '罪恶谷逆风蛮兵区')
        self.assertEqual(last['alternatives'], [])
        for bad in (row('7369', '54.6, 60.4', elite='Yes'), row('1234', '54.6, 60.4'),
                    row('7369', '54.6, 60.4', zone='Duskwood'), row('7369', '54.6, 60.4', levels='60–61'),
                    row('7369', '54.7, 60.4')):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '没有已核对的刷怪区坐标'):
                find_grinding_point('alliance', 60, '逆风小径', 54.6, 60.4,
                                    fetch=lambda url: '<table>' + bad + shadow + '</table>' if url == source else guide)
        blocked = frozenset(plan_walking_route(1419, 1430, 55, 'alive')[-1:])
        fetch.reset_mock()
        with self.assertRaisesRegex(ValueError, '受阻路段'):
            find_grinding_point('alliance', 55, '诅咒之地', 48.2, 17.4, fetch=fetch, blocked_legs=blocked)
        fetch.assert_called_once_with('https://wowhandbook.com/zh/leveling/alliance/')

    def test_stormwind_leveling_lookup_selects_a_reachable_field_camp(self):
        zone = '/zh/zones/eastern-kingdoms/westfall/'
        source = f'<section id="route-alliance"><a class="route-coords" href="{zone}?pin=45.4,70.2#map">月溪镇</a></section>'
        def fetch(url):
            return source if url.endswith(zone) else GUIDE

        result = find_grinding_point('alliance', 16, '暴风城', 64.0, 78.2, fetch=fetch)
        self.assertEqual(result['point']['name'], '月溪镇')
        self.assertTrue(result['cross_zone'])
        with self.assertRaisesRegex(ValueError, '尚未接入暴风城贸易区至正门'):
            find_grinding_point('alliance', 16, '暴风城', 71.61, 72.25, fetch=fetch)

    def test_redridge_lookup_waits_at_the_inn_and_uses_a_dry_murloc_stand(self):
        redridge = '/zh/zones/eastern-kingdoms/redridge-mountains/'
        guide = stage(1, '18–20', leg('赤脊山', 'redridge-mountains', [('湖畔镇', '26.5,45.0')]))
        markers = (f'<section id="route-alliance"><a class="route-coords" href="{redridge}?pin=30.7,56.46#map">'
                   '鱼人</a></section>')

        def fetch(url):
            return markers if url.endswith(redridge) else guide

        with self.assertRaisesRegex(ValueError, '尚未接入赤脊山'):
            find_grinding_point('alliance', 18, '赤脊山', 21.8, 44.7, fetch=fetch)
        result = find_grinding_point('alliance', 18, '赤脊山', 23.0, 46.25, fetch=fetch)
        self.assertEqual((result['point']['x'], result['point']['y']), (30.55, 57.1))
        self.assertFalse(result['cross_zone'])

    def test_grind_prefers_nearby_verified_combat_markers_over_the_hub(self):
        zone = '/zh/zones/eastern-kingdoms/westfall/'
        sources = {
            '/zh/leveling/alliance/': GUIDE,
            zone: (f'<a class="route-coords" href="{zone}?pin=45.4,70.2#map">页外</a>'
                   f'<section id="route-alliance"><section>'
                   f'<a class="route-coords" href="{zone}?pin=43.97,39.63#map">田野</a>'
                   f'<a class="route-coords" href="{zone}?pin=46.1,38.2#map">农场</a>'
                   f'<a class="route-coords" href="{zone}?pin=51.66,77.21#map">高等级</a>'
                   '</section></section>'),
        }
        result = find_grinding_point('alliance', 15, '西部荒野', 48.73, 35.87,
                                     fetch=lambda url: sources[url.removeprefix('https://wowhandbook.com')])
        self.assertEqual(result['guide_point']['name'], '哨兵岭')
        self.assertEqual((result['point']['name'], result['point']['x'], result['point']['y']),
                         ('摩尔森农场', 46.1, 38.2))
        self.assertEqual([point['name'] for point in result['alternatives']], ['萨丁农场南边的田野'])
        self.assertFalse(result['cross_zone'])

    def test_grind_uses_a_reachable_mainland_camp_when_stage_guide_recommends_a_sea_crossing(self):
        zone = '/zh/zones/eastern-kingdoms/redridge-mountains/'
        source = f'<section id="route-alliance"><a class="route-coords" href="{zone}?pin=42.74,38.46#map">山坡</a></section>'
        result = find_grinding_point('alliance', 19, '西部荒野', 46.1, 38.2,
                                     fetch=lambda url: source if url.endswith(zone) else GUIDE)
        self.assertEqual(result['guide_point']['zone'], '黑海岸')
        self.assertEqual(result['point']['zone'], '赤脊山')
        self.assertTrue(result['cross_zone'])

    def test_grind_tries_another_reachable_zone_when_current_camp_data_is_missing(self):
        westfall = '/zh/zones/eastern-kingdoms/westfall/'
        redridge = '/zh/zones/eastern-kingdoms/redridge-mountains/'
        sources = {
            '/zh/leveling/alliance/': GUIDE,
            westfall: '<section id="route-alliance">地图标记已改版</section>',
            redridge: (f'<section id="route-alliance"><a class="route-coords" '
                       f'href="{redridge}?pin=11.65,62.18#map">山丘</a></section>'),
        }
        result = find_grinding_point('alliance', 15, '西部荒野', 48.73, 35.87,
                                     fetch=lambda url: sources[url.removeprefix('https://wowhandbook.com')])
        self.assertEqual(result['point']['zone'], '赤脊山')
        self.assertTrue(result['cross_zone'])

    def test_grind_skips_exhausted_camps_without_reusing_the_guide_hub(self):
        redridge = '/zh/zones/eastern-kingdoms/redridge-mountains/'
        sources = {
            '/zh/leveling/alliance/': GUIDE,
            redridge: (f'<section id="route-alliance"><a class="route-coords" '
                       f'href="{redridge}?pin=11.65,62.18#map">山丘</a></section>'),
        }
        excluded = frozenset(('西部荒野', x, y) for x, y in ((43.97, 39.63), (46.1, 38.2), (45.4, 70.2)))
        fetch = Mock(side_effect=lambda url: sources[url.removeprefix('https://wowhandbook.com')])
        result = find_grinding_point('alliance', 15, '西部荒野', 46.1, 38.2, excluded=excluded, fetch=fetch)
        self.assertEqual(result['point']['zone'], '赤脊山')
        self.assertTrue(result['cross_zone'])
        self.assertEqual(fetch.call_count, 2)
        with self.assertRaisesRegex(ValueError, '等待重试'):
            find_grinding_point('alliance', 15, '西部荒野', 46.1, 38.2,
                                 excluded=excluded | {('赤脊山', 11.65, 62.18)}, fetch=fetch)

    def test_next_point_after_completion_and_keep_zone_below_exit_level(self):
        result = find_leveling_point('alliance', 16, '西部荒野', completed_point='哨兵岭', fetch=lambda _: GUIDE)
        self.assertEqual(result['point']['name'], '萨丁农场')
        self.assertEqual((result['point']['x'], result['point']['y']), (56.0, 31.2))
        self.assertFalse(result['cross_zone'])

    def test_stage_transition_is_explicitly_cross_zone(self):
        for completed in ('', '萨丁农场'):
            with self.subTest(completed=completed):
                result = find_leveling_point('alliance', 17, '西部荒野',
                                             completed_point=completed, fetch=lambda _: GUIDE)
                self.assertEqual((result['stage'], result['point']['name']), (2, '奥伯丁'))
                self.assertTrue(result['cross_zone'])

    def test_rejects_unknown_point_missing_stage_and_unusable_coordinates(self):
        with self.assertRaisesRegex(ValueError, '唯一'):
            find_leveling_point('alliance', 15, '西部荒野', completed_point='无坐标点', fetch=lambda _: GUIDE)
        with self.assertRaisesRegex(ValueError, '结构'):
            find_leveling_point('alliance', 15, '西部荒野', fetch=lambda _: '<article>更换页面</article>')
        with self.assertRaisesRegex(ValueError, '坐标'):
            find_leveling_point('alliance', 11, '艾尔文森林', fetch=lambda _: GUIDE)
        invalid = stage(1, '12–17', leg('西部荒野', 'westfall', [('坐标无效', '100.1, 31.2')]))
        with self.assertRaisesRegex(ValueError, '坐标'):
            find_leveling_point('alliance', 15, '西部荒野', fetch=lambda _: invalid)

    def test_cli_reports_fetch_failure_without_running_gui(self):
        with TemporaryDirectory() as directory:
            args = ['app', '--leveling-next', '--faction', 'horde', '--level', '15', '--zone', '贫瘠之地',
                    '--data-dir', directory]
            with patch('wowbuddy.automation.leveling_route.find_leveling_point', side_effect=OSError('offline')), \
                    patch.object(run_dev, 'launch') as launch:
                self.assertEqual(run_dev.main(args), 1)
                launch.assert_not_called()
            report = json.loads((Path(directory)/'leveling-next.json').read_text('utf8'))
            self.assertEqual(report, {'ok': False, 'error': 'offline'})


class CharacterStateIntegrationTests(unittest.TestCase):
    def setUp(self):
        host = (ROOT/'tests/addon_login_host.lua').read_text('utf8') + '''
            fixtureLife='alive';fixtureInstance=false;fixtureLevel=17
            function IsSpellKnown() return false end
            function UnitLevel() return fixtureLevel end
            function UnitIsPlayer(unit) return unit=='player' end
            function UnitPlayerControlled(unit) return unit=='player' end
            function UnitIsTapDenied() return false end
            function UnitFactionGroup() return 'Alliance','联盟' end
            function IsInInstance() return fixtureInstance end
            function UnitIsGhost() return fixtureLife=='ghost' end
            function CombatLogGetCurrentEventInfo()
                return now,fixtureLogKind,false,fixtureLogSource,nil,0,0,fixtureLogTarget,nil,0,0,fixtureLogSpell
            end
            local oldDead=UnitIsDeadOrGhost
            function UnitIsDeadOrGhost(unit)
                if unit=='player' then return fixtureLife~='alive' end
                return oldDead(unit)
            end
            C_Map={
                GetBestMapForUnit=function(unit) assert(unit=='player');return 52 end,
                GetMapInfo=function(id) assert(id==52);return {name='西部荒野',mapType=3} end,
                GetPlayerMapPosition=function(id,unit)
                    assert(id==52 and unit=='player')
                    return {GetXY=function() return 0.3212,0.3615 end}
                end,
            }
        '''
        self.lua, _ = full_load.AddonFullLoadTests().load(full_load.SOURCE, 'WowBuddyDev', host)
        self.g = self.lua.globals()
        self.g.EmitFixtureEvent('ADDON_LOADED', 'WowBuddyDev')
        self.g.EmitFixtureEvent('PLAYER_LOGIN')
        self.g.WowBuddyDev.RebuildPixelBars()
        self.render = self.lua.execute('''
            for _,frame in ipairs(frames) do
                local callback=frame.scripts.OnUpdate
                if callback and debug.getinfo(callback,'S').source=='@PixelBar.lua' then
                    return function() now=now+0.25;callback(frame,0.25) end
                end
            end
            error('no PixelBar callback')
        ''')
        self.pipeline = Assets.load(ROOT/'assets').pipeline()

    def game_image(self, scale=1):
        self.render()
        pixels = [[0x141414] * 32 for _ in range(1440)]
        for rect in self.g.visiblePixelRectangles().values():
            color = (round(rect.r * 255) << 16) | (round(rect.g * 255) << 8) | round(rect.b * 255)
            for y in range(round(rect.y * scale), round((rect.y + rect.height) * scale)):
                for x in range(round(rect.x * scale), round((rect.x + rect.width) * scale)):
                    pixels[y][x] = color
        return RGBImage(pixels)

    def test_quest_pin_reads_the_completed_local_quest_from_world_map_data(self):
        from wowbuddy.engine.character_state import QuestTurnInPin, decode_quest_turn_in_pin

        self.lua.execute('''
            fixtureQuestReady=true
            C_QuestLog={
                GetNumQuestLogEntries=function() return 4 end,
                GetQuestIDForLogIndex=function(index) return ({[2]=191,[3]=192,[4]=193})[index] end,
                ReadyForTurnIn=function(id) return fixtureQuestReady and id~=191 end,
                GetQuestsOnMap=function(id)
                    assert(id==52)
                    return {
                        {questID=191,x=0.3212,y=0.3615},
                        {questID=192,x=0.3213,y=0.3616,isMapIndicatorQuest=true},
                        {questID=193,x=0.4123,y=0.5678},
                        {questID=999,x=0.3212,y=0.3615},
                    }
                end,
            }
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_quest_turn_in_pin(image, frame)

        self.assertEqual(sample(), QuestTurnInPin(193, 52, 41.23, 56.78))
        self.g.fixtureQuestReady = False
        self.assertIsNone(sample())
        self.g.fixtureQuestReady = True
        self.g.fixtureLife = 'ghost'
        self.assertIsNone(sample())

    def test_quest_pin_uses_the_remote_zone_pin_instead_of_its_waypoint(self):
        from wowbuddy.engine.character_state import QuestTurnInPin, decode_quest_turn_in_pin

        self.lua.execute('''
            local getMapInfo=C_Map.GetMapInfo
            C_Map.GetMapInfo=function(id)
                if id==1433 then return {name="赤脊山",mapType=3} end
                return getMapInfo(id)
            end
            C_QuestLog={
                GetNumQuestLogEntries=function() return 1 end,
                GetQuestIDForLogIndex=function() return 87 end,
                ReadyForTurnIn=function() return true end,
                GetNextWaypoint=function() return 1433,0.02,0.05 end,
                GetQuestsOnMap=function(id)
                    if id==1433 then return {{questID=87,x=0.31,y=0.62}} end
                end,
            }
        ''')
        image = self.game_image()
        frame, _ = self.pipeline.decode(image)
        self.assertEqual(decode_quest_turn_in_pin(image, frame), QuestTurnInPin(87, 1433, 31, 62))

    def test_native_quest_dialog_turn_in_uses_task_id_hover_and_game_receipt(self):
        from wowbuddy.engine.character_state import decode_quest_dialog, decode_quest_turn_in_pin
        from wowbuddy.automation.quest_turn_in import QuestTurnIn

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixtureQuestID,fixtureRequiredMoney,fixtureChoices,fixtureQuestStage=193,0,0,"world"
            fixtureQuestReady=true
            C_QuestLog={
                GetNumQuestLogEntries=function() return 1 end,
                GetQuestIDForLogIndex=function() return 193 end,
                ReadyForTurnIn=function() return fixtureQuestReady end,
                GetQuestsOnMap=function() return {{questID=193,x=0.3212,y=0.3615}} end,
            }
            function UnitGUID(unit)
                if unit=="questnpc" or unit=="softinteract" or unit=="npc" then
                    return "Creature-0-0-0-0-12345-ABCD"
                end
                if unit=="target" and fixtureCorpse then return "Creature-0-0-0-0-12346-FFFF" end
            end
            function UnitCanAssist(_, unit) return UnitGUID(unit)~=nil end
            function UnitExists(unit) return unit~="target" or fixtureCorpse==true end
            local dead=UnitIsDeadOrGhost
            function UnitIsDeadOrGhost(unit)
                if unit=="target" and fixtureCorpse then return true end
                return dead(unit)
            end
            function CanLootUnit() return fixtureCorpseLoot,fixtureCorpseLoot end
            function UnitAffectingCombat() return false end
            function GetUnitSpeed() return 0 end
            function GetCurrentKeyBoardFocus() end
            function GetCursorInfo() end
            function GetBindingKey(action) if action=="INTERACTTARGET" then return "F7" end end
            function GetBindingAction(key, overrides)
                if key=="F7" then return "INTERACTTARGET" end
                if overrides then
                    for _,frame in ipairs(frames) do
                        local binding=frame.bindings and frame.bindings[key]
                        if binding then return "CLICK "..binding.button..":LeftButton" end
                    end
                end
                return ""
            end
            function GetQuestID() return fixtureQuestID end
            function GetQuestMoneyToGet() return fixtureRequiredMoney end
            function GetNumQuestChoices() return fixtureChoices end
            function IsQuestCompletable() return true end
            function StaticPopup_ForEachShownDialog(callback) if fixturePopup then callback({}) end end
            UIParent={
                GetEffectiveScale=function() return 1 end,
                GetWidth=function() return 1000 end, GetHeight=function() return 1000 end,
            }
            local function panel(stage) return {IsVisible=function() return fixtureQuestStage==stage end} end
            local function button(stage, x)
                local result=panel(stage)
                result.IsEnabled=function() return true end
                result.GetCenter=function() return x,300 end
                result.GetEffectiveScale=function() return 1 end
                return result
            end
            QuestFrameProgressPanel=panel("progress")
            QuestFrameRewardPanel=panel("reward")
            QuestFrameCompleteButton=button("progress",200)
            QuestFrameCompleteQuestButton=button("reward",300)
            fixtureGossipButton=button("gossip",400)
            GOSSIP_BUTTON_TYPE_ACTIVE_QUEST=4
            function fixtureGossipButton:GetElementData()
                return {buttonType=fixtureGossipType,info={questID=fixtureQuestID,isComplete=true}}
            end
            GossipFrame=panel("gossip")
            GossipFrame.GreetingPanel={ScrollBox={GetFrames=function() return {fixtureGossipButton} end}}
            function GetMouseFoci()
                if not fixtureHover then return {} end
                return {fixtureQuestStage=="progress" and QuestFrameCompleteButton
                    or fixtureQuestStage=="reward" and QuestFrameCompleteQuestButton or fixtureGossipButton}
            end
            WowBuddyDev.RefreshMacroBindings()
            local clear=WowBuddyDev.GetSecureButton("clear_quest_corpse_target")
            function clear:GetName() return self.name end
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_quest_turn_in_pin(image, frame), decode_quest_dialog(image, frame)

        self.g.fixtureCorpse = True
        pin, reading = sample()
        self.assertEqual(reading.stage, 0)  # 拾取结果不可读，保留尸体。
        job = QuestTurnIn(pin, reading)
        send = Mock(return_value=True)
        self.g.fixtureCorpseLoot = True
        job.observe(sample()[1], 0, send=send)
        send.assert_not_called()
        self.g.fixtureCorpseLoot = False
        self.g.EmitFixtureEvent('LOOT_OPENED')
        self.assertEqual(sample()[1].stage, 7)
        self.g.EmitFixtureEvent('LOOT_CLOSED')
        clear = sample()[1]
        self.assertEqual((clear.stage, clear.interact_vk), (8, 0))
        self.assertTrue(clear.clear_key)
        self.assertIn('尸体目标', job.observe(clear, 200, send=send))
        job.observe(clear, 1800, send=send)
        self.assertEqual(send.call_count, 1)  # 重复的帧不得发第二次。
        self.g.fixtureCorpse = False
        _, reading = sample()
        self.assertEqual((reading.stage, reading.interact_vk), (1, 0x76))
        self.assertIn('附近 NPC', job.observe(reading, 550, send=send))
        job.observe(sample()[1], 900, send=send)
        self.assertEqual(send.call_count, 2)
        self.g.fixtureQuestStage, self.g.fixtureGossipType = 'gossip', 5
        self.assertEqual(sample()[1].stage, 7)
        self.g.fixtureGossipType, self.g.fixtureHover = 4, True
        self.assertEqual(sample()[1].stage, 2)
        self.g.fixtureQuestStage, self.g.fixtureQuestID = 'progress', 999
        wrong = sample()[1]
        self.assertEqual((wrong.quest_id, wrong.stage), (999, 3))
        job.observe(wrong, 950, send=send)
        self.assertEqual(send.call_count, 2)
        self.g.fixtureQuestID, self.g.fixtureHover = 193, False
        job.observe(sample()[1], 1000, send=send)
        self.g.fixtureHover = True
        job.observe(sample()[1], 1250, send=send)
        self.g.fixtureQuestStage, self.g.fixtureChoices = 'reward', 2
        self.assertIn('可选奖励', job.observe(sample()[1], 1500, send=send))
        self.g.fixtureChoices, self.g.fixtureRequiredMoney = 0, 10
        self.assertIn('费用', job.observe(sample()[1], 1750, send=send))
        self.g.fixtureRequiredMoney = None
        self.assertEqual(sample()[1].stage, 7)
        self.g.fixtureRequiredMoney, self.g.fixturePopup = 0, True
        self.assertEqual(sample()[1].stage, 7)
        self.g.fixturePopup = False
        self.g.fixtureQuestReady, self.g.fixtureChoices = False, 1
        hidden_pin, active_dialog = sample()
        self.assertIsNone(hidden_pin)
        self.assertEqual((active_dialog.quest_id, active_dialog.stage), (193, 4))
        self.assertIn('等待游戏确认', job.observe(active_dialog, 2000, send=send))
        self.assertFalse(job.observe_receipt(sample()[1]))
        self.assertIsNone(job.deferral_reason(sample()[1], 6999))
        self.assertEqual(job.deferral_reason(sample()[1], 7000), '游戏未确认任务交付')
        self.g.fixtureChoices = 2
        self.assertIsNone(job.deferral_reason(sample()[1], 7200))
        self.assertIn('可选奖励', job.observe(sample()[1], 7200, send=send))
        self.g.EmitFixtureEvent('QUEST_TURNED_IN', 999, 0, 0)
        self.assertFalse(job.observe_receipt(sample()[1]))
        self.g.EmitFixtureEvent('QUEST_TURNED_IN', 193, 125, 0)
        gone, received = sample()
        self.assertIsNone(gone)
        self.assertTrue(job.observe_receipt(received))
        self.assertEqual([call.args for call in send.call_args_list], [
            ('select', clear.clear_key), ('interact', 0x76), ('hover', (2000, 7000)),
            ('quest_click', (2000, 7000)), ('quest_click', (3000, 7000)),
        ])
        retry = QuestTurnIn(pin, reading)
        send.reset_mock()
        for offset, now in enumerate((0, 1000, 1200, 2400)):
            retry.observe(replace(reading, sequence=reading.sequence + offset), now, send=send)
        self.assertEqual([call.args for call in send.call_args_list], [('interact', 0x76)] * 2)

    def test_taxi_pixels_report_only_the_verified_native_route_and_flight_state(self):
        from wowbuddy.engine.character_state import decode_taxi_state

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixtureMap=1438;fixtureNpc=3838;fixtureFare=0;fixtureDestination=26
            function UnitCanAttack() return false end
            function UnitGUID(unit) return unit=='target' and ('Creature-0-0-0-0-'..fixtureNpc..'-ABC') end
            function UnitOnTaxi() return fixtureRiding==true end
            function GetCurrentKeyBoardFocus() if fixtureFocus then return {} end end
            function GetUnitSpeed() return 0 end
            function GetCursorInfo() return nil end
            function GetMouseFoci() return {TaxiButton2} end
            TaxiFrame={IsShown=function() return true end}
            TaxiButton2={GetID=function() return 2 end, IsVisible=function() return true end,
                IsEnabled=function() return true end, GetEffectiveScale=function() return 1 end,
                GetCenter=function() return 200,300 end}
            UIParent.GetEffectiveScale=function() return 1 end
            UIParent.GetWidth=function() return 1000 end
            UIParent.GetHeight=function() return 1000 end
            C_TaxiMap={GetAllTaxiNodes=function(map)
                assert(map==1414);return {{nodeID=27,state=0,slotIndex=1},
                    {nodeID=fixtureDestination,state=1,slotIndex=2}}
            end}
            function TaxiNodeGetType(slot) return slot==1 and 'CURRENT' or 'REACHABLE' end
            function TaxiIsDirectFlight() return true end
            function TaxiNodeCost() return fixtureFare end
            function TaxiGetNodeSlot(_, _, source) return source and 1 or 2 end
            function TakeTaxiNode() error('插件不能直接登机') end
            C_Map.GetBestMapForUnit=function() return fixtureMap end
            C_Map.GetMapInfo=function() return {name='泰达希尔',mapType=3} end
            C_Map.GetPlayerMapPosition=function() return {GetXY=function() return .584,.939 end} end
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_taxi_state(image, frame)

        matched = sample()
        self.assertTrue(matched.selected and matched.panel_open and matched.hovered)
        self.assertEqual(matched.button, (2000, 7000))
        self.lua.execute('WorldMapFrame={IsVisible=function() return fixtureMapOpen==true end}')
        self.g.fixtureMapOpen = True
        self.assertTrue(sample().blocked)
        self.assertIsNone(sample().button)
        self.g.fixtureMapOpen = False
        for field, invalid, valid in (('fixtureNpc', 1234, 3838), ('fixtureFare', 1, 0),
                                      ('fixtureDestination', 28, 26), ('fixtureFocus', True, False)):
            with self.subTest(field=field):
                self.g[field] = invalid
                self.assertIsNone(sample().button)
                self.g[field] = valid

        self.lua.execute('''
            TaxiFrame.IsShown=function() return fixtureLegacyPanel==true end
            FlightMapFrame={IsShown=function() return true end, GetMapID=function() return fixtureFlightMap end}
            fixtureFlightMap=947
            function GetTaxiMapID() return 1414 end
            function GetNumRoutes() return fixtureRoutes or 1 end
            function TaxiNodeGetType() error('新版无需旧式航点类型') end
            C_TaxiMap.GetAllTaxiNodes=function(map)
                assert(map==947); return {{nodeID=27,state=0,slotIndex=1},
                    {nodeID=26,state=1,slotIndex=2,specialIconCostString=fixtureRouteCost}}
            end
            fixturePin={taxiNodeData={nodeID=26,state=1,slotIndex=2},
                GetMap=function() return FlightMapFrame end, IsVisible=function() return true end,
                IsMouseEnabled=function() return not fixturePinDisabled end,
                GetCenter=function() return 350,650 end, GetEffectiveScale=function() return 1 end}
            function FlightMapFrame:EnumeratePinsByTemplate(template)
                assert(template=='FlightMap_FlightPointPinTemplate')
                local active={[fixturePin]=true}
                if fixtureDuplicate then active[setmetatable({}, {__index=fixturePin})]=true end
                return pairs(active)
            end
            function GetMouseFoci() return {fixtureWrongHover and TaxiButton2 or fixturePin} end
        ''')
        modern = sample()
        self.assertTrue(modern.panel_open and modern.hovered)
        self.assertEqual(modern.button, (3500, 3500))
        self.g.fixtureWrongHover = True
        self.assertFalse(sample().hovered)
        for field, invalid, valid in (('fixtureFlightMap', None, 947), ('fixtureRoutes', 2, 1),
                                      ('fixtureLegacyPanel', True, False), ('fixturePinDisabled', True, False),
                                      ('fixtureDuplicate', True, False), ('fixtureRouteCost', '有额外费用', None)):
            with self.subTest(field=field):
                self.g[field] = invalid
                self.assertIsNone(sample().button)
                self.g[field] = valid
        self.g.fixturePin.taxiNodeData.slotIndex = 3
        self.assertIsNone(sample().button)
        self.g.fixturePin.taxiNodeData.slotIndex = 2
        self.g.fixturePin.isMapLayerTransition = True
        self.assertIsNone(sample().button)
        self.g.fixtureRiding = True
        self.g.fixtureMap = 1439
        self.assertTrue(sample().riding)
        self.g.fixtureRiding = False
        self.assertFalse(sample().riding)

    def test_vendor_pixels_require_a_matching_open_shop_and_report_general_slots(self):
        from wowbuddy.engine.character_state import decode_vendor_state

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            WowBuddyDevDB.supplyVendor='杂货商'
            function UnitName(unit) return unit=='target' and '杂货商' or fixtureShopName end
            function UnitCanAttack() return false end
            C_Container={GetContainerNumSlots=function(bag) return bag==4 and 0 or 12 end,
                GetContainerNumFreeSlots=function(bag) assert(bag<4);return 2,bag==0 and 0 or 8 end}
            C_MerchantFrame={GetNumJunkItems=function() return fixtureJunk or 3 end,
                IsSellAllJunkEnabled=function() return fixtureJunk ~= 0 end}
            MerchantFrame={selectedTab=1, IsShown=function() return true end}
            MerchantSellAllJunkButton={IsVisible=function() return true end, IsEnabled=function() return true end,
                IsMouseOver=function() return true end, GetEffectiveScale=function() return 1 end,
                GetCenter=function() return 200,300 end}
            UIParent.GetEffectiveScale=function() return 1 end
            UIParent.GetWidth=function() return 1000 end
            UIParent.GetHeight=function() return 1000 end
        ''')
        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_vendor_state(image, frame)

        wrong = sample()
        self.assertTrue(wrong.merchant_open)
        self.assertFalse(wrong.matched)
        self.assertIsNone(wrong.sell_point)
        self.g.fixtureShopName = '杂货商'
        matched = sample()
        self.assertEqual((matched.free, matched.junk), (2, 3))
        self.assertTrue(matched.selected and matched.matched and matched.hovered)
        self.assertEqual(matched.sell_point, (2000, 7000))
        self.lua.execute('''
            SELL_ALL_JUNK_ITEMS_POPUP='出售所有杂物？'
            function MerchantFrame_OnSellAllJunkButtonConfirmed() error('只允许读取') end
            fixtureConfirm={IsVisible=function() return true end, IsEnabled=function() return true end,
                GetEffectiveScale=function() return 1 end, GetCenter=function() return 520,360 end}
            function GetCurrentKeyBoardFocus() return nil end
            function GetMouseFoci() return {fixtureMouseFocus} end
            fixturePopup={which='GENERIC_CONFIRMATION',
                data={text=SELL_ALL_JUNK_ITEMS_POPUP, callback=function() end},
                GetButton1=function() return fixtureConfirm end}
            function StaticPopup_ForEachShownDialog(callback)
                callback(fixturePopup)
                if fixtureSecondPopup then callback({which='DELETE_ITEM'}) end
            end
        ''')
        unrelated = sample()
        self.assertTrue(unrelated.popup_blocked)
        self.assertFalse(unrelated.confirming)
        self.assertIsNone(unrelated.sell_point)
        self.lua.execute('fixturePopup.data.callback=MerchantFrame_OnSellAllJunkButtonConfirmed')
        confirming = sample()
        self.assertTrue(confirming.confirming)
        self.assertFalse(confirming.hovered)
        self.assertEqual(confirming.sell_point, (5200, 6400))
        self.lua.execute('fixtureMouseFocus=fixtureConfirm')
        self.assertTrue(sample().hovered)
        self.g.fixtureJunk = 0
        emptied = sample()
        self.assertTrue(emptied.confirming)
        self.assertFalse(emptied.popup_blocked)
        self.assertIsNone(emptied.sell_point)
        self.g.fixtureSecondPopup = True
        stacked = sample()
        self.assertTrue(stacked.popup_blocked)
        self.assertIsNone(stacked.sell_point)

        self.lua.execute('''
            function StaticPopup_ForEachShownDialog() end
            function GetInventoryAlertStatus(slot) return slot==9 and fixtureDurability or 0 end
            function CanMerchantRepair() return fixtureCanRepair end
            function GetRepairAllCost() return 75,true end
            function GetMoney() return fixtureMoney end
            MerchantRepairAllButton=fixtureConfirm
            fixtureDurability, fixtureCanRepair, fixtureMoney=2, true, 74
        ''')
        self.pipeline.unattended_grinding = True

        def repair_sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return frame, decode_vendor_state(image, frame, repair=True)

        frame, repair = repair_sample()
        self.assertEqual((frame.values['equipment_red'], repair.repair_needed, repair.repair_status), ('ON', True, 2))
        self.assertIsNone(repair.sell_point)
        self.g.fixtureCanRepair = False
        self.assertEqual(repair_sample()[1].repair_status, 1)
        self.g.fixtureCanRepair, self.g.fixtureMoney = True, 75
        repair = repair_sample()[1]
        self.assertEqual((repair.repair_status, repair.sell_point, repair.hovered), (3, (5200, 6400), True))
        self.g.fixtureDurability = 1
        frame, repair = repair_sample()
        self.assertNotIn('equipment_red', frame.values)
        self.assertIs(repair.repair_needed, False)

    def test_darkshore_vendor_reports_catalog_identity_without_overwriting_manual_name(self):
        from wowbuddy.engine.character_state import decode_vendor_state

        self.lua.execute('''
            WowBuddyDevDB.supplyVendor='其他地图的商人'
            function GetBindingKey(action) if action=='INTERACTTARGET' then return 'F7' end end
            local overrides={}
            local oldOverride=SetOverrideBindingClick
            function SetOverrideBindingClick(owner,priority,key,button,mouse)
                overrides[key]='CLICK '..button..':'..mouse
                return oldOverride(owner,priority,key,button,mouse)
            end
            function GetBindingAction(key, override)
                return key=='F7' and 'INTERACTTARGET' or override and overrides[key] or ''
            end
            function UnitFactionGroup() return 'Alliance' end
            function UnitName(unit) return (unit=='target' or unit=='npc') and '提亚尼' or '测试角色' end
            function UnitGUID(unit)
                if unit=='target' or unit=='npc' then return 'Creature-0-0-0-0-'..fixtureVendorId..'-ABC' end
            end
            function UnitCanAttack() return false end
            C_Map.GetBestMapForUnit=function() return 1439 end
            C_Map.GetMapInfo=function() return {name='黑海岸',mapType=3} end
            C_Map.GetPlayerMapPosition=function() return {GetXY=function() return .4,.7 end} end
            C_Container={GetContainerNumSlots=function() return 12 end,
                         GetContainerNumFreeSlots=function() return 0,0 end}
            C_MerchantFrame={GetNumJunkItems=function() return 0 end}
            MerchantFrame={selectedTab=1, IsShown=function() return fixtureVendorOpen end}
            WowBuddyDev.ApplyDiscardTargetBinding()
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_vendor_state(image, frame)

        self.g.fixtureVendorId = 1234
        self.g.fixtureVendorOpen = True
        wrong = sample()
        self.assertEqual((wrong.free, wrong.junk), (0, 0))
        self.assertTrue(wrong.catalog and wrong.merchant_open and wrong.select_key)
        self.assertFalse(wrong.selected or wrong.matched)
        self.g.fixtureVendorId = 4195
        matched = sample()
        self.assertTrue(matched.selected and matched.matched)
        self.assertEqual(self.g.WowBuddyDevDB.supplyVendor, '其他地图的商人')
        self.g.WowBuddyDevDB.supplyVendorMap = 1439
        manual = sample()
        self.assertFalse(manual.catalog or manual.matched)

    def test_session_marker_survives_zone_load_and_rejects_a_damaged_packet(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute((ROOT/'tests/addon_world_host.lua').read_text('utf8'))
        tokens = []
        for scale in (0.8, 1, 1.25):
            if tokens:
                self.g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', False, False)
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            token = decode_character_session(image, frame)
            self.assertIsNotNone(token)
            tokens.append(token)
            pixels = [list(row) for row in image.rows]
            for y in range(round(384 * scale), round(388 * scale)):
                for x in range(round(4 * scale), round(8 * scale)):
                    pixels[y][x] ^= 1
            self.assertIsNone(decode_character_session(RGBImage(pixels), frame))
        self.assertEqual(len(set(tokens)), 1)

    def test_travel_identity_matches_the_character_across_game_sessions(self):
        from wowbuddy.engine.character_state import decode_travel_identity

        def sample(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            session = decode_character_session(image, frame)
            self.assertIsNotNone(session)
            identity = decode_travel_identity(image, frame, session)
            self.assertIsNone(decode_travel_identity(image, frame, session + 1))
            return session, identity

        self.lua.execute("function UnitGUID(unit) if unit=='player' then return 'fixture-player-a' end end")
        token, identity = sample()
        self.assertIsNotNone(identity)
        for scale in (0.8, 1, 1.25):
            self.assertEqual(sample(scale), (token, identity))

        self.setUp()
        self.lua.execute((ROOT/'tests/addon_world_host.lua').read_text('utf8'))
        self.g.now = 400
        self.lua.execute("function UnitGUID(unit) if unit=='player' then return 'fixture-player-a' end end")
        new_token, same_character = sample()
        self.assertNotEqual(new_token, token)
        self.assertEqual(same_character, identity)

        self.g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', False, False)
        self.lua.execute("function UnitGUID(unit) if unit=='player' then return 'fixture-player-b' end end")
        other_token, other_character = sample()
        self.assertEqual(other_token, new_token)
        self.assertIsNotNone(other_character)
        self.assertNotEqual(other_character, identity)

        self.g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', False, False)
        self.lua.execute("local hidden={}; function UnitGUID() return hidden end; function issecretvalue(v) return v==hidden end")
        self.assertEqual(sample(), (new_token, None))

    def test_game_experience_updates_and_combat_notices_are_logged_independently(self):
        import test_dev_tray
        from wowbuddy.engine.character_state import LevelProgress, decode_level_progress

        self.lua.execute('''
            fixtureXP=100
            function UnitXP(unit) assert(unit=='player'); return fixtureXP end
            function UnitXPMax(unit) assert(unit=='player'); return 1200 end
        ''')

        def sample(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            return image, frame, decode_character_session(image, frame)

        for scale in (0.8, 1, 1.25):
            image, frame, token = sample(scale)
            self.assertEqual(decode_level_progress(image, frame, token), LevelProgress(17, 100, 1200, 0))
            self.assertIsNone(decode_level_progress(image, frame, token + 1))
        image, frame, token = sample()
        pixels = [list(row) for row in image.rows]
        for y in range(131 * 4, 132 * 4):
            pixels[y][6] ^= 1
        self.assertIsNone(decode_level_progress(RGBImage(pixels), frame, token))

        def exercise(window):
            window.grind_check.setChecked(True)
            now_ms = 1000
            monitor = (123, 1)

            def observe():
                nonlocal now_ms
                now_ms += 250
                image, frame, _ = sample()
                capture = SimpleNamespace(image=image, backend='offline fixture')
                window._hold_character_frame(monitor, capture, frame, now_ms)

            with patch.object(window.logger, 'append') as log:
                observe()
                observe()
                self.g.fixtureXP = 135
                observe()
                observe()
                self.g.EmitFixtureEvent('CHAT_MSG_COMBAT_XP_GAIN', 'fixture message')
                observe()
                self.g.fixtureXP = None
                self.g.EmitFixtureEvent('CHAT_MSG_COMBAT_XP_GAIN', 'fixture message')
                observe()
                observe()
                self.g.fixtureLevel, self.g.fixtureXP = 18, 4
                observe()
                monitor = (123, 2)
                observe()
                observe()
            self.assertEqual([call.args[0] for call in log.call_args_list], [
                '游戏经验起点：17 级 100/1200。',
                '游戏经验增加 35（135/1200）。',
                '游戏新增 1 条战斗经验回执。',
                '游戏新增 1 条战斗经验回执。',
                '游戏确认升级：17 → 18 级（4/1200）。',
                '游戏经验起点：18 级 4/1200。',
            ])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_confirmed_line_of_sight_failures_stop_only_unattended_attack_candidates(self):
        from wowbuddy.core.candidates import Candidate

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.g.WowBuddyDev.DB.autoTarget = True
        self.lua.execute('''
            function GetPlayerFacing() return 0 end
            function GetUnitSpeed() return 0 end
            function C_Map.GetMapWorldSize() return 1000,800 end
            function UnitCanAttack(_, unit) return unit=='target' end
            function UnitExists(unit) return unit=='target' or unit=='player' end
            function UnitPlayerControlled() return false end
            function UnitName(unit) if unit=='target' then return 'Enemy' end end
            function UnitIsDeadOrGhost() return false end
            local keys={MOVEFORWARD='W', TURNLEFT='A', TURNRIGHT='D', TARGETNEARESTENEMY='TAB'}
            local action={W='MOVEFORWARD', A='TURNLEFT', D='TURNRIGHT', TAB='TARGETNEARESTENEMY'}
            function GetBindingKey(name) return keys[name] end
            function GetBindingAction(key) return action[key] or '' end
            SPELL_FAILED_LINE_OF_SIGHT='Fixture line of sight'
            assert(WowBuddyDev.SetPostKillAutoTargetEnabled(true))
        ''')
        emit = self.g.EmitFixtureEvent

        def failed(guid, *, target='Enemy', reverse=False):
            emit('UNIT_SPELLCAST_SENT', 'player', target, guid, 116)
            if reverse:
                emit('UNIT_SPELLCAST_FAILED', 'player', guid, 116)
            emit('UI_ERROR_MESSAGE', 1, 'Fixture line of sight')
            if not reverse:
                emit('UNIT_SPELLCAST_FAILED', 'player', guid, 116)

        def sample(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            return image, frame, decode_navigation_state(image, frame)

        failed('cast1')
        emit('UNIT_SPELLCAST_FAILED', 'player', 'cast1', 116)
        failed('other', target='Another enemy')
        self.assertFalse(sample()[2].sight_blocked)
        failed('cast2', reverse=True)
        image, frame, position = sample()
        self.assertTrue(position.sight_blocked)
        for scale in (0.8, 1.25):
            self.assertTrue(sample(scale)[2].sight_blocked)
        # 游戏宿主不提供完整敌方字段，用真实色格配对后补足循环的输入。
        fields = dict(frame.values, target_valid='ON', player_in_combat='OFF', master_switch='ON')
        frame = replace(frame, values=fields)
        with (patch.object(self.pipeline.old, 'decode', return_value=frame),
              patch.object(self.pipeline.recovery, 'evaluate', return_value=(True, None)),
              patch.object(self.pipeline.engine, 'generate', return_value=(
                  Candidate(action='spell_116', tag='输出'), Candidate(action='spell_1459', tag='增益')))):
            self.assertFalse(self.pipeline.evaluate(image).attack_blocked_by_sight)
            self.pipeline.skip_obstructed_targets = True
            decision = self.pipeline.evaluate(image)
            self.assertTrue(decision.attack_blocked_by_sight)
            self.assertEqual([candidate.action for candidate in decision.candidates], ['spell_1459'])
        emit('PLAYER_TARGET_CHANGED')
        self.assertFalse(sample()[2].sight_blocked)

    def test_frost_nova_cooldown_controls_the_spell_availability_bitmap(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.g.targetAlive = True
        self.lua.execute('''
            function IsSpellKnown(id) return id == 122 or id == 865 or id == 837 end
            function UnitCanAttack(_, unit) return unit == "target" end
            local addon = WowBuddyDev
            addon.IsSpellUsable = function(id) return id == 122 or id == 865 or id == 837 end
            addon.GetSpellCooldownRemaining = function() return 0 end
            C_Spell = C_Spell or {}
            C_Spell.GetSpellCooldownDuration = function(id, ignoreGCD)
                assert(id == 865 and ignoreGCD == true)
                if cooldownUnobservable then return nil end
                return { GetRemainingDuration = function() return novaRemaining end }
            end
        ''')
        spell_ids = self.pipeline.engine.specs['1482']['actionAvailSpellIDs']
        bit = 1 << (spell_ids.index(122) + 1)

        def ready():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok)
            return bool(int(frame.values['action_avail']) & bit)

        self.g.novaRemaining = 9
        self.assertFalse(ready())
        self.g.novaRemaining = 0
        self.assertTrue(ready())

        self.g.cooldownUnobservable = True
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'nova-rank-2', 865)
        self.assertFalse(ready())
        self.g.now += 18
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_FAILED', 'player', 'failed-nova', 865)
        self.assertFalse(ready())
        self.g.now += 7
        self.assertTrue(ready())
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'nova-rank-2-again', 865)
        self.assertFalse(ready())
        self.g.now += 1
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'cold-snap', 11958)
        self.assertTrue(ready())

    def test_cast_feedback_distinguishes_game_acceptance_start_and_interruption(self):
        from wowbuddy.engine.character_state import CastFeedback, decode_cast_feedback

        self.lua.execute((ROOT/'tests/addon_world_host.lua').read_text('utf8'))
        emit = self.g.EmitFixtureEvent

        def read(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            return image, frame, decode_cast_feedback(image, frame)

        self.assertIsNone(read()[2])
        emit('UNIT_SPELLCAST_SENT', 'player', '狼蛛', 'Cast-1', 837)
        emit('UNIT_SPELLCAST_START', 'player', 'Cast-1', 837)
        emit('UNIT_SPELLCAST_INTERRUPTED', 'player', 'Cast-1', 837)
        emit('UNIT_SPELLCAST_SUCCEEDED', 'pet', 'Cast-2', 122)
        for scale in (0.8, 1, 1.25):
            image, frame, feedback = read(scale)
            self.assertEqual(feedback, CastFeedback(1, 837, ('提交', '开始读条', '中断')))
            pixels = [list(row) for row in image.rows]
            for y in range(round(404 * scale), round(408 * scale)):
                for x in range(round(4 * scale), round(8 * scale)):
                    pixels[y][x] ^= 1
            self.assertIsNone(decode_cast_feedback(RGBImage(pixels), frame))

        emit('UNIT_SPELLCAST_SENT', 'player', '狼蛛', 'Cast-3', 837)
        emit('UNIT_SPELLCAST_FAILED', 'player', 'Cast-3', 837)
        self.assertEqual(read()[2], CastFeedback(2, 837, ('提交', '失败')))
        emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Cast-4', 2137)
        self.assertEqual(read()[2], CastFeedback(3, 2137, ('成功',)))
        emit('PLAYER_ENTERING_WORLD', False, False)
        self.assertIsNone(read()[2])

    def test_cast_feedback_pairs_readable_errors_with_the_current_failed_attempt(self):
        from wowbuddy.engine.character_state import CastFeedback, decode_cast_feedback

        self.lua.execute((ROOT/'tests/addon_world_host.lua').read_text('utf8'))
        self.lua.execute('''
            SPELL_FAILED_UNIT_NOT_INFRONT = 'Fixture facing error'
            function GetGameMessageInfo(code)
                return ({ [19]='ERR_SPELL_FAILED_S', [20]='ERR_SPELL_OUT_OF_RANGE',
                          [21]='ERR_INV_FULL', [22]='ERR_SPELL_COOLDOWN' })[code]
            end
            function issecretvalue(value) return value == 22 end
        ''')
        emit = self.g.EmitFixtureEvent

        def sent(guid):
            emit('UNIT_SPELLCAST_SENT', 'player', '狼蛛', guid, 837)

        def failed(guid):
            emit('UNIT_SPELLCAST_FAILED', 'player', guid, 837)

        def error(code, message=''):
            emit('UI_ERROR_MESSAGE', code, message)

        def read(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            return image, frame, decode_cast_feedback(image, frame)

        sent('Cast-1')
        error(19, 'Fixture facing error')
        self.assertEqual(read()[2], CastFeedback(1, 837, ('提交',)))
        failed('Cast-1')
        for scale in (0.8, 1, 1.25):
            image, frame, feedback = read(scale)
            self.assertEqual(feedback, CastFeedback(1, 837, ('提交', '失败'), 19, '朝向'))
            pixels = [list(row) for row in image.rows]
            for y in range(round(412 * scale), round(416 * scale)):
                for x in range(round(4 * scale), round(8 * scale)):
                    pixels[y][x] ^= 1
            self.assertEqual(decode_cast_feedback(RGBImage(pixels), frame), CastFeedback(1, 837, ('提交', '失败')))

        sent('Cast-2')
        failed('Cast-2')
        error(21, 'Inventory full')
        error(22, 'Fixture facing error')
        self.assertEqual(read()[2], CastFeedback(2, 837, ('提交', '失败')))
        error(20)
        self.assertEqual(read()[2], CastFeedback(2, 837, ('提交', '失败'), 20, '距离'))
        self.g.now += 1
        error(19)
        self.assertEqual(read()[2], CastFeedback(2, 837, ('提交', '失败'), 20, '距离'))

        sent('Cast-3')
        error(19, 'Fixture facing error')
        error(20)
        failed('Cast-3')
        self.assertEqual(read()[2], CastFeedback(3, 837, ('提交', '失败')))
        sent('Cast-4')
        error(20)
        self.g.now += 1
        failed('Cast-4')
        self.assertEqual(read()[2], CastFeedback(4, 837, ('提交', '失败')))
        sent('Cast-5')
        error(19)
        emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Cast-5', 837)
        self.assertEqual(read()[2], CastFeedback(5, 837, ('提交', '成功')))

    def test_combat_facing_packet_requires_a_recent_failure_against_the_same_target(self):
        from wowbuddy.engine.character_state import CombatFacingSample, decode_cast_feedback, decode_combat_facing

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.g.combat = True
        self.lua.execute('''
            local hiddenSpeed = {}
            function GetUnitSpeed() return fixtureSpeed or hiddenSpeed end
            function issecretvalue(value) return value == hiddenSpeed end
            function UnitName(unit) if unit=='target' and not hideTargetName then return '狼蛛' end end
            function UnitCanAttack(_, unit) return unit=='target' end
            function UnitPlayerControlled() return false end
            function GetGameMessageInfo() return 'ERR_BADATTACKFACING' end
            function GetPlayerFacing() return 1 end
            function UnitPosition(unit)
                if unit=='player' then return 0,0,0,1 end
                if targetPosition then return 5,0,0,1 end
            end
            local keys={MOVEFORWARD='W',TURNLEFT='A',TURNRIGHT='D'}
            function GetBindingKey(action) return keys[action] end
            function GetBindingAction(key)
                for action, binding in pairs(keys) do if binding==key then return action end end
                if key=='NUMPAD5' and not hideSpellBinding then
                    for _, frame in ipairs(frames) do
                        local bound=frame.bindings and frame.bindings[key]
                        if bound then return 'CLICK '..bound.button..':'..bound.mouse end
                    end
                end
            end
        ''')
        emit = self.g.EmitFixtureEvent

        def failed(guid, target='狼蛛'):
            emit('UNIT_SPELLCAST_SENT', 'player', target, guid, 837)
            emit('UNIT_SPELLCAST_FAILED', 'player', guid, 837)
            emit('UI_ERROR_MESSAGE', 57, '')

        def read(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            feedback = decode_cast_feedback(image, frame)
            return decode_combat_facing(image, frame, feedback)

        self.g.fixtureSpeed = 0
        failed('Cast-1', '其他目标')
        self.assertIsNone(read())
        failed('Cast-2')
        keys = ord('W'), ord('A'), ord('D')
        self.assertEqual(read(), CombatFacingSample(0, keys))
        self.g.targetPosition = True
        for scale in (0.8, 1, 1.25):
            self.assertEqual(read(scale), CombatFacingSample(0, keys, 1.0, 0.0))
        emit('PLAYER_TARGET_CHANGED')
        self.assertIsNone(read())
        failed('Cast-3')
        self.assertEqual(read(), CombatFacingSample(1, keys, 1.0, 0.0))
        self.g.now += 2
        self.assertIsNone(read())
        failed('Cast-4', '')
        self.assertEqual(read(), CombatFacingSample(1, keys, 1.0, 0.0, 116))
        self.g.hideTargetName = True
        failed('Cast-5')
        self.assertEqual(read(0.8), CombatFacingSample(1, keys, 1.0, 0.0, 116))
        self.g.hideSpellBinding = True
        self.assertIsNone(read())
        self.g.hideSpellBinding = False
        self.g.fixtureSpeed = None
        failed('Cast-6', '')
        self.assertEqual(read(), CombatFacingSample(1, keys, 1.0, 0.0, 116))
        emit('PLAYER_STARTED_MOVING')
        self.assertIsNone(read())
        emit('PLAYER_STOPPED_MOVING')
        self.assertEqual(read(), CombatFacingSample(1, keys, 1.0, 0.0, 116))
        self.lua.execute("WowBuddyDev.GetBoundMacro=function() return '/cast [@focus,harm,nodead] 寒冰箭' end")
        self.assertIsNone(read())

    def test_nova_spacing_requires_a_matching_cast_root_and_increasing_distance(self):
        import test_dev_tray
        from wowbuddy.engine.character_state import decode_cast_feedback, decode_nova_spacing
        from wowbuddy.automation.navigation import NovaSpacing

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.g.combat = True
        self.g.targetAlive = True
        self.lua.execute('''
            local hiddenSpeed={}
            distance=5; heading=0; rootSource='player'; expires=100; fixtureSpeed=0
            function GetPlayerFacing() return heading end
            function GetUnitSpeed() return fixtureSpeed or hiddenSpeed end
            function issecretvalue(value) return value==hiddenSpeed end
            function C_Map.GetMapWorldSize() return nil end
            function UnitCanAttack(_, unit) return unit=='target' end
            function UnitPlayerControlled() return false end
            function UnitGUID(unit) return unit=='player' and 'fixture-player' or 'fixture-target' end
            function UnitPosition(unit)
                if unit=='player' then
                    if not hidePlayerPosition then return 0,0,0,1 end
                elseif distance then
                    return distance,0,0,targetWorld or 1
                end
            end
            function UnitIsUnit(unit, other) return unit=='vehicle' and other=='player' end
            C_UnitAuras={GetAuraDataByIndex=function(unit, index, filter)
                if hideAura then error('aura unavailable') end
                if unit=='target' and index==1 and filter=='HARMFUL|PLAYER' and rootSource then
                    return { spellId=865, sourceUnit=rootSource, expirationTime=expires }
                end
            end}
            local keys={MOVEFORWARD='W',MOVEBACKWARD='S',TURNLEFT='A',TURNRIGHT='D'}
            function GetBindingKey(action) return keys[action] end
            function GetBindingAction(key)
                for action,binding in pairs(keys) do
                    if binding==key and not (key=='S' and hideBack) then return action end
                end
            end
        ''')
        emit = self.g.EmitFixtureEvent
        emit('UNIT_SPELLCAST_SENT', 'player', '', 'Nova-1', 865)
        emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Nova-1', 865)

        def read(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            fields = dict(frame.values, player_in_combat='ON', master_switch='ON', player_valid='ON',
                          target_valid='ON', gcd='ON', player_moving='OFF', player_casting='空闲',
                          active_enemies=1, enemies_8yd=1)
            frame = replace(frame, values=fields)
            feedback = decode_cast_feedback(image, frame)
            return image, frame, *decode_nova_spacing(image, frame, feedback)

        for scale in (0.8, 1, 1.25):
            image, frame, sample, blockers = read(scale)
            self.assertIsNone(decode_navigation_state(image, frame, for_target=True))
            self.assertIsNotNone(sample)
            self.assertEqual((sample.keys, sample.distance), (tuple(map(ord, 'SWAD')), 5))
            self.assertEqual(blockers, ())
        self.g.fixtureSpeed = None
        emit('PLAYER_ALIVE')
        self.assertEqual(read()[2:], (None, ('角色未确认站定',)))
        emit('PLAYER_STARTED_MOVING')
        self.assertEqual(read()[2:], (None, ('角色未确认站定',)))
        emit('PLAYER_STOPPED_MOVING')
        self.assertIsNotNone(read()[2])
        self.g.fixtureSpeed = 7
        self.assertEqual(read()[2:], (None, ('角色未确认站定',)))
        self.g.fixtureSpeed = None
        emit('PLAYER_CONTROL_LOST')
        self.assertEqual(read()[2:], (None, ('角色未确认站定',)))
        self.g.fixtureSpeed = 0
        emit('UNIT_SPELLCAST_SENT', 'player', '', 'Nova-2', 865)
        emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Nova-2', 865)
        self.g.rootSource = 'party1'
        image, frame, sample, blockers = read()
        self.assertEqual((sample, blockers), (None, ('定身未确认来自当前角色',)))
        from wowbuddy.engine.character_state import _sample_column
        word = _sample_column(image, frame, calibration=((112, (0x57424F,)),))
        self.assertEqual(word(116), 5)
        pixels = [list(row) for row in image.rows]
        for y in range(117 * 4, 118 * 4):
            pixels[y][6] ^= 1
        damaged = RGBImage(pixels)
        self.assertEqual(decode_nova_spacing(damaged, frame, decode_cast_feedback(damaged, frame)),
                         (None, ('自身定身光环未确认',)))
        self.g.rootSource = 'vehicle'
        self.assertIsNotNone(read()[2])
        self.g.rootSource, self.g.heading = 'player', 3.14
        self.assertEqual(read()[2:], (None, ('距离或角度不适合后退',)))
        self.g.heading, self.g.distance, self.g.hideBack = None, None, True
        self.assertEqual(read()[2:], (None, ('移动键绑定未确认', '角色朝向不可读', '目标世界坐标不可读')))
        self.g.heading, self.g.distance, self.g.hideBack = 0, 5, False
        self.g.hidePlayerPosition, self.g.hideAura = True, True
        self.assertEqual(read()[2:], (None, ('角色世界坐标不可读', '定身光环查询不可读')))
        self.g.hidePlayerPosition, self.g.hideAura = False, False
        self.g.targetWorld, self.g.expires = 2, None
        self.assertEqual(read()[2:], (None, ('角色和目标世界坐标不在同一区域', '定身剩余时间不可读')))
        self.g.targetWorld, self.g.expires = 1, 100
        self.g.rootSource = None
        self.assertEqual(read()[2:], (None, ('未找到冰霜新星光环',)))
        self.g.rootSource = 'player'
        emit('PLAYER_TARGET_CHANGED')
        self.assertEqual(read()[2:], (None, ('目标已变化或不可攻击',)))

        def exercise(window):
            window.grind_check.setChecked(True)
            monitor = (123, 1)
            session = (*monitor, window._unattended_revision)
            freshness = window._character_freshness = Mock(sample=(1, 2, 3))
            freshness.hold_reason.return_value = None
            navigator = window._map_navigator = Mock()
            navigator.movement.holding_forward = False
            emit('UNIT_SPELLCAST_SENT', 'player', '', 'Nova-3', 865)
            emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Nova-3', 865)
            image, frame, sample, _ = read()
            self.assertIsNotNone(sample)
            capture = SimpleNamespace(image=image)
            self.assertIsNone(window._hold_character_frame(monitor, capture, frame, 2000))
            window._combat_dispatch = (session, 122, 1, 1900)
            crowd = replace(frame, values=dict(frame.values, enemies_8yd=2))
            self.assertIsNone(window._hold_character_frame(monitor, capture, crowd, 2000))
            navigator.movement.pulse.assert_not_called()
            self.assertIn('已后退', window._hold_character_frame(monitor, capture, frame, 2000))
            navigator.movement.pulse.assert_called_once_with(123, ord('S'), 280, sample.keys)
            self.assertIsNone(window._hold_character_frame(monitor, capture, frame, 2100))
            self.assertFalse(window._stop_before_action(frame.values))
            self.g.distance = 6.2
            image, frame, _, _ = read()
            self.assertIn('已后退', window._hold_character_frame(monitor, SimpleNamespace(image=image), frame, 2300))
            image, frame, _, _ = read()
            self.assertIsNone(window._hold_character_frame(monitor, SimpleNamespace(image=image), frame, 2600))
            self.assertEqual(navigator.movement.pulse.call_count, 2)
            freshness.sample = (1, 2, 4)
            self.assertTrue(window._stop_before_action(frame.values))

        test_dev_tray.TrayTests.run_window(self, False, exercise)

        def log(kind, source='fixture-player', target='fixture-target'):
            self.g.fixtureLogKind, self.g.fixtureLogSpell = kind, 865
            self.g.fixtureLogSource, self.g.fixtureLogTarget = source, target
            emit('COMBAT_LOG_EVENT_UNFILTERED')

        self.g.rootSource = None
        emit('UNIT_SPELLCAST_SENT', 'player', '', 'Nova-4', 865)
        log('SPELL_AURA_APPLIED', source='another-player')
        log('SPELL_AURA_APPLIED', target='another-target')
        emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Nova-4', 865)
        self.assertEqual(read()[2:], (None, ('未找到冰霜新星光环',)))
        log('SPELL_AURA_APPLIED')
        _, _, sample, blockers = read(1.25)
        self.assertEqual(blockers, ())
        self.assertTrue(sample.event_only)
        movement = Mock()
        spacing = NovaSpacing(movement)
        self.assertTrue(spacing.observe((123, 1), 4, sample))
        self.assertFalse(spacing.observe((123, 1), 4, replace(sample, sequence=sample.sequence + 1, distance=8)))
        movement.pulse.assert_called_once_with(123, ord('S'), 280, sample.keys)
        self.g.distance = None
        self.assertEqual(read()[2:], (None, ('目标世界坐标不可读',)))
        self.g.distance = 5
        log('SPELL_AURA_BROKEN')
        self.assertEqual(read()[2:], (None, ('未找到冰霜新星光环',)))

        emit('UNIT_SPELLCAST_SENT', 'player', '', 'Nova-5', 865)
        log('SPELL_AURA_APPLIED')
        self.assertIsNone(read()[2])
        emit('UNIT_SPELLCAST_SUCCEEDED', 'player', 'Nova-5', 865)
        self.g.now += 1
        self.assertEqual(read()[2:], (None, ('未找到冰霜新星光环',)))

    def test_combat_facing_turns_once_per_receipt_with_bounded_probes(self):
        from wowbuddy.engine.character_state import CombatFacingSample
        from wowbuddy.automation.navigation import CombatFacing

        movement = Mock()
        controller = CombatFacing(movement)
        session = 123, 1
        keys = ord('W'), ord('A'), ord('D')
        sample = CombatFacingSample(0, keys, 1.0, 1.5)
        movement.pulse.return_value = False
        self.assertFalse(controller.observe(session, sample, 1))
        movement.pulse.return_value = True
        self.assertTrue(controller.observe(session, sample, 1))
        movement.pulse.assert_called_with(123, keys[1], 159, keys)
        self.assertFalse(controller.observe(session, sample, 1))
        unknown = CombatFacingSample(0, keys)
        for sequence in range(2, 9):
            self.assertTrue(controller.observe(session, unknown, sequence))
            movement.pulse.assert_called_with(123, keys[2], 280, keys)
        self.assertFalse(controller.observe(session, unknown, 9))
        self.assertTrue(controller.observe(session, replace(unknown, revision=1), 10))


    def test_target_rejection_uses_current_checked_reads_at_multiple_scales(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixtureTargetPlayer=true
            function UnitExists() return true end
            function UnitCanAttack(_,unit) return unit=='target' end
            function UnitIsPlayer(unit) return unit=='player' or (unit=='target' and fixtureTargetPlayer) end
            function UnitPlayerControlled(unit) return UnitIsPlayer(unit) end
            function UnitIsTapDenied() return nil end
        ''')
        for scale in (0.8, 1, 1.25):
            with self.subTest(scale=scale):
                image = self.game_image(scale)
                frame, _ = self.pipeline.decode(image)
                self.assertTrue(frame.ok)
                frame = replace(frame, values=dict(frame.values, target_valid='ON'))
                self.assertIn('玩家控制', decode_target_rejection(image, frame))
                self.assertIn('玩家控制', frame.values['target_rejection'])
                pixels = [list(row) for row in image.rows]
                for y in range(round(372 * scale), round(376 * scale)):
                    for x in range(round(4 * scale), round(8 * scale)):
                        pixels[y][x] ^= 1
                self.assertIsNone(decode_target_rejection(RGBImage(pixels), frame))
        self.g.fixtureTargetPlayer = False
        image = self.game_image()
        frame, _ = self.pipeline.decode(image)
        self.assertIsNone(decode_target_rejection(image, replace(frame, values=dict(frame.values, target_valid='ON'))))

    def test_mob_policy_rejects_foreign_taps_and_aoe_then_loots_only_the_same_corpse(self):
        from wowbuddy.core.candidates import Candidate
        from wowbuddy.engine.character_state import decode_mob_state
        from wowbuddy.automation.corpse_loot import CorpseLoot

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixtureTap=false;fixtureHasLoot=true;fixtureCanLoot=true;fixtureLootDistance=20
            fixtureTargetGuid='Creature-test'
            function UnitExists(unit) return unit=='player' or unit=='target' end
            function UnitIsTapDenied(unit) return fixtureTap end
            function UnitAffectingCombat(unit) return unit=='player' and combat or unit=='target' and fixtureTargetCombat end
            function UnitThreatSituation(unit, target) return fixtureThreat end
            function UnitPosition(unit) return unit=='player' and 0 or fixtureLootDistance,0,0,1 end
            function UnitGUID(unit) return unit=='player' and 'Player-test' or fixtureTargetGuid end
            function CanLootUnit(guid)
                assert(guid==fixtureTargetGuid)
                if not fixtureLootUnknown then return fixtureHasLoot,fixtureCanLoot end
            end
            function GetCVarBool(key) assert(key=='autoLootDefault');return true end
            function GetPlayerFacing() return 0 end
            function C_Map.GetMapWorldSize() return 1000,800 end
            local bindings={INTERACTTARGET='F11',MOVEFORWARD='W',TURNLEFT='A',TURNRIGHT='D'}
            function GetBindingKey(action) return bindings[action] end
            function GetBindingAction(key)
                for action,bound in pairs(bindings) do if key==bound then return action end end
                return ''
            end
        ''')

        def sample(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            mob = decode_mob_state(image, frame)
            self.assertIsNotNone(mob)
            return frame, mob

        with (patch.object(self.pipeline.recovery, 'evaluate', return_value=(True, None)),
              patch.object(self.pipeline.engine, 'generate', return_value=(
                  Candidate(action='spell_1449', tag='输出'), Candidate(action='spell_122', tag='控制'),
                  Candidate(action='spell_116', tag='输出')))):
            frame, initial = sample(.8)
            self.assertEqual(initial.state, 1)
            self.assertEqual(frame.values['target_valid'], 'ON')
            self.assertEqual(frame.target_revision, initial.revision)
            decision = self.pipeline.generate(self.pipeline.prepare_frame(frame))
            self.assertEqual([item.action for item in decision.candidates], ['spell_116'])
            self.g.fixtureTargetGuid = 'Creature-next'
            self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
            frame, switched = sample()
            self.assertEqual((frame.values['target_valid'], switched.state), ('ON', 1))
            self.assertEqual(frame.target_revision, (initial.revision + 1) % 65521)
            self.g.fixtureTargetCombat = True
            frame, mob = sample(1.25)
            self.assertEqual(mob.state, 2)
            self.assertIsNone(frame.target_revision)
            self.assertTrue(self.pipeline.generate(self.pipeline.prepare_frame(frame)).target_rejection)
            self.g.fixtureThreat, self.g.combat = 0, True
            frame, initial = sample()
            self.assertEqual(initial.state, 1)
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            nav = decode_navigation_state(image, frame, for_target=True)
            self.assertEqual((nav.target_revision, nav.retarget_key), (initial.revision, 0))
            self.g.fixtureTap = True
            frame, mob = sample()
            self.assertEqual(mob.state, 2)
            self.assertIn('其他玩家', frame.values['target_rejection'])
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            self.assertIsNone(decode_navigation_state(image, frame, for_target=True).target_revision)

        loot, send, log, approach = CorpseLoot(), Mock(return_value=True), Mock(), Mock()
        def observe(mob, now, *, safe_to_loot=True):
            return loot.observe('session', mob, now, send, log, approach=approach, safe_to_loot=safe_to_loot)

        observe(initial, 0)
        self.g.targetAlive, self.g.combat = False, False
        _, foreign = sample()
        self.assertEqual(foreign.state, 0)
        self.assertIsNone(observe(foreign, 250))
        self.g.fixtureTap = False
        self.g.fixtureCanLoot = False
        _, denied = sample()
        self.assertEqual((denied.state, denied.key, denied.bearing), (0, '', None))
        self.assertIsNone(observe(denied, 500))
        send.assert_not_called()
        self.g.fixtureCanLoot = True
        self.g.combat = True
        _, threatened = sample()
        self.assertEqual((threatened.state, threatened.key, threatened.bearing), (3, '', None))
        self.assertIsNone(observe(threatened, 600, safe_to_loot=False))
        approach.assert_not_called()
        self.g.combat = False
        _, distant = sample()
        self.assertEqual((distant.state, distant.key, distant.bearing.distance), (3, '', 20))
        observe(distant, 750)
        observe(distant, 800)
        self.assertEqual([call.args for call in approach.call_args_list], [(distant.bearing,), (distant.bearing,)])
        for distance in (3, .5, 0):
            with self.subTest(distance=distance):
                self.g.fixtureLootDistance = distance
                _, nearby = sample()
                self.assertEqual((nearby.state, nearby.key, nearby.bearing), (3, 'F11', None))
        observe(nearby, 1000)
        observe(nearby, 2100)
        send.assert_called_once_with('F11')
        self.g.EmitFixtureEvent('LOOT_OPENED')
        self.assertIn('窗口已打开', observe(sample()[1], 2200))
        self.g.EmitFixtureEvent('LOOT_CLOSED')
        self.g.fixtureLootUnknown = True
        _, unknown = sample()
        self.assertEqual((unknown.state, unknown.key, unknown.bearing), (5, '', None))
        self.assertIn('等待确认', observe(unknown, 2250))
        self.assertFalse(loot.finished)
        self.g.fixtureLootUnknown = False
        self.g.fixtureHasLoot = False
        self.assertIn('拾取结束', observe(sample()[1], 2300))
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.fixtureHasLoot = True
        self.assertIsNone(observe(sample()[1], 2400))
        send.assert_called_once_with('F11')

    def test_recent_kill_reselects_only_the_same_corpse_after_the_game_clears_target(self):
        from wowbuddy.engine.character_state import decode_mob_state
        from wowbuddy.automation.corpse_loot import CorpseLoot

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixtureTarget=true; fixtureGUID='Creature-killed'; fixtureLoot=true; fixtureNativeReselect=true
            function UnitExists(unit) return unit=='player' or (unit=='target' and fixtureTarget) end
            function UnitAffectingCombat(unit) return unit=='player' and combat end
            function UnitGUID(unit)
                if unit=='softinteract' then return fixtureSoftGUID end
                return unit=='target' and fixtureTarget and fixtureGUID or nil
            end
            local oldDead=UnitIsDeadOrGhost
            function UnitIsDeadOrGhost(unit)
                if unit=='softinteract' then return fixtureSoftDead end
                return oldDead(unit)
            end
            function UnitName(unit) return unit=='target' and fixtureLootName or nil end
            function UnitPosition(unit) return unit=='player' and 0 or 3,0,0,1 end
            local originalSpeed=GetUnitSpeed
            function GetUnitSpeed(unit)
                if fixtureLootMoving then return 7 end
                return originalSpeed(unit)
            end
            function CanLootUnit() return fixtureLoot,not fixtureLootDenied end
            function GetCVarBool(key) return key=='autoLootDefault' end
            function GetBindingKey(action)
                if action=='TARGETLASTTARGET' and fixtureNativeReselect then return 'F10' end
                if action=='INTERACTTARGET' then return 'F7' end
            end
            function GetBindingAction(key, includeOverride)
                if key=='F10' and fixtureNativeReselect then return 'TARGETLASTTARGET' end
                if key=='F7' then return 'INTERACTTARGET' end
                for i=1,fixtureBusyUntil or 0 do
                    if key==WowBuddyDev.AUTO_TARGET_KEYS[i] then return 'EXISTING_BINDING' end
                end
                if includeOverride then
                    for _, frame in ipairs(frames) do
                        local binding = frame.bindings and frame.bindings[key]
                        if binding then return 'CLICK '..binding.button..':'..binding.mouse end
                    end
                end
                return ''
            end
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_mob_state(image, frame)

        loot, send, log = CorpseLoot(), Mock(return_value=True), Mock()

        def observe(mob, now, safe_to_loot=True):
            return loot.observe('session', mob, now, send, log, approach=Mock(), safe_to_loot=safe_to_loot)

        self.g.combat, self.g.targetAlive = True, True
        living = sample()
        self.assertEqual(living.state, 1)
        observe(living, 0, safe_to_loot=False)
        self.g.fixtureTarget = False
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.assertEqual(sample().state, 0)
        self.g.combat = False
        awaiting = sample()
        self.assertEqual((awaiting.state, awaiting.key, awaiting.loot_id), (7, '', 0))
        self.assertIn('击杀回执', observe(awaiting, 500))
        send.assert_not_called()
        self.g.combat = True
        self.g.EmitFixtureEvent('CHAT_MSG_COMBAT_XP_GAIN', 'fixture message')
        self.assertEqual(sample().state, 0)
        self.g.combat = False
        self.g.fixtureLootMoving = True
        waiting_for_stop = sample()
        self.assertEqual((waiting_for_stop.state, waiting_for_stop.key), (7, ''))
        send.assert_not_called()
        self.g.fixtureLootMoving = False
        self.g.fixtureNativeReselect, self.g.fixtureBusyUntil = False, 81
        self.g.WowBuddyDev.ApplyDiscardTargetBinding()
        self.assertEqual((sample().state, send.call_count), (7, 0))
        self.g.fixtureNativeReselect, self.g.fixtureBusyUntil = True, 0
        request = sample()
        self.assertEqual((request.state, request.key, request.revision), (6, 'F10', living.revision + 2))
        self.assertIn('重新选中', observe(request, 750))
        observe(sample(), 1000)
        send.assert_called_once_with('F10')

        retry, retry_send = CorpseLoot(), Mock(return_value=True)

        def observe_retry(mob, now):
            return retry.observe('session', mob, now, retry_send, Mock(),
                                 approach=Mock(), safe_to_loot=True)

        observe_retry(request, 750)
        observe_retry(request, 1400)
        retry_send.assert_called_once_with('F10')
        observe_retry(sample(), 1450)
        self.assertEqual([call.args for call in retry_send.call_args_list], [('F10',), ('F10',)])
        observe_retry(sample(), 2050)
        self.assertIsNone(observe_retry(sample(), 2250))
        self.assertEqual(retry_send.call_count, 2)

        self.g.fixtureTarget, self.g.targetAlive = True, False
        self.g.fixtureGUID = 'Creature-other'
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        wrong_corpse = sample()
        self.assertFalse(wrong_corpse.reacquired)
        self.assertFalse(self.g.WowBuddyDev.HasInterruptedLootTarget())
        wrong_loot, wrong_send = CorpseLoot(), Mock(return_value=True)
        wrong_loot.observe('session', request, 750, wrong_send, log,
                           approach=Mock(), safe_to_loot=True)
        self.assertIsNone(wrong_loot.observe('session', wrong_corpse, 1250, wrong_send, log,
                                             approach=Mock(), safe_to_loot=True))
        wrong_send.assert_called_once_with('F10')
        self.g.fixtureGUID = 'Creature-killed'
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        corpse = sample()
        self.assertEqual((corpse.state, corpse.key, corpse.reacquired), (3, 'F7', True))
        self.assertTrue(self.g.WowBuddyDev.HasInterruptedLootTarget())
        unrelated = CorpseLoot()
        self.assertIsNone(unrelated.observe('session', replace(corpse, reacquired=False), 1250, send, log,
                                            approach=Mock(), safe_to_loot=True))
        self.assertIn('拾取状态', observe(corpse, 1250))
        self.assertEqual([call.args for call in send.call_args_list], [('F10',), ('F7',)])
        self.g.EmitFixtureEvent('LOOT_OPENED')
        self.g.EmitFixtureEvent('LOOT_CLOSED')
        self.g.fixtureLoot = False
        self.assertIn('拾取结束', observe(sample(), 1500))

        self.g.combat, self.g.targetAlive = True, True
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.assertEqual(sample().state, 1)
        self.g.fixtureGUID = 'Creature-intervening'
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.fixtureTarget, self.g.combat = False, False
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.EmitFixtureEvent('CHAT_MSG_COMBAT_XP_GAIN', 'fixture message')
        blocked = sample()
        self.assertEqual((blocked.state, blocked.key, blocked.loot_block), (0, '', 1))

        self.g.fixtureTarget, self.g.targetAlive, self.g.combat = True, True, True
        self.g.fixtureGUID, self.g.fixtureLoot = 'Creature-soft-kill', True
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.assertEqual(sample().state, 1)
        self.g.fixtureTarget, self.g.combat = False, False
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.EmitFixtureEvent('CHAT_MSG_COMBAT_XP_GAIN', 'fixture message')
        self.g.fixtureSoftGUID, self.g.fixtureSoftDead = 'Creature-other', True
        self.assertEqual(sample().state, 6)
        self.g.fixtureSoftGUID = 'Creature-soft-kill'
        self.g.fixtureSoftDead = False
        self.assertEqual(sample().state, 6)
        self.g.fixtureSoftDead = True
        self.g.fixtureLootDenied = True
        self.assertEqual(sample().state, 6)
        self.g.fixtureLootDenied = False
        direct = sample()
        self.assertEqual((direct.state, direct.key, direct.soft_corpse), (3, 'F7', True))
        self.assertGreater(direct.loot_id, 0)
        soft_loot, soft_send = CorpseLoot(), Mock(return_value=True)
        soft_loot.observe('session', direct, 250, soft_send, log, approach=Mock(), safe_to_loot=True)
        soft_send.assert_called_once_with('F7')
        new_revision = direct.revision + 1
        soft_loot.observe('session', replace(direct, sequence=direct.sequence+1, revision=new_revision), 500,
                          soft_send, log, approach=Mock(), safe_to_loot=True)
        soft_send.assert_called_once_with('F7')
        self.g.fixtureSoftGUID = None
        self.g.EmitFixtureEvent('LOOT_OPENED')
        opened = replace(sample(), revision=new_revision)
        self.assertIn('交互结果', soft_loot.observe('session', opened, 1650, soft_send, log,
                                                  approach=Mock(), safe_to_loot=True))
        self.assertIn('交互结果', soft_loot.observe('session', opened, 8500, soft_send, log,
                                                  approach=Mock(), safe_to_loot=True))
        self.g.EmitFixtureEvent('LOOT_CLOSED')
        closed = replace(sample(), revision=new_revision+1)
        self.assertEqual(closed.loot_id, direct.loot_id)
        self.assertIn('拾取结束', soft_loot.observe('session', closed, 8850, soft_send, log,
                                                  approach=Mock(), safe_to_loot=True))
        self.assertIsNone(soft_loot.observe('session', replace(closed, revision=new_revision+2), 9100,
                                           soft_send, log, approach=Mock(), safe_to_loot=True))
        soft_send.assert_called_once_with('F7')

        stalled_loot, stalled_send = CorpseLoot(), Mock(return_value=True)
        stalled_loot.observe('session', direct, 0, stalled_send, log, approach=Mock(), safe_to_loot=True)
        self.assertIn('交互结果', stalled_loot.observe('session', opened, 4000, stalled_send, log,
                                                     approach=Mock(), safe_to_loot=True))
        self.assertIsNone(stalled_loot.observe('session', opened, 11200, stalled_send, log,
                                              approach=Mock(), safe_to_loot=True))
        stalled_send.assert_called_once_with('F7')

        retry_loot, retry_direct = CorpseLoot(), Mock(return_value=True)

        def observe_direct(mob, now):
            return retry_loot.observe('session', mob, now, retry_direct, log,
                                      approach=Mock(), safe_to_loot=True)

        observe_direct(direct, 0)
        observe_direct(direct, 1000)
        retry_direct.assert_called_once_with('F7')
        changed = replace(direct, sequence=direct.sequence+1, loot_generation=direct.loot_generation+1)
        observe_direct(changed, 1200)
        retry_direct.assert_called_once_with('F7')
        observe_direct(replace(direct, sequence=direct.sequence+2), 1400)
        observe_direct(replace(direct, sequence=direct.sequence+3), 2500)
        self.assertIsNone(observe_direct(replace(direct, sequence=direct.sequence+4), 3300))
        self.assertEqual([call.args for call in retry_direct.call_args_list], [('F7',), ('F7',)])

        self.g.fixtureNativeReselect = False
        for busy, expected in ((10, '-'), (27, 'CTRL-F6')):
            with self.subTest(free_key=expected):
                self.g.fixtureBusyUntil = busy
                self.g.WowBuddyDev.ApplyDiscardTargetBinding()
                button = self.g.WowBuddyDev.GetSecureButton('restore_loot_target')
                base_macro = [
                    '/stopmacro [combat][channeling][exists]',
                    '/targetlasttarget',
                    '/cleartarget [exists,nodead]',
                    '/targetlastenemy [noexists]',
                    '/cleartarget [exists,nodead]',
                ]
                self.assertEqual(button.GetAttribute(button, 'macrotext').splitlines(), base_macro)
                self.assertEqual(list(button.bindings), [expected])
                self.g.fixtureLootName = '月夜雄虎' if busy == 10 else '月夜雄虎\n/target player'
                self.g.fixtureTarget, self.g.combat = True, True
                self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
                self.assertEqual(sample().state, 1)
                self.g.fixtureTarget, self.g.combat = False, False
                self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
                self.g.EmitFixtureEvent('CHAT_MSG_COMBAT_XP_GAIN', 'fixture message')
                request = sample()
                self.assertEqual((request.state, request.key), (6, expected))
                if busy == 10:
                    base_macro.insert(3, '/targetexact [noexists] 月夜雄虎')
                self.assertEqual(button.GetAttribute(button, 'macrotext').splitlines(), base_macro)
                self.g.ClearOverrideBindings(button)

    def test_trivial_npcs_are_rejected_unless_they_are_fighting_and_targeting_us(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            function UnitExists() return true end
            function UnitCanAttack(_,unit) return unit=='target' end
            function UnitIsPlayer(unit) return unit=='player' end
            function UnitPlayerControlled() return fixtureControlled end
            function UnitIsTrivial(unit) assert(unit=='target');return fixtureTrivial end
            function UnitAffectingCombat(unit)
                if unit=='target' then return fixtureTargetFighting end
                if unit=='player' then return combat end
            end
            function UnitIsUnit(a,b) return a=='targettarget' and b==fixtureAttackedUnit end
            function UnitThreatSituation() return 1 end
        ''')

        def rejection():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            frame = replace(frame, values=dict(frame.values, target_valid='ON'))
            return decode_target_rejection(image, frame)

        low = '当前怪物等级过低'
        for level, combat, trivial, controlled, fighting, attacked, expected in (
            (59, False, True, False, False, None, low),
            (60, False, True, False, False, None, low),
            (17, True, True, False, False, None, low),
            (17, True, True, False, True, 'party1', low),
            (17, True, True, False, True, 'player', None),
            (17, True, True, False, True, 'pet', None),
            (17, True, True, False, False, 'player', low),
            (17, False, False, False, False, None, None),
            (17, False, None, False, False, None, None),
            (17, False, True, None, False, None, None),
        ):
            with self.subTest(level=level, combat=combat, trivial=trivial, fighting=fighting, attacked=attacked):
                self.g.fixtureLevel, self.g.combat = level, combat
                self.g.fixtureTrivial, self.g.fixtureControlled = trivial, controlled
                self.g.fixtureTargetFighting, self.g.fixtureAttackedUnit = fighting, attacked
                self.assertEqual(rejection(), expected)

        self.g.fixtureControlled = False
        self.lua.execute("function UnitIsTrivial() error('unavailable') end")
        self.assertIsNone(rejection())

    def test_unattended_target_selection_ignores_legacy_four_level_rejection(self):
        self.pipeline.unattended_grinding = True
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            function UnitExists() return true end
            function UnitCanAttack(_,unit) return unit=='target' end
            function UnitIsPlayer(unit) return unit=='player' end
            function UnitPlayerControlled(unit) return unit=='player' end
            function UnitLevel(unit) return unit=='target' and fixtureTargetLevel or 22 end
            function UnitIsTrivial() return fixtureTrivial end
        ''')
        for level, trivial, expected in ((18, False, None), (20, False, None), (22, False, None),
                                         (13, True, '当前怪物等级过低')):
            with self.subTest(level=level, trivial=trivial):
                self.g.fixtureTargetLevel, self.g.fixtureTrivial = level, trivial
                frame, _ = self.pipeline.decode(self.game_image())
                self.assertTrue(frame.ok)
                self.assertEqual(frame.values.get('target_valid'), 'ON')
                self.assertEqual(frame.values.get('target_rejection'), expected)

    def test_elite_rejection_uses_only_confirmed_hostile_creature_classifications(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            function UnitExists() return true end
            function UnitCanAttack(_,unit) return unit=='target' end
            function UnitIsPlayer(unit) return unit=='player' end
            function UnitPlayerControlled() return false end
            function UnitClassification(unit) assert(unit=='target');return fixtureClassification end
        ''')

        def rejection():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            frame = replace(frame, values=dict(frame.values, target_valid='ON'))
            return decode_target_rejection(image, frame)

        elite_reason = '当前目标是精英怪或世界首领'
        for classification, expected in (('elite', elite_reason), ('rareelite', elite_reason),
                                          ('worldboss', elite_reason), ('rare', None),
                                          ('normal', None), (None, None)):
            with self.subTest(classification=classification):
                self.g.fixtureClassification = classification
                self.assertEqual(rejection(), expected)

        self.g.fixtureClassification = 'elite'
        self.g.combat = True
        self.assertIsNone(rejection())
        self.g.combat = False
        self.g.fixtureLevel = 60
        self.assertIsNone(rejection())
        self.g.fixtureLevel = 17
        self.lua.execute("function UnitClassification() error('unavailable') end")
        self.assertIsNone(rejection())

    def test_toc_state_survives_rescaling_and_unavailable_map_position(self):
        for scale in (0.8, 1, 1.25):
            with self.subTest(scale=scale):
                image = self.game_image(scale)
                frame, _ = self.pipeline.decode(image)
                self.assertTrue(frame.ok, frame.status)
                state = decode_character_state(image, frame)
                self.assertEqual((state.life, state.map_id, state.zone, state.x, state.y),
                                 ('alive', 52, '西部荒野', 32.12, 36.15))
        self.g.fixtureLife = 'ghost'
        self.lua.execute("function C_Map.GetPlayerMapPosition() error('unavailable') end")
        image = self.game_image()
        frame, _ = self.pipeline.decode(image)
        state = decode_character_state(image, frame)
        self.assertEqual((state.life, state.x, state.y), ('ghost', None, None))
        pixels = [list(row) for row in image.rows]
        pixels[10][6] ^= 1
        self.assertIsNone(decode_character_state(RGBImage(pixels), frame))

    def test_cli_selects_route_from_rendered_game_state_without_manual_inputs(self):
        def lookup(*args, **kwargs):
            return find_leveling_point(*args, **kwargs, fetch=lambda _: GUIDE)

        capture = Mock()
        capture.capture.return_value = SimpleNamespace(image=self.game_image())
        window = SimpleNamespace(executable='Wow.exe', hwnd=123)
        assistant = SimpleNamespace(executable='wow战斗助手.exe', hwnd=125)
        with TemporaryDirectory() as directory, \
                patch('wowbuddy.win32.capture.make_win32_capture', return_value=capture), \
                patch('wowbuddy.win32.game_windows.CtypesWindowBackend'), \
                patch('wowbuddy.win32.game_windows.enumerate_windows', return_value=SimpleNamespace(windows=[assistant, window])), \
                patch('wowbuddy.automation.leveling_route.find_leveling_point', side_effect=lookup) as find, \
                patch.object(run_dev, 'launch') as launch:
            args = ['app', '--leveling-next', '--data-dir', directory]
            self.assertEqual(run_dev.main(args), 0)
            find.assert_called_once_with('alliance', 17, '西部荒野', completed_point='')
            launch.assert_not_called()
            report = json.loads((Path(directory)/'leveling-next.json').read_text('utf8'))
            self.assertEqual((report['point']['name'], report['cross_zone']), ('奥伯丁', True))
            self.assertEqual((report['character']['map_id'], report['character']['x']), (52, 32.12))
            self.assertEqual(capture.capture.call_count, 2)
            capture.dxgi.backend.close.assert_called_once()

    def test_cli_writes_error_without_network_when_windows_are_ambiguous(self):
        window = SimpleNamespace(executable='Wow.exe', hwnd=123)
        with TemporaryDirectory() as directory, \
                patch('wowbuddy.win32.game_windows.CtypesWindowBackend'), \
                patch('wowbuddy.win32.game_windows.enumerate_windows', return_value=SimpleNamespace(windows=[window, window])), \
                patch('wowbuddy.automation.leveling_route.find_leveling_point') as find:
            self.assertEqual(run_dev.main(['app', '--leveling-next', '--data-dir', directory]), 1)
            report = json.loads((Path(directory)/'leveling-next.json').read_text('utf8'))
            self.assertFalse(report['ok'])
            self.assertIn('一个游戏窗口', report['error'])
            find.assert_not_called()

    def test_death_and_ghost_dialogs_drive_two_clicks_and_wait_for_game_ack(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            popupType='DEATH';fixtureHovered=false;fixtureEnabled=true
            local button={IsVisible=function() return true end,IsEnabled=function() return fixtureEnabled end,
                GetCenter=function() return 50,37.5 end,GetEffectiveScale=function() return 1 end}
            local buttonChild={GetParent=function() return button end}
            function StaticPopup_FindVisible(which)
                if popupType==which then
                    return {which=which,IsVisible=function() return true end,
                            GetButton1=function() return button end}
                end
            end
            function GetMouseFoci() return fixtureHovered and {buttonChild} or {} end
            function CannotBeResurrected() return nil end
            C_DeathInfo={GetCorpseMapPosition=function(id)
                assert(id==52)
                return {GetXY=function() return 0.3476,0.365 end}
            end}
        ''')
        mouse = Mock()
        revival = AutomaticRevival(mouse)
        rect = Rect(20, 30, 1020, 830)

        def observe(now_ms):
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            state = decode_death_state(image, frame)
            self.assertIsNotNone(state)
            return state, revival.observe('session', 123, state, rect, now_ms)

        self.g.fixtureLife = 'dead'
        self.g.typing = True
        state, message = observe(0)
        self.assertIsNone(state.button)
        self.assertEqual(state.popup, 'input_blocked')
        self.assertIn('允许输入', message)
        mouse.move.assert_not_called()
        self.g.typing = False
        dead, _ = observe(250)
        self.assertEqual((dead.life, dead.button, dead.corpse), ('dead', (5000, 6250), (52, 34.76, 36.5)))
        self.assertEqual(dead.popup, 'ready')
        self.assertFalse(dead.corpse_estimated)
        mouse.move.assert_called_once_with(123, (520, 530))
        mouse.click.assert_not_called()
        revival.observe('session', 123, replace(dead, hovered=True), rect, 260)
        mouse.click.assert_not_called()
        self.g.fixtureHovered = True
        self.assertIn('释放灵魂', observe(500)[1])
        mouse.click.assert_called_once_with(123, (520, 530))
        self.g.fixtureLife = 'ghost'
        self.lua.execute('function C_Map.GetBestMapForUnit() return 53 end')
        ghost, message = observe(750)
        self.assertIn('进入灵魂状态', message)
        self.assertEqual((ghost.button, ghost.corpse), (None, (52, 34.76, 36.5)))
        self.g.popupType = 'RECOVER_CORPSE'
        self.g.fixtureEnabled = False
        state, message = observe(1000)
        self.assertIsNone(state.button)
        self.assertEqual(state.popup, 'disabled')
        self.assertIn('倒计时', message)
        self.g.fixtureEnabled = True
        observe(1250)
        self.assertEqual(mouse.click.call_count, 1)
        self.assertIn('尸体复活', observe(1500)[1])
        self.assertEqual(mouse.click.call_count, 2)
        self.g.fixtureLife = 'alive'
        self.assertIn('确认角色复活', observe(1750)[1])

    def test_ghost_start_resolves_an_overlapping_cross_zone_corpse_position(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixtureLife='ghost'; ghostMap=1411; corpseZone=1413; preciseCorpse=false; continentReads=0
            local maps={
              [1411]={mapID=1411, mapType=3, parentMapID=1414, name='杜隆塔尔'},
              [1413]={mapID=1413, mapType=3, parentMapID=1414, name='贫瘠之地'},
              [1414]={mapID=1414, mapType=2, parentMapID=947, name='卡利姆多'},
            }
            local function point(x,y) return {GetXY=function() return x,y end} end
            function C_Map.GetBestMapForUnit() return ghostMap end
            function C_Map.GetMapInfo(mapID) return maps[mapID] end
            function C_Map.GetPlayerMapPosition() return point(.3465,.4226) end
            function StaticPopup_FindVisible() return nil end
            function C_Map.GetMapInfoAtPosition(mapID,x,y)
                if mapID==1414 and x==.56390733 and y==.50896855 then return maps[corpseZone] end
            end
            C_DeathInfo={GetCorpseMapPosition=function(mapID)
                if mapID==1414 then
                    continentReads=continentReads+1
                    return point(.56390733,.50896855)
                end
                if mapID==1411 then return point(.32578412,.42413058) end
                if mapID==1413 and preciseCorpse then return point(.6225,.1923) end
            end}
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_death_state(image, frame)

        # 两张地图的绘制范围都能表示这点。区域确认后需等该区的精确坐标。
        self.assertIsNone(sample().corpse)
        self.g.preciseCorpse = True
        resolved = sample()
        self.assertEqual((resolved.life, resolved.corpse, resolved.corpse_estimated),
                         ('ghost', (1413, 62.25, 19.23), False))
        self.assertEqual(resolved.popup, 'missing')
        route = plan_walking_route(1411, resolved.corpse[0], 0, resolved.life)
        self.assertEqual([leg.destination for leg in route], [1413])
        self.g.ghostMap = 1413
        self.assertEqual(sample().corpse, resolved.corpse)
        self.assertEqual(self.g.continentReads, 2)

        self.g.fixtureLife = 'alive'
        self.assertIsNone(sample().corpse)
        self.g.fixtureLife, self.g.corpseZone = 'ghost', 1411
        self.assertEqual(sample().corpse, (1411, 32.58, 42.41))
        self.assertEqual(self.g.continentReads, 3)

        self.g.fixtureLife = 'alive'
        sample()
        self.lua.execute('C_Map.GetMapInfoAtPosition = nil')
        self.g.fixtureLife, self.g.ghostMap = 'ghost', 1411
        self.assertEqual(sample().corpse, (1411, 32.58, 42.41))
        self.assertEqual(self.g.continentReads, 3)

    def test_ghost_retains_the_observed_death_position_if_corpse_api_returns_no_position(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            function StaticPopup_FindVisible() return nil end
            C_DeathInfo={GetCorpseMapPosition=function() return nil end}
        ''')

        def sample():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            return decode_death_state(image, frame)

        self.g.fixtureLife = 'dead'
        dead = sample()
        self.assertEqual((dead.life, dead.popup, dead.corpse_estimated), ('dead', 'missing', True))
        self.assertEqual(dead.corpse, (52, 32.12, 36.15))
        self.g.fixtureLife = 'ghost'
        self.lua.execute('function C_Map.GetBestMapForUnit() return 53 end')
        ghost = sample()
        self.assertTrue(ghost.corpse_estimated)
        self.assertEqual(ghost.corpse, dead.corpse)
        self.lua.execute('function C_DeathInfo.GetCorpseMapPosition() return {GetXY=function() return 0.33,0.44 end} end')
        verified = sample()
        self.assertFalse(verified.corpse_estimated)
        self.assertEqual(verified.corpse, (52, 33, 44))
        self.g.fixtureLife = 'alive'
        self.assertIsNone(sample().corpse)

    def test_navigation_reads_effective_keys_and_hides_motion_while_recovery_popup_visible(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            fixturePopup=false; fixtureHeading=4.712; fixtureSpeed=0
            function GetPlayerFacing() return fixtureHeading end
            function GetUnitSpeed() return fixtureSpeed end
            function C_Map.GetMapWorldSize(id) assert(id==52);return 1000,800 end
            function GetBindingKey(action)
                if action=='MOVEFORWARD' then return 'W','UP' end
                if action=='TURNLEFT' then return 'A','LEFT' end
                if action=='TURNRIGHT' then return 'D','RIGHT' end
            end
            local effective={UP='MOVEFORWARD', LEFT='TURNLEFT', D='TURNRIGHT',
                             A='STRAFELEFT', W='CLICK other:LeftButton'}
            function GetBindingAction(key, checkOverride) assert(checkOverride);return effective[key] end
            function StaticPopup_FindVisible(which)
                if fixturePopup and which=='RECOVER_CORPSE' then return {} end
            end
        ''')

        def read(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            return decode_navigation_state(image, frame)

        for scale in (0.8, 1, 1.25):
            with self.subTest(scale=scale):
                nav = read(scale)
                self.assertEqual((nav.life, nav.map_id, nav.x, nav.y, nav.heading),
                                 ('alive', 52, 32.12, 36.15, 4.712))
                self.assertEqual((nav.width, nav.height, nav.keys), (1000, 800, (0x26, 0x25, ord('D'))))
                self.assertTrue(nav.continuous)
                self.assertFalse(nav.moving)
        self.g.fixtureSpeed = 7
        nav = read()
        self.assertTrue(nav.continuous and nav.moving)
        self.assertEqual(nav.idle_key_index, 0)
        self.g.fixtureSpeed = 0
        self.g.fixtureLife = 'ghost'
        self.assertEqual(read().life, 'ghost')
        image = self.game_image(4 / 3)
        frame, _ = self.pipeline.decode(image)
        frame = replace(frame, geometry=replace(frame.geometry, pitch=5.375))
        nav = decode_navigation_state(image, frame)
        self.assertEqual((nav.life, nav.x, nav.y, nav.keys), ('ghost', 32.12, 36.15, (0x26, 0x25, ord('D'))))
        self.g.fixturePopup = True
        self.assertIsNone(read())
        image = self.game_image()
        frame, _ = self.pipeline.decode(image)
        self.assertEqual(decode_navigation_state(image, frame, for_revival=True).life, 'ghost')
        self.g.fixturePopup = False
        self.g.typing = True
        self.assertIsNone(read())

    def test_game_movement_events_keep_the_combat_frame_readable_when_speed_is_secret(self):
        self.lua.execute((ROOT/'tests/addon_world_host.lua').read_text('utf8'))
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.g.combat = True
        self.lua.execute('''
            local hidden = {}
            fixtureSpeed = nil
            function GetUnitSpeed(unit)
                assert(unit == 'player')
                if fixtureSpeed == nil then return hidden end
                return fixtureSpeed
            end
            function issecretvalue(value) return value == hidden end
            function GetPlayerFacing() return 0 end
            function C_Map.GetMapWorldSize() return 1000,800 end
            local keys={MOVEFORWARD='W',TURNLEFT='A',TURNRIGHT='D'}
            function GetBindingKey(action) return keys[action] end
            function GetBindingAction(key)
                for action,binding in pairs(keys) do
                    if binding==key then return action end
                end
            end
        ''')

        def readings():
            image = self.game_image()
            frame, _ = self.pipeline.decode(image)
            self.assertTrue(frame.ok, frame.status)
            nav = decode_navigation_state(image, frame, for_target=True)
            return frame.values['player_moving'], nav.moving if nav else None

        emit = self.g.EmitFixtureEvent
        self.assertEqual(readings(), ('UNKNOWN', None))
        emit('PLAYER_STARTED_MOVING')
        self.assertEqual(readings(), ('ON', True))
        emit('PLAYER_STOPPED_MOVING')
        self.assertEqual(readings(), ('OFF', False))
        self.g.fixtureSpeed = 7
        self.assertEqual(readings(), ('ON', True))
        self.g.fixtureSpeed = None
        self.assertEqual(readings(), ('ON', True))
        emit('PLAYER_STARTED_MOVING')
        self.g.fixtureSpeed = 0
        self.assertEqual(readings(), ('OFF', False))
        self.g.fixtureSpeed = None
        self.assertEqual(readings(), ('OFF', False))
        for event in ('PLAYER_ENTERING_WORLD', 'PLAYER_DEAD', 'PLAYER_ALIVE', 'PLAYER_UNGHOST',
                      'PLAYER_CONTROL_LOST', 'PLAYER_CONTROL_GAINED'):
            emit('PLAYER_STOPPED_MOVING')
            self.assertEqual(readings(), ('OFF', False))
            emit(event)
            self.assertEqual(readings(), ('UNKNOWN', None))
        emit('PLAYER_STOPPED_MOVING')
        self.g.combat = False
        self.assertEqual(readings(), ('OFF', None))

    def test_fine_navigation_coordinates_require_a_matching_and_consistent_extension(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            function GetPlayerFacing() return 0 end
            function GetUnitSpeed() return 0 end
            function C_Map.GetPlayerMapPosition()
                return {GetXY=function() return 0.3212567,0.3615434 end}
            end
            function C_Map.GetMapWorldSize() return 10133,6756 end
            local keys={MOVEFORWARD='W',TURNLEFT='A',TURNRIGHT='D'}
            local actions={W='MOVEFORWARD',A='TURNLEFT',D='TURNRIGHT'}
            function GetBindingKey(action) return keys[action] end
            function GetBindingAction(key) return actions[key] end
        ''')

        for scale in (0.8, 1, 1.25, 4 / 3):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            if scale == 4 / 3:
                frame = replace(frame, geometry=replace(frame.geometry, pitch=5.375))
            nav = decode_navigation_state(image, frame)
            self.assertEqual((nav.x, nav.y), (32.1257, 36.1543))
            self.assertEqual(nav.position_steps, 1_000_000)
            character = decode_character_state(image, frame)
            self.assertEqual((character.x, character.y), (32.13, 36.15))

        image = self.game_image()
        frame, _ = self.pipeline.decode(image)
        fine = [image.pixel(6, 4 * index + 2) for index in range(83, 89)]
        for changed, value in ((0, 0x141414), (1, (fine[1] - 1) % 256), (2, fine[2] + 1),
                               (3, fine[3] + 200), (5, fine[5] ^ 1)):
            with self.subTest(changed=changed):
                words = fine.copy()
                words[changed] = value
                if changed != 5:
                    checksum = 0
                    for word in words[:-1]:
                        checksum = (checksum * 31 + word) % 0xFEFFFD
                    words[-1] = checksum
                pixels = [list(row) for row in image.rows]
                for index, word in enumerate(words, 83):
                    for y in range(index * 4, index * 4 + 4):
                        pixels[y][6] = word
                old = decode_navigation_state(RGBImage(pixels), frame)
                self.assertEqual((old.x, old.y, old.position_steps), (32.13, 36.15, 10_000))

    def test_auberdine_elevation_requires_current_navigation_and_world(self):
        self.g.WowBuddyDev.DB.masterSwitch = True
        self.lua.execute('''
            height=14.77; world=1; taxi=false
            function UnitPosition() return 6357,540.5,height,world end
            function UnitOnTaxi() return taxi end
            function GetPlayerFacing() return 0 end
            function GetUnitSpeed() return 0 end
            function C_Map.GetBestMapForUnit() return 1439 end
            function C_Map.GetMapInfo() return {name='黑海岸',mapType=3} end
            function C_Map.GetPlayerMapPosition()
                return {GetXY=function() return 0.3665903,0.4525954 end}
            end
            function C_Map.GetMapWorldSize() return 6550,4367 end
            local keys={MOVEFORWARD='W',TURNLEFT='A',TURNRIGHT='D'}
            local actions={W='MOVEFORWARD',A='TURNLEFT',D='TURNRIGHT'}
            function GetBindingKey(action) return keys[action] end
            function GetBindingAction(key) return actions[key] end
        ''')

        image = self.game_image()
        frame, _ = self.pipeline.decode(image)
        self.assertEqual(decode_character_state(image, frame).elevation, 14.77)
        self.assertEqual(decode_navigation_state(image, frame).elevation, 14.77)

        self.g.height = 8.75
        newer = self.game_image()
        frame, _ = self.pipeline.decode(newer)
        self.assertEqual(decode_navigation_state(newer, frame).elevation, 8.75)
        rows = [list(row) for row in newer.rows]
        for y in range(600, 624):
            rows[y][6] = image.pixel(6, y)
        stale = RGBImage(rows)
        self.assertIsNone(decode_character_state(stale, frame).elevation)
        self.assertIsNone(decode_navigation_state(stale, frame).elevation)

        self.g.world = 0
        other = self.game_image()
        frame, _ = self.pipeline.decode(other)
        self.assertIsNone(decode_character_state(other, frame).elevation)
        self.g.world, self.g.taxi = 1, True
        flying = self.game_image()
        frame, _ = self.pipeline.decode(flying)
        self.assertIsNone(decode_character_state(flying, frame).elevation)
        self.assertIsNone(decode_navigation_state(flying, frame))

    def test_discard_target_macro_uses_free_key_and_publishes_verified_stationary_binding(self):
        from wowbuddy.core.keybindings import parse_keybinding

        self.g.WowBuddyDev.DB.masterSwitch = True
        self.g.WowBuddyDev.DB.autoTarget = True
        key = self.lua.execute('''
            fixtureSpeed=0
            function GetPlayerFacing() return 0 end
            function GetUnitSpeed() return fixtureSpeed end
            function UnitPlayerControlled() return false end
            function C_Map.GetMapWorldSize() return 1000,800 end
            local keys={MOVEFORWARD='W', TURNLEFT='A', TURNRIGHT='D', TARGETNEARESTENEMY='TAB'}
            local base={W='MOVEFORWARD', A='TURNLEFT', D='TURNRIGHT', TAB='TARGETNEARESTENEMY', F7='OPENBAG'}
            function GetBindingKey(action) return keys[action] end
            function GetBindingAction(key, overrides)
                if overrides then
                    for _,frame in ipairs(frames) do
                        local binding=frame.bindings and frame.bindings[key]
                        if binding then return 'CLICK '..binding.button..':'..binding.mouse end
                    end
                end
                return base[key] or ''
            end
            assert(WowBuddyDev.SetPostKillAutoTargetEnabled(true))
            local button=assert(WowBuddyDev.GetSecureButton('discard_unreachable_target'))
            assert(button:GetAttribute('macrotext')=='/cleartarget [nocombat,nochanneling,harm,nodead]')
            local key=next(button.bindings)
            assert(key~='F7' and GetBindingAction(key,false)=='')
            return key
        ''')

        def sample(scale=1):
            image = self.game_image(scale)
            frame, _ = self.pipeline.decode(image)
            return decode_navigation_state(image, frame)

        for scale in (0.8, 1, 1.25):
            self.assertEqual(sample(scale).discard_key, parse_keybinding(key).vk)
        self.g.fixtureSpeed = 7
        self.assertEqual(sample().discard_key, 0)
        self.g.fixtureSpeed = 0
        self.lua.execute("ClearOverrideBindings(WowBuddyDev.GetSecureButton('discard_unreachable_target'))")
        nav = sample()
        self.assertEqual((nav.retarget_key, nav.discard_key), (9, 0))

    def test_revival_discards_stale_mouse_targets_after_reading_loss_and_window_move(self):
        mouse = Mock()
        mouse.click.return_value = False
        revival = AutomaticRevival(mouse)
        rect = Rect(0, 0, 800, 600)
        state = DeathState('dead', 1, (5000, 6000), False, None, 'ready')
        revival.observe('session', 123, state, rect, 0)
        revival.observe('session', 123, replace(state, sequence=2, hovered=True), rect, 250)
        revival.observe('session', 123, None, rect, 2800)
        revival.observe('session', 123, state, rect, 3000)
        self.assertEqual(mouse.move.call_count, 1)
        next_frame = replace(state, sequence=3)
        revival.observe('session', 123, next_frame, rect, 3250)
        self.assertIn('未确认鼠标命中', revival.observe('session', 123, next_frame, rect, 4500))
        self.assertIsNone(revival.observe('session', 123, next_frame, rect, 6500))
        self.assertIsNone(revival.observe('session', 123, next_frame, rect, 10000))
        self.assertEqual(mouse.move.call_count, 2)
        self.assertEqual(mouse.click.call_count, 1)
        revival.observe('session', 123, replace(state, sequence=4, button=None, popup='disabled'), rect, 10_250)
        revival.observe('session', 123, replace(state, sequence=5), rect, 10_500)
        self.assertEqual(mouse.move.call_count, 3)
        moved = Rect(10, 20, 810, 620)
        revival.observe('session', 123, replace(state, sequence=6, hovered=True), moved, 10_750)
        self.assertEqual(mouse.move.call_args.args, (123, (410, 380)))
        self.assertEqual(mouse.click.call_count, 1)
        mouse.click.return_value = True
        self.assertIn('已点击', revival.observe('session', 123, replace(state, sequence=7, hovered=True), moved, 11_000))
        mouse.click.assert_called_with(123, (410, 380))

    def test_revival_waits_for_a_fresh_frame_when_game_regains_foreground(self):
        mouse = Mock()
        foreground = Mock(return_value=False)
        revival = AutomaticRevival(mouse, in_foreground=foreground)
        rect = Rect(0, 0, 800, 600)
        dead = DeathState('dead', 1, (5000, 6000), False, None, 'ready')
        self.assertIn('游戏回到前台', revival.observe('session', 123, dead, rect, 0))
        revival.observe('session', 123, replace(dead, sequence=2), rect, 12_000)
        mouse.move.assert_not_called()
        foreground.return_value = True
        revival.observe('session', 123, replace(dead, sequence=2), rect, 12_001)
        mouse.move.assert_not_called()
        revival.observe('session', 123, replace(dead, sequence=3), rect, 12_250)
        mouse.move.assert_called_once_with(123, (400, 360))
        mouse.click.assert_not_called()
        self.assertIn('释放灵魂', revival.observe('session', 123,
            replace(dead, sequence=4, hovered=True), rect, 12_500))
        mouse.click.assert_called_once_with(123, (400, 360))

    def test_rapid_death_after_reviving_retries_at_a_different_confirmed_spot(self):
        mouse = Mock()
        revival = AutomaticRevival(mouse)
        rect = Rect(0, 0, 800, 600)
        ghost = DeathState('ghost', 1, (5000, 6000), False, (52, 36, 36), 'ready')
        position = NavigationState('ghost', 1, 52, 32.5, 36, 0, 1000, 1000, (87, 65, 68), continuous=True)

        def poll(state, now, at=position, **readings):
            return revival.observe('session', 123, state, rect, now, position=at, **readings)

        poll(ghost, 0)
        poll(replace(ghost, sequence=2, hovered=True), 250)
        mouse.click.assert_called_once()
        poll(DeathState('alive', 3, None, False, None), 750, in_combat=True)
        poll(DeathState('dead', 4, None, False, ghost.corpse), 13000)
        poll(replace(ghost, button=None, popup='missing', sequence=5), 13500)
        ready = replace(ghost, sequence=6)
        self.assertIn('上次复活后遭袭', poll(ready, 30000))
        first = revival.landing_destination
        self.assertGreater(abs(first.y - position.y), 1.8)
        poll(replace(ready, button=None, popup='missing', sequence=7), 30250,
             replace(position, x=first.x, y=first.y))
        self.assertEqual((revival.landing_destination.x, revival.landing_destination.y), (position.x, position.y))
        poll(replace(ready, sequence=8), 31000)
        second = revival.landing_destination
        self.assertNotEqual(first.y, second.y)
        at_second = replace(position, x=second.x, y=second.y)
        poll(replace(ready, sequence=9), 32000, replace(at_second, moving=True))
        mouse.click.assert_called_once()
        poll(replace(ready, sequence=10), 32250, at_second)
        poll(replace(ready, sequence=11, hovered=True), 32500, at_second)
        self.assertEqual(mouse.click.call_count, 2)


class AutomaticRevivalRetryTests(unittest.TestCase):
    def test_unattended_avoids_landing_after_delayed_combat_and_death(self):
        rect = Rect(0, 0, 800, 600)
        ghost = DeathState('ghost', 1, (5000, 6000), False, (1439, 39, 77), 'ready')
        landing = NavigationState('ghost', 1, 1439, 35.5, 77, 0, 1000, 1000, (87, 65, 68))

        for name, x, combat_delay, death_delay, avoid in (
            ('live_timing', 35.5, 14_100, 32_200, True),
            ('walked_away', 40, 14_100, 32_200, False),
            ('combat_started_later', 35.5, 21_000, 32_200, False),
            ('survived_window', 35.5, 14_100, 46_000, False),
        ):
            with self.subTest(name=name):
                mouse = Mock()
                revival = AutomaticRevival(mouse)

                def poll(state, now, position=None, **readings):
                    return revival.observe('session', 123, state, rect, now, position=position, **readings)

                poll(ghost, 0, landing)
                poll(replace(ghost, sequence=2, hovered=True), 250, landing)
                mouse.click.assert_called_once()
                revival.prefer_clearance = True
                alive = DeathState('alive', 3, None, False, None)
                poll(alive, 1000)
                living = replace(landing, life='alive', x=x)
                poll(replace(alive, sequence=4), 11_000, living, recovery_ready=True)
                poll(replace(alive, sequence=5), 1000 + combat_delay, living, in_combat=True)
                dead = DeathState('dead', 6, None, False, ghost.corpse)
                poll(dead, 1000 + death_delay)
                poll(replace(ghost, sequence=7, button=None, popup='missing'), 48_000)
                result = poll(replace(ghost, sequence=8), 50_000, landing)
                if avoid:
                    self.assertIn('上次复活后遭袭', result)
                    self.assertIsNotNone(revival.landing_destination)
                else:
                    self.assertIsNone(revival.landing_destination)
                mouse.click.assert_called_once()

    def test_edge_popup_waits_for_position_and_tries_both_sides_after_range_loss(self):
        mouse = Mock()
        revival = AutomaticRevival(mouse, prefer_clearance=True)
        rect = Rect(0, 0, 800, 600)
        ghost = DeathState('ghost', 1, (5000, 6000), False, (1439, 39.02, 77.15), 'ready')
        position = NavigationState('ghost', 1, 1439, 39.3583, 77.8038, 0.478, 6550, 4367, (87, 65, 68))
        corpse = MapDestination(*ghost.corpse, 'ghost', '尸体')
        self.assertGreater(math.hypot(*corpse.offset_from(position)), 35)

        def poll(sequence, at, *, popup='ready', hovered=False, nearby=False, now=None):
            state = replace(ghost, sequence=sequence, popup=popup,
                            button=ghost.button if popup == 'ready' else None, hovered=hovered)
            return revival.observe('session', 123, state, rect, sequence * 250 if now is None else now,
                                   position=at, nearby_hostile=nearby)

        self.assertIn('等待有效的灵魂定位', poll(1, None))
        self.assertIn('从尸体侧面复活', poll(2, position))
        first = revival.landing_destination
        self.assertFalse(first.contains(position, radius=18))
        first_position = replace(position, x=first.x, y=first.y)
        self.assertIn('超出游戏复活范围', poll(3, first_position, popup='missing'))
        self.assertIn('从尸体侧面复活', poll(4, position))
        second = revival.landing_destination
        self.assertNotEqual(first, second)
        second_position = replace(position, x=second.x, y=second.y)
        self.assertIn('附近刚出现敌人', poll(5, second_position, nearby=True))
        self.assertIn('等待有效的灵魂定位', poll(6, None))
        self.assertIn('附近刚出现敌人', poll(7, second_position))
        mouse.move.assert_not_called()
        mouse.click.assert_not_called()
        self.assertIn('已定位', poll(8, second_position, now=10_000))
        self.assertIn('已点击', poll(9, second_position, hovered=True, now=10_250))
        mouse.click.assert_called_once_with(123, (400, 360))

    def test_blocked_return_rechecks_the_popup_at_the_current_position(self):
        mouse = Mock()
        revival = AutomaticRevival(mouse, prefer_clearance=True)
        rect = Rect(0, 0, 800, 600)
        ghost = DeathState('ghost', 1, (5000, 6000), False, (52, 36, 36), 'ready')
        position = NavigationState('ghost', 1, 52, 33.2, 36, 0, 1000, 1000, (87, 65, 68))

        def poll(state, now, at=position):
            return revival.observe('session', 123, state, rect, now, position=at)

        self.assertIn('更远的复活位置', poll(ghost, 0))
        farther = revival.landing_destination
        at = replace(position, sequence=2, x=farther.x, y=farther.y)
        missing = replace(ghost, sequence=2, button=None, popup='missing')
        self.assertIn('返回上一个可用位置', poll(missing, 250, at))
        self.assertEqual(revival.landing_destination.x, position.x)
        self.assertIn('返回上一处复活位置也受阻', revival.landing_blocked())
        self.assertIsNone(revival.landing_destination)
        poll(replace(missing, sequence=3), 500, at)
        mouse.move.assert_not_called()
        mouse.click.assert_not_called()
        self.assertIn('已定位', poll(replace(ghost, sequence=4, hovered=True), 750, at))
        mouse.click.assert_not_called()
        self.assertIn('已点击', poll(replace(ghost, sequence=5, hovered=True), 1000, at))
        mouse.click.assert_called_once_with(123, (400, 360))

    def test_unattended_reconnect_probes_once_from_the_first_confirmed_popup(self):
        corpse = (1436, 52.29, 72.62)
        rect = Rect(0, 0, 800, 600)
        position = NavigationState('ghost', 1, 1436, 52.4, 74.1, 0, 3500, 2333, (87, 65, 68))
        ghost = DeathState('ghost', 1, None, False, corpse, 'missing')
        for unattended in (False, True):
            with self.subTest(unattended=unattended):
                mouse = Mock()
                revival = AutomaticRevival(mouse, prefer_clearance=unattended)

                def poll(state, now, at=position):
                    return revival.observe('session', 123, state, rect, now, position=at)

                poll(ghost, 0)
                ready = replace(ghost, sequence=2, popup='ready', button=(5000, 6000))
                status = poll(ready, 1000)
                if unattended:
                    self.assertIn('更远的复活位置', status)
                    farther = revival.landing_destination
                    self.assertGreater(farther.y, position.y)
                    mouse.move.assert_not_called()
                    lost = replace(ghost, sequence=3)
                    self.assertIn('超出游戏复活范围', poll(lost, 1250, replace(position, x=farther.x, y=farther.y)))
                    self.assertIn('已定位', poll(replace(ready, sequence=4), 1500))
                    self.assertIsNone(revival.landing_destination)
                else:
                    self.assertIn('已定位', status)
                self.assertIn('已点击', poll(replace(ready, sequence=5, hovered=True), 1750))
                mouse.click.assert_called_once_with(123, (400, 360))

    def test_first_combat_death_probes_clearance_only_while_popup_allows_it(self):
        mouse = Mock()
        revival = AutomaticRevival(mouse, prefer_clearance=True)
        rect = Rect(0, 0, 800, 600)
        ghost = DeathState('ghost', 3, (5000, 6000), False, (52, 36, 36), 'ready')
        position = NavigationState('ghost', 1, 52, 33.2, 36, 0, 1000, 1000, (87, 65, 68))

        def poll(state, now, at=position, **readings):
            return revival.observe('session', 123, state, rect, now, position=at, **readings)

        poll(DeathState('alive', 1, None, False, None), 1000, in_combat=True)
        poll(DeathState('dead', 2, None, False, ghost.corpse), 1500)
        poll(ghost, 20000)
        self.assertIn('更远的复活位置', poll(replace(ghost, sequence=4), 20250))
        farther = revival.landing_destination
        self.assertAlmostEqual(farther.x, 32.2)
        mouse.move.assert_not_called()
        self.assertIn('超出游戏复活范围', poll(replace(ghost, sequence=5, button=None, popup='missing'),
                                                20500, replace(position, x=farther.x)))
        self.assertAlmostEqual(revival.landing_destination.x, position.x)
        poll(replace(ghost, sequence=6), 21000)
        mouse.move.assert_called_once()
        poll(replace(ghost, sequence=7, hovered=True), 21250)
        mouse.click.assert_called_once()
        self.assertIsNone(revival.landing_destination)

    def test_revive_waits_for_navigation_key_release_and_fresh_hover(self):
        for life in ('dead', 'ghost'):
            with self.subTest(life=life):
                mouse = Mock()
                stop_movement = Mock(return_value=False)
                revival = AutomaticRevival(mouse, stop_movement=stop_movement)
                rect = Rect(0, 0, 800, 600)
                popup = DeathState(life, 1, (5000, 6000), False, None, 'ready')
                position = None if life == 'dead' else NavigationState(
                    'ghost', 1, 52, 36, 36, 0, 1000, 1000, (87, 65, 68), moving=True)

                def poll(sequence, now, *, hovered=False):
                    state = replace(popup, sequence=sequence, hovered=hovered)
                    return revival.observe('session', 123, state, rect, now, position=position)

                self.assertIn('正在停步', poll(1, 0))
                mouse.move.assert_not_called()
                stop_movement.return_value = True
                if position is not None:
                    poll(2, 250)
                    mouse.move.assert_not_called()
                    position = replace(position, moving=False)
                self.assertIn('已定位', poll(3, 500))
                stop_movement.return_value = False
                self.assertIn('正在停步', poll(4, 750, hovered=True))
                self.assertEqual(revival.attempts, 0)
                mouse.click.assert_not_called()
                stop_movement.return_value = True
                self.assertIn('已定位', poll(5, 3500, hovered=True))
                poll(5, 3600, hovered=True)
                mouse.click.assert_not_called()
                self.assertIn('已点击', poll(6, 3700, hovered=True))
                mouse.click.assert_called_once_with(123, (400, 360))

    def test_unconfirmed_mouse_input_can_recover_without_spending_the_click_budget(self):
        for life, no_hover in (('dead', True), ('ghost', False)):
            with self.subTest(life=life):
                mouse = Mock()
                mouse.click.return_value = False
                revival = AutomaticRevival(mouse)
                rect = Rect(0, 0, 800, 600)
                state = DeathState(life, 1, (5000, 6000), False, (52, 36, 36), 'ready')

                def poll(sequence, now, *, hovered=False):
                    return revival.observe('session', 123, replace(state, sequence=sequence, hovered=hovered), rect, now)

                poll(1, 0)
                first_failure = 1000 if no_hover else 250
                poll(2, first_failure, hovered=not no_hover)
                poll(2, first_failure + 3000)
                self.assertEqual(mouse.move.call_count, 1)
                poll(3, first_failure + 3100)
                self.assertEqual(mouse.move.call_count, 2)
                second_failure = first_failure + 3100 + first_failure
                poll(4, second_failure, hovered=not no_hover)
                poll(5, second_failure + 5999)
                poll(5, second_failure + 6000)
                self.assertEqual(mouse.move.call_count, 2)

                poll(6, second_failure + 6250)
                self.assertEqual(mouse.move.call_count, 3)
                mouse.click.return_value = True
                poll(6, second_failure + 6300, hovered=True)
                self.assertEqual(mouse.click.call_count, 0 if no_hover else 2)
                self.assertIn('已点击', poll(7, second_failure + 6400, hovered=True))
                self.assertEqual(revival.attempts, 1)

    def test_confirmed_popup_can_retry_once_after_delayed_game_acknowledgement(self):
        for life, next_life, confirmation in (('dead', 'ghost', '灵魂状态'), ('ghost', 'alive', '角色复活')):
            with self.subTest(life=life):
                mouse = Mock()
                revival = AutomaticRevival(mouse)
                rect = Rect(0, 0, 800, 600)
                state = DeathState(life, 1, (5000, 6000), False, (52, 36, 36), 'ready')

                def poll(sequence, now, *, hovered=False):
                    return revival.observe('session', 123, replace(state, sequence=sequence, hovered=hovered), rect, now)

                poll(1, 0)
                self.assertIn('已点击', poll(2, 250, hovered=True))
                poll(3, 3000)
                self.assertIn('已点击', poll(4, 3250, hovered=True))
                self.assertIn('延时确认', poll(5, 6000))
                poll(6, 15_249)
                poll(7, 15_250)
                poll(7, 16_000, hovered=True)
                self.assertEqual(mouse.move.call_count, 2)
                self.assertEqual(mouse.click.call_count, 2)
                poll(8, 16_050, hovered=True)
                poll(8, 16_100, hovered=True)
                self.assertEqual(mouse.move.call_count, 3)
                self.assertEqual(mouse.click.call_count, 2)
                self.assertIn('已点击', poll(9, 16_300, hovered=True))
                self.assertIn('三次尝试', poll(10, 20_000))
                poll(11, 40_000)
                self.assertEqual(mouse.move.call_count, 3)
                self.assertEqual(mouse.click.call_count, 3)
                next_state = DeathState(next_life, 12, None, False, None)
                self.assertIn(confirmation, revival.observe('session', 123, next_state, rect, 40_250))


class CorpseLootTimingTests(unittest.TestCase):
    def setUp(self):
        self.loot = CorpseLoot()
        self.send = Mock(return_value=True)
        self.log = Mock()
        self.approach = Mock()
        self.living = MobState(1, 12, 1, '', 7, False)
        self.distant = replace(self.living, sequence=2, state=3, bearing=TargetBearing(12, 0, 20))
        self.nearby = replace(self.distant, sequence=3, bearing=None, key='F11')
        self.observe(self.living, 0)
        self.observe(self.distant, 1000)
        self.observe(self.nearby, 11800)
        self.approach.assert_called_once_with(self.distant.bearing)
        self.send.assert_called_once_with('F11')

    def observe(self, mob, now):
        return self.loot.observe('session', mob, now, self.send, self.log, approach=self.approach, safe_to_loot=True)

    def test_waits_for_late_loot_window_after_approaching(self):
        opened = replace(self.nearby, sequence=4, loot_open=True, key='')
        self.assertIn('窗口已打开', self.observe(opened, 12300))
        self.assertIn('窗口已打开', self.observe(opened, 16500))
        unconfirmed = replace(self.nearby, sequence=5)
        self.assertIn('等待确认', self.observe(unconfirmed, 16600))
        self.send.assert_called_once_with('F11')
        closed = replace(unconfirmed, sequence=6, state=4, key='', loot_generation=8)
        self.assertIn('拾取结束', self.observe(closed, 17000))
        self.assertIsNone(self.observe(closed, 17100))

    def test_late_interaction_without_window_retries_once_then_times_out(self):
        self.assertIn('等待确认', self.observe(replace(self.nearby, sequence=4), 12700))
        self.assertIn('等待确认', self.observe(replace(self.nearby, sequence=5), 14999))
        self.assertIsNone(self.observe(replace(self.nearby, sequence=6), 15000))
        self.assertEqual([call.args for call in self.send.call_args_list], [('F11',), ('F11',)])

    def test_unclosed_window_still_has_a_deadline(self):
        opened = replace(self.nearby, sequence=4, loot_open=True, key='')
        self.assertIn('窗口已打开', self.observe(opened, 15100))
        self.assertIn('窗口已打开', self.observe(opened, 22999))
        self.assertIsNone(self.observe(opened, 23000))
        self.send.assert_called_once_with('F11')


class CorpseAccessTests(unittest.TestCase):
    def test_reached_corpse_without_popup_waits_for_fresh_reading_and_tries_bounded_probes(self):
        access = CorpseAccess()
        corpse = MapDestination(1432, 50, 50, 'ghost', '尸体')
        at_corpse = NavigationState('ghost', 1, 1432, 50, 50, 0, 1000, 800, (87, 65, 68))
        self.assertEqual(access.observe(1, at_corpse, corpse, 0), (corpse, None))
        self.assertEqual(access.observe(1, at_corpse, corpse, 1800), (corpse, None))
        access.pause()
        second = replace(at_corpse, sequence=2)
        self.assertEqual(access.observe(1, second, corpse, 2000), (corpse, None))
        self.assertEqual(access.observe(1, replace(second, sequence=3), corpse, 3499), (corpse, None))
        position = replace(second, sequence=4)
        target, status = access.observe(1, position, corpse, 3500)
        self.assertIn('尝试从附近接近', status)
        self.assertFalse(corpse.contains(replace(position, x=target.x, y=target.y)))
        tried = []
        while target is not None and len(tried) < 5:
            self.assertAlmostEqual(math.hypot(*target.offset_from(position)), 16)
            tried.append(target)
            target, status = access.observe(1, position, corpse, 3600, blocked=target)
        self.assertEqual(len(set(tried)), 4)
        self.assertIn('接入点已试完', status)
        self.assertEqual(access.observe(1, position, corpse, 7000), (None, None))
        self.assertEqual(access.observe(2, position, corpse, 7100), (corpse, None))


class AutomaticLevelingTests(unittest.TestCase):
    def setUp(self):
        self.character = CharacterState('alive', True, True, 'alliance', 16, 1436, '西部荒野', 32.12, 36.15)
        self.submit = Mock()
        self.planner = AutomaticLeveling(self.submit)

    def test_grinding_rejects_a_wrong_map_id_before_reading_guides_and_recovers(self):
        westfall = '/zh/zones/eastern-kingdoms/westfall/'
        markers = (f'<section id="route-alliance"><a class="route-coords" '
                   f'href="{westfall}?pin=46.1,38.2#map">营地</a></section>')
        fetch = Mock(side_effect=lambda url: markers if url.endswith(westfall) else GUIDE)

        def submit(fn, *args, **options):
            future = Future()
            try:
                future.set_result(fn(*args, fetch=fetch, **options))
            except ValueError as error:
                future.set_exception(error)
            return future

        planner = AutomaticLeveling(submit)
        westfall_character = replace(self.character, level=15, x=46.1, y=38.2)
        wrong_map = replace(westfall_character, map_id=1433)
        planner.observe(1, wrong_map, 0, grinding=True)
        planner.observe(1, wrong_map, 250, grinding=True)
        refused = planner.observe(1, wrong_map, 500, grinding=True)
        self.assertFalse(refused['ok'])
        self.assertIn('地图编号', refused['error'])
        fetch.assert_not_called()

        planner.observe(1, westfall_character, 750, grinding=True)
        planner.observe(1, westfall_character, 1000, grinding=True)
        result = planner.observe(1, westfall_character, 1250, grinding=True)
        self.assertTrue(result['ok'])
        self.assertFalse(result['cross_zone'])
        self.assertEqual(result['point']['name'], '摩尔森农场')
        self.assertEqual(result['character']['map_id'], 1436)

    def test_repeated_camp_death_requires_same_camp_level_session_and_time_window(self):
        camp = MapDestination(52, 32.12, 36.15, 'alive', '刷怪区')
        for session, character, destination, second_at in (
            (2, self.character, camp, 2000),
            (1, replace(self.character, level=17), camp, 2000),
            (1, self.character, replace(camp, x=35), 2000),
            (1, self.character, camp, 301_001),
        ):
            with self.subTest(session=session, character=character, destination=destination, at=second_at):
                planner = AutomaticLeveling(self.submit)
                self.assertFalse(planner.record_camp_death(1, self.character, camp, 1000))
                self.assertFalse(planner.record_camp_death(session, character, destination, second_at))
                self.assertTrue(planner.record_camp_death(session, character, destination, second_at + 1000))
                self.assertFalse(planner.record_camp_death(session, character, destination, second_at + 2000))

    def test_monitor_uses_validated_cache_after_network_loss_and_rechecks_level_and_cooldown(self):
        westfall = '/zh/zones/eastern-kingdoms/westfall/'
        markers = '<section id="route-alliance">' + ''.join(
            f'<a class="route-coords" href="{westfall}?pin={pin}#map">营地</a>'
            for pin in ('46.1,38.2', '45.4,70.2', '51.66,77.21')) + '</section>'
        clock = Mock(return_value=0)
        fetch = Mock(side_effect=lambda url: markers if url.endswith(westfall) else GUIDE)
        cache = LevelingGuideCache(clock=clock)

        def submit(fn, *args, **options):
            future = Future()
            try:
                future.set_result(fn(*args, fetch=fetch, **options))
            except (OSError, ValueError) as error:
                future.set_exception(error)
            return future

        planner = AutomaticLeveling(submit, cache=cache)
        character = replace(self.character, level=15, x=46.1, y=38.2)

        def lookup(character, start):
            planner.observe(1, character, start, grinding=True)
            planner.observe(1, character, start + 250, grinding=True)
            return planner.observe(1, character, start + 500, grinding=True)

        online = lookup(character, 1000)
        self.assertEqual(online['point']['name'], '摩尔森农场')
        self.assertNotIn('cached_sources', online)
        fetch.side_effect = OSError('offline')
        clock.return_value = 20
        upgraded = replace(character, level=16)
        planner.retire_camp(1, upgraded, MapDestination(character.map_id, 45.4, 70.2, 'alive', '月溪镇'), 2000)
        cached = lookup(upgraded, 2000)
        self.assertEqual(cached['point']['name'], '匕首岭')
        self.assertEqual(cached['cached_sources'], ['https://wowhandbook.com/zh/leveling/alliance/',
                                                    'https://wowhandbook.com' + westfall])
        with self.assertRaisesRegex(OSError, 'offline'):
            find_leveling_point('horde', 16, '贫瘠之地', fetch=fetch, cache=cache)
        clock.return_value = 901
        expired = lookup(replace(upgraded, level=17), 903_000)
        self.assertFalse(expired['ok'])
        self.assertEqual(expired['error'], 'offline')

    def test_monitor_ignores_old_level_result_and_requeries_after_level_change(self):
        old, new = Future(), Future()
        self.submit.side_effect = (old, new)
        upgraded = replace(self.character, level=17)
        self.assertIsNone(self.planner.observe(1, self.character, 0))
        self.planner.observe(1, self.character, 250)
        self.submit.assert_called_once_with(find_leveling_point, 'alliance', 16, '西部荒野')
        self.planner.observe(1, upgraded, 300)
        self.planner.observe(1, upgraded, 550)
        self.assertEqual(self.submit.call_count, 1)
        old.set_result({'point': {'name': '哨兵岭'}})
        self.assertIsNone(self.planner.observe(1, upgraded, 600))
        self.submit.assert_called_with(find_leveling_point, 'alliance', 17, '西部荒野')
        new.set_result({'point': {'name': '奥伯丁'}})
        self.assertIsNone(self.planner.observe(1, None, 650))
        self.assertIsNone(self.planner.observe(1, upgraded, 700))
        result = self.planner.observe(1, upgraded, 950)
        self.assertEqual((result['ok'], result['character']['level'], result['point']['name']),
                         (True, 17, '奥伯丁'))
        self.planner.observe(1, upgraded, 1200)
        self.assertEqual(self.submit.call_count, 2)

    def test_monitor_retries_fetch_failure_without_spamming(self):
        error = Future()
        error.set_exception(OSError('offline'))
        self.submit.side_effect = (error, Future())
        self.planner.observe(1, self.character, 0)
        self.planner.observe(1, self.character, 250)
        self.assertEqual(self.planner.observe(1, self.character, 500)['error'], 'offline')
        self.planner.observe(1, self.character, 60_499)
        self.assertEqual(self.submit.call_count, 1)
        self.planner.observe(1, self.character, 60_500)
        self.assertEqual(self.submit.call_count, 2)

    def test_replan_discards_pending_result_even_when_the_route_key_is_unchanged(self):
        obsolete, replacement = Future(), Future()
        self.submit.side_effect = (obsolete, replacement)
        self.planner.observe(1, self.character, 0)
        self.planner.observe(1, self.character, 250)
        self.planner.request_replan()
        obsolete.set_result({'point': {'name': '旧营地'}})
        self.assertIsNone(self.planner.observe(1, self.character, 500))
        self.assertEqual(self.submit.call_count, 2)
        replacement.set_result({'point': {'name': '新营地'}})
        self.assertEqual(self.planner.observe(1, self.character, 750)['point']['name'], '新营地')

    def test_grinding_requeries_when_reaching_a_different_shore(self):
        wetlands = '/zh/zones/eastern-kingdoms/wetlands/'
        sources = {
            '/zh/leveling/alliance/': stage(1, '19–25', leg('赤脊山', 'redridge-mountains', [('湖畔镇', '25.5,59.4')])),
            wetlands: f'<section id="route-alliance"><a class="route-coords" href="{wetlands}?pin=60.51,63.71#map">营地</a></section>',
        }

        def submit(fn, *args, **options):
            future = Future()
            try:
                future.set_result(fn(*args, fetch=lambda url: sources[url.removeprefix('https://wowhandbook.com')],
                                     **options))
            except ValueError as error:
                future.set_exception(error)
            return future

        self.submit.side_effect = submit
        east = replace(self.character, level=20, map_id=1432, zone='洛克莫丹', x=78, y=35)
        west = replace(east, x=37.9, y=87)
        self.assertEqual(east.route_key, west.route_key)
        self.planner.observe(1, east, 0, grinding=True)
        self.planner.observe(1, east, 250, grinding=True)
        error = self.planner.observe(1, east, 500, grinding=True)
        self.assertFalse(error['ok'])
        self.assertIn('湖岸', error['error'])
        self.planner.observe(1, west, 600, grinding=True)
        self.planner.observe(1, replace(west, x=38), 849, grinding=True)
        self.assertEqual(self.submit.call_count, 1)
        self.planner.observe(1, west, 850, grinding=True)
        result = self.planner.observe(1, west, 900, grinding=True)
        self.assertTrue(result['ok'] and result['cross_zone'])
        self.assertEqual(result['point']['zone'], '湿地')
        self.planner.observe(1, replace(west, x=39, y=85), 1200, grinding=True)
        self.assertEqual(self.submit.call_count, 2)

    def test_grinding_discards_an_inflight_lookup_from_the_other_shore(self):
        old, new = Future(), Future()
        self.submit.side_effect = (old, new)
        east = replace(self.character, map_id=1432, zone='洛克莫丹', x=65.4, y=39.6)
        west = replace(east, x=37.9, y=87)
        self.planner.observe(1, east, 0, grinding=True)
        self.planner.observe(1, east, 250, grinding=True)
        self.planner.observe(1, west, 300, grinding=True)
        old.set_result({'point': {'name': '东岸老山猪区'}})
        self.assertIsNone(self.planner.observe(1, west, 550, grinding=True))
        self.submit.assert_called_with(find_grinding_point, 'alliance', 16, '洛克莫丹', 37.9, 87,
                                       excluded=frozenset(), current_map_id=1432)
        new.set_result({'point': {'name': '碎石怪断骨者营地'}})
        self.assertEqual(self.planner.observe(1, west, 600, grinding=True)['point']['name'], '碎石怪断骨者营地')

    def test_grinding_requeries_with_exclusions_and_allows_the_camp_after_cooldown(self):
        first, retry, fresh = Future(), Future(), Future()
        self.submit.side_effect = (first, retry, fresh)
        session = (123, 456, 0)
        camp = MapDestination(52, 46.1, 38.2, 'alive', '摩尔森农场')
        self.planner.retire_camp(session, self.character, camp, 1000)
        self.planner.observe(session, self.character, 1100, grinding=True)
        self.planner.observe(session, self.character, 1350, grinding=True)
        args = (find_grinding_point, 'alliance', 16, '西部荒野', 32.12, 36.15)
        self.submit.assert_called_once_with(*args, excluded=frozenset({('西部荒野', 46.1, 38.2)}), current_map_id=1436)
        first.set_exception(ValueError('等待重试'))
        self.assertFalse(self.planner.observe(session, self.character, 1500, grinding=True)['ok'])
        self.planner.observe(session, self.character, 180_999, grinding=True)
        self.submit.assert_called_with(*args, excluded=frozenset({('西部荒野', 46.1, 38.2)}), current_map_id=1436)
        retry.set_result({'point': {'name': '另一处'}})
        self.planner.observe(session, self.character, 181_000, grinding=True)
        self.planner.observe(session, self.character, 181_250, grinding=True)
        self.submit.assert_called_with(*args, excluded=frozenset(), current_map_id=1436)

    def test_grinding_clears_old_result_when_no_positions_arrive_during_cooldown(self):
        initial, retry = Future(), Future()
        initial.set_result({'point': {'name': '摩尔森农场'}})
        self.submit.side_effect = (initial, retry)
        session = (123, 456, 0)
        self.planner.observe(session, self.character, 0, grinding=True)
        self.planner.observe(session, self.character, 250, grinding=True)
        self.assertTrue(self.planner.observe(session, self.character, 300, grinding=True)['ok'])
        camp = MapDestination(52, 46.1, 38.2, 'alive', '摩尔森农场')
        self.planner.retire_camp(session, self.character, camp, 1000)
        self.planner.observe(session, None, 2000, grinding=True)
        self.planner.observe(session, self.character, 200_000, grinding=True)
        self.planner.observe(session, self.character, 200_250, grinding=True)
        self.assertEqual(self.submit.call_count, 2)

    def test_death_cooldown_outlasts_a_shorter_route_failure(self):
        camp = MapDestination(52, 46.1, 38.2, 'alive', '摩尔森农场')
        self.planner.retire_camp(1, self.character, camp, 1000, after_deaths=True)
        self.planner.retire_camp(1, self.character, camp, 2000)
        self.assertEqual(self.planner._camp_exclusions(1, self.character, 900_999),
                         frozenset({('西部荒野', 46.1, 38.2)}))
        self.assertEqual(self.planner._camp_exclusions(1, self.character, 901_000), frozenset())

    def test_blocked_road_remains_excluded_across_zones_until_cooldown_expires(self):
        source = replace(self.character, map_id=1429, zone='艾尔文森林')
        current = replace(source, map_id=1436, zone='西部荒野')
        camp = MapDestination(1433, 11.65, 62.18, 'alive', '山丘')
        blocked = frozenset(plan_walking_route(1429, 1433, source.level, 'alive'))
        first, second = Future(), Future()
        self.submit.side_effect = (first, second)
        self.planner.retire_travel(1, source, camp, '赤脊山', blocked, 1000)
        self.planner.observe(1, current, 1100, grinding=True)
        self.planner.observe(1, current, 1350, grinding=True)
        args = (find_grinding_point, 'alliance', 16, '西部荒野', current.x, current.y)
        self.submit.assert_called_once_with(*args, blocked_legs=blocked,
                                            excluded=frozenset({('赤脊山', 11.65, 62.18)}), current_map_id=1436)
        first.set_result({'point': {'name': '另一个营地'}})
        result = self.planner.observe(1, current, 1500, grinding=True)
        self.assertEqual(result['blocked_roads'], [(1429, 1433)])
        self.assertEqual(result['blocked_connections'], [leg.blocked_key for leg in blocked])
        self.planner.observe(1, current, 180_999, grinding=True)
        self.assertEqual(self.submit.call_count, 1)
        self.planner.observe(1, current, 181_000, grinding=True)
        self.planner.observe(1, current, 181_250, grinding=True)
        self.submit.assert_called_with(*args, excluded=frozenset(), current_map_id=1436)

    def test_cli_passes_opt_in_to_normal_window(self):
        with patch.object(run_dev, 'launch', return_value=0) as launch:
            self.assertEqual(run_dev.main(['app', '--auto-leveling', '--auto-revive', '--auto-navigate', '--no-watch']), 0)
            self.assertTrue(launch.call_args.kwargs['auto_leveling'])
            self.assertTrue(launch.call_args.kwargs['auto_revive'])
            self.assertTrue(launch.call_args.kwargs['auto_navigate'])
            self.assertFalse(launch.call_args.kwargs['watch'])

    def test_grind_mode_is_explicit_opt_in(self):
        with patch.object(run_dev, 'launch', return_value=0) as launch:
            self.assertEqual(run_dev.main(['app', '--auto-grind']), 0)
            self.assertTrue(launch.call_args.kwargs['auto_grind'])
            launch.reset_mock()
            self.assertEqual(run_dev.main(['app', '--auto-leveling', '--auto-navigate']), 0)
            self.assertNotIn('auto_grind', launch.call_args.kwargs)


class RevivalMouseTests(unittest.TestCase):
    def test_click_requires_known_game_foreground_and_unchanged_cursor(self):
        mouse = Win32Mouse.__new__(Win32Mouse)
        mouse.windows, mouse.processes, mouse.user = Mock(), Mock(), Mock()
        mouse.windows.GetAncestor.side_effect = lambda hwnd, _: hwnd
        mouse.windows.GetForegroundWindow.return_value = 100
        mouse.processes.process_path.return_value = r'D:\game\Wow.exe'
        mouse.user.GetAsyncKeyState.return_value = 0
        mouse.user.WindowFromPoint.return_value = 100
        mouse.user.GetCursorPos.side_effect = lambda out: self.set_cursor(out, 300, 400)
        mouse.user.SendInput.return_value = 2
        self.assertFalse(mouse.click(101, (300, 400)))
        self.assertFalse(mouse.click(100, (301, 400)))
        mouse.processes.process_path.return_value = r'D:\game\WowBuddyDev.exe'
        self.assertFalse(mouse.click(100, (300, 400)))
        mouse.user.SendInput.assert_not_called()

        mouse.processes.process_path.return_value = r'D:\game\Wow.exe'
        self.assertTrue(mouse.click(100, (300, 400)))
        count, events, size = mouse.user.SendInput.call_args.args
        self.assertEqual((count, size, [entry.mi.dwFlags for entry in events]), (2, 40, [2, 4]))

    @staticmethod
    def set_cursor(out, x, y):
        out._obj.x, out._obj.y = x, y
        return 1


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.position = NavigationState('ghost', 0, 52, 32.12, 36.15, 0.0, 1000, 800, (87, 65, 68))
        self.destination = MapDestination(52, 34.76, 36.15, 'ghost', '尸体')

    def test_controller_turns_and_moves_to_same_map_corpse_using_feedback(self):
        position = self.position
        movement = Mock()

        def pulse(_hwnd, key, hold, keys):
            nonlocal position
            duration = hold / 1000
            if key == keys[0]:
                distance = 7 * duration
                position = replace(position,
                    x=position.x - 100 * distance * math.sin(position.heading) / position.width,
                    y=position.y - 100 * distance * math.cos(position.heading) / position.height)
            else:
                direction = 1 if key == keys[1] else -1
                position = replace(position, heading=(position.heading + direction * duration * 3) % math.tau)
            return True

        movement.pulse.side_effect = pulse
        navigator = MapNavigator(movement)
        for sequence in range(80):
            position = replace(position, sequence=sequence)
            status = navigator.observe('session', 123, position, self.destination)
            if status:
                break
        self.assertIn('已到达', status)
        self.assertEqual(movement.pulse.call_args_list[0].args[1], ord('D'))
        self.assertTrue(any(item.args[1] == ord('W') for item in movement.pulse.call_args_list))
        self.assertTrue(all(20 <= item.args[2] <= 120 for item in movement.pulse.call_args_list))

    def test_cross_map_stale_and_stalled_positions_do_not_repeat_movement(self):
        movement = Mock()
        navigator = MapNavigator(movement)
        wrong_map = replace(self.position, map_id=53)
        self.assertIn('其他地图', navigator.observe('session', 123, wrong_map, self.destination))
        self.assertIsNone(navigator.observe('session', 123, wrong_map, self.destination))
        movement.pulse.assert_not_called()
        navigator.observe('session', 123, self.position, self.destination)
        navigator.observe('session', 123, self.position, self.destination)
        self.assertEqual(movement.pulse.call_count, 1)
        for sequence in range(1, 6):
            status = navigator.observe('session', 123, replace(self.position, sequence=sequence), self.destination)
        self.assertIn('连续五次', status)
        self.assertTrue(navigator.blocked)
        navigator.observe('session', 123, replace(self.position, sequence=6), self.destination)
        self.assertEqual(movement.pulse.call_count, 5)

    def test_returns_to_the_same_camp_after_combat_displaces_the_character(self):
        movement = Mock()
        movement.keep_forward.return_value = False
        navigator = MapNavigator(movement)
        start = replace(self.position, life='alive', continuous=True)
        camp = MapDestination(start.map_id, start.x, start.y, 'alive', '练级据点')
        self.assertIn('已到达', navigator.observe('session', 123, start, camp))
        self.assertIsNone(navigator.observe('session', 123, replace(start, sequence=1), camp))
        navigator.observe('session', 123, None, camp)
        outside = replace(start, sequence=2, x=start.x - 2, heading=3 * math.pi / 2)
        self.assertIsNone(navigator.observe('session', 123, outside, camp))
        movement.hold_forward.assert_called_once_with(123, outside.keys)
        self.assertIn('已到达', navigator.observe('session', 123, replace(start, sequence=3), camp))
        self.assertIsNone(navigator.observe('session', 123, replace(start, sequence=4), camp))

    def test_exit_probe_stops_on_a_stall_without_trying_a_local_detour(self):
        movement = Mock()
        navigator = MapNavigator(movement)
        position = replace(self.position, heading=3 * math.pi / 2)
        exit_point = replace(self.destination, radius=2, allow_detour=False)
        for sequence in range(6):
            status = navigator.observe('session', 123, replace(position, sequence=sequence), exit_point)
        self.assertIn('路口未确认切图', status)
        self.assertTrue(navigator.blocked)
        self.assertIsNone(navigator.observe('session', 123, replace(position, sequence=7), exit_point))
        self.assertEqual(movement.pulse.call_count, 5)

    def test_precision_waypoint_runs_until_close_then_stops_and_uses_short_steps(self):
        movement = Mock()
        movement.keep_forward.side_effect = (False, True, False)
        navigator = MapNavigator(movement)
        position = replace(self.position, continuous=True, heading=3 * math.pi / 2)
        waypoint = replace(self.destination, radius=1.25, precision_stop=True)
        navigator.observe('session', 123, position, waypoint)
        movement.hold_forward.assert_called_once_with(123, position.keys)
        close = replace(position, sequence=1, x=34.3, moving=True)
        navigator.observe('session', 123, close, waypoint)
        self.assertEqual(movement.release_forward.call_count, 2)
        movement.pulse.assert_not_called()
        navigator.observe('session', 123, replace(close, sequence=2, moving=False), waypoint)
        movement.pulse.assert_called_once_with(123, ord('W'), 120, position.keys)

    def simulate_detour(self, blocked, *, intermittent_path=False, size=(1000, 1000), position_steps=10_000,
                        via_x=None, finish_x=360):
        width, height = size
        decimals = 4 if position_steps == 1_000_000 else 2
        position = replace(self.position, x=30_000 / width, y=35_000 / height, width=width, height=height,
                           heading=3 * math.pi / 2, position_steps=position_steps)
        destination = MapDestination(52, 100 * finish_x / width, 35_000 / height, 'ghost', '尸体')
        movement = Mock()
        navigator = MapNavigator(movement)
        path = object() if intermittent_path else None
        if via_x is not None:
            path = WalkingTrip('session', (), destination, camp_road=((via_x, position.y),
                                                                     (destination.x, destination.y)))

        def pulse(_hwnd, key, hold, keys):
            nonlocal position
            duration = hold / 1000
            if key == keys[0]:
                distance = 7 * duration
                x = position.x - 100 * distance * math.sin(position.heading) / position.width
                y = position.y - 100 * distance * math.cos(position.heading) / position.height
                if not blocked(x * width / 100, y * height / 100):
                    position = replace(position, x=x, y=y)
            else:
                direction = 1 if key == keys[1] else -1
                position = replace(position, heading=(position.heading + direction * duration * 3) % math.tau)
            return True

        movement.pulse.side_effect = pulse
        log = []
        for sequence in range(400):
            if intermittent_path and sequence % 3 == 2:
                navigator.observe('session', 123, None, None, path=path)
                continue
            sample = replace(position, sequence=sequence % 256, x=round(position.x, decimals),
                             y=round(position.y, decimals))
            waypoint = path.observe(sample)[0] if via_x is not None else destination
            status = navigator.observe('session', 123, sample, waypoint, path=path)
            if status:
                log.append((status, sample))
                before = movement.pulse.call_count
                navigator.observe('session', 123, None, None if intermittent_path else waypoint, path=path)
                navigator.observe('session', 123, sample, waypoint, path=path)
                self.assertEqual(movement.pulse.call_count, before)
                if status.startswith(('已到达', '已暂停')):
                    for fresh in range(1, 5):
                        navigator.observe('session', 123, replace(sample, sequence=(sequence + fresh) % 256),
                                          waypoint, path=path)
                    self.assertEqual(movement.pulse.call_count, before)
                    break
        self.assertTrue(log)
        return log, movement.pulse.call_count

    def test_local_detour_uses_a_clear_side_then_resumes_direct_route(self):
        log, _ = self.simulate_detour(lambda x, y: 320 <= x <= 324 and 347 <= y <= 353)
        messages = [message for message, _ in log]
        self.assertIn('直行受阻', messages[0])
        self.assertTrue(any('已通过绕行段' in message for message in messages))
        self.assertIn('已到达', messages[-1])

    def test_continuous_detour_waits_for_a_stopped_sample_before_turning_at_a_corner(self):
        movement = Mock()
        movement.keep_forward.return_value = False
        navigator = MapNavigator(movement)
        anchor = replace(self.position, continuous=True, heading=3 * math.pi / 2)
        for sequence in range(6):
            status = navigator.observe('session', 123, replace(anchor, sequence=sequence), self.destination)
        self.assertIn('直行受阻', status)
        detour = navigator._detour
        corner, next_point = detour.waypoints
        east, north = corner.offset_from(anchor)
        heading = math.atan2(-east, north) % math.tau
        navigator.observe('session', 123, replace(anchor, sequence=6, heading=heading), self.destination)

        movement.reset_mock()
        movement.keep_forward.return_value = True
        movement.release_forward.side_effect = (False, True)
        moving = replace(anchor, sequence=7, x=corner.x, y=corner.y, heading=heading, moving=True)
        self.assertIsNone(navigator.observe('session', 123, moving, self.destination))
        self.assertEqual(detour.waypoints[0], corner)
        self.assertIsNone(navigator.observe('session', 123, replace(moving, sequence=8), self.destination))
        self.assertEqual(detour.waypoints[0], corner)
        self.assertEqual(movement.release_forward.call_count, 2)

        movement.keep_forward.return_value = False
        stopped = replace(moving, moving=False, sequence=9)
        self.assertIsNone(navigator.observe('session', 123, stopped, self.destination))
        self.assertEqual(detour.waypoints[0], next_point)
        navigator.observe('session', 123, stopped, self.destination)
        movement.hold_forward.assert_not_called()
        movement.pulse.assert_not_called()
        navigator.observe('session', 123, replace(stopped, sequence=10), self.destination)
        self.assertIn(movement.pulse.call_args.args[1], anchor.keys[1:])

    def test_barrens_size_can_detour_with_precise_readings(self):
        def blocked(x, y):
            return 320 <= x <= 324 and 347 <= y <= 353

        size = (10133, 6756)
        coarse, _ = self.simulate_detour(blocked, size=size)
        self.assertIn('缺少足够精度', coarse[-1][0])
        precise, _ = self.simulate_detour(blocked, size=size, position_steps=1_000_000, intermittent_path=True)
        messages = [message for message, _ in precise]
        self.assertTrue(any('已通过绕行段' in message for message in messages))
        self.assertIn('已到达', messages[-1])

    def test_barrens_detour_pauses_when_only_coarse_position_is_available(self):
        movement = Mock()
        navigator = MapNavigator(movement)
        position = replace(self.position, heading=3 * math.pi / 2, width=10133, height=6756,
                           position_steps=1_000_000)
        for sequence in range(6):
            status = navigator.observe('session', 123, replace(position, sequence=sequence), self.destination)
        self.assertIn('直行受阻', status)
        pulses = movement.pulse.call_count
        movement.release_forward.reset_mock()
        for sequence in range(5, 8):
            coarse = replace(position, sequence=sequence, position_steps=10_000)
            self.assertIsNone(navigator.observe('session', 123, coarse, self.destination))
        self.assertEqual(movement.pulse.call_count, pulses)
        self.assertEqual(movement.release_forward.call_count, 3)
        self.assertFalse(navigator.blocked)
        navigator.observe('session', 123, replace(position, sequence=8), self.destination)
        self.assertEqual(movement.pulse.call_count, pulses + 1)

    def test_local_detour_returns_to_anchor_before_trying_other_side(self):
        log, _ = self.simulate_detour(lambda x, y: 320 <= x <= 324 and 340 <= y <= 353)
        messages = [message for message, _ in log]
        self.assertIn('直行受阻', messages[0])
        self.assertIn('当前侧绕行受阻', messages[1])
        self.assertIn('已退回绕行起点', messages[2])
        anchor, returned = log[0][1], log[2][1]
        self.assertLessEqual(math.hypot((anchor.x - returned.x) * 10, (anchor.y - returned.y) * 10), 1.35)
        self.assertIn('已到达', messages[-1])

    def test_detour_changes_side_when_small_steps_never_make_net_progress(self):
        movement = Mock()
        navigator = MapNavigator(movement)
        anchor = replace(self.position, heading=3 * math.pi / 2)
        path = object()
        for sequence in range(6):
            status = navigator.observe('session', 123, replace(anchor, sequence=sequence),
                                       self.destination, path=path)
        self.assertIn('直行受阻', status)
        detour = navigator._detour
        for sequence in range(6, 80):
            if sequence % 2:
                navigator.observe('session', 123, None, None, path=path)
                continue
            # 读数在树根旁来回滑动，画面间歇缺失使单次按键回执无法配对。
            point = replace(anchor, sequence=sequence, x=anchor.x + (sequence % 4) * 0.01)
            east, north = detour.waypoints[0].offset_from(point)
            heading = math.atan2(-east, north)
            status = navigator.observe('session', 123, replace(point, heading=heading),
                                       self.destination, path=path)
            if status:
                break
        self.assertIn('先退回绕行起点', status)
        self.assertTrue(detour.returning)
        self.assertFalse(navigator.blocked)
        status = navigator.observe('session', 123, replace(anchor, sequence=81), self.destination, path=path)
        self.assertIn('改从另一侧', status)
        self.assertEqual(detour.pulses, 0)

    def test_each_separate_obstacle_has_its_own_detour_budget(self):
        def blocked(x, y):
            return ((310 <= x <= 313 and 347 <= y <= 353)
                    or (350 <= x <= 353 and 342 <= y <= 350)
                    or (390 <= x <= 393 and 343 <= y <= 352))

        log, _ = self.simulate_detour(blocked, finish_x=420)
        messages = [message for message, _ in log]
        self.assertEqual(sum('直行受阻' in message for message in messages), 3, messages)
        self.assertIn('已到达', messages[-1])

    def test_dead_end_retreats_along_the_approach_before_trying_a_wider_detour(self):
        def blocked(x, y):
            # 两侧在通道内都走不通。必须退回入口，才能绕过尽头。
            return ((325 <= x <= 333 and (347 <= y <= 348.5 or 351.5 <= y <= 353))
                    or (330 <= x <= 333 and 347 <= y <= 353))

        log, _ = self.simulate_detour(blocked, intermittent_path=True)
        messages = [message for message, _ in log]
        self.assertIn('直行受阻', messages[0])
        self.assertTrue(any('沿刚走过的路线后退' in message for message in messages))
        self.assertTrue(any('已通过绕行段' in message for message in messages))
        self.assertIn('已到达', messages[-1])

    def test_dead_end_immediately_after_a_waypoint_can_retreat_along_the_previous_leg(self):
        def blocked(x, y):
            return ((325 <= x <= 333 and (347 <= y <= 348.5 or 351.5 <= y <= 353))
                    or (330 <= x <= 333 and 347 <= y <= 353))

        log, _ = self.simulate_detour(blocked, intermittent_path=True, via_x=33)
        messages = [message for message, _ in log]
        self.assertIn('路点 2', messages[0])
        self.assertTrue(any('沿刚走过的路线后退' in message for message in messages), messages)
        self.assertTrue(any('已通过绕行段' in message for message in messages), messages)
        self.assertIn('已到达', messages[-1])

    def test_waypoint_trail_is_reset_for_new_routes_unconfirmed_arrivals_and_position_jumps(self):
        origin = replace(self.position, x=30, y=35, width=1000, height=1000, heading=3 * math.pi / 2)
        first = MapDestination(52, 31, 35, 'ghost', '第一个路点', radius=2)
        second = MapDestination(52, 36, 35, 'ghost', '第二个路点')
        for case, x in (('new_route', 30.84), ('not_arrived', 30.58), ('position_jump', 31.05)):
            with self.subTest(case=case):
                navigator = MapNavigator(Mock())
                path = object()
                for sequence in range(8):
                    sample = replace(origin, sequence=sequence, x=origin.x + sequence * 0.08)
                    navigator.observe('session', 123, sample, first, path=path)
                self.assertGreater(len(navigator._trail), 1)
                arrived = replace(origin, sequence=8, x=x)
                navigator.observe('session', 123, arrived, second, path=object() if case == 'new_route' else path)
                self.assertEqual([point.x for point in navigator._trail], [x])

    def test_local_detour_stops_after_both_sides_fail(self):
        for intermittent_path in (False, True):
            with self.subTest(intermittent_path=intermittent_path):
                log, pulses = self.simulate_detour(lambda _x, _y: True, intermittent_path=intermittent_path)
                self.assertIn('绕行各可用方向均受阻', log[-1][0])
                self.assertEqual(sum('直行受阻' in message for message, _ in log), 1)
                self.assertLess(pulses, 50 if intermittent_path else 40)

    def test_detour_stops_when_coordinates_leave_its_local_area(self):
        movement = Mock()
        navigator = MapNavigator(movement)
        position = replace(self.position, heading=3 * math.pi / 2)
        for sequence in range(6):
            status = navigator.observe('session', 123, replace(position, sequence=sequence), self.destination)
        self.assertIn('直行受阻', status)
        self.assertIn('离开局部绕行范围', navigator.observe(
            'session', 123, replace(position, sequence=6, y=position.y + 3), self.destination))
        self.assertEqual(movement.pulse.call_count, 5)

    def test_navigation_discards_a_detour_after_external_displacement(self):
        start = replace(self.position, heading=3 * math.pi / 2)
        for interruption in ('moving', 'manual_key', 'missing_position'):
            with self.subTest(interruption=interruption):
                movement = Mock()
                navigator = MapNavigator(movement)
                for sequence in range(6):
                    status = navigator.observe('session', 123, replace(start, sequence=sequence), self.destination)
                self.assertIn('直行受阻', status)
                movement.pulse.reset_mock()

                if interruption == 'missing_position':
                    self.assertIsNone(navigator.observe('session', 123, None, self.destination))
                    self.assertIsNone(navigator.observe(
                        'session', 123, replace(start, sequence=5), self.destination))
                else:
                    paused = replace(start, sequence=6, moving=interruption == 'moving')
                    movement.can_input.return_value = interruption != 'manual_key'
                    self.assertIsNone(navigator.observe('session', 123, paused, self.destination))
                    movement.can_input.return_value = True
                    self.assertIsNone(navigator.observe('session', 123, paused, self.destination))
                movement.pulse.assert_not_called()

                displaced = replace(start, sequence=7, x=start.x - 2.5)
                self.assertIsNone(navigator.observe('session', 123, displaced, self.destination))
                self.assertFalse(navigator.blocked)
                self.assertEqual(movement.pulse.call_args.args[1], start.keys[0])

    def test_foreground_key_pulse_releases_key_after_partial_failure(self):
        keyboard, processes = Mock(), Mock()
        keyboard.GetAncestor.side_effect = lambda hwnd, _: hwnd
        keyboard.GetForegroundWindow.return_value = 100
        keyboard.GetAsyncKeyState.return_value = 0x8000
        keyboard.MapVirtualKeyW.return_value = 0x11
        processes.process_path.return_value = r'D:\game\Wow.exe'
        pulse = ForegroundMovement(keyboard, processes)
        self.assertFalse(pulse.pulse(101, 87, 120, self.position.keys))
        self.assertFalse(pulse.pulse(100, 87, 120, self.position.keys))
        keyboard.SendInput.assert_not_called()

        keyboard.GetAsyncKeyState.return_value = 0
        keyboard.SendInput.side_effect = (1, 0, 1)
        self.assertTrue(pulse.pulse(100, 87, 120, self.position.keys))
        self.assertEqual([call.args[0][0].flags for call in keyboard.SendInput.call_args_list], [0, 2, 2])

    def test_forward_key_is_held_across_fresh_samples_and_watchdog_releases_it(self):
        keyboard, processes = Mock(), Mock()
        keyboard.GetAncestor.side_effect = lambda hwnd, _: hwnd
        keyboard.GetForegroundWindow.return_value = 100
        keyboard.MapVirtualKeyW.return_value = 0x11
        processes.process_path.return_value = r'D:\game\Wow.exe'
        down = set()

        def inject(events):
            event = events[0]
            if event.flags & 2:
                down.discard(event.vk)
            else:
                down.add(event.vk)
            return 1

        keyboard.SendInput.side_effect = inject
        keyboard.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key in down else 0
        movement = ForegroundMovement(keyboard, processes)
        keys = self.position.keys
        with (patch('wowbuddy.automation.navigation.Timer') as timer,
              patch('wowbuddy.automation.navigation.monotonic', return_value=0.0) as clock):
            self.assertTrue(movement.hold_forward(100, keys))
            clock.return_value = 0.2
            self.assertTrue(movement.keep_forward(100, keys))
            self.assertTrue(movement.hold_forward(100, keys))
            keyboard.SendInput.assert_called_once()
            first_expiry = timer.call_args.args[1]
            clock.return_value = 0.71
            first_expiry()
            self.assertEqual(down, {87})
            clock.return_value = 1.0
            timer.call_args.args[1]()
            self.assertEqual(down, set())
            self.assertEqual([call.args[0][0].flags for call in keyboard.SendInput.call_args_list], [0, 2])

            self.assertTrue(movement.hold_forward(100, keys))
            keyboard.GetForegroundWindow.return_value = 101
            self.assertFalse(movement.keep_forward(100, keys))
            self.assertEqual(down, set())

    def test_failed_turn_keyup_releases_owned_keys_even_without_new_position(self):
        for steering in (False, True):
            with self.subTest(steering=steering):
                keyboard, processes = Mock(), Mock()
                keyboard.GetAncestor.side_effect = lambda hwnd, _: hwnd
                keyboard.GetForegroundWindow.return_value = 100
                keyboard.MapVirtualKeyW.return_value = 0x11
                processes.process_path.return_value = r'D:\game\Wow.exe'
                movement = ForegroundMovement(keyboard, processes)
                keys = self.position.keys
                forward, left, _ = keys
                down = set()
                failures = iter((0, 0, 0, 0, 1))

                def inject(events):
                    event = events[0]
                    if event.flags & 2:
                        if event.vk == left and not next(failures):
                            return 0
                        down.discard(event.vk)
                    else:
                        down.add(event.vk)
                    return 1

                keyboard.SendInput.side_effect = inject
                keyboard.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key in down else 0
                with (patch('wowbuddy.automation.navigation.Timer') as timer,
                      patch('wowbuddy.automation.navigation.monotonic', return_value=0.0) as clock):
                    if steering:
                        self.assertTrue(movement.hold_forward(100, keys))
                    self.assertFalse(movement.pulse(100, left, 35, keys, steering=steering))
                    self.assertEqual(down, {forward, left} if steering else {left})
                    self.assertEqual(timer.call_args.args[0], 0.1)
                    keyboard.GetForegroundWindow.return_value = 101
                    clock.return_value = 0.11
                    timer.call_args.args[1]()
                    self.assertEqual(down, {left})
                    self.assertFalse(movement.holding_forward)
                    clock.return_value = 0.22
                    timer.call_args.args[1]()
                    self.assertEqual(down, set())
                    events = [call.args[0][0] for call in keyboard.SendInput.call_args_list]
                    pressed = [event.vk for event in events if not event.flags & 2]
                    self.assertEqual(pressed, [forward, left] if steering else [left])

    def test_navigator_renews_on_new_moving_samples_and_yields_on_lost_feedback(self):
        movement = Mock()
        movement.keep_forward.return_value = False
        navigator = MapNavigator(movement)
        start = replace(self.position, continuous=True, heading=3 * math.pi / 2)
        navigator.observe('session', 123, start, self.destination)
        movement.hold_forward.assert_called_once_with(123, start.keys)
        movement.keep_forward.return_value = True
        for sequence in range(1, 5):
            sample = replace(start, moving=True, sequence=sequence, x=start.x + sequence * 0.12)
            navigator.observe('session', 123, sample, self.destination)
            navigator.observe('session', 123, sample, self.destination)
        self.assertEqual(movement.hold_forward.call_count, 5)
        movement.pulse.assert_not_called()
        movement.release_forward.reset_mock()
        navigator.observe('session', 123, None, self.destination)
        movement.release_forward.assert_called_once_with()
        movement.keep_forward.return_value = False
        navigator.observe('session', 123, replace(sample, sequence=5), self.destination)
        self.assertEqual(movement.hold_forward.call_count, 5)

    def test_map_navigation_does_not_count_manual_takeover_as_a_stall(self):
        start = replace(self.position, continuous=True, heading=3 * math.pi / 2)
        exit_point = replace(self.destination, radius=2, allow_detour=False)
        for external_motion in (False, True):
            with self.subTest(external_motion=external_motion):
                movement = Mock()
                movement.keep_forward.side_effect = (False, True, True, True, True)
                navigator = MapNavigator(movement)
                for sequence in range(5):
                    sample = replace(start, sequence=sequence)
                    self.assertIsNone(navigator.observe('session', 123, sample, exit_point))
                self.assertEqual(movement.hold_forward.call_count, 5)

                movement.keep_forward.side_effect = None
                movement.keep_forward.return_value = False
                movement.can_input.return_value = external_motion
                paused = replace(start, sequence=5, moving=external_motion, x=start.x - 0.1)
                self.assertIsNone(navigator.observe('session', 123, paused, exit_point))
                self.assertFalse(navigator.blocked)
                self.assertEqual(movement.hold_forward.call_count, 5)
                movement.pulse.assert_not_called()

                movement.can_input.return_value = True
                self.assertIsNone(navigator.observe('session', 123, paused, exit_point))
                self.assertEqual(movement.hold_forward.call_count, 5)
                stationary = replace(paused, sequence=6, moving=False)
                self.assertIsNone(navigator.observe('session', 123, stationary, exit_point))
                self.assertEqual(movement.hold_forward.call_count, 6)
                movement.keep_forward.return_value = True
                for sequence in range(7, 11):
                    sample = replace(stationary, sequence=sequence)
                    self.assertIsNone(navigator.observe('session', 123, sample, exit_point))
                self.assertIn('路口未确认切图', navigator.observe(
                    'session', 123, replace(stationary, sequence=11), exit_point))

    def test_road_waypoint_and_gentle_turn_share_one_forward_keypress(self):
        keyboard, processes = Mock(), Mock()
        keyboard.GetAncestor.side_effect = lambda hwnd, _: hwnd
        keyboard.GetForegroundWindow.return_value = 123
        keyboard.MapVirtualKeyW.return_value = 0x11
        processes.process_path.return_value = r'D:\game\Wow.exe'
        down = set()
        events = []

        def inject(inputs):
            event = inputs[0]
            released = bool(event.flags & 2)
            events.append((event.vk, released))
            if released:
                down.discard(event.vk)
            else:
                down.add(event.vk)
            return 1

        keyboard.SendInput.side_effect = inject
        keyboard.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key in down else 0
        navigator = MapNavigator(ForegroundMovement(keyboard, processes))
        path = object()
        start = replace(self.position, continuous=True, heading=3 * math.pi / 2)
        next_point = replace(self.destination, x=37, y=35, label='下一路点')
        with patch('wowbuddy.automation.navigation.Timer'):
            navigator.observe('session', 123, start, self.destination, path=path)
            moving = replace(start, moving=True, sequence=1, x=34)
            navigator.observe('session', 123, moving, next_point, path=path)
            self.assertEqual(events, [(87, False), (65, False), (65, True)])
            navigator.observe('session', 123, moving, next_point, path=path)
            self.assertEqual(len(events), 3)

            sharp_corner = replace(next_point, x=moving.x, y=39, label='急弯')
            navigator.observe('session', 123, replace(moving, sequence=2), sharp_corner, path=path)
            self.assertEqual(events[-1], (87, True))
            self.assertEqual(down, set())

    def test_target_approach_renews_owned_forward_and_stops_without_bearing(self):
        movement = Mock()
        movement.keep_forward.return_value = False
        approach = TargetApproach(movement)
        position = replace(self.position, life='alive', continuous=True)
        target = TargetBearing(3, 0.5, 37, continuous=True)
        session = (123, 1)

        approach.observe(session, position, target)
        approach.observe(session, replace(position, sequence=1), target)
        movement.hold_forward.assert_called_once_with(123, position.keys)
        movement.keep_forward.return_value = True
        moving = replace(position, sequence=2, moving=True)
        bearing = replace(target, x=0.43, distance=35)
        approach.observe(session, moving, bearing)
        approach.observe(session, moving, bearing)
        self.assertEqual(movement.hold_forward.call_count, 2)
        movement.pulse.assert_called_once_with(123, 65, 35, position.keys, steering=True)
        movement.release_forward.assert_not_called()
        approach.observe(session, moving, None)
        movement.release_forward.assert_called_once_with()
        movement.keep_forward.return_value = False
        farther = replace(position, sequence=3, x=position.x + 5)
        self.assertIsNone(approach.observe(session, farther, target))
        self.assertIn('移动范围上限', approach.observe(session, replace(farther, sequence=4), target))

    def test_target_approach_rebases_after_external_motion(self):
        session = (123, 1)
        position = replace(self.position, life='alive', continuous=True, target_revision=3)
        target = TargetBearing(3, 0.5, 37, continuous=True)
        for paused_bearing in (target, None):
            with self.subTest(bearing_during_pause=paused_bearing):
                movement = Mock()
                movement.keep_forward.return_value = False
                approach = TargetApproach(movement)
                approach.observe(session, position, target, allow_unlocated=True)
                self.assertIn('开始接近', approach.observe(session, replace(position, sequence=1), target))
                movement.hold_forward.assert_called_once()

                moving = replace(position, sequence=2, x=position.x + 5, moving=True)
                self.assertIsNone(approach.observe(session, moving, paused_bearing, allow_unlocated=True))
                self.assertFalse(approach.pursuing)
                self.assertTrue(approach.waiting_for_input_or_bearing)
                self.assertIsNone(approach.observe(session, replace(moving, moving=False), target))
                self.assertEqual(movement.hold_forward.call_count, 1)

                stopped = replace(moving, sequence=3, moving=False)
                self.assertIsNone(approach.observe(session, stopped, target))
                self.assertFalse(approach.exhausted_for(session, stopped))
                self.assertFalse(approach.waiting_for_input_or_bearing)
                self.assertEqual(movement.hold_forward.call_count, 2)

                movement.keep_forward.return_value = True
                for sequence in range(4, 8):
                    self.assertIsNone(approach.observe(session, replace(stopped, sequence=sequence), target))
                self.assertIn('距离变化', approach.observe(session, replace(stopped, sequence=8), target))

    def test_target_approach_pauses_on_missing_bearing_and_caps_retries_without_progress(self):
        movement = Mock()
        approach = TargetApproach(movement)
        position = replace(self.position, life='alive')
        target = TargetBearing(3, 0.5, 37)

        def observe(sequence, bearing=target):
            return approach.observe((10, 1), replace(position, sequence=sequence), bearing)

        observe(1)
        observe(1)
        observe(2, None)
        observe(3)
        movement.pulse.assert_not_called()
        self.assertIn('开始接近', observe(4))
        for sequence in range(5, 10):
            status = observe(sequence)
        self.assertIn('距离变化', status)
        self.assertIsNone(observe(10))
        self.assertEqual(movement.pulse.call_count, 5)

        observe(11, replace(target, revision=4))
        self.assertIn('开始接近', observe(12, replace(target, revision=4)))
        self.assertEqual(movement.pulse.call_count, 6)

    def test_target_approach_prefers_recovered_bearing_before_reselect_is_sent(self):
        movement = Mock()
        approach = TargetApproach(movement)
        session = (123, 1)
        position = replace(self.position, life='alive', target_revision=3, retarget_key=9)
        for sample in range(17):
            current = replace(position, sequence=sample)
            status = approach.observe(session, current, None, allow_unlocated=True, now_ms=sample * 500)
        self.assertIn('持续缺少', status)
        self.assertTrue(approach.exhausted_for(session, current))
        approach.retarget(session, current, allowed=True, now_ms=8000)
        movement.pulse.assert_not_called()
        target = TargetBearing(3, 0.5, 37)
        approach.observe(session, replace(current, sequence=17), target, allow_unlocated=True, now_ms=8100)
        status = approach.observe(session, replace(current, sequence=18), target, allow_unlocated=True, now_ms=8200)
        self.assertIn('开始接近', status)
        movement.pulse.assert_called_once_with(123, 87, 120, position.keys)

    def test_missing_combat_bearing_scans_in_place_until_recovered_or_exhausted(self):
        for recovery in (True, False):
            with self.subTest(recovery=recovery):
                movement = Mock()
                movement.keep_forward.return_value = False
                approach = TargetApproach(movement)
                session = (123, 1)
                position = replace(self.position, life='alive', target_revision=3, heading=6.0)

                def observe(sequence, heading=6.0, bearing=None, **changes):
                    sample = replace(position, sequence=sequence, heading=heading, **changes)
                    return approach.observe(session, sample, bearing, scan_in_combat=True, now_ms=sequence * 500)

                observe(1, target_revision=None)
                observe(2)
                observe(2)
                movement.pulse.assert_not_called()
                self.assertIn('开始原地转向', observe(3))
                observe(3)
                movement.pulse.assert_called_once_with(123, 65, 240, position.keys)
                if recovery:
                    target = TargetBearing(3, .5, 32.5)
                    observe(4, .45, target)
                    self.assertIn('开始接近', observe(5, .45, target))
                    movement.pulse.assert_called_with(123, 87, 120, position.keys)
                else:
                    observe(4)
                    self.assertIn('已停止转向', observe(5))
                    self.assertIsNone(observe(6))
                    self.assertEqual([item.args[1] for item in movement.pulse.call_args_list], [65, 65])

    def test_target_approach_does_not_inherit_reselection_for_late_or_unconfirmed_changes(self):
        for revision, switched_at in ((4, 4250), (5, 2250)):
            with self.subTest(revision=revision, switched_at=switched_at):
                movement = Mock()
                approach = TargetApproach(movement)
                session = (123, 1)
                position = replace(self.position, life='alive', target_revision=3, retarget_key=9, discard_key=0x77)

                def stall(first_sequence, start_ms, sample):
                    for offset in range(7):
                        now = start_ms + offset * 250
                        current = replace(sample, sequence=first_sequence + offset)
                        approach.observe(session, current, TargetBearing(sample.target_revision, 0.5, 37), now_ms=now)
                    self.assertTrue(approach.exhausted_for(session, current))
                    self.assertIsNone(approach.retarget(session, current, allowed=True, now_ms=now))
                    following = replace(current, sequence=current.sequence + 1)
                    self.assertIn('重选一次', approach.retarget(session, following, allowed=True, now_ms=now + 250))

                stall(1, 250, position)
                stall(9, switched_at, replace(position, target_revision=revision))
                self.assertEqual([call.args[1] for call in movement.pulse.call_args_list].count(9), 2)
                self.assertNotIn(0x77, [call.args[1] for call in movement.pulse.call_args_list])

    def test_discard_retries_once_after_failed_input_or_missing_acknowledgement(self):
        for first_sent in (False, True):
            with self.subTest(first_sent=first_sent):
                movement = Mock()
                movement.pulse.side_effect = (first_sent, True)
                approach = TargetApproach(movement)
                session = (123, 1)
                position = replace(self.position, life='alive', target_revision=3, discard_key=119)

                def poll(sequence, now, *, allowed=True):
                    sample = replace(position, sequence=sequence)
                    self.assertIsNone(approach.confirmed_discard(session, sample, 'ON', now))
                    approach.observe(session, sample, None, now_ms=now, allow_unlocated=True, sight_blocked=True)
                    return approach.retarget(session, sample, allowed=allowed, now_ms=now)

                self.assertIsNone(poll(1, 100))
                self.assertIn('等待游戏确认' if first_sent else '未成功发送', poll(2, 350))
                self.assertIsNone(poll(3, 2349))
                self.assertIsNone(poll(4, 2351, allowed=False))
                self.assertIsNone(poll(5, 2400))
                self.assertIsNone(poll(5, 2450))
                self.assertIn('等待游戏确认', poll(6, 2600))
                self.assertEqual(movement.pulse.call_count, 2)
                if first_sent:
                    self.assertIsNone(poll(7, 4601))
                    self.assertIsNone(poll(8, 4900))
                else:
                    cleared = replace(position, sequence=7, target_revision=4)
                    self.assertEqual(approach.confirmed_discard(session, cleared, 'OFF', 2800),
                                     (replace(position, sequence=1), None))
                self.assertEqual(movement.pulse.call_count, 2)

    def test_discard_receipt_can_resume_after_a_capture_pause(self):
        session = (123, 1)
        position = replace(self.position, life='alive', target_revision=3, discard_key=119)
        for recovered_revision, receipt_after_ms in ((4, 0), (3, 1000), (3, 2250), (5, 0)):
            with self.subTest(recovered_revision=recovered_revision, receipt_after_ms=receipt_after_ms):
                movement = Mock()
                approach = TargetApproach(movement)
                approach.observe(session, position, None, now_ms=0, allow_unlocated=True, sight_blocked=True)
                approach.retarget(session, position, allowed=True, now_ms=0)
                following = replace(position, sequence=1)
                self.assertIn('等待游戏确认', approach.retarget(session, following, allowed=True, now_ms=250))
                approach.pause(session)
                self.assertIsNone(approach.confirmed_discard(session, None, 'OFF', 9000))

                recovered = replace(position, sequence=2, target_revision=recovered_revision)
                receipt = approach.confirmed_discard(session, recovered,
                                                     'ON' if recovered_revision == 3 else 'OFF', 10_000)
                if recovered_revision == 3:
                    self.assertIsNone(receipt)
                    cleared = replace(recovered, sequence=3, target_revision=4)
                    receipt = approach.confirmed_discard(session, cleared, 'OFF', 10_000 + receipt_after_ms)
                expected = (position, None) if recovered_revision in (3, 4) and receipt_after_ms <= 2000 else None
                self.assertEqual(receipt, expected)
                movement.pulse.assert_called_once()

    def test_target_approach_uses_player_displacement_when_distance_is_coarse(self):
        for distance in (72.5, None):
            with self.subTest(distance=distance):
                movement = Mock()
                approach = TargetApproach(movement)
                position = replace(self.position, life='alive', width=1000)
                target = TargetBearing(3, 0.5, distance, estimated=True)
                session = (123, 1)
                for sequence in range(8):
                    sample = replace(position, sequence=sequence, x=position.x + max(0, sequence - 1) / 10)
                    approach.observe(session, sample, target)
                self.assertEqual(movement.pulse.call_count, 7)
                if distance is None:
                    at_limit = replace(position, sequence=8, x=position.x + 0.81)
                    self.assertIn('移动范围上限', approach.observe(session, at_limit, target))
                    movement.release_forward.assert_called_once_with()
                    self.assertEqual(movement.pulse.call_count, 7)
                else:
                    target = replace(target, distance=80)
                    for sequence in range(8, 13):
                        sample = replace(position, sequence=sequence, x=position.x + (sequence - 1) / 10)
                        status = approach.observe(session, sample, target)
                    self.assertIn('距离变化', status)
                    movement.release_forward.assert_called_once_with()


class ArrivalPullTests(unittest.TestCase):
    def setUp(self):
        self.session = (10, 1)
        self.dispatcher = Mock()
        self.dispatcher.state.last_sent_ms = 0
        self.dispatcher.dispatch.return_value.success = True
        self.foreground = Mock()
        self.pull = ArrivalPull(self.dispatcher, self.foreground)
        self.position = NavigationState('alive', 0, 52, 32.12, 36.15, 0, 1000, 800, (87, 65, 68), 1)
        self.destination = MapDestination(52, 32.12, 36.15, 'alive', '练级据点')

    def step(self, sequence, now, *, gate=0, ready=True, x=32.12, target='OFF', ack=0,
             revision=None, range_blocked=False, pursuing=False, heading=0, allow_retarget=True, status=None,
             moving=False, rejection=None):
        fields = {'ttd': str(PACKET_BASE + 8192 + 1024 * gate + 32 * ack + 1),
                  'target_valid': target, 'player_valid': 'ON', 'player_in_combat': 'OFF'}
        frame = OldFrame('ok', values=fields)
        tick = TickResult(status or ('no_candidates' if range_blocked else 'stopped'),
                          Decision(frame, fields, (), recovery_ready=ready, attack_blocked_by_range=range_blocked,
                                   target_rejection=rejection),
                          display_now_ms=10_000)
        position = replace(self.position, sequence=sequence, x=x, heading=heading,
                           target_revision=revision, retarget_key=9, moving=moving)
        return self.pull.observe(self.session, self.destination, position, tick, now, 100, pursuing=pursuing,
                                 allow_retarget=allow_retarget)

    def test_camp_scans_four_confirmed_directions_before_reporting_empty(self):
        self.position = replace(self.position, continuous=True)
        self.step(1, 0)
        self.assertIn('已发出', self.step(2, 250))
        for sector in range(1, 4):
            with self.subTest(sector=sector):
                sequence, time = 3 + (sector - 1) * 4, 2250 + (sector - 1) * 2750
                old_heading, heading = (sector - 1) * math.pi / 2, sector * math.pi / 2
                self.step(sequence, time, ack=sector, heading=old_heading)
                status = self.step(sequence + 1, time + 250, ack=sector, heading=old_heading)
                self.assertIn(f'第 {sector + 1} 个方向', status)
                self.foreground.pulse.assert_called_with(10, self.position.keys[1], 120, self.position.keys)
                self.assertEqual(self.dispatcher.dispatch.call_count, sector)
                self.step(sequence + 2, time + 500, ack=sector, heading=heading)
                self.assertIn('已发出', self.step(sequence + 3, time + 750, ack=sector, heading=heading))
                self.assertFalse(self.pull.empty)
        self.assertIn('四个方向', self.step(15, 10_500, ack=4, heading=3 * math.pi / 2))
        self.assertEqual(self.dispatcher.dispatch.call_count, 4)
        self.assertTrue(self.pull.empty)

    def test_camp_keeps_scanning_after_a_rejected_target_is_cleared(self):
        for initially_acceptable in (False, True):
            with self.subTest(initially_acceptable=initially_acceptable):
                self.pull = ArrivalPull(self.dispatcher, self.foreground)
                self.dispatcher.reset_mock()
                self.foreground.reset_mock()
                self.position = replace(self.position, continuous=True)
                self.step(1, 0, revision=10)
                self.assertIn('已发出', self.step(2, 250, revision=10))
                rejected = dict(target='ON', revision=11, ack=1, gate=1,
                                rejection='当前怪物已被其他玩家占有')
                if initially_acceptable:
                    self.assertIn('可攻击目标', self.step(3, 500, target='ON', revision=11, ack=1, gate=1))
                self.assertIsNone(self.step(4, 750, **rejected))
                self.foreground.pulse.assert_not_called()
                self.dispatcher.dispatch.assert_called_once()
                self.step(5, 2250, ack=1, revision=12)
                self.assertIn('第 2 个方向', self.step(6, 2500, ack=1, revision=12))
                second = math.pi / 2
                self.step(7, 2750, ack=1, revision=12, heading=second)
                self.assertIn('已发出', self.step(8, 3000, ack=1, revision=12, heading=second))
                self.assertEqual(self.dispatcher.dispatch.call_count, 2)

    def test_rejected_target_budget_expires_and_resets_after_combat_or_session_change(self):
        session = (10, 1)
        record = self.pull.record_rejected_target
        camp = self.destination
        self.assertFalse(record(session, camp, replace(self.position, x=80), 0))
        self.assertFalse(record(session, camp, self.position, 1000))
        self.assertFalse(record(session, camp, self.position, 2000))
        self.assertFalse(record(session, camp, self.position, 62_001))
        fields = {'player_in_combat': 'ON'}
        frame = OldFrame('ok', values=fields)
        fight = TickResult('sent', Decision(frame, fields, ()))
        self.pull.observe(session, camp, self.position, fight, 62_250, 100)
        self.assertFalse(record(session, camp, self.position, 62_500))
        self.assertFalse(record(session, camp, self.position, 63_000))
        session = (10, 2)
        self.assertFalse(record(session, camp, self.position, 64_000))
        self.assertFalse(record(session, camp, self.position, 65_000))
        self.assertTrue(record(session, camp, self.position, 66_000))

    def test_camp_scan_cancels_after_target_appears_or_turn_cannot_be_confirmed(self):
        for target_appears in (False, True):
            with self.subTest(target_appears=target_appears):
                self.pull = ArrivalPull(self.dispatcher, self.foreground)
                self.dispatcher.reset_mock()
                self.foreground.reset_mock()
                self.position = replace(self.position, continuous=True)
                self.step(1, 0)
                self.step(2, 250)
                self.step(3, 2250, ack=1)
                self.assertIn('第 2 个方向', self.step(4, 2500, ack=1))
                if target_appears:
                    self.assertIn('可攻击目标', self.step(5, 2750, ack=1, target='ON'))
                else:
                    self.step(5, 7250, ack=1)
                    self.assertIn('未确认转到', self.step(6, 7500, ack=1))
                self.assertFalse(self.pull.empty)
                self.assertEqual(self.dispatcher.dispatch.call_count, 1)

    def test_camp_scan_resumes_the_same_turn_after_input_or_readiness_is_lost(self):
        for interruption in ('input', 'moving', 'recovery'):
            with self.subTest(interruption=interruption):
                self.setUp()
                self.position = replace(self.position, continuous=True)
                self.step(1, 0)
                self.assertIn('已发出', self.step(2, 250))
                self.step(3, 2250, ack=1)
                self.assertIn('第 2 个方向', self.step(4, 2500, ack=1))

                self.foreground.can_input.return_value = interruption != 'input'
                self.assertIsNone(self.step(5, 2800, ack=1, moving=interruption == 'moving',
                                            ready=interruption != 'recovery'))
                self.foreground.can_input.return_value = True
                self.assertIsNone(self.step(6, 160_000, ack=1))
                self.assertIn('第 2 个方向', self.step(7, 160_250, ack=1))
                self.assertEqual(self.dispatcher.dispatch.call_count, 1)
                self.step(8, 160_500, ack=1, heading=math.pi / 2)
                self.assertIn('已发出', self.step(9, 160_750, ack=1, heading=math.pi / 2))
                self.assertEqual(self.dispatcher.dispatch.call_count, 2)
                self.assertFalse(self.pull.empty)

    def test_camp_scan_retries_same_direction_after_failed_send_or_missing_ack(self):
        for delivery_succeeded in (False, True):
            with self.subTest(delivery_succeeded=delivery_succeeded):
                self.pull = ArrivalPull(self.dispatcher, self.foreground)
                self.dispatcher.reset_mock()
                self.foreground.reset_mock()
                self.dispatcher.dispatch.return_value.success = True
                self.position = replace(self.position, continuous=True)
                self.step(1, 0)
                self.step(2, 250)
                self.step(3, 2250, ack=1)
                self.assertIn('第 2 个方向', self.step(4, 2500, ack=1))
                second = math.pi / 2
                self.dispatcher.dispatch.return_value.success = delivery_succeeded
                self.step(5, 2750, ack=1, heading=second)
                self.step(6, 3000, ack=1, heading=second)
                self.assertEqual(self.dispatcher.dispatch.call_count, 2)

                self.dispatcher.dispatch.return_value.success = True
                self.step(7, 5000, ack=1, heading=second)
                self.assertIsNone(self.step(7, 5100, ack=1, heading=second))
                self.assertIn('已发出', self.step(8, 5250, ack=1, heading=second))
                self.assertEqual(self.foreground.pulse.call_count, 1)
                self.step(9, 7250, ack=2, heading=second)
                self.assertIn('第 3 个方向', self.step(10, 7500, ack=2, heading=second))
                self.assertEqual(self.dispatcher.dispatch.call_count, 3)
                self.assertFalse(self.pull.empty)

    def test_camp_scan_with_two_missing_receipts_keeps_the_camp(self):
        self.position = replace(self.position, continuous=True)
        self.step(1, 0)
        self.step(2, 250)
        self.step(3, 2250, ack=1)
        self.assertIn('第 2 个方向', self.step(4, 2500, ack=1))
        second = math.pi / 2
        self.step(5, 2750, ack=1, heading=second)
        self.step(6, 3000, ack=1, heading=second)
        self.step(7, 5000, ack=1, heading=second)
        self.step(8, 5250, ack=1, heading=second)
        self.assertIn('回执', self.step(9, 7250, ack=1, heading=second))
        self.assertEqual(self.dispatcher.dispatch.call_count, 3)
        self.assertEqual(self.foreground.pulse.call_count, 1)
        self.assertFalse(self.pull.empty)

    def test_retarget_rejects_unacknowledged_or_changed_target_and_waits_for_pursuit(self):
        for case in ('unacknowledged', 'changed', 'pursuing'):
            with self.subTest(case=case):
                self.pull = ArrivalPull(self.dispatcher, self.foreground)
                self.step(1, 0, revision=10)
                self.step(2, 250, revision=10)
                ack = 0 if case == 'unacknowledged' else 1
                self.step(3, 500, revision=11, target='ON', ack=ack, range_blocked=True)
                self.step(4, 8000, revision=12 if case == 'changed' else 11,
                          target='ON', ack=ack, range_blocked=True, pursuing=case == 'pursuing')
                for sequence, now in ((5, 8500), (6, 8750)):
                    self.step(sequence, now, revision=12 if case == 'changed' else 11,
                              target='ON', ack=ack, range_blocked=True)
                self.foreground.pulse.assert_not_called()

    def test_camp_retarget_yields_to_exhausted_approach(self):
        self.step(1, 0, revision=10)
        self.step(2, 250, revision=10)
        self.step(3, 500, revision=11, target='ON', ack=1, range_blocked=True)
        for sequence, now in ((4, 8500), (5, 8750), (6, 9000)):
            self.step(sequence, now, revision=11, target='ON', ack=1, range_blocked=True,
                      allow_retarget=False)
        self.foreground.pulse.assert_not_called()
        self.assertIn('追踪的目标已变化',
                      self.step(7, 9250, revision=12, target='ON', ack=1, range_blocked=True))

    def test_camp_joins_target_and_key_receipts_that_arrive_on_different_frames(self):
        cases = (
            (10, 0, 11, 0, 11, 1, 750, True),
            (10, 0, None, 1, 11, 1, 750, True),
            (65520, 31, 65520, 0, 0, 0, 750, True),
            (10, 0, 11, 0, 11, 1, 2750, False),
            (10, 0, 12, 0, 12, 1, 750, False),
            (10, 0, 11, 0, 11, 2, 750, False),
        )
        for start_revision, start_ack, first_revision, first_ack, next_revision, next_ack, when, valid in cases:
            with self.subTest(first_revision=first_revision, first_ack=first_ack, next_revision=next_revision,
                              next_ack=next_ack, when=when):
                self.pull = ArrivalPull(self.dispatcher, self.foreground)
                self.foreground.reset_mock()
                self.step(1, 0, revision=start_revision, ack=start_ack)
                self.step(2, 250, revision=start_revision, ack=start_ack)
                self.assertIn('出现可攻击目标', self.step(3, 500, revision=first_revision, ack=first_ack,
                                                         target='ON', range_blocked=True))
                fields = dict(revision=next_revision, ack=next_ack, target='ON', range_blocked=True)
                self.step(4, when, **fields)
                first = self.step(5, 8500, **fields)
                self.step(5, 8750, **fields)
                self.foreground.pulse.assert_not_called()
                second = self.step(6, 9000, **fields)
                if valid:
                    self.assertIsNone(first)
                    self.assertIn('已请求重选一次', second)
                    self.foreground.pulse.assert_called_once_with(10, 9, 35, (87, 65, 68, 9))
                else:
                    self.assertIn('尚未进入战斗', first)
                    self.assertIsNone(second)
                    self.foreground.pulse.assert_not_called()

    def test_camp_retarget_waits_for_a_new_window_after_a_pause(self):
        for pause, can_input in (({'allow_retarget': False}, True), ({'ready': False}, True),
                                 ({'moving': True}, True), ({}, False)):
            with self.subTest(pause=pause, can_input=can_input):
                self.pull = ArrivalPull(self.dispatcher, self.foreground)
                self.foreground.reset_mock()
                self.foreground.can_input.return_value = True
                self.step(1, 0, revision=10)
                self.step(2, 250, revision=10)
                fields = dict(revision=11, target='ON', ack=1, range_blocked=True)
                self.assertIn('确认首次选怪', self.step(3, 500, **fields))
                self.foreground.can_input.return_value = can_input
                self.assertIsNone(self.step(4, 8500, **fields, **pause))

                self.foreground.can_input.return_value = True
                self.assertIsNone(self.step(5, 12_500, **fields))
                self.assertIsNone(self.step(6, 12_750, **fields))
                self.foreground.pulse.assert_not_called()
                self.assertIsNone(self.step(7, 20_500, **fields))
                self.assertIsNone(self.step(7, 20_750, **fields))
                self.assertIn('已请求重选一次', self.step(8, 21_000, **fields))
                self.foreground.pulse.assert_called_once_with(10, 9, 35, (87, 65, 68, 9))

    def test_camp_retargets_an_acknowledged_target_while_a_buff_is_suppressed(self):
        self.step(1, 0, revision=10)
        self.step(2, 250, revision=10)
        fields = dict(revision=11, target='ON', ack=1, range_blocked=True, status='suppressed')
        self.assertIn('确认首次选怪', self.step(3, 500, **fields))
        self.step(4, 8500, **fields)
        self.step(4, 8750, **fields)
        self.foreground.pulse.assert_not_called()
        self.assertIn('已请求重选一次', self.step(5, 9000, **fields))
        self.foreground.pulse.assert_called_once_with(10, 9, 35, (87, 65, 68, 9))

    def test_no_first_pull_without_recovery_or_while_original_target_gate_is_active(self):
        self.step(1, 0, ready=False)
        self.step(2, 250, ready=False)
        self.step(3, 500, gate=1)
        self.step(4, 750, gate=1)
        self.step(5, 1000, x=42)
        self.step(6, 1250, x=42)
        self.foreground.can_input.return_value = False
        self.step(7, 1500)
        self.step(8, 1750)
        self.dispatcher.dispatch.assert_not_called()

    def test_retries_only_twice_and_stops_if_selected_target_never_enters_combat(self):
        self.step(1, 0)
        self.assertIn('已发出', self.step(2, 250))
        self.step(3, 1000)
        self.step(4, 2250)
        self.assertIn('已发出', self.step(5, 2500))
        self.assertIn('已暂停重试', self.step(6, 4500))
        self.step(7, 5000)
        self.assertEqual(self.dispatcher.dispatch.call_count, 2)
        self.assertFalse(self.pull.empty)

        self.pull = ArrivalPull(self.dispatcher, self.foreground)
        self.step(1, 0)
        self.step(2, 250)
        self.assertIn('出现可攻击目标', self.step(3, 500, target='ON'))
        self.assertIn('尚未进入战斗', self.step(4, 8500, target='ON'))
        self.assertEqual(self.dispatcher.dispatch.call_count, 3)

    def test_empty_camp_requires_a_game_acknowledgement(self):
        self.step(1, 0)
        self.step(2, 250)
        self.step(3, 750, ack=1)
        self.step(4, 2250, ack=1)
        self.step(5, 2500, ack=1)
        self.assertIn('已暂停重试', self.step(6, 4500, ack=2))
        self.assertTrue(self.pull.empty)
        self.step(7, 49_400, ack=2)
        self.step(8, 49_500, ack=2)
        self.step(8, 49_600, ack=2)
        self.assertEqual(self.dispatcher.dispatch.call_count, 2)
        self.assertIn('已发出', self.step(9, 49_700, ack=2))

    def test_unconfirmed_second_stationary_attempt_keeps_the_camp(self):
        self.step(1, 0)
        self.step(2, 250)
        self.step(3, 2250, ack=1)
        self.step(4, 2500, ack=1)
        self.assertIn('已暂停重试', self.step(5, 4500, ack=1))
        self.assertFalse(self.pull.empty)


class WalkingRouteTests(unittest.TestCase):
    def test_quest_cross_map_requires_a_connected_exit_and_a_confirmed_crossing(self):
        from wowbuddy.engine.character_state import QuestTurnInPin
        from wowbuddy.automation.manual_routes import ManualRoute, parse_manual_connection
        from wowbuddy.automation.walking_route import plan_quest_approach

        character = CharacterState('alive', True, True, 'horde', 16, 1411, '杜隆塔尔', 40, 50)
        position = NavigationState('alive', 1, 1411, 40, 50, 0, 3499, 2333, (87, 65, 68))
        pin = QuestTurnInPin(193, 1413, 45, 44)
        crossing = parse_manual_connection('WBDROUTE1|1411|4000,5000|4300,5200\nWBDROUTE1|1413|3900,3900|4200,4200')
        disconnected = ManualRoute(1413, ((42.1, 42), (45, 44)))
        self.assertIsNone(plan_quest_approach(1, pin, position, character,
                                             routes=(disconnected,), connections=(crossing,)))
        road = ManualRoute(1413, ((42, 42), (45, 44)))
        trip = plan_quest_approach(1, pin, position, character, routes=(road,), connections=(crossing,))
        next_point, _ = trip.observe(position)
        self.assertEqual((next_point.map_id, next_point.x, next_point.y), (1411, 43, 52))
        arriving = replace(position, map_id=1413, x=39, y=39, sequence=2)
        self.assertIsNone(trip.observe(arriving)[0])
        trip.observe(replace(arriving, sequence=3))
        next_point, _ = trip.observe(replace(arriving, sequence=4))
        self.assertEqual((next_point.map_id, next_point.x, next_point.y), (1413, 42, 42))
        self.assertFalse(trip.complete)

    def test_quest_trip_joins_a_marked_road_and_requires_the_correct_map_and_endpoint(self):
        from wowbuddy.engine.character_state import QuestTurnInPin
        from wowbuddy.automation.manual_routes import ManualRoute
        from wowbuddy.automation.walking_route import plan_quest_approach

        character = CharacterState('alive', True, True, 'alliance', 16, 52, '西部荒野', 32, 36)
        position = NavigationState('alive', 1, 52, 32, 36, 0, 3499, 2333, (87, 65, 68))
        pin = QuestTurnInPin(193, 52, 41.23, 56.78)
        road = ManualRoute(52, ((32, 36), (34, 40), (39, 55), (41.23, 56.78)))
        self.assertIsNone(plan_quest_approach(1, pin, position, character))
        self.assertIsNone(plan_quest_approach(1, replace(pin, map_id=1436), position, character, routes=(road,)))
        self.assertIsNone(plan_quest_approach(1, pin, replace(position, y=35), character, routes=(road,)))
        trip = plan_quest_approach(1, pin, position, character, routes=(road,))
        for i, point in enumerate(road.points[1:], 2):
            destination, _ = trip.observe(position)
            self.assertEqual((destination.x, destination.y), point)
            position = replace(position, x=point[0], y=point[1], sequence=i)
        self.assertEqual(trip.observe(position)[0], trip.goal)
        self.assertTrue(trip.complete and trip.goal.contains(position))

    def test_redridge_triangle_keeps_both_directions_on_the_road(self):
        redridge, elwynn, duskwood = 1433, 1429, 1431
        road_bend = [(12.15, 69.33), (11.45, 69.6), (10.55, 70.06), (9.6, 70.57)]

        def trip_to(goal, position):
            legs = plan_walking_route(position.map_id, goal.map_id, 21, goal.life)
            return WalkingTrip(1, legs, goal, level=21)

        def follow(trip, position):
            points = []
            for _ in range(60):
                point, _ = trip.observe(position)
                if point is None or point == trip.goal:
                    return points
                points.append(point)
                position = replace(position, x=point.x, y=point.y, sequence=position.sequence + 1)
            self.fail('路线没有到达边界或目标')

        def check_bend(points, expected):
            locations = [(point.x, point.y) for point in points]
            index = locations.index(expected[0])
            self.assertEqual(locations[index:index + len(expected)], expected)
            self.assertTrue(all(point.radius == 2 and not point.allow_detour
                                for point in points[index:index + len(expected)]))
            self.assertNotIn((10.1, 70.8), locations)

        fish = NavigationState('alive', 1, redridge, 30.55, 57.1, 0, 2171, 1448, (87, 65, 68))
        west = MapDestination(elwynn, 90, 73, 'alive', '艾尔文森林')
        west_trip = trip_to(west, fish)
        check_bend(follow(west_trip, fish), road_bend)
        arrived = replace(fish, map_id=elwynn, x=94, y=73, sequence=100)
        self.assertEqual(west_trip.observe(arrived), (None, None))
        self.assertIn('确认进入艾尔文森林', west_trip.observe(replace(arrived, sequence=101))[1])

        ghost = replace(arrived, life='ghost', sequence=1, width=3471, height=2315)
        corpse = MapDestination(redridge, fish.x, fish.y, 'ghost', '尸体')
        east_trip = trip_to(corpse, ghost)
        east_trip.observe(ghost)
        entry = replace(fish, life='ghost', x=0.3, y=73.2, sequence=2)
        self.assertEqual(east_trip.observe(entry), (None, None))
        self.assertIn('确认进入赤脊山', east_trip.observe(replace(entry, sequence=3))[1])
        check_bend(follow(east_trip, replace(entry, sequence=4)), road_bend[::-1])
        self.assertTrue(east_trip.complete)

        south = MapDestination(duskwood, 98, 4, 'alive', '暮色森林')
        fork = replace(fish, x=14.5, y=70.0)
        check_bend(follow(trip_to(south, fork), fork),
                   [(12.15, 69.33), (11.49, 70.03), (10.92, 71.12), (10.58, 72.12)])

    def test_redridge_to_westfall_joins_the_east_road_after_entering_elwynn(self):
        redridge, elwynn, westfall = 1433, 1429, 1436
        goal = MapDestination(westfall, 51.66, 77.21, 'alive', '匕首岭')
        trip = WalkingTrip(1, plan_walking_route(redridge, westfall, 18, 'alive'), goal, level=18)
        arrival = NavigationState('alive', 1, elwynn, 90.3, 73.7, 0, 3471, 2315, (87, 65, 68))
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertIn('确认进入艾尔文森林', trip.observe(replace(arrival, sequence=2))[1])

        position = replace(arrival, sequence=3)
        join, _ = trip.observe(position)
        self.assertAlmostEqual(join.x, 90.30, places=2)
        self.assertAlmostEqual(join.y, 73.57, places=2)
        position = replace(position, sequence=4, x=join.x, y=join.y)
        for expected in ((90.15, 73.57), (89.47, 73.73), (87.95, 73.91), (87.47, 74.20),
                         (86.96, 74.19), (86.57, 73.89), (85.25, 73.92), (84.05, 74.38), (83.12, 74.41),
                         (82.25, 74.1), (81.3, 73.86), (79.6, 73.82), (78.92, 73.62),
                         (78.05, 72.91), (77.35, 72.6)):
            point, _ = trip.observe(position)
            self.assertEqual((point.x, point.y), expected)
            position = replace(position, sequence=position.sequence + 1, x=point.x, y=point.y)
        self.assertEqual(trip.goal, goal)

    def test_elwynn_eastbound_follows_the_measured_road_inside_the_fence(self):
        elwynn, redridge = 1429, 1433
        goal = MapDestination(redridge, 23.25, 79.41, 'alive', '偷猎者营地')
        trip = WalkingTrip(1, plan_walking_route(elwynn, redridge, 18, 'alive'), goal, level=18)
        position = NavigationState('alive', 1, elwynn, 86.5739, 73.8924, 4.8, 3471, 2315, (87, 65, 68))
        for expected in ((86.96, 74.19), (87.47, 74.20), (87.95, 73.91), (89.47, 73.73)):
            point, _ = trip.observe(position)
            self.assertEqual((point.x, point.y), expected)
            self.assertEqual(point.radius, 2)
            self.assertFalse(point.allow_detour)
            position = replace(position, sequence=position.sequence + 1, x=point.x, y=point.y)

    def test_elwynn_eastern_road_rejoins_from_the_observed_westbound_stall(self):
        elwynn, westfall, redridge = 1429, 1436, 1433
        start = (77.848, 73.0471)
        position = NavigationState('alive', 1, elwynn, *start, 0, 3471, 2315, (87, 65, 68))
        for destination, expected in ((westfall, [(78.05, 72.91), (77.35, 72.6), (76.4, 72.37)]),
                                      (redridge, [(78.05, 72.91), (78.92, 73.62), (79.6, 73.82)])):
            with self.subTest(destination=destination):
                goal = MapDestination(destination, 30, 55, 'alive', '')
                trip = WalkingTrip(1, plan_walking_route(elwynn, destination, 18, 'alive'), goal, level=18)
                sample = position
                for xy in expected:
                    point, _ = trip.observe(sample)
                    self.assertEqual((point.x, point.y), xy)
                    sample = replace(sample, sequence=sample.sequence + 1, x=point.x, y=point.y)

    def test_redridge_graveyard_ghost_uses_observed_turn_to_poacher_corpse(self):
        from wowbuddy.automation.walking_route import camp_access_road

        origin = NavigationState('ghost', 1, 1433, 18.45, 58.12, 0, 2171, 1448, (87, 65, 68))
        corpse = MapDestination(1433, 23.17, 79.31, 'ghost', '尸体')
        road = camp_access_road(corpse, origin=origin)
        self.assertEqual(road[0], (18.45, 58.12))
        self.assertEqual(road[-1], (23.29, 76.47))
        self.assertFalse(camp_access_road(replace(corpse, x=32, y=55), origin=origin))
        self.assertFalse(camp_access_road(corpse, origin=replace(origin, x=30, y=82)))

        trip = WalkingTrip(1, (), corpse, camp_road=road)
        position = origin
        visited = []
        for _ in range(len(road)):
            waypoint, _ = trip.observe(position)
            if waypoint == corpse:
                break
            self.assertEqual(trip.observe(position)[0], waypoint)
            visited.append(waypoint)
            position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)
        turn = [item for item in visited if 69.5 <= item.y <= 70.7]
        self.assertEqual([(item.x, item.y) for item in turn],
                         [(21.79, 69.5), (21.86, 69.9), (22.08, 69.84),
                          (22.33, 69.83), (22.49, 69.85), (22.64, 70.7)])
        self.assertTrue(all(item.radius == 2 and item.allow_detour for item in turn))
        self.assertEqual(waypoint, corpse)
        self.assertTrue(trip.complete)

    def test_elwynn_east_bend_stays_on_the_shared_road_in_both_directions(self):
        elwynn = 1429
        west_end, east_end = (60.6, 72.62), (74.1, 72.6)
        bend = [(62.15, 72.90), (63.10, 73.55), (64.10, 73.93), (65.20, 74.08),
                (66.80, 73.99), (67.60, 73.36), (68.40, 72.25), (69.10, 71.39),
                (70.10, 71.08), (70.95, 71.35), (71.90, 72.15), (72.70, 72.71)]
        for start, end, map_id, expected in ((west_end, east_end, 1433, bend),
                                              (east_end, west_end, 1436, bend[::-1])):
            with self.subTest(map_id=map_id):
                legs = plan_walking_route(elwynn, map_id, 18, 'alive', origin=start)
                trip = WalkingTrip(1, legs, MapDestination(map_id, 30, 55, 'alive', ''), level=18)
                position = NavigationState('alive', 1, elwynn, *start, 0, 3471, 2315, (87, 65, 68))
                for xy in (*expected, end):
                    waypoint, _ = trip.observe(position)
                    self.assertEqual((waypoint.x, waypoint.y), xy)
                    self.assertEqual(trip.observe(position)[0], waypoint)
                    position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)

    def test_elwynn_crossing_keeps_the_westfall_bridge_and_sentinel_bend(self):
        elwynn, westfall = 1429, 1436
        goal = MapDestination(westfall, 51.66, 77.21, 'alive', '匕首岭')
        legs = plan_walking_route(elwynn, westfall, 18, 'alive')
        trip = WalkingTrip(1, legs, goal, level=18)
        keys = (87, 65, 68)
        position = NavigationState('alive', 1, elwynn, 20.99, 79.31, 0, 3471, 2315, keys)
        waypoint, _ = trip.observe(position)
        self.assertEqual((waypoint.x, waypoint.y), (20.72, 79.61))
        self.assertEqual((waypoint.radius, waypoint.allow_detour), (2, False))

        arrival = NavigationState('alive', 2, westfall, 62.32, 17.10, 0, 3500, 2333, keys)
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertIn('已确认进入西部荒野', trip.observe(replace(arrival, sequence=3))[1])
        position = replace(arrival, sequence=4)
        points = []
        for _ in range(65):
            waypoint, _ = trip.observe(position)
            if trip.complete:
                break
            points.append(waypoint)
            position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)
        self.assertEqual(waypoint, goal)
        self.assertTrue(trip.complete)
        self.assertEqual([(p.x, p.y) for p in points[:4]],
                         [(62.26, 17.18), (61.94, 17.62), (61.6, 18.05), (61.25, 18.42)])
        bend = [p for p in points if 41.8 <= p.y <= 45.0]
        self.assertEqual([(p.x, p.y) for p in bend],
                         [(58.15, 41.85), (57.75, 43.08), (58.19, 44.05), (58.75, 44.96)])
        self.assertTrue(all((p.radius, p.allow_detour) == (2, False) for p in points[:4] + bend))

        south_fork = [p for p in points if 64.4 <= p.y < 66 and 56.25 <= p.x <= 57.75]
        self.assertIn((57.62, 65.23), [(p.x, p.y) for p in south_fork])
        self.assertIn((57.08, 65.74), [(p.x, p.y) for p in south_fork])
        self.assertNotIn((57.33, 65.38), [(p.x, p.y) for p in south_fork])
        self.assertTrue(all((p.radius, p.allow_detour) == (2, False) for p in south_fork))

    def test_elwynn_westbound_resumes_from_the_measured_fence_collision(self):
        legs = plan_walking_route(1429, 1436, 18, 'alive')
        goal = MapDestination(1436, 51.66, 77.21, 'alive', '匕首岭')
        approach = (28.4, 78.1)
        east, west = (25.4056, 78.3621), (25.2468, 78.4324)
        recovery = ((25.2971, 78.0313), (25.3515, 78.1998))
        road = ((24.76, 78.62), (24.11, 78.66), (23.22, 78.42))
        for start, points in ((approach, (east, west) + road), ((25.1899, 78.1041), recovery + (west,) + road)):
            with self.subTest(start=start):
                trip = WalkingTrip(1, legs, goal, level=18)
                position = NavigationState('alive', 1, 1429, *start, 1.433, 3471, 2315, (87, 65, 68))
                for point in points:
                    waypoint, _ = trip.observe(position)
                    self.assertEqual((waypoint.x, waypoint.y), point)
                    self.assertFalse(waypoint.allow_detour)
                    self.assertEqual((waypoint.radius, waypoint.precision_stop),
                                     (1.25, True) if point not in road else (2, False))
                    position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)
                waypoint, _ = trip.observe(position)
                self.assertEqual((waypoint.x, waypoint.y), (22.2, 78.45))

        eastbound = WalkingTrip(1, plan_walking_route(1429, 1433, 18, 'alive'),
                               MapDestination(1433, 23.25, 79.41, 'alive', '赤脊山偷猎者营地'), level=18)
        position = NavigationState('alive', 1, 1429, 25.1899, 78.1041, 3.554, 3471, 2315, (87, 65, 68))
        for point in recovery + (east, approach):
            waypoint, _ = eastbound.observe(position)
            self.assertEqual((waypoint.x, waypoint.y), point)
            position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)

    def test_elwynn_eastbound_keeps_the_measured_southern_bend_past_the_obstacle(self):
        goal = MapDestination(1433, 23.25, 79.41, 'alive', '赤脊山偷猎者营地')
        trip = WalkingTrip(1, plan_walking_route(1429, 1433, 18, 'alive'), goal, level=18)
        position = NavigationState('alive', 1, 1429, 53.6, 72.6, 4.7, 3471, 2315, (87, 65, 68))
        for point in ((54.8065, 72.6292), (55.7516, 72.5913), (56.7244, 72.3673), (58.0, 71.9)):
            waypoint, _ = trip.observe(position)
            self.assertEqual((waypoint.x, waypoint.y), point)
            position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)

    def test_local_dagger_hills_approach_joins_the_road_near_the_live_fence(self):
        goal = MapDestination(1436, 51.66, 77.21, 'alive', '匕首岭')
        for x, y in ((58.1, 37.2), (57.6, 43.5)):
            with self.subTest(origin=(x, y)):
                position = NavigationState('alive', 1, 1436, x, y, 0, 3500, 2333, (87, 65, 68))
                road = camp_access_road(goal, origin=position)
                self.assertEqual(road[-1], (goal.x, goal.y))
                trip = WalkingTrip(1, (), goal, camp_road=road, level=18)
                waypoint, _ = trip.observe(position)
                self.assertTrue(57.7 <= waypoint.x <= 58.5)
                self.assertLess(abs(waypoint.y - y), 1.6)
                self.assertIn((58.75, 44.96), road)
                self.assertNotIn((62.26, 17.18), road)

    def test_lakeshire_camp_follows_the_bridge_from_the_north_bank(self):
        start = NavigationState('alive', 1, 1433, 23.0, 46.25, 0, 2171, 1448, (87, 65, 68))
        fish = MapDestination(1433, 30.55, 57.1, 'alive', '湖南岸鱼人区')
        road = camp_access_road(fish, origin=start)
        trip = WalkingTrip(1, (), fish, camp_road=road, level=18)
        at_inn = replace(start, x=21.8, y=44.7)
        point, notice = trip.observe(at_inn)
        self.assertIsNone(point)
        self.assertIn('尚未接入赤脊山', notice)
        self.assertEqual(trip.observe(at_inn), (None, None))
        point, _ = trip.observe(replace(start, sequence=2))
        bridge = []
        for sequence in range(3, len(road) + 4):
            if trip.complete:
                break
            if 48.7 <= point.y <= 57.0:
                bridge.append(point)
            point, _ = trip.observe(replace(start, sequence=sequence, x=point.x, y=point.y))
        self.assertEqual(point, fish)
        self.assertEqual(len(bridge), 11)
        self.assertTrue(all(point.radius == 2 and not point.allow_detour for point in bridge))

        at_west = replace(start, x=0.3, y=73.2)
        self.assertNotIn((27.5, 52.0), camp_access_road(fish, origin=at_west))
        corpse = replace(fish, life='ghost')
        self.assertEqual(camp_access_road(corpse, origin=replace(start, life='ghost')), road)

    def test_stormwind_wall_login_waits_for_a_safe_road_join(self):
        city, elwynn = 1453, 1429
        goal = MapDestination(elwynn, 42.1, 63.1, 'alive', '艾尔文森林')
        trip = WalkingTrip(1, plan_walking_route(city, elwynn, 18, 'alive'), goal, level=18)
        wall = NavigationState('alive', 1, city, 71.61, 72.25, 0, 1737.5, 1158.34, (87, 65, 68))
        point, notice = trip.observe(wall)
        self.assertIsNone(point)
        self.assertIn('暴风城', notice)
        self.assertEqual(trip.observe(wall), (None, None))
        point, notice = trip.observe(replace(wall, sequence=2))
        self.assertIsNone(point)
        self.assertIn('无法接入原陆路', notice)

        approach = replace(wall, sequence=3, x=65.8, y=80.8)
        point, _ = trip.observe(approach)
        self.assertEqual((point.x, point.y), (68.9, 82.5))
        self.assertFalse(trip.travel_exhausted)
        self.assertEqual((point.radius, point.allow_detour), (2, False))

    def test_hillsbrad_arathi_gate_uses_east_approach_and_ghost_return(self):
        lions = NavigationState('alive', 1, 1424, 60.983, 50.923, 0, 3200, 2133, (87, 65, 68))
        camp = MapDestination(1417, 23.663, 35.371, 'alive', '北侧迅猛龙区')
        self.assertIsNone(plan_walking_route(1424, 1417, 29, 'alive'))
        legs = plan_walking_route(1424, 1417, 30, 'alive', origin=(lions.x, lions.y))
        trip = WalkingTrip(1, legs, camp, level=30)
        point, _ = trip.observe(lions)
        self.assertEqual((point.x, point.y), (63.3, 46.0))
        gate = []
        for sequence in range(2, 45):
            if '的路口' in point.label:
                break
            if not point.allow_detour:
                gate.append(point)
            point, _ = trip.observe(replace(lions, sequence=sequence, x=point.x, y=point.y))
        self.assertGreater(point.x, 82.82)
        self.assertEqual((len(gate), gate[-1].x, gate[-1].y), (5, 82.61, 57.65))
        self.assertTrue(all(point.radius == 2 for point in gate))

        across = replace(lions, map_id=1417, sequence=45, x=20.017, y=29.27, width=3600, height=2400)
        self.assertEqual(trip.observe(across), (None, None))
        self.assertEqual(trip.observe(across), (None, None))
        self.assertIn('确认进入阿拉希高地', trip.observe(replace(across, sequence=46))[1])
        waypoint, _ = trip.observe(replace(across, sequence=47))
        self.assertEqual((waypoint.x, waypoint.y, waypoint.radius, waypoint.allow_detour), (20.09, 29.34, 2, False))

        corpse = MapDestination(1424, lions.x, lions.y, 'ghost', '尸体')
        reverse = WalkingTrip(1, plan_walking_route(1417, 1424, 0, 'ghost'), corpse)
        at_gate = replace(lions, life='ghost', x=82.70, y=57.706)
        self.assertEqual(reverse.observe(at_gate), (None, None))
        self.assertIn('确认进入希尔斯布莱德丘陵', reverse.observe(replace(at_gate, sequence=2))[1])
        visited = []
        point, _ = reverse.observe(replace(at_gate, sequence=3))
        for sequence in range(4, 45):
            if reverse.complete:
                break
            visited.append((point.x, point.y))
            point, _ = reverse.observe(replace(at_gate, sequence=sequence, x=point.x, y=point.y))
        self.assertEqual(point, corpse)
        self.assertIn((65.45, 42.15), visited)
        self.assertNotIn((62.5, 41.51), visited)

    def test_hillsbrad_east_camps_and_corpse_use_the_bridge(self):
        north = MapDestination(1424, 60.983, 50.923, 'alive', '北侧山地狮')
        south = MapDestination(1424, 58.522, 55.591, 'alive', '南侧山地狮')
        farm = NavigationState('alive', 1, 1424, 36.38, 39.77, 0, 3200, 2133, (87, 65, 68))
        road = camp_access_road(north, origin=farm)
        self.assertEqual(road[0], (farm.x, farm.y))
        self.assertIn((57.6, 36.55), road)
        trip = WalkingTrip(1, (), north, camp_road=road, level=27)
        point, _ = trip.observe(farm)
        bridge = []
        for sequence in range(2, len(road) + 3):
            if trip.complete:
                break
            if 62.5 <= point.x <= 63.31 and 41.51 <= point.y <= 41.76:
                bridge.append(point)
            point, _ = trip.observe(replace(farm, sequence=sequence, x=point.x, y=point.y))
        self.assertEqual(point, north)
        self.assertEqual(len(bridge), 6)
        self.assertTrue(all(point.radius == 2 and not point.allow_detour for point in bridge))

        at_north = replace(farm, x=north.x, y=north.y)
        local = camp_access_road(south, origin=at_north)
        self.assertEqual(local, ((north.x, north.y), (60.8, 53.8), (59.4, 54.8), (south.x, south.y)))
        corpse = MapDestination(farm.map_id, farm.x, farm.y, 'ghost', '尸体')
        self.assertEqual(camp_access_road(corpse, origin=replace(at_north, life='ghost')), road[::-1])

    def test_silverpine_hillsbrad_transition_and_farm_use_road_junctions(self):
        amber = NavigationState('alive', 1, 1421, 54.85, 54.4, 0, 4200, 2800, (87, 65, 68))
        bear = MapDestination(1424, 57.63, 23.63, 'alive', '灰熊区')
        legs = plan_walking_route(1421, 1424, 19, 'alive', origin=(amber.x, amber.y))
        trip = WalkingTrip(1, legs, bear, level=19)
        point, _ = trip.observe(amber)
        self.assertEqual((point.x, point.y), (54.643, 54.702))
        exit_waypoint = None
        for sequence in range(2, 29):
            if not point.allow_detour:
                exit_waypoint = point
                break
            point, _ = trip.observe(replace(amber, sequence=sequence, x=point.x, y=point.y))
        self.assertIsNotNone(exit_waypoint)
        self.assertGreater(exit_waypoint.x, 67.08)

        across = replace(amber, map_id=1424, x=13.82, y=46.12, width=3200, height=2133, sequence=30)
        self.assertEqual(trip.observe(across), (None, None))
        self.assertEqual(trip.observe(across), (None, None))
        self.assertIn('确认进入希尔斯布莱德丘陵', trip.observe(replace(across, sequence=31))[1])
        visited = []
        point, _ = trip.observe(replace(across, sequence=32))
        for sequence in range(33, 68):
            if trip.complete:
                break
            visited.append((point.x, point.y))
            point, _ = trip.observe(replace(across, sequence=sequence, x=point.x, y=point.y))
        self.assertEqual(point, bear)
        self.assertTrue(trip.complete)
        self.assertIn((32.5, 49.93), visited)
        self.assertIn((56.302, 26.484), visited)

        farm = MapDestination(1424, 36.82, 39.58, 'alive', '雇农区')
        at_bear = replace(across, x=bear.x, y=bear.y)
        farm_road = camp_access_road(farm, origin=at_bear)
        self.assertEqual((farm_road[0], farm_road[-1]), ((bear.x, bear.y), (farm.x, farm.y)))
        self.assertEqual(farm_road[1], (56.302, 26.484))
        self.assertIn((32.5, 49.93), farm_road)
        self.assertEqual(tuple(leg.destination for leg in plan_walking_route(1424, 1421, 0, 'ghost')), (1421,))

    def test_tirisfal_silverpine_border_waits_for_confirmation_and_amber_bridge_stays_narrow(self):
        source = NavigationState('alive', 1, 1420, 74.16, 62.79, 0, 4519, 3013, (87, 65, 68))
        wolves = MapDestination(1421, 54.88, 13.61, 'alive', '玛尔丁果园外')
        legs = plan_walking_route(1420, 1421, 12, 'alive', origin=(source.x, source.y))
        trip = WalkingTrip(1, legs, wolves, level=12)
        first, _ = trip.observe(source)
        self.assertEqual((first.x, first.y), (76.7, 62.4))
        across = replace(source, map_id=1421, x=67.33, y=5.0, width=4200, height=2800, sequence=2)
        self.assertEqual(trip.observe(across), (None, None))
        self.assertEqual(trip.observe(across), (None, None))
        self.assertIn('确认进入银松森林', trip.observe(replace(across, sequence=3))[1])
        self.assertEqual(tuple(trip.legs), ())
        reverse = plan_walking_route(1421, 1420, 0, 'ghost')
        self.assertEqual(tuple(leg.destination for leg in reverse), (1420,))

        amber = MapDestination(1421, 54.85, 54.4, 'alive', '安伯米尔外围')
        at_wolves = replace(across, x=wolves.x, y=wolves.y, sequence=1)
        road = camp_access_road(amber, origin=at_wolves)
        travel = WalkingTrip(2, (), amber, camp_road=road, level=15)
        point, _ = travel.observe(at_wolves)
        bridge = []
        for sequence in range(2, len(road) + 3):
            if travel.complete:
                break
            if 28.5 <= point.y <= 31.2:
                bridge.append(point)
            point, _ = travel.observe(replace(at_wolves, sequence=sequence, x=point.x, y=point.y))
        self.assertTrue(travel.complete)
        self.assertEqual(len(bridge), 4)
        self.assertTrue(all(point.radius == 2 and not point.allow_detour for point in bridge))

    def test_dun_morogh_tunnel_and_quarry_connect_to_starter_and_cross_zone_roads(self):
        start = NavigationState('alive', 1, 1426, 25.86, 78.26, 0, 4925, 3283, (87, 65, 68))
        grey = MapDestination(1426, 43.6, 49.6, 'alive', '灰色洞穴外')
        road = camp_access_road(grey, origin=start)
        self.assertEqual((road[0], road[-1]), ((25.86, 78.26), (43.6, 49.6)))
        trip = WalkingTrip(1, (), grey, camp_road=road, level=6)
        reached = []
        point, _ = trip.observe(start)
        for sequence in range(2, len(road) + 2):
            if trip.complete:
                break
            reached.append(point)
            point, _ = trip.observe(replace(start, x=point.x, y=point.y, sequence=sequence))
        self.assertTrue(trip.complete)
        tunnel = [waypoint for waypoint in reached if (waypoint.x, waypoint.y) in ((34.32, 70.95), (35.65, 65.79))]
        self.assertEqual([(waypoint.x, waypoint.y) for waypoint in tunnel], [(34.32, 70.95), (35.65, 65.79)])
        self.assertTrue(all(waypoint.radius == 2 and not waypoint.allow_detour for waypoint in tunnel))

        quarry = replace(start, x=70.67, y=56.64)
        loch = MapDestination(1432, 31.5, 72.1, 'alive', '碎石穴居人前哨')
        legs = plan_walking_route(1426, 1432, 12, 'alive', origin=(quarry.x, quarry.y))
        cross_zone = WalkingTrip(2, legs, loch, level=12)
        first, _ = cross_zone.observe(quarry)
        self.assertEqual((first.x, first.y), (69.65, 57.08))

    def test_new_starter_camp_roads_leave_through_the_valley_gate(self):
        cases = ((1429, (50.83, 37.92), (42.9, 86.56), (45.55, 46.8)),
                 (1411, (41.83, 65.81), (57.4, 56.4), (48.7, 68.35)),
                 (1411, (41.83, 65.81), (50.8, 48.8), (48.7, 68.35)))
        for map_id, start, end, gate in cases:
            with self.subTest(map_id=map_id, end=end):
                position = NavigationState('alive', 1, map_id, *start, 0, 3471, 2315, (87, 65, 68))
                goal = MapDestination(map_id, *end, 'alive', '新手区刷怪点')
                road = camp_access_road(goal, origin=position)
                self.assertIn(gate, road)
                self.assertEqual(camp_access_road(goal, origin=replace(position, map_id=1432)), ())
                self.assertEqual(camp_access_road(goal, origin=replace(position, x=60)), ())
                trip = WalkingTrip(1, (), goal, level=6, camp_road=road)
                visited = []
                for sequence in range(2, len(road) + 3):
                    waypoint, _ = trip.observe(position)
                    if waypoint == goal:
                        break
                    visited.append((waypoint.x, waypoint.y))
                    position = replace(position, sequence=sequence, x=waypoint.x, y=waypoint.y)
                self.assertEqual(visited, list(road))
                self.assertTrue(trip.complete)

    def test_teldrassil_camp_routes_use_the_bridge_and_both_graveyards(self):
        from wowbuddy.automation.walking_route import _TELDRASSIL_BRIDGE

        island = 1438
        west = MapDestination(island, 40.504, 55.571, 'alive', '西部营地')
        position = NavigationState('alive', 1, island, 53.628, 55.608, 0, 5092, 3394, (87, 65, 68))
        road = camp_access_road(west, origin=position)
        trip = WalkingTrip(1, (), west, camp_road=road)
        crossed = []
        for _ in range(len(road) + 2):
            target, _ = trip.observe(position)
            self.assertIsNotNone(target)
            if trip.complete:
                break
            point = target.x, target.y
            if point in _TELDRASSIL_BRIDGE:
                self.assertFalse(target.allow_detour)
                crossed.append(point)
            position = replace(position, sequence=position.sequence + 1, x=target.x, y=target.y)
        self.assertTrue(trip.complete)
        self.assertEqual(tuple(crossed), _TELDRASSIL_BRIDGE)

        grave = replace(position, life='ghost', x=56.217, y=63.289)
        road = camp_access_road(replace(west, life='ghost'), origin=grave)
        self.assertEqual(road[:2], ((56.217, 63.289), (55.671, 60.884)))
        self.assertEqual(tuple(point for point in road if point in _TELDRASSIL_BRIDGE), _TELDRASSIL_BRIDGE)
        grave = replace(position, life='ghost', x=58.713, y=42.329)
        corpse = MapDestination(island, 60.613, 46.26, 'ghost', '尸体')
        road = camp_access_road(corpse, origin=grave)
        self.assertEqual((road[0], road[-1]), ((58.713, 42.329), (60.613, 46.26)))
        self.assertIn((58.508, 45.665), road)

    def test_darnassus_east_gate_requires_fresh_gate_samples_and_rejoins_the_camp_road(self):
        from wowbuddy.automation.walking_route import _DARNASSUS_EAST_GATE, source_road_blocks

        forest, city = 1438, 1457
        forest_gate = _DARNASSUS_EAST_GATE[forest]
        city_gate = _DARNASSUS_EAST_GATE[city]
        legs = plan_walking_route(forest, city, 11, 'alive', faction='alliance')
        self.assertIsNone(plan_walking_route(forest, city, 11, 'alive', faction='horde'))
        self.assertIn(legs[0], source_road_blocks(forest, 55.8716, 89.336))
        camp = (39.91, 28.687)
        origin = NavigationState('alive', 1, forest, *camp, 0, 5092, 3394, (87, 65, 68))
        town_goal = MapDestination(city, *city_gate[-1], 'alive', '达纳苏斯东门')
        trip = WalkingTrip(1, legs, town_goal, level=11, faction='alliance')
        waypoints = []
        while len(waypoints) < 30:
            waypoint, _ = trip.observe(origin)
            self.assertIsNotNone(waypoint)
            point = waypoint.x, waypoint.y
            waypoints.append(point)
            if point in forest_gate:
                self.assertFalse(waypoint.allow_detour)
            if point == forest_gate[2]:
                break
            origin = replace(origin, x=point[0], y=point[1], sequence=origin.sequence + 1)
        self.assertIn((38.6, 51.9), waypoints)
        self.assertEqual(waypoints[-1], forest_gate[2])

        arrival = replace(origin, map_id=city, width=1058, height=706, x=city_gate[2][0], y=city_gate[2][1],
                          sequence=origin.sequence + 1)
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertEqual(trip.observe(replace(arrival, x=29.13, y=41.21, sequence=arrival.sequence+1)),
                         (None, None))
        arrival = replace(arrival, sequence=arrival.sequence + 2)
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertIn('已确认进入达纳苏斯', trip.observe(replace(arrival, sequence=arrival.sequence+1))[1])
        at = replace(arrival, sequence=arrival.sequence + 2)
        for _ in city_gate:
            waypoint, _ = trip.observe(at)
            if trip.complete:
                break
            self.assertFalse(waypoint.allow_detour)
            at = replace(at, x=waypoint.x, y=waypoint.y, sequence=at.sequence + 1)
        self.assertTrue(trip.complete)
        self.assertEqual(waypoint, town_goal)

        legs = plan_walking_route(city, forest, 10, 'alive', faction='alliance')
        self.assertIn(legs[0], source_road_blocks(city, 29.13, 41.21))
        camp_goal = MapDestination(forest, *camp, 'alive', '神谕林地')
        trip = WalkingTrip(2, legs, camp_goal, level=10, faction='alliance')
        origin = replace(arrival, x=town_goal.x, y=town_goal.y, sequence=1)
        first, _ = trip.observe(origin)
        self.assertEqual((first.x, first.y), city_gate[-2])
        entering = replace(origin, map_id=forest, width=5092, height=3394, x=forest_gate[2][0],
                           y=forest_gate[2][1], sequence=2)
        self.assertEqual(trip.observe(entering), (None, None))
        self.assertIn('已确认进入泰达希尔', trip.observe(replace(entering, sequence=3))[1])
        visited = []
        at = replace(entering, sequence=4)
        for _ in range(30):
            waypoint, _ = trip.observe(at)
            if trip.complete:
                break
            self.assertIsNotNone(waypoint)
            visited.append((waypoint.x, waypoint.y))
            at = replace(at, x=waypoint.x, y=waypoint.y, sequence=at.sequence + 1)
        self.assertTrue(trip.complete)
        self.assertIn((38.6, 51.9), visited)
        self.assertIn((39.5, 50.45), visited)
        self.assertEqual(waypoint, camp_goal)

    def test_darnassus_city_road_crosses_both_bridges_and_stops_short_of_the_portal(self):
        from wowbuddy.automation.walking_route import _DARNASSUS_CITY_ROAD, _DARNASSUS_EAST_GATE, _DARNASSUS_TREE_WAIT

        city, forest = 1457, 1438
        origin = NavigationState('alive', 1, city, *_DARNASSUS_EAST_GATE[city][-1], 0, 1058, 706, (87, 65, 68))
        wait = MapDestination(city, *_DARNASSUS_TREE_WAIT, 'alive', '树门前', radius=1.25)
        route = camp_access_road(wait, origin=origin)
        self.assertEqual(route, _DARNASSUS_CITY_ROAD[len(_DARNASSUS_EAST_GATE[city]) - 1:])
        trip = WalkingTrip(1, (), wait, level=12, camp_road=route, faction='alliance')
        visited = []
        for _ in route:
            waypoint, _ = trip.observe(origin)
            if trip.complete:
                break
            self.assertFalse(waypoint.allow_detour)
            visited.append((waypoint.x, waypoint.y))
            if (waypoint.x, waypoint.y) == _DARNASSUS_TREE_WAIT:
                self.assertTrue(waypoint.precision_stop)
                self.assertEqual(waypoint.arrival_radius, 1.25)
            origin = replace(origin, x=waypoint.x, y=waypoint.y, sequence=origin.sequence + 1)
        self.assertTrue(trip.complete)
        self.assertIn((51.05791, 40.42858), visited)
        self.assertIn((34.52247, 41.27876), visited)

        # 从城内过桥回营地时，不得从树门起点直穿湖面接东门。
        legs = plan_walking_route(city, forest, 10, 'alive', faction='alliance')
        goal = MapDestination(forest, 39.91, 28.687, 'alive', '神谕林地')
        trip = WalkingTrip(2, legs, goal, level=10, faction='alliance')
        waypoint, _ = trip.observe(origin)
        self.assertEqual((waypoint.x, waypoint.y), route[-2])

        # 进城后若用户标了东门附近的点，内置路线在该点接入，不会先走到树门。
        east = _DARNASSUS_EAST_GATE[city]
        legs = plan_walking_route(forest, city, 10, 'alive', faction='alliance')
        goal = MapDestination(city, *east[-1], 'alive', '城内路点')
        trip = WalkingTrip(3, legs, goal, level=10, camp_road=(east[-1],), catalog_goal=goal, faction='alliance')
        self.assertEqual(trip._camp_road, east)

    def test_ruttheran_portal_does_not_confuse_teldrassil_highland_with_the_harbor(self):
        from wowbuddy.automation.walking_route import (_DARNASSUS_EAST_GATE, _DARNASSUS_TREE_ENTRY, _DARNASSUS_TREE_WAIT,
                                           _RUTTHERAN_FLIGHT_ROAD)

        forest, city = 1438, 1457
        destination = _RUTTHERAN_FLIGHT_ROAD[-1]
        highland = 39.91, 28.687
        options = dict(faction='alliance', destination_xy=destination)
        legs = plan_walking_route(forest, forest, 12, 'alive', origin=highland, **options)
        self.assertEqual([(leg.source, leg.destination, leg.portal) for leg in legs],
                         [(forest, city, False), (city, forest, True)])
        self.assertEqual(plan_walking_route(city, forest, 12, 'alive', origin=_DARNASSUS_TREE_WAIT, **options),
                         (legs[-1],))
        self.assertEqual(plan_walking_route(city, forest, 12, 'alive', origin=_DARNASSUS_TREE_ENTRY, **options),
                         (legs[-1],))
        self.assertIsNone(plan_walking_route(city, forest, 12, 'alive', origin=(39, 67), **options))
        self.assertIsNone(plan_walking_route(forest, forest, 12, 'alive', origin=highland,
                                            destination_xy=(55, 95), faction='alliance'))

        goal = MapDestination(forest, *destination, 'alive', '鲁瑟兰飞行台', radius=1.25)
        trip = WalkingTrip(1, legs, goal, level=12, faction='alliance')
        at = NavigationState('alive', 1, forest, *highland, 0, 5092, 3394, (87, 65, 68))
        visited = []
        for _ in range(100):
            waypoint, notice = trip.observe(at)
            if notice == '已走完换图接入道路。':
                at = replace(at, sequence=at.sequence + 1)
                continue
            self.assertIsNotNone(waypoint)
            point = waypoint.x, waypoint.y
            visited.append((at.map_id, point))
            if at.map_id == forest and point == _DARNASSUS_EAST_GATE[forest][2]:
                entry = _DARNASSUS_EAST_GATE[city][2]
                at = replace(at, map_id=city, width=1058, height=706, x=entry[0], y=entry[1],
                             sequence=at.sequence + 1)
                self.assertEqual(trip.observe(at), (None, None))
                at = replace(at, sequence=at.sequence + 1)
                self.assertIn('进入达纳苏斯', trip.observe(at)[1])
            elif point == _DARNASSUS_TREE_ENTRY:
                self.assertTrue(waypoint.precision_stop)
                self.assertFalse(waypoint.allow_detour)
                break
            else:
                at = replace(at, x=point[0], y=point[1], sequence=at.sequence + 1)
        self.assertIn((city, _DARNASSUS_TREE_WAIT), visited)
        self.assertEqual(visited[-1], (city, _DARNASSUS_TREE_ENTRY))

        wrong = replace(at, map_id=forest, width=5092, height=3394, x=highland[0], y=highland[1],
                        sequence=at.sequence + 1)
        self.assertEqual(trip.observe(wrong), (None, None))
        self.assertEqual(trip.observe(replace(wrong, sequence=wrong.sequence+1)), (None, None))
        landing = replace(wrong, x=55.91761, y=89.72052, sequence=wrong.sequence + 2)
        self.assertEqual(trip.observe(landing), (None, None))
        self.assertEqual(trip.observe(landing), (None, None))
        self.assertIn('进入鲁瑟兰港', trip.observe(replace(landing, sequence=landing.sequence+1))[1])
        at = replace(landing, sequence=landing.sequence + 2)
        for _ in range(len(_RUTTHERAN_FLIGHT_ROAD) + 2):
            waypoint, _ = trip.observe(at)
            if trip.complete:
                break
            self.assertFalse(waypoint.allow_detour)
            at = replace(at, x=waypoint.x, y=waypoint.y, sequence=at.sequence + 1)
        self.assertTrue(trip.complete)
        self.assertEqual(waypoint, goal)
        self.assertTrue(goal.contains(at))

        trip = WalkingTrip(2, (legs[-1],), goal, level=12, faction='alliance')
        at = NavigationState('alive', 1, city, *_DARNASSUS_TREE_ENTRY, 0, 1058, 706, (87,65,68))
        waypoint, message = trip.observe(at, now_ms=1)
        self.assertIsNone(waypoint)
        self.assertIn('等待游戏确认切图', message)
        waypoint, message = trip.observe(replace(at, sequence=2), now_ms=8002)
        self.assertIsNone(waypoint)
        self.assertIn('暂无其他已核对的陆路', message)
        self.assertTrue(trip.travel_exhausted)

    def test_ruttheran_return_to_highland_walks_via_the_city_and_checks_the_landing(self):
        from wowbuddy.automation.walking_route import (_DARNASSUS_RETURN_LANDING, _RUTTHERAN_FLIGHT_ROAD,
                                           _RUTTHERAN_RETURN_ENTRY, source_road_blocks)

        forest, city = 1438, 1457
        harbor = _RUTTHERAN_FLIGHT_ROAD[-1]
        highland = 39.91, 28.687
        options = dict(faction='alliance', origin=harbor, destination_xy=highland)
        legs = plan_walking_route(forest, forest, 10, 'alive', **options)
        self.assertEqual([(leg.source, leg.destination, leg.portal) for leg in legs],
                         [(forest, city, True), (city, forest, False)])
        portal = legs[0]
        self.assertNotIn(portal, source_road_blocks(forest, *harbor))
        self.assertIn(portal, source_road_blocks(forest, *highland))
        self.assertIsNone(plan_walking_route(forest, forest, 10, 'alive', blocked_legs={portal}, **options))
        self.assertIsNone(plan_walking_route(forest, forest, 10, 'ghost', **options))
        self.assertIsNone(plan_walking_route(forest, forest, 10, 'alive', **(options | {'origin': (55, 95)})))
        goal = MapDestination(forest, *highland, 'alive', '高地营地')
        trip = WalkingTrip(1, legs, goal, level=10, faction='alliance')
        at = NavigationState('alive', 1, forest, *harbor, 0, 5092, 3394, (87, 65, 68))
        visited = []
        for _ in range(len(portal.points)):
            waypoint, _ = trip.observe(at)
            point = waypoint.x, waypoint.y
            visited.append(point)
            at = replace(at, x=point[0], y=point[1], sequence=at.sequence + 1)
            if point == _RUTTHERAN_RETURN_ENTRY:
                self.assertTrue(waypoint.precision_stop)
                self.assertFalse(waypoint.allow_detour)
                break
        self.assertEqual(visited, list(portal.points[1:]))

        wrong = replace(at, map_id=city, width=1058, height=706, x=75, y=40, sequence=at.sequence + 1)
        self.assertEqual(trip.observe(wrong), (None, None))
        landing = replace(wrong, x=_DARNASSUS_RETURN_LANDING[0], y=_DARNASSUS_RETURN_LANDING[1],
                          sequence=wrong.sequence + 1)
        self.assertEqual(trip.observe(landing), (None, None))
        self.assertEqual(trip.observe(landing), (None, None))
        at = replace(landing, sequence=landing.sequence + 1)
        self.assertIn('进入达纳苏斯', trip.observe(at)[1])
        self.assertIs(trip.arrival_connection, portal)
        self.assertIs(trip.legs[0], legs[1])
        self.assertEqual(trip.approach_road[-1], highland)

    def test_ruttheran_taxi_requires_fresh_hover_flight_and_ramp_receipts(self):
        from wowbuddy.engine.character_state import TaxiState
        from wowbuddy.automation.walking_route import _AUBERDINE_DESCENT_PROFILE, _RUTTHERAN_FLIGHT_ROAD

        harbor = _RUTTHERAN_FLIGHT_ROAD[-1]
        goal = MapDestination(1439, 38.953, 48.684, 'alive', '黑海岸练级营地')
        options = dict(faction='alliance', allow_taxi=True, destination_xy=(goal.x, goal.y))
        from_forest = plan_walking_route(1438, 1439, 12, 'alive', origin=(39.91, 28.687), **options)
        self.assertEqual([(leg.source, leg.destination) for leg in from_forest],
                         [(1438, 1457), (1457, 1438), (1438, 1439)])
        self.assertIsNone(plan_walking_route(1438, 1439, 11, 'alive', origin=harbor, **options))
        legs = plan_walking_route(1438, 1439, 12, 'alive', origin=harbor, **options)
        trip = WalkingTrip(1, legs, goal, level=12, faction='alliance')
        position = NavigationState('alive', 1, 1438, *harbor, 0, 5092, 3394, (87, 65, 68))
        send = Mock(return_value=True)
        reading = TaxiState(1, 1438, False, False, False, False, False, 'F7', 0x76, None)

        def step(at, data, now):
            return trip.observe(at, now_ms=now, taxi_reading=data, taxi_send=send)

        step(position, reading, 0)
        send.assert_called_once_with('select', 'F7')
        step(position, replace(reading, sequence=2, selected=True), 500)
        send.assert_called_with('interact', 0x76)
        panel = replace(reading, sequence=3, selected=True, panel_open=True, hovered=True, button=(2000, 7000))
        step(position, panel, 2100)
        send.assert_called_with('hover', (2000, 7000))
        step(position, panel, 2200)
        self.assertEqual(send.call_count, 3)
        step(position, replace(panel, sequence=4), 2300)
        send.assert_called_with('board', (2000, 7000))
        step(position, replace(panel, sequence=5), 11000)
        self.assertEqual([call.args[0] for call in send.call_args_list], ['select', 'interact', 'hover', 'board', 'close'])
        deck = replace(position, map_id=1439, x=36.3967, y=45.6172, width=6550, height=4367,
                       elevation=16.29, position_steps=1_000_000)
        ground = TaxiState(6, 1439, False, False, False, False, False, '', 0, None)
        self.assertEqual(step(deck, ground, 12000), (None, None))
        self.assertIn('确认登机', step(None, replace(ground, sequence=7, riding=True), 12200)[1])
        landed = replace(ground, sequence=8)
        self.assertEqual(step(replace(deck, elevation=8.75), landed, 39500), (None, None))
        self.assertEqual(step(deck, landed, 40000), (None, None))
        self.assertEqual(step(deck, landed, 40010), (None, None))
        entry, notice = step(replace(deck, sequence=2), replace(ground, sequence=9), 40200)
        self.assertIn('平台宽段', notice)
        self.assertFalse(entry.allow_detour)
        self.assertIsNotNone(entry.elevation_range)
        stop = replace(deck, sequence=3, x=entry.x, y=entry.y, elevation=15.67)
        self.assertIn('窄转角', step(stop, replace(ground, sequence=10), 40400)[1])
        self.assertEqual(step(replace(stop, sequence=4), replace(ground, sequence=11), 40600), (None, None))
        x, y, height = _AUBERDINE_DESCENT_PROFILE[-1]
        ramp = replace(deck, sequence=5, x=x, y=y, elevation=height)
        self.assertEqual(step(ramp, replace(ground, sequence=12, riding=True), 40800), (None, None))
        self.assertEqual(step(ramp, replace(ground, sequence=13), 41000), (None, None))
        self.assertEqual(step(ramp, replace(ground, sequence=13), 41200), (None, None))
        self.assertIn('落地并接入道路', step(replace(ramp, sequence=6), replace(ground, sequence=14), 41400)[1])
        self.assertFalse(trip.waiting_for_taxi)
        self.assertFalse(trip.complete)
        first, _ = trip.observe(replace(ramp, sequence=7))
        self.assertTrue(first.precision_stop)
        self.assertIsNotNone(first.elevation_range)

    def test_ruttheran_flight_failure_waits_for_panel_closure_then_chooses_a_land_route(self):
        from wowbuddy.engine.character_state import TaxiState
        from wowbuddy.automation.walking_route import WalkingLeg, _RUTTHERAN_FLIGHT_ROAD, _RUTTHERAN_TAXI

        harbor = _RUTTHERAN_FLIGHT_ROAD[-1]
        goal = MapDestination(1439, 38.953, 48.684, 'alive', '黑海岸练级营地')
        position = NavigationState('alive', 1, 1438, *harbor, 0, 5092, 3394, (87, 65, 68))
        panel = TaxiState(1, 1438, False, True, True, False, False, '', 0, None)
        road = WalkingLeg(1438, 1439, 12, (harbor, (58.6, 94)),
                          arrival_road=((38.5, 48), (goal.x, goal.y)), manual=True)
        for connections in ((), (road,)):
            with self.subTest(connections=bool(connections)):
                trip = WalkingTrip(1, (_RUTTHERAN_TAXI,), goal, level=12, faction='alliance', connections=connections)
                send = Mock(return_value=True)

                def step(sequence, now, **changes):
                    return trip.observe(position, now_ms=now, taxi_reading=replace(panel, sequence=sequence, **changes),
                                        taxi_send=send)

                step(1, 0)
                step(1, 1500)
                step(2, 1800, blocked=True)
                step(3, 2000)
                step(4, 3499)
                send.assert_not_called()
                self.assertIn('等待游戏确认飞行面板已关闭', step(5, 3500)[1])
                step(6, 4000)
                send.assert_called_once_with('close', None)
                self.assertFalse(trip.travel_exhausted)
                self.assertTrue(trip.waiting_for_taxi)
                step(7, 4100, panel_open=False, blocked=True)
                self.assertTrue(trip.waiting_for_taxi)
                self.assertIn('未确认可达', step(8, 4200, panel_open=False)[1])
                self.assertIn(_RUTTHERAN_TAXI, trip.excluded_legs)
                self.assertEqual(trip.travel_exhausted, not bool(connections))
                if connections:
                    self.assertEqual(tuple(trip.legs), (road,))
                    self.assertEqual(trip.goal, goal)
                else:
                    self.assertEqual(step(9, 5000, panel_open=False), (None, None))
                send.assert_called_once_with('close', None)

    def test_auberdine_reacquires_the_deck_at_the_last_flight_waypoint(self):
        from wowbuddy.engine.character_state import TaxiState

        goal = MapDestination(1439, 38.953, 48.684, 'alive', '黑海岸练级营地')
        trip = WalkingTrip.resume_auberdine(1, goal, level=12, faction='alliance')
        landing = NavigationState('alive', 1, 1439, 36.39804, 45.64006, 0, 6550, 4367,
                                  (87, 65, 68), position_steps=1_000_000, elevation=15.82)
        ground = TaxiState(1, 1439, False, False, False, False, False, '', 0, None)
        send = Mock()

        def step(sequence, *, elevation=15.82, riding=False):
            return trip.observe(replace(landing, sequence=sequence, elevation=elevation),
                                taxi_reading=replace(ground, sequence=sequence, riding=riding), taxi_send=send)

        self.assertEqual(step(1, elevation=17.74), (None, None))
        self.assertEqual(step(2), (None, None))
        self.assertEqual(step(2), (None, None))
        point, notice = step(3)
        self.assertIn('平台宽段', notice)
        self.assertEqual((point.x, point.y), (36.62086, 45.35114))
        self.assertFalse(point.allow_detour)

        self.assertEqual(step(4, elevation=8.75), (None, None))
        self.assertEqual(step(5), (None, None))
        self.assertEqual(step(6)[0], point)
        self.assertEqual(step(7, riding=True), (None, None))
        self.assertEqual(step(8), (None, None))
        self.assertEqual(step(9)[0], point)
        send.assert_not_called()

    def test_auberdine_lower_ramp_requires_elevation_and_keeps_small_steps(self):
        from wowbuddy.automation.walking_route import _AUBERDINE_DESCENT_PROFILE

        darkshore = 1439
        x, y, height = _AUBERDINE_DESCENT_PROFILE[-1]
        goal = MapDestination(darkshore, 38.953, 48.684, 'alive', '黑海岸练级营地')
        origin = NavigationState('alive', 1, darkshore, x, y, 0, 6550, 4367, (87,65,68),
                                 continuous=True, position_steps=1_000_000, elevation=height)
        self.assertEqual(camp_access_road(goal, origin=replace(origin, elevation=None)), ())
        self.assertEqual(camp_access_road(goal, origin=replace(origin, elevation=7)), ())
        road = camp_access_road(goal, origin=origin)
        self.assertEqual(road[:7], tuple((x, y) for x, y, _ in reversed(_AUBERDINE_DESCENT_PROFILE)))
        trip = WalkingTrip(1, (), goal, camp_road=road)
        first, _ = trip.observe(origin)
        self.assertEqual(first.arrival_radius, .65)
        self.assertFalse(first.allow_detour)
        navigator = MapNavigator(Mock())
        for position in (replace(origin, elevation=None), replace(origin, elevation=7),
                         replace(origin, position_steps=10_000)):
            self.assertFalse(first.has_elevation(position))
            self.assertIsNone(navigator.observe(1, 123, position, first, path=trip))
        navigator.movement.pulse.assert_not_called()
        self.assertEqual(trip.observe(replace(origin, x=first.x, y=first.y, sequence=2, elevation=7))[0], first)
        east, north = first.offset_from(origin)
        navigator.movement.keep_forward.return_value = False
        aligned = replace(origin, heading=math.atan2(-east, north), sequence=3)
        navigator.observe(1, 123, aligned, first, path=trip)
        self.assertLessEqual(navigator.movement.pulse.call_args.args[2], 85)
        navigator.movement.hold_forward.assert_not_called()

        heights = {(x, y): height for x, y, height in _AUBERDINE_DESCENT_PROFILE}
        at = replace(aligned, sequence=4)
        for _ in road:
            waypoint, _ = trip.observe(at)
            if trip.complete:
                break
            self.assertIsNotNone(waypoint)
            at = replace(at, x=waypoint.x, y=waypoint.y, sequence=at.sequence + 1,
                         elevation=heights.get((waypoint.x, waypoint.y)))
        self.assertTrue(trip.complete)

    def test_darkshore_river_corpse_uses_the_bridge_or_rejoins_from_the_west_bank(self):
        darkshore = 1439
        corpse = MapDestination(darkshore, 39.49, 71.58, 'ghost', '尸体')
        position = NavigationState('ghost', 1, darkshore, 39.95, 72.41, 0, 6550, 4367, (87, 65, 68))
        road = camp_access_road(corpse, origin=position)
        self.assertEqual(road[:3], ((39.95, 72.41), (39.1759, 72.8755), (39.1097, 72.76)))
        trip = WalkingTrip(1, (), corpse, camp_road=road)
        turn, _ = trip.observe(position)
        self.assertEqual((turn.x, turn.y), road[1])
        self.assertEqual(turn.arrival_radius, 1.25)
        self.assertTrue(turn.precision_stop)
        self.assertFalse(turn.allow_detour)
        up, _ = trip.observe(replace(position, x=turn.x, y=turn.y, sequence=2))
        self.assertEqual((up.x, up.y), road[2])
        self.assertFalse(up.allow_detour)

        lower = replace(position, x=39.58, y=72.72)
        self.assertEqual(camp_access_road(corpse, origin=lower)[1:3], ((39.186, 73.13), (39.1097, 72.9296)))
        stuck_at_tree = replace(position, x=39.2195, y=72.6538)
        escape = camp_access_road(corpse, origin=stuck_at_tree)
        self.assertEqual(escape[1:3], ((39.2, 72.755), road[2]))
        escape_trip = WalkingTrip(1, (), corpse, camp_road=escape)
        next_point, _ = escape_trip.observe(stuck_at_tree)
        self.assertEqual((next_point.x, next_point.y), escape[1])
        graveyard = replace(position, x=43.273, y=91.721)
        approach = camp_access_road(corpse, origin=graveyard)
        self.assertIn((41.3842, 75.374), approach)
        self.assertEqual(approach[-6:], ((41.1399, 73.1756), (40.8918, 72.6317), (40.6819, 72.3454),
                                         (39.8994, 71.5725), (39.796, 71.641), road[-1]))
        self.assertFalse(camp_access_road(corpse, origin=replace(position, map_id=1440)))
        self.assertFalse(camp_access_road(replace(corpse, life='alive'), origin=position))
        self.assertFalse(camp_access_road(replace(corpse, y=71.2), origin=position))

    def test_darkshore_camp_rotation_and_graveyard_use_the_south_road(self):
        from wowbuddy.automation.walking_route import (_DARKSHORE_BRIDGE_ROAD, _DARKSHORE_SOUTH_TIGER_ROAD,
                                             _DARKSHORE_SOUTH_TIGER_REJOIN, source_road_blocks)

        darkshore = 1439
        north = (39.8, 70.691)
        south = (38.315, 77.167)
        origin = NavigationState('alive', 1, darkshore, *north, 0, 6550, 4367, (87, 65, 68))
        goal = MapDestination(darkshore, *south, 'alive', '南侧猛虎')
        road = camp_access_road(goal, origin=origin)
        self.assertEqual(road[-len(_DARKSHORE_SOUTH_TIGER_ROAD):], _DARKSHORE_SOUTH_TIGER_ROAD)
        trip = WalkingTrip(1, (), goal, camp_road=road)
        crossed = []
        for _ in range(len(road) + 2):
            target, _ = trip.observe(origin)
            self.assertIsNotNone(target)
            if trip.complete:
                break
            point = target.x, target.y
            if point in _DARKSHORE_BRIDGE_ROAD:
                self.assertFalse(target.allow_detour)
                crossed.append(point)
            if point in _DARKSHORE_SOUTH_TIGER_ROAD[1:-1]:
                self.assertTrue(target.precision_stop)
                self.assertFalse(target.allow_detour)
            origin = replace(origin, sequence=origin.sequence + 1, x=target.x, y=target.y)
        self.assertTrue(trip.complete)
        self.assertEqual(tuple(crossed), _DARKSHORE_BRIDGE_ROAD)
        stopped = replace(origin, x=40.91, y=76.9)
        rejoined = camp_access_road(goal, origin=stopped)
        self.assertEqual(rejoined, _DARKSHORE_SOUTH_TIGER_REJOIN[1:] + _DARKSHORE_SOUTH_TIGER_ROAD[6:])

        graveyard = replace(origin, life='ghost', x=43.273, y=91.721)
        corpse = MapDestination(darkshore, 39.02, 77.15, 'ghost', '尸体')
        road = camp_access_road(corpse, origin=graveyard)
        self.assertEqual(road[:3], ((43.273, 91.721), (42.843, 91.179), (42.1, 90)))
        self.assertIn((40.57, 86), road)
        self.assertIn((41.45, 77), road)
        self.assertLess(math.hypot((road[-1][0] - corpse.x) * 65.5, (road[-1][1] - corpse.y) * 43.67), 15)
        self.assertFalse(source_road_blocks(darkshore, 43.28, 57.63))
        self.assertTrue(source_road_blocks(darkshore, 40.5, 74.3))
        town = replace(origin, x=37, y=44.1)
        camp = MapDestination(darkshore, 38.953, 48.684, 'alive', '奥伯丁南侧营地')
        road = camp_access_road(camp, origin=town)
        self.assertEqual(road[:2], ((37, 44.1), (37.506, 44.847)))
        self.assertIn((39.98, 48), road)
        self.assertEqual(road[-1], (camp.x, camp.y))

    def test_auberdine_harbor_ground_joins_town_without_admitting_the_flight_deck(self):
        from wowbuddy.automation.walking_route import _AUBERDINE_HARBOR_ROAD, darkshore_camp_origin

        darkshore = 1439
        ground = _AUBERDINE_HARBOR_ROAD[-1]
        self.assertTrue(darkshore_camp_origin(*ground))
        self.assertFalse(darkshore_camp_origin(36.3967, 45.6172))
        self.assertFalse(darkshore_camp_origin(36.68193, 45.15648))
        goal = MapDestination(darkshore, 38.953, 48.684, 'alive', '奥伯丁南侧营地')
        origin = NavigationState('alive', 1, darkshore, *ground, 0, 6550, 4367, (87, 65, 68))
        road = camp_access_road(goal, origin=origin)
        self.assertEqual(road[:len(_AUBERDINE_HARBOR_ROAD)], _AUBERDINE_HARBOR_ROAD[::-1])
        self.assertIn((39.98, 48), road)
        self.assertEqual(road[-1], (goal.x, goal.y))
        trip = WalkingTrip(1, (), goal, camp_road=road)
        for _ in road:
            waypoint, _ = trip.observe(origin)
            if trip.complete:
                break
            self.assertIsNotNone(waypoint)
            if (waypoint.x, waypoint.y) in _AUBERDINE_HARBOR_ROAD:
                self.assertFalse(waypoint.allow_detour)
            origin = replace(origin, sequence=origin.sequence + 1, x=waypoint.x, y=waypoint.y)
        self.assertTrue(trip.complete)

        origin = replace(origin, x=ground[0], y=ground[1])
        legs = plan_walking_route(darkshore, 1440, 22, 'alive', origin=ground, faction='alliance')
        goal = MapDestination(1440, 29.803, 19.749, 'alive', '灰谷北路营地')
        trip = WalkingTrip(2, legs, goal, level=22, faction='alliance')
        waypoint, _ = trip.observe(origin)
        self.assertEqual((waypoint.x, waypoint.y), _AUBERDINE_HARBOR_ROAD[-2])
        self.assertFalse(waypoint.allow_detour)

    def test_darkshore_crossing_uses_the_north_ashenvale_road_and_stays_out_of_the_east_network(self):
        darkshore, ash, barrens = 1439, 1440, 1413
        self.assertIsNone(plan_walking_route(darkshore, ash, 21, 'alive'))
        self.assertIsNone(plan_walking_route(darkshore, barrens, 27, 'alive'))
        self.assertIsNone(plan_walking_route(barrens, darkshore, 27, 'alive'))
        legs = plan_walking_route(darkshore, ash, 22, 'alive')
        goal = MapDestination(ash, 29.803, 19.749, 'alive', '北路营地')
        trip = WalkingTrip(1, legs, goal, level=22)
        departure = NavigationState('alive', 1, darkshore, 39.851, 90.339, 0, 6550, 4367, (87, 65, 68))
        target, _ = trip.observe(departure)
        self.assertEqual((target.x, target.y), (42.1, 90))
        entering = replace(departure, map_id=ash, x=29.217, y=13.83, width=5767, height=3844, sequence=2)
        self.assertEqual(trip.observe(entering), (None, None))
        self.assertEqual(trip.observe(entering), (None, None))
        self.assertIn('确认进入灰谷', trip.observe(replace(entering, sequence=3))[1])
        at = replace(entering, sequence=4)
        for _ in range(18):
            target, _ = trip.observe(at)
            if trip.complete:
                break
            self.assertIsNotNone(target)
            at = replace(at, x=target.x, y=target.y, sequence=at.sequence + 1)
        self.assertTrue(trip.complete)
        self.assertEqual(target, goal)
        alternate = MapDestination(ash, 27.094, 18.591, 'alive', '西侧营地')
        road = camp_access_road(alternate, origin=at)
        self.assertEqual(road, ((29.803, 19.749), (28.63, 19.1), (29, 18.1), (27.094, 18.591)))
        self.assertEqual(len(plan_walking_route(ash, darkshore, 0, 'ghost')), 1)

    def test_darkshore_crossing_rejoins_from_the_south_tiger_recovery_spur(self):
        from wowbuddy.automation.walking_route import (_DARKSHORE_SOUTH_TIGER_REJOIN, _DARKSHORE_SOUTH_TIGER_ROAD,
                                             _DARKSHORE_SOUTH_ROAD)

        darkshore, ash = 1439, 1440
        goal = MapDestination(ash, 29.803, 19.749, 'alive', '北路营地')
        for life, level in (('alive', 22), ('ghost', 0)):
            with self.subTest(life=life):
                start = _DARKSHORE_SOUTH_TIGER_REJOIN[0]
                position = NavigationState(life, 1, darkshore, *start, 0, 6550, 4367, (87, 65, 68))
                legs = plan_walking_route(darkshore, ash, level, life, origin=start, faction='alliance')
                trip = WalkingTrip(1, legs, replace(goal, life=life), level=level, faction='alliance')
                expected = (_DARKSHORE_SOUTH_TIGER_REJOIN[1:]
                            + _DARKSHORE_SOUTH_TIGER_ROAD[4:0:-1] + _DARKSHORE_SOUTH_ROAD[:2])
                for index, point in enumerate(expected):
                    target, _ = trip.observe(position)
                    self.assertIsNotNone(target)
                    self.assertEqual((target.x, target.y), point)
                    if index < len(expected) - 2:
                        self.assertTrue(target.precision_stop)
                        self.assertFalse(target.allow_detour)
                    position = replace(position, sequence=position.sequence + 1, x=target.x, y=target.y)

    def test_west_ashenvale_links_camps_and_same_map_corpse_along_the_road(self):
        ash = 1440
        camp = MapDestination(ash, 32.045, 43.145, 'alive', '山坡营地')
        origin = NavigationState('alive', 1, ash, 27.021, 26.203, 0, 5767, 3844, (87, 65, 68))
        road = camp_access_road(camp, origin=origin)
        self.assertEqual(road[:2], ((27.021, 26.203), (25.96, 25.6)))
        self.assertIn((25.55, 38.1), road)
        self.assertEqual(road[-3:], ((31.4, 47.18), (31.474, 44.043), (32.045, 43.145)))

        previous = replace(origin, x=camp.x, y=camp.y)
        next_camp = replace(camp, x=31.378, y=45.238)
        self.assertEqual(camp_access_road(next_camp, origin=previous),
                         ((32.045, 43.145), (31.474, 44.043), (31.4, 47.18), (31.378, 45.238)))
        corpse = MapDestination(ash, 32.05, 43.15, 'ghost', '尸体')
        recovery = camp_access_road(corpse, origin=replace(origin, life='ghost'))
        self.assertEqual(recovery, road)
        away = replace(origin, life='ghost', x=65.0, y=65.0)
        self.assertFalse(camp_access_road(corpse, origin=away))

    def test_morshan_crossing_joins_the_camp_road_after_two_map_frames(self):
        self.assertIsNone(plan_walking_route(1413, 1440, 22, 'alive'))
        self.assertEqual([leg.destination for leg in plan_walking_route(1411, 1440, 23, 'alive')], [1413, 1440])
        self.assertEqual([leg.destination for leg in plan_walking_route(1440, 1411, 0, 'ghost')], [1413, 1411])
        route = plan_walking_route(1413, 1440, 23, 'alive')
        goal = MapDestination(1440, 72.52, 69.5, 'alive', '营地')
        trip = WalkingTrip(1, route, goal, level=23)
        departure = NavigationState('alive', 1, 1413, 43.81, 48.17, 0, 10133, 6756, (87, 65, 68))
        target, _ = trip.observe(departure)
        self.assertEqual((target.x, target.y), route[0].approaches[0][0])
        crossing = replace(departure, map_id=1440, x=68.64, y=86.88, width=5767, height=3844, sequence=2)
        self.assertEqual(trip.observe(crossing), (None, None))
        self.assertEqual(trip.observe(crossing), (None, None))
        self.assertIn('已确认进入灰谷', trip.observe(replace(crossing, sequence=3))[1])
        road = camp_access_road(goal)
        self.assertEqual(road[-1], (72.18, 68.65))
        target, _ = trip.observe(replace(crossing, sequence=4))
        self.assertEqual((target.x, target.y), road[0])
        for sequence, (px, py) in enumerate(road, 5):
            target, _ = trip.observe(replace(crossing, x=px, y=py, sequence=sequence))
        self.assertEqual(target, goal)

    def test_west_ashenvale_to_eastern_camps_uses_narrow_bridges(self):
        ash = 1440
        origin = NavigationState('alive', 1, ash, 31.378, 45.238, 0, 5767, 3844, (87, 65, 68))
        bridges = ((33.947, 48.223), (37.3627, 53.4073), (63.5985, 70.0608))
        eastern_bridge = (79.4, 68.25)
        for camp in ((66.573, 70.074), (68.2, 69.161), (80.615, 68.224), (81.469, 69.206)):
            with self.subTest(camp=camp):
                expected = bridges + (eastern_bridge,) if camp[0] > eastern_bridge[0] else bridges
                goal = MapDestination(ash, *camp, 'alive', '狼群营地')
                road = camp_access_road(goal, origin=origin)
                self.assertEqual(road[-1], camp)
                trip = WalkingTrip(1, (), goal, camp_road=road)
                position = origin
                crossed = []
                for _ in range(len(road) + 2):
                    target, _ = trip.observe(position)
                    self.assertIsNotNone(target)
                    if trip.complete:
                        break
                    point = target.x, target.y
                    if point in expected:
                        self.assertFalse(target.allow_detour)
                        crossed.append(point)
                    position = replace(position, sequence=position.sequence + 1, x=target.x, y=target.y)
                self.assertTrue(trip.complete)
                self.assertEqual((position.x, position.y), camp)
                self.assertEqual(tuple(crossed), expected)

    def test_ashenvale_wolf_camps_use_the_fork_for_upgrade_and_rotation(self):
        ash, barrens = 1440, 1413
        east = MapDestination(ash, 68.2, 69.161, 'alive', '东侧狼群')
        west = MapDestination(ash, 66.573, 70.074, 'alive', '西侧狼群')
        old = NavigationState('alive', 1, ash, 72.52, 69.5, 0, 5767, 3844, (87, 65, 68))

        def follow(trip, position):
            for _ in range(30):
                target, _ = trip.observe(position)
                if trip.complete:
                    self.assertEqual(target, trip.goal)
                    return position
                self.assertIsNotNone(target)
                position = replace(position, sequence=position.sequence + 1, x=target.x, y=target.y)
            self.fail('路线未抵达营地')

        east_road = camp_access_road(east, origin=old)
        self.assertAlmostEqual(east_road[0][0], 72.18, delta=0.03)
        self.assertAlmostEqual(east_road[0][1], 68.65, delta=0.03)
        self.assertIn((68.32, 71.14), east_road)
        self.assertNotIn((67.05, 71.12), east_road)
        at_east = follow(WalkingTrip(1, (), east, camp_road=east_road), old)
        west_road = camp_access_road(west, origin=at_east)
        self.assertEqual(west_road[:2], ((68.2, 69.161), (68.41, 70.32)))
        self.assertIn((67.05, 71.12), west_road)
        at_west = follow(WalkingTrip(1, (), west, camp_road=west_road), at_east)

        route = plan_walking_route(barrens, ash, 27, 'alive')
        trip = WalkingTrip(1, route, east, level=27)
        crossing = replace(old, x=68.64, y=86.88)
        self.assertEqual(trip.observe(crossing), (None, None))
        self.assertIn('确认进入灰谷', trip.observe(replace(crossing, sequence=2))[1])
        follow(trip, replace(crossing, sequence=3))
        reverse = plan_walking_route(ash, barrens, 0, 'ghost')
        corpse = MapDestination(barrens, 50, 30, 'ghost', '尸体')
        target, _ = WalkingTrip(1, reverse, corpse).observe(replace(at_west, life='ghost'))
        self.assertEqual((target.x, target.y), (67.05, 71.12))

    def test_ashenvale_felfire_camps_connect_across_the_bridge_in_both_directions(self):
        ash, barrens = 1440, 1413
        near = MapDestination(ash, 80.615, 68.224, 'alive', '桥头营地')
        far = MapDestination(ash, 81.469, 69.206, 'alive', '东侧营地')
        wolf = NavigationState('alive', 1, ash, 68.2, 69.161, 0, 5767, 3844, (87, 65, 68))
        bridge = (79.4, 68.25)

        def follow(trip, position):
            visited = []
            for _ in range(45):
                target, _ = trip.observe(position)
                self.assertIsNotNone(target)
                if trip.complete:
                    self.assertEqual(target, trip.goal)
                    return visited, position
                point = target.x, target.y
                if point == bridge:
                    self.assertFalse(target.allow_detour)
                visited.append(point)
                position = replace(position, sequence=position.sequence + 1, x=target.x, y=target.y)
            self.fail('路线未抵达营地')

        road = camp_access_road(far, origin=wolf)
        points, at_far = follow(WalkingTrip(1, (), far, camp_road=road), wolf)
        self.assertEqual(points[0], (68.41, 70.32))
        self.assertLess(points.index((68.32, 71.14)), points.index(bridge))
        self.assertNotIn((67.05, 71.12), points)
        backtrack = camp_access_road(near, origin=at_far)
        points, _ = follow(WalkingTrip(1, (), near, camp_road=backtrack), at_far)
        self.assertEqual(points, [(near.x, near.y)])

        corpse_in_ashenvale = replace(near, life='ghost')
        ghost_road = camp_access_road(corpse_in_ashenvale, origin=replace(at_far, life='ghost'))
        self.assertEqual(ghost_road, ((far.x, far.y), (near.x, near.y)))

        legs = plan_walking_route(barrens, ash, 32, 'alive')
        trip = WalkingTrip(1, legs, near, level=32)
        crossing = replace(wolf, x=68.64, y=86.88)
        self.assertEqual(trip.observe(crossing), (None, None))
        self.assertIn('确认进入灰谷', trip.observe(replace(crossing, sequence=2))[1])
        points, _ = follow(trip, replace(crossing, sequence=3))
        self.assertIn(bridge, points)

        corpse = MapDestination(barrens, 50, 30, 'ghost', '尸体')
        reverse = WalkingTrip(1, plan_walking_route(ash, barrens, 0, 'ghost'), corpse)
        ghost = replace(at_far, life='ghost')
        target, _ = reverse.observe(ghost)
        self.assertEqual((target.x, target.y), (near.x, near.y))
        for point in ((near.x, near.y), (80.0, 68.39)):
            ghost = replace(ghost, x=point[0], y=point[1], sequence=ghost.sequence + 1)
            target, _ = reverse.observe(ghost)
        self.assertEqual((target.x, target.y), bridge)

    def test_alliance_talondeep_resumes_inside_the_cave_and_returns_to_ashenvale(self):
        from wowbuddy.automation.walking_route import _TALONDEEP_CAVES

        ash, stone, desolace = 1440, 1442, 1443
        sizes = {ash: (5767, 3844), stone: (4883, 3256), desolace: (4496, 2998)}
        camp = MapDestination(desolace, 59.928, 13.372, 'alive', '营地')
        corpse = MapDestination(ash, 80.615, 68.224, 'ghost', '尸体')

        def position(life, map_id, point, sequence=1):
            return NavigationState(life, sequence, map_id, *point, 0, *sizes[map_id], (87, 65, 68))

        def confirm(trip, arrival):
            self.assertEqual(trip.observe(arrival), (None, None))
            self.assertEqual(trip.observe(arrival), (None, None))
            arrival = replace(arrival, sequence=arrival.sequence + 1)
            self.assertIn('确认进入', trip.observe(arrival)[1])
            return replace(arrival, sequence=arrival.sequence + 1)

        def walk(trip, frame, until):
            visited = []
            for _ in range(180):
                target, _ = trip.observe(frame)
                if target is None:
                    self.assertFalse(trip.complete)
                    frame = replace(frame, sequence=frame.sequence + 1)
                    continue
                point = target.x, target.y
                if point in _TALONDEEP_CAVES.get(frame.map_id, ()):
                    self.assertFalse(target.allow_detour)
                    self.assertEqual(target.radius, 1.25)
                visited.append(point)
                if point == until:
                    return visited
                frame = position(frame.life, frame.map_id, point, frame.sequence + 1)
            self.fail('未到达路点')

        legs = plan_walking_route(ash, desolace, 35, 'alive', faction='alliance')
        self.assertEqual([leg.destination for leg in legs], [stone, desolace])
        self.assertEqual([leg.destination for leg in plan_walking_route(ash, desolace, 35, 'alive', faction='horde')],
                         [1413, stone, desolace])
        trip = WalkingTrip(1, legs, camp, level=35, faction='alliance')
        departure = position('alive', ash, (80.615, 68.224))
        cave_switch = 8
        visited = walk(trip, departure, _TALONDEEP_CAVES[ash][cave_switch])
        self.assertIn((44.16, 57.18), visited)
        entry = position('alive', stone, _TALONDEEP_CAVES[stone][cave_switch])
        arrival = confirm(trip, entry)
        visited = walk(trip, arrival, legs[1].points[-1])
        self.assertEqual(visited[0], _TALONDEEP_CAVES[stone][cave_switch + 1])
        self.assertIn(_TALONDEEP_CAVES[stone][-1], visited)
        restart = WalkingTrip(2, legs[1:], camp, level=35, faction='alliance')
        self.assertEqual(walk(restart, entry, legs[1].points[-1]), visited)
        final = confirm(trip, position('alive', desolace, legs[1].arrival_road[0]))
        walk(trip, final, (camp.x, camp.y))

        reverse_legs = plan_walking_route(desolace, ash, 0, 'ghost', faction='alliance')
        self.assertEqual([leg.destination for leg in reverse_legs], [stone, ash])
        reverse = WalkingTrip(3, reverse_legs, corpse, faction='alliance')
        visited = walk(reverse, position('ghost', desolace, (50.409, 62.913)), reverse_legs[0].points[-1])
        self.assertEqual(visited[0], (49.72, 63.714))
        arrival = confirm(reverse, position('ghost', stone, reverse_legs[0].arrival_road[0]))
        walk(reverse, arrival, _TALONDEEP_CAVES[stone][0])
        arrival = confirm(reverse, position('ghost', ash, _TALONDEEP_CAVES[ash][0]))
        visited = walk(reverse, arrival, (corpse.x, corpse.y))
        self.assertIn((44.16, 57.18), visited)
        self.assertNotIn(_TALONDEEP_CAVES[ash][-1], visited)

        cave_corpse = replace(corpse, map_id=stone, x=entry.x, y=entry.y)
        cave_road = camp_access_road(cave_corpse, origin=position('ghost', stone, (78.17, 42.93)))
        self.assertIn(_TALONDEEP_CAVES[stone][-1], cave_road)
        self.assertEqual(cave_road[-1], (cave_corpse.x, cave_corpse.y))

    def test_ashenvale_to_desolace_walks_the_three_crossings_and_camp_road(self):
        sizes = {1440: (5767, 3844), 1413: (10133, 6756), 1442: (4883, 3256), 1443: (4496, 2998)}
        near = (59.928, 13.372)
        far = (59.774, 24.319)
        crossings = {
            (1440, 1413): (48.18, 4.13),
            (1413, 1442): (84, 96.5),
            (1442, 1443): (54.3018, 2.9383),
            (1443, 1442): (29.771, 77.963),
            (1442, 1413): (34.8, 27.33),
            (1413, 1440): (68.64, 86.88),
        }

        def frame(life, sequence, map_id, point):
            return NavigationState(life, sequence, map_id, *point, 0, *sizes[map_id], (87, 65, 68))

        def walk(trip, position):
            visited = []
            while trip.legs:
                leg = trip.legs[0]
                for _ in range(80):
                    target, status = trip.observe(position)
                    if target is None:
                        self.assertIsNotNone(status)
                        position = replace(position, sequence=position.sequence + 1)
                        continue
                    visited.append((target.map_id, target.x, target.y))
                    position = frame(position.life, position.sequence + 1, target.map_id, (target.x, target.y))
                    if (target.x, target.y) == leg.points[-1]:
                        break
                else:
                    self.fail(f'未到达换图口 {leg.source} → {leg.destination}')
                position = frame(position.life, position.sequence + 1, leg.destination,
                                 crossings[leg.source, leg.destination])
                self.assertEqual(trip.observe(position), (None, None))
                self.assertEqual(trip.observe(position), (None, None))
                position = replace(position, sequence=position.sequence + 1)
                self.assertIn('确认进入', trip.observe(position)[1])
            for _ in range(48):
                position = replace(position, sequence=position.sequence + 1)
                target, _ = trip.observe(position)
                self.assertIsNotNone(target)
                if trip.complete:
                    self.assertEqual(target, trip.goal)
                    return visited
                visited.append((target.map_id, target.x, target.y))
                position = frame(position.life, position.sequence, target.map_id, (target.x, target.y))
            self.fail('未走完营地接入道路')

        self.assertIsNone(plan_walking_route(1440, 1443, 34, 'alive'))
        legs = plan_walking_route(1440, 1443, 35, 'alive')
        self.assertEqual([leg.destination for leg in legs], [1413, 1442, 1443])
        goal = MapDestination(1443, *far, 'alive', '凄凉之地中北部营地')
        points = walk(WalkingTrip(1, legs, goal, level=35), frame('alive', 1, 1440, (81.469, 69.206)))
        for point in ((1440, 79.4, 68.25), (1413, 43.85, 29.1), (1442, 42.795, 42.646), (1443, 60.664, 20.884)):
            self.assertIn(point, points)
        near_goal = MapDestination(1443, *near, 'alive', '凄凉之地北部营地')
        at_far = frame('alive', 1, 1443, far)
        road = camp_access_road(near_goal, origin=at_far)
        self.assertEqual(road, (far, (60.664, 20.884), near))

        reverse = plan_walking_route(1443, 1440, 0, 'ghost')
        self.assertEqual([leg.destination for leg in reverse], [1442, 1413, 1440])
        corpse = MapDestination(1440, 68.6, 85.3, 'ghost', '尸体')
        points = walk(WalkingTrip(2, reverse, corpse), frame('ghost', 1, 1443, far))
        self.assertIn((1443, 60.664, 20.884), points)
        self.assertEqual(points.count((1443, 53.5241, 5.5071)), 1)
        self.assertIn((1442, 42.795, 42.646), points)

    def test_desolace_central_camps_and_graveyard_use_the_same_corridor(self):
        north, central, east = (59.774, 24.319), (61.922, 44.567), (63.96, 45.64)
        map_id = 1443

        def frame(life, point):
            return NavigationState(life, 1, map_id, *point, 0, 4496, 2998, (87, 65, 68))

        north_camp = MapDestination(map_id, *north, 'alive', '北部营地')
        central_camp = MapDestination(map_id, *central, 'alive', '中部营地')
        east_camp = MapDestination(map_id, *east, 'alive', '东部营地')
        forward = camp_access_road(east_camp, origin=frame('alive', north))
        self.assertEqual((forward[0], forward[-2], forward[-1]), (north, central, east))
        self.assertIn((63.333, 39.497), forward)
        self.assertEqual(camp_access_road(north_camp, origin=frame('alive', east)), forward[::-1])
        self.assertEqual(camp_access_road(central_camp, origin=frame('alive', east)), (east, central))
        south = MapDestination(map_id, 62.723, 71.011, 'alive', '南部营地')
        further = camp_access_road(south, origin=frame('alive', east))
        self.assertEqual((further[0], further[-1]), (east, (south.x, south.y)))
        self.assertIn((63.183, 60.807), further)

        graveyard = frame('ghost', (50.409, 62.913))
        corpse = MapDestination(map_id, 63.99, 45.68, 'ghost', '尸体')
        road = camp_access_road(corpse, origin=graveyard)
        self.assertEqual((road[0], *road[-3:-1]), ((graveyard.x, graveyard.y), central, east))
        self.assertAlmostEqual(road[-1][1], corpse.y, places=2)
        south_corpse = replace(south, life='ghost', x=62.74, y=71.02)
        south_road = camp_access_road(south_corpse, origin=graveyard)
        self.assertLess(south_road.index(central), south_road.index((63.183, 60.807)))
        self.assertEqual(camp_access_road(east_camp, origin=replace(graveyard, life='alive')), ())
        self.assertEqual(camp_access_road(corpse, origin=frame('ghost', (32, 55))), ())
        position = graveyard
        trip = WalkingTrip(1, (), corpse, camp_road=road)
        for _ in range(len(road) + 2):
            target, _ = trip.observe(position)
            if trip.complete:
                self.assertEqual(target, corpse)
                break
            position = replace(position, sequence=position.sequence + 1, x=target.x, y=target.y)
        else:
            self.fail('跑尸未接回游戏上报的尸体坐标')

    def test_desolace_feralas_crossing_and_ghost_return_use_the_south_approach(self):
        desolace, feralas = 1443, 1444
        south = (61.166, 74.452)
        wolf = MapDestination(feralas, 44.503, 9.115, 'alive', '菲拉斯北部狼群')
        bear = MapDestination(feralas, 43.033, 9.689, 'alive', '菲拉斯北部铁鬃熊')
        sizes = {desolace: (4496, 2998), feralas: (6950, 4633)}

        def frame(life, map_id, point, sequence=1):
            return NavigationState(life, sequence, map_id, *point, 0, *sizes[map_id], (87, 65, 68))

        def cross(trip, origin, entry):
            leg = trip.legs[0]
            position = origin
            for _ in range(35):
                target, _ = trip.observe(position)
                self.assertIsNotNone(target)
                position = frame(position.life, target.map_id, (target.x, target.y), position.sequence + 1)
                if (target.x, target.y) == leg.points[-1]:
                    break
            else:
                self.fail('未到达换图口')
            position = frame(position.life, leg.destination, entry, position.sequence + 1)
            self.assertEqual(trip.observe(position), (None, None))
            self.assertEqual(trip.observe(position), (None, None))
            position = replace(position, sequence=position.sequence + 1)
            self.assertIn('确认进入', trip.observe(position)[1])
            visited = []
            for _ in range(35):
                position = replace(position, sequence=position.sequence + 1)
                target, _ = trip.observe(position)
                self.assertIsNotNone(target)
                if trip.complete:
                    self.assertEqual(target, trip.goal)
                    return visited
                visited.append((target.x, target.y))
                position = frame(position.life, target.map_id, (target.x, target.y), position.sequence)
            self.fail('未沿接入道路抵达')

        self.assertIsNone(plan_walking_route(desolace, feralas, 45, 'alive'))
        legs = plan_walking_route(desolace, feralas, 46, 'alive')
        self.assertEqual([leg.destination for leg in legs], [feralas])
        trip = WalkingTrip(1, legs, wolf, level=46)
        visited = cross(trip, frame('alive', desolace, south), (45.1, 2.5))
        self.assertIn((45.707, 5.252), visited)
        road = camp_access_road(bear, origin=frame('alive', feralas, (wolf.x, wolf.y)))
        self.assertEqual((road[0], road[-1]), ((wolf.x, wolf.y), (bear.x, bear.y)))

        corpse = MapDestination(desolace, *south, 'ghost', '尸体')
        reverse = WalkingTrip(2, plan_walking_route(feralas, desolace, 0, 'ghost'), corpse)
        visited = cross(reverse, frame('ghost', feralas, (bear.x, bear.y)), (42.3785, 96.3419))
        self.assertIn((45.449, 86.129), visited)
        self.assertNotIn((59.928, 13.372), visited)

    def test_alliance_felwood_corridor_joins_talondeep_in_both_directions(self):
        from wowbuddy.automation.walking_route import _TALONDEEP_CAVES, source_road_blocks

        feralas, desolace, stone, ash, felwood = 1444, 1443, 1442, 1440, 1448
        outgoing = plan_walking_route(feralas, felwood, 54, 'alive', faction='alliance')
        self.assertEqual([leg.destination for leg in outgoing], [desolace, stone, ash, felwood])
        self.assertIsNone(plan_walking_route(feralas, felwood, 54, 'alive', faction='alliance',
                                             blocked_legs={outgoing[2]}))
        incoming = plan_walking_route(felwood, feralas, 0, 'ghost', faction='alliance')
        self.assertEqual([leg.destination for leg in incoming], [ash, stone, desolace, feralas])

        junction, bridge = (60.694, 65.507), (63.5985, 70.0608)
        self.assertFalse(source_road_blocks(ash, 63.35, 49.8) & {incoming[1], outgoing[-1]})
        self.assertEqual(source_road_blocks(ash, 10, 50) & {incoming[1], outgoing[-1]},
                         {incoming[1], outgoing[-1]})

        def walk_ashenvale(trip, position, stop):
            visited = []
            for _ in range(120):
                target, _ = trip.observe(position)
                if target is not None:
                    self.assertEqual(target.map_id, ash)
                    visited.append((target.x, target.y))
                    if visited[-1] == stop:
                        return visited
                    position = replace(position, x=target.x, y=target.y)
                position = replace(position, sequence=position.sequence + 1)
            self.fail('未沿灰谷道路抵达下一处路口')

        goal = MapDestination(felwood, 51.775, 24.167, 'alive', '营地')
        trip = WalkingTrip(1, outgoing[-1:], goal, level=54, faction='alliance')
        entry = NavigationState('alive', 1, ash, 42.1908, 71.2824, 0, 5767, 3844, (87, 65, 68))
        visited = walk_ashenvale(trip, entry, outgoing[-1].points[-1])
        self.assertLess(visited.index((44.16, 57.18)), visited.index(junction))
        self.assertNotIn(bridge, visited)

        corpse = MapDestination(feralas, 44.461, 11.743, 'ghost', '尸体')
        reverse = WalkingTrip(2, incoming, corpse, faction='alliance')
        position = replace(entry, life='ghost', x=55.5, y=29.0)
        self.assertEqual(reverse.observe(position), (None, None))
        position = replace(position, sequence=2)
        self.assertIn('确认进入灰谷', reverse.observe(position)[1])
        visited = walk_ashenvale(reverse, replace(position, sequence=3), _TALONDEEP_CAVES[ash][-1])
        self.assertLess(visited.index(junction), visited.index((44.16, 57.18)))
        self.assertNotIn(bridge, visited)

    def test_feralas_to_felwood_walks_the_bridge_and_both_felwood_graveyards(self):
        ash, felwood = 1440, 1448
        camp = MapDestination(felwood, 51.775, 24.167, 'alive', '铁木森林营地')
        bridge = (63.5985, 70.0608)
        sizes = {ash: (5767, 3844), felwood: (5750, 3833)}

        def frame(life, map_id, xy, sequence=1):
            return NavigationState(life, sequence, map_id, *xy, 0, *sizes[map_id], (87, 65, 68))

        def follow(trip, position, entry=None):
            visited = []
            for _ in range(80):
                target, _ = trip.observe(position)
                self.assertIsNotNone(target)
                if trip.complete:
                    self.assertEqual(target, trip.goal)
                    return visited
                visited.append((target.x, target.y))
                if trip.legs and (target.x, target.y) == trip.legs[0].points[-1]:
                    position = frame(position.life, trip.legs[0].destination, entry, position.sequence + 1)
                    self.assertEqual(trip.observe(position), (None, None))
                    self.assertEqual(trip.observe(position), (None, None))
                    position = replace(position, sequence=position.sequence + 1)
                    self.assertIn('确认进入', trip.observe(position)[1])
                position = (frame(position.life, target.map_id, (target.x, target.y), position.sequence + 1)
                            if target.map_id == position.map_id else replace(position, sequence=position.sequence + 1))
            self.fail('未抵达目的地')

        self.assertIsNone(plan_walking_route(1444, felwood, 53, 'alive'))
        legs = plan_walking_route(1444, felwood, 54, 'alive')
        self.assertEqual([leg.destination for leg in legs], [1443, 1442, 1413, ash, felwood])
        trip = WalkingTrip(1, legs[-1:], camp, level=54)
        visited = follow(trip, frame('alive', ash, (67.05, 71.12)), (54.5461, 92.2609))
        self.assertIn(bridge, visited)
        self.assertIn((48.586, 27.061), visited)

        corpse = MapDestination(ash, 64.3, 70.45, 'ghost', '灰谷尸体')
        reverse = WalkingTrip(2, plan_walking_route(felwood, ash, 0, 'ghost'), corpse)
        visited = follow(reverse, frame('ghost', felwood, (54.116, 89.513)), (55.5, 29))
        self.assertIn(bridge, visited)

        corpse = MapDestination(felwood, 60.931, 8.449, 'ghost', '魔爪村尸体')
        for graveyard, junction in (((56.759, 87.036), (54.116, 89.513)),
                                    ((49.507, 31.052), (48.586, 27.061))):
            position = frame('ghost', felwood, graveyard)
            road = camp_access_road(corpse, origin=position)
            self.assertEqual(road[0], graveyard)
            self.assertIn(junction, road)
            self.assertIn(junction, follow(WalkingTrip(3, (), corpse, camp_road=road), position))

    def test_joining_built_in_road_mid_segment_continues_instead_of_backtracking(self):
        from wowbuddy.automation.walking_route import WalkingLeg

        leg = WalkingLeg(1435, 1419, 44, ((42, 20), (42, 22), (41, 24)))
        goal = MapDestination(1419, 55, 30, 'alive', '刷怪点')
        middle = NavigationState('alive', 1, 1435, 42, 20.5, 0, 2400, 1600, (87, 65, 68))
        target, _ = WalkingTrip(1, (leg,), goal, level=44).observe(middle)
        self.assertEqual((target.x, target.y), (42, 22))

        rejoin = WalkingTrip(2, (leg,), goal, level=44)
        target, _ = rejoin.observe(replace(middle, x=42.1))
        self.assertEqual((target.x, target.y), (42, 20.5))
        target, _ = rejoin.observe(replace(middle, sequence=2))
        self.assertEqual((target.x, target.y), (42, 22))

    def test_barrens_bridge_waits_for_new_map_before_following_the_other_approach(self):
        self.assertIsNone(plan_walking_route(1411, 1413, 11, 'alive'))
        map_sizes = {1411: (5287, 3525), 1413: (10133, 6756)}
        for source, target, life in ((1411, 1413, 'alive'), (1413, 1411, 'ghost')):
            with self.subTest(life=life):
                route = plan_walking_route(source, target, 12 if life == 'alive' else 0, life)
                self.assertEqual([leg.destination for leg in route], [target])
                road = route[0].arrival_road
                goal = MapDestination(target, 53.1, 30.4, life, '目标')
                trip = WalkingTrip(1, route, goal, level=12)
                departure = route[0].points
                position = NavigationState(life, 0, source, *departure[0], 0, *map_sizes[source], (87, 65, 68))
                for seq, (x, y) in enumerate(departure[:-1]):
                    waypoint, _ = trip.observe(replace(position, x=x, y=y, sequence=seq))
                    self.assertEqual((waypoint.map_id, waypoint.x, waypoint.y), (source, *departure[seq + 1]))
                arrived = NavigationState(life, 30, target, *road[0], 0, *map_sizes[target], (87, 65, 68))
                self.assertEqual(trip.observe(arrived), (None, None))
                self.assertEqual(trip.observe(arrived), (None, None))
                self.assertIn('已确认进入', trip.observe(replace(arrived, sequence=31))[1])
                waypoint, _ = trip.observe(replace(arrived, sequence=32))
                self.assertEqual((waypoint.map_id, waypoint.x, waypoint.y), (target, *road[1]))
                for seq, (x, y) in enumerate(road[1:], 33):
                    destination, _ = trip.observe(replace(arrived, x=x, y=y, sequence=seq))
                self.assertEqual(destination, goal)

    def test_ironforge_can_reach_loch_modan_and_continue_to_wetlands(self):
        route = plan_walking_route(1455, 1432, 18, 'alive')
        self.assertEqual([leg.destination for leg in route], [1426, 1432])
        self.assertIsNone(plan_walking_route(1455, 1437, 18, 'alive'))
        self.assertEqual([leg.destination for leg in plan_walking_route(1455, 1437, 20, 'alive')],
                         [1426, 1432, 1437])
        self.assertEqual([leg.destination for leg in plan_walking_route(1432, 1455, 0, 'ghost')], [1426, 1455])

        goal = MapDestination(1432, 37.5, 90.1, 'alive', '碎石怪萨满祭司营地')
        trip = WalkingTrip((123, 1), route, goal, level=18)
        gate = NavigationState('alive', 1, 1455, *route[0].points[0], 0, 791, 528, (87, 65, 68))
        next_point, _ = trip.observe(gate)
        self.assertEqual((next_point.x, next_point.y), route[0].points[1])
        outside = replace(gate, map_id=1426, x=52.9, y=35.45, sequence=2, width=4925, height=3283)
        self.assertEqual(trip.observe(outside), (None, None))
        self.assertEqual(trip.observe(outside), (None, None))
        self.assertIn('确认进入丹莫罗', trip.observe(replace(outside, sequence=3))[1])
        waypoint, _ = trip.observe(replace(outside, sequence=4))
        self.assertEqual((waypoint.x, waypoint.y), route[0].arrival_road[1])

        arrival = route[0].arrival_road
        for seq, (x, y) in enumerate(arrival[1:], 5):
            _, status = trip.observe(replace(outside, x=x, y=y, sequence=seq))
        self.assertIn('走完换图接入道路', status)
        crossing = replace(outside, map_id=1432, x=15.58, y=19.97, sequence=30, width=2758, height=1840)
        self.assertEqual(trip.observe(crossing), (None, None))
        self.assertIn('确认进入洛克莫丹', trip.observe(replace(crossing, sequence=31))[1])
        waypoint, _ = trip.observe(replace(crossing, sequence=32))
        self.assertEqual((waypoint.x, waypoint.y), route[1].arrival_road[1])
        self.assertIn((36.0, 84.9), trip._camp_road)
        self.assertEqual(trip.goal, goal)

    def setUp(self):
        self.westfall = ZONE_MAP_IDS['西部荒野']
        self.duskwood = ZONE_MAP_IDS['暮色森林']
        self.redridge = ZONE_MAP_IDS['赤脊山']
        self.elwynn = ZONE_MAP_IDS['艾尔文森林']

    def test_catalog_uses_current_forever_maps_and_leaves_water_crossings_unplanned(self):
        self.assertEqual((self.westfall, self.duskwood, self.redridge, self.elwynn), (1436, 1431, 1433, 1429))
        path = plan_walking_route(self.elwynn, self.redridge, 22, 'alive')
        self.assertEqual([leg.destination for leg in path], [self.redridge])
        self.assertIsNone(plan_walking_route(self.elwynn, self.redridge, 14, 'alive'))
        self.assertEqual(len(plan_walking_route(self.elwynn, self.redridge, 12, 'ghost')), 1)
        self.assertIsNone(plan_walking_route(self.westfall, 1439, 17, 'alive'))
        self.assertEqual(plan_walking_route(self.redridge, self.redridge, 22, 'alive'), ())

    def test_loch_modan_uses_south_road_from_town_to_trogg_camp(self):
        loch = ZONE_MAP_IDS['洛克莫丹']
        self.assertEqual(loch, 1432)
        goal = MapDestination(loch, 37.9, 87.0, 'alive', '碎石怪断骨者营地')
        town = CharacterState('alive', True, True, 'alliance', 16, loch, '洛克莫丹', 33.53, 49.38)
        road = camp_access_road(goal, origin=town)
        trip = WalkingTrip((123, 1), (), goal, level=16, camp_road=road)
        point = NavigationState('alive', 1, loch, town.x, town.y, 0, 2758, 1840, (87, 65, 68))
        self.assertEqual(road[1], (32.3, 50.5))
        for sequence, (x, y) in enumerate(road, 1):
            target, _ = trip.observe(replace(point, x=x, y=y, sequence=sequence))
            if sequence < len(road):
                self.assertEqual((target.x, target.y), road[sequence])
                self.assertFalse(trip.complete)
        self.assertEqual(target, goal)
        self.assertTrue(trip.complete)
        self.assertEqual(camp_access_road(goal, origin=replace(town, x=62)), ())

    def test_loch_east_bank_leaves_the_ridge_before_diverging_to_camps(self):
        loch = ZONE_MAP_IDS['洛克莫丹']
        ridge = NavigationState('alive', 1, loch, 69.03, 54.23, 3.751, 2758, 1840, (87, 65, 68))
        boars = MapDestination(loch, 65.4, 39.6, 'alive', '东岸老山猪区')
        buzzards = MapDestination(loch, 76.8, 70.5, 'alive', '旅行者营地西侧山鹫区')
        for goal in (boars, buzzards):
            with self.subTest(goal=goal.label):
                road = camp_access_road(goal, origin=ridge)
                trip = WalkingTrip((123, 1), (), goal, level=16, camp_road=road)
                waypoint, _ = trip.observe(ridge)
                self.assertEqual((waypoint.x, waypoint.y), (69.1, 52.4))
                for sequence, point in enumerate(road, 2):
                    waypoint, _ = trip.observe(replace(ridge, x=point[0], y=point[1], sequence=sequence))
                self.assertEqual(waypoint, goal)
                self.assertTrue(trip.complete)
        self.assertEqual(camp_access_road(boars, origin=replace(ridge, x=33.53)), ())
        self.assertIn((75.7, 46.6), camp_access_road(buzzards, origin=ridge))
        self.assertIn((65.9, 47.9), camp_access_road(boars, origin=ridge))

    def test_loch_east_camps_use_northern_lodge_approach_in_both_directions(self):
        loch = ZONE_MAP_IDS['洛克莫丹']
        boars = MapDestination(loch, 65.4, 39.6, 'alive', '东岸老山猪区')
        buzzards = MapDestination(loch, 76.8, 70.5, 'alive', '旅行者营地西侧山鹫区')
        start = NavigationState('alive', 1, loch, boars.x, boars.y, 0, 2758, 1840, (87, 65, 68))
        anchors = ((75.7, 46.6), (80.7, 61.5), (80.7, 64.7), (78.1, 68.1))
        for origin, goal, ordered in ((start, buzzards, anchors),
                                      (replace(start, x=buzzards.x, y=buzzards.y), boars, anchors[::-1])):
            with self.subTest(goal=goal.label):
                road = camp_access_road(goal, origin=origin)
                self.assertEqual(sorted(ordered, key=road.index), list(ordered))
                self.assertNotIn((63.2, 68.8), road)
                self.assertNotIn((81.4, 61.6), road)
                trip = WalkingTrip((123, 1), (), goal, level=16, camp_road=road)
                target, _ = trip.observe(origin)
                first = (66.5, 41.2) if goal == buzzards else (77.3, 69.25)
                self.assertEqual((target.x, target.y), first)
        resumed = replace(start, x=63.4, y=68.18)
        road = camp_access_road(buzzards, origin=resumed)
        trip = WalkingTrip((123, 1), (), buzzards, level=16, camp_road=road)
        target, _ = trip.observe(resumed)
        self.assertEqual((target.x, target.y), (63.0, 67.3))
        target, _ = trip.observe(replace(resumed, x=63.0, y=67.3, sequence=2))
        self.assertEqual((target.x, target.y), (62.7, 65.8))
        at_lodge_slope = replace(start, x=81.3, y=60.55)
        road = camp_access_road(buzzards, origin=at_lodge_slope)
        trip = WalkingTrip((123, 1), (), buzzards, level=16, camp_road=road)
        target, _ = trip.observe(at_lodge_slope)
        self.assertEqual((target.x, target.y), (80.7, 60.6))

    def test_dun_algaz_keeps_tunnel_waypoints_after_cutover(self):
        loch, wetlands = ZONE_MAP_IDS['洛克莫丹'], ZONE_MAP_IDS['湿地']
        self.assertEqual(wetlands, 1437)
        self.assertIsNone(plan_walking_route(loch, wetlands, 19, 'alive'))
        goal = MapDestination(wetlands, 60.51, 63.71, 'alive', '藓皮豺狼人营地')
        path = plan_walking_route(loch, wetlands, 20, 'alive')
        trip = WalkingTrip((123, 1), path, goal, level=20)
        position = NavigationState('alive', 1, loch, 78, 35, 0, 2758, 1840, (87, 65, 68))
        destination, status = trip.observe(position)
        self.assertIsNone(destination)
        self.assertIn('西岸', status)
        west = replace(position, x=25.56, y=10.56, sequence=2)
        waypoint, _ = trip.observe(west)
        self.assertEqual((waypoint.x, waypoint.y), (25.45, 6.9))

        across = replace(position, map_id=wetlands, x=55.84, y=91.93, sequence=3, width=4135, height=2756)
        self.assertEqual(trip.observe(across), (None, None))
        self.assertEqual(trip.observe(across), (None, None))
        destination, status = trip.observe(replace(across, sequence=4))
        self.assertIsNone(destination)
        self.assertIn('确认进入湿地', status)
        self.assertFalse(trip.complete)
        road = camp_access_road(goal)
        for sequence, (x, y) in enumerate(road, 5):
            waypoint, status = trip.observe(replace(across, x=x, y=y, sequence=sequence))
            if sequence - 4 < len(road):
                self.assertEqual((waypoint.x, waypoint.y), road[sequence - 4])
                self.assertFalse(trip.complete)
        self.assertEqual(waypoint, goal)
        self.assertTrue(trip.complete)
        self.assertIn((50.56, 82.56), road)
        self.assertIn((53.7, 70.3), road)

        ghost_path = plan_walking_route(wetlands, loch, 0, 'ghost')
        self.assertEqual(ghost_path[0].points[-1], road[0])
        corpse = MapDestination(loch, 28.5, 24.0, 'ghost', '尸体')
        ghost = WalkingTrip((123, 1), ghost_path, corpse)
        seam = replace(west, life='ghost', x=25.34, y=2.8, sequence=5)
        self.assertEqual(ghost.observe(seam), (None, None))
        self.assertIn('确认进入洛克莫丹', ghost.observe(replace(seam, sequence=6))[1])
        waypoint, _ = ghost.observe(replace(seam, sequence=7))
        self.assertEqual((waypoint.x, waypoint.y), (25.45, 6.9))
        self.assertEqual(ghost.observe(replace(seam, x=corpse.x, y=corpse.y, sequence=8)), (corpse, None))

    def test_dig_camps_join_the_wetlands_road_from_the_north(self):
        start = NavigationState('alive', 1, 1432, 65.4, 39.6, 0, 2758, 1840, (87, 65, 68))
        route = plan_walking_route(1432, 1437, 20, 'alive')
        wetlands = MapDestination(1437, 60.51, 63.71, 'alive', '湿地营地')
        for x, y in ((67.869, 59.098), (67.015, 59.412)):
            with self.subTest(stand=(x, y)):
                camp = MapDestination(1432, x, y, 'alive', '挖掘场')
                road = camp_access_road(camp, origin=start)
                self.assertEqual(road[0], (65.4, 39.6))
                self.assertEqual(road[-1], (x, y))
                position = replace(start, x=x, y=y)
                trip = WalkingTrip((123, 1), route, wetlands, level=20)
                visited = []
                for _ in range(80):
                    waypoint, status = trip.observe(position)
                    if waypoint is None:
                        self.assertIn('等待游戏确认切图', status)
                        break
                    visited.append((waypoint.x, waypoint.y))
                    position = replace(position, x=waypoint.x, y=waypoint.y, sequence=position.sequence + 1)
                self.assertEqual(visited[:len(road)-1], list(road[-2::-1]))
                self.assertIn((48.589, 14.27), visited)
                self.assertEqual(visited[-1], (25.27, 0.07))

    def test_east_loch_modan_walks_the_dam_before_entering_wetlands(self):
        route = plan_walking_route(1432, 1437, 20, 'alive')
        goal = MapDestination(1437, 60.51, 63.71, 'alive', '藓皮豺狼人营地')
        trip = WalkingTrip((123, 1), route, goal, level=20)
        position = NavigationState('alive', 1, 1432, 65.4, 39.6, 0, 2758, 1840, (87, 65, 68))
        visited = []
        for _ in range(60):
            waypoint, _ = trip.observe(position)
            if waypoint is None:
                break
            visited.append(waypoint)
            position = replace(position, sequence=position.sequence + 1, x=waypoint.x, y=waypoint.y)
        self.assertEqual((visited[0].x, visited[0].y), (61.9, 32))
        self.assertEqual((visited[-1].x, visited[-1].y), (25.27, 0.07))
        deck = [point for point in visited if 39.88 <= point.x <= 55.7]
        self.assertEqual(len(deck), 35)
        self.assertTrue(all(point.radius == 2 and not point.allow_detour for point in deck))
        self.assertGreater(deck[0].x, deck[-1].x)
        self.assertFalse(trip.travel_exhausted)

        entered = replace(position, map_id=1437, x=55.84, y=91.93, width=4135, height=2756,
                          sequence=position.sequence + 1)
        self.assertEqual(trip.observe(entered), (None, None))
        self.assertEqual(trip.observe(entered), (None, None))
        self.assertIn('确认进入湿地', trip.observe(replace(entered, sequence=entered.sequence + 1))[1])
        for x, y in camp_access_road(goal):
            entered = replace(entered, sequence=entered.sequence + 2, x=x, y=y)
            waypoint, _ = trip.observe(entered)
        self.assertEqual(waypoint, goal)

    def test_displaced_loch_route_replans_after_two_matching_origin_samples(self):
        from wowbuddy.automation.walking_route import WalkingLeg

        origin = NavigationState('alive', 1, 1432, 65.4, 39.6, 0, 2758, 1840, (87, 65, 68))
        route = plan_walking_route(1432, 1437, 20, 'alive')
        goal = MapDestination(1437, 60.51, 63.71, 'alive', '藓皮豺狼人营地')
        alternate = (
            WalkingLeg(1432, 2500, 20, ((78, 35), (80, 35)), manual=True),
            WalkingLeg(2500, 1437, 20, ((20, 35), (25, 35)), manual=True),
        )
        for connections in ((), alternate):
            with self.subTest(alternate=bool(connections)):
                trip = WalkingTrip((123, 1), route, goal, level=20, connections=connections)
                self.assertIsNotNone(trip.observe(origin)[0])
                displaced = replace(origin, x=78, y=35, sequence=2)
                self.assertIsNone(trip.observe(displaced)[0])
                self.assertEqual(trip.observe(displaced), (None, None))
                self.assertFalse(trip.travel_exhausted)
                trip.observe(None)
                self.assertIsNone(trip.observe(replace(displaced, sequence=3))[0])
                self.assertFalse(trip.travel_exhausted)

                waypoint, status = trip.observe(replace(displaced, sequence=4))
                self.assertIsNone(waypoint)
                self.assertFalse(trip.blocked_legs)
                if connections:
                    self.assertIn('重规划', status)
                    self.assertFalse(trip.travel_exhausted)
                    self.assertEqual(tuple(trip.legs), connections)
                    waypoint, _ = trip.observe(replace(displaced, sequence=5))
                    self.assertEqual((waypoint.x, waypoint.y), connections[0].points[1])
                else:
                    self.assertIn('无法接入原陆路', status)
                    self.assertTrue(trip.travel_exhausted)
                    waypoint, _ = trip.observe(replace(origin, sequence=5))
                    self.assertIsNotNone(waypoint)
                    self.assertFalse(trip.travel_exhausted)

    def test_stranglethorn_road_joins_from_both_sides_and_supports_ghosts(self):
        stranglethorn = ZONE_MAP_IDS['荆棘谷']
        self.assertEqual(stranglethorn, 1434)
        self.assertIsNone(plan_walking_route(self.duskwood, stranglethorn, 29, 'alive'))
        path = plan_walking_route(self.duskwood, stranglethorn, 30, 'alive')
        goal = MapDestination(stranglethorn, 35.65, 12.14, 'alive', '刷怪点')
        for road in (path[0].points, *path[0].approaches):
            trip = WalkingTrip((123, 1), path, goal, level=30)
            position = NavigationState('alive', 1, self.duskwood, *road[0], 0, 2700, 1800, (87, 65, 68))
            first, _ = trip.observe(position)
            self.assertEqual((first.x, first.y), road[1])
            across = replace(position, map_id=stranglethorn, x=39.47, y=4.92, sequence=2,
                             width=6381, height=4254)
            self.assertEqual(trip.observe(across), (None, None))
            self.assertEqual(trip.observe(across), (None, None))
            destination, status = trip.observe(replace(across, sequence=3))
            self.assertIsNone(destination)
            self.assertIn('确认进入荆棘谷', status)
            self.assertFalse(trip.complete)
            waypoint, _ = trip.observe(replace(across, sequence=4))
            self.assertEqual((waypoint.x, waypoint.y), (39.37, 6.15))
            self.assertEqual(trip.observe(replace(across, sequence=4)), (waypoint, None))
            road_points = []
            for sequence in range(5, 14):
                road_points.append((waypoint.x, waypoint.y))
                sample = replace(across, x=waypoint.x, y=waypoint.y, sequence=sequence)
                waypoint, status = trip.observe(sample)
            self.assertIn((38.38, 11.66), road_points)
            self.assertEqual(road_points[-1], (36.2, 14.6))
            self.assertIn('走完营地接入道路', status)
            self.assertEqual(waypoint, goal)
            self.assertTrue(trip.complete)
        eastern_goal = replace(goal, x=48.09, y=20.2)
        east = WalkingTrip((123, 1), path, eastern_goal, level=39)
        self.assertEqual(east.observe(across), (None, None))
        self.assertIsNone(east.observe(replace(across, sequence=3))[0])
        self.assertIn((39.8, 23.55), camp_access_road(eastern_goal))
        ghost_route = plan_walking_route(stranglethorn, self.westfall, 1, 'ghost')
        self.assertEqual([leg.destination for leg in ghost_route], [self.duskwood, self.westfall])

    def test_stranglethorn_to_swamp_uses_east_bank_bridge_and_confirms_each_crossing(self):
        stranglethorn, duskwood, deadwind, swamp = (1434, 1431, 1430, 1435)
        self.assertIsNone(plan_walking_route(stranglethorn, swamp, 40, 'alive'))
        path = plan_walking_route(stranglethorn, swamp, 41, 'alive')
        self.assertEqual([leg.destination for leg in path], [duskwood, deadwind, swamp])
        reverse = plan_walking_route(swamp, stranglethorn, 1, 'ghost')
        self.assertEqual([leg.destination for leg in reverse], [deadwind, duskwood, stranglethorn])
        goal = MapDestination(swamp, 27.1, 56.7, 'alive', '西部小盐齿鳄鱼区')
        trip = WalkingTrip((123, 1), path, goal, level=41)
        position = NavigationState('alive', 1, stranglethorn, 48.09, 20.2, 0, 6381, 4254, (87, 65, 68))
        used = []

        def follow_current_map():
            nonlocal position
            for _ in range(100):
                point, status = trip.observe(position)
                if point is None and status == '已走完换图接入道路。':
                    position = replace(position, sequence=position.sequence + 1)
                    continue
                if point is None or point == goal:
                    return point
                self.assertEqual(point.map_id, position.map_id)
                used.append((point.map_id, point.x, point.y))
                position = replace(position, x=point.x, y=point.y, sequence=position.sequence + 1)
            self.fail('路点未走完')

        for target, x, y, width, height in ((duskwood, 44.80, 85.40, 2700, 1800),
                                            (deadwind, 32.69, 35.71, 2500, 1667),
                                            (swamp, 8.47, 51.17, 2294, 1529)):
            self.assertIsNone(follow_current_map())
            position = replace(position, map_id=target, x=x, y=y, width=width, height=height,
                               sequence=position.sequence + 1)
            self.assertEqual(trip.observe(position), (None, None))
            self.assertEqual(trip.observe(position), (None, None))
            position = replace(position, sequence=position.sequence + 1)
            self.assertIn('确认进入', trip.observe(position)[1])
        self.assertEqual(follow_current_map(), goal)
        self.assertIn((stranglethorn, 39.8, 23.55), used)
        self.assertIn((duskwood, 44.3, 66.4), used)
        self.assertIn((deadwind, 44.2, 34.28), used)
        self.assertIn((swamp, 25.7, 55.65), used)
        self.assertTrue(trip.complete)

    def test_blasted_lands_uses_land_approach_after_map_confirmation(self):
        swamp, blasted = 1435, 1419
        self.assertIsNone(plan_walking_route(swamp, blasted, 43, 'alive'))
        legs = plan_walking_route(swamp, blasted, 48, 'alive')
        goal = MapDestination(blasted, 52.27, 27.39, 'alive', '中部灰鬃野猪区')
        trip = WalkingTrip(1, legs, goal, level=48)
        pos = NavigationState('alive', 1, swamp, 27.1, 56.7, 0, 2294, 1529, (87, 65, 68))
        point, _ = trip.observe(pos)
        self.assertEqual((point.x, point.y), (26.4, 56.7))
        for sequence in range(2, 25):
            pos = replace(pos, x=point.x, y=point.y, sequence=sequence)
            point, _ = trip.observe(pos)
            if point is None:
                break
        self.assertIsNone(point)
        entry = replace(pos, map_id=blasted, x=52.16, y=8.04, width=3350, height=2233, sequence=30)
        self.assertEqual(trip.observe(entry), (None, None))
        self.assertEqual(trip.observe(entry), (None, None))
        self.assertIn('确认进入诅咒之地', trip.observe(replace(entry, sequence=31))[1])
        visited = []
        for sequence in range(32, 65):
            point, _ = trip.observe(replace(entry, sequence=sequence))
            if point == goal:
                break
            visited.append((point.x, point.y))
            entry = replace(entry, x=point.x, y=point.y)
        self.assertEqual(visited[-1], (52.6, 26.5))
        self.assertIn((50.35, 20.35), visited)
        self.assertTrue(trip.complete)
        reverse = plan_walking_route(blasted, swamp, 1, 'ghost')
        self.assertEqual([leg.destination for leg in reverse], [swamp])
        self.assertEqual(reverse[0].arrival_road[-1], (26.4, 56.7))

    def test_deadwind_camp_approaches_join_from_both_entrances_and_switch_on_land(self):
        deadwind, duskwood, swamp, blasted = (1430, 1431, 1435, 1419)
        east = plan_walking_route(blasted, deadwind, 55, 'alive')
        self.assertEqual([leg.destination for leg in east], [swamp, deadwind])
        ogre = MapDestination(deadwind, 54.6, 60.4, 'alive', '罪恶谷逆风蛮兵区')
        shadow = replace(ogre, x=38.6, y=42.15, label='西侧天空之影区')
        for source, entry, camp, through, away in (
            (swamp, (60.17, 41.45), ogre, (52.55, 42.2), (44.2, 34.28)),
            (duskwood, (32.69, 35.71), ogre, (44.2, 34.28), (60.2, 41.3)),
            (swamp, (60.17, 41.45), shadow, (44.2, 34.28), (54.55, 59.95)),
        ):
            with self.subTest(source=source, camp=camp.label):
                legs = plan_walking_route(source, deadwind, 55, 'alive')
                trip = WalkingTrip(1, legs, camp, level=55)
                position = NavigationState('alive', 1, deadwind, *entry, 0, 2500, 1667, (87, 65, 68))
                self.assertEqual(trip.observe(position), (None, None))
                self.assertEqual(trip.observe(position), (None, None))
                self.assertIn('确认进入逆风小径', trip.observe(replace(position, sequence=2))[1])
                seen = []
                for sequence in range(3, 85):
                    point, _ = trip.observe(replace(position, sequence=sequence))
                    if point == camp:
                        break
                    self.assertEqual(point.map_id, deadwind)
                    seen.append((point.x, point.y))
                    position = replace(position, x=point.x, y=point.y)
                self.assertTrue(trip.complete)
                self.assertIn(through, seen)
                self.assertNotIn(away, seen)
        from_ogre = replace(position, x=ogre.x, y=ogre.y)
        self.assertIn((44.2, 34.28), camp_access_road(shadow, origin=from_ogre))
        self.assertEqual(camp_access_road(ogre, origin=from_ogre), ())
        ghost_goal = replace(ogre, life='ghost', x=54.7, y=60.8)
        ghost = WalkingTrip(1, plan_walking_route(swamp, deadwind, 1, 'ghost'), ghost_goal)
        entry = replace(position, life='ghost', x=60.17, y=41.45, sequence=1)
        self.assertEqual(ghost.observe(entry), (None, None))
        self.assertIn('确认进入逆风小径', ghost.observe(replace(entry, sequence=2))[1])
        next_road, _ = ghost.observe(replace(entry, sequence=3))
        self.assertEqual((next_road.x, next_road.y), (58.4, 41.5))
        self.assertIn((54.55, 59.95), camp_access_road(ghost_goal, origin=entry))
        self.assertEqual(camp_access_road(replace(ghost_goal, x=70), origin=entry), ())
        self.assertEqual(ghost.observe(replace(entry, x=ghost_goal.x, y=ghost_goal.y, sequence=4)), (ghost_goal, None))

    def test_stormwind_gate_uses_goldshire_fork_after_map_confirmation(self):
        city = ZONE_MAP_IDS['暴风城']
        for map_id, expected_fork in ((self.westfall, (40.5, 66.9)), (self.redridge, (44.3, 67.9))):
            with self.subTest(map_id=map_id):
                legs = plan_walking_route(city, map_id, 16, 'alive')
                self.assertEqual([leg.destination for leg in legs], [self.elwynn, map_id])
                goal = MapDestination(map_id, 46.1, 38.2, 'alive', '刷怪点')
                trip = WalkingTrip((123, 1), legs, goal, level=16)
                position = NavigationState('alive', 1, city, *legs[0].points[0], 0, 1738, 1158, (87, 65, 68))
                self.assertEqual(trip.observe(position)[0].map_id, city)
                position = replace(position, sequence=2, map_id=self.elwynn, x=32.4, y=50.5, width=3471, height=2315)
                self.assertEqual(trip.observe(position), (None, None))
                self.assertEqual(trip.observe(position), (None, None))
                position = replace(position, sequence=3)
                self.assertIn('确认进入艾尔文森林', trip.observe(position)[1])
                for sequence, expected in enumerate(
                        ((33.5, 52.1), (34.6, 53.2), (36.4, 53.8), (38.1, 55.2), (39.9, 57.6),
                         (40.15, 59.2), (40.75, 60.9), (41.6, 63.7), (42.3, 66.3), expected_fork), 4):
                    waypoint, _ = trip.observe(replace(position, sequence=sequence))
                    self.assertEqual((waypoint.x, waypoint.y), expected)
                    position = replace(position, x=waypoint.x, y=waypoint.y)
                self.assertEqual(trip.goal, goal)

    def test_departure_from_dagger_hills_returns_through_the_westfall_road_and_bridge(self):
        goal = MapDestination(self.redridge, 23.25, 79.41, 'alive', '赤脊山偷猎者营地')
        legs = plan_walking_route(self.westfall, self.redridge, 18, 'alive', origin=(52.3, 72.6))
        trip = WalkingTrip(1, legs, goal, level=18)
        position = NavigationState('alive', 1, self.westfall, 52.3, 72.6, 0, 3500, 2333, (87, 65, 68))
        waypoint, _ = trip.observe(position)
        self.assertEqual((waypoint.x, waypoint.y), (52.55, 65.28))
        path = []
        for sequence in range(2, len(legs[0].points) + 3):
            if waypoint is None:
                break
            self.assertEqual(waypoint.map_id, self.westfall)
            path.append((waypoint.x, waypoint.y))
            position = replace(position, sequence=sequence, x=waypoint.x, y=waypoint.y)
            waypoint, _ = trip.observe(position)
        points = ((54.64, 65.82), (57.08, 65.74), (58.19, 44.05), (61.6, 18.05), (62.26, 17.18))
        indexes = [path.index(point) for point in points]
        self.assertEqual(indexes, sorted(indexes))
        self.assertGreater(position.x, 62.26)
        self.assertLess(position.y, 17.18)
        arrival = replace(position, map_id=self.elwynn, x=20.23, y=81.08, sequence=100)
        self.assertEqual(trip.observe(arrival), (None, None))
        self.assertIn('确认进入艾尔文森林', trip.observe(replace(arrival, sequence=101))[1])
        self.assertEqual(tuple(trip.legs), legs[1:])

    def test_westfall_crossing_continues_forward_and_follows_elwynn_fence_bend(self):
        for life in ('alive', 'ghost'):
            with self.subTest(life=life):
                legs = plan_walking_route(self.westfall, self.redridge, 18, life)
                goal = MapDestination(self.redridge, 23.25, 79.41, life, '赤脊山偷猎者营地')
                trip = WalkingTrip((123, 1), legs, goal, level=18)
                arrival = NavigationState(life, 1, self.elwynn, 20.23, 81.08, 0, 3471, 2315, (87, 65, 68))
                self.assertEqual(trip.observe(arrival), (None, None))
                self.assertIn('确认进入艾尔文森林', trip.observe(replace(arrival, sequence=2))[1])
                waypoint, _ = trip.observe(replace(arrival, sequence=3))
                self.assertGreater(waypoint.x, arrival.x)
                self.assertLess(waypoint.y, arrival.y)

                # 从实机已抵达的弯道起点重新接路，下一段应沿栅栏内的道路转弯。
                trip = WalkingTrip((123, 2), legs[1:], goal, level=18)
                bend = replace(arrival, x=28.4, y=78.1, sequence=4)
                waypoint, _ = trip.observe(bend)
                self.assertTrue(29 < waypoint.x < 30)
                self.assertGreaterEqual(waypoint.y, 78)
                self.assertEqual(trip.goal, goal)

    def test_quick_border_returns_retry_original_leg_then_exclude_it(self):
        for life in ('alive', 'ghost'):
            with self.subTest(life=life):
                legs = plan_walking_route(self.westfall, self.redridge, 18, life)
                goal = MapDestination(self.redridge, 23.25, 79.41, life, '赤脊山偷猎者营地')
                trip = WalkingTrip((123, 1), legs, goal, level=18)
                source = NavigationState(life, 1, self.westfall, 62.38, 17.83, 0, 3500, 2333, (87, 65, 68))
                arrival = replace(source, map_id=self.elwynn, x=20.23, y=81.08, width=3471, height=2315)
                returned = replace(source, x=62.35, y=17.78)

                for attempt in range(5):
                    step, clock = attempt * 6, attempt * 5000
                    self.assertEqual(trip.observe(replace(source, sequence=step + 1), now_ms=clock)[0].map_id,
                                     self.westfall)
                    self.assertEqual(trip.observe(replace(arrival, sequence=step + 2), now_ms=clock + 200), (None, None))
                    self.assertIn('确认进入艾尔文森林',
                                  trip.observe(replace(arrival, sequence=step + 3), now_ms=clock + 400)[1])
                    first = replace(returned, sequence=step + 4)
                    self.assertIn('非预期地图', trip.observe(first, now_ms=clock + 2400)[1])
                    self.assertEqual(trip.observe(first, now_ms=clock + 2600), (None, None))
                    _, status = trip.observe(replace(returned, sequence=step + 5), now_ms=clock + 2800)
                    if attempt < 4:
                        self.assertIn('重新接入原陆路', status)
                        self.assertEqual(tuple(trip.legs), legs)
                        self.assertFalse(trip.blocked_legs)
                    else:
                        self.assertIn(legs[0], trip.blocked_legs)
                        if life == 'alive':
                            self.assertTrue(trip.travel_exhausted)
                        else:
                            self.assertFalse(trip.travel_exhausted)
                            self.assertEqual([leg.destination for leg in trip.legs], [self.duskwood, self.redridge])
                self.assertEqual(trip.goal, goal)

    def test_late_or_distant_border_return_uses_normal_replanning(self):
        legs = plan_walking_route(self.westfall, self.redridge, 18, 'alive')
        goal = MapDestination(self.redridge, 23.25, 79.41, 'alive', '赤脊山偷猎者营地')
        source = NavigationState('alive', 1, self.westfall, 62.38, 17.83, 0, 3500, 2333, (87, 65, 68))
        arrival = replace(source, map_id=self.elwynn, x=20.23, y=81.08, width=3471, height=2315)
        for returned_x, now_ms in ((62.35, 7000), (60, 2400)):
            with self.subTest(returned_x=returned_x, now_ms=now_ms):
                trip = WalkingTrip((123, 1), legs, goal, level=18)
                trip.observe(source, now_ms=0)
                trip.observe(replace(arrival, sequence=2), now_ms=200)
                trip.observe(replace(arrival, sequence=3), now_ms=400)
                returned = replace(source, x=returned_x, sequence=4)
                trip.observe(returned, now_ms=now_ms)
                self.assertIn('重规划陆路', trip.observe(replace(returned, sequence=5), now_ms=now_ms + 200)[1])
                self.assertFalse(trip.blocked_legs)

    def test_ghost_from_westfall_joins_road_to_the_stormwind_gate(self):
        city = ZONE_MAP_IDS['暴风城']
        legs = plan_walking_route(self.westfall, city, 0, 'ghost')
        self.assertEqual([leg.destination for leg in legs], [self.elwynn, city])
        goal = MapDestination(city, 65, 77, 'ghost', '尸体')
        trip = WalkingTrip((123, 1), legs, goal)
        position = NavigationState('ghost', 1, self.elwynn, 20.2, 80.7, 0, 3471, 2315, (87, 65, 68))
        self.assertEqual(trip.observe(position), (None, None))
        self.assertIn('确认进入艾尔文森林', trip.observe(replace(position, sequence=2))[1])
        waypoint, _ = trip.observe(replace(position, sequence=3))
        self.assertEqual((waypoint.x, waypoint.y), (22.2, 79.1))
        self.assertEqual(trip.goal, goal)

    def test_multizone_walk_retains_final_goal_until_confirmed_in_each_new_map(self):
        path = plan_walking_route(self.westfall, self.redridge, 22, 'alive')
        goal = MapDestination(self.redridge, 25.5, 59.4, 'alive', '湖畔镇')
        trip = WalkingTrip((123, 1), path, goal)

        def sample(map_id, sequence, x, y):
            return NavigationState('alive', sequence, map_id, x, y, 0.0, 1000, 1000, (87, 65, 68))

        sequence = 0
        for leg_index, leg in enumerate(path):
            first = sample(leg.source, sequence, *leg.points[0])
            destination, status = trip.observe(first)
            self.assertIsNone(status)
            self.assertEqual((destination.x, destination.y, destination.arrival_radius), (*leg.points[1], 5))
            self.assertEqual(trip.observe(first), (destination, None))
            for x, y in leg.points[1:]:
                sequence += 1
                destination, status = trip.observe(sample(leg.source, sequence, x, y))
            self.assertIsNotNone(destination)
            self.assertIn('等待游戏确认切图', status)
            self.assertFalse(destination.allow_detour)
            last_x, last_y = leg.points[-1]
            self.assertLessEqual(math.hypot((destination.x - last_x) * 10, (destination.y - last_y) * 10), 12.001)
            sequence += 1
            reached_probe = sample(leg.source, sequence, destination.x, destination.y)
            stopped, status = trip.observe(reached_probe)
            self.assertIsNone(stopped)
            self.assertIn('等待游戏确认切图', status)
            sequence += 1
            self.assertEqual(trip.observe(replace(reached_probe, sequence=sequence)), (None, None))
            self.assertFalse(trip.complete)
            unexpected = sample(1439, sequence, 10, 10)
            self.assertIn('非预期地图', trip.observe(unexpected)[1])
            expected = sample(leg.destination, sequence, 60, 60)
            self.assertEqual(trip.observe(expected), (None, None))
            self.assertEqual(trip.observe(expected), (None, None))
            self.assertEqual(trip.observe(None), (None, None))
            self.assertEqual(trip.observe(expected), (None, None))
            sequence += 1
            destination, status = trip.observe(replace(expected, sequence=sequence))
            self.assertIn('已确认进入', status)
            if leg_index + 1 < len(path):
                self.assertIsNone(destination)
            else:
                self.assertEqual(destination, goal)
        self.assertTrue(trip.complete)

    def test_revival_rejoins_nearest_road_point_without_changing_destination(self):
        path = plan_walking_route(self.westfall, self.redridge, 22, 'alive')
        goal = MapDestination(self.redridge, 25.5, 59.4, 'alive', '湖畔镇')
        trip = WalkingTrip((123, 1), path, goal)
        points = path[0].points
        start = NavigationState('alive', 1, self.westfall, *points[0], 0, 1000, 1000, (87, 65, 68))
        first, _ = trip.observe(start)
        self.assertEqual((first.x, first.y), points[1])
        self.assertEqual(trip.observe(replace(start, life='ghost')), (None, None))
        trip.resume_after_revival()
        rejoin, _ = trip.observe(replace(start, sequence=3, x=points[3][0], y=points[3][1]))
        self.assertEqual((rejoin.x, rejoin.y), points[4])
        self.assertEqual(trip.goal, goal)
        self.assertEqual(tuple(trip.legs), path)

    def test_blocked_road_replans_to_same_destination_for_leveling_and_corpse_runs(self):
        for life, level in (('alive', 22), ('ghost', 0)):
            with self.subTest(life=life):
                path = plan_walking_route(self.westfall, self.redridge, level, life)
                goal = MapDestination(self.redridge, 25.5, 59.4, life, '目的地')
                trip = WalkingTrip((123, 1), path, goal, level=level)
                position = NavigationState(life, 1, self.westfall, *path[0].points[0],
                                           0, 1000, 1000, (87, 65, 68))
                blocked, _ = trip.observe(position)
                self.assertIsNone(trip.avoid_blocked_road(replace(position, map_id=self.elwynn), blocked))
                self.assertIn('改走经暮色森林', trip.avoid_blocked_road(position, blocked))
                self.assertEqual([leg.destination for leg in trip.legs], [self.duskwood, self.redridge])
                new_target, _ = trip.observe(replace(position, sequence=2))
                self.assertNotEqual(new_target, blocked)
                self.assertIn('暂无其他', trip.avoid_blocked_road(position, new_target))
                self.assertEqual(trip.goal, goal)

    def test_unconfirmed_exit_uses_alternate_after_fresh_source_map_samples(self):
        path = plan_walking_route(self.westfall, self.redridge, 22, 'alive')
        goal = MapDestination(self.redridge, 25.5, 59.4, 'alive', '目的地')
        trip = WalkingTrip((123, 1), path, goal, level=22)
        position = NavigationState('alive', 1, self.westfall, *path[0].points[-1],
                                   0, 1000, 1000, (87, 65, 68))
        probe, _ = trip.observe(position, now_ms=100)
        at_exit = replace(position, sequence=2, x=probe.x, y=probe.y)
        self.assertIsNone(trip.observe(at_exit, now_ms=200)[0])
        self.assertEqual(trip.observe(at_exit, now_ms=9000), (None, None))
        trip.observe(None, now_ms=9100)
        self.assertEqual(trip.observe(replace(at_exit, sequence=3), now_ms=9200), (None, None))
        self.assertEqual(trip.observe(replace(at_exit, sequence=4), now_ms=17199), (None, None))
        destination, status = trip.observe(replace(at_exit, sequence=5), now_ms=17200)
        self.assertIsNone(destination)
        self.assertIn('改走经暮色森林', status)
        self.assertEqual(trip.observe(replace(at_exit, sequence=6), now_ms=17400)[0].map_id, self.westfall)

    def test_exit_displacement_after_missing_position_rejoins_the_same_road(self):
        for life in ('alive', 'ghost'):
            with self.subTest(life=life):
                path = plan_walking_route(self.westfall, self.redridge, 22, life)
                leg = path[0]
                goal = MapDestination(self.redridge, 25.5, 59.4, life, '目的地')
                trip = WalkingTrip((123, 1), path, goal, level=22)
                end = NavigationState(life, 1, leg.source, *leg.points[-1],
                                      0, 1000, 1000, (87, 65, 68))
                probe, _ = trip.observe(end, now_ms=100)
                at_exit = replace(end, sequence=2, x=probe.x, y=probe.y)
                self.assertIsNone(trip.observe(at_exit, now_ms=200)[0])
                self.assertEqual(trip.observe(None, now_ms=9000), (None, None))
                away = replace(at_exit, sequence=3, x=leg.points[0][0], y=leg.points[0][1])
                next_point, status = trip.observe(away, now_ms=10_000)
                self.assertIsNotNone(next_point)
                self.assertEqual((next_point.x, next_point.y), leg.points[1])
                self.assertIn('重新接入原路段', status)
                self.assertEqual(trip.observe(replace(away, sequence=4), now_ms=19_000), (next_point, None))
                self.assertEqual(tuple(trip.legs), path)
                self.assertFalse(trip.blocked_legs)

    def test_dev_window_restarts_road_approach_only_after_revival_ack(self):
        script = '''
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from run_dev import launch
from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
from wowbuddy.automation.death_recovery import AutomaticRevival
from wowbuddy.automation.navigation import MapDestination
from wowbuddy.core.old_protocol import OldFrame
from wowbuddy.engine.pipeline import Decision
from wowbuddy.engine.scheduler import TickResult
from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

app = QApplication(['WowBuddyDev'])
def verify():
    try:
        window = next(w for w in app.topLevelWidgets() if w.windowTitle().startswith('WowBuddyDev'))
        session = (123, 1, 0)
        legs = plan_walking_route(1436, 1433, 22, 'alive')
        goal = MapDestination(1433, 25.5, 59.4, 'alive', 'camp')
        trip = WalkingTrip(session, legs, goal)
        window._leveling_trip = ('alliance', 22, trip)
        mouse = Mock()
        window._automatic_revival = AutomaticRevival(mouse)
        position = NavigationState('alive', 1, 1436, *legs[0].points[0], 0, 1000, 1000, (87, 65, 68))
        previous, _ = trip.observe(position)
        for sequence, life in enumerate(('dead', 'ghost'), 1):
            window._poll_revival(session, DeathState(life, sequence, None, False, None), None)
            assert trip.current == previous
        window._poll_revival(session, None, None)
        assert trip.current == previous
        window._poll_revival(session, DeathState('alive', 3, None, False, None), None)
        assert trip.current is None and trip.goal is goal and tuple(trip.legs) == legs
        renewed, _ = trip.observe(position)
        window._poll_revival(session, DeathState('alive', 4, None, False, None), None)
        assert trip.current == renewed
        character = CharacterState('alive', True, True, 'alliance', 22, 1436, '西部荒野', position.x, position.y)
        frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
        navigator = window._map_navigator = Mock()
        navigator.observe.return_value = None
        death = DeathState('alive', 5, None, False, None)
        def poll(recovered, death, *, disabled=False):
            result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, frame.values, (),
                recovery_ready=recovered, recovery_disabled=disabled)))
            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                window._poll_navigation(result, session, object(), frame, character, death, navigate=True)
        poll(False, death)
        assert navigator.observe.call_args.args[2:4] == (None, None)
        poll(False, death, disabled=True)
        poll(False, death, disabled=True)
        assert navigator.observe.call_args.args[2:4] == (None, None)
        assert window.ui.log_view.toPlainText().count('自动吃喝已关闭') == 1
        poll(True, None)
        assert navigator.observe.call_args.args[2:4] == (None, None)
        poll(True, death, disabled=True)
        assert navigator.observe.call_args.args[2:4] == (position, renewed)
        assert window._post_revival_session is None
        mouse.move.assert_not_called()
        mouse.click.assert_not_called()
        print('revival acknowledged before route restart', flush=True)
        window.close()
    except Exception:
        import traceback
        traceback.print_exc()
        app.exit(3)

QTimer.singleShot(0, verify)
QTimer.singleShot(3000, lambda: app.exit(42))
sys.exit(launch(Path(sys.argv[1]), hub_online=False, client_online=False, addon_online=False, auto_grind=True))
'''
        with TemporaryDirectory() as data_dir:
            result = subprocess.run([sys.executable, '-c', script, data_dir], cwd=ROOT, timeout=15,
                                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', WOWBUDDY_NO_GAME_SCAN='1'),
                                    capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'revival acknowledged before route restart', result.stdout)

    def test_dev_ghost_detour_survives_interleaved_missing_positions_on_direct_leg(self):
        script = '''
import math
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from run_dev import launch
from wowbuddy.engine.character_state import DeathState, NavigationState
from wowbuddy.automation.navigation import MapNavigator
from wowbuddy.core.old_protocol import OldFrame

app = QApplication(['WowBuddyDev'])
def verify():
    try:
        window = next(w for w in app.topLevelWidgets() if w.windowTitle().startswith('WowBuddyDev'))
        session = (123, 1, 0)
        movement = Mock()
        navigator = window._map_navigator = MapNavigator(movement)
        frame = OldFrame('ok', values={'player_valid': 'OFF', 'player_in_combat': 'OFF'})
        result = SimpleNamespace(tick=None)
        death = DeathState('ghost', 1, None, False, (1439, 39.02, 77.15), popup='missing')
        point = NavigationState('ghost', 0, 1439, 41.7669, 85.9794, 0, 6546, 4364,
                                (87, 65, 68), position_steps=1_000_000)
        heading = math.atan2((point.x - 39.02) * point.width, (point.y - 77.15) * point.height)
        def poll(position):
            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                window._poll_navigation(result, session, object(), frame, None, death, navigate=True)

        for sequence in range(6):
            poll(replace(point, sequence=sequence, heading=heading))
        assert window._corpse_trip.complete
        detour = navigator._detour
        assert detour is not None
        for sequence in range(6, 24):
            sends = movement.pulse.call_count
            poll(None)
            assert movement.pulse.call_count == sends and navigator._detour is detour
            east, north = detour.waypoints[0].offset_from(point)
            poll(replace(point, sequence=sequence, heading=math.atan2(-east, north)))
        poll(replace(point, sequence=24, heading=heading))
        assert detour.returning and not navigator.blocked
        poll(None)
        poll(replace(point, sequence=25, heading=heading))
        assert navigator._detour is detour and not detour.returning
        assert '改从另一侧前往' in window.ui.log_view.toPlainText()
        window.close()
    except Exception:
        import traceback
        traceback.print_exc()
        app.exit(3)

QTimer.singleShot(0, verify)
QTimer.singleShot(3000, lambda: app.exit(42))
sys.exit(launch(Path(sys.argv[1]), hub_online=False, client_online=False, addon_online=False))
'''
        with TemporaryDirectory() as data_dir:
            result = subprocess.run([sys.executable, '-c', script, data_dir], cwd=ROOT, timeout=15,
                                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', WOWBUDDY_NO_GAME_SCAN='1'),
                                    capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dev_facing_holds_frame_before_the_next_dispatch(self):
        script = '''
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from run_dev import launch
from wowbuddy.engine.character_state import CastFeedback, CombatFacingSample
from wowbuddy.core.old_protocol import OldFrame

app = QApplication(['WowBuddyDev'])
def verify():
    try:
        window = next(w for w in app.topLevelWidgets() if w.windowTitle().startswith('WowBuddyDev'))
        monitor = (123, 1)
        session = (*monitor, window._unattended_revision)
        frame = OldFrame('ok', values={'player_in_combat': 'ON', 'player_moving': 'OFF'})
        capture = SimpleNamespace(image=None)
        freshness = window._character_freshness = Mock(sample=(1, 2, 3))
        freshness.hold_reason.return_value = None
        movement = window._map_navigator = Mock()
        movement.movement.holding_forward = False
        feedback = CastFeedback(17, 837, ('提交', '失败'), 57, '朝向')
        sample = CombatFacingSample(5, (87, 65, 68), action_spell=116)
        with patch('wowbuddy.engine.character_state.decode_cast_feedback', return_value=feedback), patch(
                'wowbuddy.engine.character_state.decode_combat_facing', return_value=sample), patch.object(
                window.loop.capture, 'desktop_status', return_value=None):
            for sent in (None, (session, 133, 16, 500), (session, 116, 17, 500),
                         (session, 116, 16, 0)):
                window._combat_dispatch = sent
                assert window._hold_character_frame(monitor, capture, frame, 2000) is None
            movement.movement.pulse.assert_not_called()
            window._combat_dispatch = (session, 116, 16, 1500)
            assert window._hold_character_frame(monitor, capture, frame, 2000)
            movement.movement.pulse.assert_called_once_with(123, 68, 280, (87, 65, 68))
            assert window._hold_character_frame(monitor, capture, frame, 2100) is None
            assert not window._stop_before_action(frame.values)
            freshness.sample = (1, 2, 4)
            assert window._stop_before_action(frame.values)
        print('facing corrected before dispatch', flush=True)
        window.close()
    except Exception:
        import traceback
        traceback.print_exc()
        app.exit(3)

QTimer.singleShot(0, verify)
QTimer.singleShot(3000, lambda: app.exit(42))
sys.exit(launch(Path(sys.argv[1]), hub_online=False, client_online=False, addon_online=False, auto_grind=True))
'''
        with TemporaryDirectory() as data_dir:
            result = subprocess.run([sys.executable, '-c', script, data_dir], cwd=ROOT, timeout=15,
                                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', WOWBUDDY_NO_GAME_SCAN='1'),
                                    capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'facing corrected before dispatch', result.stdout)

    def test_two_fresh_samples_in_an_unexpected_known_zone_replan_to_the_original_goal(self):
        goal = MapDestination(self.redridge, 25.5, 59.4, 'alive', '湖畔镇')
        original = plan_walking_route(self.westfall, self.redridge, 22, 'alive')
        trip = WalkingTrip((123, 1), original, goal, level=22)
        sample = NavigationState('alive', 5, self.duskwood, 72, 34, 0, 1000, 1000, (87, 65, 68))
        self.assertIn('非预期', trip.observe(sample)[1])
        self.assertEqual(trip.observe(sample), (None, None))
        trip.observe(None)
        self.assertIn('非预期', trip.observe(replace(sample, sequence=6))[1])
        self.assertIn('重规划', trip.observe(replace(sample, sequence=7))[1])
        self.assertEqual([(leg.source, leg.destination) for leg in trip.legs], [(self.duskwood, self.redridge)])
        self.assertEqual(trip.goal, goal)
        self.assertEqual(trip.observe(replace(sample, sequence=8))[0].map_id, self.duskwood)


if __name__ == '__main__':
    unittest.main()
