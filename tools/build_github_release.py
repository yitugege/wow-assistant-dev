"""构建公开Release插件附件：随机文件名仅作用于产物。"""
from pathlib import Path
import json
import sys
from build_addon import build
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.dev_version import VERSION

def main():
    output=ROOT/'dist/release/WowBuddyDev-addon.zip'
    manifest=build(ROOT/'addon/WowBuddyDev',output,random_names=True)
    manifest.update(protocol_version=DEV_VERSION,version=VERSION,repository='yitugege/wow-assistant-dev')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'package':str(output),'addon_directory':manifest['addon_directory'],'files':len(manifest['members']),'sha256':manifest['sha256']}))

if __name__=='__main__':main()
