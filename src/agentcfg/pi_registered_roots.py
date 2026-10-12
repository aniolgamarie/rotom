"""显式非Git根登记；查询观察不授予Writer或执行许可。"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat

from .deployment import json_bytes
from .pi_dependencies import digest
from .paths import PathError, _absolute_directory, _text
from .storage import Conflict, Tree, ensure_private


def physical(info):
  return {"dev": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}


def closed(value, keys):
  if not isinstance(value, dict) or set(value) != set(keys):
    raise Conflict("工作根登记结构无效")


def identity(value):
  closed(value, ("dev", "inode", "uid"))
  if any(type(item) is not int or item < 0 for item in value.values()) or value["inode"] < 1:
    raise Conflict("工作根登记身份无效")


def pairs(items):
  result = {}
  for key, value in items:
    if key in result: raise Conflict("工作根登记含重复字段")
    result[key] = value
  return result


def _has_git_marker(directory):
  return os.path.lexists(directory / ".git")


def ancestors(path):
  return [path, *path.parents]


class RegisteredRoots:
  def __init__(self, *, account_home=None):
    self.account_home = Path(account_home if account_home is not None else pwd.getpwuid(os.geteuid()).pw_dir)
    self.account_home = self.account_home.absolute()
    self.anchor = self.account_home / ".agentcfg-workspaces"
    self.account_identity = None
    self.anchor_identity = None
    try:
      _text(str(self.account_home))
      if ".." in self.account_home.parts: raise Conflict("账户目录路径无效")
      with _absolute_directory(self.account_home) as fd:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022: raise Conflict("账户目录属主或权限无效")
        self.account_identity = physical(info)
    except (OSError, PathError):
      raise Conflict("账户目录不可安全核验") from None

  @contextmanager
  def _locked(self, *, write=False):
    try:
      with _absolute_directory(self.account_home) as fd:
        if os.fstat(fd).st_mode & 0o022: raise Conflict("账户目录权限无效")
        if physical(os.fstat(fd)) != self.account_identity:
          raise Conflict("账户目录身份已变化")
        try: fcntl.flock(fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError: raise Conflict("WORKSPACE_BUSY：账户协调锁繁忙") from None
        except OSError: raise Conflict("账户协调锁不可用") from None
        try:
          with _absolute_directory(self.account_home) as current:
            if physical(os.fstat(current)) != self.account_identity: raise Conflict("账户目录身份已变化")
          yield fd
        finally: fcntl.flock(fd, fcntl.LOCK_UN)
    except (OSError, PathError):
      raise Conflict("账户协调路径不可安全核验") from None

  def _coordinator(self, anchor_identity):
    return {"canonical_path": str(self.account_home), "account_identity": self.account_identity,
            "registry_identity": anchor_identity}

  def _root_id(self, coordinator, info):
    # 路径仅用于复核，不参与物理根身份。
    return digest({"coordinator": {"account_identity": coordinator["account_identity"],
                   "registry_identity": coordinator["registry_identity"]}, "root": info})

  @contextmanager
  def _state(self, account_fd, *, create=False):
    created = False
    if not os.path.lexists(self.anchor):
      if self.anchor_identity is not None: raise Conflict("账户协调目录已失联")
      if not create:
        yield None, None, None
        return
      ensure_private(self.anchor)
      created = True
      os.fsync(account_fd)
    with Tree(self.anchor) as tree:
      current = physical(os.fstat(tree.fd))
      if self.anchor_identity is not None and current != self.anchor_identity:
        raise Conflict("账户协调目录身份已变化")
      self.anchor_identity = current
      if set(os.listdir(tree.fd)) - {"registry.json", "claims.json", "claim-evidence", "workspace-leases", "project-metadata", "reviewer-budget.json", "reviewer-budget", "reviewer-authority.json", "reviewer-scopes"}: raise Conflict("账户协调目录含未知内容")
      raw = tree.read("registry.json", max_bytes=1024 * 1024)
      coordinator = self._coordinator(current)
      if raw is None:
        if not created: raise Conflict("账户协调登记缺失")
        data = {"schema_version": 1, "coordinator": coordinator, "roots": []}
      else:
        if raw[1] != 0o600: raise Conflict("工作根登记权限无效")
        try: data = json.loads(raw[0], object_pairs_hook=pairs)
        except (ValueError, UnicodeError): raise Conflict("工作根登记JSON无效") from None
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] not in (1, 2): raise Conflict("工作根登记版本无效")
        closed(data, ("schema_version", "coordinator", "roots") + (("claim_protocol",) if data["schema_version"] == 2 else ()))
        if data["schema_version"] == 2 and (type(data["claim_protocol"]) is not int or data["claim_protocol"] != 1): raise Conflict("工作根协调协议无效")
        closed(data["coordinator"], ("canonical_path", "account_identity", "registry_identity"))
        identity(data["coordinator"]["account_identity"]); identity(data["coordinator"]["registry_identity"])
        if data["coordinator"] != coordinator: raise Conflict("工作根协调身份冲突")
        if not isinstance(data["roots"], list): raise Conflict("工作根记录无效")
        ids, physical_ids, paths = set(), set(), set()
        for record in data["roots"]:
          closed(record, ("root_id", "canonical_path", "filesystem_identity", "kind"))
          identity(record["filesystem_identity"])
          path = record["canonical_path"]
          try: _text(path)
          except PathError: raise Conflict("工作根记录路径无效") from None
          if not Path(path).is_absolute() or str(Path(path)) != path or ".." in Path(path).parts: raise Conflict("工作根记录路径无效")
          if record["kind"] != "non-git" or record["root_id"] != self._root_id(coordinator, record["filesystem_identity"]): raise Conflict("工作根记录摘要无效")
          key = tuple(record["filesystem_identity"][key] for key in ("dev", "inode", "uid"))
          if key in physical_ids or record["root_id"] in ids or path in paths: raise Conflict("工作根登记重复")
          physical_ids.add(key); ids.add(record["root_id"]); paths.add(path)
      if data["schema_version"] == 2 or "claims.json" in os.listdir(tree.fd) or "claim-evidence" in os.listdir(tree.fd):
        from .pi_workspace_claims import read_table
        claims = read_table(tree, coordinator)
        if data["schema_version"] == 1 and (claims["claims"] or "claim-evidence" in os.listdir(tree.fd)):
          raise Conflict("账户协调初始化存在未知占用")
      for directory, expected in (("workspace-leases", {"write-lease.json", "evidence"}),
                                  ("project-metadata", {".agentcfg-openspec.json", ".agentcfg-openspec-pending.json"})):
        if directory not in os.listdir(tree.fd): continue
        if directory == "workspace-leases" and data["schema_version"] != 2: raise Conflict("账户协调初始化存在未知局部占用")
        with Tree(tree.root / directory) as markers:
          known = {record["root_id"] for record in data["roots"]}
          for name in os.listdir(markers.fd):
            if name not in known: raise Conflict("账户协调存在未登记的局部占用")
            with Tree(markers.root / name) as local:
              if set(os.listdir(local.fd)) - expected: raise Conflict("局部工作区标记含未知内容")
      yield tree, data, raw

  def _status(self, record):
    path = Path(record["canonical_path"])
    try:
      with _absolute_directory(path) as fd:
        if any(_has_git_marker(item) for item in ancestors(path)): return "identity-changed"
        return "current" if physical(os.fstat(fd)) == record["filesystem_identity"] else "identity-changed"
    except FileNotFoundError: return "missing"
    except (OSError, PathError): return "identity-changed"

  def _observe(self, record):
    return {"record": deepcopy(record), "status": self._status(record)}

  def _canonical(self, path):
    try:
      _text(os.fspath(path))
      canonical = Path(path).resolve(strict=True)
      with _absolute_directory(canonical) as fd:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid(): raise Conflict("工作根属主无效")
        return canonical, physical(info)
    except (OSError, RuntimeError, PathError): raise Conflict("工作根路径不可安全核验") from None

  def _allowed(self, path):
    # 锚尚未创建时，账户目录的祖先同样覆盖未来控制根。
    chain = ancestors(path)
    for item in chain:
      if _has_git_marker(item): raise Conflict("Git根不得作为非Git根登记")
    business = {tuple(physical(item.stat()).values()) for item in chain}
    anchor_exists = self.anchor.exists()
    control = self.anchor if anchor_exists else self.account_home
    control_chain = {tuple(physical(item.stat()).values()) for item in ancestors(control)}
    root_key = tuple(physical(path.stat()).values())
    control_key = tuple(physical(control.stat()).values())
    if root_key in control_chain or (anchor_exists and control_key in business):
      raise Conflict("业务根覆盖账户控制目录")

  def register(self, path):
    try:
      with self._locked(write=True) as account_fd:
        canonical, info = self._canonical(path)
        self._allowed(canonical)
        with self._state(account_fd, create=True) as (tree, data, raw):
          for record in data["roots"]:
            if record["canonical_path"] == str(canonical) or record["filesystem_identity"] == info:
              if self._status(record) != "current": raise Conflict("已登记工作根失联或身份变化")
              if record["filesystem_identity"] != info: raise Conflict("工作根身份已变化")
              return self._observe(record)
          record = {"root_id": self._root_id(data["coordinator"], info), "canonical_path": str(canonical),
                    "filesystem_identity": info, "kind": "non-git"}
          fresh_path, fresh_info = self._canonical(canonical)
          if fresh_path != canonical or fresh_info != info: raise Conflict("工作根登记前身份已变化")
          self._allowed(canonical)
          data["roots"].append(record)
          tree.replace("registry.json", json_bytes(data), expected=raw[2] if raw else None)
          return self._observe(record)
    except (OSError, PathError): raise Conflict("工作根登记不可安全完成") from None

  def list(self):
    with self._locked() as account_fd:
      with self._state(account_fd) as (_, data, __):
        return [self._observe(record) for record in data["roots"]] if data else []

  def inspect(self, path):
    try:
      _text(os.fspath(path))
      target = Path(os.path.abspath(path))
      with self._locked() as account_fd:
        with self._state(account_fd) as (_, data, __):
          if not data: return {"status": "not-registered", "record": None}
          # 失联路径仍可按登记路径诊断；不用于任何写入准入。
          for record in data["roots"]:
            if record["canonical_path"] == str(target): return self._observe(record)
          canonical, _ = self._canonical(path)
          for ancestor in ancestors(canonical):
            key = physical(ancestor.stat())
            for record in data["roots"]:
              if record["filesystem_identity"] == key: return self._observe(record)
          return {"status": "not-registered", "record": None}
    except (OSError, PathError): raise Conflict("工作根查询不可安全完成") from None


def cmd_workspace(args):
  registry = RegisteredRoots()
  value = registry.list() if args.workspace_command == "list" else getattr(registry, args.workspace_command)(args.path)
  if args.format == "json": print(json.dumps(value, ensure_ascii=False, sort_keys=True))
  else:
    observations = value if isinstance(value, list) else [value]
    for observation in observations:
      record = observation["record"]
      print(f"{observation['status']}: {record['canonical_path'] if record else '未登记'}")
  return 0
