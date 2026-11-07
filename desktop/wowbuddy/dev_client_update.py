"""目录版客户端更新：可校验暂存、退出后的目录交换与失败回滚。"""
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import tempfile
import uuid
import zipfile
from .dev_addon_install import _plain_path

NAME='WowBuddyDev'
EXE='WowBuddyDev.exe'

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024):value.update(block)
    return value.hexdigest()

def member_path(name):
    path=PurePosixPath(name)
    reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
    if (len(path.parts)<2 or path.parts[0]!=NAME or path.as_posix()!=name
            or '\\' in name or any(part in ('.','..','.local') or part.endswith((' ','.'))
                or any(c in part for c in ':<>"|?*') or any(ord(c)<32 for c in part)
                or part.split('.')[0].upper() in reserved for part in path.parts)):
        raise ValueError('客户端包路径无效：'+name)
    return Path(*path.parts[1:])

def stage_update(package,manifest_path,workspace):
    package=Path(package);manifest=json.loads(Path(manifest_path).read_text('utf8'))
    if manifest.get('product')!='wowbuddy-client' or manifest.get('format')!=1:
        raise ValueError('不是支持的客户端更新清单')
    if digest(package)!=manifest['sha256']:raise ValueError('客户端ZIP摘要不符')
    members=manifest['members']
    if not isinstance(members,dict) or not members or len(members)>15000:
        raise ValueError('客户端文件清单无效')
    workspace=Path(workspace).absolute();_plain_path(workspace);workspace.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='client-stage-',dir=workspace,delete=False) as tmp:
        stage=Path(tmp)
        try:
            with zipfile.ZipFile(package) as archive:
                entries=archive.infolist()
                if (len(entries)!=len(members) or set(archive.namelist())!=set(members)
                        or sum(i.file_size for i in entries)>1024**3):
                    raise ValueError('客户端ZIP清单不一致或解压大小超限')
                seen=set()
                for entry in entries:
                    relative=member_path(entry.filename)
                    if entry.is_dir() or (entry.external_attr>>16)&0o170000==0o120000 or entry.filename.casefold() in seen:
                        raise ValueError('客户端ZIP含链接、目录项或重复路径')
                    seen.add(entry.filename.casefold())
                    target=stage/NAME/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(entry) as source,target.open('xb') as destination:
                        shutil.copyfileobj(source,destination,1024*1024)
                    if digest(target)!=members[entry.filename]:raise ValueError('客户端成员摘要不符')
            validate_staged(stage/NAME,manifest)
            (stage/'manifest.json').write_text(json.dumps(manifest),'utf8')
            return stage/NAME
        except Exception:
            shutil.rmtree(stage)
            raise

def validate_staged(directory,manifest):
    directory=Path(directory);_plain_path(directory)
    actual={}
    for path in directory.rglob('*'):
        _plain_path(path)
        if path.is_file():actual[NAME+'/'+path.relative_to(directory).as_posix()]=digest(path)
    if actual!=manifest['members']:raise ValueError('暂存客户端已改变')
    exe=directory/EXE
    if not exe.is_file() or not (directory/'_internal').is_dir():raise ValueError('客户端缺少EXE或运行库')
    with exe.open('rb') as stream:
        if stream.read(2)!=b'MZ':raise ValueError('客户端EXE头无效')

def replace_stopped_client(staged,current):
    """宿主必须已退出；不杀进程，不在此函数重启。旧目录保留为备份。"""
    staged=Path(staged).absolute();current=Path(current).absolute()
    for path in (staged,current):_plain_path(path)
    if (current==current.parent or staged==current or staged.is_relative_to(current)
            or current.is_relative_to(staged) or staged.drive.lower()!=current.drive.lower()):
        raise ValueError('更新暂存与客户端目录必须独立且位于同一卷')
    if not (current/EXE).is_file():raise ValueError('目标不是独立客户端目录')
    manifest=json.loads((staged.parent/'manifest.json').read_text('utf8'))
    if manifest.get('product')!='wowbuddy-client':raise ValueError('客户端身份无效')
    validate_staged(staged,manifest)
    local=current/'.local'
    if local.exists():
        for path in (local,*local.rglob('*')):_plain_path(path)
        try:shutil.copytree(local,staged/'.local')
        except OSError:
            if (staged/'.local').exists():shutil.rmtree(staged/'.local')
            raise
    backup=current.with_name(current.name+'.backup-'+uuid.uuid4().hex)
    try:
        current.rename(backup)
        try:staged.rename(current)
        except OSError:
            backup.rename(current)
            raise
    except OSError:
        if (staged/'.local').exists():shutil.rmtree(staged/'.local')
        raise
    return {'target':str(current),'backup':str(backup),'version':manifest.get('version',''),
            'restarted':False}
