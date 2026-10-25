"""Pi 可选 TF 目录：隔离选择、原生渲染与既有默认设置保护。"""

import json
from pathlib import Path
import tomllib

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.schema import ConfigError
from agentcfg.workspace import load_workspace


REPO = Path(__file__).resolve().parents[1]
REMOTE_IDS = {
  "kimi_tf": ("kimi-for-coding", "k3", "k3-256k", "k3.1-pro", "k3.1-pro-highspeed", "kimi-for-coding-highspeed"),
  "zhipu_tf": ("glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-5.1", "glm-5-turbo"),
  "deepseek_tf": ("deepseek-flash", "deepseek-v4-pro"),
}
TF_IDS = {f"pi-{provider}-{remote}" for provider, remotes in REMOTE_IDS.items() for remote in remotes}


def machine_file(tmp_path, *, tf=True, urls=True):
  text = (REPO / "examples/pi-tf.local.toml").read_text() if tf else 'schema_version = 1\n[machine]\nid = "fixture"\n'
  if not urls:
    text = text.replace('tf_openai_url = "https://tf-gateway.example.invalid/v1"', "")
  path = tmp_path / ("tf.toml" if tf else "default.toml")
  path.write_text(text)
  path.chmod(0o600)
  return path


def rendered(workspace):
  return {(item.target.path, item.target.selector): json.loads(item.content)
    for item in workspace.adapter.render(workspace.resolved.data)
    if item.target.path.endswith(".json")}


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_tf_selection_adds_thirteen_routes_without_changing_existing_choices(tmp_path, profile):
  baseline = load_workspace(machine_file(tmp_path, tf=False), profile, repository=REPO)
  selected = load_workspace(machine_file(tmp_path), profile, repository=REPO)
  before, data = baseline.resolved.data, selected.resolved.data
  assert len(before["models"]) == 10
  assert len(data["models"]) == 23
  assert set(data["models"]) - set(before["models"]) == TF_IDS
  assert data["profile"]["roles"] == before["profile"]["roles"] == {"main": "kimi_code_openai"}
  for field in ("plugins", "mcp", "skills", "rules", "agent_options"):
    assert data["profile"][field] == before["profile"][field]
  assert data["profile"]["plugins"] == ["pi-footer"]
  assert data["profile"]["agent_options"]["resources"]["extensions"] == ["builtin:codemode"]
  artifacts = rendered(selected)
  baseline_artifacts = rendered(baseline)
  for key, value in baseline_artifacts.items():
    if key != ("pi-home/settings.json", "/enabledModels"):
      assert artifacts[key] == value
  enabled = artifacts[("pi-home/settings.json", "/enabledModels")]
  assert len(enabled) == 23
  assert set(enabled) - set(baseline_artifacts[("pi-home/settings.json", "/enabledModels")]) == {
    f"agentcfg-{provider}/{remote}" for provider, remotes in REMOTE_IDS.items() for remote in remotes}
  spec = selected.adapter.launch_spec(data, cwd=tmp_path.absolute(),
    runtime_root=(tmp_path / "runtime").absolute(), instance_root=selected.instance, lock_identity="a" * 64)
  bindings = {binding.value.reference: binding for binding in spec.environment if isinstance(binding.value, SecretRef)}
  for provider in REMOTE_IDS:
    credential = "secret:omp_" + provider + "_key"
    assert bindings[credential].required is False
    assert artifacts[("pi-home/models.json", f"/providers/agentcfg-{provider}/apiKey")] == "$" + bindings[credential].name
  assert "builtin:codemode" in spec.argv
  assert any("pi-footer" in arg for arg in spec.argv)


