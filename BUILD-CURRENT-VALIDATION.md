# 当前源码本地构建验收

## 最新本地构建：源码43a7350

已纳入治疗候选NaN处理及小组/大组排序修复。完整独立测试集231项通过，用时139.141秒，进程退出码0；日志.local/regression-healing-current.log。该数量不包括另行运行的tests/core套件，不能混称所有测试目录已递归覆盖。

目录业务EXE位于dist/desktop/WowBuddyDev/WowBuddyDev.exe，SHA256为`1add58374521beb00d457b7c72204c3f5b090ab619fc88d01c0fc83221ecc232`。单文件位于dist/outer/WowBuddyDev-Outer.exe，SHA256为`f2f66682686290b4f5cb74608b6b67962faff485ac6a17c18763194586895b03`。构建前后源码摘要一致，冻结窗口及系统后端自检通过。

六种规则输入的冻结自检通过，每次1进程最终0。单文件首次解包、缓存复用、缺失ready恢复通过，每次3进程最终0。两次正常GUI启动后只关闭测试Job内窗口，设置保留及旧缓存清理通过，每次3进程最终0；关闭PID分别18928、26980。

隔离目录为.local/frozen-selftest-nnhh197e、.local/frozen-outer-中文 & 08hl8zzu、.local/outer-gui-orioab4w。报告为dist/healing-frozen-selftest.json、dist/healing-frozen-outer.json、dist/healing-outer-gui.json；日志为.local/build-healing-{desktop,outer}.log及.local/check-healing-{selftest,outer,gui}.log。

版本字段仍为0.2.7，这是本地构建，与公开0.2.7附件不同；没有覆盖公开附件。未执行本地包在线升级、逐项冻结排序对照或真实游戏验收。

## 最新公开构建：0.2.7（44b9004）

源码及六个发布附件已公开：https://github.com/yitugege/wow-assistant-dev/releases/tag/v0.2.7 。业务EXE SHA256为`3922a921ea13fd53de8ace505fad577e46cc2ea6525d5bd38af0fe0369e4afca`，单文件EXE为`e9c50f46cf3473510cd593d2fae91398fff4329d14cb36c9c6f05d625f15d008`。构建前后源码摘要一致。

134项核心测试通过。目录包独立解压自检通过；插件78个文件、59个随机命名Lua编译及TOC/XML引用检查通过。单文件首次解包、缓存复用、缺失ready恢复均通过，每次三个测试进程最终全部退出。

发布后通过客户端实际下载模块从公开GitHub下载目录包、插件和单文件，核对清单及SHA256；目录版和隔离单文件启动自检通过。随机插件目录为`w64cfe25c40c6`。证据为`dist/release-027-local-check.json`、`dist/frozen-outer-check.json`和`dist/public-release-027-check.json`；日志为`.local/validate-027.log`、`.local/check-027-outer.log`和`.local/check-public-027.log`。

补充验证：0.2.6到0.2.7的真实公开下载、替换及重启交接已通过CLI和GUI自动更新两条路径。两次各观察到6个隔离测试进程，最终全部退出；GUI旧进程28640、新进程53188，设置保留。证据为dist/upgrade-026-027-cli.json及dist/upgrade-026-027-gui.json。未验证手动点击更新按钮。

插件实际公开包升级也在隔离目录通过：新包目录w64cfe25c40c6安装时保留旧身份w0047ac9cbe3b，78个新文件与78个备份文件逐字节核对通过，SavedVariables测试文件保持不变。见dist/addon-upgrade-026-027.json；不代表已在游戏中加载。未安装至用户游戏目录或完成真实游戏验收。历史GUI/数值边界测试仍按各自源码基线记录，不能混称为本版全部重新执行。

## 历史构建：源码f33b078

已纳入回执解析967c037、Qt初始化12f2fee、治疗自检6a8cdf2和打断判断f33b078。目录版SHA256为`3ccecfff4ebac232b72a375e170af499b84e4b66fc1af8b785dc44f3b3ccf2eb`，单文件为`16779aa07a81be3bee930271969efe722a26b421726746bc991e5d50d6b17561`，位置仍为下表对应路径。版本字段0.2.6，未覆盖公开发布。

构建前后源码摘要一致；冻结窗口及系统后端自检通过。六种规则输入的冻结自检通过，每次1进程最终0，12个启动环境字段和原资源未变检查通过；隔离目录.local/frozen-selftest-8kd_ffo6。

外层259成员校验、首次解包/缓存复用/缺失ready恢复通过，每次3进程最终0；隔离目录.local/frozen-outer-中文 & irrw64p1，缓存键951dde2f74740a6e。禁用游戏扫描并使用诊断参数启动两次GUI，向各自Job内窗口发送WM_CLOSE，设置保留和旧缓存清理通过，每次3进程最终0；目录.local/outer-gui-pq4uaxea。

报告为dist/frozen-native-selftest-current.json、dist/frozen-outer-check.json、dist/outer-gui-check.json。日志为.local/build-current-parity-{desktop,outer}.log及.local/check-current-parity-{selftest,outer,gui}.log。未验证真实游戏、在线升级或冻结程序逐项数值边界；对应源码原Qt对照不混称为冻结执行。

## 历史构建：源码32bb8a9

已将可用技能统计和候选引擎的int64解析修复打入目录客户端及单文件外层。版本字段仍为0.2.6，本次是本地测试构建，未覆盖公开附件。

|产物|SHA256|
|---|---|
|dist/desktop/WowBuddyDev/WowBuddyDev.exe|21aecb2152be5eb3265d73775e32ca1569f0d081779e6278eab7b8b13d5f5b8f|
|dist/outer/WowBuddyDev-Outer.exe|6276a424c1523d87ec84ffd35b295cf7dfc2b002651888b17d14688e54aea56f|

构建前后源码摘要一致，目录版冻结GUI和系统后端构造自检通过。隔离副本六种规则输入自检通过，各自1进程、最终活动数0，12个启动环境字段及正常退出核对通过；原构建规则未改。报告dist/frozen-native-selftest-current.json，隔离目录.local/frozen-selftest-xxcrs__f。

外层259个成员校验通过；首次解包、缓存复用、缺失ready标记三个场景均通过，每次3进程最终全部退出。报告dist/frozen-outer-check.json，隔离目录.local/frozen-outer-中文 & mijy72eg，缓存键dacbcb0f108fcd9d。日志为.local/build-int64-desktop.log、.local/build-int64-outer.log、.local/check-int64-frozen.log和.local/check-int64-outer.log。

本轮没有重复窗口人工交互或在线升级验证。解析边界的原Qt对照仍为源码测试，冻结自检不等于冻结程序逐项重跑该边界集；构建清单证明修复源码已纳入。全部游戏行为和完整还原仍未验收。

## 历史构建：源码a5c3f93

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
