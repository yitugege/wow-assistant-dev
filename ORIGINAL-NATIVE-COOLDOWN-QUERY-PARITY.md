# 原生技能冷却查询对照

本轮新增 `tests/test_original_native_cooldown_query.py`，直接从原 addon.bin 抽取 SafeNumber、getSpellCooldownState 和 GetSpellCooldownRemaining，与独立版对应函数在 Lua 5.1 中分别执行。原包 SHA256 为 `361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`，测试启动时强制核对。

## 覆盖与结果

分别设置现代 `C_Spell.GetSpellCooldown` 与旧 `_G.GetSpellCooldown` 路径，每条路径执行 22 组输入，共 44 组原版/独立版对照。现代路径同时安装一个会报错的旧接口，确认实际选择现代接口。另行确认空技能 ID 返回零且不访问接口。

覆盖表返回、多返回值、数字字符串、小数、缺少字段、不可转换字段、负时长、刚好到期、已经到期、nil/false 返回、禁用状态以及接口抛错。每组既比较两版输出，也断言独立预期值。全部通过，单项测试 0.020 秒，无跳过。

几个实际语义：

- 表形式只有 isEnabled 明确为 false 才禁用；字段缺失或为数字 0 都没有禁用。
- 多返回值形式直接使用第三个返回值，nil/false 禁用，但数字 0 在 Lua 中为真。
- 无法转换的开始时间变成零；如果时长足够大，最终仍可能算出正剩余时间。
- 接口异常向上传递，原函数没有捕获。测试宿主使用 pcall 观察失败，不将其改成成功返回零，也不比较包含源码行号的错误文本。

执行命令：`D:/reverse-analysis/build-env/Scripts/python.exe -m unittest discover -s tests -p test_original_native_cooldown_query.py -v`。

## 边界

这验证了无本地冷却配置技能的原生查询分支及接口适配语义。API 输出由宿主提供，不是实际游戏返回；未模拟 WoW 特殊秘密值类型，也没有宣称数字字符串测试能代替秘密值验证。配置技能与持久化分支见 ORIGINAL-PERSISTENT-COOLDOWNS-PARITY.md。未发现需要修改产品代码的差异，因此没有重建 EXE 或覆盖公开发布包。
