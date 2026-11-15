"""使用隔离构建驱动实际 Qt 按钮，从 GitHub 下载并重启官方单文件。"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from check_frozen_outer import ROOT, run
from wowbuddy.update.github_outer import check_latest, verify_outer
from wowbuddy.legacy.launcher import BUSINESS_EXE, release_directory
from wowbuddy.release_identity import CACHE_NAMESPACE, file_sha256, read_release_identity


TRACE_ENV = 'WOWBUDDY_MANUAL_UPDATE_TEST_TRACE'
DRIVER = """
import json
import os
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def attach(window, path):
    app = QApplication.instance()
    path = Path(path)
    events = []
    timer = QTimer(window)
    step = 'check'

    def record(event, **fields):
        events.append({'event': event, **fields})
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(events, ensure_ascii=False), 'utf-8')
        temp.replace(path)

    def finished():
        result = getattr(window, '_outer_update_result', None)
        record('old_quit', phase=result.phase if result else None,
               restart_started=bool(result and result.restart_started),
               monitor_active=window.session.is_active())

    def advance():
        nonlocal step
        try:
            if step == 'check':
                assert not window.session.is_active() and not window.watch_timer.isActive()
                assert not window.ui.auto_update_check.isChecked()
                assert getattr(window, '_client_update_future', None) is None
                assert window.ui.update_check_button.isEnabled()
                assert window._outer_update_target is not None
                window.ui.update_check_button.click()
                assert window._client_update_phase == 'check' and window._client_update_manual
                record('check_clicked', old_pid=os.getpid())
                step = 'wait_check'
            elif step == 'wait_check' and getattr(window, '_client_update_consumed', False):
                info = window._client_update_info
                assert info.get('kind') == 'outer' and info.get('has_update'), window.ui.update_status.text()
                button = window.ui.update_apply_button
                assert button.isVisible() and button.isEnabled() and button.text() == '下载更新包'
                assert not window._client_auto_chain
                record('update_offered', current=info['current_version'], version=info['version'],
                       package_url=info['package_url'], label=button.text())
                # The old GUI has already parsed its command line. Only the
                # restarted published executable receives this closing self-test.
                sys.argv.append('--desktop-selftest')
                button.click()
                assert window._client_update_phase == 'download'
                assert not button.isEnabled()
                record('download_clicked')
                step = 'wait_install'
            elif step == 'wait_install':
                result = getattr(window, '_outer_update_result', None)
                if result is not None:
                    assert result.restart_started, result.text
                    timer.stop()
                elif getattr(window, '_client_update_consumed', False):
                    assert getattr(window, '_client_update_staged', None), window.ui.update_status.text()
        except Exception as error:
            timer.stop()
            record('error', detail=str(error) or repr(error), step=step)
            app.exit(91)

    app.aboutToQuit.connect(finished)
    timer.timeout.connect(advance)
    timer.start(125)
"""


def stage_fixture(root, version):
    stage = root / 'fixture'
    stage.mkdir()
    for name in ('addon', 'assets', 'desktop'):
        shutil.copytree(ROOT / name, stage / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('run_dev.py', 'run_outer_dev.py'):
        shutil.copy2(ROOT / name, stage / name)
    scripts = stage / 'tools'
    scripts.mkdir()
    for name in ('build_addon.py', 'build_source_guard.py', 'build_desktop.py', 'build_outer_dev.py'):
        shutil.copy2(ROOT / 'tools' / name, scripts / name)

    version_path = stage / 'desktop/wowbuddy/dev_version.py'
    # 只替换版本行，保留同文件中的 REPOSITORY 等其他常量。
    original = version_path.read_text('utf-8')
    if len(re.findall(r'^VERSION=.*$', original, flags=re.M)) != 1:
        raise ValueError('dev_version.py 版本行位置已变化')
    version_path.write_text(re.sub(r'^VERSION=.*$', f'VERSION={version!r}', original, flags=re.M), 'utf-8')
    entry = stage / 'run_dev.py'
    content = entry.read_text('utf-8')
    marker = '    def after_main(window):\n'
    if content.count(marker) != 1:
        raise ValueError('启动后回调位置已变化')
    injected = f"""        if os.environ.get({TRACE_ENV!r}):
            from manual_update_test_driver import attach
            attach(window, os.environ[{TRACE_ENV!r}])
