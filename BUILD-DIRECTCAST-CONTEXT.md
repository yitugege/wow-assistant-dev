# 诊断上下文版客户端构建

2026-11-07，构建当前工作树，使测试EXE内嵌插件包含DirectCast调用上下文诊断。此改动保留原调用顺序和返回语义，不是施法权限修复。

## 交付

- 单文件：`dist/local-directcast-context/WowBuddyDev-Outer.exe`，SHA256 `474314f38dd1f16d284a09900add37509eadfc4b8c7f2fd978ab231d2c3a537e`。
- 目录版：`dist/desktop/WowBuddyDev/WowBuddyDev.exe`，SHA256 `e0c73d49981f9fee81b0f405b6bedb9a868c40cad55eeec81610c73349d90078`。
- 单文件归档同时保存内外层构建清单和frozen-outer-check.json。公开GitHub附件未更新。

## 本次验证

- 构建输入前后摘要一致；目录版冻结启动与系统后端初始化自检通过。
- 85个插件源码文件与目录版_internal及附带ZIP逐字节一致。
- 单文件266个成员、PE身份和负载摘要校验通过。
- 单文件首次解包、缓存复用、缺失ready标记后重建三场景通过，各自Job最终进程数为0，启动日志位置检查通过。
- 当前核心测试156项通过，4.037秒。没有把此前完整顶层回归、六方案或正常GUI检查算成本次重测。

本次未验证实际游戏施法、普通GUI交互及在线更新；自动施法和自动换怪仍不能宣布完成。当前本机游戏插件使用随机命名诊断包，目录身份WowBuddyDev；该构建附带包使用可读源码名称，独立随机下载包仍位于dist/directcast-context。
