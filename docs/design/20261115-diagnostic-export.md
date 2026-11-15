# 一键导出诊断

- 编号：20261115-diagnostic-export
- 状态：游戏验收通过（2026-11-15，G1–G4）
- 来源：新需求（2026-11-15，流程改进第 3 条：游戏验收证据收集）
- 发布版本：（发布后填写）

## 1. 问题记录与分析

- 现象：游戏内验收时，证据要由用户手工从多个位置收集（桌面日志、诊断文件、SavedVariables、聊天框里 `/dump` 的输出），容易漏项，且文件里含账号名与本机用户名。
- 现状（排查结论）：
  - 桌面端写在数据目录 D（默认 `<程序目录>/.local`，`--data-dir` 可改；`dev_paths.py`）：`startup.log`(+`.old`)、`startup-error.log`、`logs/monitor_*.log`、`settings.ini`、各类结果 JSON（`leveling-*.json`、`vendor-travel.json`、`update-*.json`、`_update.txt`、`client-update-*.json`、`addon-release.json`、`hub-selftest.json`、`engine-selftest.json`、`dump-ui.json`）。
  - 插件已持久化的 SavedVariables（`WowBuddyDev.toc`）：`WowBuddyDevDB`、`WowBuddyDevDiagnostics`（受保护操作拦截记录，≤50 条，`SecurityDiagnostics.lua`）、`WowBuddyDevHookProbe`、`WowBuddyDevHookLog`。文件位于 `<客户端>/WTF/Account/<账号>/SavedVariables/<插件目录名>.lua`；发布包的插件目录名为随机 `w`+12 位十六进制，由 `<客户端>/.wowbuddy-install.json` 记录（`update/dev_addon_update.installed_name`）。
  - **只在运行时存在、不落盘**：`WowBuddyDev.moduleErrors`（模块越界）、Lua 错误收集器（`WowBuddyDev.GetCapturedLuaErrors()`，≤10 种）、`WowBuddyDev.errorLogs`（≤50 条）。
  - 界面只有“运行日志”卡片与“清空日志”按钮（`app/ui_layout.py`）；没有打开目录或导出动作。桌面运行代码里没有写 zip 的辅助函数。
  - 窗口环境设置了 `WOWBUDDY_NO_GAME_SCAN`，`discover_clients` 在该环境下返回空；导出需显式传入不含该变量的环境。

### 复现用例

新功能，无缺陷复现；以第 3 节离线验收作为先行测试（先写测试，确认失败，再实现）。

## 2. 设计

### 目标与非目标

- 目标：一次操作生成一个 zip，包含游戏验收所需的全部证据，并去掉账号名与本机用户名。
- 目标：插件把只在运行时存在的三类诊断在登出/重载时写入 SavedVariables，使其能被导出。
- 目标（2026-11-15 用户决定并入）：开发版的客户端识别与插件安装认得官方经典服客户端：执行文件 `WowClassic.exe` / `WowClassicB.exe`，安装根目录下的子目录 `_classic_`、`_classic_era_`、`_classic_titan_`。用户的客户端为 `D:\Program Files (x86)\World of Warcraft`。
- 非目标：不上传、不联网；不读取或修改游戏进程；不改变任何战斗、发键、无人托管行为；不导出 `hub/` 循环库与攻略缓存。
- 保持不变：现有 SavedVariables 结构（`WowBuddyDevDiagnostics` 仍是记录数组）、所有现有文件的写入方式。
- 保持不变：原版对照的安装与检测（`addons/addon_install.GAME_VARIANTS`、`addon_games`、`addon_actions` 的“无限客户端”提示）仍只认 `_classic_beta_\WowB.exe` 与 `_cn_beta_\Wow.exe`；窗口与发键层 `win32/game_windows.GAME_EXECUTABLES` 本来已包含 `wowclassic.exe`、`wowclassicb.exe`，不改。

### 方案与数据流

