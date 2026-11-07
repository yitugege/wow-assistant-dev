# 插件迁移差异与未恢复功能

本轮逐文件读取原addon.bin和独立源码，仅归一CRLF/LF、P07483180→WowBuddyDev、SemrepDB→WowBuddyDevDB。工具 `tools/audit_addon_migration.py` 输出完整摘要清单 `dist/addon-migration-audit.json` 和可审查差异 `dist/addon-migration.diff`。这不是运行时等价证明，也不把差异自动认定为用户批准。

DirectCast后续原文执行结果见DIRECT-CAST-ORIGINAL-FINDINGS.md：已确认按钮返回值类型错误、关闭后遗留移动补发、放置失败仍缓存等行为。当前已拆成六个独立模块恢复主要入口和周期逻辑，自动按钮挂钩仍未接入；不能仅凭离线对照称其游戏内可用。

2026-11-07按f1b6d86产品源码重新审计：原78成员中，24个逐字节相同，42个仅上述名称或换行不同，11个仍有差异，1个同名文件缺失（DirectCast.lua）。独立新增八个文件：DirectCast的Slots、Guards、Actions、Probe、Keeper、Movement六个模块，以及SecurityDiagnostics.lua、HookOrderProbe.lua，共85个文件。缺少原同名文件不等于其全部功能缺失。原TOC映射到WowBuddyDev.toc后单独比较，不误报为文件丢失。

## 影响功能的差异

|位置|实际差异|验收结论|
|---|---|---|
|DirectCast.lua及TOC|原包包含且TOC加载；独立打包拒绝原同名文件，改为加载六个可读子模块|槽位、宏解析、光环判断、显式施法入口、移动补发、自Buff续挂及环境入口已有原调用轨迹对照；自动按钮挂钩仍缺失，原生权限和施法结果待验收。环境入口本身不证明能解除游戏限制。|
|Core.lua|增加只读GetBoundMacro查询，供DirectCast旧查询失败时回退|修复原模块无法访问局部宏注册表的问题；九职业绑定及重绑定离线检查通过。这是明确修复，不是原缺陷的逐字复现。|
|PixelBar.lua、Core.lua|技能位图由固定bit0标记、从bit1起编码改为从bit0起承载24项，并使用独立版本码|修复24项状态溢出、与独立客户端配套；是协议变更，不是字节级原样还原。原协议兼容与独立协议应分开验收。|
|Druid-Bindings.lua|SHIFT-F2原空槽补为既有变换之力宏|原资源缺陷修复，见ROTATION-GAPS.md；不能将241动作均有宏的现状归称原包也是如此。|
|SettingsUI.lua|恢复导入前清理，匹配范围改为独立WowBuddyDev_前缀|已恢复枚举、逐项pcall读取/删除、失败继续及先清理后校验顺序；旧MKL/P07483180名字不清理。范围差异仍保留，详见下节测试及限制。|
|SettingsUI.lua|清空自有控制键后的SaveBindings调用已恢复|12组原Lua与独立Lua状态及调用序列一致；真实游戏保存及受保护错误来源尚未确认。|
|AutoTarget.lua、RaidFocus.lua、Core.lua|捕获异常后增加绑定错误记录|保留失败返回/后续流程，新增可见诊断；自动选怪门控124帧对照不覆盖全部绑定异常诊断分支。|

其余差异主要是Core、DebugAuras、DebugDock、PanelV2、PixelBar、SettingsReset、SettingsUI里的具名Frame/Button身份隔离，以及TOC版本、说明、诊断SavedVariables。旧新实例同时加载时的所有全局冲突仍不能仅凭改名证明已消除。

## 后续要求

完整还原不能只统计测试数量。DirectCast自动按钮挂钩缺失、天赋导入清理范围变化及原缺陷修复须保留在差异清单。最新诊断插件已安装，备份和WTF不变检查通过，但仍未取得游戏内加载、点击顺序或施法证据，见INSTALLED-HOOK-PROBE-VALIDATION.md。以下修复小节保留当时测试记录，其中“仅源码”描述属于历史状态；当前交付状态以COMPLETENESS.md为准。

## 后续修复：独立天赋导入清理

SettingsUI恢复`purgeImportedTalentConfigs`及其导入前调用，保留原流程的战斗/可编辑性/框架加载前置检查，随后清理、再解析与验证导入串。读取单个配置失败跳过，删除失败继续。匹配仅限`WowBuddyDev_`开头，配合现有独立导入命名；这与原任意位置匹配MKL/P07483180不同。

`tests/test_talent_import_cleanup.py`执行实际源码函数片段，四项通过：自有前缀和旧/混合名字区分；单个读取或删除报错；三种前置拒绝；无效头仍保留原清理先行顺序；空配置列表和重复导入。游戏API全部为记录替身，未删除真实配置。

名称前缀不是配置来源的密码学证明：玩家手动命名为同一前缀的配置也会匹配，和原按名称识别的机制相同。实际游戏权限、删除结果、重复配置界面以及完整SettingsUI点击回调尚未验收。本次修改仅在源码，尚未更新本地EXE或公开插件包。

## 后续修复：控制键清除后的绑定保存

恢复原`SaveBindings(GetCurrentBindingSet())`，置于清除DB字段及刷新按钮文字之后。原回调没有战斗检查、没有pcall，也没有保存失败后的回滚；独立版保留这些行为。左键进入捕获、应用新控制键仍不调用游戏绑定保存，与原路径一致。

`tests/test_control_key_settings.py`五项通过，其中三种控制键×战斗/非战斗×绑定集1/2共12组实际原Lua回调与独立Lua对照：剩余DB字段、按钮文字、调用顺序及保存参数一致。单独验证保存抛错后DB清除和文字刷新仍生效。另四项天赋导入和两项打包测试通过，共11项。未修改真实游戏绑定，未验证客户端安全执行环境；修复仅源码，尚未安装或公开发布。
