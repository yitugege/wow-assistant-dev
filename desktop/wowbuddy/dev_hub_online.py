"""独立循环库来源和覆盖前备份；同步状态机沿用原实现。"""
from pathlib import Path
import hashlib
from .hub_sync import LocalFileBackend

HUB_URL='https://raw.githubusercontent.com/yitugege/wow-assistant-dev/main/assets/rotations.json'

class BackupHubFiles(LocalFileBackend):
    def begin_atomic(self,path):
        target=Path(path)
        if target.exists():
            payload=target.read_bytes()
            backup=target.parent/'backups'/(hashlib.sha256(payload).hexdigest()+'.json')
            backup.parent.mkdir(parents=True,exist_ok=True)
            try:
                with backup.open('xb') as stream:stream.write(payload)
            except FileExistsError:
                if backup.read_bytes()!=payload:raise OSError('循环库备份摘要冲突')
        return super().begin_atomic(path)
