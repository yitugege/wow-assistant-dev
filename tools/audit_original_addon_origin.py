"""只读核对原内置插件包与参考源码，区分可读协议契约来源。"""
from pathlib import Path
import hashlib
import json
import sys
import struct
import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon, read_bundle, compare_directory


def resource_inventory(data):
    """枚举PE资源正文，不加载DLL、不执行原文件。"""
    pe = pefile.PE(data=data)
    resources = []
    try:
        root = getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None)
        for kind in root.entries if root is not None else ():
            for name in kind.directory.entries:
                for language in name.directory.entries:
                    entry = language.data.struct
                    payload = pe.get_data(entry.OffsetToData, entry.Size)
                    if len(payload) != entry.Size:
                        raise ValueError('PE资源正文截断')
                    resources.append(({
                        'type': str(kind.name or kind.id), 'name': str(name.name or name.id),
                        'language': language.id, 'size': len(payload),
                        'sha256': hashlib.sha256(payload).hexdigest(),
                        'wbd1': payload.startswith(b'WBD1'),
                        'wbaddon1': payload.startswith(b'WBADDON1\n'),
                    }, payload))
        return resources
    finally:
        pe.close()


def original_delivery_chain(reference):
    original = Path('D:/download/WOW战斗助手.exe')
    data = original.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != '9694f988f740acd88402c6f0ddaaf6f9173525f8c8137941a553d2c74d97bf14':
        raise ValueError('原EXE身份已变化，需重新确定证据基线')
    resources = resource_inventory(data)
    bundles = [(row, raw) for row, raw in resources if row['wbd1']]
    if len(bundles) != 1:
        raise ValueError('原资源中的WBD1数量与当前基线不符')
    bundle = read_bundle(bundles[0][1])
    rows = compare_directory(bundle, reference / 'unpacked')
    nested = []
    pe_resources = {}
    for member in bundle:
        if member.data.startswith(b'WBADDON1\n'):
            items = read_addon(member.data)
            nested.append({'name': member.name, 'sha256': member.sha256,
                           'members': len(items), 'toc': {
                               item.name: item.data.decode('utf-8-sig')
                               for item in items if item.name.endswith('.toc')}})
        if member.data.startswith(b'MZ'):
            pe_resources[member.name] = [row for row, _ in resource_inventory(member.data)]
    business = next(member for member in bundle if member.name == 'WOW战斗助手.exe')
    pe = pefile.PE(data=business.data)
    try:
        pointer = struct.unpack('<Q', pe.get_data(0x10f028, 8))[0]
        filename = pe.get_string_at_rva(pointer - pe.OPTIONAL_HEADER.ImageBase)
        if filename != b'addon.bin':
            raise ValueError('原安装器插件路径常量与基线不符')
    finally:
        pe.close()
    evidence = []
    for name in ('0x140011f10.c', '0x1400155d0.c'):
        source = reference / 'decompiled-main/functions' / name
        evidence.append({'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    return {'original': str(original), 'sha256': digest,
            'outer_resources': [row for row, _ in resources],
            'bundle_resource': bundles[0][0], 'bundle_members': len(bundle),
            'unpacked_comparison': rows,
            'all_unpacked_members_equal': all(row['equal'] for row in rows),
            'addon_containers_at_member_root': nested,
            'pe_member_resources': pe_resources,
            'installer_filename': {'pointer_rva': '0x10f028', 'target_va': hex(pointer),
                                   'value': filename.decode('ascii'), 'decompiled_evidence': evidence},
            'scope': '枚举PE资源表及WBD1成员根签名；不排除节内编码数据、其他压缩容器、动态生成或远程下载'}


def check():
    reference = Path('D:/reverse-analysis/wow-assistant')
    package = reference / 'unpacked/addon.bin'
    payload = package.read_bytes()
    members = read_addon(payload)
    rows = compare_directory(members, reference / 'addon-source')
    toc = {m.name: m.data.decode('utf-8-sig') for m in members if m.name.endswith('.toc')}
    contracts = {}
    for name in ('contract.json', 'contract_readable.json'):
        data = (reference / 'unpacked' / name).read_bytes()
        document = json.loads(data)
        contracts[name] = {
            'sha256': hashlib.sha256(data).hexdigest(),
            'description': document.get('_comment'),
            'header': document.get('header'),
            'independent_copy_equal': data == (ROOT / 'assets' / name).read_bytes(),
        }
    # 名称和数字标记只作定位线索，不将未匹配误报成不存在任何等价实现。
    needles = ('10685761', '19, 227, 149', '19,227,149', '0x13E395')
    hits = {needle: [m.name for m in members if needle.encode() in m.data]
            for needle in needles}
    return {
        'original_delivery_chain': original_delivery_chain(reference),
        'package': str(package), 'package_sha256': hashlib.sha256(payload).hexdigest(),
        'member_count': len(members), 'source_comparison': rows,
        'all_reference_members_equal': all(row['equal'] for row in rows),
        'toc': toc, 'contracts': contracts, 'readable_literal_hits': hits,
        'scope': '只读包来源与逐字节对应；未运行Lua，不证明全部运行时行为或协议发送端不存在',
    }


if __name__ == '__main__':
    report = check()
    destination = ROOT / 'dist/original-addon-origin.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({key: report[key] for key in
                     ('package_sha256', 'member_count', 'all_reference_members_equal',
                      'readable_literal_hits')}, ensure_ascii=False))
    chain = report['original_delivery_chain']
    print(json.dumps({'bundle_members': chain['bundle_members'],
                      'all_unpacked_members_equal': chain['all_unpacked_members_equal'],
                      'addon_containers': [item['name'] for item in chain['addon_containers_at_member_root']],
                      'pe_members': len(chain['pe_member_resources'])}))
