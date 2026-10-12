"""纯数据计划与真实离线resolver组合；不执行SDK、认证或服务。"""
from copy import deepcopy
import json

import pytest

from agentcfg.pi_modern_diagnostics import modern_profile_plan
from agentcfg.pi_evidence import IDENTITY_FIELDS
from agentcfg.schema import ConfigError


def inputs():
  return {"profile_id": "pi-base", "identity": {key: "a" * 64 for key in IDENTITY_FIELDS},
    "selections": {"roles": ["main"], "skills": ["cpp-database-kernel"],
      "prompts": ["ordinary-plan"], "themes": [], "extensions": [], "plugins": []},
    "discovery": {"project_resources": False, "external_skills_count": 0}}


def test_plan_is_an_independent_selection_plan_with_no_execution_claims():
  source = inputs(); before = deepcopy(source)
  plan = modern_profile_plan(**source)
  assert source == before
  assert plan["diagnostic_identity"] == source["identity"]
  assert "configuration_identity" not in plan
  assert all(row["load_evidence"] == "not-run" for row in plan["selected_sources"])
  assert [(row["kind"], row["id"]) for row in plan["selected_sources"]] == sorted(
    (row["kind"], row["id"]) for row in plan["selected_sources"])
  assert plan["permission_isolation"]["complete_coverage"] is False
  assert set(plan["permission_isolation"]["unverified_entrypoints"]) == {
    "file", "model-bash", "user-bash", "mcp", "extension", "worker", "service"}
  plan["diagnostic_identity"]["lock_digest"] = "b" * 64
  plan["selected_sources"][0]["id"] = "changed"
  assert source == before and modern_profile_plan(**source) != plan


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_discovery_is_assets_only_and_never_claims_observation(profile):
  value = inputs(); value["profile_id"] = profile
  value["discovery"] = {"project_resources": True, "external_skills_count": 2}
  plan = modern_profile_plan(**value)["discovery_plan"]
  assert plan["scope"] == "assets-only"
  assert plan["global"]["planned"] == plan["package"]["planned"] == "explicit-selection-only"
  assert plan["ancestor"]["planned"] == "disabled" and plan["project"]["planned"] == "enabled"
  assert plan["external_skills_count"] == 2
  assert all(plan[k]["observed"] == "not-run" for k in ("global", "package", "ancestor", "project"))


class DictSubclass(dict):
  pass


class ListSubclass(list):
  pass


class StringSubclass(str):
  pass


@pytest.mark.parametrize("location,value", [
  ("profile_id", "legacy"), ("profile_id", StringSubclass("pi-base")),
  ("identity", DictSubclass({key: "a" * 64 for key in IDENTITY_FIELDS})),
  ("identity", {}), ("identity.lock_digest", "A" * 64), ("identity.lock_digest", True),
  ("identity.secret", "SYNTHETIC_PRIVATE"), ("selections", []),
  ("selections", DictSubclass(inputs()["selections"])), ("selections.roles", ListSubclass(["main"])),
  ("selections.roles", [StringSubclass("main")]), ("selections.roles", ["main", "main"]),
  ("selections.roles", [True]), ("selections.roles", ["/private/token"]),
  ("selections.roles", ["https://private.invalid"]), ("selections.roles", [".."]),
  ("selections.roles", ["bad\nname"]), ("selections.roles", ["x" * 513]),
  ("selections.roles", ["main"] * 4097), ("selections.auth", []),
  ("discovery", DictSubclass(inputs()["discovery"])), ("discovery.project_resources", 1),
  ("discovery.external_skills_count", True), ("discovery.external_skills_count", -1),
  ("discovery.external_skills_count", 4097), ("discovery.paths", ["SYNTHETIC_PRIVATE"]),
])
def test_invalid_plan_data_fails_without_raw_values(location, value):
  args = inputs(); parts = location.split(".")
  if len(parts) == 1: args[location] = value
  else: args[parts[0]][parts[1]] = value
  with pytest.raises(ConfigError) as error: modern_profile_plan(**args)
  assert error.value.code == "pi-modern-diagnostic-plan"
  assert "SYNTHETIC_PRIVATE" not in str(error.value)


def modern_projection(tmp_path):
  from test_pi_doctor import projection
  from test_pi_profile_projection import resolved
  value = projection(tmp_path); value["data"] = resolved()
  return value


def test_actual_base_resolver_only_lists_selected_sources_without_full_import(tmp_path, monkeypatch):
  import builtins
  from agentcfg.pi import PiAdapter
  from test_pi_adapter import ROOT
  value = modern_projection(tmp_path)
  from agentcfg import pi_diagnostics
  calls = []
  def fixed_identity(projection):
    calls.append(projection)
    return {key: "a" * 64 for key in IDENTITY_FIELDS}
  # 原身份计算会render并做既有配置校验；这里只毒化新计划接缝的额外Full导入。
  monkeypatch.setattr(pi_diagnostics, "diagnostic_identity", fixed_identity)
  original = builtins.__import__
  forbidden = ("pi_delegate", "pi_web", "pi_readseek", "pi_worker_files", "pi_task_keeper")
  def guarded(name, *args, **kwargs):
    assert not any(token in name for token in forbidden)
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  value["data"]["providers"]["deepseek_openai"]["credential_ref"] = "secret:SYNTHETIC_PRIVATE"
  plan = next(row for row in PiAdapter(ROOT).capability_diagnostics(value) if row["id"] == "pi-host")["profile_plan"]
  selected = {kind: {row["id"] for row in plan["selected_sources"] if row["kind"] == kind}
    for kind in ("roles", "skills", "plugins", "prompts")}
  assert selected["roles"] == {"main"}
  assert selected["plugins"] == {"colorful-footer", "pi-todo", "loop-guard"}
  assert selected["prompts"] == {"ordinary-implement", "ordinary-plan", "ordinary-review"}
  assert selected["skills"] == set(value["data"]["profile"]["skills"])
  assert "SYNTHETIC_PRIVATE" not in json.dumps(plan)
  assert len(calls) == 1


