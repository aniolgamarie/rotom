"""Full controller 私有来源注册；字符串/模型字段不产生来源或写批准。"""

from copy import deepcopy
from pathlib import Path
import json
import uuid

from .activity import digest
from .deployment import json_bytes
from .model_delegate_actions import capture_delegate_origin
from .model_delegate_v3_execution import capture_budget
from .pi_supervisor import Principal
from .schema import ConfigError
from .storage import Conflict, Tree


class DelegateSources:
  def __init__(self, controller):
    self.controller = controller
    self.live = {}
    self.profile_bytes = None

  def _full(self):
    host = self.controller.host
    manifest = host.manifest()
    if (manifest.get("profile_id") != "pi-full" or "model-delegate" not in manifest.get("plugins", [])
        or manifest.get("plugin_capabilities", {}).get("model-delegate", {}).get("capability_id") != "unified-delegate"):
      raise Conflict("DELEGATE_CAPABILITY_UNAVAILABLE")
    with Tree(host.runtime_root) as tree:
      raw = tree.read("runtime/profile.json", max_bytes=8 * 1024 * 1024)
      from .pi_runtime_packages import MAX_RECEIPT
      receipt_raw = tree.read(".agentcfg-receipt.json", max_bytes=MAX_RECEIPT)
    if raw is None or receipt_raw is None: raise Conflict("DELEGATE_SOURCE_UNAVAILABLE")
    profile = json.loads(raw[0])
    receipt = json.loads(receipt_raw[0])
    if (profile.get("schema_version") != 2 or profile.get("profile_id") != "pi-full"
        or profile.get("runtime_identity") != host.runtime_root.name
        or "unified-delegate" not in receipt.get("slice", {}).get("capability_ids", [])):
      raise Conflict("DELEGATE_SOURCE_UNAVAILABLE")
    if self.profile_bytes is None:
      from .pi_runtime_packages import status
      if status(host.runtime_root, host.runtime_root.name) != "installed": raise Conflict("DELEGATE_SOURCE_UNAVAILABLE")
      self.profile_bytes = (raw[0], receipt_raw[0])
    elif self.profile_bytes != (raw[0], receipt_raw[0]): raise Conflict("DELEGATE_SOURCE_STALE")
    return manifest

  def _live_manager(self, principal):
    if type(principal) is not Principal or principal.role != "manager" or principal.lease_id is None:
      raise Conflict("DELEGATE_SOURCE_REGISTRATION_DENIED")
    host = self.controller.host
    lease = host.store.read(principal.lease_id)
    if (lease["kind"] != "host" or lease["state"] != "running" or lease["grant_generation"] != principal.grant_generation
        or host.store.processes.observe(lease["process_identity"]) != "alive"):
      raise Conflict("DELEGATE_SOURCE_STALE")
    return lease

  def _register(self, kind, principal, source_id, *, task_id=None, step_id=None, authorization=None):
    manifest = self._full()
    if type(source_id) is not str or not 1 <= len(source_id) <= 150: raise ConfigError("delegate-source-invalid")
    host = self.controller.host
    origin = capture_delegate_origin({"instance_id": host.store.owner["instance_id"], "host": "cli" if kind == "cli" else "pi",
      "source_id": source_id, "task_id": task_id, "step_id": step_id})
    scope = authorization or {"modes": ["review", "investigate"], "write_authorized": False,
      "roots": deepcopy(manifest["options"].get("paths", {}).get("roots", {}))}
    record = {"schema_version": 3, "kind": "delegate-source", "source_kind": kind, "origin": origin, "authorization": scope}
    with Tree(self.controller.root, create=True) as tree:
      path = "sources-v3/" + digest(origin) + ".json"
      old = tree.read(path, max_bytes=1024 * 1024)
      if old is None: tree.write_immutable(path, json_bytes(record))
      elif old[0] != json_bytes(record): raise Conflict("DELEGATE_SOURCE_SCOPE_STALE")
    reference = uuid.uuid4().hex
    manager_id = getattr(host, "host_lease_id", None) or (principal.lease_id if principal.role == "manager" else None)
    lease = host.store.read(manager_id) if manager_id else None
    self.live[reference] = {"record": record, "role": principal.role, "principal_lease_id": principal.lease_id,
      "principal_generation": principal.grant_generation, "activation": host.store.owner["supervisor_activation_id"],
      "manager_lease_id": manager_id, "manager_generation": lease["grant_generation"] if lease else None}
    return reference

  def model(self, principal, session_id):
    self._live_manager(principal)
    if type(session_id) is not str: raise ConfigError("delegate-source-invalid")
    # Session ID由选定的自有factory取原public SessionManager，模型action不接该字段。
    return self._register("model-tool", principal, "session:" + session_id)

  def task_keeper(self, principal, facts):
    if type(principal) is not Principal or principal.role != "task-keeper-source":
      raise Conflict("DELEGATE_SOURCE_REGISTRATION_DENIED")
    host = self.controller.host
    lease = host.store.read(principal.lease_id)
    if (lease["kind"] != "host" or lease["state"] != "running" or lease["grant_generation"] != principal.grant_generation
        or host.store.processes.observe(lease["process_identity"]) != "alive"):
      raise Conflict("DELEGATE_SOURCE_STALE")
    manifest = self._full()
    if "task-keeper" not in manifest["plugins"] or manifest["options"].get("task_keeper", {}).get("enabled") is not True:
      raise Conflict("DELEGATE_CAPABILITY_UNAVAILABLE")
    from .pi_supervisor import closed
    from .paths import safe_id
    closed(facts, ("task_id", "step_id", "store_owner", "cwd", "source_cwd", "role", "model", "policy_digest"))
    closed(facts["store_owner"], ("scopeId", "token", "epoch"))
    if (facts["role"] not in ("scout", "reviewer") or facts["policy_digest"] != digest(manifest["permission_policy"])
        or type(facts["store_owner"]["epoch"]) is not int or facts["store_owner"]["epoch"] < 1
        or any(type(facts["store_owner"][k]) is not str or not 1 <= len(facts["store_owner"][k]) <= 256 for k in ("scopeId", "token"))):
      raise Conflict("DELEGATE_TASK_SCOPE_UNAVAILABLE")
    task_id, step_id = safe_id(facts["task_id"]), safe_id(facts["step_id"])
    role = "task_keeper_reviewer" if facts["role"] == "reviewer" else "task_keeper_reader"
    selected = manifest.get("model_bindings", {}).get(role)
    if selected is None or facts["model"] != {"provider_id": selected["provider"], "model_id": selected["model"]}:
      raise Conflict("DELEGATE_TASK_ROLE_UNAVAILABLE")
    role_id = "task-keeper-reviewer" if facts["role"] == "reviewer" else "task-keeper-reader"
    phase = manifest.get("role_bindings", {}).get(role_id)
    if (type(phase) is not dict or phase.get("managed") is not True or phase.get("model") != selected
        or phase.get("write_roots") != [] or type(phase.get("read_roots")) is not list
        or not {"tk_read", "tk_ls", "tk_find", "tk_grep"} <= set(phase.get("tools", []))):
      raise Conflict("DELEGATE_TASK_ROLE_UNAVAILABLE")
    cwd, source_cwd = Path(facts["cwd"]).resolve(strict=True), Path(facts["source_cwd"]).resolve(strict=True)
    roots = manifest["options"].get("paths", {}).get("roots", {})
    if not any(source_cwd.is_relative_to(Path(row["path"]).resolve(strict=True)) for row in roots.values() if row["purpose"] == "project"):
      raise Conflict("DELEGATE_ROOT_UNBOUND")
    if not phase["read_roots"] or not set(phase["read_roots"]) <= set(roots): raise Conflict("DELEGATE_TASK_ROLE_UNAVAILABLE")
    authorization = {"modes": ["review", "investigate"], "write_authorized": False, "roots": {key: deepcopy(roots[key]) for key in phase["read_roots"] if key in roots},
      "task_binding": {"cwd": str(cwd), "source_cwd": str(source_cwd), "model": deepcopy(facts["model"]), "store_scope_id": facts["store_owner"]["scopeId"]}}
    reference = self._register("task-keeper", Principal("manager", principal.lease_id, principal.grant_generation), "task:" + task_id + ":" + step_id,
      task_id=task_id, step_id=step_id, authorization=authorization)
    self.live[reference]["store_owner"] = deepcopy(facts["store_owner"])
    return reference

  def retire_task_keeper(self, principal, reference):
    slot = self.live.get(reference)
    if (type(principal) is not Principal or principal.role != "task-keeper-source" or slot is None
        or slot["record"]["source_kind"] != "task-keeper" or slot["principal_lease_id"] != principal.lease_id
        or slot["principal_generation"] != principal.grant_generation): raise Conflict("DELEGATE_SOURCE_REGISTRATION_DENIED")
    for association in self.controller.modern_attempts.values():
      logical = self.controller.logical.private(association["logical_run_id"])
      if logical is not None and logical["origin"] == slot["record"]["origin"]:
        self.controller.logical.revoke(logical["run_id"])
    del self.live[reference]
    return {"retired": True}

  def cli(self, principal):
    if type(principal) is not Principal or principal.role != "user": raise Conflict("DELEGATE_SOURCE_REGISTRATION_DENIED")
    host = self.controller.host
    with Tree(self.controller.root, create=True) as tree:
      raw = tree.read("cli-source-id.json", max_bytes=1024)
      if raw is None:
        source_id = "cli-" + uuid.uuid4().hex
        tree.write_immutable("cli-source-id.json", json_bytes({"source_id": source_id}))
      else: source_id = json.loads(raw[0])["source_id"]
    reference = self._register("cli", principal, source_id)
    with Tree(self.controller.root) as tree:
      tree.write_state("cli-source-ref.json", json_bytes({"schema_version": 3, "source_ref": reference,
        "activation": host.store.owner["supervisor_activation_id"]}))
    return reference

  def resolve(self, principal, reference, *, stop=False):
    if type(reference) is not str or reference not in self.live: raise Conflict("DELEGATE_SOURCE_REQUIRED")
    slot = self.live[reference]; host = self.controller.host
    if (type(principal) is not Principal or principal.role != slot["role"] or principal.lease_id != slot["principal_lease_id"]
        or principal.grant_generation != slot["principal_generation"] or slot["activation"] != host.store.owner["supervisor_activation_id"]):
      raise Conflict("DELEGATE_SOURCE_REQUIRED")
    if slot["manager_lease_id"] is not None and not (stop and slot["record"]["source_kind"] == "cli"):
      lease = host.store.read(slot["manager_lease_id"])
      if (lease["state"] != "running" or lease["grant_generation"] != slot["manager_generation"]
          or host.store.processes.observe(lease["process_identity"]) != "alive"):
        raise Conflict("DELEGATE_SOURCE_STALE")
    if not stop: self._full()
    return deepcopy(slot["record"])

  def authorize(self, source, action):
    if action["action"] != "submit": return
    scope = source["authorization"]
    if source["source_kind"] == "model-tool" and (action["mode"] == "implement" or action["allow_workspace_write"] or action["worktree_root"] is not None):
      raise Conflict("DELEGATE_MODEL_WRITE_FORBIDDEN")
    if action["mode"] not in scope["modes"] or action["mode"] == "implement" and scope.get("write_authorized") is not True:
      raise Conflict("DELEGATE_SOURCE_SCOPE_DENIED")
    task = scope.get("task_binding")
    if task and (action["cwd"] != task["cwd"] or action["model"] != task["model"]):
      raise Conflict("DELEGATE_TASK_SCOPE_UNAVAILABLE")
    cwd = Path(action["cwd"]).resolve(strict=True)
    if not any(cwd.is_relative_to(Path(row["path"]).resolve(strict=True)) for row in scope["roots"].values()):
      raise Conflict("DELEGATE_ROOT_UNBOUND")

  def binding(self, source, action):
    host = self.controller.host; manifest = self._full()
    options = manifest["options"].get("model_delegate", {})
    budget = capture_budget(options.get("budget"))
    from .model_delegate import selected_route
    route_id, route = selected_route(manifest, action["backend"], action["model"])
    workspace = host.store.workspaces.identify(Path(action["cwd"]))
    providers = manifest.get("model_configuration", {}).get("providers", {})
    selected = providers.get(action["model"]["provider_id"])
    if selected is None:
      selected = next((value for value in providers.values() if value.get("logical_id") == action["model"]["provider_id"]), None)
    if type(selected) is not dict: raise Conflict("DELEGATE_ACCOUNT_SCOPE_UNAVAILABLE")
    authentication = {key: selected.get(key) for key in ("auth_kind", "owner", "logical_id", "credential_ref")}
    # 原manifest只含公开配置/凭据引用，不读/散列认证值。
    account = digest({"instance_id": host.store.owner["instance_id"], "backend": action["backend"],
      "provider": action["model"]["provider_id"], "route_id": route_id, "authentication": authentication,
      "proxy_credential_category": route.get("credential_ref")})
    binding = {"runtime_identity_digest": host.runtime_root.name,
      "capability_binding_digest": digest({"profile": "pi-full", "plugins": manifest["plugin_capabilities"]}),
      "config_identity_digest": digest({"manifest_digest": host.config.get("manifest_digest"), "delegate": options,
        "models": manifest["model_bindings"], "allowed_models": manifest["allowed_models"],
        "authentication": authentication}),
      "policy_digest": digest(manifest["permission_policy"]), "workspace_identity_digest": workspace["workspace_key"],
      "account_scope_id": account, "budget_scope_id": budget["scope_id"]}
    return binding, budget
