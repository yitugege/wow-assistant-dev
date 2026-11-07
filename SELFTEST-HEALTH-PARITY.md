# 治疗自检血量读取修复

核对原05c6a0调用的05c150完整导出：只接受focus_player或focus_party后单字符1至4，取health_<unit>原文本直接QString::toInt(base10)。没有trimmed、section或字段替代回退。

独立selftest_focus._health曾先Unicode trimmed再Python int，产生长文本异常以及NUL/NBSP差异。改为复用已恢复的candidates._decimal_int，保留目标名严格限制，转换失败返回-1。

原Qt对照新增13种血量×5个目标共65组及5种非法目标名；修复前10组异常、10组结果不符，修复后全部通过。原有字段、动作、焦点及压制账本测试同时通过；五项独立自检入口测试通过，包括报告追加和失败退出码约定。

日志：.local/selftest-health-before.log、.local/selftest-health-after.log、.local/selftest-health-entry.log。本轮验证原Qt转换与静态调用流程，未执行原05c150整函数机器码或真实治疗。该修复影响自检血量诊断，不将它称为实际治疗排序已全部还原。尚未打包。
