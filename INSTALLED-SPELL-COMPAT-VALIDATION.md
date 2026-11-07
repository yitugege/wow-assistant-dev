# 技能名称兼容修复本机安装

已在游戏未运行时，将7b0eaa1产品源码对应的随机命名插件包安装到现有 `_forever_/Interface/AddOns/WowBuddyDev`。包同时含技能名称查询和圣印回显修复。没有执行用户取消的 `/dump type(GetSpellInfo)` 查询，也没有改变客户端权限或启动游戏。

## 安装证据

- 包：`dist/spell-name-compat/WowBuddyDev-addon.zip`；SHA256 `6621922b4e04337b1408ee07cdc397d87e23b009365809ef4fd143baeedbaf90`。
- 安装前再次检查Wow、WowB、WowClassic、WowClassicB均未运行，AddOns只有已有WowBuddyDev目录。核对包摘要和逐文件摘要，66个Lua文件通过Lua5.1编译后才安装。
- 保留现有插件目录身份及同名TOC，内部Lua文件仍来自随机命名包。安装后85文件逐一与包比较一致，TOC仅按安装身份改名。
- 原插件85文件备份到游戏客户端 `WowBuddyDev-backups/20261107T142053Z-fd1841d94eec455b9ce464ac3aa43eab`，逐文件摘要一致；没有清理其他插件目录。
- WTF目录72个文件的路径及内容摘要安装前后完全一致。未修改游戏启用状态或保存变量。
- 完整安装结果保存在本机 `.local/install-spell-name-compat.json`，不公开用户配置内容。

## 安装内容离线验证

从实际安装目录读取随机Lua文件与TOC，在既有显式Lua测试宿主中加载64个条目，执行ADDON_LOADED、PLAYER_LOGIN、PLAYER_ENTERING_WORLD及7个单次延时回调；法师职业宏和独立自动选怪键检查通过。报告 `.local/installed-compat-load.json`。

首次命令行验证因PowerShell引号导致Python解析失败，未运行插件代码；随后改用本地脚本并成功完成上述检查。没有把失败命令算作验证通过。

## 限制

安装与离线回调不代表游戏施法成功。原生GetSpellInfo是否存在、此次修复能否解决现场no-slot、受保护操作结果、自动按钮挂钩与连续换怪仍未验收。已向用户询问是否方便进入角色；公开GitHub下载附件未更换，客户端EXE仍为本地7b0eaa1构建。
