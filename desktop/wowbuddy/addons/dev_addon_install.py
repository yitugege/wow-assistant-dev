"""独立插件包的本地安装；固定目录、逐文件校验、更新前备份。"""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import tempfile
import uuid
import zipfile
import re

NAME = 'WowBuddyDev'
# 开发版认可的客户端执行文件（含官方经典服），与 win32.game_windows.GAME_EXECUTABLES 一致（tests/test_client_recognition.py）。
CLIENT_EXECUTABLES = ('Wow.exe', 'WowB.exe', 'WowClassic.exe', 'WowClassicB.exe')
PRODUCT = 'wowbuddy-dev'


def random_addon_name(name):
    """发布包随机命名的插件目录：w + 12 位小写十六进制。"""
    return re.fullmatch(r'w[0-9a-f]{12}',name) is not None


def valid_install_record(record):
    """安装记录属于本产品，且记录的目录名为固定名或发布包随机名。"""
    name=record.get('addon_directory','')
    return record.get('product')==PRODUCT and (name==NAME or random_addon_name(name))


def package_version(package):
    """插件包清单中的版本号；清单缺失或没有版本时返回空串。"""
    try:
        value = json.loads(Path(package).with_suffix('.manifest.json').read_text('utf8')).get('version', '')
    except (OSError, ValueError, AttributeError):
        return ''
    return value if isinstance(value, str) else ''


def installed_version(addons):
    """AddOns 目录对应安装记录中的版本号（标准路径记录在客户端根目录，其他目录记录在本目录）；未知返回空串。"""
    addons = Path(addons)
    standard = addons.name.lower() == 'addons' and addons.parent.name.lower() == 'interface'
    record_path = (addons.parent.parent if standard else addons) / '.wowbuddy-install.json'
    try:
        record = json.loads(record_path.read_text('utf8'))
    except (OSError, ValueError):
        return ''
    value = record.get('version', '') if isinstance(record, dict) and valid_install_record(record) else ''
    return value if isinstance(value, str) else ''


def is_newer(candidate, current):
    """candidate 版本号是否高于 current（按数字段比较）。"""
    from wowbuddy.update.updater import compare_versions
    return compare_versions(candidate, current) > 0


def plain_path(path):
    """安装边界内不接受符号链接或Windows目录联接。"""
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError(f'安装路径不能包含链接或目录联接：{part}')


_plain_path = plain_path


def is_reparse_point(path):
    """符号链接、目录联接等重解析点（Windows 属性 0x400）；不跟随链接，路径不存在时抛 OSError。"""
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)

_RESERVED_NAMES = {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}


def member_relative(name, root):
    """ZIP 成员名须为 root/... 的规范 POSIX 相对路径，返回去掉 root 后的相对路径；不合规返回 None。

    各段不得为 . / .. / .local，不得以空格或点结尾，不得含 Windows 非法字符、控制字符或保留设备名。
    """
    path=PurePosixPath(name)
    if (len(path.parts)<2 or path.parts[0]!=root or path.as_posix()!=name
            or '\\' in name or any(part in ('.','..','.local') or part.endswith((' ','.'))
                or any(c in part for c in ':<>"|?*') or any(ord(c)<32 for c in part)
                or part.split('.')[0].upper() in _RESERVED_NAMES for part in path.parts)):
        return None
    return Path(*path.parts[1:])


def client_directory(selected):
    path = Path(selected).absolute()
    _plain_path(path)
    if path.name.lower() == 'addons' and path.parent.name.lower() == 'interface':
        path = path.parent.parent
    if not path.is_dir() or not any((path/name).is_file() for name in CLIENT_EXECUTABLES):
        raise ValueError('请选择包含' + '、'.join(CLIENT_EXECUTABLES) + '之一的客户端目录，或该客户端的Interface/AddOns目录')
    return path.resolve()


def read_package(package, *, with_metadata=False):
    package = Path(package)
    data = package.read_bytes()
    manifest = json.loads(package.with_suffix('.manifest.json').read_text('utf8'))
    addon_name=manifest.get('addon_directory',NAME)
    if addon_name != NAME and (not random_addon_name(addon_name) or manifest.get('product')!=PRODUCT):
        raise ValueError('插件包目录或产品身份无效')
    if hashlib.sha256(data).hexdigest() != manifest['sha256']:
        raise ValueError('插件ZIP摘要不符，请重新构建插件包')
    members = manifest['members']
    payload = {}
    folded = set()
    with zipfile.ZipFile(BytesIO(data)) as archive:
        if len(archive.infolist()) != len(members) or set(archive.namelist()) != set(members):
            raise ValueError('插件ZIP成员与清单不一致')
        for item in archive.infolist():
            name = item.filename
            relative = member_relative(name, addon_name)
            if (item.is_dir() or relative is None
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                    or name.casefold() in folded):
                raise ValueError(f'插件包包含非法路径：{name}')
            folded.add(name.casefold())
            content = archive.read(item)
            if hashlib.sha256(content).hexdigest() != members[name]:
                raise ValueError(f'插件文件摘要不符：{name}')
            payload[relative] = content
    if Path(f'{addon_name}.toc') not in payload:
        raise ValueError('插件包缺少同名TOC')
    return (addon_name,payload) if with_metadata else payload


