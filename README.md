# WOW助手独立开发工程

自有桌面助手与 WoW 插件的开发仓库。原 EXE 与 `D:/reverse-analysis/wow-assistant` 只作参考，不在其中开发。公开仓库：https://github.com/yitugege/wow-assistant-dev

完整的历史说明（各命令细节、协议修复、诊断入口）见 [docs/HISTORY.md](docs/HISTORY.md)，全部专题记录见 [docs/INDEX.md](docs/INDEX.md)。

## 当前状态

- 公开开发测试版：[v0.2.8](https://github.com/yitugege/wow-assistant-dev/releases/tag/v0.2.8)，说明见 [docs/RELEASE-0.2.8.md](docs/RELEASE-0.2.8.md)。
- **游戏内验收尚未完成。** 构建自检、离线测试与游戏实测分开报告；自动施法、自动换目标、无人托管等功能需要游戏内证据，不以窗口能启动或测试通过代替。
- 受保护操作弹窗尚未在游戏中确认消失；插件 `SecurityDiagnostics.lua` 记录 ADDON_ACTION_BLOCKED/FORBIDDEN 到 `WowBuddyDevDiagnostics`。
- 2026-11-15 起桌面源码按层拆分（见下节）；拆分后的完整测试集尚未运行。

## 目录结构

```
run_dev.py                 桌面入口：参数解析、后端选择、构造主窗口
run_outer_dev.py           自有外层入口
desktop/wowbuddy/
  core/                    纯决策与协议（表达式、候选、像素协议、几何、按键解析）；不导入 Qt/ctypes 或其他子层
  win32/                   窗口枚举、抓屏、按键与鼠标发送
  engine/                  决策引擎编排：管线、方案控制器、调度、发送、监控会话、阈值、资源加载
  automation/              无人托管：路线、导航、复活、补给；unattended.py 持有全部行程状态、判定阶段并产出每帧动作，
                           unattended_phases.py 为复活/补给/练级阶段处理器（经窗口 host 收发按键与写日志）
  update/                  客户端/插件/外层的 GitHub 更新检查、下载校验与交接安装
  legacy/                  原版外层与保护线程的还原对照（自有外层入口仍在使用，不再扩展）
  selftest/                引擎自检组；fixtures/ 为其合成输入（打包版 --selftest/--engine-selftest 运行时使用）
  addons/                  插件安装与识别：游戏目录检测、校验安装、热安装、旧插件清理、命令行安装
  app/                     Qt 应用层：基础主窗口 qt_app、独立开发版主窗口 dev_window 与界面部件
  *.py                     入口层：启动与崩溃取证、命令行/诊断入口、循环库同步、设置、日志与 Qt 辅助
addon/WowBuddyDev/         插件源码（TOC 为加载顺序与打包白名单）
  Modules.lua              模块注册表（TOC 第一个加载）：每个文件经 Namespace(名, 使用的模块) 取得命名空间；
                           RegisterModule/Require/ModuleExports 声明并检查加载期依赖、传递内部函数；
                           视图默认检查跨模块读写是否在声明范围内（越界只记入 moduleErrors，不拦截）
  CoreSettings.lua         存档初始化/迁移、用户宏存储、爆发自动关闭设置
  CoreState.lua            冷却、消耗品、饰品与施法成功记录的共享状态表 coreState（原 Core.lua 文件级 local）
  CoreCooldownLedger.lua   持久化冷却账本、爆发药水冷却、充能记录与恢复
  CoreConsumables.lua      物品冷却、消耗品反查表与消耗品剩余冷却
  CoreClassData.lua        按专精装载职业模块数据
  Core.lua                 技能冷却查询、施法成功事件、天赋冷却门控、饰品与 GCD、扩展数值规则
  CoreCastState.lua        读条/引导/施法成功代次与蓄力状态
  CoreLocale.lua           技能名本地化、默认宏、错误日志
  CoreEvents.lua           专精识别与切换、施法失败配对、核心事件注册与分发、登录初始化
  CoreControls.lua         控制键冲突、按键检测、开关命令
  CoreMovement.lua         移动键位方案与 isMoving 编码
  CoreDiagnostics.lua      /pmstest 诊断输出
assets/                    协议契约、规则 JSON、离线循环库快照
tests/  tools/  docs/      测试、构建与审计脚本、文档
```

分层约束由 `tests/test_layer_boundaries.py` 静态检查：`core` 只能导入自身，`automation` 不导入 Qt，`app` 以外的子包都不导入 `app`。

Core.lua 拆分文件按原语句顺序排在 TOC 中；`tests/addon_sources.py` 按 `-- @@拆分：X.lua@@` 标记把它们拼回原 Core.lua 文本（`coreState.X` 还原为原 local），供与原版插件逐段对照的测试使用，`tests/test_core_split.py` 校验拆分结构。

## 环境

Windows + Python（已验证环境见 requirements 文件中的版本）：

```
python -m pip install -r requirements.txt        # 运行
python -m pip install -r requirements-dev.txt    # 测试与构建（lupa、PyInstaller）
```

## 运行

```
python run_dev.py                 # 正常启动，默认自动监视游戏窗口
python run_dev.py --no-watch      # 只手动操作
python run_dev.py --data-dir=D:/某目录   # 独立设置与日志目录（默认 .local）
```

## 构建

| 命令 | 产物 |
|---|---|
| `python tools/build_addon.py` | `dist/WowBuddyDev-dev.zip`，固定目录名，离线开发用 |
| `python tools/build_github_release.py` | `dist/release/WowBuddyDev-addon.zip` 与 `.manifest.json`，公开发布用 |
| `python tools/build_desktop.py` | `dist/desktop/WowBuddyDev/`（目录版，需保留 `_internal` 与 `packages`），结束时自动运行冻结自检 |

插件打包只收录 TOC 引用的文件和被引用的资源（贴图、音效），见 `tools/build_addon.py`。

## 测试

```
python -m unittest discover -s tests -v    # 全部测试（Lua 部分需要 lupa）
python tools/test_core.py                  # 核心行为回归，结果写 dist/core-tests.json
python run_dev.py --desktop-selftest       # 离屏 GUI 构造/关闭检查
python run_dev.py --engine-selftest        # 原引擎自检组（严格返回码）
```

这些检查都不抓屏、不向游戏发键，通过不代表游戏内功能可用。

## 约定

- 不重新接入旧更新服务；客户端、插件与循环库只从本仓库 GitHub Releases/仓库更新。
- 未经明确要求不提交、不推送。
