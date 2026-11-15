# 可打断读条表达式解析修复

原03dc90:778–790核对：取原字段文本，QString长度必须为7且首字符为#，截取后直接toUInt(base16)，成功后判断(value & 0xFFFFFF00)==0xFF00。字段辅助02f470只复制文本，不trim。

当前表达式原用Python字符长度及Unicode trimmed；未模拟NUL终止。改为UTF-16单元长度、NUL终止和ASCII空白，保留加号、0x前缀和掩码。正常六位像素色文本行为不变。

新增test_interruptible_native.py直接调用原Qt6Core.dll toUInt：256个允许低字节变化的颜色加17个边界，共273项全部通过。首轮272项中3项与原Qt不同；核心回归另暴露旧测试错误期待NBSP通过，加入该原样输入对照后确认Qt拒绝，修正测试预期。最终134项核心回归通过。

日志.local/interruptible-before.log、.local/interruptible-after.log、.local/core-interruptible.log。外层长度/首字符/掩码依据静态控制流，转换执行真实原DLL；未执行原整个规则函数机器码或游戏打断。修复尚未进入EXE。
