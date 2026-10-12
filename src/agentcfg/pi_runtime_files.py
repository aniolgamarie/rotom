"""现代运行包的仓库源码白名单；锁住原始与转换后字节，不扫描扩大选择。"""

import hashlib
import os
from pathlib import Path
import re
import stat

from .paths import relative_path
from .schema import ConfigError
from .storage import Conflict, Tree


DECLARATION = {"source", "path", "transform"}
LOCKED = DECLARATION | {"input_digest", "digest", "mode"}
GENERATED = ("runtime/profile.json", "runtime/commands.json")
HEX = re.compile(r"[0-9a-f]{64}")
DELEGATE_ASSETS = frozenset({"shared/skills/model-delegate/schemas/" + name + "-v2.json"
  for name in ("request", "event", "context", "feedback", "receipt")} | {
  "shared/skills/model-delegate/presets/" + name + ".md"
  for name in ("scout", "plan", "general", "challenge", "review", "research", "context")})



def _validate(rows, *, locked):
  if not isinstance(rows, list) or not rows or len(rows) > 2048:
    raise ValueError()
  names = set()
  for row in rows:
    if not isinstance(row, dict) or set(row) != (LOCKED if locked else DECLARATION): raise ValueError()
    source, target = row["source"], row["path"]
    if not isinstance(source, str) or not isinstance(target, str): raise ValueError()
    if relative_path(source).as_posix() != source or relative_path(target).as_posix() != target: raise ValueError()
    if source.startswith("agents/pi/runtime/"):
      name = source.removeprefix("agents/pi/runtime/")
      if not re.fullmatch(r"[a-z][a-z0-9-]*\.(ts|json|toml|sb)", name): raise ValueError()
      expected = "runtime/" + (name[:-3] + ".mjs" if name.endswith(".ts") else name)
      transform = "ts-module" if name.endswith(".ts") else "copy"
    elif source in DELEGATE_ASSETS:
      expected, transform = "supervisor/" + source, "copy"
    elif source == "agents/pi/packages/durable-service/src/owner-message.ts":
      expected, transform = "runtime/durable-owner-message.mjs", "ts-module"
    elif re.fullmatch(r"agents/pi/build/licenses/pi-modern/[A-Za-z0-9][A-Za-z0-9_.-]*", source):
      expected, transform = source.removeprefix("agents/pi/build/"), "copy"
    elif re.fullmatch(r"(?:src/agentcfg/[a-z_][a-z0-9_]*\.py|(?:agents/pi/)?schemas/[a-z0-9_-]+(?:\.schema)?\.json|scripts/pi-[a-z-]+(?:\.py|\.c)?)", source):
      expected, transform = "supervisor/" + source, "copy"
    else:
      raise ValueError()
    if (target != expected or row["transform"] != transform or target in names
        or target in (*GENERATED, "runtime/launch.mjs", "runtime/resource-loader.mjs")):
      raise ValueError()
    names.add(target)
    if locked and (type(row["mode"]) is not int or row["mode"] != 0o600
        or any(not isinstance(row[key], str) or not HEX.fullmatch(row[key]) for key in ("input_digest", "digest"))):
      raise ValueError()
  # 顺序也是锁内容的一部分；安装输出不依赖调用者提供的声明顺序。
  return sorted(rows, key=lambda row: row["path"])


def validate_manifest(rows):
  try:
    if _validate(rows, locked=True) != rows: raise ValueError()
  except Exception:
    raise ConfigError("pi-runtime-files-invalid") from None


def _content(tree, row):
  raw = tree.read(row["source"], max_bytes=16 * 1024 * 1024)
  if raw is None: raise ValueError()
  data = raw[0]
  # 仅转换仓库自身可执行ECMAScript子集的相对模块引用，不触碰npm宿主。
  transformed = re.sub(rb'([\"\x27]\./[a-z0-9_-]+)\.ts([\"\x27])', rb'\1.mjs\2', data) if row["transform"] == "ts-module" else data
  return data, transformed


