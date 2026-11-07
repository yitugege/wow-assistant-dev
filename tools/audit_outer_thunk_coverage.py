"""跟踪短跳板扩展出的新增展开范围；人工审读不等于动态等价。"""
import csv
import hashlib
import json
from audit_outer_reachable_functions import ROOT, EVIDENCE

REVIEWED = {
    0xaa8c: '按上下文锁编号加锁，调用aac4，再解锁；异常展开行为未动态验证',
    0xaac4: '退出一次性标志；按退出模式选择回调表，解码并调用全局回调，遍历两组终止回调；含间接调用警告',
    0xb524: '宽环境指针为空时获取环境块并构造字符串指针表；成功写入两份全局指针，失败返回-1，释放临时块',
    0xb594: '扫描双零结尾宽环境块；跳过首字符为等号的条目，分配零终止指针表并逐条复制；分配失败清理已分配条目',
    0xb6b4: '非空环境指针表逐条释放，最后释放表本身；不是子进程环境变量修改',
    0xc8b0: '有界宽字符串复制；成功返回0；无效参数errno22，空间不足清空目标首字符并errno34；错误均调用参数处理器',
    0xdfbc: 'GetEnvironmentStringsW获取原环境块，计算含末尾空项长度，分配并复制；释放Windows环境块，返回副本或空',
}


def main():
    directory = ROOT / 'dist'
    baseline = json.loads((directory / 'outer-reachable-with-initializers.json').read_text('utf8'))
    expanded = json.loads((directory / 'outer-reachable-with-initializers-thunks.json').read_text('utf8'))
    if baseline['sha256'] != expanded['sha256']:
        raise ValueError('调用图映像身份不一致')
    old = {r['begin'] for r in baseline['reachable_functions']}
    with (directory / 'outer-ghidra-remaining/functions.tsv').open(encoding='utf8') as stream:
        names = {int(r['rva'], 16): r['name'] for r in csv.DictReader(stream, delimiter='\t')}
    rows = []
    for row in expanded['reachable_functions']:
        if row['begin'] in old:
            continue
        rva = int(row['begin'], 16)
        folder = EVIDENCE / 'decompiled-memory/functions' if rva < 0x6000 else directory / 'outer-ghidra-remaining'
        path = folder / f'{int(expanded["image_base"], 16) + rva:#x}.c'
        body = path.read_bytes() if path.exists() else None
        if rva in REVIEWED and not body:
            raise ValueError(f'已审读正文缺失: {rva:#x}')
        rows.append({'rva': hex(rva), 'provider_name': names.get(rva), 'body': str(path),
                     'body_sha256': hashlib.sha256(body).hexdigest() if body else None,
                     'observation': REVIEWED.get(rva),
                     'warning_lines': [line.strip() for line in body.decode('utf8').splitlines()
                                       if 'WARNING:' in line] if body else []})
    report = {'source_sha256': expanded['sha256'], 'rows': rows,
              'limitations': ['仅记录两张调用图差集，不代表全部函数',
                              '无精确正文可能是展开分块，不能直接按缺失功能计数',
                              '人工语义记录不代表机器码动态验证或产品等价']}
    output = directory / 'outer-thunk-coverage.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'new_ranges': len(rows),
                      'reviewed': sum(r['observation'] is not None for r in rows),
                      'without_exact_body': sum(r['body_sha256'] is None for r in rows)}))


if __name__ == '__main__':
    main()
