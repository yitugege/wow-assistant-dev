"""独立源码发布包标识；本地测试附加层，不冒充原版授权或数字签名。"""
from dataclasses import dataclass
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re

from .launcher import BUSINESS_EXE
from .launcher_host import WindowsHostAPI

SCHEMA = "wowbuddy-source-release-v1"
MANIFEST_RESOURCE = 203
CACHE_NAMESPACE = "WOWBuddy-Source-Local-Test"


@dataclass(frozen=True)
class ReleaseIdentity:
    payload_sha256: str
    business_sha256: str
    business_name: str = BUSINESS_EXE

    @property
    def cache_key(self):
        return self.payload_sha256[:16]

    def encode(self):
        return json.dumps({"schema": SCHEMA, "payload_sha256": self.payload_sha256,
            "business_sha256": self.business_sha256, "business_name": self.business_name},
            ensure_ascii=False, sort_keys=True).encode("utf-8")


def decode_identity(data: bytes) -> ReleaseIdentity:
    if len(data) > 65536:
        raise ValueError("发布标识过大")
    value = json.loads(data)
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("business_name") != BUSINESS_EXE:
        raise ValueError("不是独立源码本地测试发布包")
    fields = [value.get(name) for name in ("payload_sha256", "business_sha256")]
    if any(not isinstance(text, str) or not re.fullmatch("[0-9a-f]{64}", text) for text in fields):
        raise ValueError("发布标识缺少有效摘要")
    return ReleaseIdentity(*fields)


def read_identity_resource(api, module=None) -> ReleaseIdentity:
    info = api.find_resource(module, MANIFEST_RESOURCE, 10)
    if not info:
        raise ValueError("缺少源码发布包标识")
    loaded = api.load_resource(module, info)
    if not loaded:
        raise OSError("发布标识加载失败")
    pointer = api.lock_resource(loaded)
    size = api.sizeof_resource(module, info)
    if not pointer or not 0 < size <= 65536:
        raise ValueError("发布标识资源损坏")
    return decode_identity(api.copy_resource(pointer, size))


def read_release_identity(path: Path | None = None) -> ReleaseIdentity:
    """只以资源方式映射PE；不执行其入口、TLS或DllMain。None为自身模块。"""
    api = WindowsHostAPI()
    if path is None:
        return read_identity_resource(api)
    load = api.k.LoadLibraryExW
    load.argtypes, load.restype = [C.c_wchar_p, C.c_void_p, C.c_uint32], C.c_void_p
    free = api.k.FreeLibrary
    free.argtypes, free.restype = [C.c_void_p], C.c_int32
    module = load(str(Path(path).resolve()), None, 0x22)  # AS_DATAFILE | AS_IMAGE_RESOURCE
    if not module:
        raise C.WinError(C.get_last_error())
    try:
        return read_identity_resource(api, module)
    finally:
        free(module)


def file_sha256(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validated_outer_target(outer: str, inner: Path, *, identity_reader=read_release_identity) -> Path | None:
    """仅识别包含当前业务成品摘要的本地发布包，不能凭任意环境路径授予更新目标。"""
    if not outer:
        return None
    target, business = Path(outer), Path(inner)
    if not target.is_absolute() or target.suffix.lower() != ".exe":
        return None
    try:
        target, business = target.resolve(strict=True), business.resolve(strict=True)
        if target == business or not target.is_file() or business.name != BUSINESS_EXE:
            return None
        identity = identity_reader(target)
        return target if identity.business_sha256 == file_sha256(business) else None
    except (OSError, ValueError):
        return None
