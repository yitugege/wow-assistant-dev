"""跟踪短跳板扩展出的新增展开范围；人工审读不等于动态等价。"""
import csv
import argparse
import hashlib
import json
import struct
import pefile
from audit_outer_reachable_functions import ROOT, EVIDENCE

REVIEWED = {
    0xcb54: '记录Windows错误到线程上下文并映射errno，设置两类错误更新标志',
    0xcb78: '返回线程doserrno地址，线程上下文不存在时返回全局备用地址',
    0xccac: 'argv通配符展开：FindFirstFileExW/FindNextFileW，跳过点目录并拼回路径；16处删除块警告使输出数组构造仍需机器码复核',
    0xd0ac: '拼接可选宽路径前缀并加入动态指针数组，容量从4倍增，溢出或分配失败返回12；复制调用参数未完整反编译',
    0xe8d0: '逐UTF16单位寻找字符集合中的首个匹配，输入结束返回空',
    0xf078: '懒解析AppPolicyGetProcessTerminationMethod，缺失返回0xc0000225，存在时传入当前进程令牌伪句柄及输出地址',
    0xf438: '顺序调用成对初始化项，遇失败逆序清理此前成功项，清理参数为0；运行时间接回调未动态执行',
    0xff4c: '有状态UTF8解码，保留不足字节状态并返回-2，检查续字节/过长编码/代理区/Unicode上限，非法走错误处理',
    0x1010c: '单字符UTF8到UTF16包装，将非BMP码点替换为FFFD；伪代码void返回及省略参数需机器码复核',
    0x10154: 'UTF8字符串转UTF16或计数，非BMP输出代理对，目标剩1单位时停止；非法序列记录errno42并保留源位置',
    0x10dbc: '控制台代码页转换写出，保存跨次调用UTF8/DBCS残字节，转换后WriteFile；换行补CR及计数ABI尚未动态验证',
    0x11250: '窄文本按块插入CR再写LF，记录错误/写入字节/插入字节；WriteFile短写即返回',
    0x11358: 'UTF16文本按块插入宽CR，按字节记录写入量和额外CR量，WriteFile短写即返回',
    0x11474: 'UTF16转UTF8后循环写完一块；机器码确认成功零字节会回到同一写入循环，无零进度检查；仅静态确认',
    0x115e8: '描述符校验及加锁写入包装，锁内重查打开位；无效描述符更新错误上下文，-2不调用参数处理器',
    0x11708: '写入模式分派：二进制直接WriteFile，文本按编码/控制台分派，追加模式先seek；处理部分成功、设备CtrlZ、零进度与错误映射',
    0x11b30: '返回描述符0x40设备位，边界非法记录errno9，-2特殊值不调用无效参数处理器',
    0x11bac: '控制流保护检查包装，间接调用__guard_check_icall；没有正文级业务逻辑',
    0x11be8: '获取底层句柄并SetFilePointerEx，成功清文件EOF位，失败映射错误；返回值宽度需机器码复核',
    0x11ca0: '确保控制台句柄后写一个UTF16单位，API返回成功即返回字符，否则FFFF；未检查写入数量',
    0x11ea0: '句柄为-2时懒打开CONOUT$，-1为失败；机器码确认仅首次未初始化状态尝试打开',
    0x11f10: 'WriteConsoleW失败且GetLastError为6时，按句柄哨兵决定关闭，再重开并重试一次；其他错误不重试',
    0xc940: '有界宽字符串复制；count为-1允许截断并返回80，空间不足返回34，无效参数返回22；三段链式展开归属同一入口',
    0x10340: '通用元素排序；大分区按中间枢轴分割并用显式栈处理，小分区逐项选择交换；两段链式展开归属此入口，比较回调ABI仍需机器码验证',
    0xe304: '校验CRT描述符后读取底层句柄；-2及无效描述符清doserrno并置errno9，后者另调用参数处理器',
    0xf7e8: '逐流加锁后复查打开/缓冲/提交标志，按flush-all模式刷新并累计成功数或记录失败，再解锁',
    0xf884: '全局锁保护遍历流表，过滤打开状态与待刷新标志，交给逐流锁包装处理',
    0xf968: 'common_flush_all构造计数和错误上下文；模式true返回成功数，false返回错误状态；未完整原表动态执行',
    0xf9c8: '原码执行确认先重置缓冲指针/计数，再写入；短写/失败设置错误位；切换读写模式时成功后清写位',
    0xfa54: '原码确认64位流指针不被全局上下文覆盖；空流分派flush-all(false)，非空刷新成功后按0x800标志提交；28场景隔离原码验证',
    0xfcf8: '线程locale指针与全局对应项不一致且未锁定线程locale时更新引用',
    0xfd64: '线程多字节信息指针与全局对应项不一致且未锁定线程locale时更新引用',
    0xfd9c: '多字节转单宽字符，按UTF8/单字节/多字节代码页分派；空输入重置状态；转换失败记录errno42，完整ABI未动态验证',
    0x1030c: '流非空返回偏移0x18的文件描述符；空流置errno22并调用无效参数处理器',
    0x10c9c: '描述符加锁后复查打开位，调用FlushFileBuffers；失败保留GetLastError并置errno9，再解锁；机器码静态核对',
    0x10d28: '_commit校验描述符；-2直接errno9，其他无效值另调用参数处理器；有效值进入锁定提交包装器',
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


def unwind_owner(pe, start):
    """只依据UNW_FLAG_CHAININFO解析归属，不按地址相邻推断函数。"""
    entries = {entry.struct.BeginAddress: entry.struct for entry in pe.DIRECTORY_ENTRY_EXCEPTION}
    current = entries[start]
    seen = set()
    chain = []
    while True:
        if current.BeginAddress in seen:
            raise ValueError('链式展开循环')
        seen.add(current.BeginAddress)
        header = pe.get_data(current.UnwindData, 4)
        if len(header) != 4 or header[0] & 7 not in (1, 2):
            raise ValueError('未支持或截断的展开头')
        flags, count = header[0] >> 3, header[2]
        row = {'begin': hex(current.BeginAddress), 'end_exclusive': hex(current.EndAddress),
               'unwind_rva': hex(current.UnwindData), 'header': header.hex(),
               'version': header[0] & 7, 'flags': flags}
        chain.append(row)
        if not flags & 4:
            return current.BeginAddress, chain
        if header[0] & 7 != 1:
            raise ValueError('当前只解析版本1的链式展开目标')
        if flags & 3:
            raise ValueError('CHAININFO与handler标志冲突')
        slot = current.UnwindData + 4 + ((count + 1) & ~1) * 2
        raw = pe.get_data(slot, 12)
        if len(raw) != 12:
            raise ValueError('链式展开目标截断')
        begin, end, unwind = struct.unpack('<III', raw)
        row.update(chain_slot=hex(slot), chain_bytes=raw.hex(), chain_target=hex(begin))
        target = entries.get(begin)
        if target is None or (target.EndAddress, target.UnwindData) != (end, unwind):
            raise ValueError('链式展开目标与.pdata条目不一致')
        current = target


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
    payload = (EVIDENCE / 'original-27ac1127fc/probe/outer-memory-analysis.exe').read_bytes()
    if hashlib.sha256(payload).hexdigest() != expanded['sha256']:
        raise ValueError('展开数据映像与调用图不一致')
    pe = pefile.PE(data=payload)
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
        owner, chain = unwind_owner(pe, rva)
        owner_path = folder / f'{int(expanded["image_base"], 16) + owner:#x}.c'
        owner_body = owner_path.read_bytes() if owner_path.exists() else None
        if rva in reviewed and not body:
            raise ValueError(f'已审读正文缺失: {rva:#x}')
        rows.append({'rva': hex(rva), 'provider_name': names.get(rva), 'body': str(path),
                     'body_sha256': hashlib.sha256(body).hexdigest() if body else None,
                     'unwind_owner_rva': hex(owner), 'unwind_chain': chain,
                     'owner_body': str(owner_path),
                     'owner_body_sha256': hashlib.sha256(owner_body).hexdigest() if owner_body else None,
                     'owner_observation': reviewed.get(owner) if owner != rva else None,
                     'observation': reviewed.get(rva),
                     'warning_lines': [line.strip() for line in body.decode('utf8').splitlines()
                                       if 'WARNING:' in line] if body else []})
    pe.close()
    report = {'source_sha256': expanded['sha256'], 'rows': rows,
              'limitations': ['仅记录两张调用图差集，不代表全部函数',
                              '无精确正文可能是展开分块，不能直接按缺失功能计数',
                              '人工语义记录不代表机器码动态验证或产品等价']}
    output = directory / ('outer-termination-coverage.json' if args.terminators else 'outer-thunk-coverage.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'new_ranges': len(rows),
                      'reviewed': sum(r['observation'] is not None for r in rows),
                      'reviewed_via_owner': sum(r['owner_observation'] is not None for r in rows),
                      'without_exact_body': sum(r['body_sha256'] is None for r in rows),
                      'missing_body_resolved_by_chain': sum(r['body_sha256'] is None and r['owner_body_sha256'] is not None for r in rows)}))


if __name__ == '__main__':
    main()
