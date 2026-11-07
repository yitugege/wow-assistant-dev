"""外层专用附件合同；真实PE资源验证但不执行试件。"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.github_outer import (EXE_NAME,MANIFEST_NAME,REPOSITORY,check_latest,download_checked,verify_outer,validate_manifest)
from wowbuddy.packages import Member,write_bundle
from wowbuddy.launcher import BUSINESS_EXE
from wowbuddy.release_identity import ReleaseIdentity,file_sha256


class OuterGithubTests(unittest.TestCase):
    def test_missing_outer_asset_never_falls_back_to_directory_release(self):
        release={'tag_name':'v9.0.0','assets':[]}
        with self.assertRaises(ValueError):check_latest(fetch=lambda *args:json.dumps(release).encode())
        self.assertFalse(check_latest(current_version='9.0.0',fetch=lambda *args:json.dumps(release).encode())['has_update'])

    def test_manifest_type_and_version_rejection(self):
        base={'product':'wowbuddy-outer','format':1,'version':'1.0.0','artifact':EXE_NAME,
              'size':50,'sha256':'a'*64,'payload_sha256':'b'*64,'business_sha256':'c'*64}
        for changes in ({'format':True},{'size':True},{'version':None},{'artifact':'WowBuddyDev-windows-x64.zip'},
                        {'sha256':'bad'},{'size':300*1024*1024}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_manifest(base|changes,'1.0.0')

    @unittest.skipUnless((ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe').is_file(),'需要自有PE作为资源载体')
    def test_pinned_download_actual_pe_payload_and_tampering(self):
        from PyInstaller.utils.win32.winresource import add_or_update_resource
        with TemporaryDirectory() as directory:
            root=Path(directory);outer=root/EXE_NAME
            shutil.copy2(ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe',outer)
            business=b'not executed fixture'
            payload=write_bundle([Member(BUSINESS_EXE,business)])
            identity=ReleaseIdentity(hashlib.sha256(payload).hexdigest(),hashlib.sha256(business).hexdigest())
            add_or_update_resource(str(outer),payload,10,[200],[1033])
            add_or_update_resource(str(outer),identity.encode(),10,[203],[1033])
            manifest={'product':'wowbuddy-outer','format':1,'version':'9.0.0','artifact':EXE_NAME,
                'size':outer.stat().st_size,'sha256':file_sha256(outer),'payload_sha256':identity.payload_sha256,'business_sha256':identity.business_sha256}
            self.assertEqual(verify_outer(outer,manifest),identity)
            base=f'https://github.com/{REPOSITORY}/releases/download/v9.0.0/'
            release={'tag_name':'v9.0.0','assets':[{'name':n,'browser_download_url':base+n} for n in (EXE_NAME,MANIFEST_NAME)]}
            calls=[]
            def fetch(url,limit):
                calls.append(url)
                if url==base+EXE_NAME:return outer.read_bytes()
                if url==base+MANIFEST_NAME:return json.dumps(manifest).encode()
                return json.dumps(release).encode()
            info=check_latest(current_version='0.2.4',fetch=fetch)
            staged=download_checked(info,root/'updates',fetch=fetch)
            self.assertFalse(staged['installed']);self.assertEqual(file_sha256(Path(staged['staged'])),manifest['sha256'])
            self.assertEqual(sum('api.github.com' in url for url in calls),1)
            with self.assertRaises(ValueError):download_checked(info|{'package_url':base.replace('v9.0.0','v9.1.0')+EXE_NAME},root/'updates',fetch=fetch)
            add_or_update_resource(str(outer),payload+b'bad',10,[200],[1033])
            manifest.update(size=outer.stat().st_size,sha256=file_sha256(outer))
            before=set((root/'updates').iterdir())
            with self.assertRaisesRegex(ValueError,'EXE大小或摘要'):download_checked(info,root/'updates',fetch=fetch)
            info['manifest']=dict(manifest)
            with self.assertRaisesRegex(ValueError,'负载摘要'):download_checked(info,root/'updates',fetch=fetch)
            self.assertEqual(set((root/'updates').iterdir()),before)


if __name__=='__main__':unittest.main()
