"""从明确配置的公开GitHub Release下载配套插件，不使用旧更新服务器。"""
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from wowbuddy.addons.dev_addon_install import read_package
from wowbuddy.core.dev_protocol import DEV_VERSION

from wowbuddy.dev_version import REPOSITORY
ZIP_NAME='WowBuddyDev-addon.zip'
MANIFEST_NAME='WowBuddyDev-addon.manifest.json'


class GithubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed=urlparse(newurl)
        if (parsed.scheme!='https' or parsed.hostname not in
                {'github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
                or parsed.username or parsed.password or parsed.port not in (None,443)):
            raise ValueError('GitHub下载跳转到了非预期地址')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def read_download(response,limit,progress=None):
    try:total=max(0,int(response.headers.get('Content-Length','0')))
    except (TypeError,ValueError):total=0
    if total>limit:raise ValueError('GitHub下载内容超过大小限制')
    chunks=[];received=0
    if progress:progress(0,total)
    while True:
        block=response.read(min(256*1024,limit+1-received))
        if not block:break
        received+=len(block)
        if received>limit:raise ValueError('GitHub下载内容超过大小限制')
        chunks.append(block)
        if progress:progress(received,total)
    return b''.join(chunks)


def fetch_bytes(url,limit,*,progress=None):
    request=Request(url,headers={'User-Agent':'WowBuddyDev','Accept':'application/vnd.github+json'})
    with build_opener(GithubRedirect()).open(request,timeout=30) as response:
        return read_download(response,limit,progress)


def latest_release(fetch, *, repository=REPOSITORY, label='', require_version=True):
    """取仓库最新正式 Release（拒绝草稿与预发布）；require_version 时标签须为版本号。

    返回 (release, tag, version)；version 为去掉前缀 v 的标签。label 用于错误提示（如“客户端”）。
    """
    release=json.loads(fetch(f'https://api.github.com/repos/{repository}/releases/latest',2*1024*1024))
    if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError(f'未获取正式{label}发布')
    tag=release.get('tag_name','')
    if require_version and (not isinstance(tag,str) or not re.fullmatch(r'v?\d+(?:\.\d+){1,3}',tag)):
        raise ValueError(f'{label}发布版本号格式无效')
    return release,tag,tag.removeprefix('v') if isinstance(tag,str) else ''


def asset_url(release,name,*,repository=REPOSITORY,label=''):
    """Release 中唯一同名附件的下载地址，须是本仓库、本版本标签下的 GitHub 地址。"""
    matches=[item for item in release.get('assets',[]) if item.get('name')==name]
    if len(matches)!=1:raise ValueError(f'{label}Release缺少唯一附件：'+name)
    url=matches[0].get('browser_download_url','');parsed=urlparse(url)
    expected='/'+repository+'/releases/download/'+str(release.get('tag_name',''))+'/'+name
    if parsed.scheme!='https' or parsed.netloc!='github.com' or parsed.path!=expected or parsed.query or parsed.fragment:
        raise ValueError(f'{label}附件不属于当前仓库和版本')
    return url


def download_latest(data_dir, *, repository=REPOSITORY, fetch=fetch_bytes, cached=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
        raise ValueError('GitHub仓库名无效')
    release,_,_=latest_release(fetch,repository=repository,label='插件',require_version=False)
    manifest_bytes=fetch(asset_url(release,MANIFEST_NAME,repository=repository,label='插件'),2*1024*1024)
    manifest=json.loads(manifest_bytes)
    if manifest.get('product')!='wowbuddy-dev' or manifest.get('protocol_version')!=DEV_VERSION:
        raise ValueError('发布插件与当前客户端协议不匹配，请更新配套客户端')
    if cached and cached.get('sha256')==manifest.get('sha256'):
        try:
            package=Path(cached['package'])
            read_package(package)
            local=json.loads(package.with_suffix('.manifest.json').read_text('utf8'))
            if local['sha256']==manifest['sha256']:
                return dict(cached,changed=False)
        except (OSError,ValueError,KeyError):
            pass  # 缓存损坏时重新下载；不把旧缓存错误当作线上包可用。
    zip_bytes=fetch(asset_url(release,ZIP_NAME,repository=repository,label='插件'),32*1024*1024)
    downloads=Path(data_dir)/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    # 下载失败或校验失败只清理本次临时目录，不触碰已安装插件。
    with tempfile.TemporaryDirectory(prefix='github-',dir=downloads,delete=False) as temporary:
        folder=Path(temporary)
        package=folder/ZIP_NAME
        try:
            package.write_bytes(zip_bytes)
            package.with_suffix('.manifest.json').write_bytes(manifest_bytes)
            read_package(package)
        except Exception:
            package.unlink(missing_ok=True)
            package.with_suffix('.manifest.json').unlink(missing_ok=True)
            folder.rmdir()
            raise
    return {'package':str(package),'tag':release.get('tag_name',''),
            'release_url':release.get('html_url',''),'repository':repository,
            'sha256':manifest['sha256'],'addon_directory':manifest['addon_directory'],'changed':True}