def lock_files(repository, declarations):
  try:
    rows = _validate(declarations, locked=False)
    result = []
    with Tree(Path(repository), private=False) as source:
      for row in rows:
        raw, data = _content(source, row)
        result.append({**row, "input_digest": hashlib.sha256(raw).hexdigest(),
          "digest": hashlib.sha256(data).hexdigest(), "mode": 0o600})
    return result
  except Exception:
    raise ConfigError("pi-runtime-files-invalid") from None


def verify_sources(repository, rows):
  validate_manifest(rows)
  declarations = [{key: row[key] for key in DECLARATION} for row in rows]
  if lock_files(repository, declarations) != rows:
    raise ConfigError("pi-runtime-files-stale")


def install_files(repository, stage, rows):
  validate_manifest(rows)
  prepared = []
  try:
    with Tree(Path(repository), private=False) as source:
      for row in rows:
        raw, data = _content(source, row)
        if hashlib.sha256(raw).hexdigest() != row["input_digest"] or hashlib.sha256(data).hexdigest() != row["digest"]:
          raise ValueError()
        prepared.append((row["path"], data))
  except Exception:
    raise ConfigError("pi-runtime-files-stale") from None
  # 全部输入核对成功后才写stage；调用方仍负责整个运行包的激活事务。
  with Tree(Path(stage)) as target:
    for path, data in prepared:
      target.write_state(path, data)


def validate_files(root, rows, *, generated=GENERATED, python_bundle=None, durable_owner=None):
  try:
    validate_manifest(rows)
    expected = {row["path"] for row in rows} | set(generated)
    if durable_owner is not None:
      if type(generated) is not tuple or generated != GENERATED: raise ValueError()
      from .pi_modern_launcher import _owner_rows, OWNER_ORIGIN
      _owner_rows(durable_owner, rows, python_bundle, locked=True)
      expected.add(OWNER_ORIGIN)
    directories = {parent.as_posix() for name in expected for parent in Path(name).parents if parent != Path(".")}
    if python_bundle is not None:
      if type(generated) is not tuple or generated != GENERATED: raise ValueError()
      from .pi_python_bundle_runtime import validate_installed_python_bundle
      layout = validate_installed_python_bundle(root, python_bundle)
      expected.update(row["path"] for row in layout["files"])
      directories.update(layout["directories"])
      directories.update(parent.as_posix() for name in expected for parent in Path(name).parents if parent != Path("."))
    actual, actual_directories = set(), set()
    def walk(directory):
      for entry in os.scandir(directory):
        path = Path(entry.path)
        name = path.relative_to(root).as_posix()
        info = entry.stat(follow_symlinks=False)
        if info.st_uid != os.geteuid() or info.st_mode & 0o6022: raise ValueError()
        if stat.S_ISDIR(info.st_mode):
          actual_directories.add(name); walk(path)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
          actual.add(name)
        else:
          raise ValueError()
    root = Path(root)
    # 资产许可证归现有资产安装器及完整收据；仅核对自有现代许可命名空间。
    ancestor = root / "licenses"
    if ancestor.is_symlink(): raise ValueError()
    if ancestor.exists():
      info = ancestor.stat(follow_symlinks=False)
      if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o6022: raise ValueError()
    for name in ("runtime", "supervisor", "licenses/pi-modern"):
      path = root / name
      if path.is_symlink(): raise ValueError()
      if path.exists():
        if not path.is_dir(): raise ValueError()
        actual_directories.add(name)
        if name == "licenses/pi-modern": actual_directories.add("licenses")
        walk(path)
    if actual != expected or actual_directories != directories: raise ValueError()
    with Tree(root) as tree:
      for row in rows:
        raw = tree.read(row["path"], max_bytes=16 * 1024 * 1024)
        if raw is None or hashlib.sha256(raw[0]).hexdigest() != row["digest"] or raw[1] != row["mode"]: raise ValueError()
      for name in generated:
        raw = tree.read(name)
        if raw is None or raw[1] != 0o600: raise ValueError()
      if durable_owner is not None:
        raw = tree.read(OWNER_ORIGIN, max_bytes=16 * 1024 * 1024)
        if raw is None or raw[1] != 0o600: raise ValueError()
  except Exception:
    raise Conflict("Pi所选运行文件与锁不一致") from None
