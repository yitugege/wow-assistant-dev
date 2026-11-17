# 助手 MCP 接口（日志与状态）

- 编号：20261115-assistant-mcp
- 状态：离线自检通过（2026-11-15），待实际使用验收 N1–N5
- 来源：新需求（2026-11-15，用户：“给助手做一个 MCP 接口，这样你就可以知道助手的日志和状态”）
- 发布版本：不随客户端发布（本机开发工具）

## 1. 背景与分析

- 现在 Claude 只能在用户提醒后用命令读 `.local` 下的文件（`logs\monitor_*.log`、`startup.log`、`addon-install.log`、`settings.ini`、`diagnostics\*.zip`、练级 JSON），每次都要手写解析；看不到“此刻”的状态。
- 实时状态（是否在监控、无人托管阶段、循环路线进度、角色坐标与生命状态、目标与战斗、最近的停发原因、转向统计）只在助手进程内存中，没有落盘。
- 项目中无 `.mcp.json`；`.venv` 未安装 MCP Python SDK。

## 2. 设计

### 目标与非目标

- 目标：Claude Code 通过 MCP 工具读取助手的日志与实时状态，用于游戏验收与问题分析。
- 少量控制（用户 2026-11-15 选定“只读 + 少量控制”）：只开放**让助手停下来或导出**的操作——停止监控、关闭无人托管、导出诊断。
- 非目标：不开放任何会让助手开始发键的操作（开始监控、开启无人托管、发键、录制路线），不改设置、不装插件；不读取游戏内存；不开网络端口、不联网。

### 方案

1. **状态快照（助手侧）**：开发版窗口每秒把当前状态写入 `数据目录/status.json`（先写临时文件再替换，避免读到半份）：
   - `updated_at`、客户端版本、监控中与否、游戏窗口句柄；
   - 无人托管开关、当前阶段（`UnattendedPhase`）、行程目标与是否完成；
   - 循环路线：类型（录制/坐标）、停留点 `k/n`、录制路线点数；
   - 角色：生命状态、地图、坐标、等级、是否战斗中；目标：是否有效、距离、拒绝原因；
   - 最近一次未发键原因、最近 20 行运行日志；转向统计当前段的进度。
   助手退出时写入 `running: false`。
2. **MCP 服务（独立进程）**：`tools/wowbuddy_mcp.py`，stdio 方式运行，由 Claude Code 按项目 `.mcp.json` 启动；只读 `数据目录`（默认 `.local`，可用参数指定）：

| 工具 | 作用 |
|---|---|
| `get_status` | 返回 `status.json`，并标出快照是否过期（超过 5 秒未更新视为助手未运行或卡住） |
| `tail_log(lines=200, contains=None, skip_noise=True)` | 最新监控日志的末尾若干行；可按关键字过滤；默认过滤逐帧字段读数与重复的“未发键”行 |
| `search_log(pattern, since=None, limit=200)` | 在最近的监控日志中按正则查找（可限定起始时间） |
| `list_logs()` | 列出监控日志文件（时间、大小） |
| `get_patrol()` | 当前循环路线摘要（来源设置，只读）与 `status.json` 中的进度 |
| `get_steering_stats(limit=50)` | 日志中的“转向统计”行汇总 |
| `get_addon_install_log(lines=50)` | `addon-install.log` 末尾 |
| `list_diagnostics()` / `read_diagnostics(name, member)` | 列出导出的诊断包，读取其中的清单或指定成员（文本） |

