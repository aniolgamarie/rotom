"""用途默认与额外实例固定启动契约；所有原生操作均使用替身。"""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import shutil

import pytest

from termcfg import work, work_config, work_shell
from termcfg.errors import TermcfgError
from test_work_lifecycle import context_case, enter, project_candidate
from test_work_parent_v2 import setup_parent, launch
from test_work_wrapper_v2 import setup_launch, wire


def add_type(case, key="tool", *, launcher="shell", cwd=None):
  template = case.settings.structured["templates"]["trial"]
  definition = {"label": "Tool " + key, "launcher": launcher}
  if cwd is not None:
    definition["cwd"] = cwd
  template["tab_types"][key] = definition
  template["order"].append(key)
  return definition


def open_type(case, caller, key="tool", *, new=False):
  return work.open_type_v2(case.client, case.settings, case.state, key,
    new=new, caller_id=caller["pane_id"], binary=case.settings.herdr_binary)


def typed(case, key="tool"):
  return case.state.bindings()[0]["types"][key]


@pytest.mark.parametrize("launcher", ["shell", "editor", "pi", "dsh", "codex"])
def test_each_launcher_default_and_extra_keep_one_fixed_contract(context_case, monkeypatch, launcher):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  executable = case.tmp / "literal tool 中文"
  executable.write_text("synthetic executable; never run")
  executable.chmod(0o700)
  prepared = []
  def agent(settings, role, profile):
    prepared.append((role, profile))
    return {"generation": "b" * 64, "identity": "synthetic-runtime", "policy": "caller"}
  monkeypatch.setattr(work_config, "_prepared_agent", agent)
  case.settings = replace(case.settings, editor=str(executable), codex_binary=str(executable),
    pi_profile="pi-explicit", dsh_profile="dsh-explicit")
  add_type(case, launcher=launcher)
  default = open_type(case, caller)
  contract = deepcopy(typed(case))
  extra = open_type(case, caller, new=True)
  after = typed(case)
  assert default["pane_id"] != extra["pane_id"]
  assert default["tokens"]["rw2_kind"] == "default"
  assert extra["tokens"]["rw2_kind"] == "extra"
  assert after["default"] == contract["default"] == default["tokens"]["rw2_instance"]
  assert len(after["instances"]) == 2
  for key in ("cwd", "captured_home", "launch", "digest"):
    assert after[key] == contract[key]
  assert after["launch"]["launcher"] == launcher
  assert case.client.call_counts["workspace.create"] == 1
  assert case.client.call_counts["tab.create"] == 2
  if launcher in ("pi", "dsh"):
    assert prepared and set(prepared) == {(launcher, launcher + "-explicit")}
    assert "--cwd" in after["launch"]["argv"]
  else:
    assert prepared == []
  if launcher == "shell":
    assert len(after["launch"]["argv"]) == 1
  if launcher == "codex":
    assert "--no-daemon" in after["launch"]["argv"]


def test_extra_before_default_never_becomes_default(context_case):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  add_type(case)
  extra = open_type(case, caller, new=True)
  before = deepcopy(typed(case))
  assert before["default"] is None
  assert before["instances"][extra["tokens"]["rw2_instance"]]["kind"] == "extra"
  default = open_type(case, caller)
  after = typed(case)
  assert default["pane_id"] != extra["pane_id"]
  assert after["default"] == default["tokens"]["rw2_instance"]
  assert after["instances"][extra["tokens"]["rw2_instance"]] == before["instances"][extra["tokens"]["rw2_instance"]]
  assert after["digest"] == before["digest"] and len(after["instances"]) == 2


def test_relative_home_and_absolute_cwd_remain_fixed_after_caller_changes(context_case, monkeypatch):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  first_home = os.environ["HOME"]
  relative = case.project / "relative"
  home_child = Path(first_home) / "home-child"
  absolute = case.tmp / "absolute"
  for path in (relative, home_child, absolute):
    path.mkdir()
  paths = {"relative": ("relative", relative), "homedir": ("~/home-child", home_child),
    "absolute": (str(absolute), absolute)}
  before = {}
  for key, (value, path) in paths.items():
    add_type(case, key, cwd={"path": value})
    open_type(case, caller, key)
    before[key] = deepcopy(typed(case, key))
    assert before[key]["cwd"] == str(path.resolve())
  later = case.tmp / "later-home"
  later.mkdir()
  monkeypatch.setenv("HOME", str(later))
  monkeypatch.setenv("SHELL", "/synthetic/missing-new-shell")
  monkeypatch.chdir(later)
  case.client.panes[caller["pane_id"]]["cwd"] = str(later)
  for key in paths:
    open_type(case, caller, key, new=True)
    after = typed(case, key)
    assert after["captured_home"] == first_home
    for field in ("cwd", "launch", "digest"):
      assert after[field] == before[key][field]


def test_existing_default_focus_needs_no_executable_or_agent_preparation(context_case, monkeypatch):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  add_type(case)
  first = open_type(case, caller)
  before = deepcopy(typed(case))
  Path(before["launch"]["argv"][0]).unlink()
  def forbidden(*args, **kwargs):
    pytest.fail("focus must not prepare any launcher")
  monkeypatch.setattr(work_config, "prepare_launch", forbidden)
  second = open_type(case, caller)
  assert second["pane_id"] == first["pane_id"]
  assert typed(case) == before and case.client.call_counts["tab.create"] == 1


