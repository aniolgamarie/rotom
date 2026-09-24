"""委托执行边界与冻结授权；原生沙箱授权不冒充逐工具拦截。"""

from copy import deepcopy
import json
from pathlib import Path

from .activity import digest
from .deployment import json_bytes
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


def codex_api_base_url(value):
  from urllib.parse import urlsplit
  try:
    if not isinstance(value, str) or not value or any(ord(char) <= 32 for char in value) or "\\" in value: raise ValueError()
    parsed = urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.port == 0
        or parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "::1")):
      raise ValueError()
  except ValueError: raise ConfigError("delegate-codex-api-base-url") from None
  return value


def boundary(backend):
  if backend not in ("pi", "codex"): raise ConfigError("delegate-backend")
  return "native-sandbox" if backend == "codex" else "agentcfg-tools"


def native_execution(value):
  closed(value, ("allow_shell", "tool_network"), ("web_search",))
  if type(value["allow_shell"]) is not bool or value["tool_network"] != "none" or value.get("web_search", "disabled") not in ("disabled", "cached", "live"):
    raise ConfigError("delegate-native-execution-policy")
  return deepcopy(value)


def execution_policy(manifest, backend):
  value = {"boundary": boundary(backend), "file_policy": deepcopy(manifest["permission_policy"])}
  if backend == "codex":
    bound = manifest["options"].get("model_delegate", {}).get("codex", {})
    selected = bound.get("native_execution")
    if selected is None: raise ConfigError("delegate-native-execution-required")
    value["native_execution"] = native_execution(selected)
    from .pi_codex_admission import POLICY_ID
    value["configuration_admission"] = POLICY_ID
    from .pi_native_roots import snapshot_root_limits
    value["root_limits"] = snapshot_root_limits(manifest["options"])
    if "api_base_url" in bound: value["api_base_url"] = codex_api_base_url(bound["api_base_url"])
  return value


def validate_policy_binding(value):
  from .pi_catalog import validate_policy
  request, policy = value["request"], value["execution_policy"]
  closed(policy, ("boundary", "file_policy"), ("native_execution", "root_limits", "configuration_admission", "api_base_url"))
  validate_policy(policy["file_policy"])
  if (request["execution_boundary"] != boundary(request["backend"]) or policy["boundary"] != request["execution_boundary"]
      or digest(policy) != request["execution_policy_digest"] or digest(policy["file_policy"]) != request["policy_digest"]):
    raise Conflict("DELEGATE_EXECUTION_POLICY_MISMATCH")
  if request["backend"] == "codex":
    from .pi_codex_admission import POLICY_ID
    if policy.get("configuration_admission") != POLICY_ID: raise Conflict("DELEGATE_CONFIGURATION_POLICY_MISMATCH")
    from .pi_native_roots import validate_root_limits
    native_execution(policy.get("native_execution", {}))
    validate_root_limits(policy.get("root_limits", {}))
    if "api_base_url" in policy: codex_api_base_url(policy["api_base_url"])
  elif any(key in policy for key in ("native_execution", "root_limits", "configuration_admission", "api_base_url")): raise Conflict("DELEGATE_EXECUTION_POLICY_MISMATCH")
  return policy


def record_native_authorization(root, request, permissions):
  if request["execution_boundary"] != "native-sandbox": raise Conflict("DELEGATE_EXECUTION_BOUNDARY")
  value = {"schema_version": 1, **{key: request[key] for key in
    ("run_id", "lease_id", "request_digest", "runtime_identity", "execution_policy_digest", "grant_generation", "cwd")},
    "permissions": deepcopy(permissions)}
  value["authorization_digest"] = digest(value)
  with Tree(root) as tree: tree.write_immutable("native-authorizations/" + request["run_id"] + ".json", json_bytes(value))
  return value


def verify_execution_policy(root, request):
  """由控制者保存的授权验证，不从CLI结果、自报工具事件或提示中推断。"""
  try:
    with Tree(root) as tree:
      raw = tree.read("inputs/" + request["run_id"] + ".json")
      if raw is None or raw[1] != 0o600: raise ValueError()
      value = json.loads(raw[0])
      if value["request"] != request or value["definition_digest"] != digest({key: item for key, item in value.items() if key != "definition_digest"}):
        raise ValueError()
      validate_policy_binding(value)
      if request["execution_boundary"] == "native-sandbox":
        raw = tree.read("native-authorizations/" + request["run_id"] + ".json")
        if raw is None or raw[1] != 0o600: raise ValueError()
        proof = json.loads(raw[0])
        fields = ("run_id", "lease_id", "request_digest", "runtime_identity", "execution_policy_digest", "grant_generation", "cwd")
        closed(proof, ("schema_version", *fields, "permissions", "authorization_digest"))
        if (proof["schema_version"] != 1 or any(proof[key] != request[key] for key in fields)
            or proof["authorization_digest"] != digest({key: item for key, item in proof.items() if key != "authorization_digest"})
            or not isinstance(proof["permissions"], dict) or proof["permissions"].get(":root") != "deny"):
          raise ValueError()
    return {"execution_boundary": request["execution_boundary"], "execution_policy_digest": request["execution_policy_digest"], "execution_policy_verified": True}
  except (ValueError, TypeError, KeyError, ConfigError):
    raise Conflict("DELEGATE_EXECUTION_POLICY_UNVERIFIED") from None
