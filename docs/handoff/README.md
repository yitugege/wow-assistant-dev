# 换电脑交接（2026-11-17）

## 1. 搭建

```
git clone https://github.com/yitugege/wow-assistant-dev.git
cd wow-assistant-dev
git checkout dev/loop-grid-20261117
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt     # 含 numpy（格子寻路构建用）
.venv\Scripts\python -m unittest discover -s tests                # 离线自检
.venv\Scripts\python run_dev.py                                    # 启动桌面端
```

- 插件：桌面端“插件管理”安装，或 `python tools/build_addon.py` 后把 `dist/WowBuddyDev-dev.zip` 解到游戏 `Interface/AddOns`。
- MCP（Claude Code 读日志/状态）：仓库根的 `.mcp.json` 已配置，用 `.venv/Scripts/python.exe tools/wowbuddy_mcp.py --data-dir .local`；助手上勾选“允许 MCP 控制”后才能停止监控。

## 2. 本机数据迁移（`.local/` 不进仓库）

- 路线与开关：`docs/handoff/automation-settings.ini` 是旧电脑 `.local/settings.ini` 的 `[automation]` 段（循环路线、商人路线、跑尸路线、格子寻路/边走边找怪/满包继续打怪开关）。新电脑首次启动后关闭助手，把这一段覆盖进 `.local/settings.ini` 再启动。
- 地图格子：`.local/walkgrid/1433.wgrid` 需重新生成（读本机游戏客户端数据）：
  ```
  mkdir .local\walkgrid
  copy docs\handoff\walkgrid-calibration.json .local\walkgrid\calibration.json
  .venv\Scripts\python tools\build_walk_grid.py --map 1433 --game-dir "<新电脑的 WoW 经典服目录>"
  ```
  校准点（UnitPosition 与地图坐标）与游戏安装位置无关，可直接复用。
- 商人绑定是插件存档（SavedVariables），换电脑后要在游戏里选中湖畔镇修理商人重新 `/wbdvendor`。

## 3. 当前状态

- 已验证（游戏内）：格子绕行与格子跑尸、墓地出口路线复用、半圈转向、三方向扫怪、整圈循环（152–255 秒）、复活点等敌上限、商人绑定（10:24:16 select_key=CTRL-[）。
- 未通过：一小时连续循环验收。08:51–09:45 共 55 分钟 9 次死亡，耐久变红后因无商人绑定停住；绑定后补给行程在商人旁仍去走路线起点受阻（L15）。
- 待用户确认的设计（未改代码）：`docs/design/20261117-loop-survival.md`（L13 复活后回满、L14 战斗中目标打不到就换、L15 已在商人旁直接交互）；后台运行验证 `docs/design/20261116-background-run-feasibility.md`（V1–V3）。
- 问题全集与观察日志：`docs/design/20261117-loop-issues.md`（L0–L15）。
- `tests/test_patrol_rejoin.py` 中 L12 复现用例标为 expectedFailure，等设计确认后修。
