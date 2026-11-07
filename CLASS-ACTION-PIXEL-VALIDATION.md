# 九职业技能状态绘制与客户端解码验证

## 实际覆盖

`tests/test_pixelbar_full_module.py`执行独立源码中的ForeverTalentData、ForeverClassSupport、各职业class_forever、ActionKeyCheck、AutoTarget及完整PixelBar。读取真实Lua纹理回调写出的矩形和RGB构建画面，交给当前桌面pipeline解析，再由EvaluationContext读取技能可用性。测试没有按客户端契约直接填造技能色块。

|职业|技能可用位数|新增状态帧数|
|---|---:|---:|
|法师|21|27|
|德鲁伊|24|30|
|猎人|21|27|
|圣骑士|19|25|
|牧师|20|26|
|盗贼|17|23|
|萨满|18|24|
|术士|19|25|
|战士|23|29|
|合计|182|236|

每个职业先覆盖未强制、全部强制以及逐个技能强制可用。此组验证的是原有forceAvailableState路径、职业就绪判定结果、RGB编码、桌面开发协议转换与字段索引的一致性；不把强制状态当作真实技能已就绪。保留职业OverrideIsSpellReady及别名逻辑，通过完整IsSpellReady结果与桌面availability逐项比较，确认最大24位不丢失。

另每个职业执行四组游戏API输入：已学/可用/无冷却/有射程，已学/可用/冷却3秒/无射程，已学/不可用/无冷却/有射程，未学/可用/无冷却。没有替换IsSpellReadyRaw或IsSpellReady，验证基础就绪门控、职业最终就绪结果、已存在的known字段及已学情况下的range字段。射程及冷却来自显式游戏API替身，未在游戏客户端执行。

## 结果与边界

新增236帧全部通过；整个文件4项测试通过，用时20.579秒，包含此前自动选怪、法师循环及治疗链测试。日志 `.local/pixelbar-all-action-states.log`。本次无需修改产品源码，没有新增可执行构建。

182是actionAvailSpellIDs的位数总和，不是所有动作数；不能与241个注册动作混称。未穷尽全部技能等级、别名组合、职业覆盖条件、秘密值/异常、全部字段类型或41套循环实战，也不证明实际游戏施法、插件安全执行或readable发送端。该结果验证的是自有协议与自有客户端的一致性；原包及独立协议已知差异仍见ADDON-MIGRATION-DIFFERENCES.md。
