# 开发版插件被 GitHub 旧发布包覆盖

- 编号：20261115-addon-overwritten-by-github
- 状态：游戏验收通过（2026-11-15，E1–E3）
- 来源：游戏内问题反馈（2026-11-15，H1/H2 验收前用户发现“游戏的插件版本不对”）
- 发布版本：（发布后填写）

## 1. 问题记录与分析

### 现象

`D:\Program Files (x86)\World of Warcraft1.14\_forever_`（用户实际使用的无限版客户端）中，14:01 经“安装/更新开发插件”装入的本次构建（含 `Modules.lua`、`RuntimeDiagnostics.lua`），在 14:09:58 被替换为 GitHub 发布包 v0.2.8。`World of Warcraft\_classic_era_` 在 13:58 也被装入同一发布包（随机目录 `w9dc7a52c043c`）。

### 证据（只读核对，未改代码）

| 项 | 观察 |
|---|---|
| 当前安装内容 | `_forever_\Interface\AddOns\WowBuddyDev` 共 78 个文件，无 `Modules.lua`、`CoreState.lua`、`RuntimeDiagnostics.lua`；目录与 `.wowbuddy-install.json` 修改时间 14:09:58–59 |
| 内容来源 | 与 `.local\downloads\github-*\WowBuddyDev-addon.zip`（tag v0.2.8）逐文件比较：77/78 相同；与本地 `dist\WowBuddyDev-dev.zip` 仅 10/78 相同 |
| 下载记录 | `.local\downloads` 有三个下载目录：13:56:56、13:58:15、14:09:58 |
| 监控 | 14:09:47 停止监控（`monitor_20261115_140939.log`），11 秒后插件被替换 |
| 日志缺口 | 停止监控后界面日志不写入文件，安装那一刻的状态文字没有留存 |

### 两条会安装 GitHub 包的路径（代码事实）

1. **“GitHub下载更新”按钮**：`app/dev_window.py` 中 `addon_detect_button` 文字被改为“GitHub下载更新”，点击调用 `_download_github_addon` → `github_addon.download_latest(data_dir)`（不带缓存，**每次都新建下载目录**）→ `install_package` 安装到当前“插件路径”所选客户端。前提只有“未在监控、已选客户端目录”。
2. **启动与定时自动热更**：`_refresh_addon_release`（启动后 `addon_startup_timer`、之后随 `hub_timer` 周期触发）→ `dev_addon_update.refresh_package`（优先用 `addon-release.json` 缓存，发布内容未变则不下载）→ `apply_release`：发布内容有变化（`changed=True`）时，对所有检测到且已安装本插件、未在运行的客户端调用 `reinstall_games` 重装。

### 推断

- 13:56:56 为启动后的首次自动检查（无缓存，下载并 `changed=True`）。
- 13:58:15、14:09:58 两次都新建了下载目录，符合手动点击“GitHub下载更新”的特征，且时间与 `_classic_era_`、`_forever_` 被替换的时间对应。
- **用户已确认**（2026-11-15）：这两个时间点击过“GitHub下载更新”。证据链完整：两次覆盖均由手动点击“GitHub下载更新”造成，自动热更未参与本次覆盖（R3 仍是潜在风险）。

### 根因

| # | 根因 | 位置 |
|---|---|---|
| R1 | 两个按钮语义接近且相邻：“GitHub下载更新”装的是已发布版本，“安装/更新开发插件”装的是本地构建；按钮上没有标明各自会装哪个版本 | `app/dev_window._configure_unfinished_controls` |
| R2 | 插件版本号写死：源码 `WowBuddyDev.toc` 为 `## Version: 0.2.8-dev`，`tools/build_addon.py` 不改写版本行；桌面版本已是 `dev_version.VERSION = '0.2.21'`。新旧插件在游戏和助手中无法区分；`tools/check_release_consistency.py` 要求包内 TOC 为 `## Version: <VERSION>-dev`，按现状该检查会失败 | `addon/WowBuddyDev/WowBuddyDev.toc`、`tools/build_addon.py` |
| R3 | 安装前不比较版本：`download_latest` 只校验产品名与协议号（v0.2.8 与当前同为 `0x574201`），`install_package` / `apply_release` 都不判断“将装的版本是否比已装的旧”；自动热更会把所有客户端里的开发构建替换为新发布的包 | `update/github_addon.py`、`update/dev_addon_update.py`、`addons/dev_addon_install.py` |

