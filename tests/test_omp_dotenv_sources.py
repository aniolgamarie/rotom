"""dotenv 门禁只检查实际来源位置和明确传入的模式。"""

from pathlib import Path

import pytest

from agentcfg.omp_discovery import (
  SourcePolicy, assert_clean_sources, assert_native_sources, discovery_manifest,
  dotenv_names, inspect_project_sources,
)
from agentcfg.omp_execution_environment import capture_execution_environment
from agentcfg.omp_identity import native_identity
from agentcfg.storage import Conflict


@pytest.fixture
def native_environment(tmp_path, isolated_environment):
  identity = native_identity("synthetic", tmp_path / "instance")
  binding = capture_execution_environment(identity, {"HOME": str(isolated_environment.home)})
  return identity, binding


@pytest.mark.parametrize("mode", [None, "", "development", "staging", "production", "test", "custom-mode_2"])
def test_effective_dotenv_names_derive_only_public_mode(mode):
  class ModeOnly:
    def get(self, key):
      assert key == "NODE_ENV"
      return mode

  names = dotenv_names(ModeOnly())
  effective = mode or "development"
  assert ".env." + effective in names
  assert ".env." + effective + ".local" in names
  assert names[:5] == (".env", ".env.local", ".env.development", ".env.production", ".env.test")
  assert len(names) == len(set(names))


@pytest.mark.parametrize("mode", ["../sensitive", "staging/local", "bad\0sensitive", "bad\\mode", "bad.mode", "bad mode", 42])
def test_invalid_mode_rejected_without_echo(mode, native_environment, tmp_path):
  identity, binding = native_environment
  for gate in (
    lambda: dotenv_names({"NODE_ENV": mode}),
    lambda: assert_native_sources(identity, execution_environment=binding, environment={"NODE_ENV": mode}),
    lambda: inspect_project_sources(tmp_path, SourcePolicy.from_options({}), environment={"NODE_ENV": mode}),
  ):
    with pytest.raises(Conflict) as error:
      gate()
    assert str(error.value) == "OMPNODE_ENV模式无效"


@pytest.mark.parametrize("root", ["home", "base_config_root", "config_root", "agent_dir"])
@pytest.mark.parametrize("mode", ["development", "staging"])
@pytest.mark.parametrize("local", [False, True])
def test_native_dotenv_checks_actual_tool_roots_without_reading(native_environment, root, mode, local, monkeypatch):
  identity, binding = native_environment
  directory = Path(binding["home"] if root == "home" else binding["native_paths"][root])
  path = directory / (".env." + mode + (".local" if local else ""))
  directory.mkdir(parents=True, exist_ok=True)
  path.write_text("SYNTHETIC_PRIVATE_BODY=must-not-read\n")

  def forbidden(*args, **kwargs):
    raise AssertionError("dotenv body was accessed")

  monkeypatch.setattr(Path, "open", forbidden)
  with pytest.raises(Conflict) as error:
    assert_native_sources(identity, execution_environment=binding, environment={"NODE_ENV": mode})
  assert str(error.value) == "OMP检测到未声明的dotenv来源"


def test_legacy_native_gate_checks_profile_config_root(native_environment):
  identity, _ = native_environment
  root = identity.agent_dir.parent
  root.mkdir(parents=True)
  (root / ".env").touch()
  with pytest.raises(Conflict, match="dotenv"):
    assert_native_sources(identity)


@pytest.mark.parametrize("root", ["home", "base_config_root", "config_root", "agent_dir"])
def test_dangling_dotenv_symlink_is_rejected(native_environment, root):
  identity, binding = native_environment
  directory = Path(binding["home"] if root == "home" else binding["native_paths"][root])
  directory.mkdir(parents=True, exist_ok=True)
  (directory / ".env.development.local").symlink_to(directory / "missing-private-body")
  with pytest.raises(Conflict, match="dotenv"):
    assert_native_sources(identity, execution_environment=binding)


@pytest.mark.parametrize("binding", [None, [], {}, {"xdg": []}, {"xdg": {42: "invalid"}}])
def test_invalid_execution_binding_has_fixed_conflict(native_environment, binding):
  identity, _ = native_environment
  if binding is None:
    assert_native_sources(identity, execution_environment=binding)
  else:
    with pytest.raises(Conflict) as error:
      assert_native_sources(identity, execution_environment=binding)
    assert str(error.value) == "OMP执行环境绑定无效或原生路径发生冲突"


def test_unrelated_user_omp_installation_is_not_actual_native_source(native_environment):
  identity, binding = native_environment
  unrelated = Path(binding["home"]) / ".omp"
  (unrelated / "agent").mkdir(parents=True)
  (unrelated / ".env").write_text("SYNTHETIC=value")
  (unrelated / "agent/config.yml").write_text("unrelated: true")
  (unrelated / "marketplaces.json").write_text("{}")
  assert_native_sources(identity, execution_environment=binding)


@pytest.mark.parametrize("ancestor", [False, True])
@pytest.mark.parametrize("opt_in", [False, True])
@pytest.mark.parametrize("mode", ["development", "staging"])
def test_project_gates_check_same_mode_and_reject_local_overlay(tmp_path, monkeypatch, ancestor, opt_in, mode):
  project = tmp_path / "project"
  cwd = project / "nested"
  cwd.mkdir(parents=True)
  root = project if ancestor else cwd
  path = root / (".env." + mode + ".local")
  path.write_text("SYNTHETIC_PRIVATE_BODY=must-not-read")
  policy = SourcePolicy.from_options({"project_resources": opt_in,
    "project_roots": [str(project)] if opt_in else []})
  monkeypatch.setattr(Path, "open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dotenv body was read")))
  for gate in (
    lambda: assert_clean_sources(cwd, environment={"NODE_ENV": mode}),
    lambda: inspect_project_sources(cwd, policy, environment={"NODE_ENV": mode}),
  ):
    with pytest.raises(Conflict) as error:
      gate()
    assert str(error.value) == "OMP检测到未声明的dotenv来源"


def test_unselected_custom_mode_is_not_scanned(tmp_path, native_environment):
  identity, binding = native_environment
  root = Path(binding["native_paths"]["config_root"])
  root.mkdir(parents=True)
  (root / ".env.staging.local").touch()
  assert_native_sources(identity, execution_environment=binding)
  with pytest.raises(Conflict, match="dotenv"):
    assert_native_sources(identity, execution_environment=binding, environment={"NODE_ENV": "staging"})


def test_manifest_dynamic_names_are_source_contract_templates():
  contract = discovery_manifest()["dotenv"]
  assert contract == {"environment": "NODE_ENV", "defaultMode": "development",
    "modePattern": "[A-Za-z0-9][A-Za-z0-9_-]*",
    "nativeRoots": ["$HOME", "$BASE_CONFIG", "$ACTIVE_CONFIG", "$ACTIVE_AGENT"],
    "projectScope": "cwd-and-ancestors", "dynamicNames": [".env.$NODE_ENV", ".env.$NODE_ENV.local"],
    "inspection": "metadata-only"}
  assert ".env.$NODE_ENV" not in dotenv_names()
