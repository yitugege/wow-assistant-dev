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

## 后续迁入：显式施法核心与自动占槽

b7bc7e3后加入DirectCastActions.lua，在Guards之后加载。恢复EnsureSlotForSpell、增强版Cast及无技能ID时回到原始Cast的分支，连接Slots/Guards；提供`/dc test <动作键>`、`/dc on|off`。显式Cast在off时仍可调用，遵循原行为。开关帮助文案改为说明尚未接入的自动分支，并明确返回值不是实际施法成功；不复述原文件“已解锁/永放行”的未经验证声明。

原API调用顺序对照：54组已有/空/满动作条、UseAction与CastSpellByID正常/抛错/返回false、手工槽位有无组合，每组重复调用验证缓存；9组PickupSpell/PlaceAction结果组合重复查询；另覆盖无宏、无法解析、无技能ID、宏登记表回退、off后的显式测试、已有自Buff拦截。32项相关测试通过，耗时5.352秒。所有API均为内存记录替身，未执行实际游戏输入。

原已知缺陷继续保留并显式标注：PlaceAction抛错仍缓存槽位；返回false但不抛错会被当作pcall成功；非空槽索引不刷新。新增模块没有写游戏内存、重写污染状态、安装解锁器，也未挂接自动施法计时器；实际权限由游戏处理。正常客户端拒绝调用时不能声称功能可用，必须实机验收。

仍缺自动按钮挂钩、移动补发、自Buff续挂调度、EnvCloakCast等原入口；原Core的宏注册表并非公开字段，class_*动作键能否通过当前宏查询得到文本也尚需整体验证，不能用孤立fixture证明全套按键可调用。

已生成本地随机插件包`dist/directcast-actions/WowBuddyDev-addon.zip`：目录`w2e6c1e425e03`，81成员，SHA256 `50c57e910515efa4467236a6d8cc2620667fd1cd5cb795c289169ceff8a757bb`。相邻manifest记录成员摘要。打包完整性验证通过，未安装到游戏、未覆盖公开Release，也未重建内嵌插件的EXE。

## 后续接入修复：实际职业宏登记

在f3c5acd完整TOC登录宿主中复现：法师class_NUMPAD1至class_NUMPAD4的实际按钮存在宏文本，而DirectCast.Cast均返回`nil, no-macro`；class_NUMPAD5也作为回归覆盖。原因是Core的macroBindingRegistry为local，原DirectCast尝试读取的ADDON.macroBindingRegistry不存在；DEFAULT_MACROS不按class_*键存储。此前孤立宏表fixture无法揭示这个接入缺口。

修复增加Core.GetBoundMacro，只返回成功登记的宏文本字符串，不公开可变表，不直接读取按钮受保护属性。DirectCast在原DEFAULT_MACROS/公开登记表两路均无结果时才调用此接口。class_*后缀按Core已有规则规范化，兼容原`/dc`命令将输入转成小写的行为。这是明确修复，原实现对这些输入返回no-macro的行为不再保留；已有原路径的对照仍通过。

新测试执行完整插件并登录：九职业逐个非空宏键与实际按钮文本一致；法师class_NUMPAD5及小写命令进入UseAction替身；成功重绑后使用新宏及新目标，失败重绑后返回no-macro而不使用已清除登记；战斗中延迟重绑仍读取当前已登记宏。36项DirectCast/加载/打包测试通过（6.782秒），17项既有绑定/宏注册/控制设置/职业重载回归通过（0.158秒）。仍无真实游戏施法证据。

当前本地插件包更新为`dist/directcast-integration/WowBuddyDev-addon.zip`，目录`w89b13f7af55f`，SHA256 `5254ff4535dd499024e0d098cfe1b888d33bea236b9d876dc49a0d27bac2ff27`。旧directcast-actions包保留且不含本次修复；两个本地包都未公开发布或安装，现有EXE也不含本轮改动。

## 后续迁入：移动意图与停步补发

761516d后增加DirectCastMovement.lua，注册0.1秒计时器，并将Actions的宏查询作为共享只读入口。MovementGate能解析原DEFAULT_MACROS及已修复的实际Core职业宏；读条技能移动时记住技能、单位和时间，停步连续两拍后按原槽位优先/API回退路径尝试补发。普通按钮尚无挂钩调用MovementGate，因此不能称为已实现普通按键的自动拦截。

5项新测试对照原addon.bin完整模块的移动计时器：8秒及8.001秒边界，死亡/普通读条/引导/冷却/off，重新移动后静止计数复位，单次意图不重复发出，瞬发/停步/无技能ID/关闭状态，以及UseAction抛错回退而返回false不回退。完整插件法师登录后，class_numpad5能产生意图，执行实际Movement计时器两次后到达UseAction替身。相关41项测试通过，耗时7.132秒。

有意保留原行为并在`/dc`帮助中提示：off不清已有意图；引导状态不阻止补发；普通读条会保留意图等待；超过8秒或死亡/冷却会丢弃。实际游戏权限仍由游戏决定，没有新增内存写入、污染标记修改或解锁手段。本轮未游戏实测，也未接入自Buff续挂或按钮挂钩。

最新本地随机包为`dist/directcast-movement/WowBuddyDev-addon.zip`，目录`wf1c9f2648bcb`，SHA256 `64ed6bfc600dc6a2546c9da5101faeedd5bf30641eddc4deff8463d1a49a415e`。旧包、EXE及公开Release未覆盖；本包未安装。

## 后续迁入：自Buff续挂调度

e2bc73b之后新增DirectCastKeeper.lua，在Actions之后、Movement之前加载，注册1秒周期回调。Guards提供内部迭代入口，与GuardBlocked共用原先惰性建立的光环契约快照。续挂按同组首个技能ID去重，仅确认光环不存在时尝试；死亡、普通读条、引导、冷却或off阻止尝试。沿用原5秒重试间隔，包括两个API都抛错的情况。

5项新增测试将独立回调与原addon.bin完整模块的实际回调对照，覆盖光环ID/名字/未知/完整扫描缺失，4.999与5秒边界，角色状态、未知技能名、两API失败、返回false语义、首次空快照后不刷新。另执行完整插件法师登录，使用真实Mage光环契约中的一个组，仅为该组提供已知技能API，确认计时器到达UseAction(slot=7, unit=player)替身；不是游戏施法测试。相关46项测试通过（7.409秒）。

有意改变提示文案：原来直接写“自动续挂”，现在写“已尝试续挂（是否生效以游戏为准）”，避免把pcall未抛错误报为技能生效。调度顺序、光环判定、失败重试等保持原对照行为。代码仍扫描已注册契约，未额外添加只限当前职业/已学习技能的过滤；完整游戏环境的技能可用性和实际施法仍需验证。

自动按钮挂钩与EnvCloakCast尚未接入，不能声明DirectCast完整恢复。最新本地包`dist/directcast-keeper/WowBuddyDev-addon.zip`，随机目录`wf9c828087b6d`，SHA256 `ac9209cfb1e108119a2176c8e5d96170301c5463906060bd17dd5705a4a2ca55`。原有包保留，新包未安装/公开发布，EXE未重建。
