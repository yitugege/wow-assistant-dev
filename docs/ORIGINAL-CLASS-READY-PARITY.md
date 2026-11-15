# 原内置插件与独立插件的技能就绪对照

## 原始证据与执行方法

测试直接读取原EXE解包得到的 `D:/reverse-analysis/wow-assistant/unpacked/addon.bin`，先校验SHA256为 `361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`，再从包内取得Lua正文。没有以参考工程副本替代原包证据。

`tests/test_original_class_ready.py`分别建立两个独立Lua 5.1环境，加载原包/独立版ForeverTalentData、ForeverClassSupport、各职业class_forever及完整PixelBar，并取各自Core中的公共字段定义。宿主只提供显式游戏/UI替身，将原全局名P07483180映射到测试命名空间；原函数正文不改写。

## 覆盖与结果

先核对九职业actionAvailSpellIDs顺序与内容一致，共182项。每项测试已学/未学×可用/不可用×冷却nil、-1、0、0.01、3，共3640组；再各加一组未学、不可用、冷却3秒但自身位列强制可用名单的输入，共3822组。每组同时比较IsSpellReadyRaw与IsSpellReady返回值，合计7644次返回值比较，全部一致。

外层职业OverrideIsSpellReady和别名路径保持真实注册结果。德鲁伊形态特判因此包含在比较中；战士撕裂免疫状态只覆盖初始状态，未假称覆盖此前施法事件造成的免疫窗口。

测试1项通过，用时0.303秒，日志 `.local/original-class-ready.log`。本轮没有修改产品源码或生成新EXE。

## 限制

学习状态接口在单组中对所有技能返回同一布尔值，尚未覆盖每个技能等级与别名逐一学习的组合。游戏API异常、秘密值、职业事件历史和实际施法未验收。此项证明所列输入下原/独立Lua判定相同，与CLASS-ACTION-PIXEL-VALIDATION.md的236帧绘制链证据互补；不代表所有职业循环或全部原程序功能完成。

## 后续补充：逐等级学习与别名

针对上一节统一布尔学习状态的限制，新增按具体技能ID返回已学状态的接口替身。先比较九职业原包与独立版的spellReadyAliases内容及各组顺序；然后对每个职业分别执行未学任何技能、全部已学，以及动作ID和等级别名集合中每次只学一个ID。

新增19022组输入，逐组比较IsSpellKnown、IsSpellReadyRaw、IsSpellReady，全部一致；其中680组实际经过基础Raw不可用、等级别名使最终可用的路径。保持真实职业OverrideIsSpellReady和别名遍历，不强制修改技能可用状态。此前3822组仍通过。日志 `.local/original-class-ranks.log`。

新增覆盖补足“仅学某一等级”的常见边界，但仍非所有多技能学习子集、各等级不同冷却、宠物技能书或秘密值场景的穷举；游戏执行验证仍缺失。本次只有验证代码变更，不修改发布EXE。

## 当前职业注册与通用宠物分支

后续核对发现不能根据猎人/术士名称推定通用宠物技能书分支已启用。测试现在同时执行原/独立Core的真实IsPetSpell函数，逐一检查九个实际注册class_forever模块：petSpells与petSpellPlayerWrappers均为nil，182个动作位在原/独立IsPetSpell中均返回false。新旧接口的宠物专属分支是PixelBar保留的通用代码，不是这批注册动作当前配置的执行路径。

接入真实IsPetSpell后，原3822组状态与19022组等级输入仍全部通过，日志 `.local/original-pet-registration.log`，0.909秒。本证据不意味着游戏中没有宠物技能，也不证明全部宠物相关功能已验证；只能说明这九份原/独立注册表没有启用该通用分类。后续如发现运行时新增petSpells的证据，应重新检查分支可达性，不能凭该静态/加载时结果排除所有动态变化。
