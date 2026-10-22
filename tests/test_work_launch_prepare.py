"""结构化启动只准备固定目录与所选 launcher，不执行真实进程。"""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from termcfg.errors import TermcfgError
from termcfg import work_config as config
from termcfg.work_state import LAUNCH_SCHEMA, launch_digest


@pytest.fixture
def starts(tmp_path):
  workspace = tmp_path / "workspace"
  home = tmp_path / "captured-home"
  workspace.mkdir()
  home.mkdir()
  return workspace, home


def definition(launcher="shell", **fields):
  return {"label": "Literal label", "launcher": launcher, **fields}


def executable(tmp_path, name):
  path = tmp_path / name
  path.write_bytes(b"synthetic executable marker\n")
  path.chmod(0o700)
  return str(path)


@pytest.mark.parametrize("cwd", [None, {"from": "workspace_start"}, {"path": "."}])
def test_type_start_defaults_to_fixed_workspace(starts, cwd):
  workspace, home = starts
  options = {} if cwd is None else {"cwd": cwd}
  assert config.resolve_type_start(definition(**options), workspace, home) == workspace.resolve()


@pytest.mark.parametrize("form", ["relative", "home", "absolute"])
def test_type_start_resolves_literal_paths_without_evaluation(starts, form, monkeypatch):
  workspace, home = starts
  parent = home if form == "home" else workspace
  directory = parent / "中文 $() ~literal"
  directory.mkdir()
  value = "~/" + directory.name if form == "home" else str(directory) if form == "absolute" else directory.name
  monkeypatch.chdir(home)
  assert config.resolve_type_start(definition(cwd={"path": value}), workspace, home) == directory.resolve()


@pytest.mark.parametrize("fields", [
  {"unknown": "forbidden"}, {"cwd": {}}, {"cwd": {"from": "caller"}},
  {"cwd": {"from": "workspace_start", "path": "x"}}, {"cwd": {"path": ""}},
  {"cwd": {"path": "bad\nprivate"}}, {"cwd": {"path": "bad\ud800private"}},
])
def test_type_start_rejects_unknown_mixed_or_unsafe_fields(starts, fields):
  with pytest.raises(TermcfgError) as error:
    config.resolve_type_start(definition(**fields), *starts)
  assert error.value.code == 2 and "private" not in str(error.value)


def test_type_start_missing_directory_never_falls_back_or_creates(starts):
  workspace, home = starts
  with pytest.raises(TermcfgError):
    config.resolve_type_start(definition(cwd={"path": "missing"}), workspace, home)
  assert not (workspace / "missing").exists()


def test_capture_paths_preserves_home_alias_and_omitted_paths(starts, tmp_path, monkeypatch):
  workspace, home = starts
  alias = tmp_path / "home-alias"
  alias.symlink_to(home, target_is_directory=True)
  monkeypatch.setenv("HOME", str(alias) + "/")
  for key in config.PATH_NAMES[1:]:
    monkeypatch.delenv(key, raising=False)
  monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "not-created"))
  monkeypatch.setenv("SYNTHETIC_OTHER", "do not capture")
  result = config.capture_paths()
  assert set(result) == set(config.PATH_NAMES)
  assert result["HOME"] == str(alias) + "/"
  assert result["XDG_CONFIG_HOME"] == str(home / "not-created")
  assert all(result[key] is None for key in config.PATH_NAMES[2:])
  assert not (home / "not-created").exists()


@pytest.mark.parametrize("value", ["", "relative", "/bad\nprivate", "/bad\ud800private"])
def test_capture_paths_rejects_invalid_home_without_echo(value):
  with pytest.raises(TermcfgError) as error:
    config.capture_paths(home=value)
  assert error.value.code == 2 and "private" not in str(error.value)


def test_capture_paths_rejects_missing_home_and_parent_components(starts, monkeypatch):
  workspace, home = starts
  for value in (str(home / "missing"), str(home / "..")):
    with pytest.raises(TermcfgError):
      config.capture_paths(home=value)
  monkeypatch.setenv("XDG_DATA_HOME", str(home / ".." / "data"))
  with pytest.raises(TermcfgError):
    config.capture_paths(home=home)


