"""独立产品名包含wow：过滤本产品其他实例，避免被原子串规则误选。"""
import ntpath


class AssistantWindowFilter:
    def __init__(self,backend,*,current_executable=None):
        self.backend=backend
        self.current_executable=(ntpath.normcase(ntpath.normpath(str(current_executable)))
                                 if current_executable else None)

    def __getattr__(self,name):
        return getattr(self.backend,name)

    def enum_windows(self,visitor):
        def visit(hwnd):
            pid=self.backend.window_pid(hwnd)
            if pid and pid==self.backend.current_pid():
                return
            path=self.backend.process_path(pid) if pid else ''
            if ntpath.basename(path).casefold()=='wowbuddydev.exe':
                return
            if path and self.current_executable and ntpath.normcase(ntpath.normpath(path))==self.current_executable:
                return
            visitor(hwnd)
        self.backend.enum_windows(visit)