def test_tf_routes_render_protocols_and_references_without_inheriting_prices(tmp_path):
  workspace = load_workspace(machine_file(tmp_path), "pi-base", repository=REPO)
  data, artifacts = workspace.resolved.data, rendered(workspace)
  content = tomllib.loads((REPO / "agents/omp/content.toml").read_text())
  for provider, remotes in REMOTE_IDS.items():
    declaration = content["providers"][provider]
    anthropic = provider == "zhipu_tf"
    assert declaration["protocol"] == ("anthropic-messages" if anthropic else "openai-compatible")
    assert declaration["base_url_ref"] == "local:tf_" + ("anthropic" if anthropic else "openai") + "_url"
    assert data["providers"][provider]["credential_ref"] == "secret:omp_" + provider + "_key"
    prefix = f"/providers/agentcfg-{provider}/"
    assert artifacts[("pi-home/models.json", prefix + "api")] == ("anthropic-messages" if anthropic else "openai-completions")
    assert artifacts[("pi-home/models.json", prefix + "baseUrl")] == "https://tf-gateway.example.invalid/" + ("anthropic" if anthropic else "v1")
    models = {model["id"]: model for model in artifacts[("pi-home/models.json", prefix + "models")]}
    assert set(models) == set(remotes)
    for remote, model in models.items():
      assert "pricing" not in data["models"][f"pi-{provider}-{remote}"]
      assert "cost" not in model
      assert "omp" not in model and "dsh" not in model
    if provider == "kimi_tf":
      assert models["kimi-for-coding"]["compat"]["thinkingFormat"] == "zai"
      assert models["k3"]["compat"]["thinkingFormat"] == "openai"
      assert models["k3-256k"]["thinkingLevelMap"]["xhigh"] == "max"
      assert models["k3.1-pro"]["thinkingLevelMap"]["off"] is None
      assert models["k3.1-pro-highspeed"]["thinkingLevelMap"]["off"] is None
      assert models["kimi-for-coding-highspeed"]["compat"]["supportsReasoningEffort"] is False
      assert "thinkingLevelMap" not in models["kimi-for-coding-highspeed"]
    elif provider == "deepseek_tf":
      for model in models.values():
        assert model["compat"]["thinkingFormat"] == "deepseek"
        assert model["compat"]["requiresReasoningContentOnAssistantMessages"] is True
        assert model["thinkingLevelMap"]["xhigh"] == "high"
    else:
      for remote in ("glm-5.3", "glm-5.3-flash"):
        assert models[remote]["compat"] == {"forceAdaptiveThinking": True}
        assert models[remote]["thinkingLevelMap"] == {
          "off": None, "minimal": "low", "low": "low", "medium": "high",
          "high": "high", "xhigh": "max", "max": "max"}
      for remote in ("glm-5.2", "glm-5.1", "glm-5-turbo"):
        assert "thinkingLevelMap" not in models[remote]
        assert "compat" not in models[remote]
        assert "reasoning_efforts" not in data["models"][f"pi-zhipu_tf-{remote}"]


def test_selected_tf_route_requires_local_url(tmp_path):
  with pytest.raises(ConfigError) as error:
    load_workspace(machine_file(tmp_path, urls=False), "pi-base", repository=REPO)
  assert error.value.code == "local-value"


@pytest.mark.parametrize("profile", ["dsh-default", "omp-default"])
def test_pi_tf_example_does_not_change_other_host_defaults(tmp_path, profile):
  baseline = load_workspace(machine_file(tmp_path, tf=False), profile, repository=REPO)
  selected = load_workspace(machine_file(tmp_path), profile, repository=REPO)
  for key in ("providers", "models", "profile"):
    assert selected.resolved.data[key] == baseline.resolved.data[key]


def test_pi_adaptive_thinking_boolean_is_public_metadata_and_unknown_fields_fail(tmp_path):
  from agentcfg.schema import validate_document
  model = {"provider": "provider", "remote_id": "model", "input": ["text"]}
  for enabled in (True, False):
    model["native"] = {"pi": {"compat": {"forceAdaptiveThinking": enabled}}}
    validate_document("registry", {"schema_version": 1, "models": {"model": model}})
    validate_document("local", {"schema_version": 1, "machine": {"id": "fixture"},
      "overrides": {"models": {"model": {"native": model["native"]}}}})
  for compat in ({"forceAdaptiveThinking": "true"}, {"forceAdaptiveThinkings": True}):
    model["native"] = {"pi": {"compat": compat}}
    with pytest.raises(ConfigError):
      validate_document("registry", {"schema_version": 1, "models": {"model": model}})
    with pytest.raises(ConfigError):
      validate_document("local", {"schema_version": 1, "machine": {"id": "fixture"},
        "overrides": {"models": {"model": {"native": model["native"]}}}})
  local = machine_file(tmp_path)
  with local.open("a") as stream:
    stream.write('\n[overrides.models."pi-zhipu_tf-glm-5.3".native.pi.compat]\nforceAdaptiveThinking = false\n')
  workspace = load_workspace(local, "pi-base", repository=REPO)
  assert workspace.resolved.data["models"]["pi-zhipu_tf-glm-5.3"]["native"]["pi"]["compat"]["forceAdaptiveThinking"] is False
  models = rendered(workspace)[("pi-home/models.json", "/providers/agentcfg-zhipu_tf/models")]
  assert next(model for model in models if model["id"] == "glm-5.3")["compat"]["forceAdaptiveThinking"] is False
