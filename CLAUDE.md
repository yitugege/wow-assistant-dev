# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本仓库是用户自有的 WoW 战斗助手：Windows 桌面端（Python + PySide6，抓取游戏窗口像素、决策后发键）与配套 WoW 插件（Lua，把游戏状态编码成像素条）。沟通与文档用中文。项目约束以 `AGENTS.md` 为准，要点：

- 原 EXE 与 `D:/reverse-analysis/wow-assistant` 只作参考，不在其中开发；`tools/` 里写死这些路径的审计脚本只做对照。
- 不重新接入旧更新服务（`wowbuddy.cn`）；客户端、插件、循环库只从 GitHub 仓库 `yitugege/wow-assistant-dev`（`desktop/wowbuddy/dev_version.REPOSITORY`）更新。代码里残留的 `wowbuddy.cn` 字符串是存档组织名等标识，不是连接地址。
- 构建自检、离线测试与游戏实测分开报告；自动施法、换目标、无人托管等功能必须有游戏内证据，不能以测试通过或窗口能启动代替。
- WoW 受保护操作须遵守客户端安全执行机制（`SecurityDiagnostics.lua` 记录 ADDON_ACTION_BLOCKED/FORBIDDEN）。
- 未经明确要求不提交、不推送、不创建公开远程仓库；保留用户已有的未提交修改。

## 常用命令

```
python -m pip install -r requirements-dev.txt          # PySide6、lupa（Lua 测试）、PyInstaller
python run_dev.py [--no-watch] [--data-dir=...]        # 启动桌面端
python -m unittest discover -s tests -v                # 全部测试
python -m unittest discover -s tests -p "test_core_split.py" -v      # 单个测试文件
python -m unittest discover -s tests -p "test_core_split.py" -k test_toc   # 单个用例
python tools/test_core.py                              # 核心行为回归，结果写 dist/core-tests.json
python run_dev.py --desktop-selftest | --engine-selftest   # 离屏 GUI 检查 / 原引擎自检组
python tools/addon_module_deps.py [--write]            # 核对 / 重新生成插件各文件的模块依赖声明
python tools/build_addon.py                            # dist/WowBuddyDev-dev.zip（固定目录名）
python tools/build_github_release.py                   # 公开发布包（插件目录与 Lua 文件随机命名）
python tools/build_desktop.py                          # dist/desktop/WowBuddyDev/ 目录版，结束时跑冻结自检
```

测试没有 `__init__.py`，各测试文件自行把 `desktop/`、`tools/` 加入 `sys.path`。Lua 测试用 lupa（Lua 5.1）执行插件源码；`test_addon_full_load.py` 按 TOC 加载整个插件并模拟登录。

## 代码结构

```
run_dev.py                 桌面入口（PyInstaller 冻结入口）：解析参数、选后端、构造 DevWindow
run_outer_dev.py           自有单文件外层入口（→ wowbuddy.dev_outer_entry，复用 legacy 的资源释放与启动宿主）
desktop/wowbuddy/
  core/        纯决策与协议：表达式求值、候选与规则、像素协议（old/readable/dev）、像素几何、按键解析、
               自动目标与焦点排序、Qt 数字/文本语义（qt_numbers、qt_text）
  win32/       窗口枚举、抓屏（DXGI/PrintWindow）、按键与鼠标发送
  engine/      管线、方案控制器、调度、发送、监控会话、阈值、显示表、角色状态解码（character_state）
  automation/  无人托管：导航、步行路线与道路表（walking_route）、练级选点、跑尸复活、补给往返、
               交任务、飞行、拾取；unattended（状态机）与 unattended_phases（阶段处理器）
  update/      GitHub Release 检查与下载校验（github_*）、目录版客户端/外层/插件的暂存与交接安装（dev_*）；
               updater/addon_update 只剩共享数据结构与插件重装策略，旧更新服务流程已删除
  addons/      插件安装与识别：游戏目录检测、包校验安装（dev_addon_install）、热安装、旧插件清理、命令行安装
  app/         Qt 应用层：qt_app（基础主窗口）、dev_window（开发版主窗口）、窗口外壳与界面部件
  legacy/      原版外层、启动宿主与保护线程的还原对照；自有外层仍在使用其中部分，不再扩展
  selftest/    原引擎自检组（--engine-selftest），fixtures/ 为合成输入
  *.py         入口层：启动阶段与崩溃取证、命令行/诊断入口（dev_native_*、cli_*）、循环库同步（hub_sync、dev_hub_*）、
               设置、版本与仓库名（dev_version）、发布标识（release_identity）
addon/WowBuddyDev/
  Modules.lua、Core*.lua     模块注册表与原 Core 拆分文件（见下文）
  PixelBar.lua               把游戏状态编码为像素条，桌面端据此解码
  DirectCast*.lua            直接施法：宏解析、槽位、守卫条件、移动门控、钩子与探针
  AutoTarget、RaidFocus、HealingNpcFocus、CharacterState、Recovery、WandShot …   各功能模块
  Forever*.lua、classes/<职业>/   职业与天赋数据、每职业 class_forever.lua 与 <职业>-Bindings.lua（宏槽位）
  PanelV2、SettingsUI、DebugAuras、DebugDock …   界面与调试面板
  TimelineData_*.lua、MacroRefsData.lua   纯数据表
  SecurityDiagnostics.lua    记录受保护操作拦截事件
  Libs/                      第三方库（LibStub、CallbackHandler、LibSharedMedia、LibRangeCheck）
assets/        协议契约（contract*.json）、规则（rules*.json）、离线循环库快照（rotations.json）
tools/         构建（build_*）、发布与冻结包核查（check_*）、模块依赖（addon_module_deps）、逆向对照审计（audit_*）
tests/         单元与对照测试；addon_sources.py 负责拼回原 Core.lua
docs/          专题记录（INDEX.md 索引）；design/ 为需求设计文档（TEMPLATE.md 为模板）；
               evidence/ 与根目录 *.json 为迁移/对照的证据记录
```

