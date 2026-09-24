"""升级差异只比较受管声明，不读取或改写原生账号、会话与数据库。"""
import base64
import json

from .activity import digest
from .schema import ConfigError


def manifest_from_state(current):
  if not current: return None
  for item in current["items"].values():
    if item["path"] == "pi-home/agentcfg-manifest.json" and not item["selector"]:
      try:
        value = json.loads(base64.b64decode(item["desired"]["value"]["bytes"], validate=True))
      except (ValueError, KeyError, TypeError): raise ConfigError("pi-upgrade-manifest") from None
      if value.get("schema_version") != 1: raise ConfigError("pi-upgrade-manifest-version")
      return value
  return None


def compare_upgrade(previous, current, *, previous_runtime, current_runtime):
  categories = {
    "roles": lambda value: {key: value.get(key) for key in ("role_bindings", "model_bindings", "allowed_models")},
    "policy": lambda value: {"policy": value.get("permission_policy"), "limits": value.get("options", {}).get("permissions")},
    "routes": lambda value: value.get("options", {}).get("network"),
    "resources": lambda value: {key: value.get(key) for key in ("resources", "resource_ids", "plugins", "project_resources", "external_skills")},
  }
  changed = [key for key, project in categories.items() if previous is None or digest(project(previous)) != digest(project(current))]
  if previous_runtime != current_runtime: changed.insert(0, "dependencies")
  return {"changed_categories": changed, "previous_runtime_identity": previous_runtime, "current_runtime_identity": current_runtime,
    "previous_runtime_lookup": "saved-launch-contract", "evidence": "stale" if changed else "identity-check-required",
    "resume": "native-schema-check-required", "native_data": "preserved", "automatic_data_migration": False,
    "accepted_data_versions": {"pi_session": 3, "task_keeper_store": 3}, "rollback_boundary": "configuration-only"}


def upgrade_diagnostics(projection):
  current = projection["current"]
  previous = manifest_from_state(current)
  desired = next((item for item in projection["candidate"].artifacts if item.target.path == "pi-home/agentcfg-manifest.json"), None)
  if desired is None: raise ConfigError("pi-upgrade-candidate-manifest")
  result = compare_upgrade(previous, json.loads(desired.content),
    previous_runtime=(current["launch"].get("runtime_identity", current["launch"]["lock_identity"]) if current else None),
    current_runtime=projection["runtime_identity"])
  if current and current.get("generation") != projection["candidate"].generation and not result["changed_categories"]:
    result["changed_categories"].append("configuration")
    result["evidence"] = "stale"
  return result
