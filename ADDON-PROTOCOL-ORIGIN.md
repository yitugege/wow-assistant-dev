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
