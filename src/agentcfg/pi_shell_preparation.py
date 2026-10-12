"""受信 Shell 准备部分：只读检查，不执行脚本、写记录或取得 Writer 租约。

command_ref 和 binding 来自受信调用者；permissions.policy_ref 已由调用者解析为
permission_policy。权限根保留名 project 映射到 binding.project_root，声明冲突拒绝。
脚本仅原样保留在 private_input，不解析为授权模式或生成摘要。
workspace_keys 留空，外层受信 bridge 必须补齐，不能直接作为最终授权使用。
这里只记录显式根、根下已知 .git 标记与 file deny；最终 mount planner/执行前复核
还必须处理嵌套 .git、祖先替换和挂载别名。完整 OS 边界闭合前不可启用执行。
"""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import pwd
import re
import stat

from .activity import digest
from .paths import PathError, _absolute_directory, configured_path, relative_path
from .pi_catalog import validate, validate_policy
from .pi_guarded_files import root_identity
from .schema import ConfigError
from .storage import Conflict


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}")
BINDING_FIELDS = {"executable", "project_root", "read_roots", "write_roots", "timeout_seconds"}
SYSTEM_ROOTS = tuple(Path(value) for value in ("/usr", "/bin", "/lib", "/lib64"))


def _invalid():
  raise ConfigError("pi-shell-preparation")


def _path(value):
  if type(value) is not str: _invalid()
  path = configured_path(value)
  if str(path) != value or any(0xD800 <= ord(char) <= 0xDFFF for char in value): _invalid()
  return path


def _ids(value):
  if (type(value) is not list or any(type(key) is not str or not IDENTIFIER.fullmatch(key) for key in value)
      or len(value) != len(set(value))): _invalid()