3. **控制通道（文件信箱，不开端口）**：MCP 服务把请求写成 `数据目录/control/inbox/<请求号>.json`（`{"id", "action", "created_at"}`）；助手在同一个 1 秒定时器里取走请求、在主线程执行、把结果写到 `control/outbox/<请求号>.json`，并在运行日志里记一行“MCP 请求：停止监控（已执行）”。MCP 工具最多等 5 秒结果，超时返回“助手未响应”。
   - 只认白名单动作：`stop_monitoring`（监控中才执行，等同点“停止”，会松开移动键）、`stop_unattended`（等同取消勾选“无人托管”，常规监控继续）、`export_diagnostics`（打包到 `diagnostics`，不弹出目录，返回包路径）；其他动作一律拒绝并记日志。
   - 超过 30 秒的旧请求丢弃不执行（避免助手重启后执行过期命令）。
   - 对应 MCP 工具：`stop_monitoring`、`stop_unattended`、`export_diagnostics`。
4. **分析辅助（用户 2026-11-15 追加）**：
   - **保存当前帧** `capture_frame(note)`：经信箱请求，助手把最近一次轮询抓到的图**只裁剪像素条所在区域**（按当前协议几何，不保存整窗画面）存为 `数据目录/frames/<时间>.png`，同时写 `<时间>.json`：解码字段、帧状态、角色状态包、`status.json` 同刻内容、备注。用于把现场直接写成复现测试（`tests/` 合成帧写法）。不受“允许 MCP 控制”开关限制（不改变助手行为），每分钟最多 10 帧，目录最多保留 50 组。
   - **打标记** `mark(text)`：经信箱请求，助手在运行日志写一行 `==== 标记：<text> ====`（带时间），并记入 `status.json` 的 `last_mark`。不受控制开关限制。
   - **等事件** `wait_for(event, timeout_s≤600, pattern=None)`：MCP 服务侧轮询 `status.json` 与日志（每秒一次），事件为 `phase_change`（无人托管阶段变化）、`death`、`stuck`（日志出现受阻/卡住）、`monitor_stopped`、`log`（日志匹配 `pattern`）；返回事件发生时的快照与相关日志行，超时返回最后状态。纯读取。
   - **解释决策** `explain_decision()`：`status.json` 中增加 `decision` 段：最近一帧的帧状态、选中的候选（标签/按键/原因）、全部候选的标签/原因/是否停发、`attack_blocked_by_range`/`attack_blocked_by_sight`/`target_rejection`/`recovery_ready`、生效阈值，以及规则用到的解码字段。只取现有 `Decision` 对象中已有的数据，**不改引擎与规则求值代码**；逐条件级别的求值跟踪不在本次范围。
5. **状态包（追加 2，用户 2026-11-15 确认）**：`status.json` 增加 `packets` 段，每秒用最近一次抓到的帧解一遍插件已发送的签名包：角色状态、导航（朝向/移动/坐标，战斗中也更新）、死亡、交任务标记、任务对话、怪物状态、商人、飞行、目标拒绝、施法回执、经验进度；解不出的为 `null`。不改插件与协议，不进每帧决策路径。解码函数在模块加载时绑定原函数，测试中对 `character_state.decode_*` 的打桩不受影响。`capture_frame` 的 JSON 同样写入 `packets`。`explain_decision` 不变。
6. **隐私**：MCP 返回的内容会进入 Claude 的对话；`status.json` 不写账号名；日志与诊断包按现有方式（诊断包已脱敏，监控日志可能含本机路径）原样返回，工具说明中注明。

### 模块归属

| 文件 | 层 | 内容 |
|---|---|---|
| `desktop/wowbuddy/status_snapshot.py`（新建） | 入口层 | 汇总状态为字典、原子写入 `status.json`（纯逻辑 + 文件写入，不导入 Qt） |
| `desktop/wowbuddy/control_mailbox.py`（新建） | 入口层 | 信箱读写：取请求、丢弃过期、校验白名单、写结果（不导入 Qt；MCP 服务与助手共用） |
| `desktop/wowbuddy/app/dev_window.py` | app | 每秒定时写快照、处理信箱请求（调用已有的 `toggle_monitor`、`_set_unattended`、`diagnostic_export`）；退出时写 `running: false` |
| `desktop/wowbuddy/frame_capture_dump.py`（新建） | 入口层 | 按协议几何裁剪像素条区域并写 PNG + JSON、限频与保留数量（不导入 Qt，PNG 用标准库 zlib 编码） |
| `tools/wowbuddy_mcp.py`（新建） | 工具 | MCP stdio 服务：读数据目录、写信箱、`wait_for` 轮询 |
| `.mcp.json`（新建） | 项目配置 | 注册 `wowbuddy` 服务：`.venv/Scripts/python.exe tools/wowbuddy_mcp.py --data-dir .local` |
| `requirements-dev.txt` | 依赖 | 增加 MCP Python SDK（`mcp`，固定版本） |

