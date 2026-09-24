"""权限决策与固定目录句柄内的实际文件操作；模型不能提供模式或授权。"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import sys
import unicodedata

from .activity import digest
from .paths import _absolute_directory, relative_path
from .pi_catalog import validate
from .schema import ConfigError
from .storage import Conflict, Tree, identity


ALIASES = {"read": "tk_read", "grep": "tk_grep", "find": "tk_find", "ls": "tk_ls", "write": "tk_write", "edit": "tk_edit", "rename": "tk_edit", "bash": "bash", "process": "process",
  **{name: name for name in ("tk_read", "tk_grep", "tk_find", "tk_ls", "tk_write", "tk_edit", "project_check", "editor")}}
MUTATIONS = {"write", "create", "delete", "rename"}
MAX_FILE_BYTES = 1024 * 1024


def rename_exclusive(source_fd, source_name, target_fd, target_name):
  """由内核原子拒绝覆盖，不能把 stat + 普通 rename 当作排他重命名。"""
  import ctypes
  import errno
  import sys
  from .process import DependencyError
  name, flag = ("renameat2", 1) if sys.platform == "linux" else ("renameatx_np", 4) if sys.platform == "darwin" else (None, None)
  native = getattr(ctypes.CDLL(None, use_errno=True), name, None) if name else None
  if native is None:
    raise DependencyError("平台没有排他文件重命名接口")
  native.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
  native.restype = ctypes.c_int
  if native(source_fd, os.fsencode(source_name), target_fd, os.fsencode(target_name), flag) != 0:
    error = ctypes.get_errno()
    if error == errno.EEXIST: raise Conflict("RENAME_DESTINATION_CONFLICT")
    if error in (errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL): raise DependencyError("文件系统不支持排他重命名")
    raise OSError(error, "FILE_RENAME_FAILED")


def root_identity(path):
  with _absolute_directory(Path(path)) as fd:
    info = os.fstat(fd)
    return digest({"device": str(info.st_dev), "inode": str(info.st_ino), "uid": str(info.st_uid)})


def inside(path, root):
  return path == root or root in path.parents


def same_object(left, right):
  try:
    a, b = os.stat(left, follow_symlinks=False), os.stat(right, follow_symlinks=False)
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
  except (FileNotFoundError, NotADirectoryError):
    return False


def physical_inside(path, root):
  return inside(path, root) or any(same_object(parent, root) for parent in (path, *path.parents))


class FilePolicy:
  def __init__(self, *, policy, roots, ceiling, grant, mode, verify, workspace, inherited_denials=(),
      readonly_roots=(), denied_roots=(), secret_roots=(), private_roots=(), source_checkout=None):
    validate("permission-policy", policy)
    if mode not in ("ordinary", "managed", "delegate-readonly", "delegate-write"):
      raise ConfigError("pi-execution-mode")
    if set(ceiling) != {"allowed_tools", "read_roots", "write_roots"}:
      raise ConfigError("pi-role-ceiling")
    for values in ceiling.values():
      if not isinstance(values, list) or len(set(values)) != len(values):
        raise ConfigError("pi-role-ceiling")
    self.policy, self.roots, self.ceiling, self.grant = map(deepcopy, (policy, roots, ceiling, grant))
    self.mode, self.verify, self.workspace = mode, verify, workspace
    self.denials = list(deepcopy(inherited_denials))
    validate("permission-policy", {"schema_version": 1, "default": "deny", "rules": self.denials})
    if any(rule["effect"] != "deny" for rule in self.denials):
      raise ConfigError("pi-parent-denials")
    for rules in (self.policy["rules"], self.denials):
      if len({rule["id"] for rule in rules}) != len(rules) or any(tool not in ALIASES for rule in rules for tool in rule["tool_ids"]):
        raise ConfigError("pi-permission-rule-reference")
    self.readonly, self.denied = set(readonly_roots), set(denied_roots)
    if (self.readonly | self.denied) - self.roots.keys() or any(rule["kind"] == "file" and rule["root_ref"] not in self.roots for rule in [*self.policy["rules"], *self.denials]):
      raise ConfigError("pi-permission-root-unbound")
    self.secrets = tuple(Path(value).resolve(strict=True) for value in secret_roots)
    self.private_roots = tuple(Path(value).resolve(strict=True) for value in private_roots)
    self.source = Path(source_checkout).resolve(strict=True) if source_checkout else None
    self.case_sensitive = {}
    for binding in self.roots.values():
      if set(binding) != {"path", "identity"} or root_identity(binding["path"]) != binding["identity"]:
        raise Conflict("ROOT_IDENTITY")
      sensitive = True
      if sys.platform == "darwin":
        # Apple sys/unistd.h: _PC_CASE_SENSITIVE=11。只查询目录，不创建探测文件。
        with _absolute_directory(Path(binding["path"])) as fd: flag = os.fpathconf(fd, 11)
        if flag not in (0, 1): raise Conflict("ROOT_CASE_SEMANTICS")
        sensitive = bool(flag)
      self.case_sensitive[str(Path(binding["path"]))] = sensitive
    if mode != "managed":
      validate("operation-grant", grant)
      if grant["execution_mode"] != mode or grant["grant_digest"] != digest({key: value for key, value in grant.items() if key != "grant_digest"}):
        raise Conflict("GRANT_INVALID")
      if grant["root_bindings"] != self.roots:
        raise Conflict("GRANT_INVALID")
    elif grant.get("executor") != "managed-process" or grant.get("context_mode") != "fresh" or grant.get("nested") is not False:
      raise Conflict("GRANT_INVALID")
    self.metadata = {"policy_digest": digest(policy), "root_binding_digest": digest(roots), "parent_policy_digest": digest(self.denials),
      "role_or_instance_ceiling_digest": digest(ceiling), "alias_table_digest": digest(ALIASES), "execution_mode": mode,
      "grant_kind": "task" if mode == "managed" else "operation", "grant_generation": grant["grant_generation"]}

  def current(self):
    deadline = self.grant.get("deadline") if self.mode == "managed" else self.grant["expires_at"]
    try:
      expired = deadline is not None and datetime.fromisoformat(deadline.replace("Z", "+00:00")).timestamp() <= datetime.now(timezone.utc).timestamp()
    except (ValueError, TypeError, AttributeError):
      raise Conflict("GRANT_STALE") from None
    if expired or (self.mode != "ordinary" and deadline is None):
      raise Conflict("GRANT_STALE")
    if self.verify(deepcopy(self.grant), deepcopy(self.metadata)) is not True:
      raise Conflict("GRANT_STALE")
    for binding in self.roots.values():
      if root_identity(binding["path"]) != binding["identity"]:
        raise Conflict("ROOT_IDENTITY")

  def authorize(self, tool, operation, path):
    self.current()
    tool = ALIASES.get(tool)
    if (tool is None or operation not in MUTATIONS | {"read", "list", "search"}
        or tool not in [ALIASES.get(name) for name in self.grant["allowed_tools"]]
        or tool not in [ALIASES.get(name) for name in self.ceiling["allowed_tools"]]):
      raise Conflict("PERMISSION_DENIED")
    value = Path(path)
    if not value.is_absolute():
      value = Path(self.roots["project"]["path"]) / value
    if ".." in value.parts or ".git" in value.parts:
      raise Conflict("PERMISSION_DENIED")
    matches = []
    write = operation in MUTATIONS
    for name, binding in self.roots.items():
      root = Path(binding["path"])
      if (name in self.denied or write and name in self.readonly) and physical_inside(value, root):
        raise Conflict("PERMISSION_DENIED")
      if not inside(value, root):
        continue
      tail = value.relative_to(root).as_posix()
      project = Path(self.roots["project"]["path"]) if "project" in self.roots else None
      secret_hit = any(physical_inside(value, secret) for secret in self.secrets)
      secret_hit |= any(physical_inside(value, private) and not (self.mode in ("managed", "delegate-write") and project is not None
        and private != project and inside(project, private) and inside(value, project)) for private in self.private_roots)
      if name in self.denied or write and name in self.readonly or secret_hit:
        raise Conflict("PERMISSION_DENIED")
      if write and (self.mode == "delegate-readonly" or self.mode in ("managed", "delegate-write") and self.source and physical_inside(value, self.source)):
        raise Conflict("PERMISSION_DENIED")
      # Tree.parent 的 openat/no-follow 复核在真正 IO 时重复进行。
      cursor = root
      for part in value.relative_to(root).parts:
        cursor /= part
        if part.casefold() == ".git" and (not self.case_sensitive[str(root)] or same_object(cursor, cursor.parent / ".git")):
          raise Conflict("PERMISSION_DENIED")
        if cursor.is_symlink():
          raise Conflict("ROOT_IDENTITY")
      matches.append({"root_ref": name, "relative_path": tail, "root": root, "path": value})
    def path_matches(rule, target):
      rule_path = target["root"] / rule["relative_path"]
      lexical = target["relative_path"] == rule["relative_path"] or rule["match"] == "subtree" and (
        rule["relative_path"] == "." or target["relative_path"].startswith(rule["relative_path"] + "/"))
      if lexical or (physical_inside(target["path"], rule_path) if rule["match"] == "subtree" else same_object(target["path"], rule_path)):
        return True
      if rule["effect"] == "deny" and sys.platform == "darwin":
        key = lambda value: unicodedata.normalize("NFD", value) if self.case_sensitive[str(target["root"])] else unicodedata.normalize("NFD", value).casefold()
        source, destination = key(rule["relative_path"]), key(target["relative_path"])
        return source == destination or rule["match"] == "subtree" and destination.startswith(source + "/")
      return False
    def applies(rule, targets):
      return rule["kind"] == "file" and tool in [ALIASES.get(name) for name in rule["tool_ids"]] and operation in rule["operations"] and any(
        target["root_ref"] == rule["root_ref"] and path_matches(rule, target) for target in targets)
    if any(rule["effect"] == "deny" and applies(rule, matches) for rule in [*self.policy["rules"], *self.denials]):
      raise Conflict("PERMISSION_DENIED")
    key = "write_roots" if write else "read_roots"
    allowed = [target for target in matches if target["root_ref"] in self.ceiling[key]
      and (self.mode != "managed" or target["root_ref"] in self.grant[key])
      and any(rule["effect"] == "allow" and applies(rule, [target]) for rule in self.policy["rules"])]
    if not allowed:
      raise Conflict("PERMISSION_DENIED")
    target = max(allowed, key=lambda item: len(item["root"].parts))
    if write and self.workspace(target["root_ref"], deepcopy(self.grant)) is not True:
      raise Conflict("WORKSPACE_BUSY")
    return target


class GuardedFiles:
  def __init__(self, policy, *, mutation, max_read_bytes=MAX_FILE_BYTES):
    self.policy = policy
    self.mutation = mutation
    if type(max_read_bytes) is not int or not 1 <= max_read_bytes <= 16 * 1024 * 1024:
      raise ConfigError("pi-file-read-limit")
    self.max_read_bytes = max_read_bytes

  def read(self, tool, path, *, operation="read"):
    return self.read_snapshot(tool, path, operation=operation)[0]

  def read_snapshot(self, tool, path, *, operation="read"):
    """正文与 mtime 来自同一已核验句柄，供私人副本保持原生缓存语义。"""
    if operation not in ("read", "search"):
      raise ConfigError("pi-file-operation")
    target = self.policy.authorize(tool, operation, path)
    relative_path(target["relative_path"])
    with Tree(target["root"], private=False) as tree:
      with tree.parent(target["relative_path"]) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > self.max_read_bytes:
          raise Conflict("FILE_READ_BOUNDARY")
      self.policy.current()
      with tree.open_read(target["relative_path"], max_bytes=self.max_read_bytes) as (stream, opened):
        body = stream.read(self.max_read_bytes + 1)
        if len(body) > self.max_read_bytes: raise Conflict("FILE_READ_BOUNDARY")
        modified = opened.st_mtime_ns
      self.policy.current()
      return body, modified

  def metadata(self, tool, path):
    target = self.policy.authorize(tool, "read", path)
    relative_path(target["relative_path"])
    with Tree(target["root"], private=False) as tree:
      with tree.parent(target["relative_path"]) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
          raise Conflict("FILE_READ_BOUNDARY")
        self.policy.current()
        return {"size": info.st_size, "identity": digest({"device": info.st_dev, "inode": info.st_ino,
          "size": info.st_size, "mtime_ns": info.st_mtime_ns})}

  def list(self, tool, path):
    target = self.policy.authorize(tool, "list", path)
    result = []
    with _absolute_directory(target["path"]) as fd:
      self.policy.current()
      for name in sorted(os.listdir(fd)):
        if name == ".git":
          continue
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
          continue
        try:
          self.policy.authorize(tool, "list", str(target["path"] / name))
        except Conflict as error:
          if str(error) == "PERMISSION_DENIED":
            continue
          raise
        result.append({"name": name, "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file"})
        if len(result) >= 200:
          break
    return result

  def search(self, tool, path, query, kind):
    if not isinstance(query, str) or not query or len(query) > 512 or kind not in ("find", "grep"):
      raise ConfigError("pi-search-query")
    target = self.policy.authorize(tool, "search", path)
    matches = []
    scanned = 0
    truncated = False
    def visit(directory):
      nonlocal scanned, truncated
      with _absolute_directory(directory) as fd:
        for name in sorted(os.listdir(fd)):
          if name == ".git":
            continue
          if scanned >= 5000 or len(matches) >= 100:
            truncated = True
            return
          scanned += 1
          info = os.stat(name, dir_fd=fd, follow_symlinks=False)
          current = directory / name
          if stat.S_ISLNK(info.st_mode):
            continue
          try:
            self.policy.authorize(tool, "search", str(current))
          except Conflict as error:
            if str(error) == "PERMISSION_DENIED":
              continue
            raise
          if stat.S_ISDIR(info.st_mode):
            visit(current)
          elif stat.S_ISREG(info.st_mode):
            relative = current.relative_to(target["root"]).as_posix()
            if kind == "find":
              if query in relative:
                matches.append({"path": relative})
            elif info.st_size <= MAX_FILE_BYTES:
              raw = self.read(tool, str(current), operation="search")
              try:
                content = raw.decode("utf-8")
              except UnicodeError:
                continue
              for number, line in enumerate(content.splitlines(), 1):
                if query in line:
                  matches.append({"path": relative, "line": number, "text": line[:2048]})
                  if len(matches) >= 100:
                    truncated = True
                    return
    visit(target["path"])
    return {"matches": matches, "truncated": truncated}

  def write(self, tool, path, data, *, expected_digest=None, expect_absent=False):
    if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
      raise ConfigError("pi-file-content")
    if type(expect_absent) is not bool: raise ConfigError("pi-file-absence-contract")
    target = self.policy.authorize(tool, "write", path)
    relative_path(target["relative_path"])
    parents = []
    cursor = target["root"]
    for part in target["path"].parent.relative_to(target["root"]).parts:
      cursor /= part
      if not cursor.exists():
        self.policy.authorize(tool, "create", str(cursor))
        parents.append(str(cursor))
    with Tree(target["root"], private=False) as tree:
      old = tree.read(target["relative_path"], max_bytes=MAX_FILE_BYTES)
      if expect_absent and old is not None: raise Conflict("FILE_CHANGED")
      if old is None:
        self.policy.authorize(tool, "create", path)
      before = hashlib.sha256(old[0]).hexdigest() if old else None
      if expected_digest is not None and expected_digest != before:
        raise Conflict("FILE_CHANGED")
      operation = {"operation": "write", "root_ref": target["root_ref"], "relative_path": target["relative_path"],
        "before_digest": before, "after_digest": hashlib.sha256(data).hexdigest()}
      ticket = self.mutation("prepare", operation)
      if not isinstance(ticket, str) or not ticket:
        raise Conflict("MUTATION_INTENT_MISSING")
      self.policy.authorize(tool, "write", path)
      for parent in parents: self.policy.authorize(tool, "create", parent)
      tree.replace(target["relative_path"], data, old[1] if old else 0o600, expected=old[2] if old else None)
      self.mutation("settle", {**operation, "ticket": ticket})
      return {"changed": before != operation["after_digest"], "content_digest": operation["after_digest"]}

  def rename(self, tool, path, destination):
    source = self.policy.authorize(tool, "rename", path)
    target = self.policy.authorize(tool, "rename", destination)
    for value in (source, target):
      relative_path(value["relative_path"])
    with Tree(source["root"], private=False) as left, Tree(target["root"], private=False) as right:
      old, previous = left.read(source["relative_path"], max_bytes=MAX_FILE_BYTES), right.read(target["relative_path"], max_bytes=MAX_FILE_BYTES)
      if old is None or previous is not None:
        raise Conflict("RENAME_DESTINATION_CONFLICT")
      operation = {"operation": "rename", "root_ref": source["root_ref"], "relative_path": source["relative_path"],
        "destination_root": target["root_ref"], "destination_path": target["relative_path"], "content_digest": hashlib.sha256(old[0]).hexdigest()}
      ticket = self.mutation("prepare", operation)
      if not isinstance(ticket, str) or not ticket:
        raise Conflict("MUTATION_INTENT_MISSING")
      with left.parent(source["relative_path"]) as (src_fd, src_name), right.parent(target["relative_path"]) as (dst_fd, dst_name):
        self.policy.authorize(tool, "rename", path)
        self.policy.authorize(tool, "rename", destination)
        if identity(os.stat(src_name, dir_fd=src_fd, follow_symlinks=False)) != old[2]:
          raise Conflict("FILE_CHANGED")
        try:
          os.stat(dst_name, dir_fd=dst_fd, follow_symlinks=False)
        except FileNotFoundError:
          pass
        else:
          raise Conflict("RENAME_DESTINATION_CONFLICT")
        rename_exclusive(src_fd, src_name, dst_fd, dst_name)
        os.fsync(src_fd)
        os.fsync(dst_fd)
      self.mutation("settle", {**operation, "ticket": ticket})
      return {"renamed": True}
