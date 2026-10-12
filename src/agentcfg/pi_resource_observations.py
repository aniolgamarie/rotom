"""认证manager的有界加载报告；历史元数据不是权限、SourceHold或实时存活证明。"""
from copy import deepcopy
import json
import re

from .activity import OWNER_KEYS
from .deployment import json_bytes
from .pi_supervisor import Principal
from .paths import PathError
from .storage import Conflict, Tree


PATH = "diagnostics/resource-observation.json"
SNAPSHOT_LIMIT = 65536
FILE_LIMIT = 72 * 1024
KINDS = ("extensions", "skills", "prompts", "themes")
SCOPES = {"instance", "runtime", "project", "external"}
_RECORD = {"schema_version", "instance_id", "manager_activation_id", "manager_lease_id", "manager_generation",
  "session_id", "generation", "manifest_digest", "retired", "channel_closing", "snapshot"}


def _fail():
  raise Conflict("RESOURCE_OBSERVATION_INVALID") from None


def _closed(value, keys):
  if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != set(keys): _fail()


def _sha(value):
  if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None: _fail()


def _id(value, session=False):
  pattern = "[a-zA-Z0-9][a-zA-Z0-9_-]{0,149}" if session else "[a-z][a-z0-9_-]{0,63}"
  if type(value) is not str or re.fullmatch(pattern, value) is None: _fail()


def _generation(value):
  if type(value) is not int or not 1 <= value <= 2**53 - 1: _fail()


def capture_snapshot(value):
  _closed(value, {"schemaVersion", "profileId", "lockIdentity", "sliceIdentity", "runtimeIdentity",
    "configIdentity", "resourcesDigest", "observation"})
  if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or type(value["profileId"]) is not str or value["profileId"] not in ("pi-base", "pi-full"): _fail()
  for key in ("lockIdentity", "sliceIdentity", "runtimeIdentity", "configIdentity", "resourcesDigest"): _sha(value[key])
  observed = value["observation"]
  _closed(observed, {"schemaVersion", "scope", "resourcesDigest", "resources", "inlineExtensions", "selectedRoles", "rolesEvidence"})
  if (type(observed["schemaVersion"]) is not int or observed["schemaVersion"] != 1
      or type(observed["scope"]) is not str or observed["scope"] != "in-memory-public-sdk-load" or type(observed["rolesEvidence"]) is not str or observed["rolesEvidence"] != "selection-only"
      or observed["resourcesDigest"] != value["resourcesDigest"]): _fail()
  _closed(observed["resources"], KINDS)
  count = 0
  for rows in (*observed["resources"].values(), observed["selectedRoles"]):
    if type(rows) is not list or len(rows) > 4096: _fail()
    seen = set()
    for row in rows:
      _closed(row, {"id", "scope"}); _id(row["id"])
      if type(row["scope"]) is not str or row["scope"] not in SCOPES or row["id"] in seen: _fail()
      seen.add(row["id"])
    count += len(rows)
  inline = observed["inlineExtensions"]
  if type(inline) is not list or len(inline) > 4096: _fail()
  for name in inline: _id(name)
  if len(set(inline)) != len(inline) or count + len(inline) > 4096: _fail()
  if len(json_bytes(value)) > SNAPSHOT_LIMIT: _fail()
  return deepcopy(value)


def _record(value):
  _closed(value, _RECORD)
  if type(value["schema_version"]) is not int or value["schema_version"] != 1: _fail()
  for key in ("instance_id", "manifest_digest"): _sha(value[key])
  for key in ("manager_activation_id", "manager_lease_id", "session_id"): _id(value[key], True)
  for key in ("generation", "manager_generation"): _generation(value[key])
  if type(value["retired"]) is not bool or type(value["channel_closing"]) is not bool: _fail()
  capture_snapshot(value["snapshot"])
  return value


def _json_object(pairs):
  result = {}
  for key, value in pairs:
    if key in result: _fail()
    result[key] = value
  return result


def _nonfinite(_value):
  _fail()


