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


def _plain_path(path):
    """安装边界内不接受符号链接或Windows目录联接。"""
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError(f'安装路径不能包含链接或目录联接：{part}')


def client_directory(selected):
    path = Path(selected).absolute()
    _plain_path(path)
    if path.name.lower() == 'addons' and path.parent.name.lower() == 'interface':
        path = path.parent.parent
    if not path.is_dir() or not any((path/name).is_file() for name in ('Wow.exe','WowB.exe')):
        raise ValueError('请选择包含Wow.exe或WowB.exe的客户端目录，或该客户端的Interface/AddOns目录')
    return path.resolve()


def read_package(package, *, with_metadata=False):
    package = Path(package)
    data = package.read_bytes()
    manifest = json.loads(package.with_suffix('.manifest.json').read_text('utf8'))
    addon_name=manifest.get('addon_directory',NAME)
    if addon_name != NAME and (not re.fullmatch(r'w[0-9a-f]{12}',addon_name) or manifest.get('product')!='wowbuddy-dev'):
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
            path = PurePosixPath(name)
            if (item.is_dir() or len(path.parts) < 2 or path.parts[0] != addon_name
                    or name != path.as_posix() or '\\' in name
                    or any(p in ('.', '..') or ':' in p or p.endswith((' ', '.')) for p in path.parts)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                    or name.casefold() in folded):
                raise ValueError(f'插件包包含非法路径：{name}')
            folded.add(name.casefold())
            content = archive.read(item)
            if hashlib.sha256(content).hexdigest() != members[name]:
                raise ValueError(f'插件文件摘要不符：{name}')
            payload[Path(*path.parts[1:])] = content
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
        if record.get('product')!='wowbuddy-dev' or (prior!=NAME and not re.fullmatch(r'w[0-9a-f]{12}',prior)):
            raise ValueError('上次安装记录无效；不修改无法识别的目录')
        previous=addons/prior
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
        staged_record.write_text(json.dumps({'product':'wowbuddy-dev','addon_directory':installed_name},ensure_ascii=False),'utf8')
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
    # 原安装成功后才清理；清理失败不回滚已经完成的新插件安装。
    from .dev_addon_cleanup import cleanup_addons_directory
    from .addon_actions import CleanupResult
    try:
        cleanup=cleanup_addons_directory(addons,installed_name)
    except (OSError,ValueError) as error:
        cleanup=CleanupResult(notes=f'旧插件清理未完成：{error}')
    return {'target': str(target), 'backup': str(backup) if backup else None,
            'files': len(payload), 'addon_directory':installed_name,'game_verified': False,
            'cleanup_deleted':cleanup.deleted,'cleanup_notes':cleanup.notes}