- 插件端：新文件 `RuntimeDiagnostics.lua`（TOC 放在 `SecurityDiagnostics.lua` 之后），新 SavedVariable `WowBuddyDevRuntimeLog`。在 `PLAYER_LOGOUT`（登出与 `/reload` 都会触发）时写入快照：`{ savedAt, addonVersionCode, moduleErrors, luaErrors, errorLogs }`，各项复制而非引用，条数上限：moduleErrors 100、luaErrors 10、errorLogs 50。另提供 `/wbddiag`：立即刷新快照并在聊天框提示“需 /reload 后才写入磁盘”。
- 像素协议：无变化，不改 `DEV_VERSION` / `addonVersionCode`。
- 桌面端：新模块 `wowbuddy/diagnostic_export.py`（入口层，汇总多个子包的数据，不被下层导入）：
  - `export_diagnostics(data_dir, clients, *, now, environment) -> Path`：在 `D/diagnostics/` 生成 `wowbuddy-diagnostics-YYYYmmdd-HHMMSS.zip`，返回路径。
  - 收录：`desktop/` 下的上述桌面文件（`logs/` 只取最新 5 个监控日志）；每个检测到且已安装本插件的客户端 `clients/<序号>/`：`install.json`（安装记录）与各账号的 `<插件目录名>.lua`（存为 `savedvariables/<账号代号>/WowBuddyDev.lua`，同时在 manifest 记录原插件目录名）。
  - `manifest.json`：导出时间、客户端版本（`dev_version.VERSION`）、每个成员的来源类别与大小、缺失项列表、截断项列表、`game_verified: false`、`redactions`（替换规则说明，不含原值）。
  - 隐私处理：所有文本成员与 manifest 中，账号名替换为 `<ACCOUNT-n>`，本机用户名（`USERNAME` 及用户目录路径中的名字）替换为 `<USER>`；路径中的账号目录同样使用代号。
  - 大小限制：单个文本文件超过 2 MiB 只保留末尾 2 MiB（manifest 记录截断），zip 未压缩总量上限 50 MiB，超出的成员跳过并记入 manifest。
  - 只读来源文件；不在数据目录以外写文件。
- 命令行：`run_dev.py --export-diagnostics [--data-dir=...]`，列入 `strict_commands`；扫描客户端（不受 `WOWBUDDY_NO_GAME_SCAN` 影响），导出后把 `{ok, path, members, missing}` 写入 `D/diagnostics-export.json`，成功返回 0，失败返回 1 并写入错误。

### 模块归属

| 文件 | 层 | 新建/修改 | 内容 | 放在这里的理由 |
|---|---|---|---|---|
| `desktop/wowbuddy/diagnostic_export.py` | 入口层 | 新建 | 收集、脱敏、限量、写 zip 与 manifest | 需同时用到 addons（客户端发现）、update（插件目录名）、设置；只有入口层可以汇总多个子包 |
| `run_dev.py` | 入口 | 修改 | `--export-diagnostics` 参数与分派 | 现有诊断命令都在这里注册 |
| `desktop/wowbuddy/app/ui_layout.py` | app | 修改 | “运行日志”卡片增加“导出诊断”按钮（`ExportDiagnostics`） | 与“清空日志”同一卡片 |
| `desktop/wowbuddy/app/qt_app.py` 或 `app/dev_window.py` | app | 修改 | 按钮槽函数：调用导出、写日志、打开所在目录 | 界面行为只放 app 层；放 `dev_window`，基础窗口按钮保持禁用 |
| `addon/WowBuddyDev/RuntimeDiagnostics.lua` | 插件 | 新建 | 登出快照与 `/wbddiag` | 新功能放新文件，不改 Core 系列 |
| `addon/WowBuddyDev/WowBuddyDev.toc` | 插件 | 修改 | 加入新文件与 `WowBuddyDevRuntimeLog` | TOC 为加载顺序与打包白名单 |
| `tests/test_diagnostic_export.py` | 测试 | 新建 | 导出离线验收 | — |
| `tests/test_runtime_diagnostics.py` | 测试 | 新建 | 插件快照（lupa） | — |
| `desktop/wowbuddy/addons/dev_addon_install.py` | addons | 修改 | `CLIENT_EXECUTABLES`（与 `GAME_EXECUTABLES` 相同的四个执行文件，不区分大小写）；`client_directory` 按它判断，错误提示同步 | 开发版安装与发现共用的客户端判定在此；不直接导入 `win32` 以免安装路径依赖 ctypes，由测试保证两处一致 |
| `desktop/wowbuddy/addons/dev_game_paths.py` | addons | 修改 | `VARIANTS` 增加 `_classic_`、`_classic_era_`、`_classic_titan_` | 发现客户端时逐个尝试的子目录 |
| `tests/test_client_recognition.py` | 测试 | 新建 | 经典服客户端识别 | — |

### 客户端界面

