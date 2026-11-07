"""自有外层入口；本地授权默认通过，不启动旧SDK线程。"""
from wowbuddy.dev_outer_entry import main

if __name__=='__main__':
    raise SystemExit(main())
