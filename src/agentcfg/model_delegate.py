"""委托 V2 的封闭协议与证据核验；不信任宿主退出码或旧收据。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from .activity import digest
from .schema import ConfigError
from .storage import Conflict

SCHEMAS = Path(__file__).resolve().parents[2] / "shared/skills/model-delegate/schemas"
STATES = {"starting", "running", "start_unknown", "completed", "failed", "canceled", "timeout", "unknown"}
TERMINAL = {"completed", "failed", "canceled", "timeout"}
IDENTITY_FIELDS = ("run_id", "attempt_id", "backend", "mode", "preset", "requested_model", "cwd", "worktree_identity",
  "execution_boundary", "execution_policy_digest", "execution_mode", "policy_digest", "runtime_identity", "parent_task_id", "lease_id", "context_artifact_id",
  "workspace_write_lease_ids", "workspace_identity_digest", "grant_generation", "request_digest", "instance_id", "owner_nonce",
  "timeout_seconds", "continuation_of", "feedback_required")


def validate_record(kind, value, *, schemas=SCHEMAS):
  if kind not in {"request-v2", "receipt-v2", "context-v2", "feedback-v2", "event-v2"}:
    raise ConfigError("delegate-schema-version")
  try:
    schema = json.loads((schemas / (kind + ".json")).read_text())
    if not Draft202012Validator(schema).is_valid(value):
      raise ValueError()
    if kind in {"request-v2", "receipt-v2"}:
      from .pi_delegate_policy import boundary
      if value["execution_boundary"] != boundary(value["backend"]): raise ValueError()
      write = value["mode"] == "implement"
      if write != (value["execution_mode"] == "delegate-write") or write != bool(value["workspace_write_lease_ids"]):
        raise ValueError()
      if write and value["backend"] != "codex":
        raise ValueError()
      if not Path(value["cwd"]).is_absolute() or ".." in Path(value["cwd"]).parts:
        raise ValueError()
  except (ValueError, TypeError, KeyError):
    raise ConfigError("delegate-record-invalid") from None
  return value


def verify_receipt(request, receipt, proof, *, schemas=SCHEMAS):
  validate_record("request-v2", request, schemas=schemas)
  validate_record("receipt-v2", receipt, schemas=schemas)
  if any(receipt[key] != request[key] for key in IDENTITY_FIELDS):
    raise Conflict("DELEGATE_RECEIPT_IDENTITY")
  if (proof.get("execution_policy_verified") is not True or proof.get("execution_boundary") != request["execution_boundary"]
      or proof.get("execution_policy_digest") != request["execution_policy_digest"]):
    raise Conflict("DELEGATE_EXECUTION_POLICY_UNVERIFIED")
  if receipt["observed_model"] is not None and receipt["observed_model"] != request["requested_model"]:
    raise Conflict("DELEGATE_MODEL_MISMATCH")
  if (receipt["terminal_status"] != "completed" or proof.get("lease_id") != request["lease_id"]
      or proof.get("exit_code") != 0 or any(proof.get(key) is not True for key in
        ("termination_verified", "resources_reclaimed", "final_nonempty", "sequence_complete", "host_completed"))
      or any(receipt[key] is not True for key in ("process_terminated", "resources_reclaimed", "event_sequence_complete"))):
    raise Conflict("DELEGATE_EXECUTION_UNVERIFIED")
  if (not receipt["final_artifact_id"] or not receipt["final_artifact_digest"]
      or receipt["final_artifact_digest"] != proof.get("final_artifact_digest")
      or receipt["candidate_digest"] != proof.get("candidate_digest")):
    raise Conflict("DELEGATE_ARTIFACT_MISMATCH")
  if request["execution_mode"] == "delegate-readonly" and receipt["candidate_digest"] != request["candidate_digest"]:
    raise Conflict("DELEGATE_CANDIDATE_STALE")
  if request["feedback_required"] and (not receipt["feedback_dispositions"] or any(
      item["status"] not in {"verified", "provisional"} for item in receipt["feedback_dispositions"])):
    raise Conflict("DELEGATE_FEEDBACK_MISSING")
  return {"verification": "verified-execution", "run_id": receipt["run_id"], "receipt_digest": digest(receipt),
    "task_acceptance": "unverified"}


def cursor(run_id, sequence):
  if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,200}", run_id) or type(sequence) is not int or sequence < 0:
    raise ConfigError("delegate-cursor")
  return run_id + ":" + str(sequence)


def parse_cursor(run_id, value, last_sequence):
  if value is None:
    return 0
  prefix, separator, suffix = value.rpartition(":")
  if not separator or prefix != run_id or not re.fullmatch(r"0|[1-9][0-9]*", suffix) or int(suffix) > last_sequence:
    raise ConfigError("delegate-cursor")
  return int(suffix)


def control_envelope(value):
  allowed = {"schema_version", "run_id", "state", "lease_id", "verification", "artifact_ref", "next_cursor", "has_more", "events",
    "accepted", "termination_confirmed", "timed_out", "error_code", "batch_id", "result_refs", "dispatch_ids", "truncated", "artifact_id", "sha256", "offset", "next_offset", "total_bytes", "content", "capabilities"}
  if not isinstance(value, dict) or set(value) - allowed:
    raise ConfigError("delegate-control-field")
  states = STATES | ({"partial"} if "batch_id" in value else set())
  if "state" in value and value["state"] not in states:
    raise ConfigError("delegate-control-state")
  result = deepcopy(value)
  encode = lambda row: (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
  if len(encode(result)) > 4096:
    for key in ("events", "result_refs", "dispatch_ids", "artifact_ref"):
      if key in result:
        result.pop(key)
        result["truncated"] = True
      if len(encode(result)) <= 4096:
        break
  if len(encode(result)) > 4096:
    raise ConfigError("delegate-control-too-large")
  return encode(result)


class DelegationRuns:
  """每实例持久 run 记录；没有调度队列，启动权由外层 manager/supervisor 授予。"""

  def __init__(self, root, *, schemas=SCHEMAS, now=None, pause=None):
    import time
    self.root, self.schemas = Path(root), schemas
    self.now, self.pause = now or time.monotonic, pause or time.sleep

  def _key(self, run_id):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,200}", run_id) or run_id in {".", ".."}:
      raise ConfigError("delegate-run-id")
    return run_id + ".json"

  def _read(self, tree, run_id):
    raw = tree.read(self._key(run_id))
    if raw is None:
      raise Conflict("DELEGATE_RUN_NOT_FOUND")
    try:
      value = json.loads(raw[0])
      if (set(value) != {"schema_version", "request", "state", "cancel_requested", "events", "receipt", "verification"}
          or value["schema_version"] != 2 or value["state"] not in STATES or raw[1] != 0o600):
        raise ValueError()
      validate_record("request-v2", value["request"], schemas=self.schemas)
      if value["request"]["run_id"] != run_id:
        raise ValueError()
      for index, event in enumerate(value["events"], 1):
        validate_record("event-v2", event, schemas=self.schemas)
        if event["run_id"] != run_id or event["seq"] != index:
          raise ValueError()
      if value["receipt"] is not None:
        validate_record("receipt-v2", value["receipt"], schemas=self.schemas)
    except (ValueError, KeyError, TypeError, ConfigError):
      raise Conflict("DELEGATE_STATE_INVALID") from None
    return value

  def _transaction(self, operation):
    from .storage import Tree, instance_lock
    with Tree(self.root, create=True) as tree, instance_lock(tree):
      return operation(tree)

  def _save(self, tree, value):
    from .deployment import json_bytes
    tree.write_state(self._key(value["request"]["run_id"]), json_bytes(value))

  def read(self, run_id):
    return self._transaction(lambda tree: self._read(tree, run_id))

  def status(self, run_id):
    row = self.read(run_id)
    return {"schema_version": 2, "run_id": run_id, "lease_id": row["request"]["lease_id"], "state": row["state"],
      "verification": row["verification"], "next_cursor": cursor(run_id, len(row["events"]))}

  def start(self, request, starter):
    validate_record("request-v2", request, schemas=self.schemas)
    run_id = request["run_id"]
    def prepare(tree):
      if tree.read(self._key(run_id)) is not None:
        existing = self._read(tree, run_id)
        if existing["request"] != request:
          raise Conflict("DELEGATE_RUN_CONFLICT")
        return False
      self._save(tree, {"schema_version": 2, "request": deepcopy(request), "state": "starting", "cancel_requested": False,
        "events": [], "receipt": None, "verification": "unverified"})
      return True
    if not self._transaction(prepare):
      return self.status(run_id)
    # 不跨 IPC 持锁。确认丢失后保留 start_unknown；同 run 再调用也不重新启动。
    try:
      reply = starter(deepcopy(request))
      ready = isinstance(reply, dict) and reply.get("ready") is True and all(reply.get(key) == request[key] for key in ("run_id", "lease_id", "request_digest"))
    except Exception:
      ready = False
    def acknowledge(tree):
      row = self._read(tree, run_id)
      if row["state"] == "starting":
        row["state"] = "running" if ready else "start_unknown"
        self._save(tree, row)
    self._transaction(acknowledge)
    return self.status(run_id)

  def event(self, run_id, event):
    validate_record("event-v2", event, schemas=self.schemas)
    def append(tree):
      row = self._read(tree, run_id)
      if event["run_id"] != run_id:
        raise Conflict("DELEGATE_EVENT_IDENTITY")
      index = event["seq"] - 1
      if index < len(row["events"]):
        if row["events"][index] != event:
          raise Conflict("DELEGATE_EVENT_CONFLICT")
        return
      if row["state"] in TERMINAL or index != len(row["events"]):
        raise Conflict("DELEGATE_EVENT_GAP")
      row["events"].append(deepcopy(event)); self._save(tree, row)
    self._transaction(append)

  def poll(self, run_id, after=None):
    row = self.read(run_id)
    start = parse_cursor(run_id, after, len(row["events"]))
    result = {"schema_version": 2, "run_id": run_id, "state": row["state"], "events": [], "next_cursor": cursor(run_id, start), "has_more": False}
    for event in row["events"][start:]:
      candidate = {**result, "events": result["events"] + [event], "next_cursor": cursor(run_id, event["seq"])}
      if len((json.dumps(candidate, ensure_ascii=False) + "\n").encode()) > 3800:
        break
      result = candidate
    result["has_more"] = parse_cursor(run_id, result["next_cursor"], len(row["events"])) < len(row["events"])
    return result

  def cancel(self, run_id, stopper):
    def intent(tree):
      row = self._read(tree, run_id)
      row["cancel_requested"] = True; self._save(tree, row)
      return row
    row = self._transaction(intent)
    if row["state"] in TERMINAL:
      return {"run_id": run_id, "accepted": True, "termination_confirmed": bool(row["receipt"] and row["receipt"]["resources_reclaimed"])}
    stopper(deepcopy(row["request"]))
    return {"run_id": run_id, "accepted": True, "termination_confirmed": False}

  def wait(self, run_id, seconds, *, refresh=None):
    if type(seconds) not in (int, float) or not 0 <= seconds <= 60:
      raise ConfigError("delegate-wait-seconds")
    deadline = self.now() + seconds
    while True:
      if refresh is not None:
        refresh(run_id)
      result = self.status(run_id)
      if result["state"] in TERMINAL:
        return {**result, "timed_out": False}
      if self.now() >= deadline:
        return {**result, "timed_out": True}
      self.pause(min(0.1, deadline - self.now()))

  def finish(self, run_id, receipt, proof):
    def commit(tree):
      row = self._read(tree, run_id)
      validate_record("receipt-v2", receipt, schemas=self.schemas)
      if any(receipt[key] != row["request"][key] for key in IDENTITY_FIELDS):
        raise Conflict("DELEGATE_RECEIPT_IDENTITY")
      if row["receipt"] is not None:
        if row["receipt"] != receipt:
          raise Conflict("DELEGATE_TERMINAL_CONFLICT")
        return
      if proof.get("lease_id") != row["request"]["lease_id"] or proof.get("termination_verified") is not True or proof.get("resources_reclaimed") is not True:
        raise Conflict("DELEGATE_TERMINATION_UNKNOWN")
      verified = "unverified"
      if receipt["terminal_status"] == "completed":
        verified = verify_receipt(row["request"], receipt, proof, schemas=self.schemas)["verification"]
      row["receipt"], row["state"], row["verification"] = deepcopy(receipt), receipt["terminal_status"], verified
      self._save(tree, row)
    self._transaction(commit)
    return self.status(run_id)

  def check_resume(self, run_id, following, proof, *, user_authorized):
    row = self.read(run_id); old = row["request"]
    validate_record("request-v2", following, schemas=self.schemas)
    if (user_authorized is not True or proof.get("lease_id") != old["lease_id"]
        or proof.get("termination_verified") is not True or proof.get("resources_reclaimed") is not True):
      raise Conflict("DELEGATE_RESUME_NOT_AUTHORIZED")
    if (following["continuation_of"] != run_id or following["run_id"] == run_id or following["attempt_id"] == old["attempt_id"]
        or following["lease_id"] == old["lease_id"] or any(following[key] != old[key] for key in
          ("backend", "requested_model", "cwd", "worktree_identity", "instance_id", "policy_digest", "runtime_identity", "mode", "execution_mode", "execution_boundary", "execution_policy_digest"))):
      raise Conflict("DELEGATE_RESUME_IDENTITY")


def write_workspace(workspaces, *, backend, mode, configured_mode, allow_workspace_write, worktree_root, cwd, user_authorized):
  """只核验写入范围；共享租约由 ExecutionStore.allocate 在持久意图之后预留。"""
  if mode != "implement":
    if allow_workspace_write or worktree_root is not None:
      raise ConfigError("delegate-readonly-write-options")
    return []
  if (backend != "codex" or configured_mode != "explicit-write" or allow_workspace_write is not True
      or user_authorized is not True or not worktree_root):
    raise ConfigError("delegate-explicit-write-required")
  root = Path(worktree_root).resolve(strict=True)
  target = Path(cwd).resolve(strict=True)
  if not target.is_relative_to(root) or not (root / ".git").is_file() or (root / ".git").is_symlink():
    raise Conflict("DELEGATE_LINKED_WORKTREE_REQUIRED")
  identity = workspaces.identify(root)
  if Path(identity["worktree_path"]) != root or Path(identity["git_dir_path"]) == root / ".git":
    raise Conflict("DELEGATE_LINKED_WORKTREE_REQUIRED")
  return [identity]


def selected_route(manifest, backend, model):
  """只使用当前所选实例路线；不读取项目/global 配置或环境代理默认值。"""
  if (not isinstance(model, dict) or set(model) != {"provider_id", "model_id"}
      or any(not isinstance(value, str) or not value or "\0" in value for value in model.values())):
    raise ConfigError("delegate-model-binding")
  options = manifest["options"].get("model_delegate", {})
  if not options.get("enabled") or backend not in options.get("backends", []):
    raise ConfigError("delegate-backend-unbound")
  if backend == "codex":
    bound = options.get("codex", {})
    if model != {"provider_id": "openai", "model_id": bound.get("model")}:
      raise ConfigError("delegate-model-unbound")
  elif backend == "pi":
    bound = options.get("pi", {})
    allowed = [manifest["model_bindings"].get(role) for role in bound.get("model_roles", [])]
    selected = {"provider": model["provider_id"], "model": model["model_id"]}
    if selected not in allowed or selected not in manifest["allowed_models"]:
      raise ConfigError("delegate-model-unbound")
  else:
    raise ConfigError("delegate-backend-unbound")
  route_id = bound.get("network_route")
  route = manifest["options"].get("network", {}).get("routes", {}).get(route_id)
  if not route or route["mode"] not in {"direct", "proxy"}:
    raise ConfigError("delegate-route-unbound")
  logical_provider = manifest.get("provider_bindings", {}).get(model["provider_id"], {}).get("logical_id", model["provider_id"].removeprefix("agentcfg-"))
  if backend == "pi" and logical_provider not in route["provider_ids"]:
    raise ConfigError("delegate-route-provider")
  return route_id, deepcopy(route)


def saved_termination(state_root, request):
  """只核验持久终止证据；不猜 PID、不发信号，也不恢复旧 owner 权限。"""
  from .activity import ExecutionStore, OWNER_KEYS, protected, valid_evidence
  from .storage import Tree
  lease_id = request["lease_id"]
  if not re.fullmatch(r"[a-f0-9]{32}", lease_id):
    raise Conflict("DELEGATE_LEASE_IDENTITY")
  with Tree(Path(state_root)) as tree:
    raw = tree.read("activity/leases/" + lease_id + ".json")
  if raw is None:
    raise Conflict("DELEGATE_TERMINATION_UNKNOWN")
  value = json.loads(raw[0])
  store = ExecutionStore(Path(state_root), {key: value[key] for key in OWNER_KEYS}, None)
  lease = store.read(lease_id)
  if (lease["execution_id"] != request["run_id"] or lease["attempt_id"] != request["attempt_id"]
      or lease["instance_id"] != request["instance_id"] or lease["owner_nonce"] != request["owner_nonce"]
      or lease["policy_digest"] != request["policy_digest"]):
    raise Conflict("DELEGATE_LEASE_IDENTITY")
  derived = store.derived_terminated(lease) and all(store.external_status(lease, key) == "terminated" for key in lease["active_external_work_ids"])
  return {"lease_id": lease_id, "termination_verified": valid_evidence(lease) and derived, "resources_reclaimed": not protected(lease) and derived,
    "process_identity": lease["process_identity"], "termination_evidence": lease["termination_evidence"]}


def artifact_chunk(root, receipt, *, offset=0, limit=2048):
  """结果数据使用单独有界读取；只能读取本次已核验最终文件，不能提供任意路径。"""
  from .storage import Tree
  from .deployment import json_bytes
  validate_record("receipt-v2", receipt)
  if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 2048:
    raise ConfigError("delegate-artifact-range")
  with Tree(Path(root) / "reports" / receipt["run_id"]) as tree:
    raw = tree.read("final.md", max_bytes=16 * 1024 * 1024)
  if raw is None or hashlib.sha256(raw[0]).hexdigest() != receipt["final_artifact_digest"] or offset > len(raw[0]):
    raise Conflict("DELEGATE_ARTIFACT_MISMATCH")
  data = raw[0]; end = min(len(data), offset + limit)
  while end >= offset:
    try:
      content = data[offset:end].decode("utf8")
    except UnicodeError:
      end -= 1; continue
    result = {"schema_version": 2, "run_id": receipt["run_id"], "artifact_id": receipt["final_artifact_id"],
      "sha256": receipt["final_artifact_digest"], "offset": offset, "next_offset": end if end < len(data) else None,
      "total_bytes": len(data), "content": content}
    if len(json_bytes(result)) <= 4096 and (end > offset or offset == len(data)):
      return result
    end -= 1
  raise ConfigError("delegate-artifact-utf8-boundary")
