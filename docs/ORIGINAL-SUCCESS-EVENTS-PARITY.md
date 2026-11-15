# 原施法成功事件回调对照

`tests/test_original_success_events.py`从原addon.bin提取Core.lua，核对摘要`361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`，与独立Core分别执行实际局部状态初始化、IsPetSpell、resolveCooldownEventAlias及完整UNIT_SPELLCAST_SUCCEEDED回调正文。Frame只是保存并调用注册回调，未直接改写成功代次来伪造事件结果。

共131步事件历史在两端逐次比较全部快照及副作用调用记录，并断言关键结果：

- 相同GUID即使技能ID改变也去重，不重复记录冷却或调用职业处理。
- 无GUID时，同技能间隔0.049秒去重，0.051秒接受；本测试未宣称精确浮点0.05边界已穷尽。
- 等级别名事件205写入116冷却键；宠物900映射901只更新宠物冷却，不增加玩家成功代次或调用玩家职业回调。
- 非player/pet来源忽略；治疗石记录时间并在战斗中设阻止标志，饰品单独记录开始时间。
- 强制可用规则正确设置116并清除117；治疗反馈抛错被pcall隔离，后续冷却仍更新。
- 再连续120次不同GUID事件验证成功代次按1至99回绕。

2026-11-07运行`python -m unittest discover -s tests -p test_original_success_events.py -v`，1项测试通过，0.094秒，无跳过。初版夹具截取局部变量时漏掉consumableCooldownStart初始化，扩展至原声明起点后通过；未修改产品代码。

## 边界

时钟、战斗状态、职业配置及持久化/消耗品/职业回调是显式记录器或测试数据；本证据确认原事件处理器的分支、状态变化和副作用调用参数，不证明真实保存账本、每个职业OnSpellCast内部逻辑或游戏服务器确认。没有执行完整Core初始化、PixelBar渲染或客户端按键投递。打断事件仍不在本测试范围，不能把成功事件对照当作全部施法链路或完整还原验收。
