"""严格目录与组合，不从测试替身推导原生支持。"""

from copy import deepcopy
import pytest

from agentcfg.pi_catalog import read_schema, select_capabilities, validate, validate_catalog, validate_policy, validate_resources
from agentcfg.schema import ConfigError, _strict_schema


def catalog():
  item = {"id": "ordinary", "kind": "plugin", "source_id": "local", "entrypoints": [],
    "requires": [], "conflicts": [], "control_domain": "test", "supported_engines": ["node"], "evidence_cases": ["V01"]}
  return {"schema_version": 1, "capabilities": [item], "sources": {"local": {"kind": "local", "license_files": []}}}


def test_catalog_detects_missing_duplicate_and_cyclic_dependencies():
  valid = catalog()
  assert list(validate_catalog(valid)) == ["ordinary"]
  for mutation in ("missing", "cycle", "duplicate"):
    value = deepcopy(valid)
    if mutation == "missing":
      value["capabilities"][0]["requires"] = ["absent"]
    elif mutation == "cycle":
      value["capabilities"][0]["requires"] = ["ordinary"]
    else:
      value["capabilities"].append(deepcopy(value["capabilities"][0]))
    with pytest.raises(ConfigError):
      validate_catalog(value)
  with pytest.raises(ConfigError):
    select_capabilities(valid, ["ordinary"], "bun")


def test_adapter_documents_use_framework_supported_schema_subset():
  for kind in ("agent", "options", "resources"):
    _strict_schema(read_schema(kind))


def test_unknown_options_and_zero_limits_are_rejected_without_leaks():
  validate("options", {"model_delegate": {"enabled": False, "backends": []}})
  for options in ({"raw_config": "synthetic-private"}, {"task_keeper": {"limits": {"model_requests": 0}}}):
    with pytest.raises(ConfigError) as caught:
      validate("options", options)
    assert "synthetic-private" not in str(caught.value)
    assert caught.value.__context__ is None


def test_policy_union_and_duplicate_rule_ids_are_closed():
  rule = {"id": "read", "kind": "file", "effect": "allow", "tool_ids": ["tk_read"],
    "operations": ["read"], "root_ref": "project", "relative_path": ".", "match": "subtree"}
  policy = {"schema_version": 1, "default": "deny", "rules": [rule]}
  validate_policy(policy)
  for invalid in ({**rule, "command_ref": "tool:editor"}, {**rule, "match": "regex"},
      {**rule, "operations": ["execute"]}, {**rule, "relative_path": "../private"}):
    with pytest.raises(ConfigError):
      validate_policy({**policy, "rules": [invalid]})
  with pytest.raises(ConfigError):
    validate_policy({**policy, "rules": [rule, {**rule, "relative_path": "src"}]})


def test_roles_require_model_binding_and_nonroles_reject_it():
  with pytest.raises(ConfigError):
    validate_resources({"reader": {"kind": "role", "path": "roles/reader.md", "scope": "global"}})
  with pytest.raises(ConfigError):
    validate_resources({"theme": {"kind": "theme", "path": "themes/dark.json", "scope": "global", "model_role": "main"}})


def test_compiled_schema_reloads_changed_content_and_cannot_be_mutated_through_projection(tmp_path, monkeypatch):
  import json
  from agentcfg import pi_catalog
  from agentcfg.schema import ConfigError
  monkeypatch.setattr(pi_catalog, "SCHEMAS", tmp_path)
  path = tmp_path / "process-identity.schema.json"
  path.write_text(json.dumps({"type": "object", "properties": {"value": {"const": "first"}}, "required": ["value"], "additionalProperties": False}))
  pi_catalog.validate("process-identity", {"value": "first"})
  projection = pi_catalog.read_schema("process-identity")
  projection["properties"]["value"]["const"] = "injected"
  with pytest.raises(ConfigError): pi_catalog.validate("process-identity", {"value": "injected"})
  path.write_text(json.dumps({"type": "object", "properties": {"value": {"const": "second"}}, "required": ["value"], "additionalProperties": False}))
  with pytest.raises(ConfigError): pi_catalog.validate("process-identity", {"value": "first"})
  pi_catalog.validate("process-identity", {"value": "second"})
  path.unlink()
  with pytest.raises(ConfigError): pi_catalog.validate("process-identity", {"value": "second"})
