"""实例 supervisor 的单次委托控制；所有 backend 共用执行与工作区准入。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from .activity import digest, protected, valid_evidence
from .deployment import json_bytes
from .model_delegate import DelegationRuns, selected_route, validate_record, write_workspace, saved_termination, capture_delegate_arguments
from .pi_guarded_files import root_identity
from .pi_supervisor import closed
from .pi_worker_files import snapshot
from .schema import ConfigError
from .storage import Conflict, Tree


class DelegateController:
  def __init__(self, host, *, schemas=None):
    self.host = host
    self.root = Path(host.config["instance_root"]) / "pi-home/model-delegate"
    self.runs = DelegationRuns(self.root / "runs", **({"schemas": schemas} if schemas else {}))
    from .model_delegate_v3_execution import LogicalExecutions
    from .pi_delegate_sources import DelegateSources
    self.logical = LogicalExecutions(self.runs)
    self.sources = DelegateSources(self)
    self.modern_attempts = {}

  def register_cli_source(self):
    from .pi_supervisor import Principal
    return self.sources.cli(Principal("user"))

  def _logical_input(self, run_id):
    from .model_delegate_v3_intents import _read_run, _document
    def read(tree):
      row = _read_run(tree, self.runs, run_id)
      return deepcopy(_document(tree, "intents-v3/" + row["submit_key"] + ".json")[0]["action"])
    return self.runs._transaction(read)

  def _modern_origin(self, source, run_id=None):
    if run_id is None: return source["origin"]
    row = self.logical.private(run_id)
    if row is None:
      from .model_delegate_v3_intents import _read_run
      origin = self.runs._transaction(lambda tree: deepcopy(_read_run(tree, self.runs, run_id)["origin"]))
    else: origin = row["origin"]
    if origin["instance_id"] != source["origin"]["instance_id"]:
      raise Conflict("DELEGATE_EXECUTION_ORIGIN_CONFLICT")
    if source["source_kind"] != "cli" and origin != source["origin"]:
      raise Conflict("DELEGATE_EXECUTION_ORIGIN_CONFLICT")
    return origin

  def modern_query(self, principal, source_ref, run_id):
    source = self.sources.resolve(principal, source_ref, stop=True)
    origin = self._modern_origin(source, run_id)
    row = self.logical.private(run_id)
    if row is None:
      from .model_delegate_v3_intents import _read_run
      binding = self.runs._transaction(lambda tree: deepcopy(_read_run(tree, self.runs, run_id)["binding"]))
    else: binding = row["binding"]
    result = self.logical.query(origin, run_id, binding)
    for action in result["actions"]:
      action["execution_evidence"] = None
      if action["physical_run_id"] is None: continue
      try: physical = self.runs.read(action["physical_run_id"])
      except Conflict:
        action.update(physical_state="unknown", task_succeeded=False, termination_verified=False)
        continue
      receipt = physical["receipt"]
      action.update(physical_state=physical["state"], task_succeeded=physical["verification"] == "verified-execution"
        and receipt is not None and receipt["terminal_status"] == "completed",
        termination_verified=physical["verification"] == "verified-execution" and receipt is not None
        and receipt["process_terminated"] is True and receipt["resources_reclaimed"] is True)
      if action["termination_verified"]:
        action["execution_evidence"] = self._modern_execution_evidence(action, physical, origin)
    return result

  def _modern_execution_evidence(self, action, physical, origin):
    """只投影原物理收据/同代租约的验证事实；不发新权限、不读工件正文或token。"""
    try:
      request, receipt = physical["request"], physical["receipt"]
      if (physical["verification"] != "verified-execution" or receipt is None
          or any(request[key] != receipt[key] for key in ("run_id", "attempt_id", "lease_id", "grant_generation", "instance_id", "runtime_identity", "policy_digest"))
          or any(request[key] != action[field] for key, field in (("run_id", "physical_run_id"), ("attempt_id", "attempt_id"), ("lease_id", "lease_id")))
          or request["instance_id"] != origin["instance_id"] or request["runtime_identity"] != self.host.runtime_root.name):
        return None
      lease = self.host.store.read(request["lease_id"])
      current = self.host.store.reconcile(lease["lease_id"])
      evidence = lease["termination_evidence"]
      if (lease["execution_id"] != request["run_id"] or lease["attempt_id"] != request["attempt_id"]
          or lease["instance_id"] != request["instance_id"] or lease["policy_digest"] != request["policy_digest"]
          or current["lease_id"] != lease["lease_id"] or current["grant_generation"] != lease["grant_generation"]
          or current["process_identity"] != lease["process_identity"] or current["termination_evidence"] != evidence
          or evidence is None or evidence["grant_generation"] != lease["grant_generation"]
          or current["protected"] is not False or not valid_evidence(lease)
          or receipt["process_terminated"] is not True or receipt["resources_reclaimed"] is not True):
        return None
      # 已验证未启动不冒充成功process；其原not_sent/unknown分支仍由调用方保留。
      if lease["process_identity"] is None or lease["spawn_committed"] is not True:
        return None
      with Tree(self.host.root) as tree:
        raw = tree.read("activity/exits/" + lease["lease_id"] + ".json", max_bytes=16384)
      exit_code = None
      if raw is not None:
        row = json.loads(raw[0])
        closed(row, ("schema_version", "lease_id", "process_identity", "exit_code"))
        if (row["schema_version"] != 1 or row["lease_id"] != lease["lease_id"] or row["process_identity"] != lease["process_identity"]
            or type(row["exit_code"]) is not int): return None
        exit_code = row["exit_code"]
      return {"schema_version": 1, "physical_run_id": request["run_id"], "attempt_id": request["attempt_id"],
        "lease_id": lease["lease_id"], "grant_generation": lease["grant_generation"],
        "process_identity_digest": digest(lease["process_identity"]), "termination_evidence_digest": evidence["evidence_digest"],
        "terminated": True, "resources_reclaimed": True, "exit_code": exit_code}
    except (Conflict, ConfigError, KeyError, TypeError, ValueError, OSError):
      return None

  def modern_action(self, principal, source_ref, raw_action):
    from .model_delegate_actions import capture_delegate_action
    action = capture_delegate_action(raw_action)
    source = self.sources.resolve(principal, source_ref, stop=action["action"] == "cancel")
    run_id = None if action["action"] == "submit" else action["run_id"]
    origin = self._modern_origin(source, run_id)
    original = action if action["action"] == "submit" else self._logical_input(run_id)
    if action["action"] != "cancel":
      self.sources.authorize(source, original)
      binding, budget = self.sources.binding(source, original)
      if self.host.manifest()["options"]["model_delegate"].get("readonly_retries", 0) != 0:
        raise Conflict("DELEGATE_MODERN_RETRY_UNAVAILABLE")
      # 原SDK无已qualified的发送前输入token上界；仅可信合成producer可提供私有oracle。
      if original["backend"] == "pi" and not callable(getattr(self.host, "_delegate_input_oracle", None)):
        raise Conflict("DELEGATE_INPUT_METER_UNAVAILABLE")
      # Codex public turn事件不证明逐次model发送，未qualified的生产严格模式不可派发。
      if original["backend"] == "codex" and getattr(self.host, "_delegate_meter_oracle", None) is None:
        raise Conflict("DELEGATE_CODEX_METER_UNAVAILABLE")
    else:
      binding, budget = None, None
    prior = self.logical.private(run_id) if run_id is not None else None
    current = None if prior is None else next((item for item in reversed(prior["actions"])
      if item["attempt_id"] == prior["active_attempt_id"] and item["physical_run_id"] is not None), None)
    if action["action"] in {"message", "continue"}:
      if current is None or current["state"] in {"sending", "unknown"}: raise Conflict("DELEGATE_EXECUTION_ATTEMPT_UNKNOWN")
      physical = self.runs.read(current["physical_run_id"])
      if action["action"] == "message":
        if not self.ready(current["physical_run_id"]): raise Conflict("DELEGATE_NATIVE_NOT_READY")
        physical = self.runs.read(current["physical_run_id"])
        if physical["state"] != "running": raise Conflict("DELEGATE_MESSAGE_IDLE")
      else:
        proof = saved_termination(self.host.root, physical["request"])
        if (physical["verification"] != "verified-execution" or physical["receipt"] is None
            or not proof["termination_verified"] or not proof["resources_reclaimed"]
            or not physical["receipt"]["backend_resume_token"]): raise Conflict("DELEGATE_TERMINATION_UNKNOWN")
    started = self.logical.begin(origin, action, binding, budget)
    target, key = started["run_id"], started["action_key"]
    if not started["send"]: return self.modern_query(principal, source_ref, target)
    try:
      if action["action"] in {"submit", "continue"}:
        args = {key: original[key] for key in ("backend", "mode", "preset", "task", "model", "cwd", "timeout_seconds",
          "context_artifact", "feedback_required", "allow_workspace_write", "worktree_root")}
        args["idempotency_key"] = key
        if action["action"] == "continue":
          args.update(task=action["text"], timeout_seconds=action["timeout_seconds"], continuation_of=current["physical_run_id"])
        physical_principal = principal
        if action["action"] == "continue" and source["source_kind"] == "model-tool":
          from .pi_supervisor import Principal
          physical_principal = Principal("delegate", principal.lease_id, principal.grant_generation)
        request = self.prepare(physical_principal, args)
        self.logical.update(target, key, state="sending", physical=request)
        self.modern_attempts[request["run_id"]] = {"logical_run_id": target, "action_key": key, "source_kind": source["source_kind"]}
        with Tree(self.root) as tree:
          tree.write_immutable("attempt-associations-v3/" + request["run_id"] + ".json", json_bytes(self.modern_attempts[request["run_id"]]))
        if self.logical.private(target)["cancel_requested"]:
          self.cancel(principal, request["run_id"])
          self.logical.unknown(target, key, "DELEGATE_CANCELED_DURING_PREPARE")
        else:
          reply = self.start(principal, request["run_id"])
          accepted = self._modern_start_accepted(request)
          self.logical.update(target, key, state="acknowledged" if accepted else "unknown", physical=request,
            failure_code=None if accepted else "DELEGATE_START_UNKNOWN")
      elif action["action"] == "message":
        self.logical.update(target, key, state="sending", physical=physical["request"])
        self.modern_live_action(target, key, physical["request"], action)
      else:
        if current is not None:
          self.logical.update(target, key, state="sending", physical=self.input(current["physical_run_id"])["request"])
          self.cancel(principal, current["physical_run_id"])
        self.logical.update(target, key, state="acknowledged")
    except BaseException:
      # 已写sending，异常不能证明原prepare/发送没有副作用，预留保持。
      self.logical.unknown(target, key, "DELEGATE_SEND_UNKNOWN")
      raise
    return self.modern_query(principal, source_ref, target)

  def _modern_start_accepted(self, request):
    # 完整start返回后的物理接受证据；不是native ready或任务成功回执。
    saved = self.input(request["run_id"])["request"]
    if saved != request: return False
    lease = self.host.store.read(request["lease_id"])
    if (lease["lease_id"] != request["lease_id"] or lease["execution_id"] != request["run_id"]
        or lease["attempt_id"] != request["attempt_id"] or lease["grant_generation"] != request["grant_generation"]
        or lease["state"] != "running" or lease["spawn_committed"] is not True
        or lease["process_identity"] is None): return False
    return self.host.processes.observe(lease["process_identity"]) == "alive"

  def modern_live_action(self, logical_run_id, action_key, request, action):
    # 原child stdin是固定入口；输入正文只写私有文件，wire不接自由路径/程序/信号。
    with Tree(self.root, create=True) as tree:
      name = "live-inputs-v3/" + action_key + ".json"
      tree.write_immutable(name, json_bytes(action))
    frame = {"schema_version": 3, "request_id": uuid.uuid4().hex, "action_key": action_key,
      "expected_physical_run_id": request["run_id"], "input_ref": action_key}
    child = self.host.children.get(request["lease_id"])
    if child is None or child["process"].poll() is not None or getattr(child["process"], "stdin", None) is None:
      raise Conflict("DELEGATE_LIVE_CHANNEL_UNAVAILABLE")
    lease = self.host.store.read(request["lease_id"])
    if lease["state"] != "running" or lease["grant_generation"] != request["grant_generation"]:
      raise Conflict("DELEGATE_CONTROL_DENIED")
    with Tree(self.root) as tree:
      tree.write_immutable("live-frames-v3/" + action_key + ".json", json_bytes({"logical_run_id": logical_run_id, "frame": frame,
        "physical": {key: request[key] for key in ("run_id", "attempt_id", "lease_id", "grant_generation", "runtime_identity")},
        "process_identity": lease["process_identity"]}))
    data = json_bytes(frame)
    if len(data) > 4096: raise ConfigError("delegate-live-frame-invalid")
    child["process"].stdin.write(data); child["process"].stdin.flush()
    # 写入管道不是原Agent的ACK；固定匹配回执在后续原poll中归并。
    self.logical.unknown(logical_run_id, action_key, "DELEGATE_MESSAGE_ACK_PENDING")

  def input(self, run_id):
    name = self.runs._key(run_id)
    with Tree(self.root) as tree:
      raw = tree.read("inputs/" + name)
    if raw is None:
      raise Conflict("DELEGATE_RUN_NOT_FOUND")
    try:
      value = json.loads(raw[0])
      closed(value, ("schema_version", "request", "prompt", "route", "grant", "context", "definition_digest", "execution_policy"), ("retry_limit",))
      validate_record("request-v2", value["request"], schemas=self.runs.schemas)
      from .pi_delegate_policy import validate_policy_binding
      validate_policy_binding(value)
      if (value["schema_version"] != 2 or value["request"]["run_id"] != run_id
          or value["definition_digest"] != digest({key: item for key, item in value.items() if key != "definition_digest"})):
        raise ValueError()
    except (ValueError, TypeError, KeyError):
      raise Conflict("DELEGATE_INPUT_INVALID") from None
    return value

  def prepare(self, principal, args):
    args = capture_delegate_arguments(args)
    if principal.role not in ("manager", "delegate", "user"):
      raise Conflict("UNMETERED_EXTERNAL_DELEGATE")
    previous = None
    if args.get("continuation_of"):
      if principal.role not in ("user", "delegate"):
        raise Conflict("DELEGATE_RESUME_NOT_AUTHORIZED")
      previous = self.runs.read(args["continuation_of"])
      prior_proof = saved_termination(self.host.root, previous["request"])
      if not prior_proof["termination_verified"] or not prior_proof["resources_reclaimed"]:
        raise Conflict("DELEGATE_TERMINATION_UNKNOWN")
      if not previous["receipt"] or not previous["receipt"]["backend_resume_token"]:
        raise ConfigError("delegate-resume-token-missing")
    manifest = self.host.manifest(); options = manifest["options"].get("model_delegate", {})
    from .pi_delegate_policy import execution_policy
    policy = execution_policy(manifest, args["backend"])
    retry_limit = options.get("readonly_retries", 0) if principal.role in ("user", "delegate") and args["mode"] in ("review", "investigate") else 0
    if type(retry_limit) is not int or not 0 <= retry_limit <= 3:
      raise ConfigError("delegate-retry-limit")
    if (args["mode"] not in options.get("allowed_modes", []) or args["preset"] not in options.get("presets", [])
        or type(args["timeout_seconds"]) is not int or not 1 <= args["timeout_seconds"] <= options.get("max_run_seconds", 0)):
      raise ConfigError("delegate-request-binding")
    route_id, route = selected_route(manifest, args["backend"], args["model"])
    from .paths import relative_path
    from .process import DependencyError
    with Tree(self.host.runtime_root) as tree:
      preset = tree.read("supervisor/shared/skills/model-delegate/presets/" + args["preset"] + ".md")
    if preset is None:
      raise DependencyError("所选委托用途模板未进入运行包")
    purpose = preset[0].decode("utf8")
    with Tree(self.host.runtime_root) as tree:
      raw = tree.read("runtime/commands.json")
      commands = json.loads(raw[0]) if raw else {}
      definition = commands.get("programs", {}).get("delegate-" + args["backend"])
      if not definition or tree.read(relative_path(definition["entrypoint"]).as_posix()) is None:
        raise DependencyError("所选委托后端缺少冻结入口")
      if args["backend"] == "codex" and (not definition.get("backend_entrypoint") or tree.read(relative_path(definition["backend_entrypoint"]).as_posix()) is None):
        raise DependencyError("所选Codex发行物未就绪")
    cwd = Path(args["cwd"]).resolve(strict=True)
    roots = manifest["options"].get("paths", {}).get("roots", {})
    denied = manifest["options"].get("permissions", {}).get("denied_roots", [])
    allowed = [Path(binding["path"]).resolve(strict=True) for name, binding in roots.items() if name not in denied]
    planned = write_workspace(self.host.store.workspaces, backend=args["backend"], mode=args["mode"],
      configured_mode=options.get("codex", {}).get("mode"), allow_workspace_write=args.get("allow_workspace_write", False),
      worktree_root=args.get("worktree_root"), cwd=cwd, user_authorized=principal.role in ("user", "delegate"))
    admitted_root = any(cwd.is_relative_to(root) for root in allowed)
    if planned:
      # 独立候选通常是原 checkout 的相邻目录；按共同 Git 身份和项目内相对范围授权。
      planned_root = Path(planned[0]["worktree_path"])
      with Tree(Path(planned[0]["git_dir_path"]), private=False) as tree:
        common = tree.read("commondir")
      candidate_common = (Path(planned[0]["git_dir_path"]) / common[0].decode().strip()).resolve(strict=True)
      admitted_root = False
      for name, binding in roots.items():
        if name in denied or binding["purpose"] != "project":
          continue
        source_root = Path(binding["path"]).resolve(strict=True)
        source_identity = self.host.store.workspaces.identify_git(source_root)
        source_git = Path(source_identity["git_dir_path"])
        with Tree(source_git, private=False) as tree:
          source_common = tree.read("commondir")
        source_common = (source_git / source_common[0].decode().strip()).resolve(strict=True) if source_common else source_git
        relative = source_root.relative_to(Path(source_identity["worktree_path"]))
        if source_common == candidate_common and cwd.is_relative_to(planned_root / relative):
          admitted_root = True
    if (not admitted_root or any(cwd.is_relative_to(Path(roots[name]["path"]).resolve(strict=True)) for name in denied)
        or any(cwd.is_relative_to(Path(path).resolve(strict=False)) for path in self.host.config.get("protected_roots", []))):
      raise Conflict("DELEGATE_ROOT_UNBOUND")
    identity = self.host.store.workspaces.identify(cwd)
    candidate = snapshot(cwd, protected_roots=self.host.config.get("protected_roots", []))
    from .model_delegate_context import read_context
    context = read_context(self.root, args["context_artifact"], cwd=cwd, candidate_digest=candidate,
      limit=options["context_budget_tokens"]) if args.get("context_artifact") else None
    if args.get("feedback_required") and context is None:
      raise ConfigError("delegate-feedback-context-required")
    owner = self.host.store.owner
    key = digest({"owner": owner, "key": args["idempotency_key"]})
    intent = {"schema_version": 2, "arguments_digest": digest(args), "run_id": "run-" + uuid.uuid4().hex,
      "attempt_id": "attempt-" + uuid.uuid4().hex, "workspace": identity, "candidate_digest": candidate, "route_id": route_id}
    with Tree(self.root, create=True) as tree:
      old = tree.read("intents/" + key + ".json")
      if old:
        previous = json.loads(old[0])
        if previous.get("arguments_digest") != intent["arguments_digest"] or previous.get("schema_version") != 2:
          raise Conflict("DELEGATE_DISPATCH_CONFLICT")
        # 只有完整输入记录可重用；不能把分配过程中崩溃的缺失记录理解成未启动。
        return deepcopy(self.input(previous["run_id"])["request"])
      tree.write_immutable("intents/" + key + ".json", json_bytes(intent))
    lease = self.host.store.allocate(kind="codex" if args["backend"] == "codex" else "external", execution_id=intent["run_id"],
      task_id=None, attempt_id=intent["attempt_id"], lock_identity=self.host.config["lock_identity"],
      slice_identity=self.host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]), candidate_digest=candidate,
      planned_workspaces=planned)
    try:
      request = {"schema_version": 2, "run_id": intent["run_id"], "attempt_id": intent["attempt_id"], "backend": args["backend"],
        "mode": args["mode"], "preset": args["preset"], "requested_model": deepcopy(args["model"]), "cwd": str(cwd),
        "worktree_identity": identity["workspace_key"], "workspace_identity_digest": identity["workspace_key"],
        "execution_boundary": policy["boundary"], "execution_policy_digest": digest(policy),
        "execution_mode": "delegate-write" if planned else "delegate-readonly", "policy_digest": lease["policy_digest"],
        "runtime_identity": self.host.runtime_root.name, "parent_task_id": None, "lease_id": lease["lease_id"],
        "context_artifact_id": args.get("context_artifact"), "workspace_write_lease_ids": lease["workspace_write_lease_ids"],
        "grant_generation": lease["grant_generation"], "instance_id": owner["instance_id"], "owner_nonce": owner["owner_nonce"],
        "timeout_seconds": args["timeout_seconds"], "continuation_of": args.get("continuation_of"),
        "feedback_required": args.get("feedback_required", False), "candidate_digest": candidate}
      request["request_digest"] = digest({"request": request, "task_digest": digest(args["task"]), "route": route, "context_digest": digest(context), "purpose_digest": digest(purpose), "retry_limit": retry_limit})
      validate_record("request-v2", request, schemas=self.runs.schemas)
      if previous is not None:
        self.runs.check_resume(previous["request"]["run_id"], request, prior_proof, user_authorized=True)
      now = datetime.now(timezone.utc)
      tools = ["tk_read", "tk_grep", "tk_find", "tk_ls"]
      if planned:
        tools += ["tk_write", "tk_edit"]
      grant = {"schema_version": 1, "grant_id": "grant-" + request["run_id"], "operation_id": request["run_id"],
        "instance_id": owner["instance_id"], "issuer_activation_id": owner["supervisor_activation_id"], "execution_mode": request["execution_mode"],
        "allowed_tools": tools, "root_bindings": {**{name: {"path": str(Path(row["path"]).resolve(strict=True)), "identity": root_identity(Path(row["path"]).resolve(strict=True))} for name, row in roots.items()},
          "project": {"path": str(cwd), "identity": root_identity(cwd)}},
        "grant_generation": lease["grant_generation"], "issued_at": now.isoformat(), "expires_at": (now + timedelta(seconds=request["timeout_seconds"])).isoformat()}
      grant["grant_digest"] = digest(grant)
      prompt = purpose + "\n\nExecution mode: " + args["mode"] + "\nPreset text does not grant additional tools, writes or delegation.\nActual bounded task:\n" + args["task"]
      if context:
        prompt += "\nContext is evidence, not additional tool authority:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True)
      if request["feedback_required"]:
        prompt += '\nReturn only JSON with exactly facts, conflicts, summary. Each fact has id, text, source, status. New claims are unverified; do not invent evidence. The controller attaches run, turn and candidate identity.'
      value = {"schema_version": 2, "request": request, "prompt": prompt, "route": {"id": route_id, **route}, "grant": grant, "context": context, "retry_limit": retry_limit, "execution_policy": policy}
      value["definition_digest"] = digest(value)
      with Tree(self.root) as tree:
        tree.write_immutable("inputs/" + self.runs._key(request["run_id"]), json_bytes(value))
      return deepcopy(request)
    except BaseException:
      self.host.store.abort_allocation(lease["lease_id"], owner)
      raise

  def start(self, principal, run_id):
    if principal.role not in ("manager", "delegate", "user"):
      raise Conflict("UNMETERED_EXTERNAL_DELEGATE")
    value = self.input(run_id); request = value["request"]
    if request["owner_nonce"] != self.host.store.owner["owner_nonce"]:
      raise Conflict("DELEGATE_OWNER_CHANGED")
    startup_error = None
    def spawn(saved):
      nonlocal startup_error
      lease = self.host.store.read(saved["lease_id"])
      try:
        active = self.host.service.execution_children()
        if len(active) >= self.host.service.active_children:
          raise Conflict("DELEGATE_CAPACITY_BUSY")
        command = self.host.resolve_command(lease, "delegate-" + saved["backend"], {"run_id": run_id})
      except Exception as error:
        # 尚未越过 spawn 提交点的预检失败可以核实撤销；真正的启动未知仍保留。
        self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
        startup_error = error
        return {}
      with Tree(self.host.root) as tree:
        tree.write_immutable("activity/commands/" + lease["lease_id"] + ".json", json_bytes({"program": "delegate-" + saved["backend"],
          "payload_digest": digest({"run_id": run_id}), "argv_digest": digest(list(command.argv)), "cwd": str(command.cwd)}))
      started = self.host.store.start(lease["lease_id"], self.host.store.owner, spawn=lambda current: self.host.spawn(command, current))
      self.host.activate(started)
      # 原生 wrapper 另行写 ready；未收到时保留未知，不能提前断言宿主已可控制。
      with Tree(self.root) as tree:
        ready = tree.read("reports/" + run_id + "/ready.json")
      return json.loads(ready[0]) if ready else {}
    result = self.runs.start(request, spawn)
    if startup_error is not None:
      self.refresh(run_id)
      raise startup_error
    return result

  def ready(self, run_id):
    value = self.input(run_id); request = value["request"]
    with Tree(self.root) as tree:
      raw = tree.read("reports/" + run_id + "/ready.json")
    if raw is None:
      return False
    record = json.loads(raw[0]); closed(record, ("ready", "run_id", "lease_id", "request_digest"))
    if record != {"ready": True, **{key: request[key] for key in ("run_id", "lease_id", "request_digest")}}:
      raise Conflict("DELEGATE_READY_IDENTITY")
    lease = self.host.store.read(request["lease_id"])
    if lease["state"] != "running" or lease["grant_generation"] != request["grant_generation"]:
      return False
    def acknowledge(tree):
      row = self.runs._read(tree, run_id)
      if row["state"] in ("starting", "start_unknown"):
        row["state"] = "running"; self.runs._save(tree, row)
    self.runs._transaction(acknowledge)
    return True

  def cancel(self, principal, run_id):
    if principal.role not in ("manager", "delegate", "user"):
      raise Conflict("DELEGATE_CONTROL_DENIED")
    value = self.input(run_id)
    def stop(_request):
      lease = self.host.store.read(value["request"]["lease_id"])
      if lease["state"] == "allocating":
        self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      else:
        self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)
    with Tree(self.runs.root) as tree:
      saved = tree.read(self.runs._key(run_id))
    if saved is None:
      # 取消尚在 manager 队列内的分配，不经过原生启动函数。
      self.runs.start(value["request"], lambda _request: {})
    result = self.runs.cancel(run_id, stop)
    self.refresh(run_id)
    return result

  def tick(self):
    for lease in self.host.store.records():
      if lease["execution_id"] in self.modern_attempts or not lease["execution_id"].startswith("run-"): continue
      try:
        with Tree(self.root) as tree: raw = tree.read("attempt-associations-v3/" + lease["execution_id"] + ".json", max_bytes=4096)
        if raw is not None and raw[1] == 0o600:
          association = json.loads(raw[0]); closed(association, ("logical_run_id", "action_key", "source_kind"))
          logical = self.logical.private(association["logical_run_id"])
          action = next((a for a in logical["actions"] if a["action_key"] == association["action_key"]), None)
          if action and action["physical_run_id"] == lease["execution_id"] and action["lease_id"] == lease["lease_id"]:
            self.modern_attempts[lease["execution_id"]] = association
      except (Conflict, ConfigError, ValueError, TypeError): pass
    for physical_run_id, association in list(self.modern_attempts.items()):
      try:
        logical = self.logical.private(association["logical_run_id"])
        if logical is not None and self.logical.now_ms() >= logical["budget"]["deadline_ms"]:
          self.logical.revoke(association["logical_run_id"])
          request = self.input(physical_run_id)["request"]
          if request["owner_nonce"] == self.host.store.owner["owner_nonce"]:
            from .pi_supervisor import Principal
            self.cancel(Principal("user"), physical_run_id)
        if logical is not None:
          for action in logical["actions"]:
            if action["kind"] == "message" and action["physical_run_id"] == physical_run_id and action["state"] == "unknown":
              self._modern_live_ack(logical["run_id"], action["action_key"])
        self.refresh(physical_run_id)
        physical = self.runs.read(physical_run_id)
        if physical["verification"] == "verified-execution" and physical["receipt"] is not None:
          self.logical.finish_verified(association["logical_run_id"], association["action_key"])
      except (Conflict, ConfigError, ValueError):
        pass  # 原证据不完整时保持unknown及全部预留，查询不代替sender推进。
    # detach 后仍由 supervisor 执行硬时限；不依赖观察客户端继续 poll。
    for lease in self.host.store.records():
      if not protected(lease) or not lease["execution_id"].startswith("run-"):
        continue
      try:
        value = self.input(lease["execution_id"])
        if value["request"]["owner_nonce"] != self.host.store.owner["owner_nonce"]:
          continue
        from .pi_delegate_policy import execution_policy
        try:
          stale = digest(execution_policy(self.host.manifest(), value["request"]["backend"])) != value["request"]["execution_policy_digest"]
        except (ConfigError, Conflict):
          stale = True
        if stale or datetime.now(timezone.utc) >= datetime.fromisoformat(value["grant"]["expires_at"]):
          if lease["state"] == "allocating" and not lease["spawn_committed"]:
            self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
          elif lease["state"] == "running":
            self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)
      except (Conflict, ConfigError, ValueError):
        continue  # 损坏/未知记录继续保护；不能凭过期时间直接释放租约。

  def refresh(self, run_id):
    import hashlib
    import os
    value = self.input(run_id); request = value["request"]
    row = self.runs.read(run_id)
    if row["state"] in {"completed", "failed", "canceled", "timeout"}:
      return self.runs.status(run_id)
    lease = self.host.store.read(request["lease_id"])
    if protected(lease) and datetime.now(timezone.utc) >= datetime.fromisoformat(value["grant"]["expires_at"]):
      if lease["state"] == "allocating" and not lease["spawn_committed"]:
        self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      elif lease["state"] == "running":
        self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)
    self.ready(run_id)
    directory = self.root / "reports" / run_id
    with Tree(directory) as reports:
      names = sorted(os.listdir(reports.fd)) if reports.fd is not None else []
      for name in names:
        if name.startswith("event-") and name.endswith(".json"):
          event = json.loads(reports.read(name)[0])
          if name != "event-" + str(event.get("seq", "")).zfill(12) + ".json":
            raise Conflict("DELEGATE_EVENT_IDENTITY")
          self.runs.event(run_id, event)
      result_raw, final_raw = reports.read("result.json"), reports.read("final.md", max_bytes=16 * 1024 * 1024)
    proof = self.host.store.reconcile(lease["lease_id"])
    if proof["protected"] or not proof.get("termination_evidence", {}).get("verified"):
      return self.runs.status(run_id)
    with Tree(self.host.root) as tree:
      raw = tree.read("activity/exits/" + lease["lease_id"] + ".json")
    exit_record = json.loads(raw[0]) if raw else None
    if exit_record and (exit_record.get("process_identity") != lease["process_identity"] or exit_record.get("lease_id") != lease["lease_id"]):
      raise Conflict("DELEGATE_EXIT_IDENTITY")
    result = json.loads(result_raw[0]) if result_raw else None
    if result is not None:
      closed(result, ("schema_version", "run_id", "attempt_id", "request_digest", "process_identity", "host_completed", "observed_model", "resume_token", "usage", "feedback_dispositions"))
      if (result["schema_version"] != 2 or any(result[key] != request[key] for key in ("run_id", "attempt_id", "request_digest"))
          or result["process_identity"] != lease["process_identity"]):
        raise Conflict("DELEGATE_RESULT_IDENTITY")
    final = final_raw[0] if final_raw else b""
    final_digest = hashlib.sha256(final).hexdigest() if final_raw else None
    candidate = snapshot(request["cwd"], protected_roots=self.host.config.get("protected_roots", []))
    events = self.runs.read(run_id)["events"]
    sequence_complete = bool(events and events[-1]["kind"] in {"completed", "failed", "canceled", "timeout"})
    host_completed = bool(result and result["host_completed"] is True)
    success = bool(host_completed and sequence_complete and final.strip() and exit_record and exit_record["exit_code"] == 0)
    from .pi_delegate_policy import verify_execution_policy
    policy_proof = {"execution_policy_verified": False}
    try:
      policy_proof = verify_execution_policy(self.root, request)
    except Conflict:
      success = False
    if request["execution_mode"] == "delegate-readonly" and candidate != request["candidate_digest"]:
      success = False
    dispositions = []
    if request["feedback_required"] and success:
      from .model_delegate_context import feedback_from_result
      try:
        feedback, dispositions = feedback_from_result(final, value["context"], request, candidate)
        with Tree(directory) as tree:
          tree.write_immutable("feedback.json", json_bytes(feedback))
      except (ConfigError, Conflict):
        success = False
    status = "canceled" if lease["stop_requested_at"] or row["cancel_requested"] else "completed" if success else "failed"
    if datetime.now(timezone.utc) >= datetime.fromisoformat(value["grant"]["expires_at"]) and status != "completed":
      status = "timeout"
    resume_ref = result["resume_token"] if result else None
    if result is not None and run_id in self.modern_attempts:
      try: resume_ref = self._modern_resume_ref(request, directory)
      except Conflict: resume_ref = None
    receipt = {**request, "candidate_digest": candidate, "terminal_status": status,
      "backend_resume_token": resume_ref, "event_sequence_complete": sequence_complete,
      "final_artifact_id": "final-" + run_id if final_raw else None, "final_artifact_digest": final_digest,
      "process_terminated": True, "resources_reclaimed": True, "usage": result["usage"] if result else {"input_tokens": None, "output_tokens": None, "cost": None},
      "feedback_dispositions": dispositions, "observed_model": result["observed_model"] if result else None}
    evidence = {"lease_id": lease["lease_id"], "termination_verified": True, "resources_reclaimed": True,
      "exit_code": exit_record["exit_code"] if exit_record else None, "final_artifact_digest": final_digest,
      "final_nonempty": bool(final.strip()), "sequence_complete": sequence_complete, "host_completed": host_completed, "candidate_digest": candidate, **policy_proof}
    return self.runs.finish(run_id, receipt, evidence)

  def _modern_live_ack(self, logical_run_id, action_key):
    with Tree(self.root) as tree: raw = tree.read("live-frames-v3/" + action_key + ".json", max_bytes=8192)
    if raw is None or raw[1] != 0o600: return False
    record = json.loads(raw[0]); closed(record, ("logical_run_id", "frame", "physical", "process_identity"))
    frame = record["frame"]
    closed(frame, ("schema_version", "request_id", "action_key", "expected_physical_run_id", "input_ref"))
    if record["logical_run_id"] != logical_run_id or frame["action_key"] != action_key or frame["input_ref"] != action_key:
      raise Conflict("DELEGATE_LIVE_ACK_INVALID")
    request = self.input(frame["expected_physical_run_id"])["request"]
    if record["physical"] != {key: request[key] for key in ("run_id", "attempt_id", "lease_id", "grant_generation", "runtime_identity")}:
      raise Conflict("DELEGATE_LIVE_ACK_INVALID")
    lease = self.host.store.read(request["lease_id"])
    with Tree(self.root / "reports" / request["run_id"]) as tree:
      raw = tree.read("live-ack-" + action_key + ".json", max_bytes=8192)
    if raw is None or raw[1] != 0o600: return False
    ack = json.loads(raw[0])
    closed(ack, ("schema_version", "accepted", "sent", "request_id", "action_key", "expected_physical_run_id", "native_action_id",
      "process_identity", "grant_generation", "runtime_identity"))
    if (ack["schema_version"] != 3 or ack["accepted"] is not True or ack["sent"] is not True or ack["native_action_id"] is not None
        or any(ack[key] != frame[key] for key in ("request_id", "action_key", "expected_physical_run_id"))
        or ack["process_identity"] != record["process_identity"] or ack["process_identity"] != lease["process_identity"]
        or ack["grant_generation"] != request["grant_generation"] or ack["runtime_identity"] != request["runtime_identity"]):
      raise Conflict("DELEGATE_LIVE_ACK_INVALID")
    logical = self.logical.private(logical_run_id)
    # 取消后迟到ACK仅保留原artifact，不复活grant、额度或后续发送。
    if logical["cancel_requested"] or not self._modern_start_accepted(request): return False
    return self.logical.acknowledge_verified_live(logical_run_id, action_key)

  def modern_worker_authority(self, principal, run_id):
    value = self.input(run_id); request = value["request"]
    if (principal.role != "worker" or principal.lease_id != request["lease_id"]
        or principal.grant_generation != request["grant_generation"]): raise Conflict("DELEGATE_CONTROL_DENIED")
    association = self.modern_attempts.get(run_id)
    if association is None: raise Conflict("DELEGATE_MODERN_SOURCE_REQUIRED")
    lease = self.host.store.read(request["lease_id"])
    if (not self._modern_start_accepted(request) or lease["owner_nonce"] != self.host.store.owner["owner_nonce"]
        or self.host.service.closing): raise Conflict("DELEGATE_CONTROL_DENIED")
    row = self.logical.private(association["logical_run_id"])
    if row is None or row["cancel_requested"] or self.logical.now_ms() >= row["budget"]["deadline_ms"]:
      raise Conflict("DELEGATE_GRANT_REVOKED")
    from .pi_delegate_policy import execution_policy
    if digest(execution_policy(self.host.manifest(), request["backend"])) != request["execution_policy_digest"]:
      raise Conflict("DELEGATE_ADMISSION_STALE")
    return value, association, row

  def _modern_resume_ref(self, request, directory):
    # 只有原终止/回收/结果校验链已通过时由refresh调用；路径不来自模型action。
    import hashlib
    with Tree(directory) as tree:
      raw = tree.read("session-v3.json", max_bytes=4096)
    if raw is None or raw[1] != 0o600: raise Conflict("DELEGATE_RESUME_UNAVAILABLE")
    try:
      record = json.loads(raw[0])
      closed(record, ("schema_version", "physical_run_id", "attempt_id", "session_id", "session_path", "cwd"))
      if (record["schema_version"] != 3 or record["physical_run_id"] != request["run_id"]
          or record["attempt_id"] != request["attempt_id"] or record["cwd"] != request["cwd"]
          or type(record["session_id"]) is not str or not 1 <= len(record["session_id"]) <= 256): raise ValueError()
      path = Path(record["session_path"])
      base = directory / "sessions"
      relative = path.relative_to(base)
      if not path.is_absolute() or len(relative.parts) != 1: raise ValueError()
      with Tree(base) as tree: session = tree.read(str(relative), max_bytes=8 * 1024 * 1024)
      if session is None or session[1] != 0o600: raise ValueError()
      record["session_digest"] = hashlib.sha256(session[0]).hexdigest()
      reference = uuid.uuid4().hex
      with Tree(self.root) as tree: tree.write_immutable("resume-v3/" + reference + ".json", json_bytes(record))
      return reference
    except (ValueError, TypeError, KeyError): raise Conflict("DELEGATE_RESUME_INVALID") from None

  def modern_resume_path(self, request):
    import hashlib
    prior = self.runs.read(request["continuation_of"])
    proof = saved_termination(self.host.root, prior["request"])
    if (prior["verification"] != "verified-execution" or not proof["termination_verified"]
        or not proof["resources_reclaimed"]): raise Conflict("DELEGATE_TERMINATION_UNKNOWN")
    reference = prior["receipt"]["backend_resume_token"]
    if type(reference) is not str or len(reference) != 32 or any(c not in "0123456789abcdef" for c in reference):
      raise Conflict("DELEGATE_RESUME_INVALID")
    with Tree(self.root) as tree: raw = tree.read("resume-v3/" + reference + ".json", max_bytes=4096)
    if raw is None or raw[1] != 0o600: raise Conflict("DELEGATE_RESUME_INVALID")
    record = json.loads(raw[0])
    if (record["physical_run_id"] != request["continuation_of"] or record["attempt_id"] != prior["request"]["attempt_id"]
        or record["cwd"] != request["cwd"]): raise Conflict("DELEGATE_RESUME_INVALID")
    base = self.root / "reports" / request["continuation_of"] / "sessions"
    path = Path(record["session_path"])
    try:
      relative = path.relative_to(base)
      if len(relative.parts) != 1: raise ValueError()
      with Tree(base) as tree: session = tree.read(str(relative), max_bytes=8 * 1024 * 1024)
      if session is None or session[1] != 0o600 or hashlib.sha256(session[0]).hexdigest() != record["session_digest"]: raise ValueError()
    except (ValueError, TypeError): raise Conflict("DELEGATE_RESUME_INVALID") from None
    return str(path)

  def file_action(self, principal, args):
    from .pi_delegate_files import file_action
    return file_action(self, principal, args)

  def handle(self, principal, method, args):
    if method == "delegate_authorize_v3":
      closed(args, ("run_id",))
      value, _association, _row = self.modern_worker_authority(principal, args["run_id"])
      return {"valid": True, "grant_generation": value["request"]["grant_generation"]}
    if method == "delegate_meter_v3":
      closed(args, ("run_id", "metric", "sequence"))
      value, association, _row = self.modern_worker_authority(principal, args["run_id"])
      if args["metric"] == "calls":
        input_oracle = getattr(self.host, "_delegate_input_oracle", None)
        measured = input_oracle(value["request"]) if callable(input_oracle) else None
        if type(measured) is not int or measured != 0: raise Conflict("DELEGATE_INPUT_METER_UNAVAILABLE")
      # 已核原Agent ACK的message预留被下一次真实请求消费，不给发送者新额度。
      pending = next((a for a in _row["actions"] if a["kind"] == "message" and a["physical_run_id"] == args["run_id"]
        and a["state"] == "acknowledged" and a["reservation"][args["metric"]] > 0), None)
      meter_key = pending["action_key"] if pending else association["action_key"]
      oracle = getattr(self.host, "_delegate_meter_oracle", None)
      cost = oracle(value["request"]) if callable(oracle) and args["metric"] == "calls" else None
      return self.logical.meter_claim(association["logical_run_id"], meter_key, args["metric"], args["sequence"], synthetic_cost=cost)
    if method == "delegate_runtime_contract_v3":
      closed(args, ())
      self.sources._live_manager(principal)
      manifest = self.sources._full()
      from .pi_runtime_packages import MAX_RECEIPT
      with Tree(self.host.runtime_root) as tree:
        raw = tree.read(".agentcfg-receipt.json", max_bytes=MAX_RECEIPT)
      receipt = json.loads(raw[0]); piece = receipt["slice"]
      return {"schema_version": 3, "profile_id": "pi-full", "runtime_identity": receipt["identity"],
        "slice_identity": receipt["slice_identity"], "lock_identity": receipt["lock_identity"],
        "capability_projection": {"capability_ids": piece["capability_ids"], "plugins": manifest["plugin_capabilities"]},
        "provider_projection": manifest["provider_bindings"], "source_projection": {"source_ids": piece["source_ids"],
          "runtime_files": piece["runtime_files"], "resources": piece["resource_manifest"]},
        "config_identity": self.host.config["manifest_digest"], "policy_digest": digest(manifest["permission_policy"]),
        "checker_identity": "delegate-runtime-contract-v3"}
    if method == "delegate_task_source_retire_v3":
      closed(args, ("source_ref",))
      return self.sources.retire_task_keeper(principal, args["source_ref"])
    if method == "delegate_task_source_v3":
      closed(args, ("facts",))
      return {"source_ref": self.sources.task_keeper(principal, args["facts"])}
    if method == "delegate_source_open_v3":
      closed(args, ("session_id",))
      return {"source_ref": self.sources.model(principal, args["session_id"])}
    if method == "delegate_action_v3":
      closed(args, ("source_ref", "action"))
      return self.modern_action(principal, args["source_ref"], args["action"])
    if method == "delegate_lookup_v3":
      closed(args, ("source_ref", "request_id"))
      source = self.sources.resolve(principal, args["source_ref"], stop=True)
      registration = self.runs.read_modern_intent(source["origin"], args["request_id"])
      return self.modern_query(principal, args["source_ref"], registration["run_id"])
    if method == "delegate_artifact_v3":
      closed(args, ("source_ref", "run_id", "offset", "limit"))
      result = self.modern_query(principal, args["source_ref"], args["run_id"])
      action = next((a for a in reversed(result["actions"]) if a["attempt_id"] == result.get("active_attempt_id")
        and a.get("termination_verified")), None)
      if action is None: raise Conflict("DELEGATE_RESULT_UNVERIFIED")
      physical = self.runs.read(action["physical_run_id"])
      from .model_delegate import artifact_chunk
      return artifact_chunk(self.root, physical["receipt"], offset=args["offset"], limit=args["limit"])
    if method in {"delegate_status_v3", "delegate_result_v3", "delegate_poll_v3"}:
      closed(args, ("source_ref", "run_id"))
      return self.modern_query(principal, args["source_ref"], args["run_id"])
    if (method in {"delegate_prepare", "delegate_start", "delegate_command_start"}
        and self.host.manifest().get("profile_id") == "pi-full"
        and self.host.manifest().get("plugin_capabilities", {}).get("model-delegate", {}).get("capability_id") == "unified-delegate"):
      raise Conflict("DELEGATE_MODERN_SOURCE_REQUIRED")
    if method == "delegate_abort":
      closed(args, ("run_id", "lease_id"))
      value = self.input(args["run_id"])
      if principal.role != "worker" or principal.lease_id != args["lease_id"] or args["lease_id"] != value["request"]["lease_id"]:
        raise Conflict("DELEGATE_CONTROL_DENIED")
      self.host.store.request_cancel(args["lease_id"], self.host.store.owner)
      return {"accepted": True, "termination_confirmed": False}
    if method == "delegate_file_action":
      if self.input(args["run_id"])["request"]["execution_boundary"] != "agentcfg-tools":
        raise Conflict("DELEGATE_EXECUTION_BOUNDARY")
      return self.file_action(principal, args)
    if principal.role not in ("manager", "delegate", "user"):
      raise Conflict("UNMETERED_EXTERNAL_DELEGATE")
    if method == "delegate_artifact":
      closed(args, ("run_id", "offset", "limit"))
      from .model_delegate import artifact_chunk
      verified = self.handle(principal, "delegate_result", {"run_id": args["run_id"]})
      if verified["verification"] != "verified-execution":
        raise Conflict("DELEGATE_RESULT_UNVERIFIED")
      return artifact_chunk(self.root, verified["receipt"], offset=args["offset"], limit=args["limit"])
    if method == "delegate_prepare":
      return self.prepare(principal, args)
    if method in {"delegate_start", "delegate_status", "delegate_cancel", "delegate_result"}:
      closed(args, ("run_id",))
      if method == "delegate_start":
        return self.start(principal, args["run_id"])
      if method == "delegate_cancel":
        return self.cancel(principal, args["run_id"])
      status = self.refresh(args["run_id"])
      if method == "delegate_result":
        receipt = self.runs.read(args["run_id"])["receipt"]
        if receipt is None:
          raise Conflict("DELEGATE_RESULT_PENDING")
        if receipt["terminal_status"] == "completed":
          import hashlib
          current = snapshot(receipt["cwd"], protected_roots=self.host.config.get("protected_roots", []))
          with Tree(self.root / "reports" / args["run_id"]) as tree:
            artifact = tree.read("final.md", max_bytes=16 * 1024 * 1024)
          physical = self.host.store.reconcile(receipt["lease_id"])
          if (current != receipt["candidate_digest"] or artifact is None or not artifact[0].strip()
              or hashlib.sha256(artifact[0]).hexdigest() != receipt["final_artifact_digest"]
              or physical["protected"] or not physical.get("termination_evidence", {}).get("verified")):
            raise Conflict("DELEGATE_RESULT_STALE")
          from .pi_delegate_policy import verify_execution_policy
          verify_execution_policy(self.root, self.runs.read(args["run_id"])["request"])
          from .model_delegate_context import verify_saved_feedback
          verify_saved_feedback(self.root, self.runs.read(args["run_id"])["request"], receipt, artifact[0])
        return {"receipt": receipt, "receipt_digest": digest(receipt), "verification": status["verification"]}
      return status
    if method == "delegate_poll":
      closed(args, ("run_id", "after"))
      self.refresh(args["run_id"])
      return self.runs.poll(args["run_id"], args["after"])
    raise ConfigError("delegate-control-method")
