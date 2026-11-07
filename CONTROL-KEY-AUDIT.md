# 插件控制键设置与游戏绑定保存

## 确认的问题

`SettingsUI.lua` 的三个控制键（总开关、爆发、模式切换）右键清除回调在清空插件DB后调用 `SaveBindings(GetCurrentBindingSet())`。该回调没有调用SetBinding或修改游戏绑定表，且设置新控制键的 `applyCapturedKey` 只写DB与刷新界面，不调用SaveBindings。

数据链已从当前源码核对：`Core.lua` 的InitDB将WowBuddyDev.DB指向SavedVariables WowBuddyDevDB；TOC声明持久化该表；`PixelBar.lua` 直接轮询DB.masterKey、burstKey、aoeKey。因而清除这三个控制键不需要保存游戏绑定表。

本次仅去掉右键清除回调中的多余SaveBindings调用，保留DB写入、显示刷新、左键捕获和冲突检查。没有删掉技能安全按钮、覆盖绑定或宏功能，也没有变更其他真正修改游戏绑定的路径。这是独立插件的修正，原始参考保持只读。

## 验证

`tests/test_control_key_settings.py` 通过Lua 5.1执行实际源码中的回调，并把SaveBindings和GetCurrentBindingSet设为一旦调用即报错：

- 三个控制键分别在战斗内外清除，目标字段变nil，其他两键保持，显示更新。
- 左键捕获后重新写入三个键值，设置存入相同SavedVariables对象，刷新回调正常。
- 已占用的键被拒绝，已有设置保持，并显示占用动作。

三项专项测试通过（清除项含六个子场景）；天赋导入三项、插件包两项回归通过。UI控件与游戏API为替身，不证明真实战斗状态下的全部UI操作均被游戏接受。

此前用户截图只有受保护操作通用提示，没有指出具体API。当前修复不能据此认定是当时弹窗根因。仍需游戏内事件记录中的operation及stack确认；`SecurityDiagnostics.lua` 保留ADDON_ACTION_BLOCKED/FORBIDDEN记录，不重试被阻止的调用。本轮未安装到游戏目录、重新发布插件包或进行游戏实测。
