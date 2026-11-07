# 当前源码本地构建验收

## 7b0eaa1 构建与当前回归限制

后续已将匹配修复的随机插件包安装到实际_forever_客户端，游戏当时未运行；85文件及旧版备份、72个WTF文件不变核对通过。原生游戏施法尚未验收，详见INSTALLED-SPELL-COMPAT-VALIDATION.md。下文“未安装”是构建时历史状态。

后续实际冻结插件安装验证扩展至十场景通过，包含目录版随机命名包更新、单文件安装失败结果、真实文件锁触发提交失败后的旧目录恢复及解锁重试；未重新构建产品。见FROZEN-ADDON-INSTALL.md。

已重新构建目录版及单文件，包含 ForeverCompat 技能名称查询修复、PanelV2 圣印事件与重建索引修复、DirectCastProbe 和 HookOrderProbe。内嵌插件 85 个文件与源码及目录版 `_internal/addon/WowBuddyDev` 逐字节一致，报告为 `dist/addon-embedded-7b0eaa1.json`。本节之后的“最新”均为历史记录，以本节为准。

- 目录版 SHA256：`c3b9b17c0c16ffd7973fe4489cf3a46ed24686009d59b2572d864c535aa68c28`。
- 单文件 SHA256：`62a2186c82f8486b1c77705c1532f94bb67cfa4b79e36a0d017e84f419dff072`，266 个外层成员。
- 界面初始化、系统后端初始化及冻结程序六种规则输入自检通过；六个测试 Job 最终进程数均为零。
- 单文件三种解包/缓存场景及两次正常 GUI 启动退出、设置保留检查通过，各测试 Job 最终进程数均为零。只关闭测试 Job 所属窗口，没有开启监控。单文件及上述报告归档到 `dist/local-7b0eaa1/`，可执行文件为 `dist/local-7b0eaa1/WowBuddyDev-Outer.exe`。
- 完整顶层回归 356 项中 355 项通过、1 项失败，耗时 197.959 秒，日志 `.local/regression-7b0eaa1.log`。不能表述为全量回归通过。
- 失败项为自建 Qt 窗口 PrintWindow 抓屏。单独复现取得全黑或上一帧；仅同步 repaint 仍可失败。检查工具改为最多等待 4 秒取得完整匹配帧，与已有 DXGI 检查保持一致，记录尝试次数；未修改产品抓屏代码。之后检查进行到 1484/readable 时触发环境限制：色条高 1082，当前屏幕可用高 1032、缩放 1.0。报告 `dist/win32-printwindow-check.json` 仍为失败；未跳过、缩放色条或更改显示设置来宣称通过，其他尚未执行的抓屏场景也不计通过。

用户已取消游戏内 `/dump type(GetSpellInfo)` 查询，没有查询结果。此轮没有安装新插件、公开发布或执行游戏施法；实际游戏内仍为 f1b6d86 插件，公开下载仍为原 v0.2.8 附件。技能查询修复的实际施法效果和自动接续打怪仍未验收。

## 历史插件增量记录

此前插件包为dist/spell-name-compat/WowBuddyDev-addon.zip，含技能名称查询兼容和圣印回显修复；85文件，当时尚未安装/公开发布/重建EXE，见SPELL-NAME-COMPAT-VALIDATION.md。以下“最新插件增量”为前次历史记录。

最新插件增量：修复PanelV2圣印回显事件参数及面板重建索引，随机包位于dist/seal-echo-fix/WowBuddyDev-addon.zip，85文件；详见PANEL-PRESENCE-VALIDATION.md。尚未安装或公开发布，本地04cd6be EXE不包含此修复。下述hook-order-probe仍是已安装版本。

随后新增手动HookOrderProbe诊断按钮，最新本地插件包为dist/hook-order-probe/WowBuddyDev-addon.zip；04cd6be EXE也不含此诊断工具。插件包现已安装到本机_forever_测试客户端并验证备份/保存文件不变，未公开发布；见INSTALLED-HOOK-PROBE-VALIDATION.md。

构建后新增差异：DirectCastProbe.lua恢复EnvCloakCast入口，最新随机插件包位于dist/directcast-probe；下述04cd6be EXE尚不含此文件，未再次重建。仅插件源码与包有此增量，未安装或公开发布。

## 历史本地构建：04cd6be，未公开发布

已将DirectCast的Slots、Guards、Actions、Keeper、Movement五个子模块及Core职业宏查询修复打入目录版和单文件。版本字段仍为0.2.8，公开0.2.8附件未覆盖。前轮46项相关源码测试通过，本轮没有改动产品源码，执行实际打包程序验证。

