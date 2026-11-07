"""公开客户端Release检查和下载暂存；不自行替换运行程序。"""
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from .github_addon import REPOSITORY,fetch_bytes
from .dev_version import VERSION
from .updater import compare_versions
from .dev_client_update import stage_update

ZIP_NAME='WowBuddyDev-windows-x64.zip'
MANIFEST_NAME='WowBuddyDev-windows-x64.manifest.json'

def asset_url(release,name):
    matches=[item for item in release.get('assets',[]) if item.get('name')==name]
    if len(matches)!=1:raise ValueError('客户端Release缺少唯一附件：'+name)
    url=matches[0].get('browser_download_url','');parsed=urlparse(url)
    expected='/'+REPOSITORY+'/releases/download/'+release['tag_name']+'/'+name
    if parsed.scheme!='https' or parsed.netloc!='github.com' or parsed.path!=expected or parsed.query or parsed.fragment:
        raise ValueError('客户端附件不属于当前仓库和版本')
    return url

def check_latest(*,current_version=VERSION,fetch=fetch_bytes):
    release=json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',2*1024*1024))
    if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError('未获取正式客户端发布')
    tag=release.get('tag_name','')
    if not isinstance(tag,str) or not re.fullmatch(r'v?\d+(?:\.\d+){1,3}',tag):
        raise ValueError('客户端发布版本号格式无效')
    version=tag.removeprefix('v')
    result={'current_version':current_version,'version':version,'tag':tag,
            'has_update':compare_versions(version,current_version)>0,
            'release_url':f'https://github.com/{REPOSITORY}/releases/tag/{tag}'}
    if result['has_update']:
        result['package_url']=asset_url(release,ZIP_NAME)
        result['manifest_url']=asset_url(release,MANIFEST_NAME)
        manifest=json.loads(fetch(result['manifest_url'],4*1024*1024))
        if (manifest.get('product')!='wowbuddy-client' or manifest.get('format')!=1
                or manifest.get('version')!=version or manifest.get('artifact')!=ZIP_NAME
                or not re.fullmatch(r'[0-9a-f]{64}',manifest.get('sha256',''))):
            raise ValueError('客户端发布清单身份、版本或摘要不符')
        result['manifest']=manifest
    return result

def download_checked(info,workspace,*,fetch=fetch_bytes):
    if not info.get('has_update'):raise ValueError('没有更新可下载')
    # 使用检查时固定的版本清单，下载期间latest变化不混用附件。
    workspace=Path(workspace).absolute();workspace.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='client-download-',dir=workspace) as tmp:
        package=Path(tmp)/ZIP_NAME
        package.write_bytes(fetch(info['package_url'],256*1024*1024))
        manifest=package.with_suffix('.manifest.json')
        manifest.write_text(json.dumps(info['manifest']),'utf8')
        staged=stage_update(package,manifest,workspace)
    return {'staged':str(staged),'version':info['version'],'installed':False}

def run_check_command(data_dir,*,check=check_latest):
    data_dir=Path(data_dir);data_dir.mkdir(parents=True,exist_ok=True)
    try:
        result=check();code=10 if result['has_update'] else 0
        text=f"== 自动更新 ==\n当前版本 {result['current_version']}\n线上版本 {result['version']}\n"
        text+='有新版本\n' if result['has_update'] else '已是最新版本\n'
        report={'ok':True,**result,'exit_code':code}
    except Exception as error:
        code=1;text='检查失败：'+str(error)+'\n';report={'ok':False,'error':str(error),'exit_code':code}
    (data_dir/'_update.txt').write_text(text,'utf8')
    (data_dir/'update-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return code
