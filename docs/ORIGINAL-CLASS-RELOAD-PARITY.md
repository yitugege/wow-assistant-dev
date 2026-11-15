# 原专精切换与临时状态清理对照

`tests/test_original_class_reload.py`从原addon.bin（SHA256 `361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`）读取实际九职业class_forever注册模块、ForeverTalentData、ForeverClassSupport，以及Core的reloadClassData完整函数；独立源码在另一Lua运行时执行相同流程。

13次连续切换覆盖全部九职业、重复返回旧职业、未知专精9999和无专精。每次先放入旧缓存标记，再执行实际切换函数，断言：

- 11个技能/按键/像素/冷却/持久化定义/动作/额外值/消耗品表，存在职业定义时指向本次注册模块的同一表，缺省时为空。
- 冷却结束缓存、消耗品冷却、强制可用状态清空；消耗品状态已知标记复位，饰品开始时间和时长清除。
- 未知或无专精时classData、饰品ID清空，事件别名索引、待物品信息表及强制可用规则清空，不执行恢复回调。
- 有效专精按原顺序调用重建消耗品索引、恢复技能冷却、恢复消耗品冷却、刷新标志；原/独立两端调用序列相同。

2026-11-07运行`python -m unittest discover -s tests -p test_original_class_reload.py -v`，1项测试通过，0.045秒，无跳过。切换函数的外部依赖使用记录器，所以不证明真实持久化恢复后的全部值，也不证明真实游戏专精事件自动触发或桌面协议切换。这里只对实际reloadClassData的数据替换、清理及依赖调用顺序取证，未执行完整Core初始化；没有修改产品代码。
