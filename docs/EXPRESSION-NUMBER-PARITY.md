# 规则字段数值转换的原Qt对照

本轮检查 `EvaluationContext.number`，原依据为044fd0/045190：字段先QString::trimmed，拒绝空或破折号哨兵，取字面空格分隔的第一段，再调用QString::toDouble并检查ok。

`tests/test_expression_number_native.py`调用原包 `D:/reverse-analysis/wow-assistant/unpacked/Qt6Core.dll` 导出的QString::toDouble，不启动原EXE。测试QString使用显式UTF-16长度，因此包含NUL的样本并未在传入前被宿主截断。

12种基础字符串×7种包装共84组通过：普通小数、负零、零、下溢、可表示非正规数、上溢、nan、inf、+inf、-nan、下划线数字、全角数字；包装覆盖裸文本、首尾Unicode空白、NUL后续字符，以及NBSP/Tab/EM SPACE/U+001C后接字面空格和说明后缀。

逐项比较独立版是否返回有效数值与Qt ok，再比较数值（NaN单独判断）。结果全部一致，本轮无业务代码修改。日志 `.local/expression-number-native.log`。

范围限制：Qt实际转换被直接执行；字段查找、首尾trim及取第一段在测试宿主准备，其中trim复用现有Qt空白模型，没有重新执行原044fd0整函数。本结果不能证明所有Unicode版本、全部浮点舍入输入、完整规则表达式或游戏字段正确。JSON数值类型输入与字段字符串解析是两个不同路径，不混为同一验证。
