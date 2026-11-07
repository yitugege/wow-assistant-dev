# WOW助手独立开发工程

用户要求在自有桌面代码和插件源码仓库继续开发，不再修改原EXE。交付位置改变不代表全部功能还原已完成。公开仓库为 https://github.com/yitugege/wow-assistant-dev ，源码与下载包共同维护。

## GitHub 下载与发布

在 Releases 下载配套客户端目录包，解压全部文件后运行 WowBuddyDev.exe。在插件页选择包含 Wow.exe 的目录，退出游戏并停止监控，点击“GitHub下载更新”。客户端从本仓库最新正式 Release 获取插件及清单，核对协议版本、ZIP 和成员 SHA256 后安装，更新前备份旧开发插件。

`python tools/build_github_release.py` 生成 `dist/release/WowBuddyDev-addon.zip` 和同名 `.manifest.json`。发布时同时上传这两个文件。插件根目录、TOC 和 Lua 文件名在构建时随机生成，TOC/XML 引用同步更新，源码保持可读。随机命名只改变文件路径，不会消除游戏受保护操作限制。

首次随机安装后，后续更新沿用本机目录名，保留启用状态及存档名称。从固定 WowBuddyDev 开发版迁移时需要重新启用新插件；旧 SavedVariables/WowBuddyDev.lua 保留但不会自动迁入随机目录对应的存档，请先备份设置。原助手插件不会被自动删除。

下面固定目录打包命令仍用于离线开发；公开分发采用上述随机命名包。游戏内加载、受保护操作和自动换怪仍需实测，不以构建通过代替。

## 当前内容

- `desktop/wowbuddy/`：迁入当前桌面重建源码，由独立run_dev.py入口使用，并提供自有EXE构建脚本。
- `addon/WowBuddyDev/`：独立插件源码，固定目录及TOC名称。
- `assets/`：协议、规则JSON及离线循环库快照，保持桌面端与插件协议对应。
- `migration-source-manifest.json`：迁入文件摘要。后续新增和编辑不代表原目录发生变化。

原目录 `D:/reverse-analysis/wow-assistant` 以及其中的EXE保持不动。

## 本次受保护操作弹窗

截图只证明客户端阻止了插件操作，尚未给出具体函数或调用栈。发现DirectCast模块依赖解锁环境，并在普通点击/定时器中调用施法和修改安全按钮属性；该模块还将CreateSecureButton返回的布尔值当作按钮对象。

独立开发插件不复制或加载DirectCast.lua。SecurityDiagnostics.lua监听ADDON_ACTION_BLOCKED和ADDON_ACTION_FORBIDDEN，仅记录本插件的事件、函数名、战斗状态和诊断栈，最多保留50条到WowBuddyDevDiagnostics。记录器的栈不保证等于最初污染源，需要结合事件函数名继续排查。

尚未在游戏中验证弹窗已消失，不宣称已修复所有受保护操作。独立入口已停用旧更新来源和原安装流程；自有插件更新使用本仓库 GitHub Releases。

## 独立插件打包

在项目根目录运行 `python tools/build_addon.py`，生成 `dist/WowBuddyDev-dev.zip` 及成员SHA256清单。仅使用此工程内的插件源码，不调用旧EXE或原安装器；此离线包内固定为WowBuddyDev目录；公开发布请使用 build_github_release.py 生成随机命名包。

构建检查TOC引用、目录边界、禁止文件和每个ZIP成员的摘要。诊断和打包测试使用 `python -m unittest discover -s tests -v`，其中诊断测试需要Lua 5.1执行器 `lupa`。静态Lua语法检查及隔离测试不能证明WoW安全执行环境中的调用已通过。

手动游戏测试：关闭游戏后，将ZIP内WowBuddyDev文件夹放入目标客户端的Interface/AddOns。进入游戏前禁用旧助手插件，只启用WowBuddyDev。若仍弹出受保护操作提示，正常退出游戏或重载UI后，在对应账号WTF目录的SavedVariables/WowBuddyDev.lua中查看WowBuddyDevDiagnostics。客户端提供安装按钮；游戏插件启停仍需在游戏内确认。

## 独立桌面源码入口

循环库已接回自有 GitHub 在线同步：正常启动请求一次，每30分钟刷新，可点“GitHub刷新”立即更新；“重载本地方案”保持离线读取。覆盖前自动备份旧快照。`--hub-selftest --hub-fetch` 可无主窗验证联网；详见 [HUB-ONLINE.md](HUB-ONLINE.md)。此说明替代下文早期“未配置远程循环库”的记录。

