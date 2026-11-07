# 已交付职业冷却配置与重载边界

本轮检查实际职业注册表，区分Core支持持久化冷却与交付职业是否启用该功能。

## 原包配置对照

校验原addon.bin身份后，分别执行原包与独立源码九份完整class_forever.lua的注册代码，记录RegisterClass实际收到的表；只对比cooldowns、persistentCooldowns及persistentChargeTrackers，不用字符串搜索代替运行结果。

- 九职业均未注册persistentCooldowns或persistentChargeTrackers。
- 猎人cooldowns为3044→6秒、5116→12秒、2973→6秒；其他八职业没有该表。
- 两侧上述字段完全一致。Core在职业装载时用空表补齐缺省持久化配置。

此前 `test_original_persistent_cooldowns.py` 使用人为提供的持久化技能/充能配置验证通用函数及事件片段，证据仍有效，但不能当作这九个职业实际启用持久化的证明。此结论不涵盖外部脚本动态增配、其他未交付职业或消耗品专用账本。

## 独立完整插件的重载检查

加载完整TOC及猎人登录/进世界事件，给玩家成功施放3044事件：查询为6秒，运行时间推进2.25秒后为3.75秒。保存变量中的persistentCooldownLedger为空。

把保存变量递归复制到第二个全新Lua运行时，再加载并执行登录/进世界；服务器时间只推进2秒，本地会话时钟重置为1，不执行15秒延时队列，避免6秒冷却自然结束掩盖结果。此时查询3044冷却为0，持久化表仍为空。测试没有手动清理原运行时内部缓存，确实使用新的Lua运行时。

这证明当前独立插件在该配置与事件宿主下不会跨会话恢复这三个技能中的已测3044计时。原Core中对应固定cooldowns分支读取本次会话lastCastTimeBySpell，只有persistentCooldowns配置存在时才尝试账本恢复；本轮未用原完整插件执行同一重载场景，不外推为真实游戏API整体表现。

## 验证及限制

新增两项检查与原持久化函数对照合计3项通过，0.343秒；日志 `.local/shipped-cooldown-check.log`，新增文件 `tests/test_shipped_cooldown_configuration.py`。初次测试宿主缺少CreateFrame，随后复用已有显式加载宿主；账本实际为空表而非不存在，已按观察修正断言。

没有擅自给职业新增持久化定义，也未改产品源码、EXE或游戏安装。游戏原生冷却、其他就绪判定和实际施法仍需各自验证，不能仅据此推断重载后一定会重复施法。
