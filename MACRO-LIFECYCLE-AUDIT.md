# 安全按钮重建与职业切换联测

## 验证对象

此前 `test_class_macro_registration.py` 执行职业绑定表，但将CreateSecureButton替换为记录请求的函数，因此只能证明桌面动作有非空注册请求，不能证明实际Core.lua按钮创建、属性设置、覆写绑定清理或事件调度正确。

本轮新增 `tests/test_macro_binding_lifecycle.py`，直接执行Core.lua从secureButtons登记表到CheckMacroBindings的实际代码。CreateSecureButton、ApplyMacros_Internal、RefreshMacroBindings、OnEvent和绑定自检均为真实Lua实现；游戏的Frame、覆盖绑定、计时器和战斗状态为可观察替身。所有受测修改API在战斗状态下调用都会抛出异常，测试同时核对修改次数，避免异常被pcall吞掉后误判。

## 五项测试结果

1. 切换动作表后清除旧按键，旧按钮type和macrotext清空，新绑定完整建立。
2. 战斗中刷新不执行任何按钮或绑定修改，旧键暂时保留并记录pending；PLAYER_REGEN_ENABLED后按最新动作表重建，自检恢复通过。
3. 多个UPDATE_BINDINGS合并为一个下一帧任务；重建自身触发的绑定事件不会继续排队递归刷新。
4. 一个按键被后端拒绝时，其他动作仍建立，自检准确报告失败项并记录错误。
5. 执行真实Bindings.lua及九个职业的class_forever/Bindings文件，连续切换职业；241个桌面动作对应的按钮type、macrotext与职业宏表一致。每轮实际绑定键集合精确等于当前职业非空宏键集合，没有前一个职业的残留键；CheckMacroBindings全部通过且没有错误记录。

五项测试通过，0.044秒。本轮未修改业务逻辑或插件实现，没有以“增加测试”替代已知功能缺口；它补足此前注册测试不覆盖的实际Lua生命周期证据。

## 仍未证明

Frame及绑定操作不是实际游戏客户端API，因此不能证明宏在所有客户端版本可执行、按键会被接受、战斗技能会释放，或受保护操作弹窗已消失。尚未穷尽战斗开始与事件回调交错、焦点/自动选怪扩展绑定失败、全部用户自定义宏和游戏重载场景。此前18套方案引用原资源也缺失动作的问题不由本测试解决。