- 控件与位置：右侧“运行日志”卡片，“清空日志”按钮下方新增按钮“导出诊断”，对象名 `ExportDiagnostics`，在 `app/ui_layout.build_ui` 创建，`UiWidgets.export_diagnostics_button`。
- 文字与提示：按钮提示“把日志、诊断文件和游戏中的插件诊断打包成一个 zip（账号名与用户名已替换）。游戏里先 /reload 才能包含最新插件记录。”
- 默认值，启用与禁用条件：基础窗口中禁用；开发版窗口中启用，导出进行时禁用防止重复点击。
- 设置持久化：无。
- 日志输出：成功“已导出诊断：<zip 路径>（共 N 项，缺少 M 项）”；失败“诊断导出失败：<原因>”。成功后用系统文件管理器打开 `D/diagnostics/`。

### 开关与回退

不涉及自动施法、换目标或无人托管，只读导出，不设开关。插件端登出快照异常时只跳过快照（`pcall` 包裹），不影响登出与其他模块。

### 风险

- 受保护操作：无（只读 Lua 表、写 SavedVariable）。
- 旧存档兼容：新增独立 SavedVariable，不改动现有变量结构。
- 隐私：脱敏只覆盖账号名与本机用户名；角色名、服务器名、游戏路径中的其他部分仍会保留，manifest 与按钮提示中说明。
- 测试打桩、`rebuilt_core`：不改 Core 系列文件。
- 性能：快照只在登出时执行一次；导出在按钮点击时同步执行，文件量有上限。
- 经典服客户端：插件 TOC 的 `## Interface: 16001, 120100` 可能与官方经典服版本号不符，游戏会把插件标为“过期”，需要在插件列表勾选“加载过期插件”；插件中的“无限版”专属接口在官方服可能不存在。识别规则扩展只解决“找得到客户端”，插件能否在该客户端正常工作由 G1 实测确认，不在离线验收范围内。
- 识别范围扩大后，“安装插件”与“导出诊断”会列出同一安装根目录下的多个经典服客户端（如 `_classic_` 与 `_classic_era_`），各自独立处理。

## 3. 验收标准

### 离线

| 编号 | 检查 | 命令 | 预期 |
|---|---|---|---|
| A1 | 导出内容与结构 | `python -m unittest discover -s tests -p "test_diagnostic_export.py" -v` | 用临时数据目录与伪客户端（含随机插件目录名、两个账号）导出：zip 含 `manifest.json`、桌面文件、两个账号的 SavedVariables；缺失文件出现在 manifest 的缺失列表；监控日志只取最新 5 个 |
| A2 | 脱敏 | 同上 | zip 内任何成员名与内容都不含伪账号名和伪用户名；manifest 记录替换规则但不含原值 |
| A3 | 限量与只读 | 同上 | 超过 2 MiB 的日志只留末尾并记为截断；总量超限的成员被跳过并记录；导出前后来源目录内容逐字节不变；数据目录外无新文件 |
| A4 | 客户端发现不受窗口环境影响 | 同上 | 环境含 `WOWBUDDY_NO_GAME_SCAN` 时导出仍能找到传入的客户端；未安装本插件的客户端不导出 SavedVariables |
| A5 | 命令行 | 同上（用 subprocess 或直接调用入口函数） | `--export-diagnostics --data-dir=<临时>` 返回 0，`diagnostics-export.json` 中 `ok=true` 且路径存在；来源不可读时返回 1 并记录错误 |
| A6 | 界面 | `python -m unittest discover -s tests -p "test_diagnostic_export.py" -v`（离屏 Qt） | 开发版窗口有启用的 `ExportDiagnostics` 按钮；点击后调用导出并在运行日志出现“已导出诊断”；导出失败时日志出现“诊断导出失败”且窗口不崩溃 |
| A7 | 插件快照 | `python -m unittest discover -s tests -p "test_runtime_diagnostics.py" -v` | lupa 加载 `Modules.lua`、`RuntimeDiagnostics.lua` 后触发 `PLAYER_LOGOUT`：`WowBuddyDevRuntimeLog` 含三类记录且为副本、条数受上限约束；快照函数抛错时登出事件不抛出 |
| A8 | 插件结构 | `python -m unittest discover -s tests -p "test_core_split.py" -v`；`python tools/addon_module_deps.py` | TOC 含新文件与新 SavedVariable；依赖声明一致 |
| A10 | 经典服执行文件 | `python -m unittest discover -s tests -p "test_client_recognition.py" -v` | 含 `WowClassic.exe` 或 `WowClassicB.exe`（大小写不限）的目录被 `client_directory` 接受；都没有时仍报错，提示中列出四个执行文件；`CLIENT_EXECUTABLES` 与 `GAME_EXECUTABLES` 一致 |
| A11 | 经典服子目录 | 同上 | `discover_clients` 从安装根目录找到 `_classic_`、`_classic_era_`；原有 `_classic_beta_`、`_cn_beta_`、`_forever_` 仍能找到；原版对照的 `GAME_VARIANTS` 不变 |
| A9 | 回归 | `python -m unittest discover -s tests -v`；`python run_dev.py --desktop-selftest` | 全部通过（含 `test_addon_full_load`、`test_layer_boundaries`） |

