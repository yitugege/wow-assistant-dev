# 原DirectCast模块的实际行为与缺陷

`tests/test_original_direct_cast.py`直接从原addon.bin读取DirectCast.lua，核对TOC包含该文件，并在Lua 5.1显式替身宿主中执行原文。没有改写原Lua，没有加载解锁器；UseAction、CastSpellByID、动作条放置与计时器全部只是内存记录。五项测试通过（0.057秒）。

## 已确认行为

1. 文件加载完成会设置`DC.enabled=true`，注册`/dc`、`/dcbind`，并注册1秒和0.1秒两个计时器；加载本身没有调用施法替身。
2. Core.lua的`CreateSecureButton`成功返回布尔true。DirectCast包装器将该返回值交给hookButton，后者读取`btn.HookScript`导致布尔索引错误。测试确认创建已发生，随后报错；不能把这个错误解释成安全按钮一定没创建，也不能声称HookScript已成功安装。
3. 移动时记录的待发意图在`/dc off`后仍保留；停止移动后调用0.1秒计时器两次，仍产生一次UseAction替身调用。该计时器没有检查DC.enabled。
4. PlaceAction报错时，`placeSpellToSlot`仍因`return ok2 or true`返回true；EnsureSlotForSpell缓存该槽位，第二次查询不重试放置。
5. `/dc off`只改变enabled，不阻止显式DC.Cast调用。测试调用仍进入UseAction路径；这可能是显式测试命令的设计，不能自动当成与待发计时器相同的缺陷。

## 对还原工作的影响

模块不只是按钮直调，还包含自动占槽、已有/手动槽位回退、自Buff续挂及停止移动后补发。此前移除整个文件会丢失这些分支；不能以客户端常规按键通道替代全部行为证明。

同样，原注释中“白名单永放行”“已实测”等内容只是原文件声明，不是本次环境验证。当前没有证据说明这些调用能在用户游戏的安全执行环境中生效。受保护调用必须遵守游戏执行机制，不能把改写污染标记或解锁器视为已实现的普通插件能力。

现阶段原模块仍未打入独立插件，五项测试只是确定原行为与缺陷，不等于恢复完成。后续若修复上述缺陷，应保留本对照记录并明确修复后的产品行为与原始行为不同。完整真实游戏验收仍缺失。

## 后续完整模块边界对照

本轮测试扩展至12项，全部通过（0.404秒，无跳过），日志`.local/direct-cast-boundaries.log`。每次宿主加载前校验原addon.bin SHA256为`361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`；直接执行包内原文。DirectCast.lua成员SHA256为`ad6532d630eb993c53b2c7fb9767023cb24c075c83f6c8b00c3a1132c7fe90c6`，与参考目录文件逐字节一致。

78个包成员中的Lua文件按四个符号DirectCast、MovementGate、EnsureSlotForSpell、EnvCloakCast检索，只有DirectCast.lua自身命中。此结果只证明无其他明文符号引用，不排除动态查找或外部运行时调用。TOC在BuildCompat.lua之后、DecisionBridge.lua之前加载该模块。注释宣称的`DC.BindSlot`实际不存在，手动绑定通过`/dcbind`实现；不能按注释虚构该API已存在。

新增实测结果：

- 自Buff防重与定时续挂的未知值策略不同：按ID或名字找到光环时，两者均阻止施法；名字扫描报错或扫描40项仍未结束时，GuardBlocked返回false，但续挂不触发。明确扫描到列表结束且未找到时才续挂；同槽位多等级只发一次。
- 续挂在死亡、读条、引导、冷却和关闭开关时不执行。一次尝试后，到4.999秒仍不重试，5秒边界重试；UseAction和CastSpellByID都抛错也记录这5秒间隔。
- 首次定时器运行时缺少槽位契约会缓存空guardInfo；后续补注册契约不重新构建。本测试证明这一条件分支，不证明真实TOC加载一定触发它。
- 移动意图8秒边界仍会补发，8.001秒丢弃。死亡或冷却会丢弃；普通读条保留意图，结束后补发；引导状态未检查，仍调用施法替身。普通读条测试期间未越过8秒过期界限。
- 同一技能存在多个动作条槽时，原索引保留最后一个槽（测试1与144得到144）；非空索引不刷新，移除技能后仍返回旧槽。`/dcbind`接受0和999，拒绝负数输入而保留旧值，没有槽号范围校验。
- UseAction返回false而未抛错时，DC.Cast仍返回`true, "slot1"`，不会进入直调回退。原“成功”字段只表示pcall未抛错，不能作为技能生效证据。