### 复现用例（`tests/test_addon_version_guard.py`）

- R2：打包后包内 TOC 的 `## Version` 应等于 `<dev_version.VERSION>-dev`（当前为 `0.2.8-dev`，失败）。
- R3：客户端已装版本较新时，“GitHub下载更新”与自动热更不应覆盖（当前会覆盖，失败）。
- R1：界面测试断言两个按钮的文字与提示能区分来源与版本。

## 2. 设计（用户已确认，2026-11-15）

### 目标与非目标

- 目标：开发构建不会被较旧的 GitHub 发布包悄悄覆盖；用户能在助手与游戏中看出装的是哪个版本；两个安装入口不易混淆。
- 非目标：不改变发布流程本身；不移除“GitHub下载更新”与自动热更（普通用户靠它们更新）。

### 方案

1. **版本号写入（R2）**：`tools/build_addon.py` 打包时把 TOC 的 `## Version` 改写为 `<VERSION>-dev`（源码 TOC 同步改为当前版本，作为默认值）；安装记录 `.wowbuddy-install.json` 增加 `version` 字段。
2. **不降级（R3）**：安装前读取目标客户端安装记录中的版本：
   - 自动热更（`apply_release`）：将装版本不高于已装版本时跳过该客户端，并写日志“已装 X，不低于发布版 Y，跳过”。
   - “GitHub下载更新”按钮：将装版本低于已装版本时弹出确认框，写明两个版本号，用户确认才覆盖。
   - 没有版本记录的旧安装按“未知、允许覆盖”处理（与现状一致）。
3. **按钮区分（R1）**：
   - “安装/更新开发插件” → “安装本地构建（v<VERSION>）”，提示写明来源为 `dist\WowBuddyDev-dev.zip`（冻结版为 `packages\`）。
   - “GitHub下载更新” → “安装 GitHub 发布版”，检查到发布版后提示中写明其版本号。
   - 安装完成的状态文字与日志统一写明“来源 + 版本 + 目标客户端”。
4. **日志留存**：停止监控后的插件安装结果也写入文件（补上本次的证据缺口）——实现方式待定，可写入 `startup.log` 或单独的 `addon-install.log`。

### 模块归属（草案）

| 文件 | 层 | 内容 |
|---|---|---|
| `tools/build_addon.py`、`addon/WowBuddyDev/WowBuddyDev.toc` | 工具 / 插件 | 版本行改写 |
| `addons/dev_addon_install.py` | addons | 安装记录写入/读取版本；比较函数 |
| `update/dev_addon_update.py` | update | 自动热更跳过不升级的客户端 |
| `app/dev_window.py` | app | 按钮文字与提示、降级确认框、安装日志 |

### 开关与回退

不涉及自动施法、换目标或无人托管；不设开关。降级仍可通过确认框完成。

### 风险

- 版本比较依赖安装记录，手动解压安装的客户端没有记录，按“未知”处理时仍可能被覆盖。
- 改写 TOC 版本行会改变包内容与摘要，相关打包测试需同步。

## 3. 验收标准

### 离线

| 编号 | 检查 | 预期 |
|---|---|---|
| D1 | 打包版本 | 包内 TOC 为 `## Version: <VERSION>-dev`；安装记录含 `version`；`check_release_consistency` 的版本断言可通过 |
| D2 | 自动热更不降级 | 已装版本 ≥ 发布版时不重装并记录日志；已装版本较旧或未知时照常重装 |
| D3 | 手动下载降级确认 | 发布版较旧时弹确认框，取消不改文件，确认后覆盖 |
| D4 | 按钮与日志 | 两个按钮文字/提示区分来源与版本；安装日志含来源、版本、目标客户端，停止监控后也写入文件 |
| D5 | 回归 | 全量测试 0 失败 |

### 游戏内（用户执行）