## 桌面端架构（desktop/wowbuddy）

分层由 `tests/test_layer_boundaries.py` 静态检查：`core` 只依赖自身和标准库（不导入 Qt/ctypes/winreg）；`automation` 不导入 Qt；除 `app` 外的子包都不导入 `app`。

每帧数据流：`win32/capture` 抓帧 → `core/*_protocol` 把像素条解成字段（`old`/`readable` 两种帧格式；`dev_protocol.is_dev_frame` 判断是否本工程插件的协议版本 `DEV_VERSION`）→ `engine/pipeline` 求值规则与候选（`core/expressions`、`core/candidates`）→ `engine/dispatch` 经 `win32/windows_keys` 发键。`engine/character_state` 从同一帧解出角色、死亡、任务、商人、飞行、怪物等状态包（`_signed_packet` 读定长签名包，`_alive_at` 校验同序号存活帧）。

`app/qt_app.AssistantWindow` 是基础主窗口；`app/dev_window.DevWindow` 叠加无人托管、GitHub 更新和插件管理，由 `run_dev.py` 用 `DevLaunchOptions` 构造。无人托管：

- `automation/unattended.UnattendedController` 是所有行程状态的唯一持有者；`DevWindow` 上的 `_leveling_trip`、`_quest_trip` 等属性只是 `delegated()` 委托。
- `classify()` 把状态汇总为 `UnattendedPhase`；`run_frame()` 是生成器，按序产出本帧 `FrameAction`（REVIVAL/VENDOR/QUEST/LEVELING/NAVIGATION），窗口执行后用 `send()` 回传交任务结果。
- 复活、补给、练级的处理体在 `automation/unattended_phases.py`（`RevivalPhase` 等，参数 `host` 即窗口）；窗口保留同名的一行委托方法，测试的 `patch.object(window, '_poll_leveling')` 依赖它们。

测试大量用 `patch('wowbuddy.<模块>.<名字>')`（例如 79 处 `character_state.decode_*`）：抽取公共函数时，被打桩的函数必须仍经模块全局名调用；删除或改名模块级名字前先 grep `tests/`。

`core/qt_numbers`、`core/qt_text` 复刻原程序 Qt 的整数转换与 UTF-16 文本语义，失败返回值等差异是有意保留的。

## 插件架构（addon/WowBuddyDev）