"""
    entry.write_text(content.replace(marker, marker + injected), 'utf-8')
    (stage / 'manual_update_test_driver.py').write_text(DRIVER, 'utf-8')
    for script in ('build_desktop', 'build_outer_dev'):
        log = root / (script + '.log')
        with log.open('wb') as output:
            result = subprocess.run([sys.executable, str(scripts / (script + '.py'))],
                                    cwd=stage, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=150)
        if result.returncode:
            raise RuntimeError(f'{script} 失败，见 {log}')
    return stage / 'dist/outer/WowBuddyDev-Outer.exe'


def check(current='0.2.7', expected='0.2.8'):
    from PySide6.QtCore import QSettings

    release = check_latest(current_version=current)
    if not release['has_update'] or release['version'] != expected:
        raise ValueError(f'期望 GitHub v{expected}，实际为 v{release["version"]}')
    manifest = release['manifest']
    root = Path(tempfile.mkdtemp(prefix='manual-outer-update-', dir=ROOT / '.local')).resolve()
    print(json.dumps({'root': str(root), 'expected': expected}), flush=True)
    old = stage_fixture(root, current)
    old_identity = read_release_identity(old)
    assert old_identity.business_sha256 != manifest['business_sha256']
    target = root / '手动更新测试.exe'
    shutil.copy2(old, target)
    local = root / 'localappdata'
    local.mkdir()
    stable = root / '.local'
    stable.mkdir()
    ini = stable / 'settings.ini'
    selection = '1482|冰霜|官方 · 练级（冰霜 · 单体+AOE）'
    settings = QSettings(str(ini), QSettings.IniFormat)
    settings.setValue('update/autoCheck', False)
    settings.setValue('hub/selection', selection)
    settings.setValue('hub/by-spec/1482', selection)
    settings.setValue('audit/sentinel', '手动更新保留')
    settings.sync()
    del settings

    trace = root / 'manual-clicks.json'
    env = dict(os.environ, LOCALAPPDATA=str(local), PYINSTALLER_RESET_ENVIRONMENT='1',
               QT_QPA_PLATFORM='offscreen', WOWBUDDY_NO_GAME_SCAN='1')
    env[TRACE_ENV] = str(trace)
    env.pop('WOWBUDDY_UPDATE_NO_RESTART', None)
    try:
        outcome = run(target, root, env, arguments=['--no-watch', '--no-update', '--no-stealth'],
                      timeout_seconds=175)
    except (AssertionError, TimeoutError) as error:
        detail = trace.read_text('utf-8') if trace.is_file() else 'test driver produced no trace'
        raise RuntimeError(detail) from error
    events = json.loads(trace.read_text('utf-8'))
    assert [entry['event'] for entry in events] == [
        'check_clicked', 'update_offered', 'download_clicked', 'old_quit']
    assert events[1]['current'] == current and events[1]['version'] == expected
    assert events[1]['package_url'] == release['package_url']
    assert events[-1]['phase'] == 'restart_started' and events[-1]['restart_started']
    assert not events[-1]['monitor_active']
    assert outcome['processes_observed'] >= 6

    downloaded = list((root / 'WowBuddyDev-updates').glob('outer-download-*/WowBuddyDev-Outer.exe'))
    assert len(downloaded) == 1 and file_sha256(downloaded[0]) == manifest['sha256']
    new_identity = verify_outer(target, manifest)
    cache = Path(release_directory(str(local / CACHE_NAMESPACE / new_identity.cache_key), None))
    assert file_sha256(cache / BUSINESS_EXE) == manifest['business_sha256']
    # The released payload already contains a desktop-selftest report from build.
    # The restarted process overwrites it with a self-test from this cache path.
    report = json.loads((cache / 'desktop-selftest.json').read_text('utf-8'))
    assert Path(report['assets']).resolve().is_relative_to(cache.resolve())
    assert report['passed'] and report['frozen'] and report['window_closed'] and report['temporary_removed']
    assert not report['monitor_active'] and not report['watch_timer_active']
    assert not (stable / 'update-now.json').exists() and not list(stable.glob('logs/monitor_*.log'))

    settings = QSettings(str(ini), QSettings.IniFormat)
    assert not settings.value('update/autoCheck', True, type=bool)
    assert settings.value('hub/selection') == settings.value('hub/by-spec/1482') == selection
    assert settings.value('audit/sentinel') == '手动更新保留'
    assert int(settings.value('update/lastCheckMs', 0)) > 0
    startup = (stable / 'startup.log').read_text('utf-8')
    assert startup.count('正常退出，返回码 0') >= 2
    return {
        'passed': True, 'test_root': str(root), 'previous_fixture_version': current,
        'published_version': expected, 'old_fixture_sha256': file_sha256(old),
        'replaced_sha256': file_sha256(target), 'job': outcome, 'events': events,
        'release_url': release['release_url'], 'settings_preserved': True,
        'fresh_published_frozen_selftest': True, 'game_monitor_started': False,
        'normal_restarted_window_verified': False, 'production_source_instrumented': False,
    }


if __name__ == '__main__':
    result = check(*sys.argv[1:])
    path = ROOT / 'dist/frozen-manual-outer-update.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(result, ensure_ascii=True))
