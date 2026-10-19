"""Pi运行包内容收据；目录激活复用公共安全文件系统原语。"""

import hashlib
import os
from pathlib import Path
import stat

from .deployment import json_bytes
from .paths import PathError, relative_path
from .runtime_packages import owned, rename_directory, remove_backup
from .storage import Conflict, Tree
from .schema import ConfigError


MARKERS = {".agentcfg-ready", ".agentcfg-receipt.json"}


def inventory(root):
  result = {}
  root = root.absolute()
  if root.is_symlink() or not root.is_dir():
    raise Conflict("Pi运行包根目录无效")

  def walk(directory):
    for entry in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
      path = Path(entry.path)
      relative = path.relative_to(root).as_posix()
      if relative in MARKERS:
        continue
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
        result[relative] = {"kind": "directory"}
        walk(path)
      elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        with Tree(root) as tree:
          with tree.open_read(relative) as (stream, opened):
            checksum, size = hashlib.sha256(), 0
            while chunk := stream.read(1024 * 1024):
              size += len(chunk)
              if size > opened.st_size: raise Conflict("Pi运行文件在散列时发生变化")
              checksum.update(chunk)
            if size != opened.st_size: raise Conflict("Pi运行文件在散列时发生变化")
        result[relative] = {"kind": "file", "sha256": checksum.hexdigest(), "mode": stat.S_IMODE(opened.st_mode)}
      else:
        raise Conflict("Pi运行包包含不支持的文件类型")
  walk(root)
  return result


def validate_installed(root, piece):
  from .pi_dependencies import _json, digest, validate_installed_packages, validate_package_lock
  with Tree(root) as tree:
    package = tree.read("package.json")
    resolution = tree.read("package-lock.json")
    if not package or not resolution:
      raise Conflict("Pi运行包缺少原始完整锁")
    if (hashlib.sha256(package[0]).hexdigest() != piece["package_json_digest"]
        or hashlib.sha256(resolution[0]).hexdigest() != piece["package_lock_digest"]):
      raise Conflict("Pi安装修改了完整锁")
    if (piece["identity"] != digest({key: value for key, value in piece.items() if key != "identity"})
        or _json(package[0])["dependencies"] != piece["dependencies"]):
      raise Conflict("Pi安装配方身份不一致")
    locked = _json(resolution[0])
    validate_package_lock(locked, piece["dependencies"])
    validate_installed_packages(root, locked, piece["script_audits"])
    for name in piece["required_files"]:
      raw = tree.read(relative_path(name).as_posix())
      if raw is None or not raw[0].strip():
        raise Conflict("Pi官方入口、所选资源或许可缺失")


def seal(root, identity, lock_identity, piece, *, toolchains):
  from .pi_dependencies import digest, platform_id
  validate_installed(root, piece)
  files = inventory(root)
  receipt = {"schema_version": 2, "status": "installed", "identity": identity, "lock_identity": lock_identity,
    "profile_identity": piece["identity"], "profile": piece, "files": files, "manifest_digest": digest(files),
    "platform": platform_id(), "toolchains": dict(toolchains), "toolchain_identity": digest(toolchains)}
  with Tree(root) as tree:
    tree.write_state(".agentcfg-receipt.json", json_bytes(receipt))
    tree.write_state(".agentcfg-ready", (identity + "\n").encode())


def status(root, identity):
  if not root.exists() and not root.is_symlink():
    return "missing"
  try:
    from .pi_dependencies import _json, digest, platform_id
    if not owned(root, identity):
      return "damaged"
    with Tree(root) as tree:
      raw = tree.read(".agentcfg-receipt.json")
      if raw is None or raw[1] != 0o600:
        return "damaged"
      receipt = _json(raw[0])
    if (set(receipt) != {"schema_version", "status", "identity", "lock_identity", "profile_identity", "profile", "files",
          "manifest_digest", "platform", "toolchains", "toolchain_identity"}
        or receipt["schema_version"] != 2 or receipt["status"] != "installed"
        or receipt["identity"] != identity or receipt["profile_identity"] != receipt["profile"]["identity"]
        or digest({k: v for k, v in receipt["profile"].items() if k != "identity"}) != receipt["profile_identity"]
        or receipt["platform"] != platform_id() or receipt["toolchain_identity"] != digest(receipt["toolchains"])
        or digest({"profile_identity": receipt["profile_identity"],
          "platform": receipt["platform"], "toolchains": receipt["toolchains"]}) != identity
        or receipt["manifest_digest"] != digest(receipt["files"])
        or receipt["files"] != inventory(root)):
      return "damaged"
    validate_installed(root, receipt["profile"])
    return "installed"
  except (OSError, ValueError, KeyError, TypeError, Conflict, PathError, ConfigError, RecursionError):
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
