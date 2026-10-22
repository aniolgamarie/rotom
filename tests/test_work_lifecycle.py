"""独立上下文的进入、身份与只读恢复；复用已验证的假原生握手。"""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from termcfg import work, work_config
from termcfg.errors import TermcfgError
from termcfg.work_projects import Candidate
from termcfg.work_state import WorkState, context_owner
from work_helpers import FakeHerdr
from test_work_parent_v2 import setup_parent


@pytest.fixture
def context_case(tmp_path, monkeypatch):
  client, settings, state, binding = setup_parent(tmp_path, monkeypatch)
  settings.structured.update(model="structured-v1", herdr_binary=settings.herdr_binary,
    session=settings.session, include_rotom=False, sources=[], workspaces=[])
  try:
    yield SimpleNamespace(client=client, settings=settings, state=state,
      project=Path(binding["context"]["key"]), tmp=tmp_path)
  finally:
    state.close()


def project_candidate(path, *, mode="directory", title=None):
  path = Path(path).resolve()
  return Candidate("project", str(path), title or path.name, "trial", "explicit", mode, str(path))


def named_candidate(identifier, *, title="Investigation", start=None):
  return Candidate("named", identifier, title, "trial", "explicit", start_path=str(start) if start is not None else None)


def enter(case, candidate, *, client=None, state=None):
  entries = case.settings.structured["workspaces"]
  if candidate.kind == "project":
    entry = {"kind": "project", "path": candidate.key, "mode": candidate.mode, "template": candidate.template}
  else:
    entry = {"kind": "named", "id": candidate.key, "title": candidate.title, "template": candidate.template}
    if candidate.start_path is not None:
      entry["start_path"] = candidate.start_path
  key = "path" if candidate.kind == "project" else "id"
  existing = [index for index, item in enumerate(entries)
    if item["kind"] == candidate.kind and item.get(key) == entry[key]]
  if existing:
    entries[existing[0]] = entry
  else:
    entries.append(entry)
  return work.enter_context_v2(client or case.client, case.settings, state or case.state,
    candidate, binary=case.settings.herdr_binary)


def test_directory_context_creates_one_ordinary_workspace_and_one_initial_default(context_case):
  case = context_case
  pane = enter(case, project_candidate(case.project))
  bindings = case.state.bindings()
  assert len(bindings) == 1 and bindings[0]["workspace_start"] == str(case.project)
  assert bindings[0]["context"] == {"kind": "project", "key": str(case.project)}
  assert bindings[0]["workspace_id"] == pane["workspace_id"]
  assert case.client.call_counts["workspace.create"] == 1 and case.client.call_counts["tab.create"] == 0
  assert len(case.client.panes) == len(case.client.tabs) == 1
  assert bindings[0]["types"]["problem"]["default"]
  assert not any(method.startswith("worktree.") for method, _ in case.client.requests)


def test_checkout_and_two_gitfile_worktrees_remain_independent(context_case):
  case = context_case
  checkout = case.project
  (checkout / ".git").mkdir()
  paths = [checkout]
  for name in ("copy-a", "copy-b"):
    path = case.tmp / name
    path.mkdir()
    (path / ".git").write_text("gitdir: /synthetic/common-git/worktrees/" + name + "\n")
    paths.append(path)
  panes = [enter(case, project_candidate(path, mode="git")) for path in paths]
  assert len({pane["workspace_id"] for pane in panes}) == 3
  assert {item["context"]["key"] for item in case.state.bindings()} == {str(path) for path in paths}
  assert case.client.call_counts["workspace.create"] == 3 and not any(method.startswith("worktree.") for method, _ in case.client.requests)
  (checkout / ".git" / "HEAD").write_text("ref: refs/heads/another-synthetic-branch\n")
  again = enter(case, project_candidate(checkout, mode="git"))
  assert again["workspace_id"] == panes[0]["workspace_id"]
  assert case.client.call_counts["workspace.create"] == 3


