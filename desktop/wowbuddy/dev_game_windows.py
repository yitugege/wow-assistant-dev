"""独立产品名包含wow：过滤本产品其他实例，避免被原子串规则误选。"""
import ntpath


class AssistantWindowFilter:
    def __init__(self,backend):
        self.backend=backend

    def __getattr__(self,name):
        return getattr(self.backend,name)

    def enum_windows(self,visitor):
        def visit(hwnd):
            pid=self.backend.window_pid(hwnd)
            path=self.backend.process_path(pid) if pid else ''
            if ntpath.basename(path).casefold()=='wowbuddydev.exe':
                return
            visitor(hwnd)
        self.backend.enum_windows(visit)
