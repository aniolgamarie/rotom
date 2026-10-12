"""Pi运行包内容收据；目录激活复用公共安全文件系统原语。"""

import hashlib
import json
import os
from pathlib import Path
import stat

from .deployment import json_bytes
from .paths import PathError, relative_path
from .runtime_packages import owned, rename_directory, remove_backup
from .storage import Conflict, Tree
from .schema import ConfigError


MARKERS = {".agentcfg-ready", ".agentcfg-receipt.json"}
MAX_RECEIPT = 16 * 1024 * 1024
MAX_ENTRIES = 65536
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_PACKAGE_DOCUMENT = 1024 * 1024
MAX_DEPTH = 128
MAX_PATH = 4096
MAX_GRAPH_VISITS = 2 * (MAX_ENTRIES + len(MARKERS))


def _bounded_path(root, path, *, directory=False):
  relative = path.relative_to(root)
  if relative.parts and len(relative.as_posix().encode("utf-8", "strict")) > MAX_PATH:
    raise Conflict("Pi运行包路径超过校验上限")
  if directory and len(relative.parts) > MAX_DEPTH:
    raise Conflict("Pi运行包目录深度超过校验上限")


def inventory(root):
  result = {}
  count, total = 0, 0
  root = root.absolute()
  if root.is_symlink() or not root.is_dir():
    raise Conflict("Pi运行包根目录无效")

  def walk(directory):
    nonlocal count, total
    _bounded_path(root, directory, directory=True)
    entries = []
    with os.scandir(directory) as iterator:
      for entry in iterator:
        path = Path(entry.path)
        relative = path.relative_to(root).as_posix()
        if relative in MARKERS:
          continue
        _bounded_path(root, path)
        if count >= MAX_ENTRIES:
          raise Conflict("Pi运行包条目超过校验上限")
        count += 1
        entries.append(entry)
    for entry in sorted(entries, key=lambda item: os.fsencode(item.name)):
      path = Path(entry.path)
      relative = path.relative_to(root).as_posix()
      info = entry.stat(follow_symlinks=False)
      if info.st_uid != os.geteuid() or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o6022):
        raise Conflict("Pi运行文件的所有权或权限无效")
      if stat.S_ISLNK(info.st_mode):
        # npm的bin链接只允许指向当前sealed树，记录字面目标用于后续复核。
        target = os.readlink(path)
        if not path.resolve(strict=True).is_relative_to(root):
          raise Conflict("Pi运行包链接越界")
        result[relative] = {"kind": "link", "target": target}
      elif stat.S_ISDIR(info.st_mode):
        _bounded_path(root, path, directory=True)
        result[relative] = {"kind": "directory"}
        walk(path)
      elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        # 原stat先预留本文件及总量，未通过前不open或构造hash。
        reserved = info.st_size
        if reserved > MAX_FILE or reserved > MAX_TOTAL - total:
          raise Conflict("Pi运行文件超过校验大小上限")
        total += reserved
        with Tree(root) as tree:
          with tree.open_read(relative, max_bytes=MAX_FILE) as (stream, opened):
            if opened.st_size != reserved:
              raise Conflict("Pi运行文件在散列前发生变化")
            checksum, size = hashlib.sha256(), 0
            while chunk := stream.read(min(1024 * 1024, reserved - size + 1)):
              size += len(chunk)
              if size > reserved or size > opened.st_size or size > MAX_FILE:
                raise Conflict("Pi运行文件在散列时发生变化")
              checksum.update(chunk)
            if size != reserved or size != opened.st_size:
              raise Conflict("Pi运行文件在散列时发生变化")
        result[relative] = {"kind": "file", "sha256": checksum.hexdigest(), "mode": stat.S_IMODE(opened.st_mode)}
      else:
        raise Conflict("Pi运行包包含不支持的文件类型")
  walk(root)
  return result


def _package_graph(root):
  """遍历完整运行树中的 node_modules，不能只查锁内路径而遗漏夹带包。"""
  packages = set()
  visits = 0

  def scan(directory):
    nonlocal visits
    _bounded_path(root, directory, directory=True)
    entries = []
    with os.scandir(directory) as iterator:
      for entry in iterator:
        _bounded_path(root, Path(entry.path))
        if visits >= MAX_GRAPH_VISITS:
          raise Conflict("Pi安装图遍历超过校验上限")
        visits += 1
        entries.append(entry)
    return entries

  def package(path):
    if path.is_symlink() or not path.is_dir() or path.name.startswith("."):
      raise Conflict("Pi安装图包含非法包目录")
    _bounded_path(root, path, directory=True)
    packages.add(path.relative_to(root).as_posix())

  def modules(directory):
    if directory.is_symlink(): raise Conflict("Pi安装图包含链接模块目录")
    for child in sorted(Path(entry.path) for entry in scan(directory)):
      if child.name == ".bin":
        # .bin 内链接的 in-tree 边界仍由完整 inventory 核对，不产生执行授权。
        if child.is_symlink() or not child.is_dir(): raise Conflict("Pi安装图的bin目录无效")
      elif child.name == ".package-lock.json":
        if child.is_symlink() or not child.is_file(): raise Conflict("Pi安装图的npm元数据无效")
      elif child.name.startswith("@"):
        if child.is_symlink() or not child.is_dir(): raise Conflict("Pi安装图的scope目录无效")
        for scoped in sorted(Path(entry.path) for entry in scan(child)): package(scoped)
      else:
        package(child)

  def walk(directory):
    for entry in scan(directory):
      path = Path(entry.path)
      bin_command = directory.name == ".bin" and directory.parent.name == "node_modules" and not entry.is_dir(follow_symlinks=False)
      if entry.name == "node_modules" and not bin_command:
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False): raise Conflict("Pi安装图的模块目录无效")
        modules(path)
      if entry.is_dir(follow_symlinks=False): walk(path)

  walk(root)
  return packages