def _executable(path):
  # 同一句柄计算内容身份，并复核路径；不从 PATH 搜索，不执行程序。
  with _absolute_directory(path.parent) as parent:
    before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o6022 or not os.access(path, os.X_OK):
      raise ConfigError("pi-shell-executable")
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    def snapshot(info):
      return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    with os.fdopen(fd, "rb") as stream:
      if snapshot(os.fstat(stream.fileno())) != snapshot(before): raise Conflict("ROOT_IDENTITY")
      sha = hashlib.file_digest(stream, "sha256").hexdigest()
      if snapshot(os.fstat(stream.fileno())) != snapshot(before): raise Conflict("ROOT_IDENTITY")
    if snapshot(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != snapshot(before):
      raise Conflict("ROOT_IDENTITY")
  return {"path": str(path), "device": before.st_dev, "inode": before.st_ino,
    "uid": before.st_uid, "sha256": sha}


def _prepare(*, command_ref, binding, command, cwd, policy_generation, timeout_seconds,
    declared_roots, permission_policy, permissions, protected_roots):
  if type(command) is not str or not command or "\0" in command or len(command) > 65536:
    raise ConfigError("pi-shell-command")
  try:
    if len(command.encode("utf-8")) > 65536: raise ConfigError("pi-shell-command")
  except UnicodeError:
    raise ConfigError("pi-shell-command") from None
  if type(command_ref) is not str or not re.fullmatch(r"tool:[a-z][a-z0-9_-]{0,63}", command_ref): _invalid()
  if type(binding) is not dict or set(binding) != BINDING_FIELDS: _invalid()
  if type(policy_generation) is not int or not 1 <= policy_generation <= 2**53 - 1: _invalid()
  if type(binding["project_root"]) is not str or not IDENTIFIER.fullmatch(binding["project_root"]): _invalid()
  for key in ("read_roots", "write_roots"): _ids(binding[key])
  maximum = binding["timeout_seconds"]
  if type(maximum) is not int or not 1 <= maximum <= (2**53 - 1) // 1000: _invalid()
  timeout = maximum if timeout_seconds is None else timeout_seconds
  if type(timeout) is not int or not 1 <= timeout <= maximum: raise ConfigError("pi-shell-timeout")
  permissions = {} if permissions is None else permissions
  validate("options", {"paths": {"roots": declared_roots}, "permissions": permissions})
  validate_policy(permission_policy)
  if type(protected_roots) not in (list, tuple): _invalid()
  selected = set(binding["read_roots"]) | set(binding["write_roots"]) | {binding["project_root"]}
  references = set(permissions.get("denied_roots", [])) | set(permissions.get("readonly_roots", []))
  references |= {rule["root_ref"] for rule in permission_policy["rules"] if rule["kind"] == "file" and rule["root_ref"] != "project"}
  if (selected | (references - {"project"})) - declared_roots.keys(): raise ConfigError("pi-shell-root-unbound")
  roots = {key: {"path": str(_path(row["path"])), "identity": root_identity(_path(row["path"]))}
    for key, row in declared_roots.items()}
  project_id = binding["project_root"]
  if "project" in roots and roots["project"]["identity"] != roots[project_id]["identity"]:
    raise Conflict("SHELL_COMMAND_PROJECT_CONFLICT")
  # 仅保留名允许与选定项目重复；其它目录别名以及重复选中根仍拒绝。
  canonical = {key: row for key, row in roots.items() if key != "project" or project_id == "project"}
  if (len({row["identity"] for row in canonical.values()}) != len(canonical)
      or len({roots[key]["identity"] for key in selected}) != len(selected)):
    raise Conflict("ROOT_IDENTITY")
  effective_roots = {**roots, "project": roots[project_id]}
  current = _path(cwd)
  cwd_identity = root_identity(current)
  project = Path(roots[binding["project_root"]]["path"])
  projects = {Path(roots[key]["path"]) for key, row in declared_roots.items() if row["purpose"] == "project" and current.is_relative_to(Path(roots[key]["path"]))}
  if declared_roots[binding["project_root"]]["purpose"] != "project" or projects != {project}:
    raise Conflict("SHELL_COMMAND_CWD")
  if (binding["project_root"] not in binding["read_roots"]
      or any(declared_roots[key]["purpose"] not in ("project", "write") for key in binding["write_roots"])):
    raise Conflict("SHELL_COMMAND_ROOT_CEILING")
  homes = {Path.home(), Path(pwd.getpwuid(os.geteuid()).pw_dir)}
  for key in selected:
    path = Path(roots[key]["path"])
    if path == Path("/") or path in homes or ".git" in path.parts: raise Conflict("SHELL_COMMAND_ROOT_CEILING")
  rules = [rule for rule in permission_policy["rules"] if rule["kind"] == "command"
    and rule["command_ref"] == command_ref and "bash" in rule["tool_ids"] and "execute" in rule["operations"]]
  if any(rule["effect"] == "deny" for rule in rules) or not any(rule["effect"] == "allow" for rule in rules):
    raise Conflict("PERMISSION_DENIED")
  readonly = [Path(effective_roots[key]["path"]) for key in permissions.get("readonly_roots", [])]
  writes = [Path(roots[key]["path"]) for key in binding["write_roots"]]
  if any(path.is_relative_to(other) or other.is_relative_to(path) for path in writes for other in readonly):
    raise Conflict("PERMISSION_DENIED")
  denied = [Path(effective_roots[key]["path"]) for key in permissions.get("denied_roots", [])]
  denied.extend(_path(value) for value in protected_roots)
  for key in sorted(selected):
    git = Path(roots[key]["path"]) / ".git"
    if git.is_symlink(): raise Conflict("ROOT_IDENTITY")
    if git.exists(): denied.append(git)
  for rule in permission_policy["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    base = Path(effective_roots[rule["root_ref"]]["path"])
    denied.append(base if rule["relative_path"] == "." else base / relative_path(rule["relative_path"]))
  visible = [Path(roots[key]["path"]) for key in selected]
  if any(path.is_relative_to(denial) for path in [current, *visible] for denial in denied):
    raise Conflict("PERMISSION_DENIED")
  executable = _path(binding["executable"])
  if any(executable.is_relative_to(path) for path in denied): raise Conflict("PERMISSION_DENIED")
  identity = _executable(executable)
  for path in denied:
    if not any(path.is_relative_to(root) for root in [*visible, *SYSTEM_ROOTS, executable]): continue
    # 空根已屏蔽范围外路径；范围内缺失/链接/特殊文件不能靠占位表达 deny。
    try:
      with _absolute_directory(path.parent) as parent:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
      if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)): raise ValueError()
    except (OSError, PathError, ValueError):
      raise ConfigError("pi-shell-denial-not-representable") from None
  for row in roots.values():
    if root_identity(row["path"]) != row["identity"]: raise Conflict("ROOT_IDENTITY")
  if root_identity(current) != cwd_identity: raise Conflict("ROOT_IDENTITY")
  read_rows = [deepcopy(roots[key]) for key in binding["read_roots"]]
  write_rows = [deepcopy(roots[key]) for key in binding["write_roots"]]
  denied_paths = sorted({str(path) for path in denied})
  ceiling = {"binding": binding, "roots": roots, "declarations": declared_roots, "permissions": permissions,
    "protected_roots": list(protected_roots), "denied_paths": denied_paths,
    "cwd": {"path": str(current), "identity": cwd_identity}}
  resolved = {"kind": "shell-command", "tool_name": "bash",
    "target": {"command_ref": command_ref, "executable": identity, "timeout_ms": timeout * 1000},
    "read_roots": read_rows, "write_roots": write_rows, "workspace_keys": [], "network": "deny",
    "services": [], "backend": "linux-bwrap-v1", "policy": {"generation": policy_generation,
      "policy_digest": digest(permission_policy), "ceiling_digest": digest(ceiling),
      "hard_policy": "allow", "requires_human": True}}
  return {"resolution": resolved, "private_input": {"command": command}, "physical": {"cwd": str(current), "cwd_identity": cwd_identity,
    "executable_identity": deepcopy(identity), "denied_paths": denied_paths,
    "readonly_paths": sorted({str(path) for path in readonly}),
    "read_roots": [row["path"] for row in read_rows], "write_roots": [row["path"] for row in write_rows],
    "timeout_seconds": timeout}}


def prepare_shell(*, command_ref, binding, command, cwd, policy_generation, timeout_seconds=None,
    declared_roots, permission_policy, permissions=None, protected_roots=()):
  """无副作用地返回内部准备部分；未知字段与不可表达边界固定失败。"""
  try:
    return _prepare(command_ref=command_ref, binding=binding, command=command, cwd=cwd,
      policy_generation=policy_generation, timeout_seconds=timeout_seconds, declared_roots=declared_roots,
      permission_policy=permission_policy, permissions=permissions, protected_roots=protected_roots)
  except (OSError, PathError, UnicodeError, ValueError, TypeError, KeyError):
    raise ConfigError("pi-shell-preparation") from None
