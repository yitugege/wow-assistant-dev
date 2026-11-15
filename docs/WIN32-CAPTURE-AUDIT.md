# PrintWindow 实际抓屏核对

## 补充：屏幕内移动后的真实抓屏

`tools/check_win32_printwindow.py --move-window`新增左上、中央、右下三个位置，九专精×两协议×三位置共54场景。每次移动后重新读取真实窗口矩形、客户区及ClientToScreen坐标，确认原点等于请求位置，实际PrintWindow输出逐像素一致，随后解码成功。当前Windows会话、1倍缩放、测试色条完整处于屏幕内时全部通过。

结果为dist/win32-printwindow-movement-check.json，日志.local/printwindow-movement.log。窗口仍为本进程无激活测试窗口，结束后关闭销毁；未抓取用户游戏窗口或保存整屏图像。此项扩展原18场景证据，不覆盖移动过程中的每一个中间帧、遮挡、超屏、高DPI或DXGI。原默认检查仍为18场景，移动报告独立保存。

## 补充：带边框窗口客户区裁剪

`--decorated --move-window`在带真实标题栏和边框的自有Qt窗口重复九专精×两协议×三位置，54场景全部逐像素一致且解码成功。实测客户区相对GetWindowRect原点偏移均为(8,31)，确认PrintWindow完整窗口图像中的边框和标题栏未混入客户端左48列。

首轮测试因Windows将窄标题栏窗口扩到最小宽度，客户区大于原24像素画布，尺寸断言失败；该失败属于测试夹具前提错误，未计入通过。工具现以160像素完整画布承载原色条，右侧填充已知背景；业务抓屏代码未改变。增加失败时尺寸及矩形诊断，避免空白错误提示。

成功报告dist/win32-printwindow-decorated-movement-check.json，日志.local/printwindow-decorated.log，首轮定位日志.local/printwindow-decorated-detail.log。工具仍要求1倍缩放、窗口完整位于屏幕内；未将此结果外推至实际游戏、特殊边框、DPI虚拟化或DXGI。

## 结果与范围

在当前 Windows 桌面、100% 缩放、自有测试窗口完整处于屏幕内的条件下，真实 `Win32PrintWindow` 抓屏通过 9 个专精 × 两种协议，共 18 个场景：输出条带逐像素等于输入图像，随后原有解码管线正确识别协议和专精。

测试使用标准 Qt 绘制提供已知色条，再调用真实 `GetWindowDC`、`CreateCompatibleDC`、`CreateDIBSection`、`PrintWindow` 和 ctypes 图像读取。不是把预设图像直接作为抓屏后端的返回值。窗口使用无激活显示，测试结束关闭并销毁。

专精为 1482、1484、1485、1486、1487、1488、1489、1490、1491。旧协议输入宽 24 像素，输出保留 24 列；readable 输入宽 64 像素，输出裁为 48 列。readable 保留契约所需全部字段行及末尾余量，避免使用固定 1500 高度将测试窗口伸出屏幕。

工具：`tools/check_win32_printwindow.py`；实际结果：本地 `dist/win32-printwindow-check.json`；子进程测试：`tests/test_dev_win32_printwindow.py`，通过，10.232 秒。

## 原程序证据

只读反编译 `D:/reverse-analysis/wow-assistant/decompiled-main/functions/0x14001eed0.c`：创建 DIB 后先 `PrintWindow(...,2)`，仅返回失败才重试参数 0，随后从图像复制客户区条带，限制宽度为 `0x30`。当前业务实现保留此分支，本轮未改写抓屏算法。

## 实际发现的边界

初始隐藏 Qt 窗口实验中，API 返回成功但图像全黑，也未触发该窗口的绘制回调。后续默认位置、固定 1500 高度的实验中，超出屏幕下边界的区域出现黑色；该次逐像素比较失败，没有计入通过结果。

因此工具改用可绘制窗口，并显式要求 1 倍缩放、完整显示所需色条。此要求限定取证范围，不是修改客户端回退逻辑，也没有将隐藏窗口、越界窗口或高 DPI 条件视为已经支持。

## 尚未证明

- DXGI Desktop Duplication 实际 GPU 抓屏与重建。
- 游戏窗口的渲染模式、后台/遮挡状态以及高 DPI、多显示器行为。
- 从真实游戏插件到候选技能、发键、技能读条及像素回执的完整闭环。
- `PrintWindow` 参数 2 真实失败后参数 0 成功的系统级场景。

本轮仅新增取证工具、回归和说明；未重建 EXE，公开 v0.2.3 不变。
