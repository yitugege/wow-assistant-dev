# 原插件读条状态与代次差分

`tests/test_original_cast_state.py`直接从原addon.bin提取Core.lua，与独立Core.lua各自执行从`local castGenerationCounter = 1`到`local empowerGenerationCounter = 0`之前的实际正文。原包摘要为`361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`。两个Lua运行时使用同一组显式UnitCastingInfo/UnitChannelInfo、时钟和秘密值替身；不改写被比较的Lua函数正文。

验证内容：

- 22种读条输入，既比较两端结果，也断言预期的施法状态、剩余十分位秒数、技能ID与观测码。包含castBarID→castID→开始时间身份回退，读条/引导缺结束时间、秘密结束时间、到期、缺身份、秘密/无效技能ID，忽略引导、识别引导、识别蓄力和API抛错。
- 120个连续新读条，逐次重复观察，确认同一身份不增加代次；新身份代次按1至99回绕，且所有99个代次均实际出现。两端状态历史一致。
- 引导窗口的起点之前、起点本身、结束之前和结束本身共5个时间点，验证左闭右开边界。
- 成功施法状态读取的7组代次/技能ID输入，覆盖有效上限、越界、非整数、空值和数字字符串。

运行`python -m unittest discover -s tests -p test_original_cast_state.py -v`。此处读取成功施法状态时直接设置其保存字段，尚未执行完整UNIT_SPELLCAST_SUCCEEDED事件处理器；不能声称成功事件链已验收。打断也未通过真实游戏事件触发。测试不含PixelBar渲染与桌面发送，不代替已有色块测试或真实游戏读条、施法验收。本轮只增加对照证据，没有修改产品代码。
