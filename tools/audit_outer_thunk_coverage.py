"""跟踪短跳板扩展出的新增展开范围；人工审读不等于动态等价。"""
import csv
import argparse
import hashlib
import json
from audit_outer_reachable_functions import ROOT, EVIDENCE

REVIEWED = {
    0x4430: 'UTF16字符集合反向搜索分派；基线/SSE4.2/AVX2配置共2754组原码对照通过，memcpy/memset为宿主替身',
    0x4610: 'SSE4.2 pcmpestri集合查找；六处CF分支经机器码确认，伪代码地址比较及删除块警告不能照搬；已随4430隔离执行',
    0x4830: 'AVX2每批8个UTF16单位反向筛选，尾块复制并屏蔽无效位，LZCNT取最后匹配；4970返回YMM0位图',
    0x4970: '构造256位字符集合位图，小集合直接累加，大集合经256字节临时表；YMM0返回而非伪代码uint64返回',
    0x4ad0: 'UTF16反向单字符搜索；已读完整正文和机器码，基线/SSE2/AVX2所列原码对照及向量保护页边界通过；不代表完整路径获取或任意输入等价',
    0xab84: '检查主模块PE头与CLR目录，按模式执行退出回调；根据进程策略进入终止路径；未动态验证',
    0xac68: '按标志先尝试TerminateProcess，随后CLR退出入口与ExitProcess；未执行原终止函数',
    0xac98: '仅在mscoree.dll已加载时取得CorExitProcess并间接调用，随后释放模块引用',
    0xba34: '加锁后执行bc20退出表，解锁并返回结果；异常展开未验证',
    0xbc20: '解码退出表并逆序调用；先标记条目为空，调用后重读表边界以处理回调追加或重分配；最终释放并重置三指针',
    0xbd48: '构造退出表上下文，使用锁编号2调用ba34包装器',
    0xc81c: '条件查询进程策略，返回输出值是否不等于1；下层策略接口未进一步命名',
    0xc090: '获取线程数据并更新locale/多字节引用，暂设线程locale标志并在上下文记录该变更',
    0xaa8c: '按上下文锁编号加锁，调用aac4，再解锁；异常展开行为未动态验证',
    0xaac4: '退出一次性标志；按退出模式选择回调表，解码并调用全局回调，遍历两组终止回调；含间接调用警告',
    0xb524: '宽环境指针为空时获取环境块并构造字符串指针表；成功写入两份全局指针，失败返回-1，释放临时块',
    0xb594: '扫描双零结尾宽环境块；跳过首字符为等号的条目，分配零终止指针表并逐条复制；分配失败清理已分配条目',
    0xb6b4: '非空环境指针表逐条释放，最后释放表本身；不是子进程环境变量修改',
    0xc8b0: '有界宽字符串复制；成功返回0；无效参数errno22，空间不足清空目标首字符并errno34；错误均调用参数处理器',
    0xdfbc: 'GetEnvironmentStringsW获取原环境块，计算含末尾空项长度，分配并复制；释放Windows环境块，返回副本或空',
}

TERMINATION_REVIEWED = {
    0xb884: '锁4保护下将全局locale引用回退默认值，再解锁',
    0xb900: '构造锁编号4的locale清理包装器',
    0xe248: '校验描述符并清除句柄记录，特定应用模式下清空标准句柄；无效输入errno9',
    0xfc50: '通过fb28固定flush参数，关闭额外流，再释放三个标准流缓冲和锁，释放全局指针表',
    0x11a38: '锁8下遍历编号3起的流，关闭已打开项，逐项删除锁并释放流对象；返回成功关闭数',
    0x11aec: '按流标志释放归属缓冲，清空指针及计数并清除缓冲相关位',
    0x11ce0: '空流指针记录errno22；可用流加锁后调用11d5c再解锁；特殊标志流走释放状态分支',
    0x11d5c: '刷新流、释放缓冲、关闭底层描述符，成功时释放附加字段，最终清除流状态',
    0x11e04: '机器码保留64位RCX并传给11ce0；伪代码32位参数及全局覆盖为错误推断；维护并回写线程错误上下文',
    0x11ef4: '检查全局句柄排除-1/-2哨兵后调用CloseHandle',
    0x11fd0: '锁定描述符后再次检查打开标志，调用1210c或记录errno9，最后解锁',
    0x12048: '区分-2特殊描述符及其他无效输入，记录errno9；有效输入构造锁定关闭上下文',
    0x1210c: '机器码确认stdout/stderr同句柄时跳过CloseHandle，随后仍清除当前描述符；CloseHandle失败映射错误并返回-1',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terminators', action='store_true', help='记录静态终止表引出的13项差集')
    args = parser.parse_args()
    directory = ROOT / 'dist'
    baseline_name = 'outer-reachable-with-initializers-thunks.json' if args.terminators else 'outer-reachable-with-initializers.json'
    expanded_name = 'outer-reachable-with-initializers-thunks-terminators.json' if args.terminators else 'outer-reachable-with-initializers-thunks.json'
    reviewed = TERMINATION_REVIEWED if args.terminators else REVIEWED
    baseline = json.loads((directory / baseline_name).read_text('utf8'))
    expanded = json.loads((directory / expanded_name).read_text('utf8'))
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
        if rva in reviewed and not body:
            raise ValueError(f'已审读正文缺失: {rva:#x}')
        rows.append({'rva': hex(rva), 'provider_name': names.get(rva), 'body': str(path),
                     'body_sha256': hashlib.sha256(body).hexdigest() if body else None,
                     'observation': reviewed.get(rva),
                     'warning_lines': [line.strip() for line in body.decode('utf8').splitlines()
                                       if 'WARNING:' in line] if body else []})
    report = {'source_sha256': expanded['sha256'], 'rows': rows,
              'limitations': ['仅记录两张调用图差集，不代表全部函数',
                              '无精确正文可能是展开分块，不能直接按缺失功能计数',
                              '人工语义记录不代表机器码动态验证或产品等价']}
    output = directory / ('outer-termination-coverage.json' if args.terminators else 'outer-thunk-coverage.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'new_ranges': len(rows),
                      'reviewed': sum(r['observation'] is not None for r in rows),
                      'without_exact_body': sum(r['body_sha256'] is None for r in rows)}))


if __name__ == '__main__':
    main()
