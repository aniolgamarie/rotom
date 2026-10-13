"""公开 preset/备用链配置投影；项目文件模拟不是第三方宿主 smoke。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from agentcfg.adapter import Ownership, RenderContext
from agentcfg.config import LocalConfig, resolve_config
from agentcfg.omp import OmpAdapter
from agentcfg.omp_model_presets import materialize_presets, resolve_selector
from agentcfg.omp_settings import validate_options
from agentcfg.schema import ConfigError
from agentcfg.workspace import load_public_catalog


REPO = Path(__file__).resolve().parents[1]


def data(profile="omp-kernel"):
  catalog, _ = load_public_catalog(repository=REPO)
  return resolve_config(catalog, LocalConfig({"schema_version": 1, "machine": {"id": "presets-test"},
    "local_values": {"tf_openai_url": "https://tf.example.invalid/v1", "tf_anthropic_url": "https://tf.example.invalid/anthropic"}}),
    profile_id=profile, adapter_schemas=catalog.adapter_schemas).data


def rendered(config, tmp_path):
  return OmpAdapter(REPO).render_with_context(config, RenderContext("offline-render-contract", tmp_path / "runtime"))


def fields(config, tmp_path):
  return {item.target.selector: json.loads(item.content) for item in rendered(config, tmp_path)
    if item.target.path.endswith("/config.yml")}


def test_complete_five_presets_are_independent_named_fields(tmp_path):
  values = fields(data(), tmp_path)
  expected = {
    "basic": ("kimi_code_anthropic/kimi-for-coding:high", "glm_coding_anthropic/glm-5.3-flash:low",
      "kimi_code_anthropic/kimi-for-coding:max", "glm_coding_anthropic/glm-5.3:high",
      "kimi_code_anthropic/kimi-for-coding:high", "glm_coding_anthropic/glm-5.3:high", "glm_coding_anthropic/glm-5.3-flash:high"),
    "tf": ("kimi_tf/kimi-for-coding:high", "zhipu_tf/glm-5.3-flash:low", "kimi_tf/k3:high",
      "zhipu_tf/glm-5.3:high", "kimi_tf/kimi-for-coding:high", "zhipu_tf/glm-5.3:high", "zhipu_tf/glm-5.3-flash:high"),
    "cursor": ("cursor/kimi-k3:high", "cursor/composer-2.5:low", "cursor/kimi-k3:max", "cursor/glm-5.2:high",
      "cursor/composer-2.5:medium", "cursor/grok-4.7:high", "cursor/kimi-k3:high"),
  }
  for name, provider in (("deepseek-payg", "deepseek_anthropic"), ("deepseek-tf-payg", "deepseek_tf")):
    expected[name] = tuple(provider + "/deepseek-flash:" + level for level in ("high", "low", "max", "high", "high", "max", "high"))
  for name, remote_values in expected.items():
    preset = values["/modelPresets/" + name]
    assert set(preset) == {"modelRoles"}
    assert preset["modelRoles"] == dict(zip(("default", "smol", "slow", "plan", "task", "advisor", "vision"), remote_values)) | {"tiny": "local/lfm2.5-230m"}
  assert "/modelPresets" not in values
  assert values["/modelRoleStorage"] == "project"
  assert values["/modelRoles/default"] == "kimi_tf/kimi-for-coding:high"
  assert "/modelRoles/vision" not in values and "/modelRoles/advisor" not in values
  assert all(item.target.ownership is Ownership.FIELDS for item in rendered(data(), tmp_path)
    if item.target.selector and item.target.selector.startswith("/modelPresets/"))


def test_basic_bootstrap_has_full_public_roles_without_cursor_login(tmp_path):
  config = data("omp-default")
  assert "cursor" not in config["providers"]
  values = fields(config, tmp_path)
  preset = values["/modelPresets/basic"]["modelRoles"]
  assert {key.removeprefix("/modelRoles/"): value for key, value in values.items() if key.startswith("/modelRoles/")} == preset
  assert {key for key in values if key.startswith("/modelPresets/")} == {"/modelPresets/basic", "/modelPresets/deepseek-payg"}


@pytest.mark.parametrize("role,value", [
  ("main", "unknown:high"), ("main", "kimi_code_anthropic"), ("main", "kimi_code_anthropic:medium"),
  ("main", "kimi_code_anthropic:turbo"), ("vision", "glm_coding_53_anthropic:high"),
  ("tiny", "local/other"), ("main", "cursor/composer-2.5:max"),
  ("main", "cursor/glm-5.2:low"), ("main", "cursor/grok-4.7:max"),
  ("main", "cursor/kimi-k3:medium"), ("main", "cursor/kimi-k3-high:high:low"),
])
def test_invalid_reference_or_thinking_fails(role, value):
  config = data()
  config["profile"]["agent_options"]["model_presets"]["basic"]["roles"][role] = value
  with pytest.raises(ConfigError):
    OmpAdapter(REPO).validate(config)


@pytest.mark.parametrize("mutation", [
  lambda presets: presets["basic"].update(defaultThinkingLevel="high"),
  lambda presets: presets["basic"]["roles"].pop("advisor"),
  lambda presets: presets["basic"]["roles"].update(default="kimi_code_anthropic:high"),
  lambda presets: presets.update({"bad/name": deepcopy(presets["basic"])}),
  lambda presets: presets.update({"bad\n": deepcopy(presets["basic"])}),
])
def test_closed_preset_schema_rejects_new_fields_and_unsafe_names(mutation):
  config = data()
  mutation(config["profile"]["agent_options"]["model_presets"])
  with pytest.raises(ConfigError):
    materialize_presets(config)


def test_unselected_provider_and_static_model_references_fail():
  config = data()
  config["profile"]["providers"].remove("cursor")
  with pytest.raises(ConfigError):
    materialize_presets(config)
  config = data()
  config["profile"]["models"].remove("kimi_code_anthropic")
  with pytest.raises(ConfigError):
    materialize_presets(config)


def test_protocol_specific_and_dynamic_selectors_remain_distinct():
  config = data()
  assert resolve_selector(config, "kimi_code_anthropic:max", public=True, require_level=True) == "kimi_code_anthropic/kimi-for-coding:max"
  assert resolve_selector(config, "cursor/kimi-k3:max", public=True, require_level=True) == "cursor/kimi-k3:max"
  with pytest.raises(ConfigError):
    resolve_selector(config, "kimi_code_openai:high", public=True, require_level=True)


def test_configured_fallbacks_are_model_specific_and_route_isolated():
  chains = data()["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"]
  assert chains and not {"default", "smol", "slow", "plan", "task", "advisor", "vision", "tiny"}.intersection(chains)
  assert chains["cursor/composer-2.5:low"] == ["cursor/kimi-k2.7-code:low"]
  assert chains["cursor/composer-2.5:medium"] == ["cursor/kimi-k2.7-code:medium"]
  assert chains["cursor/kimi-k3-max"] == []
  assert "cursor/*" not in chains
  assert not {"cursor/kimi-k3", "cursor/kimi-k3:high", "cursor/kimi-k3:max"}.intersection(chains)
  assert chains["kimi_code_anthropic/kimi-for-coding:max"] == ["glm_coding_anthropic/glm-5.3:high"]
  for key, values in chains.items():
    assert "deepseek" not in key
    for value in values:
      assert "deepseek" not in value
      if key.startswith("cursor/"):
        assert value.startswith("cursor/")
      elif key.startswith(("kimi_tf/", "zhipu_tf/")):
        assert value.startswith(("kimi_tf/", "zhipu_tf/"))
      else:
        assert value.startswith(("kimi_code_anthropic/", "glm_coding_anthropic/"))


def test_cursor_k3_history_guard_keeps_explicit_empty_chains_in_native_render(tmp_path):
  config = data()
  validate_options(config)
  chains = config["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"]
  blocked = {"cursor/kimi-k3-low", "cursor/kimi-k3-high", "cursor/kimi-k3-max",
    "cursor/glm-5.2:high", "cursor/glm-5.2:max", "cursor/grok-4.7:high"}
  absent = {"cursor/kimi-k3", "cursor/kimi-k3:high", "cursor/kimi-k3:max"}
  assert not absent.intersection(chains)
  assert "cursor/*" not in chains
  assert {key: chains[key] for key in blocked} == {key: [] for key in blocked}
  assert all("cursor/kimi-k3" not in target for values in chains.values() for target in values)
  # 空链必须原样进入原生配置，删除键会重新落到上游角色或默认链。
  native = fields(config, tmp_path)["/retry"]["fallbackChains"]
  assert not absent.intersection(native)
  assert "cursor/*" not in native
  assert {key: native[key] for key in blocked} == {key: [] for key in blocked}
  assert native["cursor/composer-2.5:low"] == ["cursor/kimi-k2.7-code:low"]
  assert native["cursor/composer-2.5:medium"] == ["cursor/kimi-k2.7-code:medium"]


@pytest.mark.parametrize("key,chain", [
  ("not-a-key", []), ("unselected/*", []), ("unselected/model:high", []),
  ("cursor/composer-2.5:max", []), ("cursor/*", ["unselected/model:high"]),
  ("kimi_code_anthropic/*", ["kimi_code_anthropic/kimi-for-coding:medium"]),
])
def test_fallback_keys_and_values_are_strict_selected_references(key, chain):
  config = data()
  config["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"][key] = chain
  with pytest.raises(ConfigError):
    validate_options(config)


def test_selected_provider_wildcard_and_empty_deepseek_chain_are_supported():
  config = data()
  chains = config["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"]
  chains["cursor/*"] = ["cursor/kimi-k3:high"]
  chains["deepseek_anthropic/deepseek-flash:high"] = []
  validate_options(config)


def test_private_native_roles_keep_priority_and_permission_review_is_unchanged(tmp_path):
  config = data()
  config["profile"]["agent_options"]["native_model_roles"] = {"main": "cursor/kimi-k3:max"}
  values = fields(config, tmp_path)
  assert values["/modelRoles/default"] == "cursor/kimi-k3:max"
  assert values["/modelPresets/basic"]["modelRoles"]["default"] == "kimi_code_anthropic/kimi-for-coding:high"
  permission = OmpAdapter(REPO)._native_permission(config)
  assert permission["reviewer"] == {"provider": "zhipu_tf", "model": "glm-5.3-flash"}
  assert permission["remoteFallback"] == {"provider": "kimi_tf", "model": "kimi-for-coding"}
  assert permission["fallback"] == {"provider": "local", "model": "lfm2.5-230m", "installedOnly": True}


def test_project_switch_simulation_preserves_global_bootstrap_and_other_preset_names(tmp_path):
  """依公开 project modelRoles 文件契约手写切换结果；不执行原生 /modelpreset。"""
  from agentcfg import deployment
  from agentcfg.render import RenderCandidate
  from agentcfg.workspace import load_workspace
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  local = private / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="presets-owned"\n')
  local.chmod(0o600)
  workspace = load_workspace(local, "omp-default", repository=REPO)
  candidate = RenderCandidate("offline-field-ownership", workspace.adapter.render(workspace.resolved.data))
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, {})
  from agentcfg.omp_identity import native_identity
  global_path = native_identity(workspace.profile, workspace.instance).agent_dir / "config.yml"
  global_config = yaml.safe_load(global_path.read_text())
  global_config["modelPresets"]["user-created"] = {"modelRoles": {"default": "keep/user-choice"}}
  global_path.write_text(yaml.safe_dump(global_config))
  global_path.chmod(0o600)
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, {})
  assert yaml.safe_load(global_path.read_text())["modelPresets"]["user-created"] == {"modelRoles": {"default": "keep/user-choice"}}
  before = global_path.read_bytes()
  project = tmp_path / "project/.omp"
  project.mkdir(parents=True)
  project_path = project / "config.yml"
  project_path.write_text(yaml.safe_dump({"modelRoles": global_config["modelPresets"]["deepseek-payg"]["modelRoles"]}))
  assert yaml.safe_load(project_path.read_text())["modelRoles"]["default"] == "deepseek_anthropic/deepseek-flash:high"
  assert global_path.read_bytes() == before


def test_explicit_private_review_and_fallback_same_model_are_preserved():
  config = data()
  permission = config["profile"]["agent_options"]["permission_control"]
  permission["reviewer_model"] = "omp-kimi_tf-kimi-for-coding"
  permission["remote_fallback_model"] = "omp-kimi_tf-kimi-for-coding"
  native = OmpAdapter(REPO)._native_permission(config)
  assert native["reviewer"] == native["remoteFallback"] == {"provider": "kimi_tf", "model": "kimi-for-coding"}


def test_cursor_kimi_27_uses_complete_verified_thinking_levels():
  config = data()
  for level in ("minimal", "low", "medium", "high"):
    selector = "cursor/kimi-k2.7-code:" + level
    assert resolve_selector(config, selector, require_level=True) == selector
  with pytest.raises(ConfigError):
    resolve_selector(config, "cursor/kimi-k2.7-code:max", require_level=True)


def test_private_session_reviewer_override_wins_over_fixed_public_default():
  catalog, _ = load_public_catalog(repository=REPO)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "session-reviewer"},
    "local_values": {"tf_openai_url": "https://tf.example.invalid/v1", "tf_anthropic_url": "https://tf.example.invalid/anthropic"},
    "overrides": {"profiles": {"omp-kernel": {"agent_options": {"permission_control": {"reviewer_model": "session"}}}}}})
  config = resolve_config(catalog, local, profile_id="omp-kernel", adapter_schemas=catalog.adapter_schemas).data
  native = OmpAdapter(REPO)._native_permission(config)
  assert native["reviewer"] == "session"
  assert native["remoteFallback"] == {"provider": "kimi_tf", "model": "kimi-for-coding"}
  assert config["profile"]["agent_options"]["model_presets"]["cursor"]["roles"]["main"] == "cursor/kimi-k3:high"


@pytest.mark.parametrize("field,value", [("remote_fallback_model", "session"), ("reviewer_model", "unknown-model")])
def test_session_is_only_a_reviewer_literal_and_unknown_references_still_fail(field, value):
  config = data()
  config["profile"]["agent_options"]["permission_control"][field] = value
  with pytest.raises(ConfigError) as error:
    validate_options(config)
  assert error.value.code == "omp-permission-reviewer-reference"


@pytest.mark.parametrize("remote", ["model:revision", "family/model:revision"])
def test_registered_native_refs_preserve_full_remote_id_before_effort_parsing(remote):
  config = data()
  config["models"]["deepseek_flash_anthropic"]["remote_id"] = remote
  native = "deepseek_anthropic/" + remote
  assert resolve_selector(config, native) == native
  assert resolve_selector(config, native + ":high") == native + ":high"
  config["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"][native + ":high"] = []
  validate_options(config)
  with pytest.raises(ConfigError):
    resolve_selector(config, native + ":turbo")


def test_effective_model_reasoning_override_rejects_thinking_preset():
  config = data()
  config["profile"]["agent_options"]["model_options"]["kimi_code_anthropic"] = {"reasoning": False}
  with pytest.raises(ConfigError) as error:
    materialize_presets(config)
  assert error.value.code == "omp-model-thinking-level"
  assert resolve_selector(config, "kimi_code_anthropic/kimi-for-coding") == "kimi_code_anthropic/kimi-for-coding"


@pytest.mark.parametrize("value", ["cursor/*:high", "cursor/kimi-?:high", "cursor/kimi-[23]:high"])
def test_preset_and_fallback_values_require_specific_cursor_model(value):
  config = data()
  config["profile"]["agent_options"]["model_presets"]["cursor"]["roles"]["main"] = value
  with pytest.raises(ConfigError):
    materialize_presets(config)
  config = data()
  config["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"]["cursor/*"] = [value]
  with pytest.raises(ConfigError):
    validate_options(config)
