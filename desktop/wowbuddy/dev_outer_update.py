"""已校验外层下载接入原单文件替换流程；不使用目录版交换器。"""
from pathlib import Path
import shutil
from .dev_version import VERSION
from .github_outer import MANIFEST_NAME,verify_outer,validate_manifest
from .release_identity import validated_outer_target,file_sha256
from .updater import UpdateInfo,VerifiedDownload,part_file_path
from .update_handoff import TestProgramScope,QtWin32HandoffBackend,LocalHandoffProbe
import json


def install_outer(staged,inner,outer,*,current_version=VERSION,arguments=(),
                  quit_callback=lambda:None,on_status=lambda text:None,on_log=lambda text:None,
                  on_replaced=lambda text:None,restart=True,backend_factory=QtWin32HandoffBackend):
    """调用者须在GUI线程调用并阻止重入；仅验证过的自有外层是替换目标。"""
    inner=Path(inner)
    target=validated_outer_target(str(outer),inner)
    if target is None:raise ValueError('当前程序没有匹配的自有外层，拒绝替换')
    original_sha=file_sha256(target)
    staged=Path(staged).absolute()
    manifest=json.loads((staged.parent/MANIFEST_NAME).read_text('utf8'))
    validate_manifest(manifest,manifest.get('version'))
    info=UpdateInfo(ok=True,current_version=current_version,version=manifest['version'],
                    size=manifest['size'],sha256=manifest['sha256'])
    if not info.has_update:raise ValueError('外层候选版本没有高于当前版本')
    verify_outer(staged,manifest)
    part=Path(part_file_path(str(target)))
    probe=LocalHandoffProbe()
    for path in (target.parent,target,staged,part,Path(str(target)+'.old')):
        state=probe.inspect(str(path))
        if state.has_reparse or (state.exists and state.is_file and state.links!=1):
            raise ValueError('外层更新路径包含链接或重解析点')
    # 独占创建：不覆盖已有的未确认part文件。
    with part.open('xb') as destination:
        try:
            with staged.open('rb') as source:shutil.copyfileobj(source,destination,1024*1024)
        except BaseException:
            destination.close();part.unlink();raise
    try:
        verify_outer(part,manifest)
        if validated_outer_target(str(target),inner)!=target or file_sha256(target)!=original_sha:
            raise ValueError('暂存期间当前外层已经改变')
        verified=VerifiedDownload(str(part),str(target),info,manifest['size'],manifest['sha256'])
        scope=TestProgramScope(str(target.parent),str(target))
        return backend_factory(scope).execute(verified,application_arguments=['WowBuddyDev',*arguments],
            quit_callback=quit_callback,on_status=on_status,on_log=on_log,
            on_replaced=on_replaced,restart=restart)
    except BaseException:
        # 只清除本次建立且仍与候选摘要一致的part；异常后不删不明内容。
        if part.is_file() and not part.is_symlink() and file_sha256(part)==manifest['sha256']:part.unlink()
        raise
