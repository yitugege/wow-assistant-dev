# 插件升级目录身份保留

## 修复范围

原独立安装器已对随机目录间升级保留本机名称，但把已有固定目录WowBuddyDev升级到随机发布包时会改名。当前本机固定开发版正好走此分支。目录身份改变会影响游戏按插件名关联的启用状态与存档查找，因此不能仅凭SavedVariables变量名称相同就认为升级保留了原身份。

现在已有安装记录或已有固定目录时沿用原名称，包括WowBuddyDev；全新安装仍采用发布包中的随机目录。安装到不同于发布包的目录时只改TOC文件名，随机Lua名称和TOC内部引用保持一致。不会读写或执行WTF里的Lua存档，不进行账号或角色设置迁移。无效旧目录及安装记录仍拒绝覆盖。

15项安装、GitHub随机包及周期更新回归通过，包括有/无记录的固定目录升级、存档及启用配置字节不变、随机首次安装及后续目录稳定、失败回滚。此安装器修复目前仅在源码，尚未包含于已公开的v0.2.5客户端；后续客户端版本需要带入。

## 本机从公开包安装验证

安装前再次确认没有Wow/WowB/WowClassic/WowT游戏进程，AddOns下只有WowBuddyDev。使用此前从GitHub v0.2.5下载并验证过的随机包 `w4d5b51e0ba91`，经修复后的源码安装器更新。

- 安装目录保持 `D:/Program Files (x86)/World of Warcraft/_forever_/Interface/AddOns/WowBuddyDev`。
- 78个新文件逐项摘要一致（TOC文件名适配为WowBuddyDev.toc），版本0.2.5-dev。
- 旧目录78个文件完整备份，备份摘要与安装前逐项一致。
- WTF目录70个文件安装前后摘要一致；没有需要清理的其他旧插件。
- 备份目录：`D:/Program Files (x86)/World of Warcraft/_forever_/WowBuddyDev-backups/20261107T072526Z-a51da14c71fc4e1b95f0d5be26e59548`。

本地详细记录 `dist/game-addon-025-install.json`。本次未启动游戏、改变插件启用配置或测试技能释放，不能把安装验收当作游戏验收。