### 游戏内（用户执行）

| 步骤 | 操作 | 预期结果 | 需回传的证据 |
|---|---|---|---|
| G1 | 在助手中选择 `D:\Program Files (x86)\World of Warcraft\_classic_`（或 `_classic_era_`）安装本次构建的插件；进游戏在插件列表确认已加载（如显示“过期”，勾选“加载过期插件”），登录角色后 `/reload` | 助手能识别并安装到该客户端；无 Lua 报错 | 截图（如有报错或插件未加载） |
| G2 | 输入 `/run error("wbd-diag-test")`，再输入 `/wbddiag`，然后 `/reload` | `/wbddiag` 提示需重载后写盘 | 无 |
| G3 | 在助手中点击“导出诊断” | 运行日志出现“已导出诊断：…”，自动打开所在目录 | 导出的 zip |
| G4 | 打开 zip 检查 | `manifest.json` 存在；SavedVariables 中 `WowBuddyDevRuntimeLog.luaErrors` 含 `wbd-diag-test`；搜索自己的账号名与 Windows 用户名均无结果 | zip 本身即证据 |

## 4. 实现记录

- 接口拆分：`export_diagnostics(data_dir, clients, ...)` 只导出传入的客户端；客户端发现由 `find_clients(settings)` 完成（固定 `environment=None`，满足 A4）。
- 收录顺序决定总量超限时的跳过次序：SavedVariables → 安装记录 → 数据目录根下诊断文件 → 监控日志。
- 截断在脱敏之后进行，保证截断不会留下半个原始账号名。
- 偏离设计之处（已告知用户）：
  - `find_clients` 默认扫描 `common_roots()`（设计未写明，开发版窗口如此；漏掉会找不到装在常见目录的客户端）。
- 实现中发现、用户已决定并入本需求（见第 2 节目标与 A10、A11）：用户的客户端 `D:\Program Files (x86)\World of Warcraft\_classic_`、`_classic_era_` 的执行文件为 `WowClassic.exe`；现有识别（`addons/dev_addon_install.client_directory`）只认 `Wow.exe`/`WowB.exe`，子目录只认 `_classic_beta_`、`_cn_beta_`、`_forever_`，因此导出与插件安装都识别不到该客户端；当前 `_classic_` 下未安装本插件。

## 5. 离线自检结果

- 运行环境：项目 `.venv`（Python 3.13.13、PySide6 6.10.3、lupa 2.8），`QT_QPA_PLATFORM=offscreen`。
- 基线（实现前，2026-11-15）：全量 753 个测试，4 个失败均为 `test_dev_monitor_protocol` 中 HEAD 上即失败的无人托管用例，187 个跳过；先修正了模块边界误报（见 `fixes-2026-11.md`）。

