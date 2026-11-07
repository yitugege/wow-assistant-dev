"""离线重建审计入口。只读取指定的已导出证据，不运行原程序。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .packages import read_addon, read_bundle, write_addon, write_bundle, compare_directory

EXPECTED_MAIN_SHA256 = "7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(root: Path) -> dict:
    bundle_data = (root / "10_200_1033.bin").read_bytes()
    bundle = read_bundle(bundle_data)
    main_members = [m for m in bundle if m.name.lower().endswith(".exe")]
    if len(main_members) != 1 or main_members[0].sha256 != EXPECTED_MAIN_SHA256:
        raise ValueError("业务主程序身份与本次逆向目标不匹配")
    addon_data = next(member.data for member in bundle if member.name == "addon.bin")
    addon = read_addon(addon_data)
    outer_results = compare_directory(bundle, root / "unpacked")
    addon_results = compare_directory(addon, root / "addon-source")
    readable = json.loads(next(m.data for m in bundle if m.name == "rules_readable.json"))
    base_rules = json.loads(next(m.data for m in bundle if m.name == "rules.json"))
    rotations_path = root / "local-test-runtime/hub/rotations.json"
    hub = json.loads(rotations_path.read_bytes())
    operations = Counter()

    def visit(expr):
        if isinstance(expr, list) and expr and isinstance(expr[0], str):
            operations[expr[0]] += 1
            for item in expr[1:]:
                visit(item)

    profiles = hub["rotations"]
    for profile in profiles:
        for rule in profile.get("rules", []):
            visit(rule.get("when"))
    coverage = json.loads((root / "decompilation-coverage.json").read_bytes())
    return {
        "schema": "wowbuddy-reconstruction-audit-v1",
        "root": str(root.resolve()),
        "full_reconstruction_complete": False,
        "original_business_executable_used_by_this_audit": False,
        "source_sha256": {
            str(path.relative_to(Path(__file__).resolve().parents[1])): _sha(path.read_bytes())
            for folder in ("wowbuddy", "tests")
            for path in sorted((Path(__file__).resolve().parents[1] / folder).glob("*.py"))
        },
        "native_target_sha256": coverage["decompiled-main"]["identity"]["target_sha256"],
        "native_target_identity_verified": main_members[0].sha256 == EXPECTED_MAIN_SHA256,
        "containers": {
            "WBD1": {"sha256": _sha(bundle_data), "members": len(bundle),
                     "byte_exact_roundtrip": write_bundle(bundle) == bundle_data,
                     "all_exported_members_match": all(x["equal"] for x in outer_results),
                     "member_results": outer_results},
            "WBADDON1": {"sha256": _sha(addon_data), "members": len(addon),
                         "lua_files": sum(m.name.lower().endswith(".lua") for m in addon),
                         "byte_exact_roundtrip": write_addon(addon) == addon_data,
                         "all_exported_members_match": all(x["equal"] for x in addon_results),
                         "member_results": addon_results},
        },
        "action_catalog": {"specs": len(base_rules["specs"]),
                           "actions": sum(len(s["actions"]) for s in base_rules["specs"].values()),
                           "readable_key_mappings": sum(len(s["actions"]) for s in readable["specs"].values())},
        "hub_cache": {"path": str(rotations_path), "sha256": _sha(rotations_path.read_bytes()),
                      "scope": "后续取得的离线缓存，不属于原始 EXE 内嵌资源",
                      "profiles": len(profiles),
                      "rules": sum(len(p.get("rules", [])) for p in profiles),
                      "expression_operations": dict(sorted(operations.items()))},
        "decompilation": {key: {"counts": value["counts"],
                                "recorded_functions": value["recorded_functions"]}
                          for key, value in coverage.items()},
        "remaining": ["隐藏字段组件及全部界面逐像素原版对照", "双协议真实帧差分和坏帧原进程动态对照",
                      "完整状态日志逐事件对照及真实抓屏/发送后端验证",
                      "真实游戏安装场景的插件热更对照、源码发布包完整更新链与原生CLI补齐",
                      "外层保护线程和SDK内部实现、运行时OEP确认",
                      "原生自测大函数 0x140062cd0 的C伪代码及其余子组恢复（raw IR已完整导出）", "所有职业/方案逐功能原版对照验证"],
    }


def main():
    parser = argparse.ArgumentParser(description="WOW 助手重建证据离线核验")
    parser.add_argument("--root", type=Path, required=True, help="wow-assistant 证据目录")
    parser.add_argument("--output", type=Path, help="核验 JSON 的保存路径")
    args = parser.parse_args()
    report = audit(args.root)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(str(args.output.resolve()))
    else:
        print(text)
    ok = all(item["byte_exact_roundtrip"] and item["all_exported_members_match"]
             for item in report["containers"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
