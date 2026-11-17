"""助手 MCP 接口（docs/design/20261115-assistant-mcp.md：M1–M9）。"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import unittest
import zipfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests'), str(ROOT / 'tools')]

from wowbuddy import control_mailbox as mailbox  # noqa: E402
from wowbuddy import frame_capture_dump as dump  # noqa: E402
from wowbuddy import status_snapshot as snapshot  # noqa: E402
from wowbuddy.core.candidates import Candidate  # noqa: E402


def candidate(label, reason='', stop=False, key='', action=''):
    return Candidate(action=action, key=key, label=label, reason=reason, tag='t', stop=stop)


def decision(*candidates, **flags):
    frame = NS(ok=True, status='ok', protocol='readable', spec_id='62')
    return NS(frame=frame, fields={'player_hp': '80', 'target_name': '某人', 'in_range': 'ON'},
              candidates=candidates, thresholds=(), attack_blocked_by_range=flags.get('range', False),
              attack_blocked_by_sight=False, target_rejection=flags.get('rejection'), recovery_ready=True)


class SnapshotTests(unittest.TestCase):
    """M1：状态快照字段、序列化、原子写入、不含名字。"""

    def build(self, **overrides):
        character = NS(life='alive', outdoors=True, simplified_chinese=True, faction='Alliance', level=17,
                       map_id=1429, zone='艾尔文森林', x=41.2, y=65.3, elevation=None)
        parts = dict(now=1000.0, version='0.2.21', running=True, monitoring=True, hwnd=0x1234,
                     status_text='监控中', unattended=True, phase='camp',
                     patrol=snapshot.describe_patrol(NS(map_id=1429, points=((1.0, 2.0), (3.0, 4.0)),
                                                         path=((1.0, 2.0), (2.0, 3.0), (3.0, 4.0)),
                                                         recorded=True), 1),
                     character=snapshot.describe_character(character, at=999.5), life='alive',
                     decision=snapshot.describe_decision(decision(candidate('火球术', key='1', action='spell_133')),
                                                         candidate('火球术', key='1', action='spell_133')),
                     log_tail=['[10:00:00.000] 已开始监控'], steering={'index': 2, 'count': 12},
                     last_mark=None, control_allowed=False)
        parts.update(overrides)
        return snapshot.build_status(**parts)

    def test_m1_fields_and_json(self):
        status = self.build()
        for key in ('updated_at', 'version', 'running', 'monitoring', 'hwnd', 'unattended', 'patrol',
                    'character', 'decision', 'log_tail', 'steering', 'last_mark', 'control_allowed'):
            self.assertIn(key, status)
        self.assertEqual(status['unattended'], {'enabled': True, 'phase': 'camp'})
        self.assertEqual(status['patrol']['stop'], '2/2')
        self.assertTrue(status['patrol']['recorded'])
        self.assertEqual(status['character']['x'], 41.2)
        self.assertEqual(status['decision']['selected']['label'], '火球术')
        json.dumps(status, ensure_ascii=False)

    def test_m1_names_are_left_out(self):
        text = json.dumps(self.build(), ensure_ascii=False)
        self.assertNotIn('某人', text)
        self.assertNotIn('target_name', text)

    def test_m1_atomic_write_and_stopped(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / snapshot.STATUS_FILE
            snapshot.write_json_atomic(path, self.build())
            self.assertTrue(json.loads(path.read_text('utf-8'))['running'])
            snapshot.write_json_atomic(path, snapshot.stopped_status(now=2000.0, version='0.2.21'))
            stopped = json.loads(path.read_text('utf-8'))
            self.assertFalse(stopped['running'])
            self.assertEqual([p.name for p in Path(directory).iterdir()], [snapshot.STATUS_FILE])


class MailboxTests(unittest.TestCase):
    """M6：信箱白名单、过期、控制开关。"""

    def test_m6_whitelist_expiry_and_permission(self):
        with TemporaryDirectory() as directory:
            ok = mailbox.submit(directory, 'mark', {'text': '卡住了'}, now=100.0)
            control = mailbox.submit(directory, 'stop_monitoring', now=100.0)
            old = mailbox.submit(directory, 'export_diagnostics', now=50.0)
            bad = mailbox.submit(directory, 'start_monitoring', now=100.0)
            taken = mailbox.take(directory, now=101.0, allow_control=False)
            self.assertEqual([(r.id, r.action, r.args) for r in taken], [(ok, 'mark', {'text': '卡住了'})])
            self.assertEqual(mailbox.read_reply(directory, control)['status'], 'not_allowed')
            self.assertEqual(mailbox.read_reply(directory, old)['status'], 'expired')
            self.assertEqual(mailbox.read_reply(directory, bad)['status'], 'rejected')
            self.assertEqual(mailbox.take(directory, now=102.0, allow_control=False), [])
            again = mailbox.submit(directory, 'stop_monitoring', now=103.0)
            self.assertEqual([r.id for r in mailbox.take(directory, now=103.5, allow_control=True)], [again])
            mailbox.reply(directory, again, True, '已停止监控')
            self.assertEqual(mailbox.read_reply(directory, again), {'id': again, 'status': 'done', 'ok': True,
                                                                   'message': '已停止监控'})
            self.assertIsNone(mailbox.read_reply(directory, again))


def synthetic_image():
    import test_leveling_route as route_tests
    case = route_tests.CharacterStateIntegrationTests('test_toc_state_survives_rescaling_and_unavailable_map_position')
    case.setUp()
    image = case.game_image()
    frame, _ = case.pipeline.decode(image)
    return case, image, frame


class FrameDumpTests(unittest.TestCase):
    """M7：只裁像素条区域、可重新解码、限频与保留。"""

    def test_m7_crop_and_round_trip(self):
        case, image, frame = synthetic_image()
        self.assertTrue(frame.ok, frame.status)
        with TemporaryDirectory() as directory:
            dumper = dump.FrameDumper(directory)
            path = dumper.dump(image, frame, {'note': '测试'}, now=1000.0)
            png = Path(path)
            self.assertEqual(png.suffix, '.png')
            loaded = dump.read_png(png)
            self.assertLess(loaded.width, image.width)
            self.assertLessEqual(loaded.width, 20)
            self.assertEqual(loaded.height, image.height)
            again, _ = case.pipeline.decode(loaded)
            self.assertTrue(again.ok, again.status)
            self.assertEqual(dict(again.values), dict(frame.values))
            meta = json.loads(png.with_suffix('.json').read_text('utf-8'))
            self.assertEqual(meta['note'], '测试')
            self.assertEqual(meta['fields'], dict(frame.values))

    def test_m7_rate_limit_and_retention(self):
        case, image, frame = synthetic_image()
        with TemporaryDirectory() as directory:
            dumper = dump.FrameDumper(directory, per_minute=3, keep=4)
            for index in range(3):
                dumper.dump(image, frame, {}, now=1000.0 + index)
            with self.assertRaises(dump.DumpRefused):
                dumper.dump(image, frame, {}, now=1010.0)
            for index in range(3):
                dumper.dump(image, frame, {}, now=1100.0 + index)
            self.assertEqual(len(list((Path(directory) / 'frames').glob('*.png'))), 4)
            self.assertEqual(len(list((Path(directory) / 'frames').glob('*.json'))), 4)

    def test_m7_without_valid_frame(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(dump.DumpRefused):
                dump.FrameDumper(directory).dump(None, None, {}, now=1.0)


class PacketTests(unittest.TestCase):
    """M10：状态包解码进快照，且不受测试打桩影响。"""

    def test_m10_packets_from_synthetic_frame(self):
        _, image, frame = synthetic_image()
        packets = snapshot.describe_packets(image, frame)
        for key in ('session', 'character', 'navigation', 'death', 'quest_pin', 'quest_dialog', 'mob', 'vendor',
                    'taxi', 'target_rejection', 'cast_feedback', 'level_progress'):
            self.assertIn(key, packets)
        self.assertEqual((packets['character']['map_id'], packets['character']['x'], packets['character']['y']),
                         (52, 32.12, 36.15))
        self.assertEqual(packets['character']['life'], 'alive')
        json.dumps(packets, ensure_ascii=False)

    def test_m10_patched_decoders_are_not_called(self):
        from unittest.mock import patch
        _, image, frame = synthetic_image()
        with patch('wowbuddy.engine.character_state.decode_character_state') as patched:
            packets = snapshot.describe_packets(image, frame)
        patched.assert_not_called()
        self.assertEqual(packets['character']['map_id'], 52)

    def test_m10_invalid_frame(self):
        self.assertIsNone(snapshot.describe_packets(None, None))
        self.assertIsNone(snapshot.describe_packets(object(), NS(ok=False)))


LOG = '''[10:00:00.000] === 日志文件：x ===
[10:00:01.000] 已开始监控 · 目标窗口 魔兽世界（0x1234）
[10:00:02.000] #33 正在移动：OFF 已确认不存在  (rgb=255,0,0)
[10:00:02.500] #34 正在移动：ON 已确认  (rgb=0,255,0)
[10:00:03.000] 转向统计 · 第 1/12 段：用时 9.0 秒，最大偏离 2.1 码，平均偏离 0.8 码，原地转向 1 次，转向修正 3 次，受阻 0 次
[10:00:04.000] 接回录制路线，从第 3 个停留点继续。
[10:00:05.000] 转向统计 · 第 2/12 段：用时 8.0 秒，最大偏离 4.0 码，平均偏离 1.5 码，原地转向 0 次，转向修正 5 次，受阻 1 次
'''


class ToolTests(unittest.TestCase):
    """M3、M8：MCP 工具函数（不经协议）。"""

    def setUp(self):
        import wowbuddy_mcp
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'logs').mkdir()
        older = self.root / 'logs' / 'monitor_20261115_090000.log'
        older.write_text('[09:00:00.000] 旧日志\n', 'utf-8')
        os.utime(older, (1, 1))
        self.log = self.root / 'logs' / 'monitor_20261115_100000.log'
        self.log.write_text(LOG, 'utf-8')
        self.now = [5000.0]
        self.tools = wowbuddy_mcp.AssistantTools(self.root, clock=lambda: self.now[0], sleep=self.advance)
        self.sleeps = []

    def tearDown(self):
        self.directory.cleanup()

    def advance(self, seconds):
        self.sleeps.append(seconds)
        self.now[0] += seconds
        hook = getattr(self, 'on_sleep', None)
        if hook:
            hook(len(self.sleeps))

    def status(self, **values):
        data = dict(updated_at=self.now[0], running=True, monitoring=True, unattended={'enabled': True, 'phase': 'camp'},
                    life='alive', patrol={'stop': '3/12', 'recorded': True}, decision={'selected': None})
        data.update(values)
        snapshot.write_json_atomic(self.root / snapshot.STATUS_FILE, data)

    def test_m3_status_and_staleness(self):
        self.assertFalse(self.tools.get_status()['available'])
        self.status()
        self.assertFalse(self.tools.get_status()['stale'])
        self.now[0] += 10
        self.assertTrue(self.tools.get_status()['stale'])

    def test_m3_tail_filters_noise_and_keyword(self):
        lines = self.tools.tail_log(lines=50)['lines']
        self.assertFalse(any('rgb=' in line for line in lines))
        self.assertIn('[10:00:04.000] 接回录制路线，从第 3 个停留点继续。', lines)
        self.assertEqual(len(self.tools.tail_log(lines=50, skip_noise=False)['lines']), 7)
        self.assertEqual(self.tools.tail_log(lines=2)['lines'][-1][:14], '[10:00:05.000]')
        self.assertEqual(len(self.tools.tail_log(contains='接回')['lines']), 1)

    def test_m3_search_since_and_list(self):
        found = self.tools.search_log('转向统计', since='10:00:04')
        self.assertEqual([line[:14] for line in found['lines']], ['[10:00:05.000]'])
        self.assertEqual([item['name'] for item in self.tools.list_logs()][0], self.log.name)

    def test_m3_steering_and_patrol(self):
        stats = self.tools.get_steering_stats()
        self.assertEqual([(s['segment'], s['max_deviation'], s['stalls']) for s in stats], [(1, 2.1, 0), (2, 4.0, 1)])
        self.status()
        self.assertEqual(self.tools.get_patrol()['stop'], '3/12')

    def test_m3_install_log_and_diagnostics(self):
        (self.root / 'addon-install.log').write_text('a\nb\nc\n', 'utf-8')
        self.assertEqual(self.tools.get_addon_install_log(lines=2), ['b', 'c'])
        (self.root / 'diagnostics').mkdir()
        with zipfile.ZipFile(self.root / 'diagnostics' / 'wowbuddy-diagnostics-1.zip', 'w') as archive:
            archive.writestr('manifest.json', '{"ok": 1}')
            archive.writestr('logs/a.log', '日志内容')
        self.assertEqual([d['name'] for d in self.tools.list_diagnostics()], ['wowbuddy-diagnostics-1.zip'])
        whole = self.tools.read_diagnostics('wowbuddy-diagnostics-1.zip')
        self.assertEqual(whole['members'], ['manifest.json', 'logs/a.log'])
        self.assertEqual(whole['content'], '{"ok": 1}')
        self.assertEqual(self.tools.read_diagnostics('wowbuddy-diagnostics-1.zip', 'logs/a.log')['content'], '日志内容')

    def test_m3_paths_outside_data_dir_are_refused(self):
        for name in ('../settings.ini', '..\\x.zip', 'C:/Windows/win.ini', 'diagnostics/../x.zip'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.tools.read_diagnostics(name)

    def test_m8_wait_for_phase_death_and_log(self):
        self.status()

        def change(count):
            if count == 2:
                self.status(unattended={'enabled': True, 'phase': 'travel'})
        self.on_sleep = change
        result = self.tools.wait_for('phase_change', timeout_s=30)
        self.assertTrue(result['happened'])
        self.assertEqual(result['status']['unattended']['phase'], 'travel')

        self.on_sleep = lambda count: self.status(life='dead') if count == 4 else None
        self.sleeps.clear()
        self.assertTrue(self.tools.wait_for('death', timeout_s=30)['happened'])

        def append(count):
            if count == 6:
                with self.log.open('a', encoding='utf-8') as handle:
                    handle.write('[10:00:09.000] 补给路线受阻，保留原营地和商人路点。\n')
        self.on_sleep = append
        self.sleeps.clear()
        stuck = self.tools.wait_for('stuck', timeout_s=30)
        self.assertTrue(stuck['happened'])
        self.assertIn('受阻', stuck['lines'][0])

        self.on_sleep = None
        self.sleeps.clear()
        timeout = self.tools.wait_for('log', timeout_s=5, pattern='永远不会出现')
        self.assertFalse(timeout['happened'])
        self.assertIn('status', timeout)
        with self.assertRaises(ValueError):
            self.tools.wait_for('teleport')

    def test_m8_requests_go_through_mailbox(self):
        self.status(control_allowed=True)

        def answer(count):
            for request in mailbox.take(self.root, now=self.now[0], allow_control=True):
                mailbox.reply(self.root, request.id, True, f'{request.action}:{request.args.get("text", "")}')
        self.on_sleep = answer
        self.assertEqual(self.tools.request('mark', text='卡住')['message'], 'mark:卡住')
        self.on_sleep = None
        self.assertEqual(self.tools.request('mark', text='没人理')['status'], 'no_response')
        for path in (self.root / 'control' / 'inbox').glob('*.json'):
            path.unlink()
        self.status(running=False)
        self.assertEqual(self.tools.request('stop_monitoring')['status'], 'not_running')


class ProtocolTests(unittest.TestCase):
    """M4：以 stdio 启动 MCP 服务，初始化并列出工具。"""

    def test_m4_stdio_lists_tools(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def run(directory):
            parameters = StdioServerParameters(command=sys.executable,
                                               args=[str(ROOT / 'tools' / 'wowbuddy_mcp.py'), '--data-dir', directory])
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    called = await session.call_tool('get_status', {})
                    return {tool.name for tool in listed.tools}, called

        with TemporaryDirectory() as directory:
            names, called = asyncio.run(asyncio.wait_for(run(directory), 60))
        self.assertTrue({'get_status', 'tail_log', 'search_log', 'list_logs', 'get_patrol', 'get_steering_stats',
                         'get_addon_install_log', 'list_diagnostics', 'read_diagnostics', 'explain_decision',
                         'wait_for', 'capture_frame', 'mark', 'stop_monitoring', 'stop_unattended',
                         'export_diagnostics'} <= names, names)
        self.assertFalse(called.is_error)


class WindowTests(unittest.TestCase):
    """M2、M6、M7、M9：离屏真实窗口中写快照、处理信箱。"""

    def run_window(self, exercise):
        import test_dev_tray
        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def status(self, window):
        return json.loads((Path(window.launch_options.data_dir) / snapshot.STATUS_FILE).read_text('utf-8'))

    def test_m2_status_written_and_stopped_on_close(self):
        def exercise(window):
            self.assertEqual(window._status_timer.interval(), 1000)
            self.assertTrue(window._status_timer.isActive())
            window._status_tick()
            first = self.status(window)
            self.assertTrue(first['running'])
            self.assertFalse(first['monitoring'])
            window.toggle_monitor()
            window._status_tick()
            self.assertTrue(self.status(window)['monitoring'])
            directory = Path(window.launch_options.data_dir)
            window.close()
            self.assertFalse(json.loads((directory / snapshot.STATUS_FILE).read_text('utf-8'))['running'])

        self.run_window(exercise)

    def test_m6_control_requests_in_window(self):
        from unittest.mock import patch

        def exercise(window):
            directory = window.launch_options.data_dir
            self.assertFalse(window._mcp_control_check.isChecked())
            window.toggle_monitor()
            refused = mailbox.submit(directory, 'stop_monitoring')
            window._status_tick()
            self.assertTrue(window.session.is_active())
            self.assertEqual(mailbox.read_reply(directory, refused)['status'], 'not_allowed')

            window._mcp_control_check.setChecked(True)
            self.assertTrue(window.settings.mcp_control_enabled())
            window.grind_check.setChecked(True)
            unattended = mailbox.submit(directory, 'stop_unattended')
            window._status_tick()
            self.assertFalse(window.grind_check.isChecked())
            self.assertTrue(mailbox.read_reply(directory, unattended)['ok'])
            self.assertTrue(window.session.is_active())

            stop = mailbox.submit(directory, 'stop_monitoring')
            window._status_tick()
            self.assertFalse(window.session.is_active())
            self.assertTrue(mailbox.read_reply(directory, stop)['ok'])
            self.assertIn('MCP 请求：停止监控（已执行）', window.ui.log_view.toPlainText())

            with patch('PySide6.QtGui.QDesktopServices.openUrl') as opened, \
                    patch('wowbuddy.diagnostic_export.find_clients', return_value=[]):
                export = mailbox.submit(directory, 'export_diagnostics')
                window._status_tick()
                opened.assert_not_called()
            reply = mailbox.read_reply(directory, export)
            self.assertTrue(reply['ok'], reply)
            self.assertTrue(Path(reply['path']).is_file())

            mark = mailbox.submit(directory, 'mark', {'text': '这里卡住'})
            window._mcp_control_check.setChecked(False)
            window._status_tick()
            self.assertTrue(mailbox.read_reply(directory, mark)['ok'])
            self.assertIn('==== 标记：这里卡住 ====', window.ui.log_view.toPlainText())
            self.assertEqual(self.status(window)['last_mark']['text'], '这里卡住')
            window.close()

        self.run_window(exercise)

    def test_m7_m9_capture_frame_and_decision_in_window(self):
        case, image, frame = synthetic_image()
        selected = candidate('寒冰箭', key='2', action='spell_116')
        stopped = candidate('已跳过目标', reason='目标等级过高', stop=True)
        tick = NS(decision=decision(selected, stopped, rejection='目标等级过高'), selected=selected)

        def exercise(window):
            directory = window.launch_options.data_dir
            missing = mailbox.submit(directory, 'capture_frame', {'note': '无帧'})
            window._status_tick()
            self.assertFalse(mailbox.read_reply(directory, missing)['ok'])

            window._last_result = NS(status='ok', capture=NS(image=image), tick=NS(decision=NS(frame=frame),
                                                                                    selected=None))
            request = mailbox.submit(directory, 'capture_frame', {'note': '卡在树边'})
            window._status_tick()
            reply = mailbox.read_reply(directory, request)
            self.assertTrue(reply['ok'], reply)
            self.assertEqual(dump.read_png(reply['path']).height, image.height)
            meta = json.loads(Path(reply['path']).with_suffix('.json').read_text('utf-8'))
            self.assertEqual(meta['packets']['character']['map_id'], 52)
            self.assertEqual(self.status(window)['packets']['character']['map_id'], 52)

            window._last_result = NS(status='ok', capture=NS(image=image), tick=tick)
            window._status_tick()
            explained = self.status(window)['decision']
            self.assertEqual(explained['selected']['label'], '寒冰箭')
            self.assertEqual([c['label'] for c in explained['candidates']], ['寒冰箭', '已跳过目标'])
            self.assertEqual(explained['target_rejection'], '目标等级过高')
            self.assertIn('player_hp', explained['fields'])
            window.close()

        self.run_window(exercise)


if __name__ == '__main__':
    unittest.main()
