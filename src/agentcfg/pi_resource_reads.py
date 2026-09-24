"""已选择的指令资源可以只读；不把整个实例或相邻账号目录开放给文件工具。"""

import hashlib
import json
from pathlib import Path
import stat

from .paths import relative_path
from .storage import Conflict, Tree


def tree_digest(root):
  root = Path(root)
  entries = []
  def walk(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode): raise Conflict("RESOURCE_LINK_REJECTED")
    if stat.S_ISDIR(info.st_mode):
      for child in sorted(path.iterdir(), key=lambda p: p.name.encode("utf-16-be")): walk(child)
    elif stat.S_ISREG(info.st_mode):
      with Tree(root if root.is_dir() else root.parent, private=False) as tree:
        name = path.relative_to(root).as_posix() if root.is_dir() else root.name
        raw = tree.read(name)
      if raw is None: raise Conflict("RESOURCE_CHANGED")
      entries.append([path.relative_to(root).as_posix() if path != root else "", info.st_mode & 0o111, hashlib.sha256(raw[0]).hexdigest()])
    else: raise Conflict("RESOURCE_TYPE_REJECTED")
  walk(root)
  return hashlib.sha256(json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def selected_resource(host, manifest, path):
  instance = Path(host.config["instance_root"])
  with Tree(instance) as tree:
    raw = tree.read("pi-home/loaded-manifest.json")
  if raw is None: return None
  loaded = json.loads(raw[0])
  allowed = [instance / relative_path(value) for value in manifest.get("resources", {}).get("skills", [])]
  with Tree(host.runtime_root) as tree:
    profile = tree.read("runtime/profile.json")
  if profile:
    installed = json.loads(profile[0])
    allowed += [host.runtime_root / relative_path(row["path"]) for row in installed.get("resources", {}).get("skills", [])
      if row["capability_id"] in manifest.get("plugins", [])]
  allowed += [Path(row["root"]) / relative_path(row["path"]) for row in manifest.get("external_skills", [])]
  matches = [row for row in loaded.get("resources", {}).get("skills", []) if Path(row["path"]) in allowed and (
    path == Path(row["path"]) or Path(row["path"]).is_dir() and path.is_relative_to(Path(row["path"])))]
  if len(matches) != 1: return None
  selected = matches[0]
  root = Path(selected["path"])
  # 资源入口须是真正的技能目录/文件；auth.json不能伪装成技能入口。
  if root.is_file() and root.name != "SKILL.md" or root.is_dir() and not (root / "SKILL.md").is_file():
    raise Conflict("RESOURCE_SKILL_ENTRY")
  if tree_digest(root) != selected["digest"]: raise Conflict("RESOURCE_CHANGED")
  return {"path": str(root), "digest": selected["digest"]}


def read_resource(host, record):
  resource = record["resource"]
  root = Path(resource["path"])
  if tree_digest(root) != resource["digest"]: raise Conflict("RESOURCE_CHANGED")
  path = Path(record["path"])
  with Tree(root if root.is_dir() else root.parent, private=False) as tree:
    name = path.relative_to(root).as_posix() if root.is_dir() else root.name
    raw = tree.read(name, max_bytes=16 * 1024 * 1024)
  if raw is None: raise Conflict("RESOURCE_MISSING")
  return raw[0]
