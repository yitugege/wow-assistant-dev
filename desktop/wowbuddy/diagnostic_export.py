"""一键导出诊断：把桌面日志、诊断文件与游戏中本插件的 SavedVariables 打包成一个 zip。

设计与验收见 docs/design/20261115-diagnostic-export.md。
- 只读来源文件；zip 写在数据目录的 diagnostics/ 下，不在数据目录以外写文件，不联网。
- 所有成员名与内容中，账号目录名替换为 <ACCOUNT-n>，本机用户名替换为 <USER>（按词边界、不区分大小写）。
  角色名、服务器名与路径中的其他部分仍保留。
- 单个文件超过 max_file_bytes 只保留末尾；未压缩总量超过 max_total_bytes 时按收录顺序跳过后面的成员
  （顺序：插件 SavedVariables、安装记录、数据目录根下的诊断文件、监控日志）。
本模块属于入口层：汇总 addons、update 与设置的数据，不被下层导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import zipfile

from wowbuddy.dev_version import VERSION

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MONITOR_LOG_LIMIT = 5
EXPORT_DIRECTORY = 'diagnostics'
DESKTOP_SUFFIXES = ('.log', '.old', '.ini', '.json', '.txt')
EXPECTED_DESKTOP_FILES = ('startup.log', 'startup-error.log', 'settings.ini')
SAVED_VARIABLES_NAME = 'WowBuddyDev.lua'


@dataclass
class ExportResult:
    path: Path
    members: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)
    truncated: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def default_user_names(environment=None) -> tuple[str, ...]:
    environment = os.environ if environment is None else environment
    names = [environment.get('USERNAME', ''), Path.home().name]
    result = []
    for name in names:
        if name and name.casefold() not in {item.casefold() for item in result}:
            result.append(name)
    return tuple(result)


def redact(text: str, accounts: dict, users) -> str:
    """把账号名替换为代号、用户名替换为 <USER>；只替换前后不是字母数字的完整出现。"""
    replacements = [(name, code) for name, code in accounts.items() if name]
    replacements += [(name, '<USER>') for name in users if name]
    for name, code in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        pattern = r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])'
        text = re.sub(pattern, lambda _match, code=code: code, text, flags=re.IGNORECASE)
    return text


def find_clients(settings, *, running_executable='', search_roots=None):
    """按设置、正在运行的客户端与常见安装目录（与开发版窗口相同）发现游戏目录。

    固定不传窗口环境，因此不受 WOWBUDDY_NO_GAME_SCAN 影响。search_roots 为 None 时使用 common_roots()。
    """
    from wowbuddy.addons.dev_game_paths import common_roots, discover_clients
    roots = common_roots() if search_roots is None else search_roots
    return discover_clients(settings, running_executable=running_executable, search_roots=roots,
                            environment=None)


def _installed_name(client: Path) -> str:
    from wowbuddy.update.dev_addon_update import installed_name
    try:
        return installed_name(client / 'Interface' / 'AddOns')
    except OSError:
        return ''


def _account_saved_variables(client: Path, addon_name: str):
    accounts = client / 'WTF' / 'Account'
    if not addon_name or not accounts.is_dir():
        return []
    found = []
    for account in sorted(accounts.iterdir(), key=lambda p: p.name.casefold()):
        saved = account / 'SavedVariables' / f'{addon_name}.lua'
        if account.is_dir() and saved.is_file():
            found.append((account.name, saved))
    return found


def _desktop_sources(data_dir: Path):
    files = sorted((p for p in data_dir.iterdir() if p.is_file() and p.suffix.lower() in DESKTOP_SUFFIXES),
                   key=lambda p: p.name.casefold())
    sources = [(f'desktop/{p.name}', p, 'desktop') for p in files]
    logs = data_dir / 'logs'
    if logs.is_dir():
        monitor = sorted((p for p in logs.glob('monitor_*.log') if p.is_file()),
                         key=lambda p: (p.stat().st_mtime, p.name))[-MONITOR_LOG_LIMIT:]
        sources += [(f'desktop/logs/{p.name}', p, 'monitor_log') for p in sorted(monitor, key=lambda p: p.name)]
    return sources


def _target_path(data_dir: Path, now: datetime) -> Path:
    directory = data_dir / EXPORT_DIRECTORY
    directory.mkdir(exist_ok=True)
    stem = 'wowbuddy-diagnostics-' + now.strftime('%Y%m%d-%H%M%S')
    path, counter = directory / f'{stem}.zip', 1
    while path.exists():
        counter += 1
        path = directory / f'{stem}-{counter}.zip'
    return path


def _open_settings(data_dir: Path):
    from wowbuddy.settings import open_ini_settings
    return open_ini_settings(str(data_dir / 'settings.ini'))


def run_export_command(data_dir, *, running_executable='') -> int:
    """命令行 --export-diagnostics：发现客户端、导出，并把结果写入 diagnostics-export.json。成功返回 0。"""
    data_dir = Path(data_dir).absolute()
    data_dir.mkdir(parents=True, exist_ok=True)
    users = default_user_names()
    report = {'ok': False}
    try:
        clients = find_clients(_open_settings(data_dir), running_executable=running_executable)
        result = export_diagnostics(data_dir, clients, user_names=users)
        report.update(ok=True, path=str(result.path), members=sorted(result.members),
                      missing=result.missing, truncated=result.truncated, skipped=result.skipped)
    except Exception as error:  # 报告写入后返回失败码，不让命令行异常退出
        report['error'] = redact(f'{type(error).__name__}: {error}', {}, users)
    # 本报告只留在本机：path 保持原样以便打开；成员名已是脱敏后的名字。
    (data_dir / 'diagnostics-export.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return 0 if report['ok'] else 1


def export_diagnostics(data_dir, clients, *, now=None, user_names=None,
                       max_file_bytes=MAX_FILE_BYTES, max_total_bytes=MAX_TOTAL_BYTES) -> ExportResult:
    data_dir = Path(data_dir).absolute()
    now = now or datetime.now()
    users = default_user_names() if user_names is None else tuple(user_names)
    if not data_dir.is_dir():
        raise FileNotFoundError(f'数据目录不存在：{data_dir}')

    client_entries, saved_sources, account_names = [], [], []
    for index, client in enumerate((Path(c).absolute() for c in clients), 1):
        addon_name = _installed_name(client)
        saved = _account_saved_variables(client, addon_name)
        account_names += [name for name, _ in saved if name not in account_names]
        client_entries.append((index, client, addon_name, saved))
    codes = {name: f'<ACCOUNT-{number}>' for number, name in enumerate(sorted(account_names, key=str.casefold), 1)}

    sources = []
    clients_manifest = []
    for index, client, addon_name, saved in client_entries:
        clients_manifest.append({'index': index, 'path': redact(str(client), codes, users),
                                 'addon_directory': addon_name,
                                 'accounts': [codes[name] for name, _ in saved]})
        for name, path in saved:
            sources.append((f'clients/{index}/savedvariables/{codes[name]}/{SAVED_VARIABLES_NAME}', path,
                            'saved_variables'))
        record = client / '.wowbuddy-install.json'
        if addon_name and record.is_file():
            sources.append((f'clients/{index}/install.json', record, 'install_record'))
    sources += _desktop_sources(data_dir)

    target = _target_path(data_dir, now)
    result = ExportResult(target)
    result.missing = [name for name in EXPECTED_DESKTOP_FILES if not (data_dir / name).is_file()]
    total = 0
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for member, path, category in sources:
            try:
                raw = path.read_bytes()
            except OSError as error:
                result.skipped.append(member)
                result.members[member] = {'category': category, 'error': redact(str(error), codes, users)}
                continue
            data = redact(raw.decode('utf-8', 'surrogateescape'), codes, users).encode('utf-8', 'surrogateescape')
            if len(data) > max_file_bytes:
                data = data[-max_file_bytes:]
                result.truncated.append(member)
            if total + len(data) > max_total_bytes:
                result.skipped.append(member)
                continue
            total += len(data)
            archive.writestr(member, data)
            result.members[member] = {'category': category, 'bytes': len(data)}
        manifest = {
            'product': 'wowbuddy-diagnostics', 'format': 1, 'client_version': VERSION,
            'exported_at': now.isoformat(timespec='seconds'), 'game_verified': False,
            'members': {name: info for name, info in result.members.items() if 'bytes' in info},
            'missing': result.missing, 'truncated': result.truncated, 'skipped': result.skipped,
            'clients': clients_manifest,
            'redactions': ['账号目录名替换为 <ACCOUNT-n>', '本机用户名替换为 <USER>',
                           '角色名、服务器名与路径其他部分未替换'],
            'limits': {'max_file_bytes': max_file_bytes, 'max_total_bytes': max_total_bytes,
                       'monitor_logs': MONITOR_LOG_LIMIT},
        }
        archive.writestr('manifest.json', redact(json.dumps(manifest, ensure_ascii=False, indent=2), codes, users))
    return result