def _read(tree):
  raw = tree.read(PATH, max_bytes=FILE_LIMIT)
  if raw is None: return None
  if raw[1] != 0o600: _fail()
  return _record(json.loads(raw[0], object_pairs_hook=_json_object, parse_constant=_nonfinite))


def _bindings(manifest, installed):
  """与既有selection相同的公开ID/scope投影；不读资源正文或SDK缓存。"""
  expected = {kind: {} for kind in (*KINDS, "roles")}
  capabilities = {manifest["plugin_capabilities"][name]["capability_id"] for name in manifest["plugins"]}
  bootstrap = {manifest["plugin_capabilities"][name]["capability_id"] for name in manifest.get("bootstrap_plugins", [])}
  for kind in expected:
    for name in manifest["resource_ids"][kind]:
      if kind != "extensions" or not manifest.get("bootstrap"): expected[kind][name] = "instance"
    for row in installed["resources"].get(kind, []):
      if row["capability_id"] in capabilities and (kind != "extensions" or not manifest.get("bootstrap") or row["capability_id"] in bootstrap):
        if row["id"] in expected[kind]: _fail()
        expected[kind][row["id"]] = "runtime"
  for row in manifest.get("project_resources", []):
    if not manifest["options"]["discovery"].get("project_resources"): _fail()
    kind, name = row["kind"], row.get("override", row["id"])
    if kind not in expected: _fail()
    if name in expected[kind] and (kind != "roles" or not row.get("override") or name.startswith("task-keeper-")): _fail()
    expected[kind][name] = "project"
  for row in manifest.get("external_skills", []):
    if row["id"] in expected["skills"]: _fail()
    expected["skills"][row["id"]] = "external"
  inline = ["rotom-command-boundary"]
  if manifest.get("native_mcp"): inline.append("rotom-native-mcp")
  if manifest["profile_id"] == "pi-full" and manifest["options"].get("task_keeper", {}).get("enabled"): inline.append("rotom-task-keeper")
  return expected, inline


class ResourceObservations:
  def __init__(self, host):
    self.host = host

  def publish(self, principal, request):
    try:
      if type(principal) is not Principal or principal.role != "manager" or principal.lease_id is None: _fail()
      if type(request) is not dict or type(request.get("kind")) is not str or request.get("kind") not in ("loaded", "retired"): _fail()
      kind = request["kind"]
      _closed(request, {"kind", "session_id", "generation", *(("snapshot",) if kind == "loaded" else ())})
      _id(request["session_id"], True); _generation(request["generation"])
      host = self.host
      lease = host.store.read(principal.lease_id)
      if (lease["lease_id"] != principal.lease_id or lease["kind"] != "host"
          or any(lease[key] != host.store.owner[key] for key in OWNER_KEYS)
          or lease["grant_generation"] != principal.grant_generation): _fail()
      if kind == "loaded" and (host.service.closing or lease["state"] != "running" or not lease["spawn_committed"]
          or host.processes.observe(lease["process_identity"]) != "alive"): _fail()
      captured = capture_snapshot(request["snapshot"]) if kind == "loaded" else None
      if captured is not None:
        manifest = host.manifest()
        if (captured["profileId"] != manifest["profile_id"] or captured["lockIdentity"] != host.config["lock_identity"]
            or captured["sliceIdentity"] != host.config["slice_identity"] or captured["runtimeIdentity"] != host.runtime_root.name): _fail()
        with Tree(host.runtime_root) as runtime:
          raw = runtime.read("runtime/profile.json", max_bytes=8 * 1024 * 1024)
        if raw is None: _fail()
        installed = json.loads(raw[0])
        if installed["schema_version"] != 2 or installed["profile_id"] != manifest["profile_id"]: _fail()
        expected, inline = _bindings(manifest, installed); observation = captured["observation"]
        for group in KINDS:
          if {row["id"]: row["scope"] for row in observation["resources"][group]} != expected[group]: _fail()
        if ({row["id"]: row["scope"] for row in observation["selectedRoles"]} != expected["roles"]
            or sorted(observation["inlineExtensions"]) != sorted(inline)): _fail()
      with Tree(host.root) as tree:
        old = _read(tree)
        same_manager = old is not None and old["manager_activation_id"] == host.store.owner["manager_activation_id"] and old["manager_lease_id"] == principal.lease_id
        if kind == "retired":
          if not same_manager or old["generation"] != request["generation"] or old["session_id"] != request["session_id"]: _fail()
          if not old["retired"]:
            old["retired"] = True; tree.write_state(PATH, json_bytes(old))
        else:
          if same_manager and request["generation"] <= old["generation"]:
            if (request["generation"] != old["generation"] or request["session_id"] != old["session_id"]
                or old["retired"] or old["channel_closing"] or captured != old["snapshot"]): _fail()
          else:
            value = {"schema_version": 1, "instance_id": host.store.owner["instance_id"],
              "manager_activation_id": host.store.owner["manager_activation_id"], "manager_lease_id": principal.lease_id,
              "manager_generation": principal.grant_generation, "session_id": request["session_id"], "generation": request["generation"],
              "manifest_digest": host.config["manifest_digest"], "retired": False, "channel_closing": False, "snapshot": captured}
            _record(value); tree.write_state(PATH, json_bytes(value))
      return {"schema_version": 1, "accepted": True, "generation": request["generation"]}
    except (KeyError, TypeError, ValueError, OSError, Conflict, PathError):
      _fail()

  def close(self):
    # 只标观察通道关闭；它不证明进程终止、任务完成或释放Writer。
    with Tree(self.host.root) as tree:
      value = _read(tree)
      if value is not None and value["manager_activation_id"] == self.host.store.owner["manager_activation_id"]:
        value["channel_closing"] = True; tree.write_state(PATH, json_bytes(value))