def test_bound_paths_restores_only_path_variables_after_failure(starts, monkeypatch):
  workspace, home = starts
  monkeypatch.setenv("HERDR_PANE_ID", "native-pane")
  monkeypatch.setenv("SYNTHETIC_UNRELATED", "unchanged")
  before = {key: os.environ.get(key) for key in config.PATH_NAMES}
  paths = {key: None for key in config.PATH_NAMES}
  paths["HOME"] = str(home)
  with pytest.raises(RuntimeError):
    with config.bound_paths(paths):
      assert os.environ["HOME"] == str(home)
      assert all(key not in os.environ for key in config.PATH_NAMES[1:])
      assert os.environ["HERDR_PANE_ID"] == "native-pane"
      raise RuntimeError("synthetic boundary failure")
  assert {key: os.environ.get(key) for key in config.PATH_NAMES} == before
  assert os.environ["SYNTHETIC_UNRELATED"] == "unchanged"
  assert os.environ["HERDR_PANE_ID"] == "native-pane"


def test_bound_paths_rejects_extra_fields_before_mutating_environment(starts):
  before = dict(os.environ)
  with pytest.raises(TermcfgError):
    with config.bound_paths({"HOME": str(starts[1]), "HERDR_PANE_ID": "override"}):
      pytest.fail("unvalidated boundary entered")
  assert dict(os.environ) == before


@pytest.mark.parametrize("launcher", ["shell", "editor", "codex"])
def test_prepare_launch_only_checks_selected_launcher(starts, tmp_path, monkeypatch, launcher):
  workspace, home = starts
  tool = executable(tmp_path, "literal 中文 '$()`")
  monkeypatch.setenv("SHELL", tool)
  monkeypatch.setattr(config, "_prepared_agent", lambda *a: pytest.fail("unused agent prepared"))
  settings = config.WorkSettings(tmp_path / "local.toml", "fixture-herdr", "main",
    editor=tool if launcher == "editor" else None, codex_binary=tool if launcher == "codex" else None)
  result = config.prepare_launch(settings, definition(launcher), workspace, home=home)
  assert Draft202012Validator(LAUNCH_SCHEMA).is_valid(result["launch"])
  assert result["launch"]["argv"] == [tool, *(["--no-daemon"] if launcher == "codex" else [])]
  assert result["cwd"] == str(workspace.resolve()) and result["captured_home"] == str(home)
  assert result["launch"]["runtime"] is None
  assert result["digest"] == launch_digest(result["cwd"], result["captured_home"], result["launch"])
  assert result["default"] is None and result["sequence"] == 0 and result["instances"] == {}
  assert config.PAYLOAD_ENV_V2 == "ROTOM_WORK_LAUNCH_V2"


def test_fixed_shell_keeps_original_shell_and_paths_but_detects_cwd_drift(starts, tmp_path, monkeypatch):
  workspace, home = starts
  original = executable(tmp_path, "shell-original")
  later = executable(tmp_path, "shell-later")
  monkeypatch.setenv("SHELL", original)
  settings = config.WorkSettings(tmp_path / "local", "fixture-herdr", "main")
  fixed = config.prepare_launch(settings, definition(), workspace, home=home)
  before = deepcopy(fixed)
  monkeypatch.setenv("SHELL", later)
  monkeypatch.setenv("HOME", str(workspace))
  monkeypatch.setenv("XDG_CONFIG_HOME", str(workspace / "later-config"))
  rebound = config.prepare_launch(settings, definition(), workspace, fixed=fixed)
  assert rebound == fixed and fixed == before
  (workspace / "changed").mkdir()
  changed = config.prepare_launch(settings, definition(cwd={"path": "changed"}), workspace, fixed=fixed)
  assert changed["launch"] == fixed["launch"] and changed["digest"] != fixed["digest"]


