# 同专精协议切换的显示表修复

用户已明确选择修复协议切换，让独立版正常解码，并保留原行为对比。因此默认修复模式不要求重现原程序的短字段表异常；`legacy_descriptor_cache=True` 继续用于旧行为对照。

## 发现的缺口

此前DecisionPipeline按协议及专精重建解码表，但FrameController仅在专精改变时推进display_revision。相同专精从old切到readable后，真实Qt界面仍保留旧行的字段名称、类型、过滤属性和未覆盖尾部；MonitoringLoop的字段字符串缓存长度也未随新表同步。

新增从真实Qt主窗poll_once贯穿抓屏结果、控制器、会话缓存到字段控件的联测，九专精分别执行old→readable→old→readable，共36次输入。修复前25个场景失败，日志 `.local/switch-display-before.log`。既有只比较解码Frame的测试无法发现这层显示问题。

## 修复与验证

默认修复模式在相同专精、不同显示协议时推进display_revision，使既有显示缓存同步和Qt字段重建路径生效。仅切换协议不重新恢复保存的方案，也不触发专精变化回调；旧行为对比模式不走新增分支。

修复后36次输入的完整显示行（包括元数据与解码值）、字段缓存长度、每个缓存字符串均与全新控制器结果一致。三个协议切换测试通过，其中原旧模式法师短表异常仍可复现。报告 `.local/switch-display-after.log`。134项核心回归以及old/readable各两条捕获路径的监控集成测试通过，记录 `.local/switch-display-core.log`、`.local/switch-display-monitor.log`。

测试使用真实Qt控件和合成图像，抓屏后端为替身，发送器为空；没有真实游戏发键，不证明游戏协议切换已验收。修复已进入源码，尚未重新构建或更新公开附件。
