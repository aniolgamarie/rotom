"""按工具编排停止、普通 setup 与恢复；阶段记录不授予部署或进程许可。"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
import re
import sys
from types import SimpleNamespace
import uuid

from . import commands, deployment, run_owners
from .sessions import KnownSession, SessionRef
from .setup_preview import setup_plan_digest, setup_deployment_digest
from .storage import Conflict, StateError, Tree, sync_directory_ancestors


_ERROR = "维护阶段或原批次不能确认；保留原记录，不自动重试"


def _digest(value):
  return hashlib.sha256(run_owners._encode(value)).hexdigest()


def _plan_digest(value):
  value = deepcopy({key: val for key, val in value.items() if key not in ("plan_id", "readiness")})
  for target in value["targets"].values():
    target.pop("observed_at_ns", None)
  return _digest(value)


def _target(value):
  if type(value) is not dict or set(value) != set(KnownSession.__dataclass_fields__):
    raise ValueError()
  return KnownSession(**{**value, "ref": SessionRef(**value["ref"])})


def _target_scope(workspace, known):
  from .dsh_sessions import scope_key
  if workspace.agent not in ("dsh", "pi", "omp"):
    raise Conflict(_ERROR)
  relative, kind = {"dsh": ("dsh-home", "dsh-home"), "pi": ("pi-home", "pi-home"),
    "omp": ("user-home", "omp-managed-home")}[workspace.agent]
  home = run_owners.native_home_key({"kind": kind, "path": str(workspace.instance / relative)})
  if (type(known) is not KnownSession or known.ref.agent != workspace.agent
      or known.ref.backend != "managed" or known.ref.native_home_ref != home
      or known.profile != workspace.profile or known.scope != scope_key(workspace.binding)
      or known.cwd is None or known.cwd_status == "unknown" or known.confirmation == "unknown"):
    raise Conflict(_ERROR)


def _setup_shape(value):
  from .run_stop_snapshot import _hex64
  if (type(value) is not dict or set(value) != {"plan_id", "summary", "target_generation", "ready"}
      or value["ready"] is not True):
    raise ValueError()
  _hex64(value["plan_id"])
  _hex64(value["target_generation"])
  summary = value["summary"]
  if (type(summary) is not dict or set(summary) != {"changes", "drift", "conflicts", "diff", "drift_targets", "conflict_targets"}
      or any(type(summary[key]) is not int or summary[key] < 0 for key in ("changes", "drift", "conflicts"))
      or summary["drift"] != 0 or summary["conflicts"] != 0):
    raise ValueError()
  for count, key in (("changes", "diff"), ("drift", "drift_targets"), ("conflicts", "conflict_targets")):
    if type(summary[key]) is not list or len(summary[key]) != summary[count]:
      raise ValueError()
    for row in summary[key]:
      fields = {"id", "target", "field"} | ({"action", "value"} if key == "diff" else set())
      if (type(row) is not dict or set(row) != fields or type(row["id"]) is not str
          or re.fullmatch(r"target-[0-9a-f]{16}", row["id"]) is None
          or type(row["target"]) is not str or not row["target"]
          or row["field"] not in (None, "<managed-field>")):
        raise ValueError()
      if key == "diff" and (row["action"] not in ("add", "remove", "update") or row["value"] != "<redacted>"):
        raise ValueError()


def _validate_manifest(workspace, batch_id, manifest):
  from . import maintenance, run_stop_snapshot
  try:
    run_stop_snapshot._shape(manifest)
    if len(run_owners._encode(manifest)) > run_stop_snapshot._MAX_BYTES:
      raise ValueError()
    if (type(manifest) is not dict or set(manifest) != {"schema_version", "kind", "batch_id", "plan"}
        or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
        or manifest["kind"] != "tool-maintenance-workflow" or manifest["batch_id"] != batch_id):
      raise ValueError()
    value = manifest["plan"]
    fields = {"schema_version", "kind", "operation", "scope", "stop_plan",
      "targets", "setup", "blockers", "plan_id", "readiness"}
    if type(value) is dict and value.get("schema_version") == 2:
      fields.add("display")
    if (type(value) is not dict or set(value) != fields
        or type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2)
        or value["kind"] != "tool-maintenance-plan" or value["operation"] != "setup"
        or value["scope"] != {**workspace.binding, "agent": workspace.agent}
        or value["plan_id"] != _plan_digest(value) or value["readiness"] != "ready" or value["blockers"] != []):
      raise ValueError()
    stop = maintenance.decode_stop_plan(maintenance.encode_stop_plan(value["stop_plan"]))
    if (stop != value["stop_plan"] or stop["scope"] != value["scope"] or stop["operation"] != "stop_only"
        or stop["schema_version"] != 2 or stop["readiness"] != "ready"
        or type(value["targets"]) is not dict or set(value["targets"]) != set(stop["selected_runs"])):
      raise ValueError()
    refs = set()
    for target in value["targets"].values():
      known = _target(target)
      _target_scope(workspace, known)
      if known.ref in refs:
        raise ValueError()
      refs.add(known.ref)
    if value["schema_version"] == 2:
      from .stopped_sessions import validate_title
      if type(value["display"]) is not dict or set(value["display"]) != set(value["targets"]):
        raise ValueError()
      for label in value["display"].values():
        if (type(label) is not dict or set(label) != {"title", "source"}
            or label["source"] not in ("user", "native-omp", "unavailable")):
          raise ValueError()
        if label["source"] == "unavailable":
          if label["title"] is not None:
            raise ValueError()
        else:
          validate_title(label["title"])
          if label["source"] == "native-omp" and workspace.agent != "omp":
            raise ValueError()
    _setup_shape(value["setup"])
  except Exception:
    raise Conflict(_ERROR) from None


def _validate_event(manifest, events, event):
  from .run_stop_snapshot import _hex64, _shape
  try:
    _shape(event)
    if (type(event) is not dict or set(event) != {"revision", "previous", "action", "run_id", "plan_id", "exit_code", "deployment"}
        or type(event["revision"]) is not int or event["revision"] != len(events) + 1
        or event["previous"] != _digest(events[-1] if events else manifest)
        or type(event["action"]) is not str):
      raise ValueError()
    action, run, plan_id, code, deployed = (event[key] for key in ("action", "run_id", "plan_id", "exit_code", "deployment"))
    cancelled = any(row["action"] == "cancel" for row in events)
    setup = [row for row in events if row["action"].startswith("setup-")]
    restores = [row for row in events if row["action"].startswith("restore-")]
    if action in ("setup-intent", "setup-result"):
      _hex64(plan_id)
      if run is not None:
        raise ValueError()
      if action == "setup-intent":
        if (cancelled or restores or setup and (setup[-1]["action"] != "setup-result" or setup[-1]["exit_code"] == 0)
            or code is not None):
          raise ValueError()
        _hex64(deployed)
      else:
        if (not setup or setup[-1]["action"] != "setup-intent" or plan_id != setup[-1]["plan_id"]
            or type(code) is not int or not 0 <= code <= 255):
          raise ValueError()
        if code == 0:
          _hex64(deployed)
          if deployed != setup[-1]["deployment"]:
            raise ValueError()
        elif deployed is not None:
          raise ValueError()
    elif action in ("restore-intent", "restore-result"):
      if (type(run) is not str or run not in manifest["plan"]["targets"] or plan_id is not None or deployed is not None
          or not setup or setup[-1]["action"] != "setup-result" or setup[-1]["exit_code"] != 0):
        raise ValueError()
      prior = [row for row in restores if row["run_id"] == run]
      if action == "restore-intent":
        if cancelled or prior or code is not None:
          raise ValueError()
      elif len(prior) != 1 or prior[0]["action"] != "restore-intent" or type(code) is not int or not 0 <= code <= 255:
        raise ValueError()
    elif action == "cancel":
      if cancelled or any(item is not None for item in (run, plan_id, code, deployed)):
        raise ValueError()
    else:
      raise ValueError()
  except Exception:
    raise Conflict(_ERROR) from None


def lookup_session(workspace, identifier):
  if workspace.agent == "dsh":
    from .dsh_sessions import lookup_metadata
    return lookup_metadata(workspace, identifier)
  from .tool_session_headers import lookup
  return lookup(workspace, identifier).known


def setup_args(workspace):
  return SimpleNamespace(local=workspace.local_path, profile=workspace.profile,
    agent=workspace.agent, command="setup")


def _require_handoff(workspace, lock):
  from .process import DependencyError
  from .sessions import session_capability
  observer = "none"
  if workspace.agent == "pi":
    from .pi_session_guard import source_identity
    observer = source_identity()
  capability = session_capability(agent=workspace.agent, backend="managed", runtime_identity=lock.identity,
    observer_identity=observer, platform=sys.platform, location="here")
  if capability.handoff != "admitted":
    raise DependencyError("目标完整运行组合尚未核验恢复；维护流程未派发。可分别使用 instances stop 和普通 setup，并在官方界面人工恢复")


def preview_setup(workspace):
  selected, lock, candidate = commands.prepared(setup_args(workspace))
  if selected.binding != workspace.binding or selected.agent != workspace.agent or selected.profile != workspace.profile:
    raise Conflict(_ERROR)
  _require_handoff(selected, lock)
  plan = commands.current_plan(selected, lock, candidate)
  return {"plan_id": setup_plan_digest(selected, lock, candidate, plan),
    "summary": plan.public(), "target_generation": candidate.generation,
    "ready": not (plan.conflicts or plan.drift)}


def plan(workspace, *, selected_runs, sessions, labels=None):
  """只读计划；每个恢复目标必须有明确 ID，不猜测当前或最新会话。"""
  from .dsh_stop import capture_stop
  observed, records, _ = capture_stop(workspace, selected_runs=selected_runs)
  if type(sessions) is not dict or set(sessions) - set(selected_runs):
    raise ValueError("session 映射必须属于所选运行")
  from .stopped_sessions import validate_title
  labels = {} if labels is None else labels
  if type(labels) is not dict or set(labels) - set(selected_runs):
    raise ValueError("label 映射必须属于所选运行")
  for title in labels.values():
    validate_title(title)
  targets, blockers = {}, list(observed["plan"]["blockers"])
  display = {}
  auxiliary = {}
  if workspace.agent == "pi":
    from .pi_session_observation import from_records
    auxiliary = {item.run_id: item for item in from_records(workspace, records)}
  for run in observed["plan"]["selected_runs"]:
    identifier = sessions.get(run)
    historical = None
    if identifier is None:
      historical = records[run].get("session_observation")
      identifier = historical["session"]["native_ref"] if historical and historical["confirmation"] != "unknown" else None
      if identifier is None and run in auxiliary:
        identifier = auxiliary[run].ref.native_ref
    if identifier is None:
      blockers.append("session-required:" + run)
      continue
    target = lookup_session(workspace, identifier)
    _target_scope(workspace, target)
    if target.ref.native_ref != identifier or historical is not None and asdict(target.ref) != historical["session"]:
      raise Conflict(_ERROR)
    targets[run] = asdict(target)
    title, source = labels.get(run), "user" if run in labels else "unavailable"
    if title is None and workspace.agent == "omp":
      from .tool_session_headers import lookup
      from .sessions import SessionError
      try:
        header = lookup(workspace, identifier)
        if header.known.ref == target.ref and header.known.cwd == target.cwd:
          title = header.title
          source = "native-omp" if title is not None else "unavailable"
      except SessionError:
        # 标题只是显示提示；已核验的恢复身份不因标题缺失变成伪造信息。
        pass
    display[run] = {"title": title, "source": source}
  # 两个运行不能在恢复时同时追加同一会话。
  if len({target["ref"]["native_ref"] for target in targets.values()}) != len(targets):
    blockers.append("duplicate-restore-session")
  setup = preview_setup(workspace)
  if not setup["ready"]:
    blockers.append("setup-conflict-or-drift")
  value = {"schema_version": 2, "kind": "tool-maintenance-plan", "operation": "setup",
    "scope": {**workspace.binding, "agent": workspace.agent}, "stop_plan": observed["plan"],
    "targets": targets, "display": display, "setup": setup, "blockers": sorted(blockers)}
  return {**value, "plan_id": _plan_digest(value), "readiness": "blocked" if blockers else "ready"}


class Store:
  """单批次追加事实；短锁内不交互、不取得实例锁、不启动任何动作。"""

  def __init__(self, workspace, batch_id):
    run_owners._run_id(batch_id)
    self.workspace, self.batch_id = workspace, batch_id
    self.registry = run_owners.Registry(workspace.state_root / "maintenance-workflows" / batch_id, workspace.binding)

  def _read(self, tree):
    if tree is None:
      return None
    from . import run_stop_snapshot
    names = set()
    with os.scandir(tree.fd) as entries:
      for entry in entries:
        names.add(entry.name)
        if len(names) > 4097:
          raise Conflict(_ERROR)
    if "manifest.json" not in names:
      raise Conflict(_ERROR)
    def read(name):
      raw = tree.read(name, max_bytes=run_stop_snapshot._MAX_BYTES)
      if raw is None or raw[1] != 0o600:
        raise Conflict(_ERROR)
      try:
        value = json.loads(raw[0], object_pairs_hook=run_owners._pairs,
          parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
        run_stop_snapshot._shape(value)
        return value
      except (ValueError, TypeError, RecursionError, UnicodeError):
        raise Conflict(_ERROR) from None
    manifest = read("manifest.json")
    _validate_manifest(self.workspace, self.batch_id, manifest)
    events, previous = [], _digest(manifest)
    for index in range(len(names) - 1):
      name = f"event-{index + 1:04d}.json"
      if name not in names:
        raise Conflict(_ERROR)
      event = read(name)
      _validate_event(manifest, events, event)
      events.append(event)
      previous = _digest(event)
    self.registry._verify_root(tree)
    return {"manifest": manifest, "events": events, "revision": len(events), "digest": previous}

  def read(self):
    with self.registry._locked(nonblocking=True) as tree:
      return self._read(tree)

  def begin(self, value):
    try:
      manifest = {"schema_version": 1, "kind": "tool-maintenance-workflow", "batch_id": self.batch_id, "plan": deepcopy(value)}
      _validate_manifest(self.workspace, self.batch_id, manifest)
    except Exception:
      raise Conflict(_ERROR) from None
    with self.registry._locked(create=True, nonblocking=True) as tree:
      if os.listdir(tree.fd):
        raise Conflict(_ERROR)
      tree.write_new("manifest.json", run_owners._encode(manifest))
      sync_directory_ancestors(tree.root)
      return self._read(tree)

  def _append(self, tree, current, action, *, run_id=None, plan_id=None, exit_code=None, deployment=None):
    if current is None or current["revision"] >= 4096:
      raise Conflict(_ERROR)
    event = {"revision": current["revision"] + 1, "previous": current["digest"], "action": action,
      "run_id": run_id, "plan_id": plan_id, "exit_code": exit_code, "deployment": deployment}
    # 写入前完成字段及状态机校验；错误请求不能污染不可覆盖的追加事实。
    _validate_event(current["manifest"], current["events"], event)
    tree.write_new(f"event-{event['revision']:04d}.json", run_owners._encode(event))
    sync_directory_ancestors(tree.root)
    return self._read(tree)

  def append(self, expected, action, **fields):
    with self.registry._locked(nonblocking=True) as tree:
      current = self._read(tree)
      if current != expected:
        raise Conflict(_ERROR)
      return self._append(tree, current, action, **fields)

  def _complete(self, expected, action, *, run_id=None, exit_code, deployment=None):
    with self.registry._locked(nonblocking=True) as tree:
      current = self._read(tree)
      try:
        if (current is None or type(expected) is not dict or set(expected) != set(current)
            or expected["manifest"] != current["manifest"] or type(expected["events"]) is not list
            or not expected["events"] or expected["revision"] != len(expected["events"])
            or type(expected["revision"]) is not int or expected["revision"] > current["revision"]
            or expected["events"] != current["events"][:expected["revision"]]
            or expected["digest"] != _digest(expected["events"][-1])):
          raise ValueError()
        intent = expected["events"][-1]
        if intent["action"] != action.replace("result", "intent") or intent["run_id"] != run_id:
          raise ValueError()
        tail = current["events"][expected["revision"]:]
        if any(row["action"].startswith("setup-") if run_id is None else row["run_id"] == run_id for row in tail):
          raise ValueError()
      except (KeyError, TypeError, ValueError):
        raise Conflict(_ERROR) from None
      return self._append(tree, current, action, run_id=run_id, exit_code=exit_code,
        plan_id=intent["plan_id"], deployment=deployment)

  def complete_restore(self, expected_intent, run_id, exit_code):
    """其它目标和取消事实可先追加；只为原本确切意图补记一次结果。"""
    return self._complete(expected_intent, "restore-result", run_id=run_id, exit_code=exit_code)

  def complete_setup(self, expected_intent, exit_code, *, deployment=None):
    return self._complete(expected_intent, "setup-result", exit_code=exit_code, deployment=deployment)


def stop(workspace, *, expected_plan, approve, wait_seconds=30):
  from .dsh_stop_client import execute_stop
  fresh = plan(workspace, selected_runs=expected_plan["stop_plan"]["selected_runs"],
    sessions={run: target["ref"]["native_ref"] for run, target in expected_plan["targets"].items()},
    labels={run: label["title"] for run, label in expected_plan.get("display", {}).items() if label["source"] == "user"})
  # 查询时刻不参与批准摘要；session 内容/目录与精确停止计划必须仍相符。
  for run, target in fresh["targets"].items():
    target["observed_at_ns"] = expected_plan["targets"][run]["observed_at_ns"]
  fresh["plan_id"] = _plan_digest(fresh)
  if fresh != expected_plan or fresh["readiness"] != "ready" or approve(deepcopy(fresh)) is not True:
    raise Conflict(_ERROR)
  batch_id = uuid.uuid4().hex
  try:
    Store(workspace, batch_id).begin(fresh)
    execute_stop(workspace, expected_plan=fresh["stop_plan"], batch_id=batch_id,
      approve=lambda value: value["plan_id"] == fresh["stop_plan"]["plan_id"], wait_seconds=wait_seconds)
  except Exception:
    # 写后失败或快照前捕获失败均保留同一批次，不能重发停止或推造接受事实。
    pass
  try:
    return status(workspace, batch_id)
  except Exception:
    return {"batch_id": batch_id, "scope": {**workspace.binding, "agent": workspace.agent},
      "status": "unknown", "stop_status": "unknown", "continue_status": "not_sent"}


def status(workspace, batch_id):
  from .dsh_stop_client import status_stop
  value = Store(workspace, batch_id).read()
  if value is None:
    raise Conflict(_ERROR)
  try:
    stopped = status_stop(workspace, batch_id=batch_id)
    stop_status = stopped["status"]
  except Conflict:
    stopped, stop_status = None, "unknown"
  events = value["events"]
  setup = [event for event in events if event["action"].startswith("setup-")]
  restored = {run: [event for event in events if event["run_id"] == run]
    for run in value["manifest"]["plan"]["targets"]}
  cancelled = any(event["action"] == "cancel" for event in events)
  result = {"batch_id": batch_id, "scope": {**workspace.binding, "agent": workspace.agent},
    "revision": value["revision"], "stop_status": stop_status, "stop": stopped, "cancelled": cancelled,
    "setup": setup[-1] if setup else None, "restores": {run: rows[-1] if rows else None for run, rows in restored.items()},
    "targets": deepcopy(value["manifest"]["plan"]["targets"]), "continue_status": "not_sent",
    "display": deepcopy(value["manifest"]["plan"].get("display", {})),
    "load_confirmation": "unknown", "resource_check": "required-by-setup"}
  result["status"] = ("cancelled" if cancelled else "stopped" if stop_status == "stopped" and not setup
    else "unknown" if stop_status == "unknown" else "pending")
  if setup and not cancelled:
    result["status"] = "updated" if setup[-1]["action"] == "setup-result" and setup[-1]["exit_code"] == 0 else "setup-failed" if setup[-1]["action"] == "setup-result" else "setup-unknown"
  result["current_deployment_match"] = None
  if setup and setup[-1]["action"] == "setup-result" and setup[-1]["exit_code"] == 0:
    try:
      with Tree(workspace.state_root) as state:
        current = deployment.read_state(state)["current"]
        result["current_deployment_match"] = (current is not None and state.read("pending.json") is None
          and setup_deployment_digest(current) == setup[-1]["deployment"])
    except (StateError, OSError):
      pass
  from .restore_locations import status_for
  locations = {run: status_for(workspace, batch_id, run) for run in result["targets"]}
  if any(item is not None for item in locations.values()):
    result["locations"] = locations
  return result


def execute(workspace, batch_id, *, approve, progress, preview):
  """普通 setup 自己重新检查和批准；此记录不绕过任何原有物理/共享资源保护。"""
  store = Store(workspace, batch_id)
  initial = store.read()
  observed = status(workspace, batch_id)
  if observed["cancelled"] or observed["stop_status"] != "stopped" or observed["status"] in ("updated", "setup-unknown"):
    raise Conflict(_ERROR)
  dispatched = None
  def review(selected, lock, candidate, candidate_plan):
    nonlocal dispatched
    if selected.binding != workspace.binding or selected.agent != workspace.agent or selected.profile != workspace.profile:
      raise Conflict(_ERROR)
    _require_handoff(selected, lock)
    digest = setup_plan_digest(selected, lock, candidate, candidate_plan)
    if approve({"batch_id": batch_id, "plan_id": digest, "summary": candidate_plan.public()}) is not True:
      raise Conflict(_ERROR)
    dispatched = store.append(initial, "setup-intent", plan_id=digest,
      deployment=setup_deployment_digest(candidate_plan.current))
  outcome = commands._setup_operation(setup_args(workspace), progress=progress, preview=preview, approve=review)
  if dispatched is None:
    # 冲突/漂移在原 setup 批准前返回，没有执行意图或副作用。
    return outcome.code, status(workspace, batch_id)
  # 普通 setup 的精确 apply 返回事实只绑定原批准目标，不能借后续部署冒充结果。
  deployed = dispatched["events"][-1]["deployment"] if outcome.code == 0 else None
  store.complete_setup(dispatched, outcome.code, deployment=deployed)
  return outcome.code, status(workspace, batch_id)


def reserve_restore(workspace, batch_id, *, run_id):
  """为精确目标先保存普通恢复意图；位置创建不能绕过原防重门禁。"""
  store = Store(workspace, batch_id)
  value = store.read()
  observed = status(workspace, batch_id)
  if (observed["cancelled"] or observed["status"] != "updated" or run_id not in observed["targets"]
      or observed["restores"][run_id] is not None):
    raise Conflict(_ERROR)
  expected = _target(observed["targets"][run_id])
  target = lookup_session(workspace, expected.ref.native_ref)
  _target_scope(workspace, target)
  if target.ref != expected.ref or target.cwd != expected.cwd:
    raise Conflict(_ERROR)
  with Tree(workspace.state_root) as state:
    current = deployment.read_state(state)["current"]
    if (current is None or state.read("pending.json") is not None
        or setup_deployment_digest(current) != observed["setup"]["deployment"]):
      raise Conflict(_ERROR)
  intent = store.append(value, "restore-intent", run_id=run_id)
  return intent, asdict(target), observed["setup"]["deployment"]


def _finish_restore(store, intent, run_id, target, deployment_digest, launch):
  code = launch(target, expected_deployment=deployment_digest)
  if type(code) is not int or not 0 <= code <= 255:
    raise Conflict(_ERROR)
  store.complete_restore(intent, run_id, code)
  return code, status(store.workspace, store.batch_id)


def restore(workspace, batch_id, *, run_id, launch):
  """一个明确目标交给当前终端；意图持久化后不自动重放。"""
  intent, target, deployed = reserve_restore(workspace, batch_id, run_id=run_id)
  return _finish_restore(Store(workspace, batch_id), intent, run_id, _target(target), deployed, launch)


def restore_reserved(workspace, request, *, launch):
  """仅供已一次消费的位置交接；重核原意图、目标、取消与当前部署。"""
  batch_id, run_id = request["batch_id"], request["run_id"]
  if request["scope"] != {**workspace.binding, "agent": workspace.agent}:
    raise Conflict(_ERROR)
  store = Store(workspace, batch_id)
  current = store.read()
  revision = request["workflow_revision"]
  if current is None or type(revision) is not int or not 1 <= revision <= current["revision"]:
    raise Conflict(_ERROR)
  events = current["events"][:revision]
  last = events[-1]
  if (last["action"] != "restore-intent" or last["run_id"] != run_id
      or _digest(last) != request["workflow_digest"]
      or any(row["action"] == "cancel" for row in current["events"])
      or any(row["run_id"] == run_id for row in current["events"][revision:])):
    raise Conflict(_ERROR)
  expected = current["manifest"]["plan"]["targets"][run_id]
  if expected["ref"] != request["session_ref"] or expected["cwd"] != request["cwd"]:
    raise Conflict(_ERROR)
  target = lookup_session(workspace, request["session_ref"]["native_ref"])
  _target_scope(workspace, target)
  if target.ref != _target(expected).ref or target.cwd != expected["cwd"]:
    raise Conflict(_ERROR)
  observed = status(workspace, batch_id)
  if (observed["cancelled"] or observed["restores"][run_id] != last
      or observed["setup"] is None or observed["setup"]["action"] != "setup-result"
      or observed["setup"]["exit_code"] != 0 or observed["setup"]["deployment"] != request["deployment_digest"]
      or observed["current_deployment_match"] is not True):
    raise Conflict(_ERROR)
  intent = {"manifest": current["manifest"], "events": events, "revision": revision, "digest": _digest(last)}
  return _finish_restore(store, intent, run_id, target, request["deployment_digest"], launch)


def cancel(workspace, batch_id):
  from .dsh_stop_client import status_stop
  from .dsh_stop_completion import close_stop
  store = Store(workspace, batch_id)
  value = store.read()
  if value is None:
    raise Conflict(_ERROR)
  if not any(event["action"] == "cancel" for event in value["events"]):
    store.append(value, "cancel")
  try:
    current = status_stop(workspace, batch_id=batch_id)
    if current["status"] not in ("stopped", "cancelled"):
      close_stop(workspace, batch_id=batch_id, plan_id=current["plan_id"], reason=current.get("close_reason") or "cancelled")
  except (Conflict, StateError, OSError):
    # 取消仅禁止新阶段；已投递停止及其 fence 仍按原协议保留，不能伪报释放。
    pass
  return status(workspace, batch_id)