这些结果将迁入要求细化为：命令入口、槽位索引/缓存、光环三态判断、重试间隔、移动意图生命周期和API错误语义。按钮挂钩、动作条放置及施法仍须在游戏安全执行机制内实现和验收。当前未修改产品模块、未装入DirectCast、未改写污染标记或接入解锁器；本轮证据不代表DirectCast恢复完成。现有c29fe27本地EXE不因这些测试和文档修改而需要重新构建。

## 后续迁入：槽位登记与只读索引

c943f73后将原模块的`/dcbind`命令及已有槽位查找迁入`addon/WowBuddyDev/DirectCastSlots.lua`，TOC在BuildCompat之后加载。保存到`WowBuddyDev.DirectCast.slots`，仍是会话内存表，不增加持久化。FindSlotForSpell导出原私有查找算法，供后续施法模块接入；尚无施法消费者，登记并不使技能自动释放。

保留原行为：只接受完整的动作键+非负数字文本，接受0/999，忽略不符合格式的命令；1至144扫描忽略查询异常，重复技能保留最后一个槽；非空索引不刷新，空索引下次重扫。范围校验和缓存刷新未擅自修复，原缺陷仍在对照记录中。

`tests/test_direct_cast_slots.py`加载SHA校验后的原addon.bin完整模块，对照12条命令后的内存表和提示文字，以及重复槽、查询异常、非空缓存行为；另验证空索引可发现随后出现的技能。完整TOC及随机包测试确认`/dcbind`入口已实际装入。没有复制原按钮布尔值挂钩错误或自动施法调用；自动占槽、Cast、光环闸、移动意图、续挂、开关及环境直调等仍未接入。

本次产品源码有变化，旧EXE内嵌插件与公开附件均不含本子模块；需后续成套构建与游戏验证，不将子模块完成当作DirectCast完成。

## 后续迁入：宏解析与光环判断

7e69dcd后加入DirectCastGuards.lua，在槽位模块之后加载，提供ResolveMacro、SpellIDForName、GuardBlocked、KeeperAuraPresent。前两者及KeeperAuraPresent是将原私有函数作为后续模块共享入口；GuardBlocked保留原公开接口。加载时不查询光环，不注册施法计时器，不改按钮属性。

测试直接从经过摘要校验的原addon.bin执行完整DirectCast，再通过debug.getupvalue取得实际resolveMacro、nameToID和KeeperAuraPresent闭包，不另写预期算法。17种宏输入的解析输出、25组光环状态与API缺失组合、失败查询重试/成功缓存、空光环契约缓存后不重建等行为与原实现一致。完整TOC及随机包检查也确认入口已装入。

必须保留的原行为局限：`/use [@player] 13`也被解析成法术文本13；`[@focus]`仍返回target；多行`/cast Frostbolt`后接`/startattack`会得到`Frostbolt /startattack`；分号宏取最后匹配文本，并不根据实际目标选择条件分支。本轮不将这些文本解析结果作为正确施法目标或法术的证明。

GuardBlocked只在确认找到光环时返回true；KeeperAuraPresent在扫描报错、无名字API、40项扫描未结束等未知情况也返回true。首次建立空guardInfo后不重新建表，保留原已知缓存缺陷。续挂调度、施法与移动意图仍未接入，两个子模块也尚未进入EXE/公开发布包。
