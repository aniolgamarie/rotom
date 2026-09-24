"""从已锁定 npm 平台包投影 ReadSeek 原生入口；仅检查文件，不执行发行物。"""
import hashlib
import json
from pathlib import Path

from .deployment import json_bytes
from .pi_assets import binary_platform
from .process import DependencyError
from .storage import Tree


PACKAGES = {"linux-x86_64": "@jarkkojs/readseek-linux-x64", "linux-arm64": "@jarkkojs/readseek-linux-arm64",
  "darwin-arm64": "@jarkkojs/readseek-darwin-arm64"}


def install_native(repository, stage, piece, platform):
  package = PACKAGES.get(platform)
  if package is None and platform != "darwin-x86_64":
    raise DependencyError("ReadSeek所选平台不受支持")
  prefix = Path(piece["package_path"]).parent
  api = prefix / "node_modules/@jarkkojs/readseek-api"
  with Tree(stage) as target, Tree(repository, private=False) as source:
    metadata = target.read((api / "package.json").as_posix())
    if metadata is None or json.loads(metadata[0]).get("version") != "0.9.16": raise DependencyError("ReadSeek API固定依赖缺失")
    if platform == "darwin-x86_64":
      from .pi_readseek_source import build_source
      build_source(repository, stage)
      return
    candidates = [prefix / "node_modules" / package, api / "node_modules" / package]
    selected = None
    for root in candidates:
      raw = target.read((root / "package.json").as_posix())
      if raw is not None:
        selected = root, json.loads(raw[0]); break
    if selected is None: raise DependencyError("ReadSeek平台原生依赖未安装；运行时不会下载")
    root, metadata = selected
    os_name, arch = platform.split("-", 1)
    if (metadata.get("name") != package or metadata.get("version") != "0.9.16"
        or metadata.get("os") != [os_name] or metadata.get("cpu") != ["x64" if arch == "x86_64" else arch]):
      raise DependencyError("ReadSeek平台包身份不匹配")
    binary = target.read((root / "bin/readseek").as_posix(), max_bytes=128 * 1024 * 1024)
    if binary is None or binary_platform(binary[0]) != platform: raise DependencyError("ReadSeek平台入口格式不匹配")
    license = source.read("agents/pi/build/licenses/readseek/LICENSE.native")
    provenance = source.read("agents/pi/build/licenses/readseek/SOURCE.json")
    if license is None or provenance is None: raise DependencyError("ReadSeek原生许可证来源缺失")
    provenance = json.loads(provenance[0])
    if hashlib.sha256(license[0]).hexdigest() != provenance.get("sha256"): raise DependencyError("ReadSeek原生许可证摘要不匹配")
    target.replace("bin/readseek", binary[0], mode=0o700, expected=None)
    target.write_new("licenses/readseek/LICENSE.native", license[0])
    target.write_new("runtime/readseek-native.json", json_bytes({"schema_version": 1, "package": package, "version": "0.9.16",
      "platform": platform, "entrypoint": "bin/readseek", "binary_sha256": hashlib.sha256(binary[0]).hexdigest(),
      "license_source": provenance, "native_verification": "not-run"}))
