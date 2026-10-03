"""离线核验权限运行包构建输入；本模块不安装、不解压、不执行输入。"""

import hashlib
import json
from pathlib import Path
import stat

from jsonschema import Draft202012Validator

from .schema import ConfigError


BUILD_SCRIPT_PATHS = (
  "agents/omp/build-permission-control.py", "src/agentcfg/omp_permission_build.py",
  "src/agentcfg/omp_permission_build_inputs.py", "schemas/omp-permission-build-inputs.schema.json",
)


class BuildInputUnavailable(Exception):
  """只输出固定原因，不暴露本机路径或原始文件正文。"""

  exit_code = 5

  def __init__(self, code):
    self.code = code
    super().__init__(code)


def _unique_object(pairs):
  value = {}
  for key, item in pairs:
    if key in value:
      raise ConfigError("omp-build-input-duplicate-key")
    value[key] = item
  return value


def read_build_input_lock(path, schema):
  """先作封闭结构校验，再验证名称及摘要关联，绝不回显无效值。"""
  try:
    raw = Path(path).read_text(encoding="utf-8")
    value = json.loads(raw, object_pairs_hook=_unique_object,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
  except OSError:
    raise BuildInputUnavailable("omp-build-input-lock-unavailable") from None
  except (ValueError, UnicodeError):
    raise ConfigError("omp-build-input-json") from None
  if not Draft202012Validator(schema).is_valid(value):
    raise ConfigError("omp-build-input-schema")
  tools = value["tools"]
  if len({item["name"] for item in tools}) != len(tools) or not any(item["name"] == "bun" for item in tools):
    raise ConfigError("omp-build-input-tools")
  for entries in (tools, value["dependencyArtifacts"]):
    if len({item["cacheKey"] for item in entries}) != len(entries):
      raise ConfigError("omp-build-input-duplicate-asset")
    if any(item["cacheKey"] != "sha256/" + item["sha256"] for item in entries):
      raise ConfigError("omp-build-input-cache-identity")
  return value


def _ordinary_path(path, *, directory=False):
  # 不 resolve 后再检查，以免先吞掉符号链接边界。
  path = Path(path).absolute()
  try:
    for ancestor in reversed(path.parents):
      if not stat.S_ISDIR(ancestor.lstat().st_mode):
        raise BuildInputUnavailable("omp-build-input-path-boundary")
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
      raise BuildInputUnavailable("omp-build-input-path-boundary")
  except OSError:
    raise BuildInputUnavailable("omp-build-input-missing") from None
  return path


def verify_file(path, digest, *, size=None):
  """只读计算实际字节，不依据 marker、时间戳或文件名信任资产。"""
  path = _ordinary_path(path)
  value = hashlib.sha256()
  count = 0
  try:
    with path.open("rb") as stream:
      for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
        count += len(chunk)
  except OSError:
    raise BuildInputUnavailable("omp-build-input-unreadable") from None
  if value.hexdigest() != digest or size is not None and count != size:
    raise BuildInputUnavailable("omp-build-input-bytes-mismatch")
  return count


def verify_cache(root, entries):
  """每次校验只接受专用缓存内恰好已声明的内容寻址文件。"""
  root = _ordinary_path(root, directory=True)
  expected = {item["cacheKey"] for item in entries}
  actual = set()
  try:
    children = list(root.iterdir())
    if {p.name for p in children} != {"sha256"}:
      raise BuildInputUnavailable("omp-build-input-cache-shape")
    folder = _ordinary_path(root / "sha256", directory=True)
    for path in folder.iterdir():
      _ordinary_path(path)
      actual.add(path.relative_to(root).as_posix())
  except OSError:
    raise BuildInputUnavailable("omp-build-input-unreadable") from None
  if actual != expected:
    raise BuildInputUnavailable("omp-build-input-cache-closure")
  return sum(verify_file(root / item["cacheKey"], item["sha256"], size=item.get("size"))
    for item in entries)


def verify_build_inputs(value, *, source_archive, dependency_lock, tool_cache, dependency_cache):
  """调用者先通过 read_build_input_lock；这里只核验外部材料的实际字节。"""
  verify_file(source_archive, value["upstreamSource"]["archiveSha256"])
  verify_file(dependency_lock, value["dependencyLock"]["sha256"])
  return {
    "toolCount": len(value["tools"]),
    "dependencyArtifactCount": len(value["dependencyArtifacts"]),
    "toolBytes": verify_cache(tool_cache, value["tools"]),
    "dependencyBytes": verify_cache(dependency_cache, value["dependencyArtifacts"]),
  }
