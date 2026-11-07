# 原DirectCast按钮挂钩诊断

## 现场记录：1.60.1 / build 70862

2026-11-07用户回复“已记录”后，读取游戏自行写出的WowBuddyDevHookProbe保存变量；未执行保存文件中的Lua代码，只提取诊断字段。脱敏后的结构记录见`evidence/hook-order-70862.json`，不包含账号路径、其他设置或聊天内容。Interface为16001，诊断范围为自有按钮点击顺序。

共25条记录、7组PreClick序列；四次按下（序列1、2、4、6）均为`pre → default-marker → hook → post`，三次抬起（3、5、7）均为`pre → hook → post`。全部处于非战斗，LeftButton；被委托记录按钮的down=false不改变它在原按钮按下序列中的位置。序列1没有对应抬起记录，不能补造或推断丢失原因。

这证明当前客户端、此SecureActionButtonTemplate按钮的默认click动作先于OnClick挂钩。结合原DirectCast在OnClick挂钩里才尝试清空type的代码，不能用该方式撤销已发生的默认动作。直接将原布尔返回值换成按钮对象仍不足以恢复预期的吞键/防重复行为。应在后续设计中明确默认宏与直调的互斥，而不是复制这个已确认时序有问题的路径。

记录没有调用技能或宏，不证明CastSpellByID/UseAction获准，也不证明战斗中所有按钮或其他模板均有相同顺序。自动按钮挂钩仍未接入，真实单发权限与默认宏路径须继续实测。后文“未取得现场记录”均为此次之前的历史状态。

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

## 后续：手动现场诊断按钮

8637591后新增HookOrderProbe.lua及独立SavedVariables变量WowBuddyDevHookProbe。它不是DirectCast自动挂钩，不更改现有技能按钮或按键。

安装包含此模块的插件并进入角色后，脱战输入`/wbdhookprobe`，手动点击中央按钮，再输入`/wbdhookprobe report`查看记录，`/wbdhookprobe hide`关闭。重新打开会清空上次记录；退出或重载UI后由游戏保存到WTF。未获得记录前不能认定现场顺序。

诊断按钮继承SecureActionButtonTemplate，仅设置type=click和指向本插件记录按钮的clickbutton。它保留模板OnClick，另外记录PreClick、HookScript(OnClick)、PostClick；被委托的记录按钮只追加default-marker记录。此设计依据[客户端UI源码镜像的SECURE_ACTIONS.click](https://raw.githubusercontent.com/Gethe/wow-ui-source/live/Interface/AddOns/Blizzard_FrameXML/SecureTemplates.lua)，仍需验证定制客户端是否支持相同动作；若没有default-marker，报告明确提示不能判断顺序。

按钮不设置宏、技能、目标或按键，不调用施法、切目标、动作条放置API。仅在用户输入命令后创建，不自动点击。保存实际插件目录名、游戏构建号、Interface、时间、战斗状态和最近60条阶段记录。战斗中拒绝创建/显示/关闭；已创建按钮的点击回调只记录，不写安全属性。

3项记录器测试使用两种相反的显式宿主顺序，确认均如实记录而非固定预期；还覆盖默认动作缺失、记录上限、重复打开和战斗门控。与完整TOC及打包测试合计11项通过（4.475秒）。这些不是原生安全执行或实机点击证明；原模板源码也不能代替用户当前客户端的记录。

本地随机包`dist/hook-order-probe/WowBuddyDev-addon.zip`，目录`wbc204a3dc89e`，SHA256 `53b1cd4012ce71e344f0e47f0788fee50f645b981b5c9add38e7e276ac12d031`。尚未安装、公开发布或重新构建EXE。

后续安装状态：该包已通过独立安装器安装到本机_forever_客户端，保留已有目录名WowBuddyDev，旧版已备份，WTF文件保持不变；详见INSTALLED-HOOK-PROBE-VALIDATION.md。尚未取得原生点击记录，公开发布与EXE重建状态不变。
