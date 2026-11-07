"""自有单文件外层发布与下载校验；本模块不替换或启动程序。"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import tempfile
from .github_client import asset_url
from .github_addon import REPOSITORY,fetch_bytes
from .dev_version import VERSION
from .updater import compare_versions
from .release_identity import read_release_identity,file_sha256
from .launcher_host import WindowsHostAPI
from .launcher import BUSINESS_EXE
from .packages import read_bundle

EXE_NAME='WowBuddyDev-Outer.exe'
MANIFEST_NAME='WowBuddyDev-Outer.manifest.json'
MAX_BYTES=256*1024*1024


def validate_manifest(manifest,version):
    if not isinstance(version,str) or not re.fullmatch(r'\d+(?:\.\d+){1,3}',version):raise ValueError('外层清单版本无效')
    if not isinstance(manifest,dict) or (manifest.get('product'),manifest.get('format'),manifest.get('version'),manifest.get('artifact'))!=('wowbuddy-outer',1,version,EXE_NAME):
        raise ValueError('外层发布清单身份或版本不匹配')
    if type(manifest['format']) is not int:raise ValueError('外层清单格式无效')
    for name in ('sha256','payload_sha256','business_sha256'):
        value=manifest.get(name)
        if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('外层清单摘要无效：'+name)
    if type(manifest.get('size')) is not int or not 0<manifest['size']<=MAX_BYTES:raise ValueError('外层清单大小无效')
    return manifest


def read_payload(path):
    api=WindowsHostAPI()
    load=api.k.LoadLibraryExW;load.argtypes=[C.c_wchar_p,C.c_void_p,C.c_uint32];load.restype=C.c_void_p
    free=api.k.FreeLibrary;free.argtypes=[C.c_void_p];free.restype=C.c_int32
    module=load(str(Path(path).resolve()),None,0x22)
    if not module:raise C.WinError(C.get_last_error())
    try:
        info=api.find_resource(module,200,10)
        if not info:raise ValueError('缺少外层WBD1资源')
        resource=api.load_resource(module,info);size=api.sizeof_resource(module,info)
        pointer=api.lock_resource(resource) if resource else None
        if not pointer or not 0<size<=MAX_BYTES:raise ValueError('外层负载资源无效')
        return api.copy_resource(pointer,size)
    finally:free(module)


def verify_outer(path,manifest):
    validate_manifest(manifest,manifest.get('version'))
    path=Path(path)
    if path.stat().st_size!=manifest['size'] or file_sha256(path)!=manifest['sha256']:
        raise ValueError('外层EXE大小或摘要不匹配')
    identity=read_release_identity(path)
    if identity.payload_sha256!=manifest['payload_sha256'] or identity.business_sha256!=manifest['business_sha256']:
        raise ValueError('外层PE身份与发布清单不匹配')
    payload=read_payload(path)
    if hashlib.sha256(payload).hexdigest()!=identity.payload_sha256:raise ValueError('外层负载摘要不匹配')
    members=read_bundle(payload)
    business=[member for member in members if member.name==BUSINESS_EXE]
    if len(business)!=1 or business[0].sha256!=identity.business_sha256:raise ValueError('外层业务成员摘要不匹配')
    return identity


def check_latest(*,current_version=VERSION,fetch=fetch_bytes):
    release=json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',2*1024*1024))
    if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):raise ValueError('未获取正式外层发布')
    tag=release.get('tag_name','')
    if not isinstance(tag,str) or not re.fullmatch(r'v?\d+(?:\.\d+){1,3}',tag):raise ValueError('外层发布版本号无效')
    version=tag.removeprefix('v')
    result={'current_version':current_version,'version':version,'tag':tag,'kind':'outer',
            'has_update':compare_versions(version,current_version)>0,
            'release_url':f'https://github.com/{REPOSITORY}/releases/tag/{tag}'}
    if result['has_update']:
        result['package_url']=asset_url(release,EXE_NAME)
        result['manifest_url']=asset_url(release,MANIFEST_NAME)
        result['manifest']=validate_manifest(json.loads(fetch(result['manifest_url'],65536)),version)
    return result


def download_checked(info,workspace,*,fetch=fetch_bytes,progress=None):
    if not info.get('has_update') or info.get('kind')!='outer':raise ValueError('没有外层更新可下载')
    manifest=validate_manifest(info['manifest'],info['version'])
    expected='v'+info['version']
    if info['tag'] not in (expected,info['version']):raise ValueError('外层版本与标签不匹配')
    url=asset_url({'tag_name':info['tag'],'assets':[{'name':EXE_NAME,'browser_download_url':info['package_url']}]},EXE_NAME)
    workspace=Path(workspace).resolve();workspace.mkdir(parents=True,exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='outer-download-',dir=workspace))
    path=directory/EXE_NAME;metadata=directory/MANIFEST_NAME
    try:
        options={'progress':progress} if progress is not None else {}
        path.write_bytes(fetch(url,MAX_BYTES,**options))
        verify_outer(path,manifest)
        metadata.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
        return {'kind':'outer','staged':str(path),'manifest':str(metadata),'version':info['version'],'installed':False}
    except BaseException:
        path.unlink(missing_ok=True);metadata.unlink(missing_ok=True);directory.rmdir()
        raise
