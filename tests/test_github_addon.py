import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import posixpath
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_addon import build
from wowbuddy.github_addon import download_latest, ZIP_NAME, MANIFEST_NAME, REPOSITORY
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.dev_addon_install import install_package

class GithubTests(unittest.TestCase):
    def test_download_random_package_references_and_stable_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package=root/ZIP_NAME
            manifest=build(ROOT/'addon/WowBuddyDev',package,random_names=True)
            manifest['protocol_version']=DEV_VERSION
            with zipfile.ZipFile(package) as archive:
                names=set(archive.namelist()); prefix=manifest['addon_directory']
                for name in names:
                    if name.endswith('.toc'):
                        for line in archive.read(name).decode('utf8').splitlines():
                            if line.strip() and not line.startswith('#'):
                                self.assertIn(prefix+'/'+line.replace('\\','/'),names)
                    if name.endswith('.xml'):
                        for node in ET.fromstring(archive.read(name)).iter():
                            if 'file' in node.attrib:
                                self.assertIn(posixpath.normpath(posixpath.join(posixpath.dirname(name),node.attrib['file'].replace('\\','/'))),names)
                original=sorted(p.read_bytes() for p in (ROOT/'addon/WowBuddyDev').rglob('*.lua'))
                self.assertEqual(original,sorted(archive.read(n) for n in names if n.endswith('.lua')))
            base=f'https://github.com/{REPOSITORY}/releases/download/v0.2.0/'
            release={'tag_name':'v0.2.0','assets':[{'name':n,'browser_download_url':base+n} for n in (ZIP_NAME,MANIFEST_NAME)]}
            responses={base+ZIP_NAME:package.read_bytes(),base+MANIFEST_NAME:json.dumps(manifest).encode()}
            def fetch(url,limit):return responses.get(url,json.dumps(release).encode())
            downloaded=download_latest(root/'data',fetch=fetch)
            client=root/'client';client.mkdir();(client/'Wow.exe').touch()
            first=install_package(downloaded['package'],client)
            second_manifest=build(ROOT/'addon/WowBuddyDev',package,random_names=True)
            package.with_suffix('.manifest.json').write_text(json.dumps(second_manifest),'utf8')
            second=install_package(package,client)
            self.assertEqual(first['target'],second['target'])
            self.assertTrue((Path(second['target'])/(first['addon_directory']+'.toc')).exists())
            self.assertTrue(Path(second['backup']).exists())
            responses[base+ZIP_NAME]=b'corrupt'
            with self.assertRaises(ValueError):download_latest(root/'data',fetch=fetch)
            release['assets'][0]['browser_download_url']='https://example.com/evil.zip'
            with self.assertRaises(ValueError):download_latest(root/'data',fetch=fetch)

if __name__=='__main__':unittest.main()
