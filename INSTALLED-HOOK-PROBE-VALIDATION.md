# 点击顺序诊断插件本机安装记录

## 安装结果

本轮将源码f1b6d86对应的本地测试包安装到已有游戏客户端`_forever_/Interface/AddOns/WowBuddyDev`。这是开发测试安装，不是GitHub Release发布。客户端及单文件EXE没有被替换。

- 安装前插件版本0.2.5-dev；安装后TOC为0.2.8-dev，保留本机目录身份WowBuddyDev，Lua文件仍来自随机命名包。
- 包：dist/hook-order-probe/WowBuddyDev-addon.zip，SHA256 `53b1cd4012ce71e344f0e47f0788fee50f645b981b5c9add38e7e276ac12d031`。
- 安装前确认未运行Wow/WowB/WowClassic/WowClassicB，AddOns只有已有WowBuddyDev目录。
- 安装器自动备份旧插件到客户端WowBuddyDev-backups子目录；旧插件78个文件与备份逐字节摘要一致。
- 安装后85个文件与包内容一致（TOC按本机保留身份改名）。没有清理其他插件目录。
- WTF目录70个文件安装前后名称及内容摘要全部相同；没有更改启用状态或保存配置。
- 新TOC声明WowBuddyDevHookProbe保存变量，诊断脚本使用实际安装身份WowBuddyDev。

本地完整报告及备份位置保存在`.local/install-hook-probe-f1b6d86.json`，不上传用户WTF内容。前置安装器、命名空间、安全诊断及记录器共18项测试通过（1.669秒）。首次预检因构建环境未安装psutil而停止，发生在安装操作之前；随后用Windows Get-Process重新确认状态后才执行安装，没有为此安装新依赖。

## 安装文件离线执行

直接从安装后的随机文件目录读取TOC，执行64个条目、ADDON_LOADED/PLAYER_LOGIN/PLAYER_ENTERING_WORLD与7个单次延时回调；法师职业宏及独立选怪键检查通过，`/wbdhookprobe`已注册。游戏API仍为既有测试宿主替身，不是原生游戏加载验证。

## 尚待现场证据

尚未启动游戏或执行真实施法，也没有取得点击顺序记录。下一步进入角色后执行`/wbdhookprobe`，手动点击中央按钮，再用`/reload`让游戏写出保存变量；需要读取实际记录才能推进自动挂钩方案。安装成功、离线初始化成功均不能代替这个证据。