- 单文件：`dist/local-04cd6be/WowBuddyDev-Outer.exe`，SHA256 `91d3fe6976c4a607dbe8854106c49c5a2efe7b5b8d16c88b6cc829434eff9ef6`。
- 目录版：`dist/desktop/WowBuddyDev/WowBuddyDev.exe`，SHA256 `46a70ebd5f544b56ea7b308cd3060cc5aaf17a42f935f233a1b842aca9156bcc`，须保留相邻依赖。
- 内嵌固定目录插件包SHA256 `6c429fc8735347c7d9e947ffc4272e8b6a5d501b6b3c556e3fa39b528a8ae0f2`。83个文件与源码及目录版_internal/addon逐字节相同，64个Lua文件编译通过。
- GUI和系统后端初始化、6种规则输入、264个外层成员与身份资源、3种缓存场景、2次自有窗口启动/退出及设置保留检查通过。每个测试Job最终进程数均为0。

报告及构建清单已归档到`dist/local-04cd6be/`，另有`dist/addon-embedded-04cd6be.json`；日志位于`.local/build-04cd6be-{desktop,outer}.log`和`.local/check-04cd6be-{selftest,outer,gui}.log`。原directcast-actions/integration/movement/keeper本地包保留供对照，当前随机插件包仍为keeper版本。未安装游戏插件、未公开发布、未执行真实游戏施法；按钮自动挂钩等缺项继续见COMPLETENESS.md。

## 历史本地构建：9fa2008，未公开发布

已将父进程退出后再次核对清单摘要的修复打入目录版和单文件；公开0.2.8未覆盖，版本字段仍为0.2.8。产品源码摘要与两份构建清单一致。此前48项相关源码回归通过，本轮执行实际打包程序检查，没有重跑全部源码回归。

- 单文件`dist/local-9fa2008/WowBuddyDev-Outer.exe`，SHA256 `8808d010d9f1c37ac2c2c6b4d159cb6badeb64f147fb735612a9afcfc688e6a6`。
- 目录版`dist/desktop/WowBuddyDev/WowBuddyDev.exe`，SHA256 `19b11229866d087490d34281a770a2fef922f5429e3e5a3762c789a2a1aefa5f`，须保留相邻依赖。
- 构建GUI/系统后端初始化、6种规则输入、259个外层成员及身份资源、首次解包/缓存复用/缺失ready三场景、两次诊断窗口启动和设置保留全部通过。测试进程最终全部退出。
- 新版冻结交接程序在ready后、父进程退出前接收清单变化，明确拒绝替换；旧EXE保持，未生成备份或重启。此场景实际执行新修复，见MANUAL-UPDATE-VALIDATION.md。

报告`dist/frozen-selftest-9fa2008.json`、`dist/frozen-outer-9fa2008.json`、`dist/outer-gui-9fa2008.json`及`dist/frozen-directory-handoff-manifest-changed-current.json`；日志`.local/build-9fa2008-{desktop,outer}.log`、`.local/check-9fa2008-{selftest,outer,gui,manifest}.log`。未覆盖公开附件、未安装游戏插件、未验证真实施法或冻结按钮下载全流程。

## 历史本地构建与回归：c29fe27，未公开发布

目录创建前缀的UTF16计数修复已打入本地目录版和单文件，见OUTER-MKDIR-NATIVE-PARITY.md。源码基线为c29fe27，版本字段仍为0.2.8；公开附件未覆盖。

- 单文件：`dist/local-c29fe27/WowBuddyDev-Outer.exe`，SHA256 `69820bf5423781a0d7dd1349136c0bdae8adb441e5baf24ce1c4bb35346817a1`。
- 目录版：`dist/desktop/WowBuddyDev/WowBuddyDev.exe`，SHA256 `9cd9d0f80678036d28a935d399a680e726d7a755c7c231194d595b260bce3848`，运行需要相邻依赖。
- 源码回归286项顶层（180.803秒）及153项核心（1.450秒）通过，共439项，无跳过；本轮只构建和验证，未修改产品源码。
- 构建前后及验证后源码摘要一致，内嵌259成员、身份资源和负载检查通过。冻结GUI及系统后端初始化自检通过；六种规则输入、12项启动环境字段、三种解包缓存场景通过。
- 两次诊断参数窗口启动、设置保留、旧缓存清理通过，仅关闭测试Job窗口PID23388、41180；各次3个测试进程最终全部退出。使用`--dump-ui --no-watch --no-update --no-stealth`和禁止游戏目录扫描，不是普通启动或游戏测试。

