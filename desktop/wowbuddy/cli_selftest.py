"""原生062cd0完整离线自测入口；只计算合成帧、读取资源和追加报告。"""
from dataclasses import dataclass
from pathlib import Path

from .native_assets import NativeAssetStore, read_qt_json
from .startup_stages import find_resource
from .selftest_initial import run_initial_selftest
from .selftest_bindings_thresholds import run_bindings_thresholds_selftest
from .selftest_focus import run_focus_selftest
from .selftest_hub import run_hub_selftest
from .selftest_focus_dedup import run_focus_dedup_selftest
from .selftest_auto_target import run_auto_target_selftest
from .selftest_off_gcd import run_off_gcd_selftest
from .selftest_aura import run_aura_selftest
from .selftest_geometry import run_geometry_selftest


@dataclass(frozen=True)
class SelftestReport:
    text: str
    groups: dict


@dataclass(frozen=True)
class SelftestCommandResult:
    exit_code: int
    report: SelftestReport
    report_path: Path
    report_written: bool
    write_error: str


def build_selftest_report(rules, contract, *, contract_status='contract OK',
                          rules_status='rules OK', rotations=None, snapshot_path='',
                          snapshot_readable=True, spec_order=None):
    initial=run_initial_selftest(rules,contract)
    bindings=run_bindings_thresholds_selftest(rules,spec_order=spec_order)
    focus=run_focus_selftest(rules,rotations)
    hub=run_hub_selftest(rules,rotations,snapshot_path=snapshot_path,
        snapshot_readable=snapshot_readable,initial_checked=focus.checked,
        initial_mismatches=focus.mismatches,initial_skipped=focus.skipped)
    dedup=run_focus_dedup_selftest()
    target=run_auto_target_selftest(rules,contract)
    off_gcd=run_off_gcd_selftest(rules)
    aura=run_aura_selftest(rules)
    geometry=run_geometry_selftest()
    parts=['== C++ 引擎自检 ==',contract_status,rules_status,initial.text,
        '\n\n'+bindings.text,'\n\n'+focus.text,hub.text,'\n'+dedup.text,
        '\n\n'+target.text,off_gcd.text,'\n\n'+aura.text,'\n\n'+geometry.text]
    return SelftestReport('\n'.join(parts),dict(initial=initial,bindings=bindings,
        focus=focus,hub=hub,dedup=dedup,target=target,off_gcd=off_gcd,aura=aura,geometry=geometry))


def run_local_selftest_command(application_arguments, *, application_dir,
                               current_dir=None, resource_dir=None, spec_order=None):
    """原版输出appDir/_selftest.txt，WriteOnly|Append，无尾LF，失败仍返回0。

    resource_dir是重建源运行/单文件包的显式资源位置扩展；默认按原五处查找。
    多非空内置专精QHash顺序未知时必须由调用者提供spec_order，不伪造顺序。
    """
    application_dir=Path(application_dir)
    current_dir=Path.cwd() if current_dir is None else Path(current_dir)
    store=NativeAssetStore()
    outcomes={}
    for name,loader in [('contract',store.load_contract),('rules',store.load_rules)]:
        path=(str(Path(resource_dir)/(name+'.json')) if resource_dir is not None else
              find_resource(name+'.json',application_dir=str(application_dir),current_dir=str(current_dir)))
        outcomes[name]=loader(path)
    snapshot_path=''
    for argument in application_arguments:
        if argument.startswith('--rotations='):
            snapshot_path=argument[len('--rotations='):]
    snapshot=read_qt_json(snapshot_path) if snapshot_path else None
    report=build_selftest_report(store.rules.document,store.contract.document,
        contract_status='contract OK' if outcomes['contract'].accepted else 'contract 加载失败: '+outcomes['contract'].error,
        rules_status='rules OK' if outcomes['rules'].accepted else 'rules 加载失败: '+outcomes['rules'].error,
        rotations=snapshot.document if snapshot is not None else None,
        snapshot_path=snapshot_path,snapshot_readable=snapshot is None or snapshot.failure!='open',
        spec_order=spec_order)
    from PySide6.QtCore import QFile, QIODevice
    path=application_dir/'_selftest.txt'
    file=QFile(str(path))
    written=False;error=''
    if file.open(QIODevice.OpenModeFlag.WriteOnly|QIODevice.OpenModeFlag.Append):
        try:
            data=report.text.encode('utf-8')
            written=file.write(data)==len(data) and file.flush()
            if not written: error=file.errorString()
        finally:
            file.close()
    else:
        error=file.errorString()
    return SelftestCommandResult(0,report,path,written,error)
