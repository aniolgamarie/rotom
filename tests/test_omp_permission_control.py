"""权限配置的独立契约；只用虚构 model/provider，不走部署与宿主。"""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from agentcfg.omp_settings import resolve_permission_control, NATIVE_PERMISSION_CONTROL
from agentcfg.schema import ConfigError


def configured():
  return {
    "profile": {"plugins": ["omp-permission-control"], "models": ["review-small"],
      "agent_options": {"runtime_variant": "official",
        "permission_control": {"default_mode": "smart"},
        "runtime": {"tools": {"approvalMode": "write", "approval": {
          "bash": "prompt", "permission_bash": "allow"}}}}},
    "models": {"review-small": {"provider": "fictional", "remote_id": "small"}},
    "providers": {"fictional": {"protocol": "openai-compatible", "auth_kind": "api-key"}},
    "plugins": {"omp-permission-control": {"tree_digest": "a" * 64}},
  }


def test_default_reviewer_is_dynamic_session_selection():
  data = configured()
  before = deepcopy(data)
  assert resolve_permission_control(data) == {"defaultMode": "smart", "reviewer": "session"}
  assert data == before


def test_explicit_reviewer_and_installed_only_fallback():
  data = configured()
  data["profile"]["agent_options"]["permission_control"].update(
    default_mode="manual", reviewer_model="review-small", fallback_model="local/lfm2.5-230m")
  assert resolve_permission_control(data) == {"defaultMode": "manual",
    "reviewer": {"provider": "fictional", "model": "small"},
    "fallback": {"provider": "local", "model": "lfm2.5-230m", "installedOnly": True}}


def test_remote_fallback_resolves_independently_from_session_reviewer():
  data = configured()
  data["profile"]["agent_options"]["permission_control"]["remote_fallback_model"] = "review-small"
  assert resolve_permission_control(data) == {"defaultMode": "smart", "reviewer": "session",
    "remoteFallback": {"provider": "fictional", "model": "small"}}


def test_official_unselected_profile_has_no_permission_object():
  data = configured()
  data["profile"]["plugins"] = []
  data["profile"]["agent_options"] = {"runtime_variant": "official"}
  assert resolve_permission_control(data) is None


@pytest.mark.parametrize("field,value", [("default_mode", "yolo"), ("default_mode", None),
  ("reviewer_model", None), ("reviewer_model", ""), ("remote_fallback_model", None),
  ("remote_fallback_model", ""), ("fallback_model", False),
  ("fallback_model", "local/another"), ("fallback_model", "fictional/small"),
  ("pluginDigest", "secret-sentinel"), ("runtimeIdentity", "secret-sentinel"),
  ("policyVersion", "secret-sentinel"), ("unknown", "secret-sentinel")])
def test_permission_config_is_closed(field, value):
  data = configured()
  data["profile"]["agent_options"]["permission_control"][field] = value
  with pytest.raises(ConfigError) as error:
    resolve_permission_control(data)
  assert error.value.exit_code == 2
  assert "secret-sentinel" not in str(error.value)


@pytest.mark.parametrize("part", ["plugin", "variant", "config", "default-mode", "null-config"])
def test_plugin_variant_config_must_match(part):
  data = configured()
  options = data["profile"]["agent_options"]
  if part == "plugin": data["profile"]["plugins"] = []
  elif part == "variant": options["runtime_variant"] = "permission-control-v1"
  elif part == "config": del options["permission_control"]
  elif part == "null-config": options["permission_control"] = None
  else: del options["permission_control"]["default_mode"]
  with pytest.raises(ConfigError): resolve_permission_control(data)


@pytest.mark.parametrize("field", ["reviewer_model", "remote_fallback_model"])
@pytest.mark.parametrize("change", ["unselected", "missing", "ambiguous", "provider-missing"])
def test_reviewer_must_resolve_exactly_once(field, change):
  data = configured()
  data["profile"]["agent_options"]["permission_control"][field] = "review-small"
  if change == "unselected": data["profile"]["models"] = []
  elif change == "missing": data["models"] = {}
  elif change == "provider-missing": data["providers"] = {}
  else:
    data["models"]["alias"] = deepcopy(data["models"]["review-small"])
    data["profile"]["models"].append("alias")
  with pytest.raises(ConfigError): resolve_permission_control(data)


@pytest.mark.parametrize("change", ["allow", "deny", "missing", "yolo"])
def test_native_bash_prompt_is_required_even_in_manual(change):
  data = configured()
  data["profile"]["agent_options"]["permission_control"]["default_mode"] = "manual"
  tools = data["profile"]["agent_options"]["runtime"]["tools"]
  if change == "missing": tools["approval"] = {}
  elif change == "yolo": tools["approvalMode"] = "yolo"
  else: tools["approval"]["bash"] = change
  with pytest.raises(ConfigError): resolve_permission_control(data)


@pytest.mark.parametrize("change", ["prompt", "deny", "missing"])
def test_permission_tool_must_be_preapproved_without_yolo(change):
  data = configured()
  tools = data["profile"]["agent_options"]["runtime"]["tools"]
  if change == "missing": del tools["approval"]["permission_bash"]
  else: tools["approval"]["permission_bash"] = change
  with pytest.raises(ConfigError): resolve_permission_control(data)


