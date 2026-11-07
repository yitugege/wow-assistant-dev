"""从插件源码生成固定目录ZIP，不调用旧EXE或旧安装器。"""
from pathlib import Path
import hashlib
import json
import zipfile
import secrets
import re
import posixpath

ROOT = Path(__file__).resolve().parents[1]
NAME = 'WowBuddyDev'


def collect_files(directory: Path) -> list[Path]:
    directory = directory.resolve()
    toc = directory / f'{NAME}.toc'
    for line in toc.read_text('utf-8-sig').splitlines():
        entry = line.strip()
        if not entry or entry.startswith('#'):
            continue
        target = (directory / entry.replace('\\', '/')).resolve()
        if not target.is_relative_to(directory) or not target.is_file():
            raise ValueError(f'TOC引用不存在或越出插件目录：{entry}')
    files = sorted(p for p in directory.rglob('*') if p.is_file())
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError(f'插件文件不能指向目录之外：{path}')
        if path.name == 'DirectCast.lua' or path.suffix.lower() in ('.exe', '.dll', '.pyc'):
            raise ValueError(f'开发插件包包含禁止的构建输入：{path.name}')
        if '__pycache__' in path.parts:
            raise ValueError(f'插件包中存在缓存目录：{path}')
    return files


def build(directory: Path, output: Path, *, random_names=False) -> dict:
    directory = directory.resolve()
    files = collect_files(directory)
    output = output.resolve()
    if output.is_relative_to(directory):
        raise ValueError('输出文件不能位于插件源码目录中')
    output.parent.mkdir(parents=True, exist_ok=True)
    addon_name = 'w'+secrets.token_hex(6) if random_names else NAME
    paths = {path.relative_to(directory).as_posix():path.relative_to(directory).as_posix() for path in files}
    if random_names:
        for relative in paths:
            if relative.endswith('.lua'):
                parent=posixpath.dirname(relative)
                paths[relative]=posixpath.join(parent,'f'+secrets.token_hex(8)+'.lua')
        paths[f'{NAME}.toc']=f'{addon_name}.toc'
    def transformed(path, content):
        relative=path.relative_to(directory).as_posix()
        if not random_names or path.suffix.lower() not in ('.toc','.xml'):
            return content
        text=content.decode('utf-8-sig')
        if path.suffix.lower()=='.toc':
            text='\n'.join(paths.get(line.strip().replace('\\','/'),line) for line in text.splitlines())+'\n'
            text+='## X-WowBuddy-Product: wowbuddy-dev\n'
        else:
            parent=posixpath.dirname(relative)
            def rewrite(match):
                source=posixpath.normpath(posixpath.join(parent,match.group(2).replace('\\','/')))
                target=paths.get(source)
                return match.group(1)+(posixpath.relpath(target,parent or '.') if target else match.group(2))+match.group(3)
            text=re.sub(r'(file\s*=\s*[\"\x27])([^\"\x27]+)([\"\x27])',rewrite,text)
        return text.encode('utf8')
    manifest = {}
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            member = f'{addon_name}/{paths[path.relative_to(directory).as_posix()]}'
            content = transformed(path,path.read_bytes())
            item = zipfile.ZipInfo(member, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, content)
            manifest[member] = hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(manifest):
            raise RuntimeError('ZIP完整性校验失败')
        for member, digest in manifest.items():
            if hashlib.sha256(archive.read(member)).hexdigest() != digest:
                raise RuntimeError(f'ZIP成员摘要不符：{member}')
    return {'artifact': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'members': manifest, 'source_only': True, 'game_verified': False,
            'product':'wowbuddy-dev','addon_directory':addon_name,'random_names':random_names}


def main():
    output = ROOT / 'dist' / f'{NAME}-dev.zip'
    manifest = build(ROOT / 'addon' / NAME, output)
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({'artifact': str(output), 'sha256': manifest['sha256'], 'members': len(manifest['members'])}))


if __name__ == '__main__':
    main()