def test_named_ids_sharing_home_and_project_at_same_path_are_distinct(context_case):
  case = context_case
  home = Path(os.environ["HOME"])
  panes = [enter(case, named_candidate(identifier)) for identifier in ("case-a", "case-b")]
  panes.append(enter(case, project_candidate(home)))
  bindings = case.state.bindings()
  assert len({pane["workspace_id"] for pane in panes}) == len(bindings) == 3
  assert {item["workspace_start"] for item in bindings} == {str(home)}
  assert {(item["context"]["kind"], item["context"]["key"]) for item in bindings} == {
    ("named", "case-a"), ("named", "case-b"), ("project", str(home))}


def test_same_named_id_on_different_endpoints_has_separate_owner(context_case):
  case = context_case
  candidate = named_candidate("case-a")
  enter(case, candidate)
  other = FakeHerdr(str(case.tmp / "other-native" / "api.sock"), version="v2")
  with WorkState(other.socket_path, other.identity, root=case.state.base, create=True) as other_state:
    enter(case, candidate, client=other, state=other_state)
    assert case.state.bindings()[0]["owner"] != other_state.bindings()[0]["owner"]
    assert case.client.call_counts["workspace.create"] == other.call_counts["workspace.create"] == 1


def test_socket_alias_reuses_canonical_namespace_without_duplicate_creation(context_case):
  case = context_case
  candidate = named_candidate("case-a")
  first = enter(case, candidate)
  alias = case.tmp / "endpoint-alias"
  alias.symlink_to(case.tmp, target_is_directory=True)
  socket_alias = alias / "native" / "api.sock"
  with WorkState(socket_alias, case.client.identity, root=case.state.base, create=True) as aliased:
    second = enter(case, candidate, state=aliased)
    assert aliased.root == case.state.root and second["pane_id"] == first["pane_id"]
  assert case.client.call_counts["workspace.create"] == 1


def test_named_first_home_is_frozen_across_home_title_and_runtime_cwd_changes(context_case, monkeypatch):
  case = context_case
  home = os.environ["HOME"]
  first = enter(case, named_candidate("case-a", title="Original"))
  before = deepcopy(case.state.bindings()[0])
  later_home = case.tmp / "later-home"
  later_home.mkdir()
  monkeypatch.setenv("HOME", str(later_home))
  monkeypatch.setenv("SHELL", str(case.tmp / "missing-later-shell"))
  case.client.workspaces[first["workspace_id"]]["label"] = "Native title"
  case.client.panes[first["pane_id"]]["cwd"] = str(later_home)
  second = enter(case, named_candidate("case-a", title="Updated presentation"))
  after = case.state.bindings()[0]
  assert second["pane_id"] == first["pane_id"] and case.client.call_counts["workspace.create"] == 1
  assert after["workspace_start"] == after["captured_home"] == home
  assert after["types"] == before["types"]


def test_missing_explicit_named_start_refuses_without_intent_or_fallback(context_case):
  case = context_case
  missing = case.tmp / "missing-start"
  with pytest.raises(TermcfgError) as error:
    enter(case, named_candidate("case-a", start=missing))
  assert error.value.code == 2 and not missing.exists()
  assert case.state.bindings() == [] and case.state.intents() == []
  assert case.client.call_counts["workspace.create"] == 0


@pytest.mark.parametrize("launcher", ["editor", "pi", "dsh"])
def test_arbitrary_initial_editor_or_agent_has_no_bootstrap_replacement(context_case, monkeypatch, launcher):
  case = context_case
  tool = case.tmp / "literal editor 中文"
  tool.write_bytes(b"synthetic executable; never run")
  tool.chmod(0o700)
  runtime = {"generation": "a" * 64, "identity": "synthetic-runtime", "policy": "caller"}
  prepared = []
  def agent(settings, role, profile):
    prepared.append((role, profile))
    return deepcopy(runtime)
  monkeypatch.setattr(work_config, "_prepared_agent", agent)
  case.settings = replace(case.settings, editor=str(tool), pi_profile="pi-explicit", dsh_profile="dsh-explicit")
  case.settings.structured["templates"]["trial"]["tab_types"]["problem"]["launcher"] = launcher
  pane = enter(case, project_candidate(case.project))
  typed = case.state.bindings()[0]["types"]["problem"]
  assert typed["launch"]["launcher"] == launcher
  assert case.client.call_counts["workspace.create"] == 1 and case.client.call_counts["tab.create"] == 0
  assert len(case.client.tabs) == len(case.client.panes) == 1
  assert pane["tokens"]["rw2_type"] == "problem"
  if launcher == "editor":
    assert prepared == []
  else:
    assert prepared and set(prepared) == {(launcher, launcher + "-explicit")}