def test_fixed_editor_recomputes_current_selection_without_overwriting_binding(starts, tmp_path):
  workspace, home = starts
  first = config.WorkSettings(tmp_path / "local", "fixture-herdr", "main", editor=executable(tmp_path, "editor-first"))
  later = config.WorkSettings(tmp_path / "local", "fixture-herdr", "main", editor=executable(tmp_path, "editor-later"))
  fixed = config.prepare_launch(first, definition("editor"), workspace, home=home)
  requested = config.prepare_launch(later, definition("editor"), workspace, fixed=fixed)
  assert requested["launch"]["argv"] != fixed["launch"]["argv"]
  assert requested["digest"] != fixed["digest"]


@pytest.mark.parametrize("role", ["pi", "dsh"])
def test_prepare_agent_uses_captured_path_boundary_and_explicit_cli(starts, tmp_path, monkeypatch, role):
  workspace, home = starts
  runtime = {"generation": "a" * 64, "identity": "synthetic-runtime", "policy": "caller"}
  observed = []
  def prepared(settings, selected, profile):
    observed.append((selected, profile, os.environ["HOME"]))
    return deepcopy(runtime)
  monkeypatch.setattr(config, "_prepared_agent", prepared)
  settings = config.WorkSettings(tmp_path / "local", "fixture-herdr", "main",
    pi_profile="pi-explicit", dsh_profile="dsh-explicit")
  result = config.prepare_launch(settings, definition(role), workspace, home=home)
  assert observed == [(role, role + "-explicit", str(home))]
  assert result["launch"]["runtime"] == runtime
  assert result["launch"]["argv"] == [str(settings.repo_root / "agentcfg"), "--local", str(settings.local_path),
    "--profile", role + "-explicit", "run", role, "--cwd", str(workspace)]
  assert result["launch"]["paths"]["HOME"] == str(home)


@pytest.mark.parametrize("runtime", [None, {}, {"generation": "a" * 64, "identity": "runtime", "policy": "developer"},
  {"generation": None, "identity": "runtime", "policy": "legacy"},
  {"generation": "a" * 64, "identity": "hidden\nprivate", "policy": "caller"},
  {"generation": "a" * 64 + "\n", "identity": "runtime", "policy": "caller"},
  {"generation": "a" * 64, "identity": "runtime", "policy": "caller", "raw": "private"}])
def test_structured_agent_requires_complete_runtime_receipt(starts, tmp_path, monkeypatch, runtime):
  monkeypatch.setattr(config, "_prepared_agent", lambda *a: runtime)
  settings = config.WorkSettings(tmp_path / "local", "fixture-herdr", "main", pi_profile="explicit")
  with pytest.raises(TermcfgError) as error:
    config.prepare_launch(settings, definition("pi"), starts[0], home=starts[1])
  assert error.value.code == 5


def test_prepared_agent_returns_only_whitelisted_runtime_identity(starts, tmp_path, monkeypatch):
  from agentcfg.execution_environment import caller_paths
  workspace = SimpleNamespace(agent="pi", state_root=tmp_path / "state", binding={"synthetic": True},
    resolved=SimpleNamespace(data={"machine": {}}), adapter=SimpleNamespace(),
    backend=SimpleNamespace(status=lambda *a: "installed"))
  monkeypatch.setattr("agentcfg.workspace.load_workspace", lambda *a, **k: workspace)
  class State:
    def __init__(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self, name): return None
  monkeypatch.setattr("agentcfg.storage.Tree", State)
  raw = "synthetic-private-contract-canary"
  current = {"generation": "a" * 64, "binding": workspace.binding, "launch": {
    "machine": {}, "lock_identity": "runtime", "runtime_identity": "prepared-runtime",
    "environment_version": 1, "environment_policy": "caller", "caller_paths": caller_paths(),
    "argv": [raw], "adapter_binding": {"opaque": raw}}}
  monkeypatch.setattr("agentcfg.deployment.read_state", lambda *a: {"current": deepcopy(current)})
  result = config._prepared_agent(config.WorkSettings(tmp_path / "local", "fixture-herdr", "main"), "pi", "explicit")
  assert result == {"generation": "a" * 64, "identity": "prepared-runtime", "policy": "caller"}
  assert raw not in json.dumps(result)
