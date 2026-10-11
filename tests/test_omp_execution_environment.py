"""执行环境路径绑定的离线、无正文访问验收。"""

import copy
import json
import os
from pathlib import Path

import pytest

from agentcfg.omp_execution_environment import (
  XDG_KEYS, capture_execution_environment, predict_native_paths,
  validate_execution_environment,
)
from agentcfg.omp_identity import native_identity
from agentcfg.storage import Conflict


@pytest.fixture
def environment(isolated_environment):
  env = {"HOME": str(isolated_environment.home)}
  env.update({key: str(isolated_environment.home / key.lower()) for key in XDG_KEYS})
  identity = native_identity("synthetic-profile", isolated_environment.root / "state/omp/instance")
  return identity, env


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_binding_preserves_caller_and_old_paths(environment, platform):
  identity, env = environment
  binding = capture_execution_environment(identity, env, platform=platform)
  assert json.loads(json.dumps(binding)) == binding
  assert binding["home"] == env["HOME"]
  assert binding["xdg"] == {key: env[key] for key in XDG_KEYS}
  assert binding["config_dir"].startswith("../state/")
  assert os.path.normpath(os.path.join(env["HOME"], binding["config_dir"])) == str(identity.home / ".omp")
  paths = binding["native_paths"]
  base = identity.home / ".omp"
  config = base / "profiles" / identity.native_name
  agent = identity.agent_dir
  assert paths == {
    "schema_version": 1, "base_config_root": str(base), "config_root": str(config),
    "agent_dir": str(agent), "root_data": str(config), "root_state": str(config),
    "root_cache": str(config), "agent_data": str(agent), "agent_state": str(agent),
    "agent_cache": str(agent), "base_data": str(base), "base_state": str(base),
    "base_cache": str(base), "auth_db": str(agent / "agent.db"),
    "history_db": str(agent / "history.db"), "models_db": str(agent / "models.db"),
    "sessions": str(agent / "sessions"), "blobs": str(agent / "blobs"),
    "secret_placeholder_key": str(agent / "secret-placeholder.key"),
    "session_owners": str(base / "run/session-owners"),
    "global_daemon_root": str(base / "run/daemons/global"),
    "daemon_root": str(config / "run/daemons"),
    "provider_inflight_root": str(config / "run/provider-inflight"),
    "plugins_root": str(config / "plugins"),
    "marketplaces_registry": str(config / "marketplaces.json"),
  }
  assert validate_execution_environment(identity, binding, env) == binding


def test_unset_xdg_is_none_and_other_environment_is_not_read(environment):
  identity, env = environment

  class PathsOnly:
    def get(self, key):
      assert key in ("HOME", *XDG_KEYS)
      return env["HOME"] if key == "HOME" else None

  binding = capture_execution_environment(identity, PathsOnly())
  assert binding["xdg"] == {key: None for key in XDG_KEYS}
  overridden = {"HOME": env["HOME"], "PI_CONFIG_DIR": "malicious", "TOKEN": object()}
  assert capture_execution_environment(identity, overridden) == binding


@pytest.mark.parametrize("key", ["XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"])
@pytest.mark.parametrize("profile", [False, True])
def test_xdg_alternatives_rejected_before_and_after_binding(environment, key, profile):
  identity, env = environment
  binding = capture_execution_environment(identity, env)
  target = Path(env[key]) / "omp"
  if profile:
    target = target / "profiles" / identity.native_name
  target.mkdir(parents=True)
  with pytest.raises(Conflict) as error:
    capture_execution_environment(identity, env)
  assert error.value.exit_code == 4
  with pytest.raises(Conflict):
    validate_execution_environment(identity, binding, env)


def test_config_home_does_not_fake_data_or_lease_classification(environment):
  identity, env = environment
  before = capture_execution_environment(identity, env)
  (Path(env["XDG_CONFIG_HOME"]) / "omp/profiles" / identity.native_name).mkdir(parents=True)
  assert capture_execution_environment(identity, env) == before


@pytest.mark.parametrize("key", ["HOME", *XDG_KEYS])
def test_changed_caller_path_rejected(environment, key):
  identity, env = environment
  binding = capture_execution_environment(identity, env)
  changed = {**env, key: env[key] + "-changed"}
  with pytest.raises(Conflict):
    validate_execution_environment(identity, binding, changed)


@pytest.mark.parametrize("value", ["", "relative", "bad\0path", 4])
@pytest.mark.parametrize("key", ["HOME", *XDG_KEYS])
def test_invalid_environment_paths_rejected(environment, key, value):
  identity, env = environment
  with pytest.raises(Conflict) as error:
    capture_execution_environment(identity, {**env, key: value})
  assert str(error.value) == "OMP执行环境绑定无效或原生路径发生冲突"