| 步骤 | 操作 | 预期 |
|---|---|---|
| E1 | 用“安装本地构建”装入 `_forever_`，重启游戏 | 游戏插件列表与助手显示同一版本号 |
| E2 | 点击“安装 GitHub 发布版” | 弹出降级确认，取消后插件文件不变 |
| E3 | 重启助手（触发自动热更） | 插件文件不变；若 GitHub 发布内容有更新，日志显示跳过 `_forever_`（发布内容未变时自动热更不进入重装，不会出现“跳过”） |

## 4. 实现记录

- `tools/build_addon.py`：TOC 版本行（固定名与随机名包都）改写为 `## Version: <VERSION>-dev`，清单增加 `version`；源码 TOC 同步为 `0.2.21-dev`。
- `addons/dev_addon_install.py`：新增 `package_version`、`installed_version`、`is_newer`；安装记录写入 `version`，`install_package` 返回值含 `version`。
- `update/dev_addon_update.apply_release`：自动热更跳过“已装版本不低于发布版”的客户端并记日志。
- `app/dev_window.py`：
  - 按钮改为“安装本地构建（v<VERSION>）”（提示写明 `WowBuddyDev-dev.zip` 路径）与“安装 GitHub 发布版”；
  - “安装 GitHub 发布版”在发布版比已装版本旧时弹 `QMessageBox.question` 确认，取消则不改文件；客户端目录无效时不做版本检查，由安装函数报原有错误；
  - 安装结果写明来源、版本与目标客户端，经 `_record_addon_install` 同时写入运行日志与 `数据目录/addon-install.log`（导出诊断会收录）；自动热更的日志也走这里。
- 偏离设计之处：无。测试 `test_dev_tray` 中“已安装2个文件”的断言随文字变更调整为“已安装本地构建”“2 个文件”。

## 5. 离线自检结果

- 运行环境：项目 `.venv`（Python 3.13.13、PySide6 6.10.3、lupa 2.8），`QT_QPA_PLATFORM=offscreen`。

| 编号 | 命令 | 结果 |
|---|---|---|
| 复现 | `python -m unittest discover -s tests -p "test_addon_version_guard.py"` | 实现前 6 失败 4 错误（另 2 个为现有行为的回归保护，本就通过）；实现后 10 个用例全部通过 |
| D1–D4 | 同上 | 版本写入与记录、自动热更跳过（已装 0.2.21/0.2.8 时跳过，0.2.1/未知时重装）、GitHub 较旧版需确认（取消不安装、确认后安装、较新版不弹框）、按钮文字与提示、安装日志写入 `addon-install.log` |
| D5 | `python -m unittest discover -s tests` | 788 个测试 0 失败，跳过 187 个 |
| 结构 | `tools/addon_module_deps.py` | 78 个模块 0 处不一致 |
| 打包 | `python tools/build_addon.py` | 95 个文件；包内 TOC `## Version: 0.2.21-dev`，清单 `version: 0.2.21` |
| 自检 | `python run_dev.py --desktop-selftest` | 通过 |

## 6. 游戏验收结果

| 步骤 | 结果 | 证据 |
|---|---|---|
| E1 | 通过：14:43:38 经“安装本地构建（v0.2.21）”装入 `_forever_`，安装记录含 `"version": "0.2.21"`，包内 TOC `## Version: 0.2.21-dev`；用户确认游戏插件列表显示 0.2.21 | `.localddon-install.log`、`.wowbuddy-install.json` |
| E2 | 通过：14:43:53 点击“安装 GitHub 发布版”弹出降级确认，取消后记录“已取消：客户端已装 v0.2.21，未用较旧的 GitHub 发布版 v0.2.8 覆盖”，插件文件未改 | `.localddon-install.log` |
| E3 | 通过（按修正后的预期）：14:44:24 重启助手，自动检查后插件目录与安装记录修改时间仍为 14:43:59/14:44:00。GitHub 发布内容未变，自动热更未进入重装，因此没有“跳过”日志；该路径由离线 D2 覆盖 | 文件时间戳 |

结论：游戏验收通过。E3 原预期“日志显示跳过”写得不准确，已在第 3 节修正。
