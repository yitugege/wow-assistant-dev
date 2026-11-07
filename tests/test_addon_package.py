from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile
from tools.build_addon import build, collect_files


class AddonPackageTests(unittest.TestCase):
    def test_package_uses_fixed_folder_and_exact_source_bytes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (source/'WowBuddyDev.toc').write_text('## Title: fixture\nCore.lua\n', 'utf8')
            (source/'Core.lua').write_bytes(b'-- fixture\n')
            first = build(source, root/'one.zip')
            second = build(source, root/'two.zip')
            self.assertEqual(first['sha256'], second['sha256'])
            with zipfile.ZipFile(root/'one.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'WowBuddyDev/WowBuddyDev.toc','WowBuddyDev/Core.lua'})
                self.assertEqual(archive.read('WowBuddyDev/Core.lua'), b'-- fixture\n')

    def test_toc_cannot_reference_outside_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'; source.mkdir()
            (root/'outside.lua').write_text('-- external', 'utf8')
            (source/'WowBuddyDev.toc').write_text('../outside.lua\n', 'utf8')
            with self.assertRaises(ValueError): collect_files(source)


if __name__ == '__main__': unittest.main()