def _package_document(raw):
  try:
    value = json.loads(raw)
    if not isinstance(value, dict): raise ValueError()
    return value
  except (ValueError, UnicodeError):
    raise Conflict("Pi安装包清单无效") from None


def validate_installed(root, piece, *, identity=None, lock_identity=None, platform=None, toolchains=None, binding_identity=None):
  if "durable_owner" in piece and any(value is None for value in (identity, lock_identity, platform, toolchains, binding_identity)):
    raise Conflict("Pi owner材料缺少同次身份上下文")
  with Tree(root) as tree:
    package = tree.read(piece["package_path"], max_bytes=MAX_PACKAGE_DOCUMENT)
    resolution = tree.read(piece["lock_path"], max_bytes=MAX_PACKAGE_DOCUMENT)
    if not package or not resolution:
      raise Conflict("Pi运行包缺少原始完整锁")
    if (hashlib.sha256(package[0]).hexdigest() != piece["package_json_digest"]
        or hashlib.sha256(resolution[0]).hexdigest() != piece["package_lock_digest"]):
      raise Conflict("Pi安装修改了完整锁")
    locked = _package_document(resolution[0])
    prefix = Path(piece["package_path"]).parent
    installed = _package_graph(root)
    expected = {(prefix / relative_path(name)).as_posix() for name in locked["packages"] if name}
    if installed - expected: raise Conflict("Pi安装图包含未锁定包")
    for name, record in locked["packages"].items():
      if not name:
        continue
      package_root = (prefix / relative_path(name)).as_posix()
      if package_root not in installed:
        if record.get("optional"): continue
        raise Conflict("Pi安装图缺少锁定包")
      target = package_root + "/package.json"
      raw = tree.read(target, max_bytes=MAX_PACKAGE_DOCUMENT)
      if raw is None: raise Conflict("Pi安装包缺少清单")
      actual = _package_document(raw[0])
      # 别名使用锁的显式 name；普通/作用域/嵌套及 bundled 包按最后模块路径推导。
      expected_name = record.get("name", name.rsplit("node_modules/", 1)[-1])
      if not isinstance(expected_name, str) or not expected_name or not isinstance(record.get("version"), str) or actual.get("version") != record["version"] or actual.get("name") != expected_name:
        raise Conflict("Pi已安装依赖与锁不一致")
    if "runtime_files" in piece:
      from .pi_license_bundle import validate_installed as validate_licenses
      validate_licenses(root, piece, locked)
      from .pi_runtime_files import validate_files
      from .pi_modern_launcher import validate_profile, REQUIRED
      if "durable_owner" in piece:
        from .pi_owner_origin import validate_installed_owner_origin
        try:
          validate_installed_owner_origin(root, piece, identity=identity, lock_identity=lock_identity, platform=platform,
            toolchains=toolchains, binding_identity=binding_identity)
        except ValueError:
          raise Conflict("Pi owner材料无效") from None
        validate_files(root, piece["runtime_files"], python_bundle=piece.get("python_bundle"), durable_owner=piece["durable_owner"])
      else:
        validate_files(root, piece["runtime_files"], python_bundle=piece.get("python_bundle"))
      validate_profile(root, piece)
      required = [piece["entrypoint"], *REQUIRED]
    else:
      required = [piece["entrypoint"], "runtime/launch.mjs", "runtime/resource-loader.mjs", "runtime/profile.json",
        "supervisor/scripts/pi-supervisor.py", "supervisor/scripts/pi-control.py", "supervisor/scripts/pi-exec.py", "supervisor/src/agentcfg/pi_host.py"]
    for name in required:
      if tree.read(name) is None:
        raise Conflict("Pi必要运行入口缺失")
    if piece["engine"] == "bun" and any(tree.read("runtime/" + name) is None for name in ("bunfig.locked.toml", "tsconfig.locked.json")):
      raise Conflict("Bun封闭加载配置缺失")
    for kind, entries in piece["resource_manifest"].items():
      for entry in entries:
        path = root / relative_path(entry["path"])
        if path.is_symlink() or not path.exists() or (kind != "skills" and not path.is_file()):
          raise Conflict("Pi声明资源入口缺失")
        if kind == "skills" and path.is_dir() and tree.read(entry["path"] + "/SKILL.md") is None:
          raise Conflict("Pi技能入口缺失")