@pytest.mark.parametrize("location", ["top", "runtime"])
def test_raw_native_permission_object_is_not_accepted(location):
  data = configured()
  obj = data["profile"]["agent_options"]
  if location == "runtime": obj = obj["runtime"]
  obj["permissionControl"] = {"pluginDigest": "secret-sentinel"}
  with pytest.raises(ConfigError): resolve_permission_control(data)


def native():
  return {"schemaVersion": 2, "defaultMode": "smart", "reviewer": "session",
    "pluginId": "omp-permission-control", "pluginDigest": "a" * 64,
    "policyVersion": "b" * 64,
    "nativePatterns": [{"match": "pwd", "approval": "allow"}]}


@pytest.mark.parametrize("part", ["top", "reviewer", "remoteFallback", "fallback"])
def test_native_permission_objects_reject_unknown_fields(part):
  value = native()
  value["reviewer"] = {"provider": "fictional", "model": "small"}
  value["remoteFallback"] = {"provider": "fictional-remote", "model": "cheap"}
  value["fallback"] = {"provider": "local", "model": "lfm2.5-230m", "installedOnly": True}
  validator = Draft202012Validator(NATIVE_PERMISSION_CONTROL)
  validator.validate(value)
  (value if part == "top" else value[part])["unknown"] = "secret-sentinel"
  assert not validator.is_valid(value)


def test_repository_schema_has_same_native_contract():
  schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/omp-agent.schema.json").read_text())
  assert schema["$defs"]["permissionControl"] == NATIVE_PERMISSION_CONTROL


def test_native_sidecar_copies_patterns_and_has_deterministic_policy_identity():
  from agentcfg.omp import OmpAdapter
  data = configured()
  patterns = [{"match": "pwd", "approval": "allow"}, {"match": "rm -rf *", "approval": "deny"}]
  data["profile"]["agent_options"]["runtime"]["bash"] = {"patterns": patterns}
  adapter = OmpAdapter(Path(__file__).resolve().parents[1])
  first = adapter._native_permission(data)
  assert first == adapter._native_permission(deepcopy(data))
  assert first["nativePatterns"] == patterns and first["nativePatterns"] is not patterns
  changed = deepcopy(data)
  changed["profile"]["agent_options"]["runtime"]["bash"]["patterns"][0]["approval"] = "prompt"
  assert adapter._native_permission(changed)["policyVersion"] != first["policyVersion"]


def test_permission_typescript_foundation(omp_permission_materials, isolated_environment):
  from omp_permission_harness import ROOT, run_typescript
  output = run_typescript(omp_permission_materials,
    [ROOT / "agents/omp/packages/omp-permission-control/tests/foundation.test.ts"], isolated_environment)
  assert "0 fail" in output


def test_permission_typescript_core(omp_permission_materials, isolated_environment):
  from omp_permission_harness import ROOT, run_typescript
  paths = sorted((ROOT / "agents/omp/packages/omp-permission-control/tests").glob("*.test.ts"))
  assert paths
  output = run_typescript(omp_permission_materials, paths, isolated_environment,
    preload_name="identity.preload.ts")
  assert "0 fail" in output


def test_permission_patched_bridge(omp_permission_materials, isolated_environment):
  from omp_permission_harness import run_typescript
  output = run_typescript(omp_permission_materials,
    [omp_permission_materials["test_dir"] / "bridge.integration.test.ts"], isolated_environment)
  assert "0 fail" in output


def test_permission_host_identity(omp_permission_materials, isolated_environment):
  from omp_permission_harness import run_typescript
  output = run_typescript(omp_permission_materials,
    [omp_permission_materials["test_dir"] / "host-identity.integration.test.ts"], isolated_environment,
    preload_name="identity.preload.ts")
  assert "0 fail" in output


def test_permission_review_services(omp_permission_materials, isolated_environment):
  from omp_permission_harness import run_typescript
  output = run_typescript(omp_permission_materials, [
    omp_permission_materials["test_dir"] / "review-services.integration.test.ts",
    omp_permission_materials["test_dir"] / "tiny-installed.integration.test.ts",
  ], isolated_environment, preload_name="identity.preload.ts")
  assert "0 fail" in output


def test_permission_native_baseline(omp_permission_materials, isolated_environment):
  from omp_permission_harness import run_typescript
  output = run_typescript(omp_permission_materials, [
    omp_permission_materials["test_dir"] / "native-baseline.integration.test.ts",
  ], isolated_environment)
  assert "0 fail" in output
  assert "PERMISSION_NATIVE_BASELINE=" in output


def test_permission_read_proof(omp_permission_materials, isolated_environment):
  from omp_permission_harness import run_typescript
  output = run_typescript(omp_permission_materials, [
    omp_permission_materials["test_dir"] / "read-proof.integration.test.ts",
  ], isolated_environment, preload_name="identity.preload.ts")
  assert "0 fail" in output
