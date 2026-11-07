# 原内置插件与双协议契约的来源核对

## 本轮直接证据

`tools/audit_original_addon_origin.py` 只读解压原业务包中的 `D:/reverse-analysis/wow-assistant/unpacked/addon.bin`，不安装、不执行Lua。包SHA256为 `361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed`。

包内78个成员与 `D:/reverse-analysis/wow-assistant/addon-source` 中相应文件逐字节一致。TOC标注插件版本9.9.6、Interface 16001及120100，使用PanelV2.lua和PixelBar.lua。该结果确认既有插件参考源码确实对应原EXE内置包，而非仅凭文件夹名称判断。

原 `contract.json`、`contract_readable.json` 均与独立仓库assets副本逐字节一致。后者注释明确标注readable插件20.0.1、protocol 7/8，头部版本码10685761，定位颜色为(19,227,149)、(241,173,37)、(61,109,211)。不能把它与9.9.6包的“PanelV2”名字直接等同。

原包中未搜到上述版本码和首标记的所列字面量写法；这只是定位结果，不是排除所有计算式或动态生成发送端的证明。报告 `dist/original-addon-origin.json` 保存全部成员摘要、TOC、契约头部和检索结果。

## 对还原验收的影响

当前已验证的完整PixelBar实际Lua绘制路径使用旧协议布局；PanelV2主要处理横排数字显示、光环容器及补充色块，不能仅加载PanelV2就宣称执行了readable色条协议。

客户端原本读取两套契约的功能仍须保留并验证。现有readable解码、协议切换和合成图像测试继续有效，但尚不能声称完成readable配套发送端真实绘制验证。下一步应先取得或定位与20.0.1契约对应的发送端，再判断是否有可执行的原实现对照；不能凭契约新造一个发送端后当作原插件还原完成。

这份核对没有缩小原EXE全部功能还原目标，也没有解决游戏安全执行弹窗；它纠正了“PanelV2等同readable发送端”的调查前提。当前9.9.6来源配套插件的完整游戏加载、技能状态及受保护操作仍需真实游戏验证。

## 后续查找与可选资源验证

已检查相关下载文件、分析工作目录中的Lua/TOC及压缩包路径、历史readable证据记录，以及当前 `_forever_/Interface/AddOns` 的版本线索，尚未定位到20.0.1发送端。此结论限于已检查范围，不声称整台电脑或网络上不存在该插件；已向用户询问对应路径或下载地址。

同时补充当前独立入口的真实Qt启动适配测试：`contract_readable.json` 与 `rules_readable.json` 各取缺失、损坏JSON、正常三种状态，共九个组合。基础两份资源完整，游戏窗口发现使用明确替身；每组均完成正常启动、安排600ms自动启动延迟，并以实际加载资源解码旧协议1482合成图成功。未出现1500ms警告分支。原依据为05e240丢弃可选资源加载结果，不改变共享启动warning。

`tests/test_dev_staged_startup.py` 全部六项通过（2.868秒），日志 `.local/optional-readable-startup.log`。本轮没有修改业务代码；这验证的是可选资源失败不阻止旧协议启动，不证明readable发送端存在、真实游戏窗口探测或实际自动监控施法。

## 从用户原EXE重新核对交付链

扩展`tools/audit_original_addon_origin.py`，直接读取`D:/download/WOW战斗助手.exe`，先校验SHA256 `9694f988f740acd88402c6f0ddaaf6f9173525f8c8137941a553d2c74d97bf14`，再枚举资源表。全过程只读，不运行原程序、DLL或Lua。

- 原外层10项资源中，只有`10/200/1033`正文以WBD1开头，长度39,768,542字节。解析34个成员，与当前unpacked逐成员逐字节一致。
- 34成员中，只有`addon.bin`正文以WBADDON1签名开头，包含既有78个插件成员，TOC仍为9.9.6。
- 包内29个PE文件的资源表共54项，没有资源正文以WBD1或WBADDON1开头。业务EXE仅有图标、图标组、版本三类资源。
- 安装器反编译函数`0x140011f10`使用QCoreApplication::applicationDirPath和QDir::absoluteFilePath构造插件路径；`0x1400155d0`调用它并打开文件，再验证WBADDON1。重新读取业务PE的RVA `0x10f028`指针，目标VA `0x1400d0ae0`确实是`addon.bin`，不是仅凭Ghidra符号名称推断。

完整资源与成员摘要、原安装器路径常量和两份反编译正文摘要写入`dist/original-addon-origin.json`的`original_delivery_chain`；执行日志`.local/addon-delivery-chain.log`。工具校验原EXE身份和交付链，文件不同会明确报错，不悄悄沿用旧基线。

这将“参考目录没搜到”推进为“当前原交付容器和资源表内未发现第二套插件容器”。检查仅覆盖资源表正文及WBD1成员根签名，不排除节内编码数据、其他压缩容器、运行时生成或历史远程下载；也未证明所有安装/更新入口只使用此路径。仍不能宣称20.0.1发送端不存在。当前没有对应原发送端可执行对照，不能把契约合成帧当作它的实现；该缺口继续保留，其他原功能还原可继续推进。