@pytest.mark.parametrize("change", ["marker-loss", "terminal-reused", "workspace-moved"])
def test_current_identity_conflicts_never_recreate_or_adopt(context_case, change):
  case = context_case
  candidate = named_candidate("case-a")
  pane = enter(case, candidate)
  assert work.current_binding_v2(case.client, case.state, pane["pane_id"])["context"]["key"] == "case-a"
  if change == "marker-loss":
    case.client.workspaces[pane["workspace_id"]]["tokens"] = {}
    case.client.panes[pane["pane_id"]]["tokens"] = {}
  elif change == "terminal-reused":
    case.client.panes[pane["pane_id"]]["terminal_id"] = "reused-terminal"
  else:
    foreign = case.client.request("workspace.create", {"cwd": str(case.project), "label": "Native foreign",
      "focus": False, "env": {}})
    case.client.panes[pane["pane_id"]]["workspace_id"] = foreign["workspace"]["workspace_id"]
  before = len(case.client.mutation_calls)
  creates = case.client.call_counts["workspace.create"]
  with pytest.raises(TermcfgError) as error:
    work.current_binding_v2(case.client, case.state, pane["pane_id"])
  assert error.value.code == 4
  with pytest.raises(TermcfgError):
    enter(case, candidate)
  assert case.client.call_counts["workspace.create"] == creates and case.client.call_counts["tab.create"] == 0
  assert len(case.client.mutation_calls) == before


def test_lost_initial_reply_retains_unknown_and_blocks_same_context_retry(context_case):
  case = context_case
  candidate = named_candidate("case-a")
  case.client.fail("workspace.create", when="after", error=TermcfgError(4, "synthetic reply lost"))
  for _ in range(2):
    with pytest.raises(TermcfgError) as error:
      enter(case, candidate)
    assert error.value.code == 4
  owner = context_owner(case.client.socket_path, "named", "case-a")
  assert case.state.pending(owner) and case.state.load_binding(owner) is None
  assert case.client.call_counts["workspace.create"] == 1
  assert case.client.call_counts["pane.report_metadata"] == 0


def test_lifecycle_report_is_json_and_readonly_with_unresolved_receipts(context_case, sentinel_factory):
  case = context_case
  case.client.fail("workspace.create", when="after", error=TermcfgError(4, "synthetic reply lost"))
  with pytest.raises(TermcfgError):
    enter(case, named_candidate("case-a"))
  sentinel = sentinel_factory(case.state.base)
  before = len(case.client.mutation_calls)
  report = work.lifecycle_report_v2(case.client, case.state)
  assert isinstance(report, dict)
  json.dumps(report, allow_nan=False)
  assert len(case.client.mutation_calls) == before
  sentinel.assert_unchanged()


def test_unresolved_context_does_not_block_unrelated_named_context(context_case):
  case = context_case
  case.client.fail("workspace.create", when="after", occurrence=1, error=TermcfgError(4, "synthetic reply lost"))
  with pytest.raises(TermcfgError):
    enter(case, named_candidate("unknown-context"))
  pane = enter(case, named_candidate("independent-context"))
  assert pane["tokens"]["rw2_phase"] == "accepted"
  assert case.client.call_counts["workspace.create"] == 2
  assert case.state.pending(context_owner(case.client.socket_path, "named", "unknown-context"))


def native_caller(case, workspace_id):
  return case.client.request("tab.create", {"workspace_id": workspace_id, "cwd": str(case.project),
    "label": "Native", "focus": False, "env": {}})["root_pane"]["pane_id"]


