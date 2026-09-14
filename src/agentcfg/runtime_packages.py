"""DSH 包拥有目录的收据与可恢复替换；不接触实例账号或配置备份。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from .deployment import json_bytes
from .storage import Conflict, Tree
from .paths import PathError


REQUIRED_FILES = (
  "package.json", "package-lock.json",
  "node_modules/@deepseek-ai/dsh/lib/bin.js",
  "node_modules/@fission-ai/openspec/bin/openspec.js",
  "node_modules/@deepseek-harness-tui/dsh-tui/cordis.patch.yml",
  "node_modules/dsh-plugin-oauth-subs/lib/index.js",
  "node_modules/@deepseek-ai/dsh-subprocess-local/scripts/ensure-spawn-helper.mjs",
)


def topology_digest(root):
  """哈希完整 node_modules 形状、链接目标和每个包清单，不跟随链接。"""
  modules = root / "node_modules"
  if modules.is_symlink() or not modules.is_dir():
    raise OSError("node_modules is not a directory")
  digest = hashlib.sha256()

  def visit(directory, prefix=""):
    for entry in sorted(os.scandir(directory), key=lambda item: os.fsencode(item.name)):
      relative = f"{prefix}/{entry.name}" if prefix else entry.name
      info = entry.stat(follow_symlinks=False)
      digest.update(os.fsencode(relative) + b"\0")
      if stat.S_ISLNK(info.st_mode):
        digest.update(b"l\0" + os.fsencode(os.readlink(entry.path)) + b"\0")
      elif stat.S_ISDIR(info.st_mode):
        digest.update(b"d\0")
        visit(entry.path, relative)
      elif stat.S_ISREG(info.st_mode):
        digest.update(b"f\0")
        if entry.name == "package.json":
          digest.update(hashlib.sha256(Path(entry.path).read_bytes()).digest())
      else:
        digest.update(b"o\0")

  visit(modules)
  return digest.hexdigest()


def owned(root, identity):
  try:
    with Tree(root) as tree:
      marker = tree.read(".agentcfg-ready")
      return marker is not None and marker[1] == 0o600 and marker[0].strip() == identity.encode()
  except (OSError, PathError):
    raise Conflict("运行包路径或权限不安全") from None


def status(root, identity):
  if not root.exists() and not root.is_symlink():
    return "missing"
  try:
    if not owned(root, identity):
      return "damaged"
    with Tree(root) as tree:
      receipt = tree.read(".agentcfg-receipt.json")
      if receipt is None or receipt[1] != 0o600:
        return "damaged"
      data = json.loads(receipt[0])
      if (data["version"] != 2 or data["identity"] != identity
          or set(data["files"]) != set(REQUIRED_FILES)
          or data["topology"] != topology_digest(root)):
        return "damaged"
      for name in REQUIRED_FILES:
        raw = tree.read(name)
        if raw is None or data["files"][name] != hashlib.sha256(raw[0]).hexdigest():
          return "damaged"
      package, resolution = json.loads(tree.read("package.json")[0]), json.loads(tree.read("package-lock.json")[0])
      if resolution["packages"][""]["dependencies"] != package["dependencies"]:
        return "damaged"
    return "installed"
  except (OSError, PathError, Conflict, ValueError, KeyError, TypeError):
    return "damaged"


def seal(root, identity):
  with Tree(root) as tree:
    inventory = {}
    for name in REQUIRED_FILES:
      raw = tree.read(name)
      if raw is None:
        raise Conflict("运行包缺少必需文件，拒绝激活")
      inventory[name] = hashlib.sha256(raw[0]).hexdigest()
    receipt = {"version": 2, "identity": identity, "files": inventory,
               "topology": topology_digest(root)}
    tree.write_state(".agentcfg-receipt.json", json_bytes(receipt))
    tree.write_state(".agentcfg-ready", (identity + "\n").encode())


def recover_repair(final, identity):
  """固定修复槽只接纳有安装所有权标记的旧包；调用者持实例锁。"""
  backup = final.parent / (".repair-" + identity)
  if backup.exists() or backup.is_symlink():
    if not owned(backup, identity):
      raise Conflict("运行包修复备份没有有效所有权标记")
    if not final.exists() and not final.is_symlink():
      rename_directory(backup, final)
    elif status(final, identity) == "installed":
      remove_backup(backup, identity)
    else:
      raise Conflict("运行包修复存在冲突；保留原目录和修复备份")


def activate(stage, final, identity):
  backup = final.parent / (".repair-" + identity)
  if final.exists() or final.is_symlink():
    if not owned(final, identity):
      raise Conflict("运行目录已存在但没有管理器所有权标记，拒绝接管")
    rename_directory(final, backup)
  try:
    rename_directory(stage, final)
  except BaseException:
    if backup.exists() and not final.exists():
      rename_directory(backup, final)
    raise
  recover_repair(final, identity)


def rename_directory(source, destination):
  if source.parent != destination.parent:
    raise Conflict("运行包激活必须在同一私人目录内")
  with Tree(source.parent) as tree, tree.parent(source.name) as (fd, name):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise Conflict("运行包必须为受管私人目录")
    try:
      os.stat(destination.name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
      pass
    else:
      raise Conflict("运行包激活目标在操作期间出现")
    with tree.parent(name) as (checked, _):
      latest = os.stat(name, dir_fd=checked, follow_symlinks=False)
      if (info.st_dev, info.st_ino) != (latest.st_dev, latest.st_ino):
        raise Conflict("运行包身份在激活前变化")
    os.rename(name, destination.name, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def remove_backup(backup, identity):
  if not owned(backup, identity):
    raise Conflict("不能清理没有安装所有权的运行包")
  with Tree(backup.parent) as tree, tree.parent(backup.name) as (fd, name):
    # 标准库使用 fd-based rmtree，拒绝顶部符号链接，不跟随包内链接。
    shutil.rmtree(name, dir_fd=fd)
    os.fsync(fd)
