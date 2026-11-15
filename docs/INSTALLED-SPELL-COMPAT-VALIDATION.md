# 技能名称兼容修复本机安装

已在游戏未运行时，将7b0eaa1产品源码对应的随机命名插件包安装到现有 `_forever_/Interface/AddOns/WowBuddyDev`。包同时含技能名称查询和圣印回显修复。没有执行用户取消的 `/dump type(GetSpellInfo)` 查询，也没有改变客户端权限或启动游戏。

## 安装证据

- 包：`dist/spell-name-compat/WowBuddyDev-addon.zip`；SHA256 `6621922b4e04337b1408ee07cdc397d87e23b009365809ef4fd143baeedbaf90`。
- 安装前再次检查Wow、WowB、WowClassic、WowClassicB均未运行，AddOns只有已有WowBuddyDev目录。核对包摘要和逐文件摘要，66个Lua文件通过Lua5.1编译后才安装。
- 保留现有插件目录身份及同名TOC，内部Lua文件仍来自随机命名包。安装后85文件逐一与包比较一致，TOC仅按安装身份改名。
- 原插件85文件备份到游戏客户端 `WowBuddyDev-backups/20261107T142053Z-fd1841d94eec455b9ce464ac3aa43eab`，逐文件摘要一致；没有清理其他插件目录。
- WTF目录72个文件的路径及内容摘要安装前后完全一致。未修改游戏启用状态或保存变量。
- 完整安装结果保存在本机 `.local/install-spell-name-compat.json`，不公开用户配置内容。

## 安装内容离线验证

从实际安装目录读取随机Lua文件与TOC，在既有显式Lua测试宿主中加载64个条目，执行ADDON_LOADED、PLAYER_LOGIN、PLAYER_ENTERING_WORLD及7个单次延时回调；法师职业宏和独立自动选怪键检查通过。报告 `.local/installed-compat-load.json`。

首次命令行验证因PowerShell引号导致Python解析失败，未运行插件代码；随后改用本地脚本并成功完成上述检查。没有把失败命令算作验证通过。

## 限制

## 2026-11-07 实际单发测试补充

用户进入角色并授权测试后，在已选中敌方目标、目标满血272且角色满法力733的状态下，通过游戏聊天输入框执行一次 `/dc test class_NUMPAD5`。

- 日志显示 `[DirectCast] 测试 class_numpad5: true spellID=837`。本次已取得技能ID，未再出现先前的 no-slot 提示；没有运行用户取消的脚本查询，原生技能查询接口是否存在仍未确定。
- 同时出现 `[WowBuddyDev] 客户端拦截: UNKNOWN()（已记录诊断）`，以及游戏弹窗“WowBuddyDev已被禁用，因为该功能只对暴雪的UI开放”。未操作弹窗按钮。
- 观察时没有施法读条，目标血量和角色法力未改变。返回 true 不能解释为施法成功；此路径的实际受保护操作测试未通过。UNKNOWN 也不足以确定具体被拦截的 API。
- 自动施法、自动换怪仍未通过实际验收。下一步应检查诊断与安全执行路径，不能通过改名或忽略弹窗认定修复。

同期对 b7213a6 执行顶层回归：372项中371项通过、1项失败，耗时212.508秒。失败仍为真实PrintWindow验证窗口超出屏幕：1484/readable帧高1082、可用高1032、DPR 1。核心测试在正确加入desktop导入路径后153项全部通过，耗时1.548秒；首次漏加导入路径造成的12项ImportError属于测试启动错误。日志仅存本机 `.local/regression-b7213a6.log` 和 `.local/regression-core-b7213a6-corrected.log`。

以下为安装时记录，现场结果以上述补充为准。

### 原程序对照：返回成功与客户端拦截并存

`tests/test_direct_cast_actions.py::test_forbidden_event_without_lua_error_does_not_prove_cast` 从摘要核验的原 addon.bin 加载完整 DirectCast.lua，与独立模块执行相同调用。在无可用槽位的替身环境中，CastSpellByID 发出 ADDON_ACTION_FORBIDDEN / UNKNOWN()，随后分别正常返回 nil 或 false；两版均返回 `(true, 116)`，诊断仍记录拦截，未执行任何真实施法。8项施法与诊断相关测试通过（1.328秒）。该结果证明原返回值语义也存在相同局限，不证明原插件在当前游戏能施法。

