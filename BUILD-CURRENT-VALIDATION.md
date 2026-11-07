# 当前源码本地构建验收

## 最新构建：源码a5c3f93

已重新构建目录客户端及单文件外层，纳入插件更新回调生命周期、Win32启动环境字段和自检非对象specs修复。版本字段暂为0.2.6，这是后续源码的本地测试构建，摘要不同于公开v0.2.6；未覆盖GitHub附件。

|产物|SHA256|
|---|---|
|目录版业务EXE|c7d6abbae6a4b659f17ac01fe1ea0aa4e351c26c66a213c4d650a22537de88db|
|单文件外层|717e7230396c54c9f57c99d174f5cdae8e228257cf5b2b3777f5a844b4ca0546|

位置仍为下文dist/desktop与dist/outer。构建前后业务源码摘要一致；冻结GUI及真实系统后端构造自检通过。

新增工具`tools/check_frozen_native_selftest.py`将整个目录版复制到新隔离目录，只修改副本规则：正常、null、数字、字符串、数组、布尔值共六次执行实际冻结--selftest。正常规则报告OK，其余报告“规则内容为空”，均返回0；12个Win32环境字段按顺序出现在Qt构造完成之前，日志正常结束。每次一个自有Job进程、最终活动数0。原构建规则摘要保持不变。报告`dist/frozen-native-selftest-current.json`，隔离目录`.local/frozen-selftest-2pr2r1w9`。

单文件首次解包、缓存复用、缺失ready标记三场景通过，每次3个自有Job进程全部退出；报告`dist/frozen-outer-check.json`，隔离目录`.local/frozen-outer-中文 & akv4dt2h`。本次没有验证冻结程序中的插件回调重入，相关证据仍为源码真实Qt测试；不能用打包成功替代这项运行覆盖。

本轮不代表全部原功能、真实游戏或新构建在线升级链验收。下文为先前构建记录，旧摘要与测试次数不适用于本次产物。

补充窗口验收：使用--dump-ui、--no-watch、--no-update、--no-stealth两次启动单文件，禁用游戏目录扫描，仅向自有Job窗口发送WM_CLOSE。两次设置保留、旧缓存清理通过，每次3进程最终全部退出。报告`dist/outer-gui-check.json`，隔离目录`.local/outer-gui-udgj3h_s`。这是诊断参数下的窗口运行，不等于完整普通启动及在线更新测试。

## 历史构建：源码7f3ddc9

构建源码基线：`7f3ddc9`。版本标签仍为0.2.5，这是后续修复的本地测试构建，不是GitHub现有v0.2.5附件，也没有覆盖公开附件。

包含固定插件目录身份保留、外层手动下载后直接安装重启、更新完成结果只消费一次及退出后取消排队安装等修复。

## 产物与校验

|产物|位置|SHA256|
|---|---|---|
|目录版业务EXE|`D:/wow-assistant-dev/dist/desktop/WowBuddyDev/WowBuddyDev.exe`|`6817c48c577bd851d2f0551a204322fdc61c1ec4d308bafbeaee7ad7469aa706`|
|单文件外层|`D:/wow-assistant-dev/dist/outer/WowBuddyDev-Outer.exe`|`941def013727ed117442ee2d12995c886254a68edaf6733ebe1be183d1a9aeb9`|

目录版需保留相邻依赖目录，不能只复制业务EXE。单文件外层内嵌259成员，自有身份资源和负载校验通过。构建前后源码摘要一致。

## 已完成验证

- 冻结目录版界面自检及真实系统后端构造自检通过；构造成功不是捕获或游戏施法成功。
- 134项核心回归通过，`.local/current-core.log`。
- 外层首次解包、缓存复用、缺失ready标记三场景通过，每次观察到3个自有Job进程、最终活动数0。缓存业务摘要和稳定日志位置符合预期。报告 `dist/frozen-outer-check.json`。
- 两次外层窗口启动通过，使用 `--dump-ui --no-watch --no-update --no-stealth`；检查窗口报告后仅对自有Job主窗发送关闭消息。设置保留、旧缓存清理通过，每次3个进程最终全部退出。报告 `dist/outer-gui-check.json`。
- 窗口测试设置 `WOWBUDDY_NO_GAME_SCAN=1`，避免发现和更新用户游戏目录；用户原有助手未关闭。dump-ui路径不等于不带诊断参数的完整正常启动或在线更新验收。

## 尚未完成

本次构建尚未验证冻结EXE手动下载后的实际替换重启链、全部失败分支、游戏抓屏与按键接收、自动施法或连续换怪。此前旧构建的公开升级结果不能直接替代本次产物验收。公开版本仍为原v0.2.5，后续发布需新版本号及对应下载清单。
