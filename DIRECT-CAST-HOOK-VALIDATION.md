# 原DirectCast按钮挂钩诊断

基线为c04b0cd；本轮只增加原模块隔离测试，没有接入或修改产品挂钩。目标仍包含恢复完整按钮行为，不能用测试宿主的默认处理顺序替代定制游戏客户端证据。

## 原文与外部线索

测试沿用原addon.bin的SHA256校验，从完整原DirectCast.CreateSecureButton闭包通过debug.getupvalue取出实际hookButton；未改写函数正文。直接调用该闭包仅用于研究挂钩本身，不代表原布尔返回值问题已经修复。原CreateSecureButton返回true后被当成按钮的问题仍由test_original_direct_cast.py单独证明。

[公开客户端UI模板镜像](https://raw.githubusercontent.com/Gethe/wow-ui-source/live/Interface/AddOns/Blizzard_FrameXML/SecureTemplates.xml)将SecureActionButtonTemplate的OnClick指向SecureActionButton_OnClick。这只支持“模板默认动作和原挂钩位于同一事件”，没有证明用户1.60.1定制客户端的原生HookScript执行顺序。不能根据该live文件就声称用户客户端一定重复施法。

## 隔离测试结果

`tests/test_original_direct_cast_hook.py`显式设定“默认事件处理先执行，再调用挂钩”的宿主模型，并设定战斗中SetAttribute抛错；它没有实现WoW原生安全执行。

- 同一按钮反复注册只挂一次，原hookedButtons保留第一次动作键。它不是每次重绑更新动作键。
- 在上述排序模型下，普通路径先记录default:macro，再记录直调尝试，然后改为emptybutton。移动路径也先记录默认宏，再设置emptybutton。挂钩不能撤销此前已经发生的默认处理。
- 如果下一次按键事件发生在After(0)恢复前，模型默认处理看到emptybutton；延时回调随后改回macro。此结果说明修改会影响后续事件，不证明真实游戏哪次按下或抬起会执行宏。
- 战斗属性写入被宿主拒绝时，顺序为默认处理、直调尝试、属性异常；恢复回调尚未排入。off、抬起和普通施法失败路径不修改属性。

原模块12项测试与新增4项测试共16项通过，耗时0.495秒。成功的含义是这些实际原Lua分支在明确模型中表现如记录，不是挂钩在游戏可用。

## 对下一步的约束

只把布尔返回值换成GetSecureButton，不能据此宣称移动吞键或防重复已经修复。还需要当前游戏版本的事件顺序及安全执行证据，之后设计并验证默认宏与直调的互斥；不能靠HookScript宿主直接覆盖原回调来制造“只施放一次”的假象，也不能以修改污染标记代替合法执行机制。

当前独立插件仍未装入自动按钮挂钩，完整还原未达成。现有04cd6be本地EXE与插件产品源码不因本次测试、文档增加而变化。
