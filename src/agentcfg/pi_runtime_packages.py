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


def inventory(root):
  result = {}
  root = root.absolute()

  def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
      info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

  def unchanged(before, after):
    if identity(before) != identity(after):
      raise Conflict("Pi运行路径在校验期间发生变化")

  def safe(info):
    if info.st_uid != os.geteuid() or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o6022):
      raise Conflict("Pi运行文件的所有权或权限无效")

  directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

  def link_target(root_fd, parent_parts, target):
    # 不通过宿主路径解析链接；绝对目标也只能在固定根内逐段解析。
    def parts(value, parent):
      path = Path(value)
      if path.is_absolute():
        try:
          return list(path.relative_to(root).parts)
        except ValueError:
          raise Conflict("Pi运行包链接越界") from None
      return [*parent, *path.parts]
    pending = parts(target, parent_parts)
    resolved = []
    links = 0
    fd = os.dup(root_fd)
    try:
      while pending:
        name = pending.pop(0)
        if name == ".":
          continue
        if name == "..":
          if not resolved:
            raise Conflict("Pi运行包链接越界")
          resolved.pop()
          os.close(fd)
          fd = os.dup(root_fd)
          for part in resolved:
            child = os.open(part, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = child
          continue
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode):
          links += 1
          if links > 40:
            raise Conflict("Pi运行包链接循环")
          value = os.readlink(name, dir_fd=fd)
          unchanged(before, os.stat(name, dir_fd=fd, follow_symlinks=False))
          pending = parts(value, resolved) + pending
          resolved = []
          os.close(fd)
          fd = os.dup(root_fd)
        elif pending:
          child = os.open(name, directory_flags, dir_fd=fd)
          try:
            unchanged(before, os.fstat(child))
          except BaseException:
            os.close(child)
            raise
          os.close(fd)
          fd = child
          resolved.append(name)
        else:
          unchanged(before, os.stat(name, dir_fd=fd, follow_symlinks=False))
    finally:
      os.close(fd)

  def walk(root_fd, fd, prefix):
    directory_before = os.fstat(fd)
    safe(directory_before)
    with os.scandir(fd) as scanned:
      entries = sorted(scanned, key=lambda item: os.fsencode(item.name))
    for entry in entries:
      relative = "/".join((*prefix, entry.name))
      if relative in MARKERS:
        continue
      info = entry.stat(follow_symlinks=False)
      unchanged(info, os.stat(entry.name, dir_fd=fd, follow_symlinks=False))
      safe(info)
      if stat.S_ISLNK(info.st_mode):
        target = os.readlink(entry.name, dir_fd=fd)
        link_target(root_fd, prefix, target)
        unchanged(info, os.stat(entry.name, dir_fd=fd, follow_symlinks=False))
        result[relative] = {"kind": "link", "target": target}
      elif stat.S_ISDIR(info.st_mode):
        child = os.open(entry.name, directory_flags, dir_fd=fd)
        try:
          unchanged(info, os.fstat(child))
          result[relative] = {"kind": "directory"}
          walk(root_fd, child, (*prefix, entry.name))
          unchanged(info, os.fstat(child))
          unchanged(info, os.stat(entry.name, dir_fd=fd, follow_symlinks=False))
        finally:
          os.close(child)
      elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        source = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
        try:
          opened = os.fstat(source)
          unchanged(info, opened)
          safe(opened)
          checksum, size = hashlib.sha256(), 0
          while chunk := os.read(source, 1024 * 1024):
            size += len(chunk)
            if size > opened.st_size:
              raise Conflict("Pi运行文件在散列时发生变化")
            checksum.update(chunk)
          if size != opened.st_size:
            raise Conflict("Pi运行文件在散列时发生变化")
          unchanged(opened, os.fstat(source))
          unchanged(opened, os.stat(entry.name, dir_fd=fd, follow_symlinks=False))
          result[relative] = {"kind": "file", "sha256": checksum.hexdigest(), "mode": stat.S_IMODE(opened.st_mode)}
        finally:
          os.close(source)
      else:
        raise Conflict("Pi运行包包含不支持的文件类型")
    unchanged(directory_before, os.fstat(fd))

  try:
    with Tree(root) as tree:
      if tree.fd is None:
        raise Conflict("Pi运行包根目录无效")
      original = os.fstat(tree.fd)
      walk(tree.fd, tree.fd, ())
      # 重新逐段验证祖先及路径，不能把已移动的固定句柄当成当前运行根。
      with Tree(root) as current:
        if current.fd is None:
          raise Conflict("Pi运行包根目录身份发生变化")
        unchanged(original, os.fstat(current.fd))
    return result
  except (OSError, PathError):
    raise Conflict("无法安全校验Pi运行包路径") from None