def seal(root, identity, lock_identity, piece, *, toolchains, binding_identity=None):
  from .pi_dependencies import digest, platform_id
  if "durable_owner" in piece:
    validate_installed(root, piece, identity=identity, lock_identity=lock_identity, platform=platform_id(), toolchains=toolchains,
      binding_identity=binding_identity)
  else:
    validate_installed(root, piece)
  if "runtime_files" in piece:
    from .pi_modern_launcher import validate_profile
    if binding_identity is None: raise Conflict("Pi现代运行包缺少绑定身份")
    validate_profile(root, piece, identity=identity, lock_identity=lock_identity, toolchains=toolchains, profile_id=binding_identity["profile"])
  receipt = {"schema_version": 1, "status": "installed", "identity": identity, "lock_identity": lock_identity,
    "slice_identity": piece["identity"], "slice": piece, "files": inventory(root),
    "platform": platform_id(), "toolchains": dict(toolchains), "toolchain_identity": digest(toolchains)}
  if binding_identity is not None:
    receipt.update(schema_version=2, binding_identity=dict(binding_identity))
  with Tree(root) as tree:
    tree.write_state(".agentcfg-receipt.json", json_bytes(receipt))
    tree.write_state(".agentcfg-ready", (identity + "\n").encode())


def _validated_receipt(root, identity):
  with Tree(root) as tree:
    raw = tree.read(".agentcfg-receipt.json", max_bytes=MAX_RECEIPT)
    if raw is None or raw[1] != 0o600:
      return None
    receipt = json.loads(raw[0])
  from .pi_catalog import validate
  validate("runtime-receipt", receipt)
  from .pi_dependencies import digest, platform_id
  base_runtime = digest({"lock_identity": receipt["lock_identity"], "slice_identity": receipt["slice_identity"],
    "platform": receipt["platform"], "toolchain_identity": receipt["toolchain_identity"]})
  if type(receipt["schema_version"]) is not int:
    return None
  if receipt["schema_version"] == 2:
    binding = receipt["binding_identity"]
    if (binding["runtime"] != base_runtime or binding["lock"] != receipt["lock_identity"]
        or binding["slice"] != digest(receipt["slice"]) or binding["platform"] != receipt["platform"]
        or binding["adapter_version"] != "pi-1" or digest(binding) != identity):
      return None
  elif base_runtime != identity:
    return None
  if (receipt["identity"] != identity or receipt["slice_identity"] != receipt["slice"]["identity"]
      or digest({k: v for k, v in receipt["slice"].items() if k != "identity"}) != receipt["slice_identity"]
      or receipt["platform"] != platform_id() or receipt["toolchain_identity"] != digest(receipt["toolchains"])
      or receipt["files"] != inventory(root)):
    return None
  if "durable_owner" in receipt["slice"]:
    validate_installed(root, receipt["slice"], identity=identity, lock_identity=receipt["lock_identity"], platform=receipt["platform"],
      toolchains=receipt["toolchains"], binding_identity=receipt.get("binding_identity"))
  else:
    validate_installed(root, receipt["slice"])
  if receipt["schema_version"] == 2:
    from .pi_modern_launcher import validate_profile
    validate_profile(root, receipt["slice"], identity=identity, lock_identity=receipt["lock_identity"],
      toolchains=receipt["toolchains"], profile_id=receipt["binding_identity"]["profile"])
  return receipt, raw[0]


def status(root, identity):
  if not root.exists() and not root.is_symlink():
    return "missing"
  try:
    if not owned(root, identity):
      return "damaged"
    return "installed" if _validated_receipt(root, identity) is not None else "damaged"
  except (OSError, ValueError, KeyError, TypeError, Conflict, PathError, ConfigError):
    return "damaged"


def recover_repair(final, identity):
  backup = final.parent / (".repair-" + identity)
  if backup.exists() or backup.is_symlink():
    if not owned(backup, identity):
      raise Conflict("Pi修复槽所有权无效")
    if not final.exists() and not final.is_symlink():
      rename_directory(backup, final)
    elif status(final, identity) == "installed":
      remove_backup(backup, identity)
    else:
      raise Conflict("Pi运行包修复尚待处理")


def activate(stage, final, identity):
  if status(stage, identity) != "installed":
    raise Conflict("Pi暂存安装未通过验证")
  backup = final.parent / (".repair-" + identity)
  if final.exists() or final.is_symlink():
    if not owned(final, identity):
      raise Conflict("不能接管未知Pi运行目录")
    rename_directory(final, backup)
  try:
    rename_directory(stage, final)
  except BaseException:
    if backup.exists() and not final.exists():
      rename_directory(backup, final)
    raise
  recover_repair(final, identity)
