"""Host 派生的检查实现来源；只读复核，不授予 Worker 写权限。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from .activity import digest
from .paths import _absolute_directory, configured_path, relative_path
from .pi_guarded_files import root_identity
from .pi_shell_mounts import parse_mountinfo
from .schema import ConfigError
from .storage import Conflict, Tree

MAX_ENTRIES = 1024
MAX_BYTES = 16 * 1024 * 1024
MAX_EXECUTABLE = 256 * 1024 * 1024


def inline_node(binding):
  args = binding.get("args", [])
  return len(args) == 2 and args[0] in ("-e", "--eval")


def host_context(host, manifest, lease, checker_id, candidate):
  """权限来源只能是当前 Host manifest；不消费模型的 Writer 描述符。"""
  if digest(manifest) != host.config["manifest_digest"] or digest(manifest["permission_policy"]) != host.config["policy_digest"]:
    raise Conflict("ADMISSION_STALE")
  role = manifest.get("role_bindings", {}).get("task-keeper-writer")
  if not role or role.get("managed") is not True: raise Conflict("CHECK_WRITER_SCOPE_UNBOUND")
  declarations = manifest["options"]["paths"]["roots"]
  writes = []
  for name in role["write_roots"]:
    path = candidate if name == "project" else configured_path(declarations[name]["path"])
    identity = host.store.workspaces.identify(path)
    writes.append({"root_ref": name, "path": str(path), "root_identity": root_identity(path), "workspace": identity})
  protected = list(host.config.get("protected_roots", []))
  for name in manifest["options"].get("permissions", {}).get("denied_roots", []):
    protected.append(str(candidate if name == "project" else configured_path(declarations[name]["path"])))
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] == "file" and rule["effect"] == "deny":
      base = candidate if rule["root_ref"] == "project" else configured_path(declarations[rule["root_ref"]]["path"])
      protected.append(str(base / (Path(".") if rule["relative_path"] == "." else relative_path(rule["relative_path"]))))
  value = {"checker_id": checker_id, "manifest_path": str(Path(host.config["instance_root"]) / "pi-home/agentcfg-manifest.json"),
    "manifest_digest": host.config["manifest_digest"], "policy_digest": host.config["policy_digest"],
    "candidate_identity": root_identity(candidate),
    "engine": {"kind": manifest["engine"], "path": host.engine_executable, "snapshot": _scan(_canonical(host.engine_executable), executable=True)},
    "runtime": {key: host.config[key] for key in ("instance_id", "lock_identity", "slice_identity")},
    "worker_scope": writes, "roots": deepcopy(declarations),
    "protected_roots": protected}
  if lease is not None:
    value["lease"] = {key: lease[key] for key in ("lease_id", "grant_generation")}
  return value


def contract_digest(check):
  """同一检查契约跨物理 attempt 稳定；摘要不代替当前 Host 授权。"""
  value = deepcopy(check)
  value.pop("binding_digest", None)
  context = value["trusted_implementation"]["context"]
  context.pop("lease", None)
  return digest(value)


def _table():
  if sys.platform != "linux": raise ConfigError("CHECK_PHYSICAL_SCOPE_UNSUPPORTED")
  return parse_mountinfo(Path("/proc/self/mountinfo").read_text())


def _coordinate(path, table):
  matches = [row for row in table if path.is_relative_to(Path(row["mountpoint"]))]
  if not matches or len({row["mountpoint"] for row in matches}) != len(matches):
    raise Conflict("CHECK_PHYSICAL_SCOPE_AMBIGUOUS")
  row = max(matches, key=lambda row: len(Path(row["mountpoint"]).parts))
  info = path.lstat()
  if row["device"] != [os.major(info.st_dev), os.minor(info.st_dev)]: raise Conflict("CHECK_PHYSICAL_SCOPE_DEVICE")
  return tuple(row["device"]), Path(row["root"]) / path.relative_to(Path(row["mountpoint"]))


def _overlaps(left, right, table):
  if left.is_relative_to(right) or right.is_relative_to(left): return True
  ld, lp = _coordinate(left, table); rd, rp = _coordinate(right, table)
  return ld == rd and (lp.is_relative_to(rp) or rp.is_relative_to(lp))


def _snapshot(info):
  return [info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _scan(path, *, executable=False):
  """逐段 no-follow、单链接、有界内容；前后 stat 和目录列表漂移失败。"""
  count, total = 0, 0
  def walk(parent, name):
    nonlocal count, total
    count += 1
    if count > MAX_ENTRIES: raise Conflict("CHECK_TRUSTED_INPUT_LIMIT")
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if before.st_uid not in (0, os.geteuid()) or before.st_mode & 0o6022:
      raise Conflict("CHECK_TRUSTED_INPUT_PERMISSIONS")
    directory = stat.S_ISDIR(before.st_mode)
    if not directory and (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
      raise Conflict("CHECK_TRUSTED_INPUT_OBJECT")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_DIRECTORY if directory else 0)
    fd = os.open(name, flags, dir_fd=parent)
    try:
      if _snapshot(os.fstat(fd)) != _snapshot(before): raise Conflict("CHECK_TRUSTED_INPUT_DRIFT")
      value = {"identity": _snapshot(before)}
      if directory:
        names = sorted(os.listdir(fd));value["files"] = {key: walk(fd, key) for key in names}
        if names != sorted(os.listdir(fd)): raise Conflict("CHECK_TRUSTED_INPUT_DRIFT")
      else:
        cap = MAX_EXECUTABLE if executable else MAX_BYTES
        if before.st_size > cap: raise Conflict("CHECK_TRUSTED_INPUT_LIMIT")
        hasher = hashlib.sha256();size = 0
        while True:
          raw = os.read(fd, 65536)
          if not raw: break
          size += len(raw)
          if size > cap: raise Conflict("CHECK_TRUSTED_INPUT_LIMIT")
          hasher.update(raw)
        total += size
        if total > cap or size != before.st_size: raise Conflict("CHECK_TRUSTED_INPUT_LIMIT")
        value["sha256"] = hasher.hexdigest()
      if _snapshot(os.fstat(fd)) != _snapshot(before) or _snapshot(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _snapshot(before):
        raise Conflict("CHECK_TRUSTED_INPUT_DRIFT")
      return value
    finally: os.close(fd)
  with _absolute_directory(path.parent) as parent:
    return walk(parent, path.name)


def _workspace_snapshot(workspace):
  # 原 Host 已决定 Git/登记根语义；这里只复核原物理对象及少量链接元数据。
  root = _canonical(workspace["worktree_path"])
  info = root.lstat()
  if {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid} != workspace["canonical_worktree_identity"]:
    raise Conflict("ROOT_IDENTITY")
  value = {"worktree": root_identity(root)}
  git = workspace["git_dir_path"]
  if git is not None:
    git = _canonical(git);info = git.lstat()
    if {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid} != workspace["git_dir_identity"]:
      raise Conflict("ROOT_IDENTITY")
    marker = root / ".git"
    value["git_dir"] = root_identity(git)
    value["marker"] = root_identity(marker) if marker.is_dir() and not marker.is_symlink() else _scan(marker)
    value["metadata"] = {name: _scan(git / name) if (git / name).exists() or (git / name).is_symlink() else None
      for name in ("HEAD", "gitdir", "commondir")}
  return value


def _canonical(path):
  path = configured_path(str(path))
  if path.resolve(strict=True) != path: raise Conflict("CHECK_TRUSTED_INPUT_CANONICAL")
  return path


def compile_trusted(binding, candidate, executable, context):
  if binding.get("kind") not in ("build", "tests") or binding.get("parser") not in ("exit-code", "json", "tap", "pytest") or type(binding.get("minimum_tests")) is not int or binding["minimum_tests"] < 1:
    raise ConfigError("pi-check-result-contract")
  if binding["kind"] == "tests" and binding["parser"] == "exit-code": raise ConfigError("pi-managed-test-count-required")
  table = _table();candidate = _canonical(candidate);executable = _canonical(executable)
  if root_identity(candidate) != context["candidate_identity"]: raise Conflict("ROOT_IDENTITY")
  writes = [];workspace_snapshots = []
  for row in context["worker_scope"]:
    path = _canonical(row["path"])
    if root_identity(path) != row["root_identity"]: raise Conflict("ROOT_IDENTITY")
    if any(Path(m["mountpoint"]) != path and Path(m["mountpoint"]).is_relative_to(path) for m in table):
      raise Conflict("CHECK_PHYSICAL_SCOPE_SUBMOUNT")
    writes.append(path)
    workspace_snapshots.append(_workspace_snapshot(row["workspace"]))
  protected = [configured_path(p) for p in context["protected_roots"]]
  def admit(path, *, snapshot=True):
    if any(_overlaps(path, root, table) for root in writes): raise Conflict("CHECK_IMPLEMENTATION_WRITABLE")
    for root in protected:
      if path.is_relative_to(root) or root.is_relative_to(path) or root.exists() and _overlaps(path, root, table):
        raise Conflict("CHECK_TRUSTED_INPUT_PRIVATE")
    return _scan(path, executable=path == executable) if snapshot else None
  exe = admit(executable);inputs = [];roots = {}
  engine = context["engine"]
  if _scan(_canonical(engine["path"]), executable=True) != engine["snapshot"]: raise Conflict("ADMISSION_STALE")
  node = engine["kind"] == "node" and exe["sha256"] == engine["snapshot"]["sha256"]
  declared = binding.get("trusted_inputs", [])
  if not isinstance(declared, list) or len(declared) > 128: raise ConfigError("pi-check-trusted-input")
  if not (node and inline_node(binding)) and not declared: raise Conflict("CHECK_TRUSTED_INPUT_REQUIRED")
  for item in declared:
    if not isinstance(item, dict) or set(item) != {"root_ref", "relative_path"}: raise ConfigError("pi-check-trusted-input")
    name = item["root_ref"]
    if name not in context["roots"] or name not in binding.get("read_roots", []): raise Conflict("CHECK_TRUSTED_ROOT_UNBOUND")
    root = _canonical(context["roots"][name]["path"])
    if root == Path("/") or root == Path.home(): raise Conflict("CHECK_READ_ROOT_TOO_BROAD")
    relative = Path(".") if item["relative_path"] == "." else relative_path(item["relative_path"])
    path = _canonical(root / relative)
    if not path.is_relative_to(root): raise Conflict("CHECK_TRUSTED_ROOT_UNBOUND")
    # 父根也不能位于 Writer/秘密范围；只读挂载不撤销原 Writer 权限。
    admit(root, snapshot=False)
    if root.lstat().st_mode & 0o6022: raise Conflict("CHECK_TRUSTED_INPUT_PERMISSIONS")
    if any(Path(m["mountpoint"]) != root and Path(m["mountpoint"]).is_relative_to(root) for m in table): raise Conflict("CHECK_PHYSICAL_SCOPE_SUBMOUNT")
    roots[name] = {"path": str(root), "identity": root_identity(root)}
    inputs.append({"root_ref": name, "relative_path": item["relative_path"], "path": str(path), "snapshot": admit(path)})
  def covered(path):
    return any(path == Path(row["path"]) or Path(row["path"]).is_dir() and path.is_relative_to(Path(row["path"])) for row in inputs)
  def implementation(value):
    path = _canonical(Path(value) if Path(value).is_absolute() else candidate / value)
    if not covered(path): raise Conflict("CHECK_TRUSTED_INPUT_REQUIRED")
  if node:
    if not inline_node(binding):
      args = binding["args"];index = 0
      while index < len(args):
        value = args[index]
        if value == "--":
          index += 1;break
        if value in ("-r", "--require", "--import"):
          if index + 1 >= len(args) or args[index + 1].startswith("-"): raise Conflict("CHECK_TRUSTED_INPUT_UNVERIFIABLE")
          implementation(args[index + 1]);index += 2;continue
        if value.startswith(("--require=", "--import=")):
          name = value.split("=", 1)[1]
          if not name: raise Conflict("CHECK_TRUSTED_INPUT_UNVERIFIABLE")
          implementation(name);index += 1;continue
        if value.startswith("-"): raise Conflict("CHECK_TRUSTED_INPUT_UNVERIFIABLE")
        break
      if index >= len(args) or not args[index]: raise Conflict("CHECK_TRUSTED_INPUT_UNVERIFIABLE")
      implementation(args[index])
      # 脚本之后的固定 argv 是 subject 参数，不根据路径猜测接受逻辑。
  elif not covered(executable):
    raise Conflict("CHECK_TRUSTED_INPUT_UNVERIFIABLE")
  # 既有 inputs 是 acceptance logic，不因 candidate 内容摘要而成为可信来源。
  candidate_inputs = []
  for name in binding.get("inputs", []):
    path = _canonical(candidate / relative_path(name));candidate_inputs.append({"path": str(path), "snapshot": admit(path)})
  if _table() != table or any(root_identity(row["path"]) != row["root_identity"] for row in context["worker_scope"]):
    raise Conflict("CHECK_PHYSICAL_SCOPE_DRIFT")
  return {"context": deepcopy(context), "roots": roots, "executable_parent": root_identity(executable.parent), "executable": exe, "trusted_inputs": inputs, "candidate_inputs": candidate_inputs, "workspace_snapshots": workspace_snapshots}


def verify_trusted(check):
  expected = check["trusted_implementation"];context = expected["context"]
  with Tree(Path(context["manifest_path"]).parent, private=False) as tree:
    raw = tree.read(Path(context["manifest_path"]).name)
  if raw is None or digest(json.loads(raw[0])) != context["manifest_digest"]: raise Conflict("ADMISSION_STALE")
  current = json.loads(raw[0])
  if digest(current["permission_policy"]) != context["policy_digest"]: raise Conflict("ADMISSION_STALE")
  binding = current["options"]["checks"][context["checker_id"]]
  if binding != check["trusted_binding"] or current["options"]["paths"]["roots"] != context["roots"]:
    raise Conflict("ADMISSION_STALE")
  role = current.get("role_bindings", {}).get("task-keeper-writer", {})
  if role.get("managed") is not True or role.get("write_roots") != [row["root_ref"] for row in context["worker_scope"]]:
    raise Conflict("ADMISSION_STALE")
  actual = compile_trusted(binding, Path(check["cwd"]), Path(check["argv"][0]), context)
  if actual != expected: raise Conflict("CHECK_TRUSTED_IMPLEMENTATION_CHANGED")
