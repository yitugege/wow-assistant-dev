"""真实Qt监控入口贯穿抓屏选择、控制器、调度与投递记账；系统后端全部替换。"""
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'));sys.path.insert(0,str(ROOT/'tests/core'))
import test_dev_tray
from test_old_protocol import render_old
from test_pipeline import render_readable
from wowbuddy.capture import WindowCapture, Rect
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.rotation_selection import Profile
from wowbuddy.candidates import parse_rules


class MonitorProtocolTests(unittest.TestCase):
    def test_new_protocol_high_bit_to_dispatch_and_stopping(self):
        for protocol,fallback in (('old',False),('old',True),('readable',False),('readable',True)):
            with self.subTest(protocol=protocol,printwindow_fallback=fallback):
                def exercise(window):
                    def frame(bits,master=True):
                        values={'addon_version_code':DEV_VERSION,'action_avail':bits,
                            'master_switch':0x00ff00 if master else 0xff0000,
                            'player_casting':0xff0000,'gcd':0xff0000,
                            'player_in_combat':0xff0000,'druid_talents':0x0a0000}
                        return render_old(1484,values)[0] if protocol=='old' else render_readable(1484,values)
                    state={'image':frame(0x800000),'minimized':False,'time':100000}
                    windows=SimpleNamespace(is_iconic=lambda hwnd:state['minimized'],
                        window_rect=lambda hwnd:Rect(0,0,64,1500),
                        client_rect=lambda hwnd:Rect(0,0,64,1500),
                        client_to_screen=lambda hwnd:(0,0))
                    dxgi=SimpleNamespace(capture=lambda rect,width:None if fallback else state['image'])
                    prints=SimpleNamespace(capture=lambda *args:state['image'])
                    window.loop.capture=WindowCapture(windows,dxgi,prints)
                    sent=[]
                    def send(key,**kwargs):sent.append(key);return True
                    sender=SimpleNamespace(send=send,backend=SimpleNamespace(now_ms=lambda:state['time'],Sleep=lambda ms:None),
                        status='测试后端投递成功',channel='test')
                    window.sender=window.dispatcher.sender=sender
                    window.scheduler.clock_ms=lambda:state['time']
                    window.session.monotonic_ms=lambda:state['time']
                    window.controller.prepare(state['image'])
                    profile=Profile(-1,1484,'德鲁伊','','协议集成测试','','','','',
                        tuple(parse_rules([
                            {'action':'spell_1126','when':['avail',1126]},
                            {'action':'spell_17056','when':['avail',17056]}])))
                    window.controller.selection=replace(window.controller.selection,active_profile=profile)
                    window.toggle_monitor()
                    state['time']+=800
                    result=window.poll_once()
                    self.assertEqual(result.capture.backend,'printwindow' if fallback else 'dxgi')
                    self.assertIsNotNone(result.tick)
                    self.assertTrue(result.tick.decision.frame.ok)
                    self.assertEqual([c.action for c in result.tick.decision.candidates],['spell_17056'])
                    self.assertEqual(sent,['SHIFT-F2'])
                    self.assertEqual(window.dispatcher.state.success_count,1)
                    self.assertEqual(window.ui.sent_label.text(),'0')
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 1 条')
                    self.assertEqual(window.ui.fps_label.text(),'1.3')
                    self.assertIn('1.3 fps',window.ui.frame_status_label.text())
                    self.assertEqual(window.session.state.decoded_fields['action_avail'],'16777217')
                    state['time']+=5000
                    state['image']=frame(0)
                    result=window.poll_once()
                    self.assertEqual(result.tick.decision.candidates,())
                    self.assertEqual(window.ui.sent_label.text(),'1')
                    self.assertEqual(sent,['SHIFT-F2'])
                    state['time']+=5000
                    state['image']=frame(0xffffff,False)
                    window.poll_once()
                    self.assertEqual(sent,['SHIFT-F2'])
                    state['minimized']=True
                    result=window.poll_once()
                    self.assertEqual(result.capture.status,'minimized')
                    self.assertEqual(sent,['SHIFT-F2'])
                    state['minimized']=False
                    state['time']+=5000
                    window.poll_once()
                    restored_status=window.ui.status_label.text()
                    self.assertNotIn('最小化',restored_status)
                    window.watch_once()
                    self.assertEqual(window.ui.status_label.text(),restored_status)
                    window.toggle_monitor()
                    result=window.poll_once()
                    self.assertEqual(result.status,'inactive')
                    # 原0a2070仅清内部计数；089570实际尝试主键才刷新累计文案。
                    window.toggle_monitor()
                    state['time']+=5000
                    state['minimized']=False
                    window.poll_once()
                    self.assertEqual(window.dispatcher.state.success_count,0)
                    self.assertEqual(window.ui.sent_label.text(),'0')
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 1 条')
                    state['image']=frame(0x800000)
                    sender.send=lambda *args,**kwargs:False
                    state['time']+=5000
                    result=window.poll_once()
                    self.assertEqual(result.tick.dispatch.status,'failed')
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 0 条')
                test_dev_tray.TrayTests.run_window(self,False,exercise)