插件页“自动检测”会优先选运行中的客户端，并读取最近目录、配置根目录和常见安装位置；支持 `_classic_beta_`、`_cn_beta_`、`_forever_`。右键该按钮可选择或清空最近目录。手选允许游戏根目录、客户端、Interface、AddOns，安装前仍需退出游戏。原检测实现保留作对照，新增路径支持位于 `dev_game_paths.py`。

无界面安装使用 `python run_dev.py --install-addon --install-addon-dir="D:/游戏/_forever_/Interface/AddOns" --data-dir="D:/安装报告"`。直接目录语义、返回码及原版差异见 [CLI-INSTALL.md](CLI-INSTALL.md)。此命令新增于 v0.2.0 发布之后的源码。

使用具备PySide6的Windows Python运行 `python run_dev.py`。资源只读本工程assets，设置和日志默认写入本工程.local目录；也可用 `--data-dir` 指定独立数据目录。默认不自动开始监控。

显式传入 `--auto` 可在界面初始化后尝试一次开始监控，例如 `WowBuddyDev.exe --auto`。使用已迁入的原单次回调：未找到游戏时记录提示，有匹配下拉框项则选择它，已经监控时不重复切换。持续监视使用 `--watch`：初始化时立即检查，之后每5秒检查；游戏窗口关闭时停止监控，后续检查可自动重连。此模式下手动停止后，下次检查仍可能重新开始；需要保持停止时应退出助手，再不带--watch启动。自检参数不能与--auto或--watch同时使用，参数不接受缩写。

依赖安装：`python -m pip install -r requirements.txt`；运行Lua诊断测试时使用 `requirements-dev.txt`。版本来自本机已验证环境，不代表其他Python版本和系统均已测试。

当前入口不创建程序更新、插件更新或循环库网络客户端，不调用旧插件随机安装/清理入口；离线安装按钮使用本工程的本地插件包，“GitHub下载更新”按钮下载本仓库最新配套发布包。首次启动将内置离线循环库复制到数据目录的hub/rotations.json，已有文件不覆盖。当前快照可解析为41套方案，来自此前本地测试目录，保留原方案内容和作者信息；数量不代表各方案均经过游戏验证。自有远程循环库来源尚未配置。

`python run_dev.py --selftest` 使用禁止抓屏和发键的后端进行离屏GUI构造/关闭检查，输出dist/desktop-selftest.json。请以此入口启动开发工程，不直接运行迁入的legacy desktop模块，以免混入旧默认配置。

修改本地数据目录中的hub/rotations.json后，可点击“重载本地方案”，无需重新打包。源码默认目录为项目.local；EXE默认目录为程序旁.local，按钮悬停显示完整文件位置。重载只读取该本地文件，不联网；读取或JSON校验失败会记录日志并保留当前内存方案。磁盘上的错误文件不会被自动修复，重启前仍应自行改正。有效的空方案快照允许清空循环库。

## 构建自己的EXE

客户端更新检查已连接本仓库 GitHub Release；也可运行 `python run_dev.py --check-update --data-dir="D:/更新检查"`。有新版本时可下载校验并暂存，自动替换重启仍未接通，详见 [CLIENT-UPDATE.md](CLIENT-UPDATE.md)。

安装requirements-dev.txt后运行 `python tools/build_desktop.py`。构建产物为 `dist/desktop/WowBuddyDev/WowBuddyDev.exe`，是目录版：需要保留旁边的_internal和packages目录，不能只复制EXE。

该构建直接打包run_dev.py与desktop/wowbuddy源码，附带本工程assets和插件源码，不引用原EXE。插件ZIP放在packages目录，设置默认保存在EXE旁的.local目录。构建结束自动运行冻结入口的--selftest，记录build-manifest.json和desktop-selftest.json。

自测使用无系统操作的后端，不抓屏、不发键、不进入游戏；通过只代表冻结GUI能正常加载资源并关闭，不代表插件弹窗或游戏循环已经验证。

另外提供 `python run_dev.py --selftest-backends`：实际创建Win32窗口、DXGI/PrintWindow截图及按键后端对象，构造GUI后关闭，结果写入backend-selftest.json。构建脚本会对冻结EXE同时执行这项检查。它能发现系统DLL加载或后端初始化问题，但不会开始监控、调用截图或发送按键，不能证明GPU帧获取及游戏输入成功。

## 兼容边界

