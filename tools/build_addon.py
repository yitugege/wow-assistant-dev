"""从插件源码生成固定目录ZIP，不调用旧EXE或旧安装器。"""
from pathlib import Path
import hashlib
import json
import zipfile
import secrets
import re
import posixpath
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'desktop') not in sys.path:
    sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.dev_version import VERSION  # noqa: E402
VERSION_LINE = f'## Version: {VERSION}-dev'
NAME = 'WowBuddyDev'


# Lua 在运行时拼接路径加载的资源（见 PixelBar.lua 的 getLogoTexturePath、小地图图标与开关音效），
# 无法从 TOC 推出，须在此显式登记。存在才收录；正式插件构建由 require_resources 要求全部存在。
RESOURCE_FILES = (
    'PermesIcon.tga',
    'PermesLogoBlind.tga', 'PermesLogoBlindR.tga',
    'PermesLogoNormal.tga', 'PermesLogoNormalR.tga',
    'PermesLogoRed.tga', 'PermesLogoRedR.tga',
    'toggle_on.ogg', 'toggle_off.ogg', 'toggle_baofa.ogg',
    # 不在 TOC 中，但桌面端 wowbuddy.addons.addon_games.SIGNATURE_NAMES 依靠它识别已安装插件目录。
    'forever_spell_ids.lua',
)


def toc_entries(directory: Path) -> list[Path]:
    directory = directory.resolve()
    toc = directory / f'{NAME}.toc'
    entries = []
    for line in toc.read_text('utf-8-sig').splitlines():
        entry = line.strip()
        if not entry or entry.startswith('#'):
            continue
        target = (directory / entry.replace('\\', '/')).resolve()
        if not target.is_relative_to(directory) or not target.is_file():
            raise ValueError(f'TOC引用不存在或越出插件目录：{entry}')
        entries.append(target)
    return entries


def check_archive(archive, compile_lua, *, chunk_prefix='@'):
    """编译包内全部 Lua，并核对 TOC 与 XML 引用的文件都在包内。

    compile_lua(source, chunk_name) -> (ok, error)。返回 (Lua 成员名列表, Lua 内容列表, 引用列表)；
    编译失败或引用缺失时抛 ValueError。
    """
    names = set(archive.namelist())
    compiled, contents, references = [], [], []
    for name in sorted(names):
        data = archive.read(name)
        targets = []
        if name.endswith('.lua'):
            ok, error = compile_lua(data.decode('utf-8-sig'), chunk_prefix + name)
            if not ok:
                raise ValueError(error)
            compiled.append(name)
            contents.append(data)
        elif name.endswith('.toc'):
            targets = [line.strip() for line in data.decode('utf-8-sig').splitlines()
                       if line.strip() and not line.lstrip().startswith('#')]
        elif name.endswith('.xml'):
            targets = [node.attrib['file'] for node in ET.fromstring(data).iter() if 'file' in node.attrib]
        for target in targets:
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target.replace('\\', '/')))
            if resolved not in names:
                raise ValueError(f'包内引用缺失：{name} -> {target}')
            references.append({'source': name, 'target': resolved})
    return compiled, contents, references


def collect_files(directory: Path) -> list[Path]:
    """以 TOC 为白名单：TOC 本身、TOC 列出的文件和 RESOURCE_FILES 中存在的资源。"""
    directory = directory.resolve()
    for path in (p for p in directory.rglob('*') if p.is_file()):
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError(f'插件文件不能指向目录之外：{path}')
        if path.name == 'DirectCast.lua' or path.suffix.lower() in ('.exe', '.dll', '.pyc'):
            raise ValueError(f'开发插件包包含禁止的构建输入：{path.name}')
        if '__pycache__' in path.parts:
            raise ValueError(f'插件包中存在缓存目录：{path}')
    selected = {directory / f'{NAME}.toc', *toc_entries(directory)}
    selected.update(directory / name for name in RESOURCE_FILES if (directory / name).is_file())
    return sorted(selected)


def excluded_files(directory: Path) -> list[str]:
    directory = directory.resolve()
    selected = set(collect_files(directory))
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob('*')
                  if p.is_file() and p.resolve() not in selected)


def require_resources(directory: Path) -> None:
    missing = [name for name in RESOURCE_FILES if not (directory / name).is_file()]
    if missing:
        raise ValueError('插件资源缺失：' + ', '.join(missing))


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
    def stamp_version(lines):
        # 包内 TOC 的版本行固定为当前客户端版本，便于在游戏与助手中区分新旧插件。
        lines=[line for line in lines if not line.startswith('## Version:')]
        header=next((index for index, line in enumerate(lines) if not line.startswith('##')), len(lines))
        return lines[:header]+[VERSION_LINE]+lines[header:]
    def transformed(path, content):
        relative=path.relative_to(directory).as_posix()
        if path.suffix.lower()=='.toc' and not random_names:
            return ('\n'.join(stamp_version(content.decode('utf-8-sig').splitlines()))+'\n').encode('utf8')
        if not random_names or path.suffix.lower() not in ('.toc','.xml'):
            return content
        text=content.decode('utf-8-sig')
        if path.suffix.lower()=='.toc':
            lines=stamp_version(text.splitlines())
            text='\n'.join(paths.get(line.strip().replace('\\','/'),line) for line in lines)+'\n'
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
            'product':'wowbuddy-dev','addon_directory':addon_name,'random_names':random_names,'version':VERSION}


def main():
    output = ROOT / 'dist' / f'{NAME}-dev.zip'
    source = ROOT / 'addon' / NAME
    require_resources(source)
    manifest = build(source, output)
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({'artifact': str(output), 'sha256': manifest['sha256'], 'members': len(manifest['members']),
                      'excluded': excluded_files(source)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