def validate_installed(root, piece):
  with Tree(root) as tree:
    package = tree.read(piece["package_path"])
    resolution = tree.read(piece["lock_path"])
    if not package or not resolution:
      raise Conflict("Pi运行包缺少原始完整锁")
    if (hashlib.sha256(package[0]).hexdigest() != piece["package_json_digest"]
        or hashlib.sha256(resolution[0]).hexdigest() != piece["package_lock_digest"]):
      raise Conflict("Pi安装修改了完整锁")
    locked = json.loads(resolution[0])
    prefix = Path(piece["package_path"]).parent
    for name, record in locked["packages"].items():
      if not name:
        continue
      target = (prefix / relative_path(name) / "package.json").as_posix()
      raw = tree.read(target)
      if raw is None and record.get("optional"):
        continue
      if raw is None or json.loads(raw[0]).get("version") != record["version"]:
        raise Conflict("Pi已安装依赖与锁不一致")
    for name in [piece["entrypoint"], "runtime/launch.mjs", "runtime/resource-loader.mjs", "runtime/profile.json",
        "supervisor/scripts/pi-supervisor.py", "supervisor/scripts/pi-control.py", "supervisor/scripts/pi-exec.py", "supervisor/src/agentcfg/pi_host.py"]:
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


def seal(root, identity, lock_identity, piece, *, toolchains):
  from .pi_dependencies import digest, platform_id
  validate_installed(root, piece)
  receipt = {"schema_version": 1, "status": "installed", "identity": identity, "lock_identity": lock_identity,
    "slice_identity": piece["identity"], "slice": piece, "files": inventory(root),
    "platform": platform_id(), "toolchains": dict(toolchains), "toolchain_identity": digest(toolchains)}
  with Tree(root) as tree:
    tree.write_state(".agentcfg-receipt.json", json_bytes(receipt))
    tree.write_state(".agentcfg-ready", (identity + "\n").encode())


def status(root, identity):
  if not root.exists() and not root.is_symlink():
    return "missing"
  try:
    if not owned(root, identity):
      return "damaged"
    with Tree(root) as tree:
      raw = tree.read(".agentcfg-receipt.json")
      if raw is None or raw[1] != 0o600:
        return "damaged"
      receipt = json.loads(raw[0])
    from .pi_catalog import validate
    validate("runtime-receipt", receipt)
    from .pi_dependencies import digest, platform_id
    if (receipt["identity"] != identity or receipt["slice_identity"] != receipt["slice"]["identity"]
        or digest({k: v for k, v in receipt["slice"].items() if k != "identity"}) != receipt["slice_identity"]
        or receipt["platform"] != platform_id() or receipt["toolchain_identity"] != digest(receipt["toolchains"])
        or digest({"lock_identity": receipt["lock_identity"], "slice_identity": receipt["slice_identity"],
          "platform": receipt["platform"], "toolchain_identity": receipt["toolchain_identity"]}) != identity
        or receipt["files"] != inventory(root)):
      return "damaged"
    validate_installed(root, receipt["slice"])
    return "installed"
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
