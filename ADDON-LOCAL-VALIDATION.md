# 最新独立插件测试包

源码基线d3aeef6，包含独立前缀天赋清理和控制键清除后的SaveBindings恢复。原DirectCast行为对照测试不属于插件包，DirectCast仍未加载。

- 包：`D:/wow-assistant-dev/dist/WowBuddyDev-addon-d3aeef6-local.zip`
- SHA256：`416cf623c3da2d6ae3bb1e64b4c02eeb2789d9ec94b954ee9010d91e30d52295`
- 随机目录：`w1cd521bec7d4`
- 78个成员，59个Lua全部由Lua 5.1编译通过，58处TOC/XML引用全部指向包内成员。
- 包内Lua逐字节内容集合与源码一致；构建检查前后源码摘要不变。
- 同名`.manifest.json`及`.check.json`保存成员摘要、引用记录和源文件摘要。

新增可重复工具 `tools/build_checked_addon.py`，默认随机命名并输出清单及检查报告。仅编译Lua，不执行插件代码、不修改游戏目录。公开GitHub发布附件仍为原v0.2.7；此文件为本地测试包，不是新公开版本。

相关验证：GitHub下载替身、随机包引用及稳定身份升级测试1项通过；Lua命名空间及安全按钮战斗延迟测试3项通过。前者使用临时目录与明确网络替身，不是本轮真实GitHub下载。不能把编译通过当作实际加载、受保护调用或施法成功。

当前本地EXE仍为2de8343源码构建，内嵌插件早于此包；不能声称本地EXE已同步包含这两项设置修复。后续成套发布须统一版本、重建和验收。
