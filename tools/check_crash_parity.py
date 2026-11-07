"""仅运行本工程dist中的EXE崩溃诊断，比较已留存原程序的可观察结果。"""
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_SHA='7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
CASES=(('--crash-test',0xC0000005,'--crash-test：即将制造一次空指针解引用'),
       ('--crash-test=throw',0xE06D7363,'--crash-test=throw：即将抛出未捕获异常'))


def main():
    executable=ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe'
    sha=hashlib.sha256(executable.read_bytes()).hexdigest()
    cases=[]
    previous=ctypes.windll.kernel32.SetErrorMode(3)
    try:
        for flag,exit_code,last in CASES:
            with tempfile.TemporaryDirectory(prefix='wowbuddy-crash-parity-') as tmp:
                result=subprocess.run([str(executable),flag,'--selftest','--data-dir',tmp],
                    cwd=executable.parent,timeout=25)
                text=(Path(tmp)/'startup.log').read_text('utf8')
                stages=['QApplication 构造完成','全局样式表就绪',last,'异常码=']
                indices=[text.find(stage) for stage in stages]
                checks={'exit_code_match':result.returncode==exit_code,
                        'exception_code_match':f'0x{exit_code:08X}' in text,
                        'runtime_before_crash':min(indices)>=0 and indices==sorted(indices),
                        'last_record_match':f'最后记录=「{last}」' in text,
                        'no_normal_finish':'正常退出' not in text,
                        'selftest_not_executed':not (Path(tmp)/'_selftest.txt').exists()}
                if flag=='--crash-test':checks['null_write_address']='写地址=0x0' in text
                else:checks['throw_module']='KERNELBASE.dll' in text
                cases.append({'flag':flag,'exit_code':result.returncode,'checks':checks,
                              'passed':all(checks.values())})
    finally:ctypes.windll.kernel32.SetErrorMode(previous)
    report={'original_exe_sha256':ORIGINAL_SHA,'current_exe_sha256':sha,
            'baseline':'原内层crash-cli-differential/20261106T171025Z/summary.json及original-*-0.log',
            'cases':cases,'passed':all(c['passed'] for c in cases),
            'scope':'对比历史原程序结果；原EXE未重跑。独立测试子进程，未操作游戏。',
            'remaining':'空指针故障位置是独立原生线程私有代码页，原程序是EXE内地址；不证明CRT极端异常或所有诊断路径一致。'}
    (ROOT/'dist/crash-parity-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=False))
    return int(not report['passed'])

if __name__=='__main__':raise SystemExit(main())
