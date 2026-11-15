# 技能回执整数解析对照

## 后续调用行为验证

补查原089570:187，focus_party后缀使用toInt而非toLongLong。新增13组原Qt toInt对照，包括长前导零、NUL、NBSP、int32溢出和尾注；核对focus_index以及在已观察焦点为2时的should_skip_focus行为，全部通过。虽然共用实现使用int64，再限定1..4的最终输出在这些边界与原int32转换一致；不宣称所有整数转换函数类型相同。

另有3组AuraProbeLedger真实记录/回查路径：长前导零代次1能记录；NUL终止的新代次2能触发确认；同技能116回执得到FIRED_SAME/IMMUNE并把压制延长至11400ms，NBSP尾注或长溢出技能ID得到FIRED_OTHER/MISSED并缩短至2400ms；各自回查任务清除。测试时发送时间为1000ms、回查1400ms、原hold为10000ms，光环持续OFF。

共2项测试通过，日志.local/receipt-focus-ledger.log。此前36组字段/动作对照仍包含在内。本次仅加测试，无产品变更，不重建EXE。这里的回执是测试输入，IMMUNE是原回查分类名称，不证明真实游戏免疫或真实施法。

重新核对原08af70及0a2d70回执分支：字段先trimmed并取字面空格首段，再toLongLong；spell_动作名截取前缀后、在下划线处截断，直接toLongLong，不先Unicode trimmed。动作数值范围为2至0xFFFFFE。

当前aura_probe._integer在这两条路径都额外Unicode裁剪且直接Python int，造成长前导零/长溢出异常，以及NUL和Unicode空白差异。改为原Qt转换层语义：NUL终止、ASCII空白、有效数字长度与int64范围检查。字段调用方已有Unicode trimmed保持不变，动作名不额外放宽。

tests/test_receipt_integer_native.py实际调用原包Qt6Core.dll的toLongLong，对18种输入分别验证字段和动作路径，共36组；修复前4组异常、4组值不同，修复后全通过。134项核心回归通过。日志为.local/receipt-integer-before.log、.local/receipt-integer-after.log、.local/core-receipt-integer.log。

共用转换函数也被焦点判断使用：scheduler本身显式trimmed，而send_gates的focus_party后缀直接转换；两者仍由各自调用方控制前处理。当前测试未执行原完整调度机器码、真实游戏或冻结程序；原Qt负责数值oracle，外层裁剪/范围依已核对静态流程。此修复晚于32bb8a9本地构建，尚未进入EXE。
