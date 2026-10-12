"""MCP同一准备对象/一次许可；不创建服务、不发送网络、不恢复未知调用。"""

from copy import deepcopy

from .activity import OWNER_KEYS, digest
from .pi_operation_admission import context, encode_private_input
from .pi_policy_approval import aggregate_approval
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict


class McpOperationAdmissions:
  def __init__(self, operations, *, context_provider, admissions):
    from .pi_operation_admission import OperationAdmissions
    self.operations, self.host = operations, operations.host
    if (type(admissions) is not OperationAdmissions or not callable(context_provider)
        or admissions.activation_id != self.host.store.owner["manager_activation_id"]):
      raise ConfigError("pi-operation-shared-admissions")
    self.ledger, self.context_provider = admissions, context_provider
    self.mutex = self.host.service.mutex
    self.records, self.requests, self.permits = {}, {}, {}

  def _principal(self, principal):
    if principal.role != "manager" or not principal.lease_id: raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    parent = self.host.store.read(principal.lease_id)
    if (parent["kind"] != "host" or parent["state"] != "running"
        or parent["grant_generation"] != principal.grant_generation
        or any(parent[key] != self.host.store.owner[key] for key in OWNER_KEYS)
        or self.host.store.processes.observe(parent["process_identity"]) != "alive"):
      raise Conflict("GRANT_STALE")

  def _compile(self, current, private):
    closed(private, ("server_name", "action", "name", "arguments"))
    if type(private["arguments"]) is not dict: raise ConfigError("pi-mcp-call-input")
    encode_private_input(private, allow_finite_numbers=True)
    manifest = self.host.manifest()
    projection = manifest.get("native_mcp")
    if (manifest.get("profile_id") not in ("pi-base", "pi-full")
        or type(projection) is not dict): raise Conflict("MCP_CAPABILITY_UNAVAILABLE")
    closed(projection, ("schema_version", "loaded_config", "bindings", "allowed_tools"))
    if type(projection["schema_version"]) is not int or projection["schema_version"] != 1:
      raise ConfigError("pi-native-mcp-projection")
    bindings, allowed = projection["bindings"], projection["allowed_tools"]
    if type(bindings) is not dict or type(allowed) is not dict or set(bindings) != set(allowed):
      raise ConfigError("pi-native-mcp-projection")
    names = sorted(bindings) if private["server_name"] is None else [private["server_name"]]
    if (not names or len(names) > 64 or any(type(name) is not str or name not in bindings for name in names)
        or private["action"] not in ("tool", "list_resources", "list_templates", "read_resource", "tool_search")):
      raise ConfigError("pi-mcp-call-input")
    if private["action"] == "tool":
      if len(names) != 1 or private["name"] not in allowed[names[0]]: raise Conflict("MCP_TOOL_UNSELECTED")
    elif private["action"] == "read_resource":
      if len(names) != 1 or private["name"] != "read_mcp_resource": raise ConfigError("pi-mcp-call-input")
    elif private["name"] != {"list_resources": "list_mcp_resources", "list_templates": "list_mcp_resource_templates",
        "tool_search": "tool_search"}[private["action"]]: raise ConfigError("pi-mcp-call-input")
    modes, bound = [], {}
    for name in names:
      binding = bindings[name]
      selected = manifest.get("options", {}).get("mcp", {}).get("servers", {}).get(name)
      if type(binding) is not dict or type(selected) is not dict or binding.get("transport") != selected.get("transport"):
        raise Conflict("MCP_BINDING_STALE")
      rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command"
        and row["command_ref"] == "mcp:" + name and "mcp" in row["tool_ids"] and "execute" in row["operations"]]
      if not rules or any(row["effect"] == "deny" for row in rules): raise Conflict("OPERATION_HARD_DENIED")
      modes.extend(row.get("approval", "human") for row in rules if row["effect"] == "allow")
      # 只保存已部署的非秘密声明；参数及URI不进入摘要。
      route = None
      if binding["transport"] != "stdio":
        route = manifest.get("options", {}).get("network", {}).get("routes", {}).get(binding.get("network_route"))
        if not route or "mcp:" + name not in route.get("service_ids", []): raise Conflict("MCP_BINDING_STALE")
      bound[name] = {"binding": binding, "selection": selected, "route": route, "tools": allowed[name]}
    approval = aggregate_approval(modes)
    return {"kind": "mcp", "tool_name": "mcp", "target": {"server_names": names, "action": private["action"],
      "name": private["name"], "binding_digest": digest(bound)}, "read_roots": [], "write_roots": [], "workspace_keys": [],
      "network": "deny" if all(bindings[name]["transport"] == "stdio" for name in names) else "managed-route",
      "services": ["mcp:" + name for name in names], "backend": "native-mcp-v1", "policy": {
        "generation": current["policy_generation"], "policy_digest": digest(manifest["permission_policy"]),
        "ceiling_digest": digest(bound), "hard_policy": "allow", "approval": approval, "requires_human": approval == "human"}}

  def _current(self, request_id):
    current = context(self.context_provider(request_id))
    if (current["activation_id"] != self.ledger.activation_id or current["role_id"] != "main"
        or current["runtime_identity"] != self.host.runtime_root.name
        or current["profile"] != self.host.manifest().get("profile_id")): raise Conflict("OPERATION_CONTEXT_STALE")
    return current

  def _entry(self, principal, operation_id):
    self._principal(principal)
    entry = self.records.get(operation_id)
    if entry is None: raise Conflict("OPERATION_UNKNOWN")
    if entry["principal"] != (principal.lease_id, principal.grant_generation): raise Conflict("OPERATION_CONTROL_OWNER")
    return entry

  def _fresh(self, entry, current):
    try:
      if context(current) != entry["prepared"]["context"] or self.ledger.now_ms() >= current["deadline_ms"]:
        raise Conflict("OPERATION_CONTEXT_STALE")
      resolved = self._compile(current, entry["private"])
      if resolved != entry["prepared"]["resolution"]: raise Conflict("OPERATION_RESOLUTION_STALE")
      return resolved
    except Exception:
      self.ledger.revoke(entry["prepared"]["operation_id"])
      if entry["state"] in ("prepared", "consumed"): entry["state"] = "revoked"
      raise

  def prepare(self, principal, request_id, tool_name, private_input):
    with self.mutex:
      self._principal(principal)
      if tool_name != "mcp": raise ConfigError("pi-mcp-call-tool")
      current = self._current(request_id)
      resolved = self._compile(current, private_input)
      prepared = self.ledger.prepare(request_id, current=current, resolved=resolved, private_input=private_input)
      if prepared["operation_id"] not in self.records:
        self.records[prepared["operation_id"]] = {"prepared": deepcopy(prepared), "private": deepcopy(private_input),
          "principal": (principal.lease_id, principal.grant_generation), "state": "prepared"}
      return prepared

  def issue(self, principal, operation_id, *, operation_digest, source, reviewer_identity=None):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      self._fresh(entry, self._current(entry["prepared"]["request_id"]))
      permit = self.ledger.issue(operation_id, operation_digest=operation_digest,
        current=entry["prepared"]["context"], source=source, reviewer_identity=reviewer_identity)
      self.permits[permit["permit_id"]] = operation_id
      return permit

  def consume(self, principal, permit):
    with self.mutex:
      entry = self._entry(principal, self.permits.get(permit.get("permit_id")))
      resolved = self._fresh(entry, self._current(entry["prepared"]["request_id"]))
      self.ledger.consume(permit, current=entry["prepared"]["context"], resolved=resolved)
      entry["state"] = "consumed"
      return {"operation_id": entry["prepared"]["operation_id"], "kind": "mcp", "state": "consumed"}

  def dispatch(self, principal, operation_id, current, actual):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      if entry["state"] != "consumed": raise Conflict("MCP_DISPATCH_ALREADY_COMMITTED")
      self._fresh(entry, current)
      if encode_private_input(actual, allow_finite_numbers=True) != encode_private_input(entry["private"], allow_finite_numbers=True):
        entry["state"] = "revoked"
        raise Conflict("OPERATION_IDEMPOTENCY_CONFLICT")
      # 先不可逆烧掉派发槽；丢回执不重发。真实IO由唯一Node transport随后消费。
      entry["state"] = "sending"
      return {"operation_id": operation_id, "state": "sending"}

  def complete(self, principal, operation_id, outcome):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      if outcome not in ("succeeded", "failed", "cancelled", "unknown"): raise ConfigError("pi-mcp-call-outcome")
      if entry["state"] not in ("sending", "cancelled"): raise Conflict("MCP_DISPATCH_NOT_COMMITTED")
      entry["state"] = "unknown" if entry["state"] == "cancelled" else outcome
      return {"operation_id": operation_id, "state": entry["state"]}

  def revoke(self, principal, operation_id):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      self.ledger.revoke(operation_id)
      if entry["state"] in ("prepared", "consumed", "sending"):
        entry["state"] = "cancelled" if entry["state"] in ("consumed", "sending") else "revoked"
      return entry["state"]

  def status(self, principal, operation_id):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      return {"admission": self.ledger.status(operation_id), "execution": {"operation_id": operation_id, "kind": "mcp", "state": entry["state"]}}
