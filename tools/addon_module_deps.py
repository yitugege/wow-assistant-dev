"""插件模块依赖声明：静态分析各文件对命名空间字段的定义与读取，校验或更新 Namespace(名, uses) 声明。

用法：
  python tools/addon_module_deps.py           校验每个文件声明的 uses 与 Modules.lua 中的字段归属表都与静态分析一致（不一致返回 1）
  python tools/addon_module_deps.py --write   按分析结果重写声明行和字段归属表

规则：命名空间访问包括 WowBuddyDev.X 与文件内别名（local ADDON = WowBuddyDev）的 ADDON.X；
`function NS.X(` / `NS.X = ...` 为定义，其余为读取；读取的字段映射到 TOC 中首个定义它的文件。
字段归属表写在 Modules.lua 的 OWNERS_BEGIN / OWNERS_END 标记之间，运行时边界检查按它判断字段属于哪个模块。
"""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_addon import toc_entries  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'addon/WowBuddyDev'
TAG = '-- @@注册表命名空间@@'
ALIAS = re.compile(r'^local ([A-Za-z_][A-Za-z0-9_]*) *= *(?:_G\.)?WowBuddyDev *(?:--.*)?$', re.M)
OWNERS_BEGIN = '-- @@字段归属开始@@ 由 tools/addon_module_deps.py --write 生成，勿手改'
OWNERS_END = '-- @@字段归属结束@@'
DECL = re.compile(r'WowBuddyDev\.Namespace\("([^"]+)", \{ ?(.*?) ?\}\)')
KEYWORDS = set('and break do else elseif end false for function goto if in local nil not or repeat return then true until while'.split())


def tokens(src):
    """产出 (line, kind, text)；kind: name/kw/op/vararg。忽略字符串与注释。"""
    i, line, n = 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == '\n':
            line += 1; i += 1; continue
        if c in ' \t\r':
            i += 1; continue
        if src.startswith('--', i):
            m = re.match(r'--\[(=*)\[', src[i:])
            if m:
                close = ']' + m.group(1) + ']'
                j = src.find(close, i + m.end())
                j = n if j < 0 else j + len(close)
            else:
                j = src.find('\n', i)
                j = n if j < 0 else j
            line += src.count('\n', i, j); i = j; continue
        m = re.match(r'\[(=*)\[', src[i:])
        if m:
            close = ']' + m.group(1) + ']'
            j = src.find(close, i + m.end())
            j = n if j < 0 else j + len(close)
            line += src.count('\n', i, j); i = j; continue
        if c in '"\'':
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == '\\':
                    j += 1
                j += 1
            line += src.count('\n', i, j); i = j + 1; continue
        m = re.match(r'[A-Za-z_][A-Za-z0-9_]*', src[i:])
        if m:
            w = m.group(0)
            yield line, ('kw' if w in KEYWORDS else 'name'), w
            i += m.end(); continue
        m = re.match(r'0[xX][0-9a-fA-F]+|\d*\.?\d+(?:[eE][+-]?\d+)?', src[i:])
        if m and m.group(0):
            i += m.end(); continue
        if src.startswith('...', i):
            yield line, 'vararg', '...'; i += 3; continue
        yield line, 'op', c
        i += 1




def toc_files(addon=ADDON):
    """TOC 中的文件（相对插件目录的 POSIX 路径），解析与校验同打包脚本。"""
    root = Path(addon).resolve()
    return [path.relative_to(root).as_posix() for path in toc_entries(root)]


def module_files(addon=ADDON):
    return [f for f in toc_files(addon) if f.endswith('.lua') and not f.startswith('Libs/') and f != 'Modules.lua']


def field_access(source):
    """返回 (定义的字段, 读取的字段)。"""
    names = {'WowBuddyDev'} | set(ALIAS.findall(source))
    toks = list(tokens(source))
    defined, read = set(), set()
    for i, (_, kind, text) in enumerate(toks):
        if kind != 'name' or text not in names or i + 2 >= len(toks):
            continue
        if i and toks[i - 1][2] in '.:' and not (text == 'WowBuddyDev' and i >= 2 and toks[i - 2][2] == '_G'):
            continue
        if toks[i + 1][2] not in '.:' or toks[i + 2][1] != 'name':
            continue
        prev = toks[i - 3] if i >= 3 and toks[i - 1][2] == '.' and toks[i - 2][2] == '_G' else (toks[i - 1] if i else None)
        nxt = toks[i + 3] if i + 3 < len(toks) else None
        nxt2 = toks[i + 4] if i + 4 < len(toks) else None
        is_def = (prev is not None and prev[2] == 'function') or \
                 (nxt is not None and nxt[2] == '=' and not (nxt2 is not None and nxt2[2] == '='))
        (defined if is_def else read).add(toks[i + 2][2])
    return defined, read


def _access(addon):
    return {f: field_access((addon / f).read_text('utf-8-sig')) for f in module_files(addon)}


def field_owners(addon=ADDON):
    """字段 → 所属模块：TOC 顺序中首个定义该字段的文件。"""
    owner = {}
    for f, (defined, _) in _access(addon).items():
        for field in defined:
            owner.setdefault(field, f[:-4])
    return owner


def owners_block(addon=ADDON):
    rows = [f'  ["{field}"] = "{module}",' for field, module in sorted(field_owners(addon).items())]
    return '\n'.join([OWNERS_BEGIN, 'local staticOwners = {', *rows, '}', OWNERS_END])


def current_owners_block(addon=ADDON):
    text = (addon / 'Modules.lua').read_text('utf-8-sig')
    start, end = text.index(OWNERS_BEGIN), text.index(OWNERS_END) + len(OWNERS_END)
    return text, start, end


def analyse(addon=ADDON):
    files = module_files(addon)
    toc = toc_files(addon)
    access = _access(addon)
    owner = {field: module + '.lua' for field, module in field_owners(addon).items()}
    return {f[:-4]: sorted({owner[x][:-4] for x in access[f][1] if x in owner and owner[x] != f},
                           key=lambda m: toc.index(m + '.lua')) for f in files}


def declared(addon=ADDON):
    result = {}
    for f in module_files(addon):
        line = next((l for l in (addon / f).read_text('utf-8-sig').split('\n') if l.endswith(TAG)), '')
        match = DECL.search(line)
        result[f[:-4]] = (match.group(1), re.findall(r'"([^"]+)"', match.group(2))) if match else (None, None)
    return result


def main(argv):
    expected, actual = analyse(), declared()
    if '--write' in argv:
        for module, uses in expected.items():
            path = ADDON / (module + '.lua')
            data = path.read_bytes()
            bom = data.startswith(b'\xef\xbb\xbf')
            text = data.decode('utf-8-sig')
            dep_text = ', '.join(f'"{d}"' for d in uses)
            text = DECL.sub(lambda m: f'WowBuddyDev.Namespace("{module}", {{ {dep_text} }})', text, count=1)
            path.write_bytes((b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8'))
        text, start, end = current_owners_block()
        (ADDON / 'Modules.lua').write_text(text[:start] + owners_block() + text[end:], 'utf-8')
        return 0
    problems = [(m, actual[m], uses) for m, uses in expected.items() if actual[m] != (m, uses)]
    for module, got, want in problems:
        print(f'{module}: 声明 {got}，分析结果 {want}')
    text, start, end = current_owners_block()
    stale = text[start:end] != owners_block()
    if stale:
        print('Modules.lua 中的字段归属表与分析结果不一致，请运行 --write')
    print(f'{len(expected)} 个模块，{len(problems)} 处不一致')
    return 1 if problems or stale else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
