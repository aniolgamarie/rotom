"""现代profile离线选择计划；不读来源、不查账户，不证明实际加载或隔离。"""
import re

from .pi_evidence import IDENTITY_FIELDS
from .schema import ConfigError


_REGISTRIES = {"roles": "profile", "skills": "shared-skills", "prompts": "agent-resources",
  "themes": "agent-resources", "extensions": "agent-resources", "plugins": "agent-plugins"}


def _invalid():
  raise ConfigError("pi-modern-diagnostic-plan") from None


def _closed(value, keys):
  if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != set(keys):
    _invalid()


def modern_profile_plan(*, profile_id, identity, selections, discovery):
  """只投影受信解析者传入的缩小数据；通用host证据不得升级本计划。"""
  if type(profile_id) is not str or profile_id not in ("pi-base", "pi-full"):
    _invalid()
  _closed(identity, IDENTITY_FIELDS)
  for value in identity.values():
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
      _invalid()
  _closed(selections, _REGISTRIES)
  source_count = 0
  source_bytes = 0
  for kind, values in selections.items():
    if type(values) is not list or len(values) > 4096:
      _invalid()
    for value in values:
      if type(value) is not str or not value or value in (".", ".."):
        _invalid()
      if any(char in "/\\" or ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        _invalid()
      if kind not in ("roles", "skills") and re.fullmatch("[a-z][a-z0-9_-]{0,63}", value) is None:
        _invalid()
      length = len(value.encode("utf-8"))
      if length > 512:
        _invalid()
      source_bytes += length
    source_count += len(values)
    if source_count > 4096 or source_bytes > 65536 or len(set(values)) != len(values):
      _invalid()
  _closed(discovery, ("project_resources", "external_skills_count"))
  if (type(discovery["project_resources"]) is not bool
      or type(discovery["external_skills_count"]) is not int
      or not 0 <= discovery["external_skills_count"] <= 4096):
    _invalid()
  return {"schema_version": 1, "mode": "offline-plan", "profile_id": profile_id,
    "diagnostic_identity": dict(identity),
    "selected_sources": [{"kind": kind, "id": name, "registry": _REGISTRIES[kind],
      "selection": "selected", "load_evidence": "not-run"}
      for kind in sorted(selections) for name in sorted(selections[kind])],
    "discovery_plan": {"scope": "assets-only",
      "global": {"planned": "explicit-selection-only", "observed": "not-run"},
      "ancestor": {"planned": "disabled", "observed": "not-run"},
      "project": {"planned": "enabled" if discovery["project_resources"] else "disabled", "observed": "not-run"},
      "package": {"planned": "explicit-selection-only", "observed": "not-run"},
      "external_skills_count": discovery["external_skills_count"]},
    "permission_isolation": {"status": "not-run", "complete_coverage": False,
      "unverified_entrypoints": ["file", "model-bash", "user-bash", "mcp", "extension", "worker", "service"]}}
