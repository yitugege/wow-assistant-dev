"""只读核对原内置插件包与参考源码，区分可读协议契约来源。"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon, compare_directory


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
