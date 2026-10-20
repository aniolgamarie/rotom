"""新pane只调用准备好的入口，不解析秘密或改变配方。"""

from pathlib import Path

import pytest

from termcfg.errors import TermcfgError
from termcfg.work_config import WorkSettings, prepare_tool


def executable(tmp_path, name):
  p = tmp_path / name
  p.write_text("synthetic")
  p.chmod(0o700)
  return str(p)


def test_editor_single_literal_no_credentials_or_review(tmp_path, monkeypatch):
  from agentcfg.secrets import SecretStore
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  editor = executable(tmp_path, "Avalon profile 中文 '$`")
  settings = WorkSettings(tmp_path / "local.toml", "herdr", "main", editor=editor)
  assert prepare_tool(settings, "edit", tmp_path) == [editor]


def test_codex_policy_does_not_change_global_environment(tmp_path, monkeypatch):
  binary = executable(tmp_path, "codex")
  settings = WorkSettings(tmp_path / "local.toml", "herdr", "main", codex_binary=binary)
  assert prepare_tool(settings, "codex", tmp_path) == [binary, "--no-daemon"]
  other = WorkSettings(tmp_path / "local.toml", "herdr", "main", codex_binary=binary, codex_daemon=True)
  assert prepare_tool(other, "codex", tmp_path) == [binary]


@pytest.mark.parametrize("role", ["pi", "dsh"])
def test_agent_selectors_and_cwd_are_explicit(tmp_path, monkeypatch, role):
  monkeypatch.setattr("termcfg.work_config._prepared_agent", lambda *a: None)
  settings = WorkSettings(tmp_path / "local.toml", "herdr", "main",
    pi_profile="pi-explicit", dsh_profile="dsh-explicit")
  command = prepare_tool(settings, role, tmp_path)
  assert command == [str(settings.repo_root / "agentcfg"), "--local", str(settings.local_path),
    "--profile", role + "-explicit", "run", role, "--cwd", str(tmp_path)]


@pytest.mark.parametrize("role", ["edit", "pi", "dsh", "codex"])
def test_missing_choice_does_not_fall_back_to_default(tmp_path, role):
  with pytest.raises(TermcfgError) as error:
    prepare_tool(WorkSettings(tmp_path / "local", "herdr", "main"), role, tmp_path)
  assert error.value.code == 2


def test_missing_preparation_fails_before_pending_or_tab(tmp_path):
  from termcfg.herdr import Deadline
  from termcfg.work import enter_project, open_role
  from work_helpers import FakeHerdr
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  with pytest.raises(TermcfgError):
    open_role(api, settings, "pi", caller_id=next(iter(api.panes)))
  assert "rw_pending" not in api.workspaces[ws["workspace_id"]]["tokens"]
  assert not any(m == "tab.create" for m, _ in api.requests)


@pytest.mark.parametrize("wrong_agent,pending,installed,expected", [
  (True, False, True, 2), (False, True, True, 4), (False, False, False, 5), (False, False, True, None)])
@pytest.mark.parametrize("runtime_identity", [None, "saved-runtime"])
@pytest.mark.parametrize("has_validator", [False, True])
def test_prepared_agent_uses_readonly_binding_and_runtime(tmp_path, monkeypatch, wrong_agent, pending, installed, expected, runtime_identity, has_validator):
  from types import SimpleNamespace
  from termcfg.work_config import _prepared_agent
  from agentcfg.secrets import SecretStore
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  calls = []
  adapter_binding = {"synthetic": "saved-adapter"}
  def validate_binding(candidate, saved):
    assert candidate is workspace and saved is adapter_binding
    calls.append("adapter")
  def runtime_status(candidate, identity):
    assert candidate is workspace
    calls.append(("runtime", identity))
    return "installed" if installed else "missing"
  workspace = SimpleNamespace(agent="dsh" if wrong_agent else "pi", state_root=tmp_path / "state",
    resolved=SimpleNamespace(data={"machine": {}}),
    binding={"synthetic": True}, backend=SimpleNamespace(status=runtime_status),
    adapter=SimpleNamespace(**({"validate_runtime_binding": validate_binding} if has_validator else {})))
  monkeypatch.setattr("agentcfg.workspace.load_workspace", lambda *a, **k: workspace)
  class State:
    def __init__(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self, name): return pending
  monkeypatch.setattr("agentcfg.storage.Tree", State)
  contract = {"lock_identity": "synthetic", "machine": {}, "adapter_binding": adapter_binding}
  if runtime_identity is not None:
    contract["runtime_identity"] = runtime_identity
  monkeypatch.setattr("agentcfg.deployment.read_state", lambda *a:
    {"current": {"binding": workspace.binding, "launch": contract}})
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  if expected is None:
    _prepared_agent(settings, "pi", "explicit")
  else:
    with pytest.raises(TermcfgError) as error: _prepared_agent(settings, "pi", "explicit")
    assert error.value.code == expected
  assert calls == ([] if wrong_agent or pending else
    (["adapter"] if has_validator else []) + [("runtime", runtime_identity or "synthetic")])


