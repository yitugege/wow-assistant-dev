# 朝向错误后未转向、跑尸各方向受阻（2026-11-15 18:47 死亡）

- 编号：20261115-combat-facing-silent
- 状态：离线自检通过（2026-11-15），待游戏验收 G1–G2
- 来源：游戏内问题（2026-11-15 18:47–18:59，Claude 经 MCP 观察）
- 发布版本：

## 1. 问题记录与分析

### 现象

1. 18:47:36 在录制循环路线第 5 个停留点附近同时拉到多只怪，`active_enemies` 几秒内到 4。
2. 18:47:37–47 奥术冲击（400574）连续 5 次“提交、失败，同期游戏报错 朝向（编号 57）”，期间日志中**没有任何**朝向处理记录（既没有“收到技能 … 朝向错误，按目标方位转向”，也没有“本帧未取得同一目标且角色站定的转向读数”“朝向回执未匹配…”）。约 10 秒输出无效。
3. 魔爆术（8437）施法回执一秒内多次“失败”，但日志中没有桌面端发送魔爆术的记录（来源待查，见下文 Q2）。
4. 18:48:10 死亡，18:48:13 自动释放灵魂。灵魂在墓地 (23.2, 45.4)，尸体 (30.5, 28.2)，约 270 码。
5. 18:48:46 起跑尸：直行受阻 → 两侧绕行 → “绕行各可用方向均受阻” → 改去“尸体附近的备选接入点”同样受阻，反复至 18:51:55“备选接入点已试完，等待游戏开放复活”，之后停在墓地不动（至 18:59 仍为灵魂）。
6. 同期多次“等待游戏画面更新 / 游戏画面已更新，恢复监控”（18:50:37、18:51:50、18:52:26、18:57:59）。

### 证据

- 监控日志：`.local/logs/monitor_20261115_184359.log`（18:47:30–18:59，含 18:49:17 标记行）。
- 现场帧：`.local/frames/20261115-184916-166.png` + `.json`（灵魂跑尸受阻时）。
- MCP 快照：18:49 与 18:59 的 `status.json`（`packets.death.corpse = [1433, 30.48, 28.24]`，`packets.navigation` 灵魂位置与朝向）。

### 根因分析（读代码）

- 朝向处理在 `DevWindow._observe_combat_feedback`（`app/dev_window.py`）：施法回执已正常记录（说明函数执行到了），随后
  `decode_combat_facing` 取得读数 → `CombatFacing.observe` → `ForegroundMovement.pulse`（`automation/navigation.py`）。
- `pulse` 在 `can_input` 为假时直接返回 `False`：要求**游戏窗口在前台**，且用户没有按住 `W A S D Q E`、方向键、鼠标键或 Shift/Ctrl/Alt（`_MANUAL_KEYS`）。`_observe_combat_feedback` 拿到 `False` 后静默返回，不写日志。
- 现象 2 的“完全无日志”只与这一条静默路径相符（其余分支都会写日志），因此判断：**当时转向键未能发出，最可能是游戏窗口不在前台**。
- 结论（E1 已由用户证实：当时在看 Claude 前端）：
  - **根因**：转向键要求游戏在前台；`CombatFacing.observe` 直接调用 `pulse`，前台条件不满足时返回假，`_observe_combat_feedback` 静默返回。
  - **表现处**：日志不提任何原因，看起来像“没有转向逻辑”。
- 跑尸（现象 5）**不能直接归为同一原因**：`MapNavigator.observe` 每次脉冲前先查 `can_input`，不在前台时只暂停、不计受阻（`test_leveling_route` 已有用例）。现象 5 另立分析（复活后结合“尸体靠近录制路线时先接轨迹”的设计一起做）。

### 尚缺的证据（需用户补采）

- E1：已答复——游戏不在前台，用户在 Claude 前端。
- Q2：已答复——魔爆术 8437 为用户手动按键，非缺陷。

### 复现用例

