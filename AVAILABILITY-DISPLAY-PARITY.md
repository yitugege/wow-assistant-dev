# 可用技能统计整数转换修复

原`0x1400a2d70.c:666`使用QString::toLongLong(base10)，调用前按trimmed、section(字面空格,0,0)处理action_avail。既有原证据见参考工程《运行显示.md》，本轮重新核对该函数调用。

当前presentation._mask直接int(token)，遇到5000位数值或前导零时抛Python整数长度异常；另外第二次Unicode trimmed与原流程不同，未保留原Qt在NUL终止的行为。

新增tests/test_availability_display_native.py，实际加载原包Qt6Core.dll并调用toLongLong。17组输入覆盖int64边界、长前导零、长溢出、NUL、ASCII空白、内部NBSP、字段尾注和非法数字。修复前3组异常、2组结果不同；修复后全部一致。修复仅作用于技能统计显示：保留section前Unicode裁剪，转换阶段在NUL截断并裁剪ASCII空白，移除前导零后按有效位数和int64范围解析，不改变Python全局限制。

日志：`.local/availability-display-before.log`、`.local/availability-display-after.log`。134项核心回归通过，日志`.local/core-availability-display.log`。

边界：Qt整数转换是真实原DLL执行，外层trimmed/section及显示位移通过原静态流程和测试输入核对，并非执行原完整主窗函数。本轮未改候选引擎的独立整数解析路径，NUL/NBSP等边界在那里仍需单独审计。尚未重新构建或公开发布，不代表现有EXE已含修复。