报告：`dist/frozen-selftest-c29fe27.json`、`dist/frozen-outer-c29fe27.json`、`dist/outer-gui-c29fe27.json`；日志：`.local/build-c29fe27-{desktop,outer}.log`和`.local/check-c29fe27-{selftest,outer,gui}.log`。未覆盖公开附件、未安装到游戏目录；在线替换重启、真实抓屏施法和自动换怪仍未验证。原机器码对照的特殊路径场景属于源码测试，不能声称已在冻结程序中再次执行故障注入。

## 历史本地构建与回归：6bb86ed，未公开发布

后续目录版实际升级证据：使用6bb86ed隔离旧目录及c29fe27本地包，冻结交接程序完成父进程退出等待、目录交换、备份保留和新EXE自检；258个安装成员摘要及新报告来源、INI和数据保留通过，三个Job进程全部退出。见MANUAL-UPDATE-VALIDATION.md和`dist/frozen-directory-handoff.json`。不含冻结GUI手动按钮、GitHub下载、版本比较或失败回滚，未更新公开附件。

已包含更新取消记录无法落盘后的界面恢复修复。版本字段仍为0.2.8，公开附件未变。保存的单文件为`dist/local-6bb86ed/WowBuddyDev-Outer.exe`，SHA256 `e59ec68588439764b820d13831e12e4246bbca7e13cb8ebacfaac54d62c15aca`；目录版`dist/desktop/WowBuddyDev/WowBuddyDev.exe`摘要为`12b0ad2619cc29af53db4c3785f2c5e59c8b6299021ef574ea208812197f6fd6`。构建前后及验证后产品源码摘要一致，外层259成员和身份资源校验通过。

完整源码回归261项通过（163.888秒），核心153项通过（1.462秒），共414项，无跳过。日志`.local/regression-6bb86ed.log`及`.local/regression-core-6bb86ed.log`。冻结GUI/系统后端构造自检、六种规则输入、首次解包/缓存复用/缺失ready三场景均通过。两次诊断参数下的GUI启动、设置保留与旧缓存清理通过，仅关闭自有Job窗口PID40812、65800，各次3个进程全部退出。

报告保存在`dist/frozen-selftest-6bb86ed.json`、`dist/frozen-outer-6bb86ed.json`、`dist/outer-gui-6bb86ed.json`；构建日志`.local/build-6bb86ed-{desktop,outer}.log`，检查日志`.local/check-6bb86ed-{selftest,outer,gui}.log`。未安装到游戏目录、未覆盖公开附件。新增取消失败分支的故障注入仍是源码Qt测试，不是冻结故障注入；未验证此构建在线替换重启及真实游戏施法。

## 历史源码完整回归：0a99c06

顶层259项测试通过，157.256秒；核心153项通过，1.468秒，合计412项。日志 `.local/regression-0a99c06.log`、`.local/regression-core-0a99c06.log`。使用原包/机器码的子场景不另算顶层测试数。没有为本轮绕过或跳过新增测试。

同时重新比较目录版和单文件构建清单中每个产品源文件摘要，当前产品源码与64ec113构建一致；后续修改为测试和文档。保存的单文件副本SHA256仍为 `46131bbd861aff6e42162cb014e667a0f218cc9f04312647257318376a42c134`。本轮没有重新构建或覆盖发布附件，也未进行游戏施法验收。

## 历史本地构建：源码64ec113，未公开发布

已包含ea60f7f排序临时缓冲区回退、57dca3a交接准备重试、8ff0fe3交接超时及错误报告恢复。版本字段仍为0.2.8；本地后续构建未覆盖公开Release附件。单文件另存于 `dist/local-64ec113/WowBuddyDev-Outer.exe`，SHA256 `46131bbd861aff6e42162cb014e667a0f218cc9f04312647257318376a42c134`；目录业务EXE位于 `dist/desktop/WowBuddyDev/WowBuddyDev.exe`，SHA256 `41d1ca0560406d191e2289c47aa7f0c9120c774ef35934c69a04cd4d66aafd1f`。

构建前后源码摘要一致，完成后再次逐项核对源文件与保存副本摘要一致。冻结界面/系统后端自检通过，六种规则输入自检通过，单文件259个成员及身份资源校验通过。三种缓存场景均通过；两次GUI启动退出的设置保留、旧缓存清理通过，只关闭所属测试Job窗口（PID10732、33572），每次三个进程最终归零。

