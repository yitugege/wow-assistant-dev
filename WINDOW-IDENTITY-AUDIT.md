# 原生窗口身份接线核对

本轮只更新独立源码入口，尚未发布新的安装包；GitHub v0.2.3 不包含本轮修改。

## 原程序证据

- `0x14000d350` 使用 `GetCommandLineW` / `CommandLineToArgvW`，从第一个用户参数开始精确匹配 `--no-stealth`，匹配后关闭窗口身份处理。
- `0x1400b09d0` 在开关开启且窗口句柄有效时，将扩展样式按位或 `0x80`（工具窗），再调用 `SetWindowTextW` 设置缓存标题。
- 参考反编译文件位于 `D:/reverse-analysis/wow-assistant/decompiled-main/functions`，本轮未修改参考文件或原 EXE。

## 独立入口修复

普通 GUI 启动接入已有 `NativeWindowIdentity`；显示及重新显示窗口时执行。标题生成及进程内缓存沿用已有还原模块。工具窗样式会影响 Windows 任务栏窗口呈现。

`--no-stealth` 关闭此处理，保留独立版系统窗口标题。窗口内标题与托盘仍使用 WowBuddyDev。入口在 Qt 消费参数之前保留原始参数，因此即使该字符串被 Qt 当作某项参数值消费，原始开关判断仍然有效。大小写变体和 `--no-stealth=true` 不等同于该开关。

程序内部 `launch` 接口默认关闭原生身份处理，离屏诊断和构建自检维持此默认；正式普通 GUI 命令分支显式传入解析结果。

## 验证边界

`tests/test_dev_window_identity.py` 的五项测试覆盖参数分派、关闭开关时不申请句柄、样式保留与标题缓存、真实 Qt 显示回调接线，以及独立子进程内自有隐藏窗口的实际 Win32 标题/样式读回。没有操作用户现有窗口。

这不代表已完成真实桌面的任务栏、多显示器验证，也不代表游戏内自动施法或连续换怪验证通过。

完整独立回归通过：145 项，137.323 秒，记录位于本地 `.local/window-identity-tests.log`。本轮未重新构建或发布 EXE。