主全局表已改为WowBuddyDev，持久设置改为WowBuddyDevDB，安全按钮前缀改为WBD_BTN_；不会自动迁入旧插件设置。namespace-migration.json记录改名范围，原出处行注释保留。旧协议像素标识继续保留以兼容当前桌面读取端。

随后修正了12个遗留UI名称或前缀，包括主窗口、调试窗口、小地图按钮、宏滚动框、绑定测试框和OverrideOwner。frame-namespace-migration.json记录对应关系；这些控件现在使用WowBuddyDev名称，避免与旧插件同名。此改名不改变安全操作限制，不能据此保证与旧插件共存或确认弹窗根因。

其他共享快捷命令和按键冲突尚未全部排查，不能据此保证与旧插件同时启用安全。游戏测试前仍应关闭旧版本，已安装本插件到_forever_客户端，尚未验证游戏加载。

用户已授权本仓库公开源码与发布附件。

## 自动选怪核对结果

`tests/test_auto_target_bridge.py` 在Lua 5.1中加载真实ActionKeyCheck.lua和AutoTarget.lua，再用桌面parse_auto_target解码输出。已验证81个按键索引对应一致；远程角色先有可攻击目标进入战斗、目标死亡且仍在战斗时，输出状态1；脱战并重置会话后输出状态0。聊天输入焦点、关闭自动寻怪或关闭总开关都会阻止选怪请求。

当前宏为 `/targetenemy [combat,nochanneling,noexists][combat,nochanneling,dead]`，因此脱战后主动寻找下一只并拉怪尚未实现。此结果来自源码执行的模拟环境，不能证明此前游戏测试一定因脱战而停止，也不能证明游戏收到按键或成功切换目标。回执递增仅说明按钮点击回调被调用，不代表目标切换成功。

独立工程与插件的22项本地测试通过。受保护操作弹窗、实战连续换怪以及每套循环方案仍需游戏内证据。

## 天赋导入的数据边界

独立版已移除导入前按名称批量删除天赋配置的逻辑；原逻辑会在校验字符串前删除名字包含MKL等字样的配置，可能波及旧插件或用户数据。新导入名称使用WowBuddyDev_前缀，仍保留字符串、版本、专精及树哈希校验和战斗锁定检查；最终应用仍由玩家在天赋页操作。

这是自有插件的数据隔离修正，与旧实现的清理行为有意不同，不算对该行为的一比一复现。Lua模拟测试验证无效字符串不导入或删除、有效导入使用独立名称、战斗中不导入；尚未进行游戏天赋页实测。

## 核心行为回归

循环库完整性另见ROTATION-GAPS.md：已确认18套方案包含未注册的shoot_wand动作，其中一套还引用未注册的start_attack。对应分支不会生成候选；41套加载成功不等于动作全部可执行。用tools/audit_rotation_bindings.py可复现检查。

两份规则JSON与原程序已提取资源逐字节一致，缺失动作并非本次迁移遗漏。开发版在选中受影响方案时显示警告，并在悬停提示及日志列出动作名；切换或清除选择时更新警告。当前保留原动作执行行为，不将猜测的魔杖宏当作已还原功能。

补充检查：41套方案的显式字段引用均可在两份契约的合集中找到，详见tools/audit_rotation_fields.py与dist/rotation-field-audit.json；这不证明每个协议单独覆盖所有字段或游戏每帧都能读到数值。9个职业的插件actionAvailSpellIDs与桌面列表顺序一致，记录在rotation-binding-audit.json的availability_tables中；这不证明位图传输没有截断、技能实际可用或准备状态正确。

位图往返检查进一步发现3个失败场景（共200个合成场景）：德鲁伊1484的第24项置位超出RGB 24位容量，被夹到0xFFFFFF；德鲁伊全部可用同样溢出；战士1491全部23项可用恰好编码为0xFFFFFF。桌面count解码将此值视为未知，缺少单独ready字段时无法恢复技能可用性。脚本tools/audit_availability_pixels.py直接执行实际Lua位图和RGB函数，再接Python字段解码与availability判断，结果见dist/availability-pixel-audit.json。这是修复前结果；独立0.2协议现已修复编码，详见AVAILABILITY-PROTOCOL.md。

运行 `python tools/test_core.py` 检查迁入的桌面核心行为测试。当前134项通过、无跳过，涵盖表达式、规则候选、旧/可读像素协议、图像几何、调度和按键发送路由。按键测试使用模拟后端，不向游戏发键。