@pytest.mark.parametrize("mutation", [
  lambda b: b.update(extra="sensitive-value"),
  lambda b: b.update(schema_version=True),
  lambda b: b.update(home="relative"),
  lambda b: b.update(config_dir="/absolute"),
  lambda b: b.update(config_dir="../other-state"),
  lambda b: b["native_paths"].update(auth_db="/sensitive-value"),
  lambda b: b["native_paths"].update(extra="sensitive-value"),
  lambda b: b["native_paths"].update(schema_version=True),
  lambda b: b["xdg"].update(extra="sensitive-value"),
  lambda b: b.update(xdg=[]),
])
def test_tampered_binding_rejected_without_input_disclosure(environment, mutation):
  identity, env = environment
  binding = copy.deepcopy(capture_execution_environment(identity, env))
  mutation(binding)
  with pytest.raises(Conflict) as error:
    validate_execution_environment(identity, binding, env)
  assert "sensitive-value" not in str(error.value)


def test_predict_uses_profile_and_base_existence_independently(environment):
  identity, env = environment
  binding = capture_execution_environment(identity, env)
  app = Path(env["XDG_DATA_HOME"]) / "omp"
  calls = []

  def exists(path):
    calls.append(path)
    return path == app

  paths = predict_native_paths(identity, binding["home"], binding["config_dir"], binding["xdg"], exists=exists)
  assert paths["base_data"] == str(app)
  assert paths["agent_data"] == str(identity.agent_dir)
  assert paths["root_data"] == str(identity.agent_dir.parent)
  assert set(calls) == {Path(env[key]) / suffix
    for key in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")
    for suffix in ("omp", "omp/profiles/" + identity.native_name)}


@pytest.mark.parametrize("category", ["data", "state", "cache"])
def test_predict_profile_root_flattens_agent_directory(environment, category):
  identity, env = environment
  binding = capture_execution_environment(identity, env)
  app = Path(env["XDG_" + category.upper() + "_HOME"]) / "omp"
  profile = app / "profiles" / identity.native_name
  paths = predict_native_paths(identity, binding["home"], binding["config_dir"], binding["xdg"],
    exists=lambda path: path in (app, profile))
  assert paths["agent_" + category] == str(profile)
  assert paths["root_" + category] == str(profile)
  assert paths["base_" + category] == str(app)
  if category == "data":
    assert paths["auth_db"] == str(profile / "agent.db")
    assert paths["plugins_root"] == str(profile / "plugins")
  elif category == "state":
    assert paths["secret_placeholder_key"] == str(profile / "secret-placeholder.key")
    assert paths["session_owners"] == str(app / "run/session-owners")


def test_symlink_hidden_by_parent_normalization_is_rejected(environment, tmp_path):
  identity, env = environment
  link = tmp_path / "linked"
  destination = tmp_path / "nested/destination"
  destination.mkdir(parents=True)
  link.symlink_to(destination, target_is_directory=True)
  with pytest.raises(Conflict):
    capture_execution_environment(identity, {**env, "HOME": str(link) + "/../home"})


def test_capture_does_not_create_or_read_files(environment, monkeypatch, sentinel_factory):
  identity, env = environment
  identity.agent_dir.mkdir(parents=True)
  for name in ("agent.db", "history.db", "secret-placeholder.key"):
    (identity.agent_dir / name).write_bytes(b"synthetic-private-body")
  sentinel = sentinel_factory(identity.instance_root)

  def forbidden(*args, **kwargs):
    raise AssertionError("helper accessed file contents or created a directory")

  with monkeypatch.context() as patch:
    patch.setattr(Path, "open", forbidden)
    patch.setattr(Path, "read_bytes", forbidden)
    patch.setattr(Path, "read_text", forbidden)
    patch.setattr(Path, "mkdir", forbidden)
    binding = capture_execution_environment(identity, env)
    validate_execution_environment(identity, binding, env)
  sentinel.assert_unchanged()


@pytest.mark.parametrize("location", ["home", "xdg", "identity", "ancestor"])
def test_symlink_paths_rejected(environment, location, tmp_path):
  identity, env = environment
  destination = tmp_path / "destination"
  destination.mkdir()
  if location == "home":
    link = tmp_path / "linked-home"
    env = {**env, "HOME": str(link)}
  elif location == "xdg":
    link = Path(env["XDG_RUNTIME_DIR"])
  elif location == "identity":
    link = identity.home
  else:
    link = identity.instance_root.parent
  link.parent.mkdir(parents=True, exist_ok=True)
  link.symlink_to(destination, target_is_directory=True)
  with pytest.raises(Conflict):
    capture_execution_environment(identity, env)