### 开关与回退

读取部分不影响助手行为。控制部分在开发版菜单加开关“允许 MCP 控制”（`settings` 保存，默认**关闭**）：关闭时助手不读信箱，MCP 控制工具返回“助手未允许控制”。不需要时从 `.mcp.json` 删除即可。`status.json` 写入或信箱处理失败只记一次日志，不影响监控。

### 风险

- 每秒写一次小 JSON，开销可忽略；需确认在监控高频循环中不阻塞（放在独立的 1 秒定时器里）。
- 首次使用时 Claude Code 会询问是否信任项目的 MCP 服务，需要用户同意。
- MCP SDK 需要下载安装到 `.venv`（用户已选官方 SDK）。
- 控制请求在主线程执行，与用户点击同路径；停止监控时须松开移动键（沿用 `toggle_monitor` 现有处理）。信箱目录在数据目录内，只有本机进程能写。

## 3. 验收标准

### 离线

| 编号 | 检查 | 预期 |
|---|---|---|
| M1 | 状态快照 | 由给定的窗口状态生成的字典字段齐全、可 JSON 序列化；原子写入；退出时 `running: false`；不含账号名 |
| M2 | 窗口定时写入 | 离屏窗口启动后 `status.json` 每秒更新；关闭后为 `running: false` |
| M3 | MCP 工具 | 用临时数据目录直接调用各工具函数：过期判断、日志尾部与过滤、正则查找与时间起点、循环路线摘要、转向统计汇总、诊断包读取；数据目录外的路径被拒绝 |
| M6 | 控制信箱 | 白名单动作执行并写结果、未知动作拒绝、过期请求丢弃、开关关闭时不处理；窗口测试中 `stop_monitoring` 使监控停止、`stop_unattended` 取消无人托管、`export_diagnostics` 生成包且不弹目录 |
| M7 | 保存当前帧 | 合成帧经 `capture_frame` 写出 PNG 只含像素条区域，JSON 含解码字段；把写出的 PNG 重新解码得到相同字段；限频与保留上限生效；无有效帧时返回原因 |
| M8 | 打标记 / 等事件 | 标记写入日志与 `last_mark`；`wait_for` 在临时目录中对阶段变化、死亡、日志匹配各触发一次，超时返回最后状态 |
| M9 | 解释决策 | 窗口测试中 `status.json` 的 `decision` 段与当帧 `Decision` 一致（选中候选、停发原因、拦截标记） |
| M10 | 状态包 | 合成帧上 `packets` 各段可序列化、角色与导航读数正确；打桩 `character_state.decode_character_state` 后快照仍用原函数（打桩未被调用）；窗口快照与 `capture_frame` JSON 含 `packets` |
| M4 | MCP 协议 | 以 stdio 启动服务，完成初始化并列出全部工具（协议层冒烟测试） |
| M5 | 回归 | 全量测试 0 失败；分层检查通过 |

### 实际使用（用户与 Claude）