@pytest.mark.parametrize("adapter_binding", [None, {"synthetic": "stale-adapter"}])
def test_stale_adapter_binding_fails_before_pending_tab_runtime_or_secrets(tmp_path, monkeypatch, adapter_binding):
  from copy import deepcopy
  from types import SimpleNamespace
  from agentcfg.secrets import SecretStore
  from agentcfg.storage import Conflict
  from termcfg.work import enter_project, open_role
  from work_helpers import FakeHerdr
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  checked = []
  def validate_binding(candidate, saved):
    assert candidate is workspace and saved is adapter_binding
    checked.append("adapter")
    raise Conflict("synthetic private binding detail")
  workspace = SimpleNamespace(agent="pi", state_root=tmp_path / "state", binding={"synthetic": True},
    resolved=SimpleNamespace(data={"machine": {}}),
    adapter=SimpleNamespace(validate_runtime_binding=validate_binding),
    backend=SimpleNamespace(status=lambda *a: pytest.fail("runtime access")))
  monkeypatch.setattr("agentcfg.workspace.load_workspace", lambda *a, **k: workspace)
  class State:
    def __init__(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self, name): return None
  monkeypatch.setattr("agentcfg.storage.Tree", State)
  contract = {"lock_identity": "synthetic", "runtime_identity": "saved-runtime", "machine": {}}
  if adapter_binding is not None:
    contract["adapter_binding"] = adapter_binding
  monkeypatch.setattr("agentcfg.deployment.read_state", lambda *a:
    {"current": {"binding": workspace.binding, "launch": contract}})
  api = FakeHerdr()
  enter_project(api, tmp_path)
  before = deepcopy((api.workspaces, api.panes, api.tabs))
  api.requests.clear()
  settings = WorkSettings(tmp_path / "local", "herdr", "main", pi_profile="pi-explicit")
  with pytest.raises(TermcfgError) as error:
    open_role(api, settings, "pi", caller_id=next(iter(api.panes)))
  assert checked == ["adapter"]
  assert error.value.code == 4 and error.value.reason == "work_agent_deployment_conflict"
  assert "private" not in str(error.value) and error.value.__cause__ is None
  assert (api.workspaces, api.panes, api.tabs) == before
  assert not any(method in ("tab.create", "workspace.report_metadata", "pane.report_metadata")
    for method, _ in api.requests)


def test_agent_filesystem_error_does_not_escape_private_exception(tmp_path, monkeypatch):
  from agentcfg.storage import StateError
  from termcfg.work_config import _prepared_agent
  def failed(*a, **k): raise StateError("synthetic private detail")
  monkeypatch.setattr("agentcfg.workspace.load_workspace", failed)
  with pytest.raises(TermcfgError) as error:
    _prepared_agent(WorkSettings(tmp_path / "local", "herdr", "main"), "pi", "explicit")
  assert error.value.code == 6 and "private" not in error.value.reason


@pytest.mark.parametrize("changed", ["environment", "caller_paths"])
def test_changed_environment_or_caller_identity_rejected_before_runtime(tmp_path, monkeypatch, changed):
  from types import SimpleNamespace
  from termcfg.work_config import _prepared_agent
  from agentcfg.execution_environment import caller_paths
  machine = {"environment": {"inherit": []}}
  contract = {"lock_identity": "synthetic", "machine": machine,
    "environment_version": 1, "caller_paths": caller_paths()}
  current = {"environment": {"inherit": ["CUSTOM_BUILD_ROOT"]}} if changed == "environment" else machine
  if changed == "caller_paths": contract["caller_paths"] = {}
  workspace = SimpleNamespace(agent="pi", state_root=tmp_path / "state", binding={"synthetic": True},
    resolved=SimpleNamespace(data={"machine": current}),
    adapter=SimpleNamespace(validate_runtime_binding=lambda *a: pytest.fail("environment drift before adapter")),
    backend=SimpleNamespace(status=lambda *a: pytest.fail("drift must fail before runtime")))
  monkeypatch.setattr("agentcfg.workspace.load_workspace", lambda *a, **k: workspace)
  class State:
    def __init__(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self, name): return None
  monkeypatch.setattr("agentcfg.storage.Tree", State)
  monkeypatch.setattr("agentcfg.deployment.read_state", lambda *a:
    {"current": {"binding": workspace.binding, "launch": contract}})
  with pytest.raises(TermcfgError) as error:
    _prepared_agent(WorkSettings(tmp_path / "local", "herdr", "main"), "pi", "explicit")
  assert error.value.code == 4