- 离线测试：`tests/test_combat_facing_silent.py`（4 项）：`ForegroundMovement.blocked_reason` 给出“游戏不在前台 / 检测到手动按键”，成功后清空；窗口中朝向回执 + 转向失败时写一次“朝向错误未能转向：游戏不在前台…”。
- 修复前运行结果：4 项失败（3 项 `AttributeError: 'ForegroundMovement' object has no attribute 'blocked_reason'`，窗口用例日志中没有提示）。

## 2. 设计

### 目标与非目标

- 目标（本次，第 1 步）：前台移动（转向、导航、跑尸、后退）因条件不满足而发不出时，**说出原因**；MCP 状态中可见。
- 非目标（本次不做，另立设计）：不在前台时暂停无人托管（方案 A，改变行为，需开关）；不依赖前台的面向方式（方案 B，需游戏内先验证可行性）；跑尸受阻（见上）。
- 保持不变：何时转向、转几次、导航何时暂停，全部不变。

### 方案

1. `ForegroundMovement` 记录最近一次拒绝原因 `blocked_reason`：`游戏不在前台`、`检测到手动按键`、`游戏窗口无效`、`不是游戏进程`；成功发键后清空。只加记录，不改判断。
2. `_observe_combat_feedback`：`CombatFacing.observe` 返回假且移动器有 `blocked_reason` 时，每条回执写一次“朝向错误未能转向：{原因}（转向需要游戏窗口在最前面、且不按移动键）。”
3. 状态快照增加 `input_block`：`{reason, at}`（最近一次拒绝原因与时间），MCP `get_status` 可见；导航、跑尸也可据此判断“暂停是因为不在前台”。

### 模块归属

| 文件 | 层 | 新建/修改 | 内容 |
|---|---|---|---|
| `automation/navigation.py` | automation | 修改 | `ForegroundMovement._can_input` 记下拒绝原因 |
| `app/dev_window.py` | app | 修改 | 朝向失败日志；快照写 `input_block` |
| `status_snapshot.py` | 入口层 | 修改 | `build_status` 增加 `input_block` |
| `tests/test_combat_facing_silent.py` | 测试 | 新建 | 复现用例（已写，修复前失败） |

### 客户端界面

无（只有日志文字）。

### 开关与回退

不改变行为，不需要开关。

### 风险

`_can_input` 在每帧导航路径上：只多一次属性赋值，开销可忽略。`test_leveling_route` 中大量对 `ForegroundMovement` 的用例须保持通过。

## 3. 验收标准

| 编号 | 检查 | 预期 |
|---|---|---|
| F1 | `test_combat_facing_silent.py` | 4 项由失败转为通过 |
| F2 | 全量测试、分层检查 | 0 失败 |
| G1（游戏） | 无人托管打怪时切到其他窗口，遇到朝向错误 | 日志出现“朝向错误未能转向：游戏不在前台…”；`get_status` 的 `input_block.reason` 为“游戏不在前台” |
| G2（游戏） | 游戏在前台时遇到朝向错误 | 照常“按目标方位转向”，无新提示 |

## 4. 实现记录

- 设计于 2026-11-15 经用户确认。
- `ForegroundMovement._can_input` 拆出 `_input_block`，按原判断顺序返回原因；判断结果与原实现一致，只多记 `blocked_reason`/`blocked_at`。
- `_observe_combat_feedback`：转向失败且为新的朝向回执时写原因日志。
- 状态快照 `input_block = {reason, seconds_ago, at}`（取自导航与战斗共用的移动器）。
- 无偏离设计。

## 5. 离线自检结果

| 编号 | 命令 | 结果 |
|---|---|---|
| 复现 | `.venv/Scripts/python.exe -m unittest discover -s tests -p test_combat_facing_silent.py`（修复前） | 4 项失败 |
| F1 | 同上（修复后） | 4 项通过 |
| F2 | `.venv/Scripts/python.exe -m unittest discover -s tests`；`tools/addon_module_deps.py` | 848 项 0 失败、187 跳过；78 模块 0 不一致 |

## 6. 验收结果

结论：
