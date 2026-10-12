"""账户协调下的Git与已登记非Git写租约；持久记录不随profile HOME改变。"""

from contextlib import contextmanager
from copy import deepcopy
import errno
import fcntl
import json
import os
from pathlib import Path
import stat

from .activity import digest
from . import pi_registered_roots as registered_roots
from .deployment import json_bytes
from .paths import PathError, _absolute_directory
from .pi_catalog import validate
from .schema import ConfigError
from .pi_workspace_claims import WorkspaceClaims, checked_evidence, context, strict_integers
from .pi_registered_roots import pairs
from .storage import Conflict, Tree, ensure_private


MARKER = "write-lease.json"


def filesystem_identity(info):
  return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}


class WorkspaceLeases:
  def __init__(self, boot_id, *, account_home=None):
    if not isinstance(boot_id, str) or not boot_id:
      raise ConfigError("pi-host-identity")
    self.boot_id = boot_id
    self.claims = WorkspaceClaims(account_home=account_home)

  def identify(self, worktree):
    # 公共查询只持短读锁。已持账户锁的准入路径使用同一份registry快照，避免重入。
    with self.claims.registry._locked() as account_fd:
      with self.claims.registry._state(account_fd) as (_, registry, __):
        return self._identify(worktree, registry)

  def identify_git(self, worktree):
    planned = self.identify(worktree)
    if planned["git_dir_path"] is None:
      raise Conflict("WORKSPACE_GIT_REQUIRED：此操作仅支持Git工作树")
    return planned

  def _identify(self, worktree, registry):
    try:
      root = Path(worktree).resolve(strict=True)
      if not root.is_dir():
        raise ValueError()
      records = registry["roots"] if registry else []
      while True:
        with _absolute_directory(root) as fd:
          info = os.fstat(fd)
          current = registered_roots.physical(info)
        matching = [row for row in records if row["canonical_path"] == str(root) or row["filesystem_identity"] == current]
        if matching:
          if len(matching) != 1 or self.claims.registry._status(matching[0]) != "current": raise ValueError()
          row = matching[0]
          if row["filesystem_identity"] != current or info.st_uid != os.geteuid(): raise ValueError()
          identity = {"host_boot_id": self.boot_id, "uid": os.geteuid(), "canonical_worktree_identity": filesystem_identity(info),
            "git_dir_identity": None, "workspace_kind": "registered-root", "registered_root_id": row["root_id"]}
          return {**identity, "workspace_key": digest(identity), "worktree_path": row["canonical_path"], "git_dir_path": None}
        if registered_roots._has_git_marker(root): break
        if root == root.parent: raise ValueError()
        root = root.parent
      with _absolute_directory(root) as fd:
        root_identity = filesystem_identity(os.fstat(fd))
      if root_identity["uid"] != os.geteuid():
        raise ValueError()
      marker = root / ".git"
      info = marker.lstat()
      if stat.S_ISDIR(info.st_mode):
        git_dir = marker
      elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        with Tree(root, private=False) as tree:
          raw = tree.read(".git")
        line = raw[0].decode().strip()
        if not line.startswith("gitdir: ") or "\n" in line:
          raise ValueError()
        git_dir = (root / line[8:]).resolve(strict=True)
        with Tree(git_dir, private=False) as tree:
          backlink, common = tree.read("gitdir"), tree.read("commondir")
        if not backlink or not common:
          raise ValueError()
        if (git_dir / backlink[0].decode().strip()).resolve(strict=True) != marker:
          raise ValueError()
        common_dir = (git_dir / common[0].decode().strip()).resolve(strict=True)
        with _absolute_directory(common_dir) as fd:
          if os.fstat(fd).st_uid != os.geteuid():
            raise ValueError()
      else:
        raise ValueError()
      with _absolute_directory(git_dir) as fd:
        git_identity = filesystem_identity(os.fstat(fd))
      if git_identity["uid"] != os.geteuid():
        raise ValueError()
      with Tree(git_dir, private=False) as tree:
        head = tree.read("HEAD")
      if not head or not head[0].strip():
        raise ValueError()
      identity = {"host_boot_id": self.boot_id, "uid": os.geteuid(), "canonical_worktree_identity": root_identity, "git_dir_identity": git_identity}
      return {**identity, "workspace_key": digest(identity), "worktree_path": str(root), "git_dir_path": str(git_dir)}
    except (OSError, ValueError, UnicodeError, PathError, Conflict):
      raise Conflict("工作区不是可核验的Git工作树或已登记非Git根；写入未获准") from None

  @contextmanager
  def _git_locked(self, planned, *, create=False):
    with _absolute_directory(Path(planned["git_dir_path"])) as fd:
      if filesystem_identity(os.fstat(fd)) != planned["git_dir_identity"]:
        raise Conflict("Git目录句柄身份冲突")
      try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except OSError as error:
        if error.errno in (errno.EAGAIN, errno.EACCES):
          raise Conflict("WORKSPACE_BUSY：同一工作区有并发写入准入") from None
        raise Conflict("此文件系统无法提供必要的工作区锁") from None
      try:
        private = Path(planned["git_dir_path"]) / "agentcfg"
        if create:
          ensure_private(private)
        with Tree(private) as tree:
          if tree.fd is not None:
            names = os.listdir(tree.fd)
            if any(name not in (MARKER, "evidence") for name in names):
              raise Conflict("Git目录的agentcfg标记存在未知内容；不能接管")
          yield tree
      finally:
        fcntl.flock(fd, fcntl.LOCK_UN)

  @contextmanager
  def _coordinated(self, planned, *, create=False):
    # 全局账户锁始终在Git目录锁之前；不在持锁区间调用registry public API。
    with self.claims.locked(create=create) as (global_tree, table, registry):
      identify = lambda path: self._identify(path, registry)
      if identify(planned["worktree_path"]) != planned:
        raise Conflict("工作区或协调身份已改变")
      if planned["git_dir_path"] is not None:
        with self._git_locked(planned, create=create) as tree:
          yield tree, global_tree, table, identify
      else:
        # 非Git局部标记归账户协调目录所有，不在业务目录创建隐藏文件。
        private = global_tree.root / "workspace-leases" / planned["registered_root_id"]
        if create: ensure_private(private)
        with Tree(private) as tree:
          if tree.fd is not None and set(os.listdir(tree.fd)) - {MARKER, "evidence"}:
            raise Conflict("非Git工作区标记存在未知内容")
          yield tree, global_tree, table, identify

  def _read(self, tree, planned):
    raw = tree.read(MARKER, max_bytes=1024 * 1024)
    if raw is None:
      return None
    try:
      value = json.loads(raw[0], object_pairs_hook=pairs)
      strict_integers(value)
      validate("workspace-write-lease", value)
      # 已核实释放的标记可跨启动使用；活动或未知标记仍严格绑定原 boot。
      compare = set(planned) - ({"host_boot_id", "workspace_key"} if value["state"] == "released" else set())
      if raw[1] != 0o600 or any(value[key] != planned[key] for key in compare):
        raise ValueError()
      if value["allocation_id"] != value["execution_lease_id"]:
        raise ValueError()
      if value["state"] == "released":
        if not value["termination_evidence_refs"]:
          raise ValueError()
        for reference in value["termination_evidence_refs"]:
          proof = tree.read("evidence/" + reference + ".json", max_bytes=1024 * 1024)
          if proof is None or proof[1] != 0o600:
            raise ValueError()
          evidence = json.loads(proof[0], object_pairs_hook=pairs)
          strict_integers(evidence)
          validate("termination-evidence", evidence)
          if (evidence["execution_lease_id"] != value["execution_lease_id"] or evidence["grant_generation"] != value["grant_generation"]
              or evidence["evidence_digest"] != reference or reference != digest({k: v for k, v in evidence.items() if k != "evidence_digest"})):
            raise ValueError()
    except (ValueError, TypeError, KeyError, ConfigError):
      raise Conflict("工作区写租约损坏或身份未知；保护保持生效") from None
    return value

  @contextmanager
  def maintenance(self, worktree):
    """同步人工维护持有同一准入锁；此区间禁止派生会写工作树的进程。"""
    planned = self.identify(worktree)
    with self._coordinated(planned) as (tree, global_tree, table, identify):
      self.claims.check(table, planned, identify)
      current = self._read(tree, planned)
      if current is not None and current["state"] != "released":
        raise Conflict("WORKSPACE_BUSY：受管写操作尚未终止，不能初始化项目")
      yield deepcopy(planned)

  def read(self, planned):
    with self._coordinated(planned) as (tree, global_tree, table, identify):
      return self._read(tree, planned)

  def _owner(self, saved, lease):
    return all(saved[key] == lease[source] for key, source in (
      ("instance_id", "instance_id"), ("execution_lease_id", "lease_id"), ("allocation_id", "allocation_id"),
      ("holder_nonce", "owner_nonce"), ("supervisor_activation_id", "supervisor_activation_id")))

  def reserve(self, planned, lease):
    # 仅受信监督者调用；它必须先把完整 lease 意图落盘（ExecutionStore.begin 的顺序契约）。
    if (lease["state"] != "allocating" or lease["spawn_committed"] or planned not in lease["planned_workspaces"]
        or lease["allocation_id"] != lease["lease_id"]):
      raise Conflict("工作区预留缺少完整的未启动分配意图")
    with self._coordinated(planned, create=True) as (tree, global_tree, table, identify):
      old = self._read(tree, planned)
      claim = self.claims.find(table, planned)
      self.claims.check(table, planned, identify, lease=lease)
      if claim and claim["record"]["state"] == "released" and self._owner(claim["record"], lease):
        raise Conflict("同次已释放分配不得重新预留")
      if claim and claim["record"]["state"] != "released" and (not self.claims.matches(claim, lease) or claim["record"]["state"] != "reserved"):
        raise Conflict("WORKSPACE_BUSY：账户占用不属于本次未启动分配")
      if old is None and os.listdir(tree.fd):
        raise Conflict("工作区有未归属的证据记录；不能推定可写")
      if old and old["state"] != "released":
        if self._owner(old, lease) and old["state"] == "reserved" and old["grant_generation"] == lease["grant_generation"] and self.claims.matches(claim, lease):
          return old
        raise Conflict("WORKSPACE_BUSY：其他活动或未知写租约仍保护该工作区")
      record = {"schema_version": 1, **deepcopy(planned), "workspace_lease_id": digest([planned["workspace_key"], lease["lease_id"]]),
        "instance_id": lease["instance_id"], "execution_lease_id": lease["lease_id"], "allocation_id": lease["allocation_id"],
        "task_id": lease["task_id"], "attempt_id": lease["attempt_id"], "holder_nonce": lease["owner_nonce"],
        "supervisor_activation_id": lease["supervisor_activation_id"], "grant_generation": lease["grant_generation"],
        "state": "reserved", "termination_evidence_refs": []}
      validate("workspace-write-lease", record)
      self.claims.save(global_tree, table, planned, lease, record)
      tree.write_state(MARKER, json_bytes(record))
      return record

  def activate(self, planned, lease):
    with self._coordinated(planned) as (tree, global_tree, table, identify):
      old = self._read(tree, planned)
      claim = self.claims.find(table, planned)
      self.claims.check(table, planned, identify, lease=lease)
      if not self.claims.matches(claim, lease) or claim["record"]["state"] not in ("reserved", "active"):
        raise Conflict("账户工作区预留已丢失；不能激活")
      if not old or not self._owner(old, lease) or old["state"] not in ("reserved", "active") or old["grant_generation"] != lease["grant_generation"]:
        raise Conflict("工作区预留不再属于该执行")
      if not lease["spawn_committed"] or lease["process_identity"] is None:
        raise Conflict("工作区激活缺少已登记进程身份")
      old["state"] = "active"
      self.claims.save(global_tree, table, planned, lease, old)
      tree.write_state(MARKER, json_bytes(old))

  def assert_reserved(self, planned, lease):
    with self._coordinated(planned) as (tree, global_tree, table, identify):
      record = self._read(tree, planned)
      claim = self.claims.find(table, planned)
      self.claims.check(table, planned, identify, lease=lease)
      if not self.claims.matches(claim, lease) or claim["record"]["state"] != "reserved":
        raise Conflict("账户工作区预留已丢失；不能启动")
      if not record or not self._owner(record, lease) or record["state"] != "reserved" or record["grant_generation"] != lease["grant_generation"]:
        raise Conflict("工作区预留已经丢失或撤销，不能启动")
      return record

  def release(self, planned, lease, evidence, *, missing_ok=False):
    try:
      validate("termination-evidence", evidence)
    except ConfigError:
      raise Conflict("工作区释放证据不完整") from None
    if (evidence.get("verified") is not True or evidence.get("execution_lease_id") != lease["lease_id"]
        or evidence.get("grant_generation") != lease["grant_generation"]
        or evidence.get("evidence_digest") != digest({key: value for key, value in evidence.items() if key != "evidence_digest"})
        or evidence.get("kind") not in ("never-started", "terminated")):
      raise Conflict("工作区释放缺少本次执行的终止证据")
    if evidence["kind"] == "never-started" and lease["spawn_committed"]:
      raise Conflict("已经提交启动，不能使用未启动证明释放工作区")
    checked_evidence(evidence, {"execution_lease_id": lease["lease_id"], "grant_generation": lease["grant_generation"]}, context(lease))
    with self._coordinated(planned) as (tree, global_tree, table, identify):
      old = self._read(tree, planned)
      claim = self.claims.find(table, planned)
      # 分配失败的补偿遍历完整计划；未曾属于本分配的根不需要释放。
      # 任一同allocation标记仍要走严格owner/context/generation校验，不能误清未知保护。
      foreign_claim = claim is None or claim["record"]["allocation_id"] != lease["allocation_id"]
      foreign_local = old is None or old["allocation_id"] != lease["allocation_id"]
      if missing_ok and evidence["kind"] == "never-started" and foreign_claim and foreign_local:
        return False
      if claim is None:
        if old is not None: raise Conflict("账户占用缺失；旧局部标记不能自行释放")
        if missing_ok: return False
        raise Conflict("不能释放缺失的账户工作区租约")
      if not self.claims.matches(claim, lease, exact_generation=False): raise Conflict("不能释放其他分配的账户占用")
      if claim["record"]["grant_generation"] > lease["grant_generation"]: raise Conflict("不能用旧授权代释放新的账户占用")
      released = dict(claim["record"], grant_generation=lease["grant_generation"])
      checked_evidence(evidence, released, context(lease))
      if old is not None and (not self._owner(old, lease) or old["grant_generation"] > lease["grant_generation"]):
        raise Conflict("不能覆盖其他局部工作区租约")
      if old is None and evidence["kind"] != "never-started": raise Conflict("缺失局部标记只能凭同次未启动证明释放")
      if old is not None and (old["state"] != "released" or old["grant_generation"] != lease["grant_generation"]):
        tree.write_immutable("evidence/" + evidence["evidence_digest"] + ".json", json_bytes(evidence))
        old.update(state="released", grant_generation=lease["grant_generation"], termination_evidence_refs=[evidence["evidence_digest"]])
        tree.write_state(MARKER, json_bytes(old))
      if claim["record"]["state"] != "released" or claim["record"]["grant_generation"] != lease["grant_generation"]:
        global_tree.write_immutable("claim-evidence/" + evidence["evidence_digest"] + ".json", json_bytes(evidence))
        record = deepcopy(claim["record"])
        record.update(state="released", grant_generation=lease["grant_generation"], termination_evidence_refs=[evidence["evidence_digest"]])
        self.claims.save(global_tree, table, planned, lease, record)
      return True
