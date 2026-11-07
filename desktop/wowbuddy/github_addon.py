"""从明确配置的公开GitHub Release下载配套插件，不使用旧更新服务器。"""
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .dev_addon_install import read_package
from .dev_protocol import DEV_VERSION

REPOSITORY='yitugege/wow-assistant-dev'
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


def download_latest(data_dir, *, repository=REPOSITORY, fetch=fetch_bytes, cached=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
        raise ValueError('GitHub仓库名无效')
    release=json.loads(fetch(f'https://api.github.com/repos/{repository}/releases/latest',2*1024*1024))
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('不是正式发布版本')
    assets=release.get('assets',[])
    def asset_url(name):
        found=[item for item in assets if item.get('name')==name]
        if len(found)!=1:
            raise ValueError(f'GitHub Release缺少唯一附件：{name}')
        url=found[0].get('browser_download_url','')
        parsed=urlparse(url)
        if (parsed.scheme!='https' or parsed.netloc!='github.com' or parsed.query or parsed.fragment
                or not parsed.path.startswith('/'+repository+'/releases/download/')):
            raise ValueError('Release附件地址不属于配置的仓库')
        return url
    manifest_bytes=fetch(asset_url(MANIFEST_NAME),2*1024*1024)
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
    zip_bytes=fetch(asset_url(ZIP_NAME),32*1024*1024)
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
