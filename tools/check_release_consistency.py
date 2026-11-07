"""只读核对实际发布包、内嵌插件与当前源码，不重新生成随机文件名。"""
import hashlib
import json
from pathlib import Path
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.dev_version import VERSION
from wowbuddy.github_outer import verify_outer


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check():
    source = ROOT / 'addon/WowBuddyDev'
    expected = sorted(p.read_bytes() for p in source.rglob('*.lua'))
    compile_lua = LuaRuntime(unpack_returned_tuples=True).eval(
        'function(s,n) local f,e=loadstring(s,n);return f~=nil,e end')
    packages = {}
    for stem in ('WowBuddyDev-addon', 'WowBuddyDev-windows-x64'):
        path = ROOT / 'dist/release' / (stem + '.zip')
        manifest = json.loads(path.with_suffix('.manifest.json').read_text('utf8'))
        assert manifest['version'] == VERSION
        assert digest(path.read_bytes()) == manifest['sha256']
        with zipfile.ZipFile(path) as archive:
            actual = {n: digest(archive.read(n)) for n in archive.namelist() if not n.endswith('/')}
            assert actual == manifest['members']
        packages[stem] = manifest['sha256']
    for path in (ROOT / 'dist/release/WowBuddyDev-addon.zip',
                 ROOT / 'dist/desktop/WowBuddyDev/packages/WowBuddyDev-dev.zip'):
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            lua = []
            for name in names:
                data = archive.read(name)
                targets = []
                if name.endswith('.lua'):
                    ok, error = compile_lua(data.decode('utf-8-sig'), name)
                    assert ok, (name, error)
                    lua.append(data)
                elif name.endswith('.toc'):
                    lines = data.decode('utf-8-sig').splitlines()
                    assert '## Version: ' + VERSION + '-dev' in lines
                    targets = [s.strip() for s in lines if s.strip() and not s.lstrip().startswith('#')]
                elif name.endswith('.xml'):
                    targets = [node.attrib['file'] for node in ET.fromstring(data).iter() if 'file' in node.attrib]
                for target in targets:
                    assert posixpath.normpath(posixpath.join(posixpath.dirname(name), target.replace('\\', '/'))) in names
            assert sorted(lua) == expected
    for path in (ROOT / 'dist/desktop/WowBuddyDev/build-manifest.json', ROOT / 'dist/outer/build-manifest.json'):
        manifest = json.loads(path.read_text('utf8'))
        for name, sha in manifest['source_files'].items():
            assert digest((ROOT / name).read_bytes()) == sha, name
    outer = ROOT / 'dist/outer/WowBuddyDev-Outer.exe'
    manifest = json.loads(outer.with_suffix('.manifest.json').read_text('utf8'))
    assert manifest['version'] == VERSION
    verify_outer(outer, manifest)
    assert manifest['business_sha256'] == digest((ROOT / 'dist/desktop/WowBuddyDev/WowBuddyDev.exe').read_bytes())
    result = dict(passed=True, version=VERSION, packages=packages, outer_sha256=manifest['sha256'],
                  lua_files=len(expected), embedded_and_download_lua_match_source=True, game_verified=False)
    (ROOT / 'dist/release-consistency.json').write_text(json.dumps(result, indent=2), 'utf8')
    return result


if __name__ == '__main__':
    print(json.dumps(check()))
