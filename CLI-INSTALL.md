# 独立安装命令对照

本轮直接复查原 EXE 已导出的 `0x1400624b0.c`，没有重新运行原程序。该函数扫描 `--install-addon-dir=`，取最后一个值；空值时探测并选首项，之后准备容器、安装并写结果。已有 `cli_install.run_install_command` 保留该编排，现由独立入口接入自有 ZIP 安装器。

使用：`python run_dev.py --install-addon --install-addon-dir="D:/游戏/_forever_/Interface/AddOns" --data-dir="D:/测试记录"`。EXE 构建后支持相同参数。

- 显式目标直接使用，不添加 Interface/AddOns，不构造窗口、抓屏或发键后端。
- 无目标时调用原检测模块；无客户端或包准备失败返回 2，安装失败返回 1，成功返回 0。
- 结果写入 data-dir 的 `_install_addon_result.txt`，沿用 OK/FAIL、目标及目录名字段。写报告失败沿用原逻辑，不改变安装返回码。
- 标准 Interface/AddOns 路径与 GUI 共用安装记录；其他显式位置的记录和备份位于所给目录中。

## 用户指定的产品调整和仍存在的差异

自有 ZIP 和清单替代原 addon.bin，更新备份旧开发插件，不调用旧清理器删除其他插件。优先选择 packages/WowBuddyDev-addon.zip，缺少时使用本地开发包 WowBuddyDev-dev.zip。固定开发包不随机命名；GitHub 发布包随机命名。

独立入口保留参数冲突检查、支持空格取值，并将报告放入独立 data-dir；这些不等同于原程序忽略未知项和原命令优先级。原检测模块只列出 _classic_beta_ 与 _cn_beta_，尚未扩展 _forever_ 自动发现；该客户端现在须传显式目标。不能据此宣布全部原生命令或自动检测已完整还原。

新增测试验证中文直接目标、重复参数取末值、空值探测、缺包返回 2、重复安装备份、真实入口成功与失败返回码；安装器原有五项回归通过。未执行真实游戏目录安装或游戏加载。