测试脚本校验所有已导入的wowbuddy模块均来自本仓库desktop目录，并写入 `dist/core-tests.json`。`tests/core/` 的测试来自先前重建工程，迁入时的原始摘要记录于core-tests-source-manifest.json；其中3个测试文件的资源位置已改为本仓库assets，断言保留。该套测试复用已有预期，不等于本轮重新运行原EXE进行差分，也不构成全部功能一比一完成的证明。

## 协议边界的原行为对比记录

修复前，同一专精从旧像素协议切到可读协议时，留存字段表可能短于新采样数量。readable_protocol.py仍显式抛出UnverifiedDescriptorTable，runtime.py记录并跳过该帧发送。这不是完整还原：此前原生证据涉及表外内存读取，不能用补零或截断冒充其确定行为。普通帧测试通过不能覆盖此边界。用户已选择独立版修复，当前默认路径见下一节；旧模式仅保留供离线对比。

`python tools/audit_protocol_transition.py` 用本仓库资源及合成帧重放全部9个职业：1482、1485、1486、1488、1489、1490、1491这7个编号在旧缓存模式旧条→可读条时触发短表异常；1484、1487在该固定序列成功。9个职业以全新控制器直接读取可读条均成功。这表明失败与留存表生命周期有关，不能据此将所有可读协议判为不可用。修复后的9项均成功且结果与新建控制器相同。详细数量见dist/protocol-transition-audit.json；这不是新的原EXE动态运行结果，也不能证明真实游戏的协议切换频率。

原Qt指令的隔离实验见tools/probe_qstring_tail.py。使用pefile 2024.8.26及Unicorn 2.1.4，对摘要匹配的原Qt6Core.dll执行QString复制构造函数：无分配块头和有效引用计数头可返回，历史故障中的0x5分配指针则在RVA 0x170e触发无效访问。结果写入dist/qstring-tail-probe.json。实验输入是人工构造的字符串头，不证明未初始化尾部应补零，也不模拟完整堆分配器或GUI。

本机复现命令：`python tools/probe_qstring_tail.py --dll D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll --runtime D:/reverse-analysis/native-emulation-runtime`。原DLL仅作为字节输入，未调用系统加载器加载该DLL；实验不修改原文件。

## 协议切换修复（用户已选择）

独立版字段缓存现在同时比较协议和专精，避免同专精旧条/可读条互相复用字段表。离线验证覆盖9专精反复双向切换，逐帧与新建控制器完整解码结果比较。`tools/audit_protocol_transition.py` 同时输出修复后和原缓存模式的对照；后者仍复现7项短表异常。原缓存选项仅在Python离线对比使用，桌面入口不启用。该修复不代表色块技能可用性溢出、缺失动作或游戏受保护操作已经解决。

## 托盘与退出

正常启动时，系统托盘可用就显示WowBuddyDev图标，菜单包含显示主界面、停止/开始监控、退出和切换置顶。最小化按钮收起到托盘，监控继续；单击或双击图标切换隐藏/显示。关闭按钮退出并释放监控资源，不是隐藏到托盘。菜单退出也先停止计时器并释放资源，再退出Qt。

没有系统托盘时最小化保留普通窗口最小化行为，避免窗口隐藏后无法找回。自检不创建托盘。离线测试用真实Qt窗口与托盘替身验证菜单及关闭行为，尚未完成真实Windows托盘鼠标交互和视觉验收。使用--watch时，菜单停止监控后持续监视会在下一次检查中重新连接；要持续停用，请退出后不带--watch重启。

## 本地安装和更新开发插件

先退出游戏并停止助手监控，点击插件区域的浏览按钮，选择包含Wow.exe的客户端目录（也接受其Interface/AddOns目录），再点“安装/更新开发插件”。路径保存在独立settings.ini中。源码入口从dist读取WowBuddyDev-dev.zip和同名.manifest.json；冻结EXE从旁边packages读取。源码有改动时先运行tools/build_addon.py重新打包。

安装前校验ZIP整体摘要、成员列表及各文件摘要，只允许固定WowBuddyDev目录。暂存文件验证成功后才替换目标；已有开发插件整体保存在客户端的WowBuddyDev-backups/UTC时间-唯一编号目录，不修改其他插件目录或WTF设置。替换失败时尝试立即恢复旧开发版；若文件占用等原因使恢复也失败，备份仍在该目录，安装会报告失败。重装以包内容为准，自定义文件保留在备份中，不自动合并。