@pytest.mark.parametrize("absent", ["closed", "moved"])
def test_proven_closed_or_moved_default_is_replaced_without_touching_old_pane(context_case, absent):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  caller = native_caller(case, original["workspace_id"])
  old = deepcopy(case.client.panes[original["pane_id"]])
  if absent == "closed":
    del case.client.panes[original["pane_id"]]
  else:
    target = case.client.request("workspace.create", {"cwd": str(case.project), "label": "Other", "focus": False, "env": {}})
    case.client.panes[original["pane_id"]]["workspace_id"] = target["workspace"]["workspace_id"]
    old = deepcopy(case.client.panes[original["pane_id"]])
  pane = work.open_type_v2(case.client, case.settings, case.state, "problem", caller_id=caller,
    binary=case.settings.herdr_binary)
  assert pane["pane_id"] != original["pane_id"] and pane["workspace_id"] == original["workspace_id"]
  if absent == "moved":
    assert case.client.panes[original["pane_id"]] == old


@pytest.mark.parametrize("change", ["lost-marker", "reused-terminal"])
def test_missing_markers_or_reused_ids_never_authorize_default_replacement(context_case, change):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  caller = native_caller(case, original["workspace_id"])
  if change == "lost-marker":
    case.client.panes[original["pane_id"]]["tokens"] = {}
  else:
    case.client.panes[original["pane_id"]]["terminal_id"] = "reused"
  before = len(case.client.mutation_calls)
  with pytest.raises(TermcfgError) as error:
    work.open_type_v2(case.client, case.settings, case.state, "problem", caller_id=caller,
      binary=case.settings.herdr_binary)
  assert error.value.code == 4 and len(case.client.mutation_calls) == before


def test_native_split_is_unowned_and_agent_advisory_state_has_no_control_effect(context_case):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  caller = native_caller(case, original["workspace_id"])
  manual = case.client.panes[caller]
  manual["tokens"] = {"agent_state": "idle"}
  before = deepcopy(manual)
  focused = work.open_type_v2(case.client, case.settings, case.state, "problem", caller_id=caller,
    binary=case.settings.herdr_binary)
  assert focused["pane_id"] == original["pane_id"]
  assert case.client.panes[caller] == before
  binding = case.state.bindings()[0]
  assert len(binding["types"]["problem"]["instances"]) == 1


def test_rebind_requires_zero_active_and_explicit_acceptance(context_case):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  caller = native_caller(case, original["workspace_id"])
  with pytest.raises(TermcfgError) as error:
    work.rebind_type_v2(case.client, case.settings, case.state, "problem", accept=True, caller_id=caller)
  assert error.value.code == 4
  del case.client.panes[original["pane_id"]]
  other = case.tmp / "new-type-start"
  other.mkdir()
  case.settings.structured["templates"]["trial"]["tab_types"]["problem"]["cwd"] = {"path": str(other)}
  before = deepcopy(case.state.bindings()[0])
  work.rebind_type_v2(case.client, case.settings, case.state, "problem", caller_id=caller)
  assert case.state.bindings()[0] == before
  work.rebind_type_v2(case.client, case.settings, case.state, "problem", accept=True, caller_id=caller)
  assert case.state.bindings()[0]["types"]["problem"]["cwd"] == str(other)


def test_close_preview_contains_native_unowned_panes_and_affects_all_viewers(context_case, sentinel_factory):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  caller = native_caller(case, original["workspace_id"])
  workspace = case.client.workspaces[original["workspace_id"]]
  workspace.update(tab_count=2, pane_count=2)
  sentinel = sentinel_factory(case.state.base)
  before = list(case.client.mutation_calls)
  scope = work.close_preview_v2(case.client, case.state, caller_id=caller)
  assert len(scope["scope"]) == 64 and scope["capability"]["atomic_membership_guard"] is False
  assert {pane["pane_id"] for pane in scope["panes"]} == set(case.client.panes)
  assert scope["affects_all_viewers"] is True and len(scope["tabs"]) == 2
  with pytest.raises(TermcfgError) as error:
    work.close_workspace_v2(case.client, case.state, caller_id=caller, scope=scope["scope"])
  assert error.value.code == 5 and case.client.mutation_calls == before
  sentinel.assert_unchanged()


def test_close_scope_drift_returns_conflict_and_preserves_siblings(context_case):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  sibling = enter(case, named_candidate("case-b"))
  before_sibling = deepcopy(case.client.workspaces[sibling["workspace_id"]])
  scope = work.close_preview_v2(case.client, case.state, caller_id=original["pane_id"])
  native_caller(case, original["workspace_id"])
  case.client.workspaces[original["workspace_id"]].update(tab_count=2, pane_count=2)
  before = list(case.client.mutation_calls)
  with pytest.raises(TermcfgError) as error:
    work.close_workspace_v2(case.client, case.state, caller_id=original["pane_id"], scope=scope["scope"])
  assert error.value.code == 4 and case.client.mutation_calls == before
  assert case.client.workspaces[sibling["workspace_id"]] == before_sibling


