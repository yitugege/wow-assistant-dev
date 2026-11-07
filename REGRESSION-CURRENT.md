# 当前独立工程完整回归

源码基线：`d423612`。运行期间未修改源码；命令：

```powershell
& D:/reverse-analysis/build-env/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
```

199项测试全部通过，225.897秒，进程退出码0。完整日志 `.local/current-full-regression.log`。该发现目录运行的是独立工程测试，134项核心回归为另一命令，最近结果见 `.local/switch-display-core.log`，不得将两者混称为同一次运行。

本轮覆盖最近的协议显示缓存、状态提示、统计时点、更新回调修改与既有入口共存。测试中的真实Qt、Win32、Lua和冻结产物覆盖范围以各测试及专项报告为准；旧冻结产物检查不能证明最新源码已打包，替身发键不能证明游戏接受。

## 长时间无输出的定位

最初日志停在插件命令测试附近，但只读检查确认测试进程仍存活且CPU时间增加。使用当前Python内置 `_remote_debugging.RemoteUnwinder` 对本次测试进程读取栈，依次看到分阶段启动、托盘、PrintWindow子进程等待、协议切换测试，证明执行仍在推进。

多次采样停在run_dev.launch的QApplication.setStyleSheet。直接复用QApplication的launch路径未设置与prepare_qt_runtime相同的bootstrap完成标记，导致连续测试窗口反复应用全局样式；这是耗时线索，不是已测得的唯一耗时原因。没有因观测超时终止或重启这次运行。结束后日志给出199项OK及正常退出。

## 仍未完成

最新统计、状态栏和协议显示修复尚未重构冻结包；完整逐功能原程序对照、公开新版交付、游戏插件加载、抓屏与施法回执、连续换怪验收均不能由本轮测试代替。目标保持未完成。
