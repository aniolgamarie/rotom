"""Pi 持久执行记录；结果完成不等于物理终止，未知活动始终阻止变更。"""

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
import fcntl
import stat
import threading

from .deployment import json_bytes
from .paths import safe_id
from .pi_catalog import validate
from .schema import ConfigError
from .storage import Conflict, Tree, instance_lock


OWNER_KEYS = ("instance_id", "supervisor_activation_id", "manager_activation_id", "owner_nonce", "supervisor_process_identity")


def digest(value):
  return hashlib.sha256(json_bytes(value)).hexdigest()


def timestamp(value):
  return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def allocation_digest(lease):
  return digest({key: lease[key] for key in (*OWNER_KEYS, "allocation_id", "planned_workspaces", "execution_id", "attempt_id")})


def valid_evidence(lease, evidence=None):
  evidence = evidence or lease.get("termination_evidence")
  if not evidence or not evidence.get("verified"):
    return False
  if (evidence["execution_lease_id"] != lease["lease_id"] or evidence["grant_generation"] != lease["grant_generation"]
      or evidence["allocation_journal_digest"] != lease["allocation_journal_digest"]
      or evidence["external_work_ids"] != lease["active_external_work_ids"]
      or evidence["process_identities"] != ([lease["process_identity"]] if lease["process_identity"] else [])
      or evidence["evidence_digest"] != digest({key: value for key, value in evidence.items() if key != "evidence_digest"})):
    return False
  return True


def protected(lease):
  if not valid_evidence(lease):
    return True
  evidence = lease["termination_evidence"]
  return not ((lease["state"] == "reclaimed" and evidence["kind"] == "terminated")
    or (lease["state"] == "failed" and evidence["kind"] == "never-started"))


