"""机器根限制的冻结与候选投影；限制只收紧权限，不授予新目录访问。"""

from pathlib import Path
import re

from .paths import PathError, configured_path
from .pi_guarded_files import root_identity, same_object
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree
from .workspace_leases import WorkspaceLeases


def relative_inside(path, root):
  """组件关系优先，目录对象身份补足bind mount/大小写别名。"""
  path, root = Path(path), Path(root)
  if path.is_relative_to(root): return path.relative_to(root)
  for parent in (path, *path.parents):
    if same_object(parent, root): return path.relative_to(parent)
  return None


def project_anchor(path):
  # 只复用Git目录身份解析，不将此标签记录或用作启动/终止的boot证明。
  identity = WorkspaceLeases("native-policy-snapshot").identify(path)
  git = Path(identity["git_dir_path"])
  with Tree(git, private=False) as tree: raw = tree.read("commondir")
  common = (git / raw[0].decode().strip()).resolve(strict=True) if raw else git
  worktree = Path(identity["worktree_path"])
  return {"worktree": str(worktree), "worktree_identity": root_identity(worktree),
    "git_dir": str(git), "git_identity": root_identity(git), "common_dir": str(common), "common_identity": root_identity(common)}


def _snapshot_root_limits(options):
  declarations = options.get("paths", {}).get("roots", {})
  permissions = options.get("permissions", {})
  result = {"bindings": {}, "readonly_roots": list(permissions.get("readonly_roots", [])), "denied_roots": list(permissions.get("denied_roots", []))}
  if any(name not in declarations for name in [*result["readonly_roots"], *result["denied_roots"]]):
    raise ConfigError("delegate-native-root-unbound")
  for name, declaration in declarations.items():
    path = configured_path(declaration["path"]).resolve(strict=True)
    record = {"path": str(path), "identity": root_identity(path), "purpose": declaration["purpose"]}
    if declaration["purpose"] == "project": record["project_anchor"] = project_anchor(path)
    result["bindings"][name] = record
  validate_root_limits(result)
  return result


def validate_root_limits(value):
  closed(value, ("bindings", "readonly_roots", "denied_roots"))
  bindings = value["bindings"]
  if not isinstance(bindings, dict): raise ConfigError("delegate-native-root-snapshot")
  for name, record in bindings.items():
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name): raise ConfigError("delegate-native-root-snapshot")
    closed(record, ("path", "identity", "purpose"), ("project_anchor",))
    if record["purpose"] not in ("read", "write", "project"): raise ConfigError("delegate-native-root-snapshot")
    if str(configured_path(record["path"])) != record["path"]: raise ConfigError("delegate-native-root-snapshot")
    if not isinstance(record["identity"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["identity"]): raise ConfigError("delegate-native-root-snapshot")
    if record["purpose"] == "project":
      anchor = record.get("project_anchor", {})
      closed(anchor, ("worktree", "worktree_identity", "git_dir", "git_identity", "common_dir", "common_identity"))
      for key, item in anchor.items():
        if key.endswith("identity"):
          if not isinstance(item, str) or not re.fullmatch(r"[a-f0-9]{64}", item): raise ConfigError("delegate-native-root-snapshot")
        elif str(configured_path(item)) != item: raise ConfigError("delegate-native-root-snapshot")
    elif "project_anchor" in record: raise ConfigError("delegate-native-root-snapshot")
  for key in ("readonly_roots", "denied_roots"):
    items = value[key]
    if not isinstance(items, list) or any(not isinstance(name, str) or name not in bindings for name in items) or len(set(items)) != len(items):
      raise ConfigError("delegate-native-root-unbound")
  return value


def _project_root_limits(value, cwd):
  """原根仍受限制；相同Git common-dir的候选继承对应路径限制。"""
  validate_root_limits(value)
  cwd = Path(cwd).resolve(strict=True)
  origins = []
  candidate = project_anchor(cwd) if value["bindings"] else None
  if candidate: origins.append(Path(candidate["worktree"]))
  for record in value["bindings"].values():
    path = Path(record["path"])
    if path.resolve(strict=True) != path or root_identity(path) != record["identity"]:
      raise Conflict("DELEGATE_NATIVE_ROOT_STALE")
    if record["purpose"] == "project":
      anchor = project_anchor(path)
      if anchor != record["project_anchor"]: raise Conflict("DELEGATE_NATIVE_ROOT_STALE")
      if anchor["common_identity"] == candidate["common_identity"]:
        origins.append(Path(anchor["worktree"]))
  mapped = {}
  for name, record in value["bindings"].items():
    source = Path(record["path"])
    targets = {source}
    for origin in origins:
      relative = relative_inside(source, origin)
      if relative is not None: target = Path(candidate["worktree"]) / relative
      elif relative_inside(origin, source) is not None: target = Path(candidate["worktree"])
      else: continue
      # 不允许候选里新的符号链接把拒绝规则搬到其他路径。
      if target.resolve(strict=False) != target: raise Conflict("DELEGATE_NATIVE_ROOT_ALIAS")
      targets.add(target)
    mapped[name] = sorted(targets)
  return {"bindings": mapped,
    "readonly": sorted({path for name in value["readonly_roots"] for path in mapped[name]}),
    "denied": sorted({path for name in value["denied_roots"] for path in mapped[name]})}


def restrict_permissions(permissions, *, readonly=(), denied=()):
  """保持default-deny；禁止用更具体的allow重开deny/readonly。"""
  result = dict(permissions)
  def aliases(paths):
    result = {Path(path) for path in paths}
    for limit in tuple(result):
      for name, access in permissions.items():
        if name.startswith(":") or access == "deny": continue
        relative = relative_inside(limit, Path(name))
        if relative is not None: result.add(Path(name) / relative)
    return tuple(result)
  denied = aliases(denied)
  readonly = aliases(readonly)
  for name, access in list(result.items()):
    if name.startswith(":") or access == "deny": continue
    path = Path(name)
    if any(relative_inside(path, limit) is not None for limit in denied): result[name] = "deny"
    elif access == "write" and any(relative_inside(path, limit) is not None for limit in readonly): result[name] = "read"
  # 仅在已授权的写子树内增加read覆盖；其他readonly根继续default-deny。
  for path in readonly:
    if any(relative_inside(path, limit) is not None for limit in denied): continue
    if any(not name.startswith(":") and access == "write" and path.is_relative_to(Path(name)) for name, access in permissions.items()):
      result[str(path)] = "read"
  for path in denied: result[str(path)] = "deny"
  return result


def snapshot_root_limits(options):
  try: return _snapshot_root_limits(options)
  except (OSError, PathError): raise Conflict("DELEGATE_NATIVE_ROOT_STALE") from None


def project_root_limits(value, cwd):
  try: return _project_root_limits(value, cwd)
  except (OSError, PathError): raise Conflict("DELEGATE_NATIVE_ROOT_STALE") from None
