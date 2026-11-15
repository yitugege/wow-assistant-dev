# 规则JSON类型转换核对

原04fb00逐条将JSON值转换为对象；action使用toString，holdMs使用QJsonValue::toInt(0)，offGcd使用toBool(false)。缺失when与显式null不同：缺失项丢弃，null项保留后交给表达式层。当前parse_rules保持该区别。

tests/test_rule_json_native.py直接加载原附带Qt6Core.dll，构造QJsonValue并调用toInt和toBool，对照当前parse_rules及Action.from_json。覆盖25种输入：null、布尔、空串/数字串/布尔串、正负整数、小数、接近整数的小数、int32两端及越界、2^53、极大/极小有限double和负零。每种同时核对holdMs默认0、spellId默认-1、offGcd默认false，并确认显式null条件保留。

全部通过，日志.local/rule-json-native.log。本轮未修改业务代码。原04fb00的缺失/空action流程仍依据反编译和既有核心测试；本次仅动态执行原Qt转换，不是执行04fb00整函数。

循环库文本入口当前已使用QJsonDocument解析并检查错误，然后通过Qt紧凑JSON序列化转回Python，不能把Python json默认接受NaN的行为直接算作该入口缺陷。资源文件入口、全部JSON文档结构和极端内存错误未由此测试覆盖。