- `WowBuddyDev.toc` 既是加载顺序，也是打包白名单：`tools/build_addon.collect_files` 只收 TOC 条目加 `RESOURCE_FILES`（贴图、音效、`forever_spell_ids.lua` 特征文件）。新增文件必须进 TOC 或 `RESOURCE_FILES`，否则不进包；对照源码与包内容时用 `collect_files`，不要用 `rglob('*.lua')`。
- `Modules.lua` 是模块注册表，TOC 第一个加载。每个文件开头一行带 `-- @@注册表命名空间@@` 的 `Namespace("文件名", { 使用的模块 })` 取得命名空间视图；跨模块读写未声明依赖的字段只记入 `WowBuddyDev.moduleErrors`，不拦截。`uses` 列表由 `tools/addon_module_deps.py --write` 生成，`test_core_split.py` 校验它与静态分析一致。加载期依赖用 `RegisterModule(name, requires)` / `Require(name)` / `ModuleExports(name)`。
- 原 `Core.lua` 已按原语句顺序拆成 `CoreSettings/CoreState/CoreCooldownLedger/CoreConsumables/CoreClassData/Core/CoreCastState/CoreLocale/CoreButtons/CoreEvents/CoreControls/CoreMovement/CoreDiagnostics.lua`。拆分脚手架必须保持可逆：
  - `Core.lua` 中 `-- @@拆分：X.lua@@` 标记 X 的正文位置，`-- @@原行：...@@` 保留移走的原行；
  - 带 `-- @@拆分新增@@` / `-- @@注册表命名空间@@` 的行和末尾 `RegisterModule(...)` 不属于原文；
  - 原文件级状态 local 改成了状态表字段 `coreState.X`，带 `-- @@状态表@@` 的行原为 `local X = ...`；
  - `tests/addon_sources.rebuilt_core()` 据此拼回原 `Core.lua`，结果必须与拆分前逐字节一致，大量 `test_original_*` 对照测试以此对比原版行为。改 Core 系列文件时同步维护这些标记。
- 职业宏：`Bindings.lua` 的 `CLASS_MACRO_SLOTS` 定义 192 个槽位及顺序，`classes/*/*-Bindings.lua` 只为有宏的键调用 `BindKey`，空槽自动登记（`tests/test_class_binding_slots.py`）。
- 插件公开函数挂在 `WowBuddyDev` 表上（可能被 `/run`、宏或桌面端依赖），全局 `_G.WowBuddyDev` 保留为对外兼容面；插件内部经命名空间视图访问。

## 从需求到落地的流程

无论是新功能，还是用户在游戏里发现的问题，都按下面的阶段走。**未经用户确认设计，不改代码**；游戏反馈不直接打补丁，先回到“问题记录与分析”。用户在当次对话中明确要求“直接改”时以用户指示为准，但动手前仍先列出设计要点与风险。

按规模分两档：

- **完整流程**：改变行为、协议、界面或设置的需求。每个需求一份设计文档 `docs/design/YYYYMMDD-<简名>.md`（模板 `docs/design/TEMPLATE.md`），各阶段结论写回该文档。
- **小修正**：不改变行为的一两行修正（错别字、日志文字、明显的笔误）。不单独建文件，在当月记录 `docs/design/fixes-YYYY-MM.md` 追加一条“根因 / 改动 / 验收方法”，仍先经用户确认。

1. **问题记录与分析**（游戏反馈先走这一步）
   - 记录现象、出现条件、复现步骤和证据：桌面日志与诊断文件（`--data-dir` 指定目录，默认 `.local`）、插件 `WowBuddyDevDiagnostics`、`/dump WowBuddyDev.moduleErrors`、截图。证据不足时先列出需要用户补采的内容，不凭猜测修改。
   - 读代码定位根因，说明是哪一段数据流出错：插件采集 → 像素条编码 → 桌面解码 → 决策/状态机 → 发键或界面。区分“根因”与“表现处”，修复针对根因。
   - **复现用例先行**：把证据中的帧读数或状态还原成离线测试（像素帧、解码字段、状态机输入，参照 `tests/` 中已有的合成帧写法），确认它在修复前失败；无法离线复现时在文档中写明原因。
2. **设计**（写进设计文档，交给用户确认）
   - 目标与非目标；要改变的行为与保持不变的行为。
   - 方案与数据流：新增或改动的字段、数据包（签名、行区间、字数）、是否需要改 `DEV_VERSION`/`addonVersionCode` 并重装插件。
   - 模块归属：逐个列出要改或新建的文件及所在层，说明为何放在那里（规则见下一节）；涉及无人托管时写清阶段、`FrameAction` 与优先级。
   - 客户端界面（有界面变化时必写）：控件类型、放在哪张卡片或菜单（共用布局在 `app/ui_layout.build_ui`，开发版专有控件在 `DevWindow._configure_unfinished_controls`）、文字与提示、默认值、启用与禁用条件（如“需先停止监控”）、设置项如何保存在 `settings.SettingsStore`、日志里输出什么。
   - **开关与回退**：自动施法、换目标、无人托管等有风险的新行为必须有独立开关，默认关闭，游戏验收通过后才改为默认开启；写明关闭开关后恢复到的旧行为。
   - 风险：受保护操作、旧存档与旧设置兼容、被打桩的函数名、`rebuilt_core` 对照、性能（每帧路径）。
   - 验收标准：离线测试清单（含第 1 步的复现用例），以及游戏内验收步骤，每步写明预期结果和要采集的证据。
