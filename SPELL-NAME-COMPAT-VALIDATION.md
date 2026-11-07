# 技能名称查询兼容修复

2026-11-07，基线0dc1e6d。现场`/dc test class_NUMPAD5`返回`no-slot-绑槽位`后，用户取消游戏脚本查询；后续仅进行本地源码和离线测试，没有再次运行该查询或变更游戏权限。

## 确定的代码缺陷

ForeverCompat仅在旧GetSpellInfo缺失时创建兼容函数，但原函数用`type(spellID) ~= "number"`直接排除所有名称。DirectCast.ResolveMacro得到寒冰箭名称后，SpellIDForName和GuardBlocked均按名称调用这个接口，因而永远取不到法术ID。直接核对原addon.bin（SHA256 `361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`）的ForeverCompat.lua，原包也有同样判断。这是原兼容层缺陷，不是新增丢文件问题。

独立版现在接受数字或字符串，其他类型仍返回nil；保留pcall、返回字段顺序和仅缺失时补充的机制。没有覆盖已有原生GetSpellInfo，也没有加入施法权限绕过。

[客户端生成API说明的源码镜像](https://raw.githubusercontent.com/Gethe/wow-ui-source/live/Interface/AddOns/Blizzard_APIDocumentationGenerated/SpellDocumentation.lua)将C_Spell.GetSpellInfo的参数标为SpellIdentifier，并列明可使用ID、名称、带子文本名称或链接。这支持转发字符串；该live文档不能证明用户定制70862客户端的每种名称查询均可用。

## 验证

新增完整TOC接入测试，加载前明确不提供旧GetSpellInfo，只提供显式C_Spell.GetSpellInfo替身。执行实际兼容层、Core登录、职业宏注册、DirectCast宏解析与名称查询；没有再次用替身覆盖整个旧接口。

修复前测试返回与现场相同类别的`nil no-slot-绑槽位`并失败。修复后`class_numpad5`通过名称查询到116，再找到现有槽位7并调用记录式UseAction一次，目标为target。另检查数字查询仍工作、未知名称返回nil、table不传给底层、底层抛错被捕获。15项接入、原宏/光环对照与完整加载测试通过，5.952秒。

该证据证明了条件性缺陷及修复，不证明现场当前GetSpellInfo一定由这个兼容层提供；查询已取消，因此现场唯一根因仍未确认。测试UseAction是记录替身，未在游戏释放技能。

## 交付

后续交付状态：修复已包含在本地7b0eaa1 EXE，且现已安装到实际_forever_客户端，85文件及旧包备份、72个WTF文件不变核对通过；见INSTALLED-SPELL-COMPAT-VALIDATION.md。公开附件未更新，真实游戏施法未验收。下段为构建时历史状态。

本地随机包`dist/spell-name-compat/WowBuddyDev-addon.zip`，85文件，目录`w8dc69bde19b5`，SHA256 `6621922b4e04337b1408ee07cdc397d87e23b009365809ef4fd143baeedbaf90`；同时包含此前圣印回显修复。尚未安装、更新EXE或发布GitHub附件。源码审计现为24个原文件逐字节相同、41个仅名称/换行不同、12个有差异、1个原同名文件缺失但已拆模块。
