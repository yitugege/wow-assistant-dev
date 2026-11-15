"""读取插件源码；Core.lua 按拆分标记拼回原顺序，供按片段截取的对照测试使用。

Core.lua 中的 `-- @@拆分：X.lua@@` 行替换为 X.lua 的正文（文件头与模块登记行之后的部分），
并去掉拆分时新增的模块登记行和 _coreShared 别名行，状态表字段访问还原为原 local。拼回结果应与拆分前的 Core.lua 一致
（拆分前已有的模块注册表除外，它已移到 Modules.lua）。
"""
from pathlib import Path
import re

ADDON = Path(__file__).resolve().parents[1] / 'addon/WowBuddyDev'
BODY = '-- ---- 以下为原 Core.lua 内容 ----'
MARKER = re.compile(r'^-- @@拆分：(.+\.lua)@@$')
ORIGINAL = re.compile(r'^-- @@原行：(.*)@@$')   # 声明随代码移走，原位置留下原文
# 原文件级 local 状态改为状态表字段：coreState.X 拼回为 X；带 @@状态表@@ 的字段赋值行拼回为 local 声明。
STATE_DECL = re.compile(r'^coreState\.([A-Za-z_][A-Za-z0-9_]*) = (.*) -- @@状态表@@$')
STATE_REF = re.compile(r'\bcoreState\.(?=[A-Za-z_])')


def _restore_state(line):
    decl = STATE_DECL.match(line)
    return f'local {decl.group(1)} = {decl.group(2)}' if decl else STATE_REF.sub('', line)


def _added(line):
    return (line.startswith('WowBuddyDev.RegisterModule(') or 'WowBuddyDev._coreShared.' in line
            or line.endswith('-- @@拆分新增@@') or line.endswith('-- @@注册表命名空间@@'))


def split_body(name, addon=ADDON):
    lines = (addon / name).read_text('utf-8').split('\n')
    body = [_restore_state(line) for line in lines[lines.index(BODY) + 1:] if not _added(line)]
    while body and body[-1] == '':
        body.pop()
    return body


def rebuilt_core(addon=ADDON):
    out = []
    for line in (addon / 'Core.lua').read_text('utf-8').split('\n'):
        match = MARKER.match(line)
        original = ORIGINAL.match(line)
        if match:
            out.extend(split_body(match.group(1), addon))
        elif original:
            out.append(original.group(1))
        elif not _added(line):
            out.append(_restore_state(line))
    while out and out[-1] == '':
        out.pop()
    return '\n'.join(out) + '\n'


def addon_source(path, addon=ADDON):
    return rebuilt_core(addon) if path == 'Core.lua' else (addon / path).read_text('utf8')
