"""逐项记录初始化路径新增范围的正文身份与人工审读状态，不推算还原率。"""
import csv
import hashlib
import json
from audit_outer_reachable_functions import ROOT, EVIDENCE

# 仅对实际阅读过的正文作语义记录；不是自动按符号名称分类。
REVIEWED = {
    0x561c: '退出表一次初始化；按UCRT使用方式设哨兵或初始化两个表，失败返回0',
    0x5790: '按退出表哨兵选择注册入口，成功返回回调指针、失败返回空',
    0x57cc: '包装_onexit并将非空结果转换为成功0，否则-1',
    0x5b6c: '回调数组首尾地址相同；机器码确认该循环在当前映像不执行',
    0xb348: 'argv缓冲区尺寸乘加溢出检查，成功calloc，非法尺寸返回空',
    0xb844: '校验文件模式并写RVA22800；非法模式触发参数处理并返回errno22',
    0xb930: '查询/修改线程locale位；非法标志置errno22并返回-1',
    0xb9f8: '退出回调注册的锁包装，调用ba70后解锁；异常路径仍须展开证据',
    0xbdb4: '将退出表和回调组装为上下文，使用锁编号2执行注册',
    0xc850: 'HeapAlloc及new-handler重试；零长度按1申请，失败errno12',
    0xd234: 'locale上下文初始化，按参数/全局/线程选择并暂设线程标志',
    0xd4a8: '代码页-2/-3/-4分别选OEM/ACP/当前locale；还原临时线程标志',
    0xda28: '锁5下同步线程多字节表并更新引用，空结果终止',
    0xdae0: '一次初始化默认多字节表，以代码页-3调用d7b8并设完成标志',
    0xdb40: '获取当前线程状态并调用多字节数据同步',
    0xdb5c: '代码页表与系统查询初始化，拒绝UTF7/无效页，UTF8特殊处理，填充字符分类',
    0xedec: '锁4下更新线程locale指针，失败终止',
    0xee5c: '替换locale引用，加减计数并释放非默认且零引用旧对象',
    0xf320: '乘法溢出检查后重分配，新增区域清零，失败errno12',
    0xfcc4: '允许同步且locale指针过时时刷新当前线程locale',
    0x10a0c: '建立locale上下文后调用106d8，最后恢复临时线程标志',
    0x10bd0: '空指针触发非法参数及errno22，否则查询HeapSize',
    0x10c20: '空指针转malloc，零长度释放，否则HeapReAlloc及new-handler重试',
    0x12200: '机器码确认CPUID/XGETBV探测并设置能力位；反编译删除CPUID块警告不可忽略',
    0x124b0: '按线程StackLimit逐4KiB探测栈页；反编译使用隐式寄存器参数',
    0x4efc: '设置文件模式、退出表、参数模式和线程locale；保留反编译终止调用警告',
    0x4fb4: '调用58d0后返回0；58d0向两个全局64位字段分别或入0x24和2',
    0x4fc4: '5af8注册5b08为未处理异常过滤器；5894返回0，b9b0设置全局模式',
    0x58d0: '通过58c0/58c8取RVA22180/22188地址并分别或入0x24和2；未命名字段用途',
    0xb1a4: '宽字符argv分词、引号/反斜杠处理、两遍计数和写入',
    0xb3a8: '参数模式0/1/2校验，模块路径回退，分配并填充argv；模式2另走展开',
    0xb9b0: '模式仅接受0/1，交换全局值并返回旧值；非法参数置errno22并调用处理器',
    0xba70: '退出回调表解码、容量增长及失败后小步扩容、编码指针写入',
    0xc590: '检查或创建FLS线程状态；失败走abort',
    0xd2d8: '锁内复制多字节字符表，替换引用并更新引用计数',
    0xd528: '清零代码页结构并复制默认字符分类和映射表',
    0xd5c0: '代码页字符分类及大小写映射，UTF8或GetCPInfo失败走ASCII表',
    0xd7b8: '线程多字节数据按代码页重建、失败清理、引用计数与全局同步',
    0xdedc: '按代码页修正标志后调用WideCharToMultiByte；导入跳板有反编译警告',
    0xe928: '多字节转宽字符后GetStringTypeW，栈/堆缓冲区选择及失败清理',
    0xeec4: '延迟加载Windows API并缓存函数地址；VirtualProtect失败走abort',
    0xf108: '优先LCMapStringEx，缺失时转换locale并调用LCMapStringW',
    0xf1fc: '优先LocaleNameToLCID，缺失时调用10b28表查找',
    0xfb30: 'stdio表默认512项，分配失败回退3项，再失败返回-1；初始化3个流锁',
    0xfd30: '线程标志允许且指针过时时刷新多字节数据',
    0x106d8: '多字节到宽字符到locale映射，按标志输出排序键或转回字节串；清理缓冲区',
    0x10aa4: '调用__acrt_initialize_multibyte并异或1转换返回值',
    0x10b28: 'locale名称二分查表并经索引取LCID；无匹配/越界返回0',
}


def main():
    directory = ROOT / 'dist'
    baseline = json.loads((directory / 'outer-reachable-functions.json').read_text('utf8'))
    expanded = json.loads((directory / 'outer-reachable-with-initializers.json').read_text('utf8'))
    if baseline['sha256'] != expanded['sha256']:
        raise ValueError('输入映像身份不一致')
    old = {row['begin'] for row in baseline['reachable_functions']}
    with (directory / 'outer-ghidra-remaining/functions.tsv').open(encoding='utf8') as stream:
        names = {int(row['rva'], 16): row['name'] for row in csv.DictReader(stream, delimiter='\t')}
    rows = []
    for row in expanded['reachable_functions']:
        if row['begin'] in old:
            continue
        rva = int(row['begin'], 16)
        folder = EVIDENCE / 'decompiled-memory/functions' if rva < 0x6000 else directory / 'outer-ghidra-remaining'
        path = folder / f'{int(expanded["image_base"], 16) + rva:#x}.c'
        body = path.read_bytes() if path.exists() else None
        rows.append({'rva': hex(rva), 'provider_name': names.get(rva),
                     'body': str(path), 'body_sha256': hashlib.sha256(body).hexdigest() if body else None,
                     'review_state': '正文已读，未证明动态等价' if rva in REVIEWED else '待继续审读',
                     'observation': REVIEWED.get(rva),
                     'warning_lines': [line.strip() for line in body.decode('utf8').splitlines() if 'WARNING:' in line] if body else []})
    report = {'source_sha256': expanded['sha256'], 'rows': rows,
              'additional_callback': {'rva': '0x5b08', 'registered_by': '0x5af8',
                                     'status': '原正文已读；图尚未自动解析API回调参数'},
              'limitations': ['审读语义不等于机器码动态验证或独立版实现等价',
                              '提供者符号仅作线索，待审读项不能按符号名直接排除',
                              '仅列两份调用图差集；不是所有函数或业务功能清单']}
    output = directory / 'outer-initializer-coverage.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'new_ranges': len(rows),
                      'reviewed_bodies': sum(row['observation'] is not None for row in rows),
                      'pending': sum(row['observation'] is None for row in rows)}))


if __name__ == '__main__':
    main()
