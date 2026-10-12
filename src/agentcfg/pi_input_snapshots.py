"""语义输入的封闭只读投影；快照不提供权限或预算授予。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from .activity import digest
from .pi_guarded_files import root_identity
from .schema import ConfigError
from .storage import Conflict

MAX_RECORDS = 10000
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024


def _path(value):
  if (type(value) is not str or not value or len(value.encode()) > 4096 or value.startswith("/") or "\\" in value
      or any(part in ("", ".", "..") for part in value.split("/")) or re.search("[\x00-\x1f\x7f]", value)):
    raise ConfigError("INPUT_SNAPSHOT_PATH")
  return value


def scope_policy(value):
  if type(value) is not dict or set(value) - {"artifact_exclusions", "explicit_inputs"}:
    raise ConfigError("INPUT_SNAPSHOT_SCOPE")
  result = {"artifact_exclusions": [], "explicit_inputs": []}
  for name in result:
    rows = value.get(name, [])
    if type(rows) is not list or len(rows) > MAX_RECORDS:
      raise ConfigError("INPUT_SNAPSHOT_SCOPE")
    for row in rows:
      if name == "explicit_inputs":
        result[name].append(_path(row))
      else:
        if type(row) is not dict or set(row) != {"relative_path", "kind"} or row["kind"] not in ("file", "directory"):
          raise ConfigError("INPUT_SNAPSHOT_SCOPE")
        result[name].append({"relative_path": _path(row["relative_path"]), "kind": row["kind"]})
    keys = [row if type(row) is str else row["relative_path"] for row in result[name]]
    if len(set(keys)) != len(keys): raise ConfigError("INPUT_SNAPSHOT_DUPLICATE")
    result[name].sort(key=lambda row: (row if type(row) is str else row["relative_path"]).encode())
  if sum(map(len, result.values())) > MAX_RECORDS: raise ConfigError("INPUT_SNAPSHOT_LIMIT")
  semantic_digest(result)
  return result


def host_scope(host, manifest, *, source, candidate, creating):
  """只由原 Host 当前来源派生；绝不消费模型的名单/排除/凭据值。"""
  if digest(manifest) != host.config["manifest_digest"]:
    raise Conflict("ADMISSION_STALE")
  source, candidate = Path(source), Path(candidate)
  root = source if creating else candidate
  if not creating: host.store.workspaces.identify(root)
  policy = scope_policy(manifest["options"].get("input_snapshot", {}))
  protected = []
  outside = [{"root_ref": "managed-state", "category": "managed-artifact"}]
  def classify(path, reference, *, private_ancestor=False):
    path = Path(path).absolute()
    if path == root or root.is_relative_to(path):
      instance = Path(host.config["instance_root"]) if "instance_root" in host.config else None
      state = Path(host.config["state_root"]) if "state_root" in host.config else None
      # 只允许原配置的精确私有祖先包含正常受管candidate；creating source绝不豁免。
      if (private_ancestor and not creating and path != root and path in (instance, state) and instance is not None
          and candidate.parent == instance / "pi-home/task-keeper/worktrees"):
        # 类别描述私有域在固定candidate外的其余部分；不授祖先整根读取权。
        if not any(row["root_ref"] == reference for row in outside):
          outside.append({"root_ref": reference, "category": "protected-root"})
        return
      raise Conflict("INPUT_SNAPSHOT_ROOT_DENIED")
    if path.is_relative_to(root):
      name = path.relative_to(root).as_posix()
      if not any(row["relative_path"] == name for row in protected):
        protected.append({"relative_path": name, "reference": reference, "category": "protected-file", "owner": None, "provider": None})
    elif not any(row["root_ref"] == reference for row in outside):
      outside.append({"root_ref": reference, "category": "protected-root"})
  for index, path in enumerate(host.config.get("protected_roots", [])):
    classify(path, "private-root:" + str(index), private_ancestor=True)
  declarations = manifest["options"]["paths"]["roots"]
  for name in manifest["options"].get("permissions", {}).get("denied_roots", []):
    if name == "project" or name == manifest["options"]["task_keeper"]["project_root"]:
      raise Conflict("INPUT_SNAPSHOT_ROOT_DENIED")
    classify(declarations[name]["path"], "root:" + name)
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    base = root if rule["root_ref"] == "project" else Path(declarations[rule["root_ref"]]["path"])
    path = base / rule["relative_path"]
    if path == root or root.is_relative_to(path): raise Conflict("INPUT_SNAPSHOT_ROOT_DENIED")
    classify(path, "file:" + rule["root_ref"] + ":" + rule["relative_path"])
  protected.sort(key=lambda row: row["relative_path"].encode())
  outside.sort(key=lambda row: row["root_ref"].encode())
  result = {"schema_version": 1, "source_root": str(source), "candidate_root": str(candidate),
    "root_identity": None if creating else root_identity(candidate), "creating": creating,
    "policy": policy, "protected_inputs": protected, "outside_exclusions": outside}
  if len(protected) + len(outside) + sum(map(len, policy.values())) > MAX_RECORDS: raise ConfigError("INPUT_SNAPSHOT_LIMIT")
  semantic_digest(result)
  return result


def canonical(value):
  """UTF8字节键顺序；不用Python/JS各自默认Unicode排序作跨语言假设。"""
  if value is None or type(value) in (str, bool): return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
  if type(value) in (int, float) and abs(value) <= 9007199254740991 and math.isfinite(value) and value == int(value): return str(int(value))
  if type(value) is list: return "[" + ",".join(canonical(row) for row in value) + "]"
  if type(value) is dict and all(type(key) is str for key in value):
    return "{" + ",".join(canonical(key) + ":" + canonical(value[key]) for key in sorted(value, key=lambda key: key.encode())) + "}"
  raise ConfigError("INPUT_SNAPSHOT_VALUE")


def semantic_digest(value):
  try: raw = canonical(value).encode()
  except (UnicodeError, RecursionError): raise ConfigError("INPUT_SNAPSHOT_VALUE") from None
  if len(raw) > MAX_METADATA_BYTES: raise ConfigError("INPUT_SNAPSHOT_LIMIT")
  return hashlib.sha256(raw).hexdigest()


def _closed(value, fields):
  if type(value) is not dict or set(value) != set(fields): raise ConfigError("INPUT_SNAPSHOT_SHAPE")


def validate_semantic_source(value):
  _closed(value, ("schema_version", "workspace_identity", "scope", "files", "sensitive_inputs"))
  if type(value["schema_version"]) not in (int, float) or value["schema_version"] != 1: raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  _sha(value["workspace_identity"])
  scope = value["scope"];_closed(scope, ("relative_roots", "explicit_inputs", "artifact_exclusions", "outside_exclusions"))
  if scope["relative_roots"] != ["."]: raise ConfigError("INPUT_SNAPSHOT_SCOPE")
  scope_policy({name: scope[name] for name in ("explicit_inputs", "artifact_exclusions")})
  for row in scope["outside_exclusions"]:
    _closed(row, ("root_ref", "category"))
    if row["category"] not in ("protected-root", "managed-artifact") or type(row["root_ref"]) is not str: raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  if any(type(value[key]) is not list for key in ("files", "sensitive_inputs")): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  keys = []
  for row in value["files"]:
    if type(row) is not dict: raise ConfigError("INPUT_SNAPSHOT_SHAPE")
    kind = row.get("kind");_closed(row, ("relative_path", "kind", *( ("sha256", "executable") if kind == "file" else ("target",) if kind == "symlink" else ())))
    keys.append(_path(row["relative_path"]))
    if kind == "file" and (type(row["sha256"]) is not str or not re.fullmatch("[a-f0-9]{64}", row["sha256"]) or type(row["executable"]) not in (int, float) or not math.isfinite(row["executable"]) or row["executable"] != int(row["executable"]) or not 0 <= row["executable"] <= 511): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
    if kind == "symlink": _path(row["target"])
    elif kind not in ("file", "missing"): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  if len(set(keys)) != len(keys) or keys != sorted(keys, key=lambda key: key.encode()): raise ConfigError("INPUT_SNAPSHOT_DUPLICATE")
  secret_keys = []
  for row in value["sensitive_inputs"]:
    _closed(row, ("reference", "category", "owner", "provider", "actor", "state"))
    if (type(row["reference"]) is not str or row["actor"] not in ("source", "candidate") or row["state"] not in ("present", "missing", "unreadable")
        or row["category"] not in ("credential-file", "protected-file", "credential-environment") or any(row[x] is not None and type(row[x]) is not str for x in ("owner", "provider"))): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
    secret_keys.append(row["actor"] + ":" + row["reference"])
  for row in value["files"]:
    if row["kind"] == "symlink" and not any(target["kind"] == "file" and target["relative_path"] == row["target"] for target in value["files"]): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  if len(set(secret_keys)) != len(secret_keys) or secret_keys != sorted(secret_keys, key=lambda key: key.encode()): raise ConfigError("INPUT_SNAPSHOT_DUPLICATE")
  if sum(len(value[key]) for key in ("files", "sensitive_inputs")) + sum(len(scope[key]) for key in ("explicit_inputs", "artifact_exclusions", "outside_exclusions")) > MAX_RECORDS: raise ConfigError("INPUT_SNAPSHOT_LIMIT")
  semantic_digest(value)
  return deepcopy(value)

IDENTITY_FIELDS = ("config_identity", "effective_config_digest", "host_manifest_identity", "policy_digest", "project_constraints_digest", "resources_digest", "taskkeeper_policy_digest", "runtime_identity", "lock_identity", "slice_identity", "taskkeeper_runtime_identity", "capability_provider_digest", "model_routes", "checker_contracts", "local_acceptance_digest", "environment")


def _text(value):
  if type(value) is not str or not value or len(value.encode()) > 4096 or re.search("[\x00-\x1f\x7f]", value):
    raise ConfigError("INPUT_SNAPSHOT_SHAPE")


def _sha(value):
  if type(value) is not str or not re.fullmatch("[a-f0-9]{64}", value): raise ConfigError("INPUT_SNAPSHOT_SHAPE")


def _ordered(rows, key):
  if type(rows) is not list or len(rows) > MAX_RECORDS: raise ConfigError("INPUT_SNAPSHOT_LIMIT")
  values = [key(row) for row in rows]
  if len(set(values)) != len(values) or values != sorted(values, key=lambda value: value.encode()): raise ConfigError("INPUT_SNAPSHOT_DUPLICATE")


def compile_input_snapshot(source, identities):
  source = validate_semantic_source(source)
  _closed(identities, IDENTITY_FIELDS)
  for key in set(IDENTITY_FIELDS) - {"model_routes", "checker_contracts", "environment"}: _sha(identities[key])
  for row in identities["checker_contracts"]:
    _closed(row, ("check_id", "contract_digest"));_text(row["check_id"]);_sha(row["contract_digest"])
  _ordered(identities["checker_contracts"], lambda row: row["check_id"])
  for row in identities["model_routes"]:
    _closed(row, ("role_id", "provider_id", "model_id", "public_configuration_digest", "auth"))
    for key in ("role_id", "provider_id", "model_id"): _text(row[key])
    _sha(row["public_configuration_digest"]);_closed(row["auth"], ("kind", "owner", "credential_ref"))
    if row["auth"]["kind"] not in ("api-key", "oauth"): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
    _text(row["auth"]["owner"])
    ref = row["auth"]["credential_ref"]
    if ref is not None and (type(ref) is not str or not re.fullmatch("secret:[A-Za-z0-9_.:-]+", ref)): raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  _ordered(identities["model_routes"], lambda row: row["role_id"])
  env = identities["environment"]
  _closed(env, ("platform", "architecture", "node_version", "sdk_version", "declared_nonsecret_variables"))
  for key in ("platform", "architecture", "node_version", "sdk_version"): _text(env[key])
  if env["declared_nonsecret_variables"] != [{"name": "LANG", "value": "C.UTF-8"}]: raise ConfigError("INPUT_SNAPSHOT_SHAPE")
  body = {"schema_version": 1, "source": source, "identities": deepcopy(identities)}
  result = {**body, "digest": semantic_digest(body)}
  semantic_digest(result)
  return result
