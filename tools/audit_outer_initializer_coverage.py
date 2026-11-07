"""逐项记录初始化路径新增范围的正文身份与人工审读状态，不推算还原率。"""
import csv
import hashlib
import json
from audit_outer_reachable_functions import ROOT, EVIDENCE

# 仅对实际阅读过的正文作语义记录；不是自动按符号名称分类。
REVIEWED = {
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
