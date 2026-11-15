"""读取游戏存档中的 WowBuddyDevHookLog，判断 DirectCast 按钮挂钩的实机表现。

只读 WTF 存档，不修改游戏文件，不发送输入。需要 lupa（requirements-dev.txt）。
用法：python tools/analyze_hook_log.py "D:/.../_forever_" [--out 报告.json]
"""
import argparse
import json
from pathlib import Path
from lupa.lua51 import LuaRuntime

CAST_STARTED = {"UNIT_SPELLCAST_SENT", "UNIT_SPELLCAST_START", "UNIT_SPELLCAST_SUCCEEDED"}
CAST_FAILED = {"UNIT_SPELLCAST_FAILED", "UNIT_SPELLCAST_FAILED_QUIET", "UNIT_SPELLCAST_INTERRUPTED"}


def find_saved_files(client: Path):
    return sorted(client.glob("WTF/Account/*/SavedVariables/WowBuddyDev.lua")) + sorted(
        client.glob("WTF/Account/*/*/*/SavedVariables/WowBuddyDev.lua"))


def to_python(value):
    if hasattr(value, "items"):
        items = dict(value.items())
        if items and all(isinstance(k, int) for k in items):
            return [to_python(items[k]) for k in sorted(items)]
        return {k: to_python(v) for k, v in items.items()}
    return value


def load_log(path: Path):
    lua = LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False)
    lua.execute(path.read_text("utf-8", errors="replace"))
    raw = lua.globals().WowBuddyDevHookLog
    return to_python(raw) if raw is not None else None


def classify(press):
    names = [e.get("event") for e in press.get("events") or []]
    started = any(n in CAST_STARTED for n in names)
    failed = any(n in CAST_FAILED for n in names)
    errors = [e.get("message") for e in press.get("events") or [] if e.get("event") == "UI_ERROR_MESSAGE"]
    decision = press.get("decision")
    if decision == "swallow":
        if not started and not failed and not errors:
            verdict = "符合：拦下后游戏没有任何施法尝试或报错"
        else:
            verdict = "不符合：已拦下但游戏仍有施法尝试或报错，emptybutton 可能未生效"
    elif decision == "pass":
        verdict = "符合：放行后游戏有施法事件" if started or failed or errors else "待定：放行后 1.5 秒内没有施法事件"
    elif decision == "combat-pass":
        verdict = "符合：战斗中未改按钮，游戏照常处理" if started or failed or errors else "待定：战斗中放行后没有施法事件"
    else:
        verdict = "挂钩已关闭，未判断"
    return {"decision": decision, "reason": press.get("reason"), "action": press.get("action"),
            "speed": press.get("speed"), "combat": press.get("combat"),
            "typeAtClick": press.get("typeAtClick"), "typeAfterPost": press.get("typeAfterPost"),
            "events": names, "errors": errors, "verdict": verdict}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("client", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    files = find_saved_files(args.client)
    report = {"files": [], "presses": []}
    for path in files:
        log = load_log(path)
        report["files"].append({"path": str(path), "has_log": log is not None,
                                "presses": len(log.get("presses", [])) if log else 0,
                                "build": log.get("build") if log else None})
        if log:
            report["presses"] += [classify(p) for p in log.get("presses", [])]
    counts = {}
    for row in report["presses"]:
        key = row["verdict"].split("：", 1)[0]
        counts[key] = counts.get(key, 0) + 1
    report["summary"] = counts
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, "utf8")
    print(text)


if __name__ == "__main__":
    main()