def test_changed_cwd_focuses_existing_default_but_refuses_extra(context_case):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  definition = add_type(case)
  first = open_type(case, caller)
  before = deepcopy(typed(case))
  other = case.tmp / "other-start"
  other.mkdir()
  definition["cwd"] = {"path": str(other)}
  assert open_type(case, caller)["pane_id"] == first["pane_id"]
  mutations = list(case.client.mutation_calls)
  with pytest.raises(TermcfgError) as error:
    open_type(case, caller, new=True)
  assert error.value.code == 4
  assert case.client.mutation_calls == mutations and typed(case) == before


def test_removed_type_can_focus_its_default_but_cannot_create_extra(context_case):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  add_type(case)
  first = open_type(case, caller)
  before = deepcopy(typed(case))
  template = case.settings.structured["templates"]["trial"]
  del template["tab_types"]["tool"]
  template["order"].remove("tool")
  assert open_type(case, caller)["pane_id"] == first["pane_id"]
  mutations = list(case.client.mutation_calls)
  with pytest.raises(TermcfgError):
    open_type(case, caller, new=True)
  assert case.client.mutation_calls == mutations and typed(case) == before


def test_zero_active_rebind_requires_acceptance_and_preserves_other_types(context_case):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  definition = add_type(case)
  pane = open_type(case, caller)
  del case.client.panes[pane["pane_id"]]
  del case.client.tabs[pane["tab_id"]]
  other = case.tmp / "rebound-start"
  other.mkdir()
  definition["cwd"] = {"path": str(other)}
  before = deepcopy(case.state.bindings()[0])
  mutations = list(case.client.mutation_calls)
  preview = work.rebind_type_v2(case.client, case.settings, case.state, "tool", caller_id=caller["pane_id"])
  assert isinstance(preview, dict)
  assert case.state.bindings()[0] == before and case.client.mutation_calls == mutations
  rebound = work.rebind_type_v2(case.client, case.settings, case.state, "tool",
    accept=True, caller_id=caller["pane_id"])
  assert rebound == typed(case)
  assert rebound["cwd"] == str(other) and rebound["default"] is None and rebound["instances"] == {}
  assert rebound["digest"] != before["types"]["tool"]["digest"]
  assert case.state.bindings()[0]["types"]["problem"] == before["types"]["problem"]
  assert case.client.mutation_calls == mutations


def test_active_type_cannot_be_rebound_even_with_explicit_acceptance(context_case):
  case = context_case
  caller = enter(case, project_candidate(case.project))
  definition = add_type(case)
  open_type(case, caller)
  other = case.tmp / "different-start"
  other.mkdir()
  definition["cwd"] = {"path": str(other)}
  before = deepcopy(case.state.bindings()[0])
  mutations = list(case.client.mutation_calls)
  with pytest.raises(TermcfgError) as error:
    work.rebind_type_v2(case.client, case.settings, case.state, "tool",
      accept=True, caller_id=caller["pane_id"])
  assert error.value.code == 4
  assert case.state.bindings()[0] == before and case.client.mutation_calls == mutations


@pytest.mark.parametrize("module", ["work_projects.py", "work_edit.py", "work_ui.py"])
@pytest.mark.parametrize("side", ["parent", "wrapper"])
def test_introduced_launch_modules_tampering_blocks_commit_or_exec(tmp_path, monkeypatch, module, side):
  relative = "src/termcfg/" + module
  assert relative in work.LAUNCH_FILES
  source = tmp_path / "synthetic-source"
  for name in work.LAUNCH_FILES:
    target = source / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work_config.ROOT / name, target)
  original_digest = work.source_digest
  before = original_digest(source)
  def tamper():
    with (source / relative).open("ab") as stream:
      stream.write(b"\n# synthetic source change\n")
    assert original_digest(source) != before
  if side == "parent":
    client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
    settings = replace(settings, repo_root=source)
    client.barriers[("workspace.create", "after", 1)] = lambda *args: tamper()
    try:
      with pytest.raises(TermcfgError) as error:
        launch(client, settings, state, binding)
      assert error.value.code == 4 and "source_changed" in str(error.value)
      assert client.call_counts["workspace.create"] == 1
      assert all(not pane["tokens"].get("rw2_commit") for pane in client.panes.values())
      assert state.bindings() == [] and state.pending(binding["owner"])
    finally:
      state.close()
  else:
    value, settings, client, state, execute, pane = setup_launch(tmp_path, monkeypatch)
    assert value["source_digest"] == before
    tamper()
    monkeypatch.setattr(work, "source_digest", lambda *args: original_digest(source))
    mutations = list(client.mutation_calls)
    try:
      with pytest.raises(TermcfgError) as error:
        work_shell.launch_payload_v2(wire(value), client=client, settings=settings, execute=execute)
      assert error.value.code == 4 and "source_changed" in str(error.value)
      assert not execute.calls and client.mutation_calls == mutations
      assert state.read("receipts", value["op"])["phase"] == "dispatched"
    finally:
      state.close()