class ExecutionStore:
  def __init__(self, root, owner, processes, *, workspaces=None, fault=None, now=None, lease_fd=None):
    if set(owner) != set(OWNER_KEYS):
      raise ConfigError("pi-supervisor-owner")
    validate("process-identity", owner["supervisor_process_identity"])
    self.root, self.owner, self.processes = Path(root), deepcopy(owner), processes
    self.workspaces = workspaces
    self.fault = fault or (lambda phase, value: None)
    self.now = now or (lambda: datetime.now(timezone.utc))
    self.lease_fd = lease_fd
    self.mutex = threading.RLock()

  @contextmanager
  def _guard(self, tree):
    with self.mutex:
      if self.lease_fd is None:
        with instance_lock(tree) as fd:
          yield fd
        return
      info = os.fstat(self.lease_fd)
      with tree.parent("instance.lock") as (parent, name):
        expected = os.stat(name, dir_fd=parent, follow_symlinks=False)
      if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
          or info.st_nlink != 1 or (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino)):
        raise Conflict("监督者继承的实例租约身份不匹配")
      try:
        fcntl.flock(self.lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except OSError:
        raise Conflict("监督者没有实例排他租约") from None
      # 此句柄由监督者持有至所有子工作结束，单个请求不解锁。
      yield self.lease_fd

  def _path(self, lease_id):
    return "activity/leases/" + safe_id(lease_id) + ".json"

  def _validate(self, lease):
    try:
      validate("execution-lease", lease)
      valid = (lease["instance_id"] == self.owner["instance_id"] and lease["allocation_id"] == lease["lease_id"]
        and allocation_digest(lease) == lease["allocation_journal_digest"])
      if lease["state"] == "allocating":
        valid = valid and not lease["spawn_committed"] and lease["process_identity"] is None
      if lease["state"] in ("running", "settled", "cancel_requested", "reclaimed"):
        valid = valid and lease["spawn_committed"] and lease["process_identity"] is not None
      if lease["state"] in ("failed", "reclaimed"):
        valid = valid and not protected(lease)
      if lease["state"] == "failed":
        valid = valid and not lease["spawn_committed"] and lease["process_identity"] is None
      if not valid:
        raise ValueError()
    except (ConfigError, KeyError, ValueError, TypeError):
      raise Conflict("Pi执行记录损坏或身份不匹配；保护保持生效") from None

  def read(self, lease_id):
    with Tree(self.root) as tree:
      raw = tree.read(self._path(lease_id))
    if raw is None or raw[1] != 0o600:
      raise Conflict("Pi执行记录缺失或不安全")
    try:
      value = json.loads(raw[0])
    except (ValueError, UnicodeError):
      raise Conflict("Pi执行记录损坏；不能据此解除保护") from None
    self._validate(value)
    if value["lease_id"] != lease_id:
      raise Conflict("Pi执行记录路径身份冲突")
    return value

  def records(self):
    # 同一监督者的原子发布会短暂创建暂存文件；读取也串行，不能把在途写入误判为损坏。
    with self.mutex:
      directory = self.root / "activity/leases"
      if not directory.exists() and not directory.is_symlink():
        return []
      with Tree(directory) as tree:
        names = sorted(os.listdir(tree.fd))
      if any(not name.endswith(".json") for name in names):
        raise Conflict("Pi执行记录目录包含未知状态")
      return [self.read(name[:-5]) for name in names]

  def assert_mutable(self):
    if any(protected(lease) for lease in self.records()):
      raise Conflict("Pi仍有活动或终止未确认的执行；请先检查活动及显式恢复计划")

  def _save(self, tree, lease):
    self._validate(lease)
    tree.write_state(self._path(lease["lease_id"]), json_bytes(lease))

  def _register_owner(self, tree):
    path = "activity/supervisors/" + safe_id(self.owner["supervisor_activation_id"]) + ".json"
    raw = tree.read(path)
    if raw is not None and raw[0] != json_bytes(self.owner):
      raise Conflict("监督者激活身份已被其他控制者使用")
    if raw is None:
      tree.write_state(path, json_bytes(self.owner))

  def _authority(self, lease, owner):
    if owner != self.owner or any(lease[key] != self.owner[key] for key in OWNER_KEYS):
      raise Conflict("Pi执行控制者已改变；旧授权不能用于新激活")
    if self.processes.observe(self.owner["supervisor_process_identity"]) != "alive":
      raise Conflict("Pi监督者身份未确认")

  def _evidence(self, lease, kind):
    evidence = {"schema_version": 1, "kind": kind, "execution_lease_id": lease["lease_id"],
      "process_identities": [lease["process_identity"]] if lease["process_identity"] else [], "external_work_ids": list(lease["active_external_work_ids"]),
      "recorded_at": timestamp(self.now()), "allocation_journal_digest": lease["allocation_journal_digest"],
      "grant_generation": lease["grant_generation"], "verified": True}
    evidence["evidence_digest"] = digest(evidence)
    return evidence

  def begin(self, *, kind, execution_id, task_id, attempt_id, lock_identity, slice_identity, policy_digest,
      candidate_digest, planned_workspaces, spawn, parent_execution_id=None):
    lease = self.allocate(kind=kind, execution_id=execution_id, task_id=task_id, attempt_id=attempt_id,
      lock_identity=lock_identity, slice_identity=slice_identity, policy_digest=policy_digest,
      candidate_digest=candidate_digest, planned_workspaces=planned_workspaces, parent_execution_id=parent_execution_id)
    return self.start(lease["lease_id"], self.owner, spawn=spawn)

  def allocate(self, *, kind, execution_id, task_id, attempt_id, lock_identity, slice_identity, policy_digest,
      candidate_digest, planned_workspaces, parent_execution_id=None):
    lease_id = uuid.uuid4().hex
    planned = sorted(deepcopy(planned_workspaces), key=lambda item: item["workspace_key"])
    if len({item["workspace_key"] for item in planned}) != len(planned):
      raise ConfigError("pi-workspace-duplicate")
    lease = {"schema_version": 1, **deepcopy(self.owner), "lease_id": lease_id, "kind": kind,
      "execution_id": execution_id, "parent_execution_id": parent_execution_id, "task_id": task_id, "attempt_id": attempt_id,
      "lock_identity": lock_identity, "slice_identity": slice_identity, "policy_digest": policy_digest, "candidate_digest": candidate_digest,
      "process_identity": None, "process_group_identity": None, "control_channel_identity": None, "state": "allocating",
      "last_sequence": 0, "stop_requested_at": None, "termination_evidence": None, "active_external_work_ids": [],
      "grant_generation": 1, "workspace_write_lease_ids": [], "allocation_id": lease_id,
      "planned_workspaces": planned, "spawn_committed": False}
    lease["allocation_journal_digest"] = allocation_digest(lease)
    with Tree(self.root, create=True) as tree, self._guard(tree):
      self._authority(lease, self.owner)
      self._register_owner(tree)
      old_records = self.records()
      for old in old_records:
        if old["execution_id"] == execution_id:
          keys = (*OWNER_KEYS, "kind", "task_id", "attempt_id", "parent_execution_id", "lock_identity", "slice_identity", "policy_digest", "candidate_digest", "planned_workspaces")
          if any(old[key] != lease[key] for key in keys):
            raise Conflict("同一执行ID不能被不同描述或控制者复用")
          return old
      if any(protected(old) and old["supervisor_activation_id"] != self.owner["supervisor_activation_id"] for old in old_records):
        raise Conflict("旧执行尚未回收，不能创建新激活的执行")
      self._save(tree, lease)
      self.fault("intent", deepcopy(lease))
      try:
        for planned in lease["planned_workspaces"]:
          if self.workspaces is None:
            raise Conflict("工作区仲裁器未配置")
          reserved = self.workspaces.reserve(planned, lease)
          self.fault("reserved", deepcopy(lease))
          lease["workspace_write_lease_ids"].append(reserved["workspace_lease_id"])
          self._save(tree, lease)
          self.fault("journal", deepcopy(lease))
      except Exception:
        # 仅分配阶段可证明未启动；清理再次失败时仍保留 allocating 及完整计划。
        evidence = self._evidence(lease, "never-started")
        if self.workspaces:
          for planned in lease["planned_workspaces"]:
            self.workspaces.release(planned, lease, evidence, missing_ok=True)
        lease.update(state="failed", termination_evidence=evidence)
        self._save(tree, lease)
        raise
    return deepcopy(lease)

  def start(self, lease_id, owner, *, spawn, validate_admission=None):
    with Tree(self.root) as tree, self._guard(tree):
      lease = self.read(lease_id)
      self._authority(lease, owner)
      if lease["state"] != "allocating":
        return lease
      if validate_admission is not None:
        validate_admission(deepcopy(lease))
      actual = []
      for planned in lease["planned_workspaces"]:
        if self.workspaces is None:
          raise Conflict("工作区仲裁器未配置")
        actual.append(self.workspaces.assert_reserved(planned, lease)["workspace_lease_id"])
      if actual != lease["workspace_write_lease_ids"]:
        raise Conflict("分配日志与实际工作区预留不一致")
      self._authority(lease, self.owner)
      lease.update(state="starting", spawn_committed=True)
      self._save(tree, lease)
      self.fault("starting", deepcopy(lease))
      try:
        process = spawn(deepcopy(lease))
        validate("process-identity", process)
        if self.processes.observe(process) != "alive":
          raise Conflict("Pi新执行握手身份未确认")
        lease.update(state="running", process_identity=process, process_group_identity=process)
        self._save(tree, lease)
        self.fault("spawned", deepcopy(lease))
        if self.workspaces:
          for planned in lease["planned_workspaces"]:
            self.workspaces.activate(planned, lease)
      except Exception:
        lease["state"] = "unknown"
        self._save(tree, lease)
        raise Conflict("Pi启动已提交但结果未确认；保留活动保护，不能自动重发") from None
    return deepcopy(lease)

  def abort_allocation(self, lease_id, owner):
    with Tree(self.root) as tree, self._guard(tree):
      lease = self.read(lease_id)
      self._authority(lease, owner)
      if not protected(lease):
        return lease
      if lease["state"] != "allocating" or lease["spawn_committed"]:
        raise Conflict("已经提交启动，不能按未启动分配撤销")
      evidence = self._evidence(lease, "never-started")
      if self.workspaces:
        for planned in lease["planned_workspaces"]:
          self.workspaces.release(planned, lease, evidence, missing_ok=True)
      lease.update(state="failed", termination_evidence=evidence)
      self._save(tree, lease)
      return lease

  def reconcile(self, lease_id):
    lease = self.read(lease_id)
    process = self.processes.observe(lease["process_identity"]) if lease["process_identity"] else "unknown"
    external = {key: self.external_status(lease, key) for key in lease["active_external_work_ids"]}
    return {"lease_id": lease_id, "state": lease["state"], "protected": protected(lease),
      "process_status": process, "external_status": external, "termination_evidence": deepcopy(lease["termination_evidence"]),
      "process_identity": deepcopy(lease["process_identity"]), "grant_generation": lease["grant_generation"],
      "task_id": lease["task_id"], "attempt_id": lease["attempt_id"]}

  def request_cancel(self, lease_id, owner):
    with Tree(self.root) as tree, self._guard(tree):
      lease = self.read(lease_id)
      self._authority(lease, owner)
      if not protected(lease) or lease["state"] == "cancel_requested":
        return lease
      if lease["process_identity"] is None:
        raise Conflict("Pi执行身份未知，不能使用普通取消入口")
      lease.update(state="cancel_requested", stop_requested_at=timestamp(self.now()), grant_generation=lease["grant_generation"] + 1)
      self._save(tree, lease)
      return lease

  def record_external(self, lease_id, owner, identifiers):
    with Tree(self.root) as tree, self._guard(tree):
      lease = self.read(lease_id)
      self._authority(lease, owner)
      if not protected(lease) or lease["state"] != "running":
        raise Conflict("Pi执行不再允许登记外部活动")
      lease["active_external_work_ids"] = sorted(set(lease["active_external_work_ids"]) | set(identifiers))
      self._save(tree, lease)

  def external_status(self, lease, identifier):
    if not identifier.startswith("execution-lease:"):
      return self.processes.external_status(identifier) if self.processes is not None else "unknown"
    try:
      child = self.read(identifier.removeprefix("execution-lease:"))
      if (child["parent_execution_id"] != lease["execution_id"] or any(child[key] != lease[key] for key in OWNER_KEYS)
          or child["active_external_work_ids"]):
        return "unknown"
      return "unknown" if protected(child) else "terminated"
    except (ConfigError, Conflict, OSError):
      return "unknown"

  def derived_terminated(self, lease):
    # 也覆盖分配落盘后、登记父引用前崩溃的子操作。
    return (not any(protected(child) and child["parent_execution_id"] == lease["execution_id"] for child in self.records())
      and all(self.external_status(lease, key) == "terminated" for key in lease["active_external_work_ids"] if key.startswith("execution-lease:")))

  def _terminated(self, lease):
    return (lease["process_identity"] is not None and self.processes.termination_status(lease["process_identity"]) == "terminated"
      and self.derived_terminated(lease)
      and all(self.external_status(lease, key) == "terminated" for key in lease["active_external_work_ids"]))

  def finish(self, lease_id, owner):
    with Tree(self.root) as tree, self._guard(tree):
      lease = self.read(lease_id)
      self._authority(lease, owner)
      if not protected(lease):
        return lease
      if not self.derived_terminated(lease):
        raise Conflict("派生执行尚未终止，父执行不能释放工作区")
      if not valid_evidence(lease) and not self._terminated(lease):
        raise Conflict("Pi尚无完整终止和外部工作清零证据")
      evidence = lease["termination_evidence"] if valid_evidence(lease) else self._evidence(lease, "terminated")
      lease.update(state="settled", termination_evidence=evidence)
      self._save(tree, lease)
      self.fault("termination-confirmed", deepcopy(lease))
      if self.workspaces:
        for planned in lease["planned_workspaces"]:
          self.workspaces.release(planned, lease, evidence)
      lease.update(state="reclaimed", termination_evidence=evidence)
      self._save(tree, lease)
      return lease

  def _plan_fields(self, lease):
    if self.processes.observe(lease["supervisor_process_identity"]) != "dead":
      raise Conflict("旧监督者仍活动或身份未知；不能接管停止权限")
    if lease["state"] == "allocating" and not lease["spawn_committed"] and lease["process_identity"] is None:
      kind, targets = "abort_allocation", []
    elif lease["process_identity"] is not None and (valid_evidence(lease) or self._terminated(lease) or self.processes.observe(lease["process_identity"]) in ("alive", "dead")):
      kind, targets = "stop_execution", [lease["process_identity"]]
    else:
      raise Conflict("启动边界已提交但目标身份未知；不能推定从未启动")
    workspaces = set(lease["workspace_write_lease_ids"])
    if self.workspaces:
      for planned in lease["planned_workspaces"]:
        record = self.workspaces.read(planned)
        if record is not None and self.workspaces._owner(record, lease):
          workspaces.add(record["workspace_lease_id"])
    return {"schema_version": 1, "instance_id": lease["instance_id"], "lease_id": lease["lease_id"],
      "old_supervisor_activation_id": lease["supervisor_activation_id"], "old_supervisor_process_identity": lease["supervisor_process_identity"],
      "old_manager_activation_id": lease["manager_activation_id"], "target_process_identities": targets,
      "external_work_ids": lease["active_external_work_ids"], "workspace_write_lease_ids": sorted(workspaces),
      "old_grant_generation": lease["grant_generation"], "plan_kind": kind, "allocation_journal_digest": lease["allocation_journal_digest"]}

  def plan_stop(self, lease_id):
    with Tree(self.root) as tree, self._guard(tree):
      lease = self.read(lease_id)
      plan = self._plan_fields(lease)
      now = self.now()
      plan.update(created_at=timestamp(now), expires_at=timestamp(now + timedelta(seconds=300)))
      plan["plan_digest"] = digest(plan)
      validate("stop-recovery-plan", plan)
      tree.write_state("activity/plans/" + lease_id + "-" + plan["plan_digest"] + ".json", json_bytes(plan))
      return plan

  def _read_document(self, tree, path, schema):
    raw = tree.read(path)
    if raw is None or raw[1] != 0o600:
      raise Conflict("恢复记录缺失或权限不安全")
    try:
      result = json.loads(raw[0])
      validate(schema, result)
    except (ValueError, TypeError, ConfigError):
      raise Conflict("恢复记录损坏，不能授予控制权限") from None
    return result

  def recover_stop(self, lease_id, plan_digest, *, request_id):
    import re
    safe_id(lease_id)
    safe_id(request_id)
    if not re.fullmatch(r"[0-9a-f]{64}", plan_digest):
      raise ConfigError("pi-recovery-plan")
    grant_path = "activity/recoveries/" + lease_id + ".json"
    with Tree(self.root) as tree, self._guard(tree):
      self._register_owner(tree)
      if self.processes.observe(self.owner["supervisor_process_identity"]) != "alive":
        raise Conflict("新监督者身份未确认")
      lease = self.read(lease_id)
      existing = tree.read(grant_path)
      if existing is None:
        plan = self._read_document(tree, "activity/plans/" + lease_id + "-" + plan_digest + ".json", "stop-recovery-plan")
        expected = self._plan_fields(lease)
        if (plan["plan_digest"] != plan_digest or plan_digest != digest({k: v for k, v in plan.items() if k != "plan_digest"})
            or any(plan[key] != value for key, value in expected.items())):
          raise Conflict("恢复计划已变化，请重新核对")
        try:
          created = datetime.fromisoformat(plan["created_at"].replace("Z", "+00:00"))
          expires = datetime.fromisoformat(plan["expires_at"].replace("Z", "+00:00"))
          valid = created <= self.now() < expires and expires - created == timedelta(seconds=300)
        except (ValueError, TypeError):
          valid = False
        if not valid:
          raise Conflict("恢复计划已过期或时间不合法")
        grant = {"schema_version": 1, "recovery_id": uuid.uuid4().hex, "plan_digest": plan_digest,
          "request_id": request_id, "requested_action": "stop", "requester_uid": os.geteuid(),
          "new_supervisor_activation_id": self.owner["supervisor_activation_id"], "target_lease_id": lease_id,
          "old_grant_generation": lease["grant_generation"], "revocation_generation": lease["grant_generation"] + 1,
          "state": "authorized", "evidence_refs": [], "source_plan": plan, "source_lease_digest": digest(lease)}
        validate("stop-recovery", grant)
        tree.write_state(grant_path, json_bytes(grant))
        self.fault("recovery-authorized", deepcopy(grant))
      else:
        grant = self._read_document(tree, grant_path, "stop-recovery")
        plan = grant["source_plan"]
        if (grant["plan_digest"] != plan_digest or grant["request_id"] != request_id or grant["target_lease_id"] != lease_id
            or grant["requester_uid"] != os.geteuid() or plan["plan_digest"] != plan_digest
            or plan_digest != digest({k: v for k, v in plan.items() if k != "plan_digest"})):
          raise Conflict("停止授权只可按原请求幂等恢复")
        if grant["new_supervisor_activation_id"] != self.owner["supervisor_activation_id"]:
          raw = tree.read("activity/supervisors/" + safe_id(grant["new_supervisor_activation_id"]) + ".json")
          try:
            previous = json.loads(raw[0]) if raw else {}
            stopped = self.processes.observe(previous["supervisor_process_identity"]) == "dead"
          except (ValueError, TypeError, KeyError):
            stopped = False
          if not stopped:
            raise Conflict("前一个恢复控制者仍活动或身份未知")
          grant["new_supervisor_activation_id"] = self.owner["supervisor_activation_id"]
          tree.write_state(grant_path, json_bytes(grant))
      if lease["grant_generation"] == grant["old_grant_generation"] and grant["state"] == "authorized":
        if digest(lease) != grant["source_lease_digest"]:
          raise Conflict("首次停止授权的执行记录已变化")
        confirmed = deepcopy(lease["termination_evidence"]) if valid_evidence(lease) else None
        lease["grant_generation"] = grant["revocation_generation"]
        if confirmed:
          confirmed["grant_generation"] = lease["grant_generation"]
          confirmed["evidence_digest"] = digest({k: v for k, v in confirmed.items() if k != "evidence_digest"})
          lease["termination_evidence"] = confirmed
        elif lease["process_identity"] is not None:
          lease.update(state="cancel_requested", stop_requested_at=timestamp(self.now()))
        self._save(tree, lease)
      elif lease["grant_generation"] != grant["revocation_generation"]:
        raise Conflict("执行存在不同的更新授权，不能重放旧停止")
      if not protected(lease):
        grant.update(state="verified", evidence_refs=[lease["termination_evidence"]["evidence_digest"]])
        tree.write_state(grant_path, json_bytes(grant))
        return lease
      # 不重新计算含新 generation 的计划；持续核对首次授权的不可变身份及目标。
      if (lease["allocation_journal_digest"] != plan["allocation_journal_digest"]
          or self.processes.observe(plan["old_supervisor_process_identity"]) != "dead"
          or ([lease["process_identity"]] if lease["process_identity"] else []) != plan["target_process_identities"]):
        raise Conflict("停止目标身份已变化")
      self.fault("recovery-revoked", deepcopy(grant))
      grant["state"] = "stopping"
      tree.write_state(grant_path, json_bytes(grant))
      if grant["evidence_refs"]:
        if len(grant["evidence_refs"]) != 1:
          raise Conflict("停止授权的终止证据关联不明确")
        reference = grant["evidence_refs"][0]
        evidence = self._read_document(tree, "activity/evidence/" + reference + ".json", "termination-evidence")
        if reference != evidence["evidence_digest"] or not valid_evidence(lease, evidence):
          raise Conflict("停止授权的终止证据身份不匹配")
      elif valid_evidence(lease):
        evidence = lease["termination_evidence"]
      elif plan["plan_kind"] == "abort_allocation":
        if lease["spawn_committed"] or lease["state"] != "allocating":
          raise Conflict("分配不再满足未启动证明")
        evidence = self._evidence(lease, "never-started")
      elif self._terminated(lease):
        evidence = self._evidence(lease, "terminated")
      else:
        for expected in plan["target_process_identities"]:
          observed = self.processes.observe(expected)
          if observed == "unknown":
            raise Conflict("目标进程身份未知，停止拒绝")
          if observed == "alive" or self.processes.termination_status(expected) == "active":
            self.processes.stop(expected, grant_generation=lease["grant_generation"])
        self.fault("recovery-stopped", deepcopy(grant))
        if not self._terminated(lease):
          grant["state"] = "unknown"
          tree.write_state(grant_path, json_bytes(grant))
          raise Conflict("停止后仍无完整终止证明，保护保持生效")
        evidence = self._evidence(lease, "terminated")
      if not self.derived_terminated(lease):
        raise Conflict("派生执行尚未终止，父执行不能释放工作区")
      # 先落盘证明，再释放任何共享租约；重放复用同一证明，不重新解释已复用的 PID。
      tree.write_immutable("activity/evidence/" + evidence["evidence_digest"] + ".json", json_bytes(evidence))
      grant["evidence_refs"] = [evidence["evidence_digest"]]
      tree.write_state(grant_path, json_bytes(grant))
      lease["termination_evidence"] = evidence
      if evidence["kind"] == "terminated":
        lease["state"] = "settled"
      self._save(tree, lease)
      if self.workspaces:
        for planned in lease["planned_workspaces"]:
          self.workspaces.release(planned, lease, evidence, missing_ok=True)
          self.fault("recovery-released", deepcopy(grant))
      lease.update(state="failed" if plan["plan_kind"] == "abort_allocation" else "reclaimed", termination_evidence=evidence)
      self._save(tree, lease)
      grant.update(state="verified", evidence_refs=[evidence["evidence_digest"]])
      tree.write_state(grant_path, json_bytes(grant))
      return lease