def test_close_preview_includes_unmanaged_split_in_managed_tab(context_case):
  case = context_case
  original = enter(case, named_candidate("case-a"))
  split = deepcopy(original)
  split.update(pane_id="native-split", terminal_id="native-terminal", tokens={})
  case.client.panes[split["pane_id"]] = split
  case.client.tabs[original["tab_id"]]["pane_count"] = 2
  case.client.workspaces[original["workspace_id"]]["pane_count"] = 2
  scope = work.close_preview_v2(case.client, case.state, caller_id=split["pane_id"])
  assert len(scope["tabs"]) == 1 and len(scope["panes"]) == 2
  assert any(pane["pane_id"] == "native-split" for pane in scope["panes"])


def test_structured_entry_preserves_active_legacy_group_and_private_account_sentinels(context_case, sentinel_factory):
  case = context_case
  legacy = case.client.request("worktree.open", {"path": str(case.project), "cwd": str(case.project)})
  before_group = deepcopy(case.client.workspaces[legacy["workspace"]["workspace_id"]])
  private = case.tmp / "synthetic-accounts"
  private.mkdir()
  (private / "account.json").write_text('{"fixture": "never inspect real accounts"}')
  sentinel = sentinel_factory(private)
  pane = enter(case, project_candidate(case.project))
  assert pane["workspace_id"] != legacy["workspace"]["workspace_id"]
  assert case.client.workspaces[legacy["workspace"]["workspace_id"]] == before_group
  sentinel.assert_unchanged()
  assert not any(method.endswith(("close", "stop", "apply_layout")) for method, _ in case.client.requests)


def test_seven_contexts_thirty_terminals_ten_cycles_have_no_duplicate_defaults(context_case):
  from termcfg.work_projects import discover
  case = context_case
  candidates = []
  for index in range(3):
    path = case.tmp / ("project-" + str(index))
    path.mkdir()
    if index == 0:
      (path / ".git").mkdir()
    candidates.append(project_candidate(path, mode="git" if index == 0 else "directory"))
  for index in range(2):
    path = case.tmp / ("copy-" + str(index))
    path.mkdir()
    (path / ".git").write_text("gitdir: " + candidates[0].key + "/.git/worktrees/copy-" + str(index) + "\n")
    candidates.append(project_candidate(path, mode="git"))
  candidates.extend(named_candidate("case-" + name) for name in ("a", "b"))
  defaults = {}
  for candidate in candidates:
    pane = enter(case, candidate)
    defaults[(candidate.kind, candidate.key)] = pane
    for _ in range(3):
      work.open_type_v2(case.client, case.settings, case.state, "problem", new=True,
        caller_id=pane["pane_id"], binary=case.settings.herdr_binary)
  for candidate in candidates[:2]:
    pane = defaults[(candidate.kind, candidate.key)]
    work.open_type_v2(case.client, case.settings, case.state, "problem", new=True,
      caller_id=pane["pane_id"], binary=case.settings.herdr_binary)
  assert len(case.client.panes) == len(case.client.tabs) == 30
  before = deepcopy(case.state.bindings())
  for _ in range(10):
    assert len(discover(case.settings).candidates) == 7
    for candidate in candidates:
      original = defaults[(candidate.kind, candidate.key)]
      pane = enter(case, candidate)
      opened = work.open_type_v2(case.client, case.settings, case.state, "problem",
        caller_id=original["pane_id"], binary=case.settings.herdr_binary)
      assert pane["pane_id"] == opened["pane_id"] == original["pane_id"]
  assert case.state.bindings() == before
  assert case.client.call_counts["workspace.create"] == 7 and case.client.call_counts["tab.create"] == 23
  assert len([pane for pane in case.client.panes.values() if pane["tokens"]["rw2_kind"] == "default"]) == 7
  assert len({item["owner"] for item in before}) == 7