已验证临时客户端的首次安装、更新备份、其他插件保留、损坏包拒绝、路径越界拒绝、替换失败回滚及GUI按钮流程。随后已对真实客户端执行安装并核对78个文件，加载效果仍未验证，见GAME-TEST.md。安装功能不自动禁用旧插件；进入游戏前应在插件列表禁用旧助手插件。

## 界面诊断命令

`WowBuddyDev.exe --dump-ui --spec=1482 --toggle-showall --data-dir D:/wowbuddy-diagnostics` 在离屏Qt环境构造独立窗口，按原诊断实现的2600毫秒外层延迟和600毫秒写报告延迟执行，随后退出。data-dir中生成_ui.txt、可选_showall.txt及dump-ui.json；使用无系统操作后端，不创建托盘、不开始监控、不联网。输出目录同时是该次运行的设置/本地方案目录，建议指定专用目录；诊断专精和阈值初始化可能写入其settings.ini。

可重复传入--spec，按顺序应用；--talent默认10/0/0；--rotations和--rotation分别指定本地方案JSON及“专精ID|子分类|方案名”，后者有竖线时需整段加引号。相关选项必须与--dump-ui使用，不能同时--auto、--watch或自检。JSON/方案匹配失败沿用原诊断警告语义，查看dump-ui.json的warnings；这不保证所请求方案已成功套用。

独立入口差异：诊断离屏执行、完成后自动退出，报告写入显式data-dir；写报告失败返回非零码。原报告生成器、专精/方案注入及字段显示切换路径已迁入，但原入口的混合参数优先级、未知参数忽略及常驻GUI行为没有冒充为完全一致。原版--selftest与本工程同名参数含义也不同，其他原CLI分支仍需逐项接入和核对。

## 循环库离线诊断

`WowBuddyDev.exe --hub-selftest --data-dir D:/wowbuddy-hub-diagnostics` 检查该目录hub/rotations.json，首次缺少缓存时与独立GUI一样初始化内置快照，已有文件不覆盖。生成原格式_hub.txt和补充hub-selftest.json。命令不创建窗口、游戏后端或网络客户端，显式隔离旧WOWBUDDY_HOME和服务器环境变量；--hub-fetch未接入，传入会报参数错误。

原文本中的PASS仅表示存在方案；补充JSON将cache_check_passed与profiles_with_missing_actions分开。当前41套方案能加载，18套有缺失动作；二者可以同时成立，不代表全部方案可用。缓存损坏、空库或原文本报告写入失败返回非零码，已有缓存保留不修复。独立版只允许--hub-selftest与--data-dir配合；首次种子快照、额外JSON、报告失败返回码和严格参数检查均为明确的独立入口差异。

## 引擎离线自检

`WowBuddyDev.exe --engine-selftest --data-dir D:/wowbuddy-engine-diagnostics` 运行迁入的原062cd0自检组：初始候选/治疗约束、绑定与阈值展示、焦点、循环库、焦点去重、自动选怪、非GCD、光环和像素几何。原格式文本追加到_selftest.txt（多次运行保留多段），JSON最新摘要写入engine-selftest.json。

为避免与已有GUI启动自检混淆，独立入口使用--engine-selftest名称；--selftest仍是GUI构造/关闭自检。原引擎报告常量中“C++”标题沿用原文字，不代表执行了原EXE或C++引擎。顺序采用本地rules.json专精键顺序，JSON明确标注，不能当作已复现原Qt QHash的运行时顺序。

本地资源当前9组报告的已提供检查计数无失败；循环库最低血裁决还有41次无同档多人决策而跳过，JSON单列skipped，不计为通过。checks_passed只汇总原结果对象提供的断言和错误计数，部分展示段落不含断言，更不能覆盖全部功能。执行或写报告失败、检查计数失败时独立命令返回非零码；原命令的固定返回码保存在native_command_exit_code。损坏缓存会拒绝并保留文件。此诊断没有抓屏、游戏输入或网络操作。

## 0.2插件与桌面版本配套

本次插件版本为0.2.0-dev，使用0x574201协议标记，修复24项技能位图溢出及旧count全白哨兵冲突。必须与当前WowBuddyDev桌面程序配套安装，不能使用原EXE读取新插件。新桌面继续识别旧插件，但旧格式的信息丢失无法恢复。原来安装的0.1开发插件需要通过“安装/更新开发插件”更新后，才能获得位图修复。742个合成完整图像场景通过不等于游戏施法已验收。