3. **实现**（确认后进行）：按设计的模块顺序改动；先补或改测试，再改实现。偏离设计时先更新设计文档并告知用户，不默默扩大范围。
4. **离线自检**：在装好 `requirements-dev.txt`（PySide6、lupa）的环境中跑设计列出的测试和分层、拆分、依赖检查，复现用例须由失败变为通过；需要时构建插件包或桌面版。把命令和结果（含失败）写进设计文档，不把通过的测试当作功能可用。缺少可运行环境时先提出搭建（本机可用 Comfy 自带的 `D:/Program Files/Comfy Desktop/resources/bootstrap-python/uv.exe` 在临时目录建虚拟环境，下载依赖前征得用户同意），不能以静态检查代替并宣称自检完成。
5. **游戏内验收**（由用户执行）：给出验收清单，逐项写明操作、预期和要回传的证据。优先让用户回传一键诊断包（桌面日志、诊断文件、`moduleErrors`、`WowBuddyDevDiagnostics` 打包；该功能尚未实现，实现前按清单逐项回传）。用户回传结果后对照验收标准判断，结论写回文档；未通过的回到第 1 步分析，不直接追加补丁。
6. **收尾**：在 README 的“当前状态”或 `docs/` 相关文档中更新已验证与未验证的部分；发布时在发布说明（`docs/RELEASE-<版本>.md`）中列出本版包含的设计文档编号与小修正记录。不提交、不推送，除非用户要求。

## 按模块添加新功能

先按性质定层：纯计算放 `core/`，每帧编排与状态解码放 `engine/`，无人托管行为放 `automation/`，系统交互放 `win32/`，更新与安装放 `update/`、`addons/`，界面只放 `app/`。

- **新的角色状态读数**：插件端在 `CharacterState.lua` 仿照 `collectQuestPin` 发一个“签名字 + 数据字 + 校验字”的包（新签名沿用 `0x5742xx`，占用不与现有包重叠的行，`appendChecksum` 生成校验）；桌面端在 `engine/character_state.py` 用 `_signed_packet(image, frame, 起始行, 字数, 签名)` 读包，需要时 `_alive_at` 校验序号，返回冻结 dataclass。两端签名、起始行、字数必须一致；改变整体协议时同步改 `core/dev_protocol.DEV_VERSION` 与 `Core.lua` 的 `addonVersionCode`，并重装插件。
- **新的无人托管阶段**：状态字段加进 `UnattendedSnapshot`，需要时加 `UnattendedPhase` 并在 `classify()` 定优先级，在 `run_frame()` 产出新的 `FrameAction`；处理体写成 `unattended_phases.py` 中的 `XxxPhase`（经 `host` 发键、写日志，不导入 Qt）；`DevWindow` 只加 `poll_once` 分发分支、一行委托方法和 `delegated()` 属性；在 `tests/test_unattended_phase.py` 补阶段与动作顺序测试。
- **新的插件模块**：新建 `Xxx.lua`，首行写带 `-- @@注册表命名空间@@` 的 `Namespace("Xxx", { })` 声明；加入 `WowBuddyDev.toc`（资源文件加入 `tools/build_addon.RESOURCE_FILES`）；运行 `python tools/addon_module_deps.py --write` 填写依赖。对外接口挂在 `WowBuddyDev.Xxx`，插件内部传递用 `ModuleExports`/`Require`，加载期依赖在文件末尾 `RegisterModule("Xxx", {...})` 声明。新增像素字段时同步改 `PixelBar.lua`、`assets/contract*.json` 和桌面端解码。
- 新功能尽量放新文件，不改 `Core*.lua`；必须改时维护拆分标记并保证 `rebuilt_core()` 仍与原文逐字节一致。施法、选目标等受保护调用只能走按键触发路径，不放进定时器。
- 完成后至少跑 `test_layer_boundaries.py`、`test_core_split.py`、`tools/addon_module_deps.py` 和全量测试；游戏内实测单独报告。

## 文档

`README.md` 是当前状态与结构概览；`docs/INDEX.md` 索引全部专题记录，`docs/HISTORY.md` 是旧版 README（各命令与诊断入口细节）。
