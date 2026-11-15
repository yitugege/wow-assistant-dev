# 无人托管营地交接测试：释放灵魂后跑尸路线未建立

- 编号：20261115-corpse-start-wait
- 状态：离线自检通过（2026-11-15，方案 A + B2）；游戏验收 H1、H2 待用户执行
- 来源：离线测试失败（2026-11-15 全量基线发现；HEAD `bc8e450` 上同样失败，与本次重构无关）
- 发布版本：（发布后填写）

## 1. 问题记录与分析

- 现象：`tests/test_dev_monitor_protocol.py` 中 4 个用例失败，全部停在共用流程 `_exercise_unattended_camp_handoff` 第 259 行 `self.assertIsNotNone(window._corpse_trip)`：
  - `test_unattended_combat_recovery_revival_and_level_change_share_one_session`
  - `test_unattended_death_on_final_approach_counts_before_camp_arrival`
  - `test_unattended_level_44_leaves_cooled_camp_without_level_change`
  - `test_unattended_repeated_deaths_leave_camp_after_revival`
- 出现条件与复现步骤：`.venv` 中运行 `python -m unittest discover -s tests -p "test_dev_monitor_protocol.py"`；在 HEAD 的临时 worktree 中结果相同。
- 证据（只读诊断脚本包裹相关方法后运行其中一个用例，未改仓库代码）：
  - 释放灵魂后的第一帧：`decode_death_state` 返回 `life='ghost'`、`corpse=(1435, 27.1, 56.7)`、`button=None`、`popup='missing'`；`decode_navigation_state` 返回同图鬼魂定位。
  - 该帧 `_corpse_route`、`_observe_local_access`、`_start_recorded_corpse_trip` 均未被调用；`_corpse_trail.waiting_for_start` 为 `True`；界面提示为“等待释放灵魂后的墓地地图与坐标稳定。”
  - 模拟游戏的定位包序号逐帧递增（2…22），稳定判定可以在后续帧完成。
- 根因：`app/dev_window._poll_navigation`（第 1539 行）在鬼魂状态下先检查 `death.button is None and self._corpse_trail.waiting_for_start`，成立时只松开移动键并返回。`CorpseTrail.waiting_for_start`（`automation/death_recovery.py`）要求释放灵魂后的位置在同一地图、移动不超过 25 码、连续 `_CORPSE_START_STABLE_MS = 1200` 毫秒后才确认起点。测试在释放灵魂后只走了一帧（0.35 秒）就断言跑尸路线已建立。
  - 等待逻辑与这条断言是同一次提交 `260fea2`（2026-11-14，“跨图跑尸录制”）引入的，属于同一次改动内部的不一致：实现加入了起点稳定等待，测试仍按“释放后立即跑尸”编写。
  - 这个等待**不看**“录制跑尸路线”开关（`waiting_for_start` 不判断 `enabled`），默认设置下录制关闭（`automation/recordCorpseTrail` 默认 `False`），等待仍会生效。所以“测试过时”与“实现过度等待”两种解释都说得通，文档中没有写明这个等待的意图。

### 复现用例

- 离线测试：现有 4 个用例即复现用例。
- 修复前运行结果：失败（`AssertionError: unexpectedly None`，第 259 行）。

## 2. 设计

两个方案，**需要用户选择**（取决于“释放灵魂后先等约 1.2 秒再跑尸”是否是想要的游戏行为）：

### 方案 A（推荐）：保留等待，修正测试

- 理由：等待的界面提示写的是“墓地地图与坐标稳定”，不只是为录制服务；释放灵魂后客户端加载墓地时坐标可能短暂不稳，等待能避免按旧坐标规划路线。保持现有游戏行为，风险最低。
- 改动：只改 `tests/test_dev_monitor_protocol.py` 第 256–259 行附近：
  - 释放灵魂后的第一帧断言界面提示为“等待释放灵魂后的墓地地图与坐标稳定。”且未按前进（为这个等待补上测试覆盖）；
  - 之后最多轮询 8 帧（每帧 0.35 秒，约 2.8 秒），直到 `window._corpse_trip` 建立，再继续原有断言。
- 不改任何产品代码。

### 方案 B：等待只在录制开启时生效

- 理由：等待的目的若只是给录制提供干净起点，录制关闭时不必延迟跑尸。
- 改动：`app/dev_window._poll_navigation` 第 1539 行条件改为同时要求录制开关开启（`self._record_corpse_action.isChecked()`）；新增用例覆盖“录制开启时等待、关闭时立即跑尸”；4 个现有用例无需修改即通过。
- 风险：若等待实际上也在保护导航免受墓地加载期坐标影响，录制关闭时会失去这层保护，需要游戏实测确认。

### 模块归属

| 文件 | 层 | 方案 | 内容 |
|---|---|---|---|
| `tests/test_dev_monitor_protocol.py` | 测试 | A | 第一帧断言等待提示，随后有界轮询直到跑尸路线建立 |
| `desktop/wowbuddy/app/dev_window.py` | app | B | 等待条件增加录制开关判断 |
| `tests/test_dev_monitor_protocol.py` 或新测试 | 测试 | B | 录制开/关两种情况的等待行为 |

### 客户端界面

无变化（方案 A、B 都不改控件；提示文字沿用）。

### 开关与回退

- 方案 A：不改行为，无需开关。
- 方案 B：行为由已有的“录制跑尸路线”开关控制；关闭即为新行为，开启即为旧行为。

### 风险

- 方案 A：无产品行为变化；只要游戏中这 1.2 秒等待可接受即可。
- 方案 B：见上。