报告为 `dist/frozen-selftest-64ec113.json`、`dist/frozen-outer-64ec113.json`、`dist/outer-gui-64ec113.json`，日志为 `.local/build-64ec113-{desktop,outer}.log` 与 `.local/check-64ec113-{selftest,outer,gui}.log`。未安装到游戏目录，未重复公开下载/升级交接，未完成游戏施法验收。冻结常规运行通过不等于已在冻结EXE中注入分配失败或交接错误；这两个故障分支仍使用各自源码专项证据。

## 历史公开构建：0.2.8，源码03a6169

0.2.8已于提交11b9837公开发布，六个附件齐全。通过客户端实际下载模块回读公开目录包、随机插件包和单文件EXE：清单与本地一致，随机名称检查通过，目录版和单文件版下载后冻结自检通过，外层测试Job三个进程最终归零。报告 `dist/public-release-028-check.json`，日志 `.local/check-public-028.log`。本次未重新验证旧版本自动更新交接，未进行游戏实测。

最终顶层回归251项通过，用时138.192秒；核心回归153项通过，用时1.379秒，共404项。日志 `.local/regression-028-verbose.log` 与 `.local/regression-core-028.log`。顶层首次运行被人工结束后使用详细日志重跑；90秒定时堆栈是诊断输出，不代表测试超时失败。核心首次调用遗漏 PYTHONPATH，修正运行环境后通过。

成套产物摘要见 RELEASE-0.2.8.md。冻结六组输入、三组缓存、两次隔离 GUI 启动及设置保留通过。报告保留为 `dist/frozen-selftest-028.json`、`dist/frozen-outer-028.json`、`dist/outer-gui-028.json`。`tools/check_release_consistency.py` 对实际发布包核验：版本一致、成员摘要一致、59个 Lua 与源码一致且可编译、TOC/XML 引用完整、单文件身份与业务 EXE 摘要一致。未安装到游戏目录，未执行真实游戏施法。

## 历史本地构建：源码2de8343

目录业务EXE：`dist/desktop/WowBuddyDev/WowBuddyDev.exe`，SHA256 `1e2e13aa4e0644493940dfe490c045a945487798a8cd7bca142881c27fb5dd3b`。单文件EXE：`dist/outer/WowBuddyDev-Outer.exe`，SHA256 `5652df44a0fd7395960c1738059f83d70a7f0ae93c4e0cd43b5451db705eb43a`。本次已纳入受限容量排序；默认调用路径不变。版本字段仍为0.2.7，是本地后续构建，未覆盖公开附件。

构建期间源码摘要不变，冻结界面及系统后端自检通过；单文件259个成员和身份资源校验通过。六种规则输入的冻结自检通过，每次一个测试进程最终归零；原构建规则文件未改变。首次解包、复用缓存、缺失ready恢复通过，每次三个进程最终归零。两次GUI启动后只向测试Job所属主窗口发送WM_CLOSE，设置保留及旧缓存清理通过；关闭PID为70620、56736，每次三个进程最终归零。

报告：`dist/frozen-selftest-2de8343.json`、`dist/frozen-outer-2de8343.json`、`dist/outer-gui-2de8343.json`。日志：`.local/build-2de8343-{desktop,outer}.log`、`.local/check-2de8343-{selftest,outer,gui}.log`。隔离目录：`.local/frozen-selftest-yrccabuf`、`.local/frozen-outer-中文 & qd_btvsd`、`.local/outer-gui-2kwzgwze`。

该构建未做新的公开升级链、冻结排序逐项差分或游戏实测。GUI验证仍使用禁用监控/更新/游戏扫描的测试配置，不能等同于完整游戏运行。

## 历史源码回归：94493f4（当轮未重新构建）

`tests` 顶层237项测试全部通过，用时136.969秒，退出码0，无跳过；`tests/core` 另行执行153项全部通过，用时1.463秒，无跳过。两套共390项，日志分别为 `.local/regression-94493f4.log`、`.local/regression-core-94493f4.log`。原机器码的多组子场景计入各自测试方法，不额外累加为顶层测试数。

本轮覆盖当前源码的Qt界面与托盘、协议与治疗流程、更新交接、隔离插件安装、真实自身窗口PrintWindow及原机器码对照等现有套件。未启动真实游戏或验证游戏施法。测试使用临时安装目录，不代表用户游戏目录插件已更新。

本轮没有重新构建EXE。重新读取现有目录版与外层SHA256，仍与下节43a7350产物一致；94493f4受限容量排序尚未打入这些文件。当前源码回归结果不能代替最新源码冻结构建与发布验收。

## 历史本地构建：源码43a7350

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
