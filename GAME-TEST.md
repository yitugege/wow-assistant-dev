# 最新部署状态（2026-11-07 UTC）

## 自动选怪离线联测补充

后续纹理编码验证：新增`tests/test_auto_target_pixel_encoding.py`从PixelBar.lua提取并执行未改写的取包pcall段、rgbFromInt、普通number上色段及setTextureColor；纹理对象为记录颜色的替身。81按键×5状态×32回执×31序号，共401,760种有效整数包全部经过Lua取包、RGB赋色及桌面parse_auto_target解码，无字段丢失。取包函数缺失、抛错、返回字符串/布尔/表五种情况均写零，桌面不识别为选怪包。执行Core.lua实际COMMON_PIXEL_DATA定义，确认ttd为第20格（零基19）、number类型，与旧契约一致。

此轮7项选怪测试通过，日志`.local/auto-target-texture.log`；未修改产品代码或发布包。只执行所列真实源码片段，不能称为完整PixelBar每帧回调、RebuildPixelBars布局执行或真实GPU纹理渲染验证；可读协议的完整插件绘制也未由此覆盖。精确整数包验证不包括任意非有限或小数输入。

`tests/test_auto_target_bridge.py`现在把真实AutoTarget.lua输出贯穿到旧/可读两种合成像素条，再进入DecisionPipeline、Scheduler和ActionDispatcher；仅发送后端记录按键，不操作游戏。此前桥接测试只执行Lua并解析整数包，调度测试则手工构造字段，本次补齐两者之间的链路。

两种协议分别核对：有有效目标时选择寒冰箭；战斗中目标死亡后Lua状态为1，客户端发送Lua绑定的选怪键，且该动作可绕过先前技能的本地GCD；150毫秒后仍处于400毫秒抑制窗口，不重复发送；模拟安全按钮点击回执及新目标后，回执变为1、清除等待状态并恢复技能候选；键盘焦点占用、Lua总开关关闭和脱战后不再产生选怪发送。总开关分支保留合成像素master_switch为ON，单独验证Lua选怪闸门生效；完整像素总开关OFF的监控链路由test_dev_monitor_protocol.py覆盖。

4项桥接测试通过，0.516秒，记录`.local/auto-target-pixel-bridge.log`。这次没有修改业务代码或插件，也未构建新包。测试初次失败来自测试表达式缺少flag布尔参数及将GCD活动期间的状态文案错误期待为suppressed，修正测试后通过；不能记录成已修复产品缺陷。

限制：游戏API、像素绘制和按键接收仍为替身/合成输入；新目标和按钮回执是测试主动模拟，不能证明游戏已自动选中下一只怪。实际插件PixelBar渲染、真实窗口抓屏、Win32投递到WoW以及游戏宏执行仍需连接验证。

## 已部署插件记录

后续更新：现已从公开GitHub v0.2.5包安装78个文件并逐项校验。固定目录身份保持WowBuddyDev，旧插件完整备份，70个WTF文件未变，详见ADDON-IDENTITY-AUDIT.md及本地dist/game-addon-025-install.json。游戏尚未启动验证。下方0.2.0-dev段落保留此前部署历史。

已将0.2.0-dev插件安装到 `D:/Program Files (x86)/World of Warcraft/_forever_/Interface/AddOns/WowBuddyDev`。安装前未检测到Wow/WowB/WowClassic进程。安装后78个文件逐项摘要与本仓库源码一致；原v9te4am6目录78个文件的安装前后摘要一致。完整报告：dist/game-addon-install.json。真实客户端加载、Lua报错、受保护操作和实际施法尚未验证。

已请求用户在游戏插件列表禁用旧插件、启用WowBuddyDev、进入角色并停止旧助手。尚未收到准备完成的回复；不能把文件安装完成当作游戏加载通过。测试必须使用配套新桌面EXE。

新增Qt监控集成测试test_dev_monitor_protocol.py覆盖旧/可读布局各自的DXGI选择和PrintWindow回退，共4条组合路径。使用真实WindowCapture、监控轮询、控制器和调度模块，仅系统窗口/抓屏/按键后端替换。仅第24项就绪时投递SHIFT-F2；无技能就绪、总开关关闭、最小化、停止监控后不投递。投递是内存记录，不是实际游戏按键。

## 历史检查与测试步骤

# 独立版游戏验证记录

## 当前环境

本次只读检查发现客户端位于 `D:/Program Files (x86)/World of Warcraft/_forever_`，不是历史记录中的 `_classic_beta_`。AddOns下只有旧目录v9te4am6，未安装WowBuddyDev；没有运行中的WoW游戏进程。原始检查时间、客户端版本和目录列表见dist/game-environment.json。这些是检查当时的状态，开始下一次测试前需要重新核对。

本次没有修改游戏目录或启动客户端。旧插件上的历史施法结果不能当作此独立插件的验证证据。

## 后续实测顺序

1. 将当前dist/WowBuddyDev-dev.zip中的WowBuddyDev目录部署到此客户端Interface/AddOns，保留旧目录供回退。
2. 在角色插件列表禁用旧插件，仅启用WowBuddyDev；进入角色后确认加载版本。
3. 先验证总开关、色块识别和目标有效性，再选择本地循环方案。
4. 分别验证指定技能实际读条/命中、目标死亡但仍在战斗时换目标、脱战后的行为。记录是否人工切换过目标。
5. 若出现受保护操作弹窗，记录WowBuddyDevDiagnostics中的事件及函数。截图提示本身不能证明具体调用根因。
6. 将测试条件、程序与插件摘要、是否人工干预、观察结果写入本文件；未执行项保持未验证。

## 未验证项目

- 新插件受保护操作弹窗是否仍出现。
- 当前冻结EXE的实际截图及游戏接收按键。
- 自动施法与战斗中连续换怪。
- 天赋导入、宏编辑及重载后的设置恢复。
- 德鲁伊/战士技能可用性位图边界在真实游戏中的触发情况。

协议切换存在7个职业可复现的原模式合成帧边界。用户已选择修复切换并保留原行为对照，独立默认模式已按协议重新建立字段表；无需再次询问该选择。原模式表外读取不当作普通缺字段补零，详见PROTOCOL-DISPLAY-SWITCH.md。游戏实测尚未完成。