独立版现场输出数字 spellID=837 对应 DirectCastActions.lua 的 CastSpellByID 分支：在它之前没有任何槽位调用以 pcall 成功而提前返回。但这不足以把 UNKNOWN() 唯一归因于该 API，因为此前的查询、自动占槽和手动槽位分支也可能执行。需要事件堆栈等现场证据，不能仅凭弹窗推断具体 API，更不能把修复日志当成修复施法。

### 后续源码诊断增强（尚未安装）

本机保存变量中的 WowBuddyDevDiagnostics 仍为 nil，已请求用户自行处理弹窗并重载，以保存当前内存中的诊断。没有主动接受安全提示。

DirectCastActions 的查询空槽、拾取技能、放置技能、使用动作和按ID施法调用现在保存同步调用上下文，客户端拦截事件额外记录 directCastContext；保留 operation 原值，不以本地上下文覆盖 UNKNOWN()。调用正常返回或抛错后均恢复先前上下文。此信息只适用于同步到达的事件，不涵盖所有模块，也不证明具体API是安全机制判定的根源。

13项动作原版对照、完整插件接入和诊断测试通过；原调用顺序及返回值仍一致。此改动仅增强诊断，未修复施法权限，未安装到正在运行的游戏，现有EXE和发布包不包含该改动。

### 已取得保存后的实际堆栈

后续只读检查发现保存变量已更新。提取的单条拦截记录见 `evidence/directcast-forbidden-20261107.json`，不包含账号配置或聊天内容。事件为 ADDON_ACTION_FORBIDDEN，operation仍为UNKNOWN()，inCombat=false；堆栈指向实际安装的随机Lua文件第73行，再回到第83行的命令处理器。逐字节核对该文件与此前安装ZIP的唯一对应成员后，第73行确认为 `pcall(CastSpellByID, sid, unit)`。因此本次命令执行的拦截已经定位到该调用处；此前“无法唯一定位”的判断被这条更强证据更新。该结论不证明正常安全宏按钮路径也失败。

诊断增强版随机包已生成：`dist/directcast-context/WowBuddyDev-addon.zip`，目录 `w60cf116f0e52`，SHA256 `a9cb27a3537f35f0f8ff330670457b15a923047b7dd3db0221e9db5a34069de6`。66个Lua文件编译、64个TOC条目加载及隔离登录事件通过。包未安装、未发布；游戏仍使用先前版本，正常按键宏路径需要独立实测。

### 诊断增强版本机安装（更新上述未安装状态）

随后窗口列表已无游戏，再以进程检查确认Wow/WowB/WowClassic/WowClassicB均未运行，安装上述摘要对应包。85个文件逐个摘要与包核对，保留WowBuddyDev目录/TOC身份，内部Lua采用随机文件名。此前85文件完整备份到 `WowBuddyDev-backups/20261107T144745Z-e5a00d0073584d5688317c604e5c7601`；备份逐文件一致，72个WTF文件安装前后内容与路径一致，未清理其他目录。报告为本机 `.local/install-directcast-context.json`。

这是诊断增强版安装，不代表施法修复或完成游戏验收。GitHub附件和客户端EXE尚未更新。

从实际安装目录读取TOC和随机文件，在隔离宿主中重新执行64个TOC条目、登录、进入世界及7个延时回调，法师宏绑定检查通过；报告 `.local/installed-directcast-context-load.json`。该验证未启动游戏或模拟安全施法权限。

安装与离线回调不代表游戏施法成功。原生GetSpellInfo是否存在、此次修复能否解决现场no-slot、受保护操作结果、自动按钮挂钩与连续换怪仍未验收。已向用户询问是否方便进入角色；公开GitHub下载附件未更换，客户端EXE仍为本地7b0eaa1构建。
