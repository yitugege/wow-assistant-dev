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
