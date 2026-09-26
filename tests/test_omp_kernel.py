"""真实 kernel 的非秘密参考配置与受管部署逐项对齐，测试不读取用户 HOME。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from agentcfg import deployment
from agentcfg.omp import OmpAdapter
from agentcfg.omp_identity import native_identity
from agentcfg.schema import ConfigError, validate_document
from agentcfg.workspace import load_workspace


REPO = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((REPO / "tests/fixtures/omp/kernel-reference.json").read_text())


def kernel_workspace(tmp_path):
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  local = private / "machine.toml"
  local.write_text('schema_version = 1\n[machine]\nid = "kernel-test"\n'
    '[machine.paths]\n' + "\n".join(key + " = " + json.dumps(str(tmp_path / folder)) for key, folder in (
      ("instances_root", "instances"), ("state_root", "state"), ("cache_root", "cache"))) + "\n")
  local.chmod(0o600)
  return load_workspace(local, "omp-kernel", repository=REPO)


def test_kernel_deployment_preserves_reviewed_native_configuration(tmp_path):
  workspace = kernel_workspace(tmp_path)
  candidate = workspace.candidate("fixture-lock")
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, {})
  identity = native_identity(workspace.profile, workspace.instance)
  config = yaml.safe_load((identity.agent_dir / "config.yml").read_text())
  # 对照迁入前非秘密快照，身份和发现来源策略另有明确替换契约。
  for key, expected in REFERENCE["config"].items():
    if key != "skills":
      assert config[key] == expected, key
  assert config["skills"]["enablePiUser"] is True
  assert config["skills"]["enablePiProject"] is False
  models = yaml.safe_load((identity.agent_dir / "models.yml").read_text())
  for provider, expected in REFERENCE["models"]["providers"].items():
    actual = deepcopy(models["providers"][provider])
    assert actual.pop("apiKey").startswith("AGENTCFG_OMP_")
    expected = deepcopy(expected)
    for model in expected["models"]:
      model.setdefault("input", ["text"])
    assert actual == expected
  for name in REFERENCE["agents"]:
    path = identity.agent_dir / "agents" / (name + ".md")
    assert path.read_bytes() == (REPO / "agents/omp/resources/agents" / (name + ".md")).read_bytes()
  for name in REFERENCE["skills"]:
    source = REPO / "agents/omp/resources/skills" / name
    # 公共ID与原生包目录可不同，完整相对资源关系必须保留。
    target = identity.agent_dir / "skills" / ("omp-kernel-" + name)
    files = [path for path in source.rglob("*") if path.is_file()]
    for path in files:
      assert (target / path.relative_to(source)).read_bytes() == path.read_bytes()
  assert not (identity.agent_dir / "auth.db").exists()
  assert not (identity.agent_dir / "sessions").exists()


@pytest.mark.parametrize("mutate", [
  lambda options: options["runtime"].update(auth={"broker": "https://invalid.example"}),
  lambda options: options["runtime"].update(extensions=["/external.ts"]),
  lambda options: options["runtime"]["tools"].update(unknown=True),
  lambda options: options["runtime"].update(memory={"backend": "hindsight"}),
])
def test_kernel_options_reject_unknown_and_identity_settings(tmp_path, mutate):
  workspace = kernel_workspace(tmp_path)
  profile = deepcopy(workspace.resolved.data["profile"])
  mutate(profile["agent_options"])
  with pytest.raises(ConfigError):
    validate_document("profile", {"schema_version": 1, **profile}, adapter_schemas=workspace.schemas)


def test_kernel_fallback_and_agent_models_must_be_declared(tmp_path):
  workspace = kernel_workspace(tmp_path)
  data = deepcopy(workspace.resolved.data)
  data["profile"]["agent_options"]["runtime"]["retry"]["fallbackChains"]["default"] = ["undeclared/model:high"]
  with pytest.raises(ConfigError, match="fallback-model"):
    OmpAdapter(REPO).validate(data)
  from agentcfg.omp_settings import validate_agent
  with pytest.raises(ConfigError, match="agent-resource"):
    validate_agent(b"---\nname: scout\ndescription: test\nprewalk: /external.sh\n---\nbody", "scout", data)


def test_capture_retains_kernel_role_thinking(tmp_path):
  workspace = kernel_workspace(tmp_path)
  captured = workspace.adapter.capture_configuration({"modelRoles": REFERENCE["config"]["modelRoles"]}, workspace.resolved.data)
  assert captured["roles"] == workspace.resolved.data["profile"]["roles"]
  assert captured["agent_options"]["role_thinking"] == workspace.resolved.data["profile"]["agent_options"]["role_thinking"]


@pytest.mark.parametrize("channel", ["caller", "values", "inherit", "final"])
def test_native_config_overlay_environment_is_rejected(tmp_path, monkeypatch, channel):
  from test_omp_runtime_foundation import clear_omp_identity_environment
  clear_omp_identity_environment(monkeypatch)
  workspace = kernel_workspace(tmp_path)
  adapter = workspace.adapter
  if channel == "caller":
    monkeypatch.setenv("PI_CONFIG_FILES", "/outside/settings.yml")
    with pytest.raises(ConfigError, match="caller-identity"):
      adapter.validate_operation_environment(workspace)
  elif channel == "final":
    identity = native_identity(workspace.profile, workspace.instance)
    env = {"HOME": str(identity.home), "XDG_CONFIG_HOME": str(identity.xdg_config),
      "XDG_DATA_HOME": str(identity.xdg_data), "XDG_STATE_HOME": str(identity.xdg_state),
      "XDG_CACHE_HOME": str(identity.xdg_cache), "PI_CONFIG_FILES": "/outside/settings.yml"}
    with pytest.raises(ConfigError, match="operation-environment"):
      adapter.validate_operation_environment(workspace, env=env)
  else:
    data = deepcopy(workspace.resolved.data)
    data["machine"]["environment"][channel] = {"PI_CONFIG_FILES": "/outside/settings.yml"} if channel == "values" else ["PI_CONFIG_FILES"]
    with pytest.raises(ConfigError, match="identity-environment"):
      adapter.validate(data)


def test_complete_kernel_runs_from_repo_with_only_declared_secret_environment(
    tmp_path, monkeypatch, fake_subprocess):
  from types import SimpleNamespace
  from agentcfg import runtime
  from agentcfg.secrets import SecretStore
  from test_omp_runtime_foundation import RuntimeBackend, clear_omp_identity_environment
  clear_omp_identity_environment(monkeypatch)
  original = kernel_workspace(tmp_path)
  backend = RuntimeBackend()
  lock = SimpleNamespace(identity="a" * 64)
  backend.read_lock = lambda repository: lock
  workspace = SimpleNamespace(**{name: getattr(original, name) for name in (
    "profile", "instance", "state_root", "cache", "binding", "resolved", "adapter", "repository", "local_path")},
    backend=backend, secret_store=SecretStore({"omp_kimi_tf_key": "synthetic-kimi", "omp_zhipu_tf_key": "synthetic-zhipu"}))
  candidate = original.candidate(lock.identity)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, runtime.record(workspace, lock))
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=REPO) == 0
  call = fake_subprocess.calls[0]
  assert call["cwd"] == REPO
  assert "--no-title" in call["argv"]
  assert call["env"]["HOME"] == str(native_identity(workspace.profile, workspace.instance).home)
  assert sorted(value for key, value in call["env"].items() if key.startswith("AGENTCFG_OMP_PROVIDER_")) == [
    "synthetic-kimi", "synthetic-zhipu"]
  assert "PI_CONFIG_FILES" not in call["env"]
  # 实际agent权限文件一旦漂移，必须在第二次spawn前拒绝。
  from agentcfg.storage import Conflict
  agent = native_identity(workspace.profile, workspace.instance).agent_dir / "agents/task.md"
  agent.write_text(agent.read_text() + "\nchanged permission instructions\n")
  with pytest.raises(Conflict):
    runtime.run(workspace, cwd=REPO)
  assert len(fake_subprocess.calls) == 1


def test_capture_distinguishes_model_id_colon_from_thinking_suffix():
  from test_omp_adapter import omp_data
  data = omp_data()
  data["models"]["large"]["remote_id"] = "large:revision"
  adapter = OmpAdapter(REPO)
  result = adapter.capture_configuration({"modelRoles": {"default": "gateway/large:revision"}}, data)
  assert result == {"roles": {"main": "large"}}
  result = adapter.capture_configuration({"modelRoles": {"default": "gateway/large:revision:high"}}, data)
  assert result["agent_options"]["role_thinking"] == {"main": "high"}
  with pytest.raises(ConfigError):
    adapter.capture_configuration({"modelRoles": {"default": 123}}, data)
