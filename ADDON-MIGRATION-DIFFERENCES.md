# 插件迁移差异与未恢复功能

本轮逐文件读取原addon.bin和独立源码，仅归一CRLF/LF、P07483180→WowBuddyDev、SemrepDB→WowBuddyDevDB。工具 `tools/audit_addon_migration.py` 输出完整摘要清单 `dist/addon-migration-audit.json` 和可审查差异 `dist/addon-migration.diff`。这不是运行时等价证明，也不把差异自动认定为用户批准。

原78成员中：24个逐字节相同；42个仅上述名称或换行不同；11个仍有差异；1个缺失（DirectCast.lua）。独立新增SecurityDiagnostics.lua。原TOC映射到WowBuddyDev.toc后单独比较，不误报为文件丢失。

## 影响功能的差异

|位置|实际差异|验收结论|
|---|---|---|
|DirectCast.lua及TOC|原包包含且TOC加载；独立删除且打包工具拒绝该文件|实质未恢复项。原模块依赖解锁环境、直接调用施法API并挂钩安全按钮；不能用安全宏通道已实现代替该模块等价证明。此前移除用于排查受保护操作，不等于用户明确要求永久删除此原功能。|
|PixelBar.lua、Core.lua|技能位图由固定bit0标记、从bit1起编码改为从bit0起承载24项，并使用独立版本码|修复24项状态溢出、与独立客户端配套；是协议变更，不是字节级原样还原。原协议兼容与独立协议应分开验收。|
|Druid-Bindings.lua|SHIFT-F2原空槽补为既有变换之力宏|原资源缺陷修复，见ROTATION-GAPS.md；不能将241动作均有宏的现状归称原包也是如此。|
|SettingsUI.lua|移除导入天赋前对旧MKL/P07483180配置的批量清除，并改导入名|保留独立命名可避免干扰旧插件，但原清理行为并未一比一恢复。当前独立命名配置的重复导入/清理语义仍需专项核对。|
|SettingsUI.lua|移除清空自有控制键时的SaveBindings调用|控制键保存到DB并由像素条轮询；这是调用差异，不能仅因认为无用而宣称相同。受保护错误来源尚未游戏确认。|
|AutoTarget.lua、RaidFocus.lua、Core.lua|捕获异常后增加绑定错误记录|保留失败返回/后续流程，新增可见诊断；自动选怪门控124帧对照不覆盖全部绑定异常诊断分支。|

其余差异主要是Core、DebugAuras、DebugDock、PanelV2、PixelBar、SettingsReset、SettingsUI里的具名Frame/Button身份隔离，以及TOC版本、说明、诊断SavedVariables。旧新实例同时加载时的所有全局冲突仍不能仅凭改名证明已消除。

## 后续要求

完整还原不能只统计测试数量。DirectCast缺失、天赋导入清理变化、控制键保存调用变化须保留在差异清单，直到有明确的恢复实现、用户确认的产品差异或可证明等价的替代行为。当前未在游戏中执行配置删除、受保护调用或新模块加载，本轮只增加审计工具和记录。
