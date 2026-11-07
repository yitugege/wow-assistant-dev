# 原内置插件完整色块回调差分

新增`tests/test_original_pixelbar_frames.py`，直接从原EXE解出的addon.bin读取Lua，核对SHA256 `361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`，与当前独立插件在两个Lua 5.1运行时分别执行。原命名空间仅通过别名接入测试宿主，原Lua正文不改写。

双方执行ForeverTalentData、ForeverClassSupport、对应职业注册文件，以及完整ActionKeyCheck、AutoTarget、PixelBar文件，调用实际RebuildPixelBars和OnUpdate。Core只取实际COMMON_PIXEL_DATA表；其他游戏API、帧对象、技能查询及部分Core接口由显式宿主替身提供，不声称加载了完整原插件或真实游戏。

九职业各12步连续状态，共108帧：初始、进入战斗、资源/血量/移动变化、资源读取失败与饰品冷却、血量归零、目标死亡、输入焦点、技能已学、总开关关闭、重新开启并脱战、数值恢复、再次进入战斗。比较所有注册通用/职业字段的值，以及可见纹理的位置、尺寸、RGB和容器可见状态；颜色对象比较其RGBA值而非两个运行时的对象地址。

明确排除两处已经记录的协议差异：addon_version_code使用独立版本标记；action_avail改用24个有效位。字段及其对应纹理位置均按实际COMMON_PIXEL_DATA定位排除，不用任意坐标忽略其他差异。这两处已有独立协议测试，本测试不证明其原始字节相同。

运行：

```powershell
& D:/reverse-analysis/build-env/Scripts/python.exe -m unittest discover -s tests -p test_original_pixelbar_frames.py -f
```

2026-11-07结果：1项测试、108帧对照通过，0.693秒，无跳过。初版测试错误地比较Lua对象身份、遍历包含函数的内部状态表，并缺少已学技能场景的技能查询替身；修正为注册输出字段、RGBA及显式游戏查询输入后通过，没有为测试改动产品Lua。

这补充了“同样输入下原插件与独立插件实际回调输出一致”的证据。输入状态不是所有WoW API组合，帧对象没有实现真实游戏安全执行和显示环境；不能据此证明插件加载、受保护操作、抓屏、施法、连续换怪或20.0.1可读发送端完成。本轮未检测到Wow/WowClassic/WowB进程，未进行游戏操作。
