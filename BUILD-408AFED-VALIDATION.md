# 408afed安装修复版构建验证

产品源码提交408afed，包含手动随机插件身份保留，以及其他插件TOC为非UTF-8时跳过身份扫描的修复。构建期间源码一致性检查通过；本轮测试工具新增GBK其他插件fixture，不改变产品。

|产物|SHA256|
|---|---|
|dist/local-408afed/WowBuddyDev-Outer.exe|757a380f85502048a087632ee71c63c70d8e317ab76b8ec23fc85c9e8df487aa|
|dist/desktop/WowBuddyDev/WowBuddyDev.exe|dc62aac2b3b9665d33e3bf1b22be939bd9466524aeb3665bde8d5decd9081f0c|

目录版冻结启动、实际系统后端初始化自检通过；外层266个交付成员及身份/负载校验通过。

check_frozen_addon_install.py通过12场景，目录版和外层均实际执行安装命令。手动随机安装场景确认沿用原身份、精确备份、保存变量保持，以及旁边GBK编码其他插件TOC字节保持。另覆盖首次安装、更新、记录写入锁定时回滚、解除锁后重试、目标占用失败。各自有Job最终进程数均为0。

check_frozen_outer.py通过首次解包、缓存复用、缺ready标记重建三个场景；稳定启动日志检查通过，各Job进程数归零。

归档目录包含EXE、两份构建清单和两份冻结验证报告。本轮没有重新测试普通GUI两次启动、GitHub在线更新、游戏施法或自动换怪；未操作真实游戏插件目录，未发布新的GitHub Release附件。上述检查不代表完整还原。
