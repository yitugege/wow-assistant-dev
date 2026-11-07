# DXGI 实际初始化核对

## 本轮结果：未通过，不能视为 GPU 抓屏已验收

当前 Windows 会话实际调用 `CreateDXGIFactory1` 成功，随后枚举得到 3 个适配器；每个适配器首次 `EnumOutputs(0)` 都返回 `0x887A0002`（未找到输出）。第四次适配器枚举也返回该值，初始化结果为 `no_output`。

因此本次没有进入 `D3D11CreateDevice`、`DuplicateOutput`、`AcquireNextFrame`、纹理复制或映射阶段。该结果说明当前枚举链没有显示输出，不能据此推断机器没有显卡，也不能断言远程桌面、驱动或权限是具体原因。

## 原程序对照

只读反编译 `0x1400300e0` 的适配器枚举使用虚表偏移 `0x60`（槽 12），输出枚举使用偏移 `0x38`（槽 7），与当前 ctypes 实现一致；均以 `-0x7785fffe`（即 `0x887A0002`）终止相应枚举。找不到输出后设置当前时间加 `0x5dc`（1500 ms）的重试期限。

本轮检查未发现足以支持修改上述业务逻辑的差异。没有跳过失败、伪造成功或将 PrintWindow 结果计为 DXGI 结果。

## 可重复的取证入口

- `tools/check_dxgi_initialization.py`：在真实调用外围记录返回值，不替换系统调用结果；只读初始化，不抓屏、不创建测试窗口、不发键。初始化未完成时返回退出码 1。
- `tools/check_win32_printwindow.py --backend dxgi`：显示自有无激活、置顶色条窗口，在 4 秒有界等待内检查桌面合成更新后的像素；本轮第一个场景失败，记录 `no_output`，退出码 1。等待不会改变业务模块的 1500 ms 退避。
- `tools/check_win32_printwindow.py`：仍默认使用 PrintWindow。修改取证工具后，原 18 场景回归再次通过，10.275 秒。

执行时需使用 Windows Qt 平台。取证结果位于本地 `dist/dxgi-initialization-trace.json` 和 `dist/win32-dxgi-check.json`。未保存整屏图像；DXGI 检查只比较自有窗口位置的窄条。

DXGI 工具退出时释放其 COM 资源并销毁自建窗口。真实游戏、GPU 捕获及其设备丢失恢复仍需在能枚举显示输出的会话中验证。此限制只阻碍该项验收，其他还原工作仍可继续。