| 步骤 | 操作 | 预期 |
|---|---|---|
| N1 | 用户批准 `.mcp.json` 中的 `wowbuddy` 服务，启动助手并开始监控 | Claude 调用 `get_status` 能看到实时阶段、循环进度、角色坐标 |
| N3 | 打开“允许 MCP 控制”，挂机时让 Claude 调用 `stop_monitoring` | 助手停止监控、角色停下，日志有“MCP 请求：停止监控（已执行）”；关闭开关后再调用返回“未允许控制” |
| N4 | 挂机时遇到问题，用户说“存一帧” | Claude 调用 `capture_frame`，`frames/` 下出现 PNG+JSON，并能据此写出离线复现测试 |
| N5 | 用户让 Claude 等下一次死亡或卡住 | `wait_for` 在事件发生后返回，Claude 直接给出当时的状态与日志 |
| N2 | 挂机过程中 | Claude 用 `tail_log`/`search_log`/`get_steering_stats` 直接分析，不再需要用户导出诊断 |

## 4. 实现记录

- MCP SDK：`mcp==2.3.0`（2.x 中 FastMCP 改名为 `mcp.server.mcpserver.MCPServer`），已装入 `.venv` 并写入 `requirements-dev.txt`。
- 新文件：`desktop/wowbuddy/status_snapshot.py`、`control_mailbox.py`、`frame_capture_dump.py`，`tools/wowbuddy_mcp.py`（工具逻辑在 `AssistantTools`，`build_server` 只做注册），`.mcp.json`，`tests/test_assistant_mcp.py`（19 项）。
- 改动：`app/dev_window.py`（`_install_mcp_status`、`_status_tick`、`_run_mcp_request`、`_status_document`、`_stop_mcp_status`；`poll_once` 中记住最近一次角色/生命读数）；`settings.py`（`dev/mcpControl`）；`automation/steering_stats.py`（`progress()`）。
- 与设计的差异：
  - “允许 MCP 控制”做成日志卡片“导出诊断”按钮下的勾选框，不放菜单。
  - 角色坐标只在脱战并开启练级/无人托管规划时才有读数（沿用 `route_character`，不在定时器里额外解码，避免干扰测试中对 `decode_*` 的打桩）；`character.at` 标出读数时间。
  - `get_patrol` 只读 `status.json` 中的路线摘要（含停留点坐标），不直接读 QSettings。
  - 像素条裁剪宽度为 `锚点 + 3 格 + 2` 像素（合成帧 1 倍缩放下 18 像素）。
  - 自检/`--dump-ui` 模式不启动状态定时器。

## 5. 离线自检结果

| 编号 | 命令 | 结果 |
|---|---|---|
| 先行 | `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest discover -s tests -p test_assistant_mcp.py`（实现前） | 失败（模块不存在），符合预期 |
| M1–M9 | 同上（实现后） | 19 项通过 |
| M4 | 其中 `test_m4_stdio_lists_tools`：子进程 stdio 启动服务、初始化、列出 16 个工具、调用 `get_status` | 通过 |
| M5 | `.venv/Scripts/python.exe -m unittest discover -s tests` | 840 项，0 失败，187 跳过（含分层与拆分检查） |
| 依赖 | `python tools/addon_module_deps.py` | 78 个模块，0 处不一致 |
| M10 | `test_assistant_mcp.py`（追加 3 项及窗口断言） | 22 项通过；全量 843 项 0 失败、187 跳过；依赖 78 模块 0 不一致 |
| 实数据 | 对真实 `.local` 调用 `list_logs`、`tail_log`、`get_steering_stats`、`list_diagnostics` | 正常返回；`get_status` 返回“没有 status.json”（运行中的助手是旧进程） |

## 6. 验收结果

| 步骤 | 时间 | 结果 |
|---|---|---|
| N1 | 2026-11-15 18:42 | 通过：`get_status` 读到监控中、录制路线第 3/12 点、角色 24 级赤脊山 (31.67, 29.32)、最近决策（距离 32.5 码、`attack_blocked_by_range`）。附带验证：Claude Code 重启后旧助手进程被一并结束，快照正确显示 `stale: true`。追加 2（状态包）需重启助手后验收。 |

结论：