| 编号 | 命令 | 结果 |
|---|---|---|
| A1–A4 | `python -m unittest discover -s tests -p "test_diagnostic_export.py" -v` | 实现前失败（模块不存在）；实现后 8 个用例全部通过 |
| 结构 | `test_layer_boundaries.py`、`test_core_split.py`、`tools/addon_module_deps.py` | 通过；77 个模块 0 处不一致 |
| A5 | 同上（`DiagnosticExportCommandTests`） | 实现前：参数未注册，`run_dev` 进入 GUI 分支并卡在事件循环（测试中止）；实现后 3 个用例通过，`--export-diagnostics` 与其他命令混用时报参数错误 |
| A5 实跑 | `run_dev.py --export-diagnostics --data-dir=<临时目录>` | 返回 0；本机未识别到客户端（见第 4 节），zip 含 `desktop/startup.log` 与 `manifest.json` |
| A4 补充 | `test_a4_find_clients_scans_common_roots_by_default` | 通过：默认扫描 `common_roots()`，与开发版窗口一致 |
| 回归 | `test_dev_*.py`（235 个） | 仅 `test_dev_monitor_protocol` 的 4 个原有失败 |
| A10–A11 | `python -m unittest discover -s tests -p "test_client_recognition.py" -v` | 实现前 2 失败 4 错误；实现后 6 个用例通过 |
| A10–A11 回归 | `test_*addon*.py`（80 个）、`test_dev_*.py`（235 个） | 插件相关全部通过；dev 仅 4 个原有失败 |
| A6 | `test_diagnostic_export.py`（`DiagnosticExportWindowTests`，经 `run_dev.launch` 离屏启动真实开发版窗口） | 实现前 2 个错误（`UiWidgets` 无 `export_diagnostics_button`）；实现后通过：按钮启用、提示含 `/reload`、点击后日志“已导出诊断：…（共 N 项，缺少 M 项）”并打开所在目录；失败时日志“诊断导出失败：…”、不打开目录、按钮恢复可用 |
| A6 回归 | `test_*ui*`、`test_*dump*`、`test_*window*`、`test_*qt*`、`test_dev_*` | 全部通过（dev 仅 4 个原有失败） |
| A7–A8 | `python -m unittest discover -s tests -p "test_runtime_diagnostics.py" -v` | 实现前 5 个错误（文件不存在）；实现后通过：`PLAYER_LOGOUT` 写入 `WowBuddyDevRuntimeLog`（moduleErrors 保留最新 100、luaErrors 10、errorLogs 50，均为副本）；来源缺失时为空表；快照抛错不影响登出（记 `snapshotError`）；`/wbddiag` 刷新并提示需 /reload；TOC 中紧跟 `SecurityDiagnostics.lua`，声明新 SavedVariable |
| A8 | `test_core_split.py`、`tools/addon_module_deps.py` | 通过；78 个模块 0 处不一致（新模块 uses 为 Core、CoreLocale，字段归属表已重新生成） |
| A7–A8 回归 | `test_addon_*`（57 个，含按 TOC 完整加载并登录后 `moduleErrors` 为空）、`test_security_diagnostics`、`test_github_*`、`test_class_*` | 全部通过 |
| A9 | `python -m unittest discover -s tests`（`.venv`，offscreen） | 778 个测试，失败 4 个，均为基线中 HEAD 上即失败的 `test_dev_monitor_protocol` 用例，跳过 187 个（与基线相同）；无其他失败 |
| A9 | `python run_dev.py --desktop-selftest` | 返回 0，`passed: true`，未创建真实系统后端、无联网客户端 |
| 打包 | `python tools/build_addon.py` | `dist/WowBuddyDev-dev.zip` 共 95 个成员，含 `RuntimeDiagnostics.lua`；包内 TOC 列出该文件并声明 `WowBuddyDevRuntimeLog` |
| A10–A11 实跑 | `run_dev.py --export-diagnostics`（本机） | 识别到 `World of Warcraft\\_classic_`、`_classic_era_` 两个客户端；均未安装本插件，未导出 SavedVariables（符合预期） |

## 6. 游戏验收结果

用户实际使用的客户端为 `D:\Program Files (x86)\World of Warcraft1.14\_forever_`（无限版，`Wow.exe`），而非最初提供的官方经典服目录；验收在该客户端上进行。

| 步骤 | 结果 | 证据 |
|---|---|---|
| G1 | 通过：14:01 经助手“安装”将本次构建（含 `RuntimeDiagnostics.lua`）装入 `_forever_\Interface\AddOns\WowBuddyDev`；游戏内插件运行正常（版本码 5718529 = 0x574201，自动选目标通道就绪，角色状态可读） | 监控日志 `monitor_20261115_140144.log`、`monitor_20261115_140259.log` |
| G2 | 通过：`/run error("wbd-diag-test")` → `/wbddiag` → `/reload` 后，SavedVariables 中写入 `WowBuddyDevRuntimeLog`（`savedAt` 有值、`addonVersionCode = 5718529`、无 `snapshotError`，含 moduleErrors/luaErrors/errorLogs） | `wowbuddy-diagnostics-20261115-140800.zip` |
| G3 | 通过：两次点击“导出诊断”（14:05:27、14:08:00）均生成 zip，无截断、无跳过，仅缺本来不存在的 `startup-error.log` | 两个 zip |
| G4 | 通过：`clients/1/savedvariables/<ACCOUNT-1>/WowBuddyDev.lua` 中 `luaErrors` 含 `wbd-diag-test`（14:07:33）；按本机实际账号目录名与 Windows 用户名逐一检查，zip 成员名与内容中出现 0 次，用户名已替换为 `<USER>` | `wowbuddy-diagnostics-20261115-140800.zip` |

结论：游戏验收通过。

观察到的范围外问题（另行处理）：`World of Warcraft\_classic_era_` 于 13:58 被装入 GitHub v0.2.8 旧版插件（随机目录 `w9dc7a52c043c`）；是否由助手自动安装待用户确认。用户最初手工把导出的 zip 成员另存时文件名被打乱，不影响导出本身（以原始 zip 为准）。
