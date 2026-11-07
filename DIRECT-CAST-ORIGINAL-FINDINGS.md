# 原DirectCast模块的实际行为与缺陷

`tests/test_original_direct_cast.py`直接从原addon.bin读取DirectCast.lua，核对TOC包含该文件，并在Lua 5.1显式替身宿主中执行原文。没有改写原Lua，没有加载解锁器；UseAction、CastSpellByID、动作条放置与计时器全部只是内存记录。五项测试通过（0.057秒）。

## 已确认行为

1. 文件加载完成会设置`DC.enabled=true`，注册`/dc`、`/dcbind`，并注册1秒和0.1秒两个计时器；加载本身没有调用施法替身。
2. Core.lua的`CreateSecureButton`成功返回布尔true。DirectCast包装器将该返回值交给hookButton，后者读取`btn.HookScript`导致布尔索引错误。测试确认创建已发生，随后报错；不能把这个错误解释成安全按钮一定没创建，也不能声称HookScript已成功安装。
3. 移动时记录的待发意图在`/dc off`后仍保留；停止移动后调用0.1秒计时器两次，仍产生一次UseAction替身调用。该计时器没有检查DC.enabled。
4. PlaceAction报错时，`placeSpellToSlot`仍因`return ok2 or true`返回true；EnsureSlotForSpell缓存该槽位，第二次查询不重试放置。
5. `/dc off`只改变enabled，不阻止显式DC.Cast调用。测试调用仍进入UseAction路径；这可能是显式测试命令的设计，不能自动当成与待发计时器相同的缺陷。

## 对还原工作的影响

模块不只是按钮直调，还包含自动占槽、已有/手动槽位回退、自Buff续挂及停止移动后补发。此前移除整个文件会丢失这些分支；不能以客户端常规按键通道替代全部行为证明。

同样，原注释中“白名单永放行”“已实测”等内容只是原文件声明，不是本次环境验证。当前没有证据说明这些调用能在用户游戏的安全执行环境中生效。受保护调用必须遵守游戏执行机制，不能把改写污染标记或解锁器视为已实现的普通插件能力。

现阶段原模块仍未打入独立插件，五项测试只是确定原行为与缺陷，不等于恢复完成。后续若修复上述缺陷，应保留本对照记录并明确修复后的产品行为与原始行为不同。完整真实游戏验收仍缺失。