## 3. 验收标准

### 离线

| 编号 | 检查 | 命令 | 预期 |
|---|---|---|---|
| C1 | 4 个用例 | `python -m unittest discover -s tests -p "test_dev_monitor_protocol.py" -v` | 10 个用例全部通过 |
| C2 | 等待行为覆盖 | 同上 | A：释放灵魂后第一帧出现等待提示且不前进，约 1.2 秒内建立跑尸路线；B：录制开启时等待、关闭时第一帧即建立跑尸路线 |
| C3 | 回归 | `python -m unittest discover -s tests` | 0 个失败（基线中的 4 个失败消失），跳过数与基线相同 |

### 游戏内（用户执行）

| 步骤 | 操作 | 预期结果 | 需回传的证据 |
|---|---|---|---|
| H1 | 无人托管下让角色死亡并释放灵魂（录制开关保持默认关闭） | 约 1–2 秒内提示“等待释放灵魂后的墓地地图与坐标稳定”，随后开始跑向尸体，不朝错误方向起跑 | 运行日志或导出的诊断包 |
| H2 | 无人托管下在有不同等级普通怪的区域打怪 | 不因等级差放弃普通怪；灰名、精英、已被占有、玩家目标仍放弃 | 运行日志或导出的诊断包 |

## 2b. 第二个根因（实现方案 A 后发现）

- 现象：按方案 A 修正第 256–259 行后，4 个用例都越过原断言，在第 499 行失败：`self.assertIn('低 4 级', rejected.decision.target_rejection)` 得到 `None`。第 259 行之后的测试从提交 `260fea2` 以来从未真正执行过。
- 证据与根因：同一提交内插件、桌面端与测试对“目标等级”规则不一致：
  - 插件 `CharacterState.lua:1331`：目标等级不等于“角色等级 − 4”时上报拒绝原因 5；
  - 桌面 `engine/character_state.decode_target_rejection`（第 519 行注释“旧插件仍可能报告 5（等级差不等于四级），由客户端忽略”）忽略原因 5，返回 `None`；
  - 测试期望原因 5 生效：目标为角色等级 −5、−3、骷髅（−1）时都拒绝且不选技能，正好低 4 级时才攻击。
- 只读探查（临时脚本让解码器把原因 5 显示为含“低 4 级”的提示，不改仓库代码）：4 个用例全部通过，说明这是剩下的唯一不一致。
- 当前游戏行为：桌面端忽略原因 5，因此无人托管会攻击任何等级的非精英、非灰名普通怪。

需要用户选择：

- **方案 B1：启用“只打低 4 级”规则**：`decode_target_rejection` 把原因 5 显示为“当前怪物不是比角色低 4 级”，测试不改即通过。游戏行为变化：无人托管只攻击比角色正好低 4 级的怪，其余等级一律放弃（与插件现有意图一致，但非常严格）。
- **方案 B2：放弃这条规则**：插件删去原因 5（`CharacterState.lua:1330–1331`），测试第 496–502 行改为“任意等级的普通怪都会攻击”。游戏行为与现在相同；插件端少发一个无用的原因码。

用户选择 **B2**（2026-11-15）。佐证：`tests/test_leveling_route.py` 已有 `test_unattended_target_selection_ignores_legacy_four_level_rejection`，把该规则视为旧规则并要求忽略，监控测试这一段未随之更新。
风险：任意等级包括 `??`（`UnitLevel` 为 −1，远高于角色）的普通怪也会攻击；这与改动前的游戏行为相同（桌面端本来就忽略原因 5）。灰名（`UnitIsTrivial`）、精英/世界首领（脱战时）、已被占有、玩家控制目标仍会拒绝。

## 4. 实现记录

- 方案 B2 已实施：插件 `CharacterState.lua` 的 `targetRejection()` 删去原因 5 分支；`engine/character_state.decode_target_rejection` 仍忽略旧插件可能发来的 5，仅更新注释；`tests/test_dev_monitor_protocol.py` 第 496 行起改为对 −5、−3、??、−4 级目标都断言无拒绝且选择 `spell_116`。
- 方案 A 已实施：`tests/test_dev_monitor_protocol.py` 释放灵魂后第一帧断言等待提示、`_corpse_trip` 为空且未前进，再最多轮询 8 帧直到跑尸路线建立。实施后 4 个用例越过第 259 行，转而在第 499 行失败（见 2b）。

## 5. 离线自检结果

- 运行环境：项目 `.venv`（Python 3.13.13、PySide6 6.10.3、lupa 2.8），`QT_QPA_PLATFORM=offscreen`。

| 编号 | 命令 | 结果 |
|---|---|---|
| 复现 | `python -m unittest discover -s tests -p "test_dev_monitor_protocol.py"` | 修复前 4 个失败（第 259 行）；仅实施 A 后 4 个失败移到第 499 行；只读探查脚本让原因 5 生效时 4 个全部通过（证明只剩这一处不一致） |
| C1、C2 | 同上 | A + B2 后 10 个用例全部通过：释放灵魂后第一帧出现等待提示、未前进，随后建立跑尸路线；各等级普通怪均被攻击 |
| C2 | `python -m unittest discover -s tests -p "test_leveling_route.py"` | 235 个通过（含忽略旧四级规则的用例） |
| C3 | `python -m unittest discover -s tests` | 778 个测试 0 失败，跳过 187 个（与基线相同） |
| 结构 | `test_core_split.py`、`tools/addon_module_deps.py` | 通过；78 个模块 0 处不一致 |

## 6. 游戏验收结果

结论：
