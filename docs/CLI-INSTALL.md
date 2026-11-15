# 独立安装命令对照

本轮直接复查原 EXE 已导出的 `0x1400624b0.c`，没有重新运行原程序。该函数扫描 `--install-addon-dir=`，取最后一个值；空值时探测并选首项，之后准备容器、安装并写结果。已有 `cli_install.run_install_command` 保留该编排，现由独立入口接入自有 ZIP 安装器。

使用：`python run_dev.py --install-addon --install-addon-dir="D:/游戏/_forever_/Interface/AddOns" --data-dir="D:/测试记录"`。EXE 构建后支持相同参数。

- 显式目标直接使用，不添加 Interface/AddOns，不构造窗口、抓屏或发键后端。
- 无目标时调用原检测模块；无客户端或包准备失败返回 2，安装失败返回 1，成功返回 0。
- 结果写入 data-dir 的 `_install_addon_result.txt`，沿用 OK/FAIL、目标及目录名字段。写报告失败沿用原逻辑，不改变安装返回码。
- 标准 Interface/AddOns 路径与 GUI 共用安装记录；其他显式位置的记录和备份位于所给目录中。

## 用户指定的产品调整和仍存在的差异

自有 ZIP 和清单替代原 addon.bin，更新备份旧开发插件；安装成功后按原特征规则清理旧插件目录，保留当前独立插件和无关插件，详见ADDON-CLEANUP.md。优先选择 packages/WowBuddyDev-addon.zip，缺少时使用本地开发包 WowBuddyDev-dev.zip。固定开发包不随机命名；GitHub 发布包随机命名。

当前源码已恢复早期命令优先级及忽略无关参数。显式安装目录应使用原格式 `--install-addon-dir=路径`，不是空格取值；报告仍放入独立data-dir，这是独立扩展。公开v0.2.2尚未包含本次命令分派修正。原检测模块仅有 _classic_beta_ 与 _cn_beta_，保留作对照。独立入口的检测适配已添加 _forever_、最近目录以及 Program Files 下的常用位置；无显式目标时与 GUI 共用。不能据此宣布全部原生命令已完整还原。

新增测试验证中文直接目标、重复参数取末值、空值探测、缺包返回 2、重复安装备份、真实入口成功与失败返回码；安装器原有五项回归通过。未执行真实游戏目录安装或游戏加载。
