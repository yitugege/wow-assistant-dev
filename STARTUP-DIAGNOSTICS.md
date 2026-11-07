# 独立入口启动取证

原取证日志入口 `01ba50/01cd40/01ad90` 已迁入startup_log.py，之前没有接到run_dev.py。当前独立启动包装器在分派命令前打开日志，复用原时间戳、相对毫秒、阶段记录、正常结束行及超过1 MiB时轮转为startup.log.old的规则。Windows使用迁入的FILE_APPEND_DATA/FILE_SHARE_READ实现，每条刷新到文件。

实际记录的阶段包括入口分派准备、QApplication构造、Qt平台和字体/屏幕信息、样式表、独立循环库种子、契约规则加载、主窗口构造和显示。记录来自实际执行位置，未执行阶段不预写成功。主窗口日志也显示启动日志位置。

默认startup.log位于程序旁.local，显式--data-dir覆盖该目录。不会继承旧WOWBUDDY_HOME或旧LOCALAPPDATA产品目录；打开失败时沿用程序目录和临时目录后备规则。无法写日志不改变主命令返回值。独立目录初始化失败时仍尝试执行主命令，其实际错误由入口处理。

正常return和SystemExit记录返回码；未处理的Python异常写入取证日志，并将完整traceback保存到所选数据目录的startup-error.log，返回1。异常路径不会追加“正常退出”行，避免误导。所有结束路径关闭本次日志句柄。

本次不是原生崩溃捕获的完成证明：Qt消息处理器、SEH/CRT异常处理器、--crash-test两分支和分阶段启动画面仍未完整接入。Python异常不能代替访问冲突、堆损坏或进程被终止的测试。环境信息目前只采集独立程序身份和Qt基本信息，没有声称还原全部原Win32环境字段。

针对性测试验证阶段顺序、正常退出、重复启动追加、超过1 MiB轮转、句柄关闭、异常及完整traceback、日志不可写时保持返回码、SystemExit返回码。未对用户运行中的游戏或助手制造异常。

112项独立回归及冻结EXE构建自检通过。另以冻结EXE实际执行--desktop-selftest，核对日志中从入口、Qt、样式、资源到主窗口和正常退出的阶段顺序，以及Qt环境记录；报告为dist/frozen-startup-log-check.json。本改动尚未进入公开Release附件。