def install_package(package, selected):
    client = client_directory(selected)
    addons = client/'Interface'/'AddOns'
    backup_root = client/'WowBuddyDev-backups'
    record_path=client/'.wowbuddy-install.json'
    return _install_package(package,addons,backup_root,record_path)


def install_addons_directory(package, selected):
    """原CLI直接目录语义：不把传入目录归一化为游戏根目录。"""
    addons=Path(selected).absolute()
    # 标准AddOns路径与GUI共享身份记录；其他显式目录把状态留在本目录中。
    if addons.name.lower()=='addons' and addons.parent.name.lower()=='interface':
        state=addons.parent.parent
    else:
        state=addons
    return _install_package(package,addons,state/'WowBuddyDev-backups',state/'.wowbuddy-install.json')


def _install_package(package, addons, backup_root, record_path):
    addon_name,payload = read_package(package,with_metadata=True)
    previous=addons/NAME
    if record_path.exists():
        record=json.loads(record_path.read_text('utf8'))
        prior=record.get('addon_directory','')
        if not valid_install_record(record):
            raise ValueError('上次安装记录无效；不修改无法识别的目录')
        previous=addons/prior
    elif not previous.exists() and addons.is_dir():
        # 手动解压的随机发布包没有安装记录；用包内产品标记恢复唯一身份。
        matches=[]
        for candidate in addons.iterdir():
            if not random_addon_name(candidate.name):
                continue
            _plain_path(candidate)
            toc=candidate/(candidate.name+'.toc')
            if candidate.is_dir() and toc.is_file():
                _plain_path(toc)
                try:
                    lines=toc.read_text('utf-8-sig').splitlines()
                except UnicodeDecodeError:
                    # 本产品发布TOC固定UTF-8；其他插件的旧编码不是安装错误。
                    continue
                if '## X-WowBuddy-Product: wowbuddy-dev' in {line.strip() for line in lines}:
                    matches.append(candidate)
        if len(matches)>1:
            raise ValueError('发现多个本产品随机插件目录，无法确定更新身份；未修改目录')
        if matches:
            previous=matches[0]
    # 首次安装采用发布包随机目录；已有安装（包括固定名开发版）保持本机身份。
    # 不改目录名，才能延续游戏启用状态及按插件名关联的存档文件。
    installed_name=previous.name if record_path.exists() or previous.exists() else addon_name
    if installed_name!=addon_name:
        payload[Path(f'{installed_name}.toc')]=payload.pop(Path(f'{addon_name}.toc'))
    target=addons/installed_name
    for path in (addons, target, previous, backup_root, record_path):
        _plain_path(path)
    if target.exists() and not target.is_dir():
        raise ValueError(f'插件目标不是目录：{target}')
    if target.exists() and target!=previous:
        raise ValueError('随机目标目录已被占用，拒绝覆盖')
    if previous.exists() and not (previous/f'{previous.name}.toc').is_file():
        raise ValueError('旧开发插件缺少同名TOC，拒绝移动')
    addons.mkdir(parents=True, exist_ok=True)
    backup = None
    with tempfile.TemporaryDirectory(prefix='.wowbuddy-install-', dir=addons) as temporary:
        stage = Path(temporary)/installed_name
        stage.mkdir()
        for relative, content in payload.items():
            destination = stage/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        if any((stage/relative).read_bytes() != content for relative, content in payload.items()):
            raise OSError('暂存插件文件验证失败')
        # 先准备安装记录；替换失败可同时恢复旧目录和原记录。
        staged_record=Path(temporary)/'install-record.json'
        record={'product':'wowbuddy-dev','addon_directory':installed_name}
        version=package_version(package)
        if version:
            record['version']=version
        staged_record.write_text(json.dumps(record,ensure_ascii=False),'utf8')
        if previous.exists():
            backup_root.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup = backup_root/f'{stamp}-{uuid.uuid4().hex}'
            previous.rename(backup)
        try:
            stage.rename(target)
            staged_record.replace(record_path)
        except OSError:
            if target.exists() and not stage.exists():
                target.rename(stage)
            if backup is not None:
                backup.rename(previous)
            raise
    return {'target': str(target), 'backup': str(backup) if backup else None,
            'files': len(payload), 'addon_directory':installed_name,'game_verified': False,
            'cleanup_deleted':0,'cleanup_notes':'其他插件目录保留。','version':package_version(package)}
