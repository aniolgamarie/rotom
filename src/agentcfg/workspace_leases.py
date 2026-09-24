"""以 worktree 专属 git-dir inode 加锁，持久记录不随 HOME/profile 改变。"""

from contextlib import contextmanager
from copy import deepcopy
import errno
import fcntl
import json
import os
from pathlib import Path
import stat

from .activity import digest
from .deployment import json_bytes
from .paths import PathError, _absolute_directory
from .pi_catalog import validate
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


MARKER = "write-lease.json"


def filesystem_identity(info):
  return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}


class WorkspaceLeases:
  def __init__(self, boot_id):
    if not isinstance(boot_id, str) or not boot_id:
      raise ConfigError("pi-host-identity")
    self.boot_id = boot_id

  def identify(self, worktree):
    try:
      root = Path(worktree).resolve(strict=True)
      if not root.is_dir():
        raise ValueError()
      while not (root / ".git").exists() and not (root / ".git").is_symlink() and root != root.parent:
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
      raise Conflict("工作区不是可核验的本机Git工作树；写入未获准") from None

  @contextmanager
  def _locked(self, planned, *, create=False):
    if self.identify(planned["worktree_path"]) != planned:
      raise Conflict("工作区或Git目录身份已改变")
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

  def _read(self, tree, planned):
    raw = tree.read(MARKER)
    if raw is None:
      return None
    try:
      value = json.loads(raw[0])
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
          proof = tree.read("evidence/" + reference + ".json")
          if proof is None or proof[1] != 0o600:
            raise ValueError()
          evidence = json.loads(proof[0])
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
    with self._locked(planned) as tree:
      current = self._read(tree, planned)
      if current is not None and current["state"] != "released":
        raise Conflict("WORKSPACE_BUSY：受管写操作尚未终止，不能初始化项目")
      yield

  def read(self, planned):
    with self._locked(planned) as tree:
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
    with self._locked(planned, create=True) as tree:
      old = self._read(tree, planned)
      if old is None and os.listdir(tree.fd):
        raise Conflict("工作区有未归属的证据记录；不能推定可写")
      if old and old["state"] != "released":
        if self._owner(old, lease) and old["state"] == "reserved" and old["grant_generation"] == lease["grant_generation"]:
          return old
        raise Conflict("WORKSPACE_BUSY：其他活动或未知写租约仍保护该工作区")
      record = {"schema_version": 1, **deepcopy(planned), "workspace_lease_id": digest([planned["workspace_key"], lease["lease_id"]]),
        "instance_id": lease["instance_id"], "execution_lease_id": lease["lease_id"], "allocation_id": lease["allocation_id"],
        "task_id": lease["task_id"], "attempt_id": lease["attempt_id"], "holder_nonce": lease["owner_nonce"],
        "supervisor_activation_id": lease["supervisor_activation_id"], "grant_generation": lease["grant_generation"],
        "state": "reserved", "termination_evidence_refs": []}
      validate("workspace-write-lease", record)
      tree.write_state(MARKER, json_bytes(record))
      return record

  def activate(self, planned, lease):
    with self._locked(planned) as tree:
      old = self._read(tree, planned)
      if not old or not self._owner(old, lease) or old["state"] not in ("reserved", "active") or old["grant_generation"] != lease["grant_generation"]:
        raise Conflict("工作区预留不再属于该执行")
      if not lease["spawn_committed"] or lease["process_identity"] is None:
        raise Conflict("工作区激活缺少已登记进程身份")
      old["state"] = "active"
      tree.write_state(MARKER, json_bytes(old))

  def assert_reserved(self, planned, lease):
    with self._locked(planned) as tree:
      record = self._read(tree, planned)
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
    with self._locked(planned) as tree:
      old = self._read(tree, planned)
      if old is None or not self._owner(old, lease):
        if missing_ok:
          return False
        raise Conflict("不能释放不属于当前执行的工作区租约")
      if old["grant_generation"] > lease["grant_generation"]:
        raise Conflict("工作区已存在更新授权，不能用旧证据释放")
      if old["state"] != "released":
        tree.write_immutable("evidence/" + evidence["evidence_digest"] + ".json", json_bytes(evidence))
        old.update(state="released", grant_generation=lease["grant_generation"], termination_evidence_refs=[evidence["evidence_digest"]])
        tree.write_state(MARKER, json_bytes(old))
      return True
