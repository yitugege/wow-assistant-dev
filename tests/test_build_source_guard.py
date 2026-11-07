"""阻止把旧插件打进新客户端；使用隔离真实文件，不执行打包器。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tools.build_source_guard import snapshot_sources,require_matching_sources


class BuildSourceGuardTests(unittest.TestCase):
    def test_changed_added_deleted_addon_and_new_python_are_rejected(self):
        for mutation in ('change','add','delete','new_python','asset'):
            with self.subTest(mutation=mutation),TemporaryDirectory() as tmp:
                root=Path(tmp)
                files={'run_dev.py':'# entry','desktop/wowbuddy/main.py':'# business',
                       'addon/WowBuddyDev/Core.lua':'-- old','addon/WowBuddyDev/a.toc':'Core.lua',
                       'assets/config.json':'{}'}
                for name,text in files.items():
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                old=snapshot_sources(root)
                self.assertEqual(require_matching_sources(root,old),old)
                if mutation=='change':(root/'addon/WowBuddyDev/Core.lua').write_text('-- fixed')
                elif mutation=='add':(root/'addon/WowBuddyDev/new.lua').write_text('-- new')
                elif mutation=='delete':(root/'addon/WowBuddyDev/Core.lua').unlink()
                elif mutation=='new_python':(root/'desktop/wowbuddy/new.py').write_text('# new')
                else:(root/'assets/config.json').write_text('{"changed":true}')
                with self.assertRaisesRegex(ValueError,'先重建'):require_matching_sources(root,old)

    def test_legacy_manifest_without_addon_coverage_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'run_dev.py').write_text('# entry')
            addon=root/'addon/WowBuddyDev';addon.mkdir(parents=True)
            (addon/'Core.lua').write_text('-- existing')
            current=snapshot_sources(root)
            legacy={k:v for k,v in current.items() if not k.startswith('addon/')}
            with self.assertRaisesRegex(ValueError,'Core.lua'):require_matching_sources(root,legacy)


if __name__=='__main__':unittest.main()