def read_resource_observation(state_root, *, context=None):
  result = {"status": "unavailable", "reason_code": "RESOURCE_OBSERVATION_UNAVAILABLE",
    "evidence": "authenticated-manager-reported", "liveness": "last-observed-not-live",
    "config_identity_evidence": "runtime-observed", "source_hold": "not-qualified", "isolation": "unverified"}
  if context is None: return result
  try:
    _closed(context, {"profile_id", "lock_identity", "slice_identity", "runtime_identity", "manifest_digest"})
    for key in ("lock_identity", "slice_identity", "runtime_identity", "manifest_digest"): _sha(context[key])
    if context["profile_id"] not in ("pi-base", "pi-full"): _fail()
    with Tree(state_root) as tree: value = _read(tree)
    if value is None: return result
    snapshot = value["snapshot"]
    matches = all(snapshot[key] == context[name] for key, name in (
      ("profileId", "profile_id"), ("lockIdentity", "lock_identity"), ("sliceIdentity", "slice_identity"), ("runtimeIdentity", "runtime_identity")))
    stale = not matches or value["manifest_digest"] != context["manifest_digest"] or value["retired"] or value["channel_closing"]
    result.update(status="stale" if stale else "last-observed", reason_code="RESOURCE_OBSERVATION_STALE" if stale else "RESOURCE_OBSERVATION_REPORTED",
      session_id=value["session_id"], generation=value["generation"], snapshot=snapshot)
    # 只说明固定managed loader的显式选择契约；不把缺失某ID当全文件系统扫描证据。
    rows = snapshot["observation"]["resources"]
    result["selection_boundary"] = {"evidence": "last-observed-selection-contract",
      "implicit_global": "disabled-by-managed-loader", "implicit_ancestor": "disabled-by-managed-loader",
      "project": "explicit-selected-only", "package": "explicit-selected-only",
      "loaded_package_resources": [{"kind": kind, "id": row["id"]} for kind in KINDS for row in rows[kind] if row["scope"] == "runtime"],
      "loaded_project_resources": [{"kind": kind, "id": row["id"]} for kind in KINDS for row in rows[kind] if row["scope"] == "project"],
      "filesystem_scan": "not-performed", "isolation": "unverified"}
  except (KeyError, TypeError, ValueError, OSError, Conflict, PathError):
    pass
  return result