def test_legacy_diagnostic_rows_do_not_acquire_modern_plan(tmp_path):
  from test_pi_doctor import projection
  from agentcfg.pi import PiAdapter
  from test_pi_adapter import ROOT
  assert all("profile_plan" not in row for row in PiAdapter(ROOT).capability_diagnostics(projection(tmp_path)))


def test_complete_base_diagnostic_identity_does_not_import_unselected_web(tmp_path, monkeypatch):
  import builtins
  from agentcfg import pi_diagnostics
  value = modern_projection(tmp_path)
  before = deepcopy(value)
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    assert name != "pi_web" and not name.endswith(".pi_web"), "unselected web module imported"
    return original(name, *args, **kwargs)
  # 不stub身份/render；完整调用验证原配置与原生成产物的非秘密身份。
  with monkeypatch.context() as guard:
    guard.setattr(builtins, "__import__", guarded)
    identity = pi_diagnostics.diagnostic_identity(value)
    rows = pi_diagnostics.capabilities(value)
  assert set(identity) == set(IDENTITY_FIELDS)
  assert all(len(item) == 64 for item in identity.values())
  plan = next(row for row in rows if row["id"] == "pi-host")["profile_plan"]
  assert plan["diagnostic_identity"] == identity
  assert value == before
  assert plan["installed_resource_inventory"]["status"] == "not-inspected"
  assert plan["installed_resource_inventory"]["load_evidence"] == "not-run"


def test_unselected_web_configuration_keeps_original_error_without_import(tmp_path, monkeypatch):
  import builtins
  from agentcfg.pi import PiAdapter
  from test_pi_adapter import ROOT, pi_data
  value = pi_data(tmp_path)
  value["profile"]["agent_options"]["web"] = {"settings": {"autoOpenBrowser": False}}
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    assert name != "pi_web" and not name.endswith(".pi_web")
    return original(name, *args, **kwargs)
  with monkeypatch.context() as guard:
    guard.setattr(builtins, "__import__", guarded)
    with pytest.raises(ConfigError) as error: PiAdapter(ROOT).validate(value)
  assert error.value.code == "pi-web-not-selected"


def test_registry_unicode_names_and_diagnostic_byte_boundaries():
  value = inputs(); value["selections"]["skills"] = ["数据库技能"]
  value["selections"]["roles"] = ["x" * 512]
  plan = modern_profile_plan(**value)
  assert any(row["id"] == "数据库技能" for row in plan["selected_sources"])
  value["selections"]["skills"] = ["中" * 171]
  with pytest.raises(ConfigError): modern_profile_plan(**value)


@pytest.mark.parametrize("boundary", ["bytes", "count"])
def test_aggregate_selection_limits_reject_without_truncation(boundary):
  value = inputs()
  value["selections"] = {kind: [] for kind in value["selections"]}
  if boundary == "bytes":
    value["selections"]["skills"] = [str(i) + "x" * 509 for i in range(129)]
  else:
    value["selections"]["roles"] = ["r" + str(i) for i in range(2048)]
    value["selections"]["skills"] = ["s" + str(i) for i in range(2049)]
  with pytest.raises(ConfigError) as error: modern_profile_plan(**value)
  assert error.value.code == "pi-modern-diagnostic-plan"


def test_profile_role_resource_id_collision_cannot_masquerade_as_prompt(tmp_path, monkeypatch):
  from agentcfg import pi_diagnostics
  value = modern_projection(tmp_path)
  monkeypatch.setattr(pi_diagnostics, "diagnostic_identity", lambda _: inputs()["identity"])
  value["data"]["profile"]["agent_options"]["resources"]["roles"] = ["main"]
  value["data"]["adapter_documents"]["agent"]["resources"]["main"] = {
    "kind": "prompt", "path": "agents/pi/prompts/ordinary/debug.md", "scope": "global"}
  with pytest.raises(ConfigError) as error: pi_diagnostics.capabilities(value)
  assert error.value.code == "pi-modern-diagnostic-plan"


def test_actual_base_rejects_explicit_project_resource_loading():
  from test_pi_profile_projection import resolved
  from agentcfg.pi_profile_config import validate_projection
  data = resolved()
  data["profile"]["agent_options"]["discovery"]["project_resources"] = True
  with pytest.raises(ConfigError) as error:
    validate_projection(data)
  assert error.value.code == "pi-base-resource-selection"
