# 原解包写文件循环动态对照

`tests/test_outer_write_native.py`直接执行原30e0..31cc机器码，与独立`launcher._write_native`比较。原映像SHA256强制校验为`fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520`，完整解码，确认三个调用槽分别为RVA14030、14040、14050，全部跳转留在函数区间内。没有只复制第一条.pdata记录的30e0..3152前缀。

## 宿主边界

三个IAT槽分别注入CreateFileW、WriteFile、CloseHandle显式记录器，不调用真实文件系统。路径对象按原短/长字符串布局构造，分别使用单字符文件名和中文长路径；原函数的路径对象分支、分块、指针推进、退出及关闭代码原样执行。原返回值按AL布尔解释，不把反编译的完整64位返回值当作定义。

## 场景与证据

13组写入配置×2种路径，共26组：长度0、1、1MiB-1、1MiB、1MiB+1、2MiB+17，连续短写，短写后零写，短写后API失败，首写失败，空/非空文件创建失败，以及CloseHandle返回失败。

逐组比较布尔结果、完整调用顺序、每次请求的字节数和数据SHA256、实际累计写入内容。另断言CreateFileW参数为GENERIC_WRITE、共享0、CREATE_ALWAYS、普通属性，安全属性/模板句柄均空；WriteFile的overlapped为空。

确认：空文件仍创建并关闭；超过1MiB分块；短写仅推进实际写入量；零写或错误立即停止；创建失败不关闭无效句柄；写入失败仍关闭且不回滚此前内容；关闭返回失败不改变函数成功结果。独立实现上述场景全部一致。

命令：`D:/reverse-analysis/build-env/Scripts/python.exe -m unittest discover -s tests -p test_outer_write_native.py -v`。1项通过，3.038秒，无跳过。

## 剩余范围

这是原写入控制流与独立实现的隔离对照，不是原2750完整资源解析/解包、真实磁盘权限与共享冲突测试，也不是目录创建失败链路验证。没有模拟不合法的API“写入量超过请求量”；独立实现对此有显式ValueError，原函数没有相同检查。没有修改产品代码或公开包。
