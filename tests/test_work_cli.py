"""结构化命令的离线入口、严格参数与可选选择器。"""
import json
import os
from types import SimpleNamespace

import pytest

from termcfg import work
from termcfg.errors import TermcfgError
from test_work_config_edit import local_settings


def invoke(settings, *args):
  return work.main(["--local", str(settings.local_path), *args])


def test_offline_check_and_list_do_not_connect_or_launch(tmp_path, monkeypatch, capsys):
  settings = local_settings(tmp_path)
  monkeypatch.setattr(work, "connected", lambda *a, **k: pytest.fail("native connection"))
  assert invoke(settings, "config", "check") == 0
  assert invoke(settings, "list", "--json") == 0
  value = json.loads(capsys.readouterr().out.splitlines()[-1])
  assert value["candidates"] == []


@pytest.mark.parametrize("args", [
  ("project", "add", "--path", "."), ("source", "add", "--id", "projects"),
  ("named", "add", "--id", "case-a"), ("config", "unknown"),
])
def test_incomplete_input_fails_without_any_side_effect(tmp_path, args, sentinel_factory):
  settings = local_settings(tmp_path)
  before = sentinel_factory(tmp_path)
  assert invoke(settings, *args) == 2
  before.assert_unchanged()


def test_cli_dry_run_and_save_use_same_manual_document(tmp_path, sentinel_factory, capsys):
  from termcfg.work_config import read_settings
  settings = local_settings(tmp_path)
  args = ("named", "add", "--id", "case-a", "--title", "调查 $literal", "--template", "dev")
  before = sentinel_factory(tmp_path)
  assert invoke(settings, *args, "--dry-run") == 0
  before.assert_unchanged()
  assert invoke(settings, *args) == 0
  saved = read_settings(local=settings.local_path)
  assert saved.structured["workspaces"][0]["title"] == "调查 $literal"
  assert invoke(settings, "list", "--json") == 0
  assert "case-a" in capsys.readouterr().out


@pytest.mark.parametrize("with_child", [False, True])
def test_source_cli_preview_discloses_actual_matches_without_effects(tmp_path, sentinel_factory, capsys, with_child):
  settings = local_settings(tmp_path)
  root = tmp_path / "projects"
  root.mkdir()
  if with_child:
    (root / "中文 child").mkdir()
  before = sentinel_factory(tmp_path)
  assert invoke(settings, "source", "add", "--id", "projects", "--path", str(root),
    "--mode", "directory", "--template", "dev", "--dry-run") == 0
  output = capsys.readouterr().out
  assert "Candidates: " + str(int(with_child)) in output
  if with_child:
    assert str(root / "中文 child") in output and "source:projects" in output
    assert "directory |" in output
  before.assert_unchanged()


def test_registration_shows_candidates_before_confirmation(tmp_path, monkeypatch, capsys, sentinel_factory):
  from termcfg import work_ui
  settings = local_settings(tmp_path)
  root = tmp_path / "projects"
  root.mkdir()
  (root / "child").mkdir()
  fields = iter(("projects", str(root)))
  choices = iter(("directory", "0"))
  monkeypatch.setattr(work_ui, "_text", lambda *a, **k: next(fields))
  monkeypatch.setattr(work_ui, "select", lambda *a, **k: next(choices))
  def cancel(label):
    output = capsys.readouterr().out
    assert str(root / "child") in output and "Candidates: 1" in output
    assert "directory |" in output and "source:projects" in output
    return False
  monkeypatch.setattr(work_ui, "confirm", cancel)
  before = sentinel_factory(tmp_path)
  assert work_ui.registration(settings, "source") is None
  before.assert_unchanged()


def test_selector_and_check_show_discovery_diagnostics_without_losing_candidates(tmp_path, monkeypatch, capsys):
  from termcfg import work_ui, work_projects
  from termcfg.work_edit import preview, save
  settings = local_settings(tmp_path)
  project = tmp_path / "project"
  project.mkdir()
  save(preview(settings, "project-add", {"path": str(project), "mode": "directory", "template": "dev"}))
  content = settings.local_path.read_text().replace("include_rotom = false", 'include_rotom = true\nrotom_template = "dev"')
  settings.local_path.write_text(content)
  monkeypatch.setattr(work_projects, "_executing_root", lambda _: False)
  rows = []
  def cancel(candidates, **kwargs):
    rows.extend(candidates)
    return None
  monkeypatch.setattr(work_ui, "select", cancel)
  assert invoke(settings) == 0
  assert "work_executing_root_unverified" in capsys.readouterr().err
  assert any(str(project) in label and "directory" in label for _, label in rows)
  assert invoke(settings, "config", "check") == 0
  assert "work_executing_root_unverified" in capsys.readouterr().err


def test_registration_preview_reports_unreadable_source(tmp_path, monkeypatch, capsys):
  from pathlib import Path
  settings = local_settings(tmp_path)
  root = tmp_path / "projects"
  root.mkdir()
  original = Path.iterdir
  def unreadable(path):
    if path == root:
      raise PermissionError()
    return original(path)
  monkeypatch.setattr(Path, "iterdir", unreadable)
  assert invoke(settings, "source", "add", "--id", "projects", "--path", str(root),
    "--mode", "directory", "--template", "dev", "--dry-run") == 0
  output = capsys.readouterr()
  assert "work_source_unreadable" in output.err and "projects" in output.err
  assert "Candidates: 0" in output.out


@pytest.mark.parametrize("mode", [0o400, 0o444])
@pytest.mark.parametrize("kind", ["source", "project", "named", "editor"])
def test_initial_readonly_configuration_provides_safe_manual_fragment(tmp_path, monkeypatch, capsys,
    sentinel_factory, mode, kind):
  settings = local_settings(tmp_path)
  project = tmp_path / "中文 project"
  project.mkdir()
  with settings.local_path.open("a") as stream:
    stream.write('\n# private-content-canary\n')
  settings.local_path.chmod(mode)
  from agentcfg import paths
  original_open = os.open
  def guard(path, *args, **kwargs):
    if os.fspath(path) in (settings.local_path.name, str(settings.local_path)):
      pytest.fail("unsafe configuration body was opened")
    return original_open(path, *args, **kwargs)
  monkeypatch.setattr(paths.os, "open", guard)
  args = {"source": ("source", "add", "--id", "projects", "--path", str(project), "--mode", "directory", "--template", "dev"),
    "project": ("project", "add", "--path", str(project), "--mode", "directory", "--template", "dev"),
    "named": ("named", "add", "--id", "case-a", "--title", "调查 $literal", "--template", "dev"),
    "editor": ("config", "edit")}[kind]
  before = sentinel_factory(tmp_path)
  assert invoke(settings, *args) == 4
  output = capsys.readouterr()
  assert "Manual machine.work fragment" in output.err and "unverified" in output.err
  assert "private-content-canary" not in output.err + output.out
  assert "saved" not in output.out and "unchanged" not in output.out
  assert "do not replace" in output.err
  if kind != "editor":
    import tomlkit
    fragment = output.err.split("Manual machine.work fragment:\n", 1)[1]
    value = tomlkit.parse(fragment).unwrap()["machine"]["work"]
    entry = value["sources" if kind == "source" else "workspaces"][0]
    assert entry["template"] == "dev"
    assert entry.get("path", entry.get("title")) == ("调查 $literal" if kind == "named" else str(project))
  else:
    assert "# [machine.work]" in output.err
  before.assert_unchanged()


def test_unsafe_symlink_configuration_is_not_read_for_manual_fragment(tmp_path, capsys, sentinel_factory):
  settings = local_settings(tmp_path)
  target = settings.local_path.with_suffix(".private")
  settings.local_path.rename(target)
  with target.open("a") as stream:
    stream.write("\n# private-symlink-canary\n")
  settings.local_path.symlink_to(target)
  before = sentinel_factory(tmp_path)
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "Case", "--template", "dev") == 4
  output = capsys.readouterr().err
  assert "Manual machine.work fragment" in output and "private-symlink-canary" not in output
  before.assert_unchanged()


def test_initial_readonly_invalid_explicit_input_does_not_emit_invalid_entry(tmp_path, capsys):
  settings = local_settings(tmp_path)
  settings.local_path.chmod(0o400)
  assert invoke(settings, "named", "add", "--id", "bad.id", "--title", "Case", "--template", "dev") == 4
  output = capsys.readouterr().err
  assert "Manual machine.work fragment" in output and "bad.id" not in output
  assert "No entry generated" in output


def test_initial_readonly_mount_save_reports_validated_fragment(tmp_path, monkeypatch, capsys):
  import errno
  from agentcfg.storage import Tree
  settings = local_settings(tmp_path)
  original = Tree.replace
  def readonly(tree, path, *args, **kwargs):
    if tree.root == settings.local_path.parent:
      raise OSError(errno.EROFS, "synthetic readonly mount")
    return original(tree, path, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", readonly)
  before = settings.local_path.read_bytes()
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "Case", "--template", "dev") == 6
  output = capsys.readouterr()
  assert "Manual machine.work fragment" in output.err and "case-a" in output.err
  assert "work_config: saved" not in output.out and settings.local_path.read_bytes() == before


@pytest.mark.parametrize("configured,fixed,other,command,expected", [
  ("shell", None, "pi", "open", 30),
  ("pi", None, "shell", "open", 60),
  ("dsh", None, "shell", "open", 60),
  ("pi", "shell", "pi", "open", 30),
  ("shell", "pi", "shell", "open", 60),
  (None, "dsh", "shell", "open", 60),
  ("shell", "pi", "pi", "rebind", 30),
  ("dsh", "shell", "shell", "rebind", 60),
])
def test_type_operation_budget_uses_confirmed_contract_without_restarting_clock(tmp_path, monkeypatch,
    configured, fixed, other, command, expected):
  from contextlib import contextmanager
  from dataclasses import replace
  from termcfg import herdr, work_config
  settings, client, _ = native_cli(tmp_path, monkeypatch)
  definitions = {} if configured is None else {"tool": {"launcher": configured}}
  settings = replace(settings, structured={"templates": {
    "dev": {"tab_types": definitions}, "unrelated": {"tab_types": {"tool": {"launcher": other}}}}})
  binding = {"template": "dev", "types": {} if fixed is None else {"tool": {"launch": {"launcher": fixed}}}}
  clock = [1000.0]
  monkeypatch.setattr(herdr.time, "monotonic", lambda: clock[0])
  monkeypatch.setenv("HERDR_PANE_ID", "fixture-pane")
  monkeypatch.setenv("HERDR_SOCKET_PATH", client.socket_path)
  monkeypatch.setattr(work, "_caller_scope", lambda *a: "fixture-pane")
  monkeypatch.setattr(work, "current_binding_v2", lambda *a: binding)
  monkeypatch.setattr(work_config, "prepare_launch", lambda *a, **k: pytest.fail("unexpected preparation"))
  deadlines, calls = [], []
  @contextmanager
  def locked(deadline):
    deadlines.append(deadline)
    clock[0] += 1
    yield
  @contextmanager
  def connected(current, deadline, *, start):
    assert start is False
    assert deadline is deadlines[-1]
    clock[0] += 2
    client.deadline = deadline
    yield client, "/fixture/herdr"
  def dispatch(current_client, *args, **kwargs):
    calls.append(current_client.deadline)
    assert current_client.deadline.expires_at == 1000 + expected
    assert current_client.deadline.remaining() == expected - 3
  monkeypatch.setattr(work, "operation_lock", locked)
  monkeypatch.setattr(work, "connected", connected)
  monkeypatch.setattr(work, "open_type_v2", dispatch)
  monkeypatch.setattr(work, "rebind_type_v2", dispatch)
  args = SimpleNamespace(command=command, role="tool", new=False, accept=True)
  assert work.structured_native_command(args, settings) == 0
  assert calls == deadlines and len(calls) == 1


@pytest.mark.parametrize("launcher,expected", [("shell", 30), ("pi", 60)])
def test_removed_type_selector_focus_keeps_fixed_budget_without_preparation(tmp_path, monkeypatch,
    launcher, expected):
  import tomlkit
  from termcfg import work_config, work_ui
  from termcfg.work_state import WorkState
  settings, client, _ = native_cli(tmp_path, monkeypatch)
  document = tomlkit.parse(settings.local_path.read_text())
  definition = document["machine"]["work"]["templates"]["dev"]["tab_types"]["shell"]
  definition["launcher"] = launcher
  document["machine"]["work"]["pi_profile"] = "pi-explicit"
  settings.local_path.write_text(tomlkit.dumps(document))
  monkeypatch.setattr(work_config, "_prepared_agent", lambda *a: {
    "generation": "b" * 64, "identity": "synthetic-runtime", "policy": "caller"})
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "Case", "--template", "dev") == 0
  bootstrap = client.request("workspace.create", {"cwd": os.environ["HOME"], "label": "Native", "focus": False, "env": {}})
  monkeypatch.setenv("HERDR_PANE_ID", bootstrap["root_pane"]["pane_id"])
  monkeypatch.setenv("HERDR_SOCKET_PATH", client.socket_path)
  assert invoke(settings, "named", "enter", "case-a") == 0
  pane = next(item for item in client.panes.values() if item.get("tokens", {}).get("rw2_type") == "shell")
  monkeypatch.setenv("HERDR_PANE_ID", pane["pane_id"])
  with WorkState(client.socket_path, client.identity) as state:
    binding = work.current_binding_v2(client, state, pane["pane_id"])
    locator = binding["types"]["shell"]["default"]
  document["machine"]["work"]["templates"]["dev"] = {"order": ["other"], "initial": "other",
    "tab_types": {"other": {"label": "Other", "launcher": "shell"}}}
  settings.local_path.write_text(tomlkit.dumps(document))
  def choose(rows, **kwargs):
    assert kwargs["prompt"] == "Terminal type > "
    removed = [(key, label) for key, label in rows if label.startswith("shell |")]
    assert len(removed) == 1 and "focus only" in removed[0][1].lower()
    assert "Default: focus or create" not in removed[0][1] and "rebind" not in removed[0][1].lower()
    return removed[0][0]
  monkeypatch.setattr(work_ui, "select", choose)
  monkeypatch.setattr(work_config, "prepare_launch", lambda *a, **k: pytest.fail("focus prepared launcher"))
  original = work.focus_instance_v2
  calls = []
  def focus(current_client, *args, **kwargs):
    assert args[-1] == locator
    calls.append(current_client.deadline.remaining())
    return original(current_client, *args, **kwargs)
  monkeypatch.setattr(work, "focus_instance_v2", focus)
  before = dict(client.call_counts)
  assert invoke(settings, "open") == 0
  assert len(calls) == 1 and expected - 2 < calls[0] <= expected
  assert client.call_counts["workspace.create"] == before["workspace.create"]
  assert client.call_counts.get("tab.create", 0) == before.get("tab.create", 0)


def test_missing_fzf_never_blocks_complete_explicit_cli(tmp_path, monkeypatch):
  from termcfg import work_ui
  settings = local_settings(tmp_path)
  monkeypatch.setattr(work_ui, "resolve_executable", lambda _: (_ for _ in ()).throw(
    TermcfgError(5, "work_selector_not_prepared")))
  assert invoke(settings) == 5
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "Case", "--template", "dev") == 0


@pytest.mark.parametrize("exit_code", [1, 130])
def test_selector_cancel_clears_hostile_overrides_and_has_no_effect(tmp_path, monkeypatch, exit_code):
  from termcfg import work_ui
  monkeypatch.setenv("FZF_DEFAULT_OPTS", "--bind=start:execute(touch sentinel)")
  monkeypatch.setenv("FZF_DEFAULT_COMMAND", "touch sentinel")
  monkeypatch.setenv("FZF_DEFAULT_OPTS_FILE", "/untrusted/options")
  monkeypatch.setattr(work_ui, "resolve_executable", lambda _: "/fixture/fzf")
  def run(argv, **kwargs):
    assert not any(key.startswith("FZF_") for key in kwargs["env"])
    assert not kwargs.get("shell", False)
    if "--version" in argv:
      return SimpleNamespace(returncode=0, stdout=b"0.74.5 fixture\n")
    if "--help" in argv:
      return SimpleNamespace(returncode=0, stdout=b"--read0 --print0 --no-multi --delimiter --with-nth --prompt --height --layout --border")
    assert kwargs["input"] == b"opaque-id\tLiteral $(command)\0"
    assert "--no-preview" not in argv
    return SimpleNamespace(returncode=exit_code, stdout=b"")
  assert work_ui.select([("opaque-id", "Literal $(command)")], run=run) is None


def test_selector_rejects_unmapped_or_multiple_results(tmp_path, monkeypatch):
  from termcfg import work_ui
  monkeypatch.setattr(work_ui, "resolve_executable", lambda _: "/fixture/fzf")
  def run(argv, **kwargs):
    if "--version" in argv:
      return SimpleNamespace(returncode=0, stdout=b"0.74.5\n")
    if "--help" in argv:
      return SimpleNamespace(returncode=0, stdout=b"--read0 --print0 --no-multi --delimiter --with-nth --prompt --height --layout --border")
    return SimpleNamespace(returncode=0, stdout=b"unmapped\tAnything\0")
  with pytest.raises(TermcfgError) as error:
    work_ui.select([("known", "A")], run=run)
  assert error.value.code == 5


def test_global_selectors_mutually_exclusive_before_loading(tmp_path):
  settings = local_settings(tmp_path)
  assert work.main(["--machine", "trial", "--local", str(settings.local_path), "config", "check"]) == 2


def native_cli(tmp_path, monkeypatch):
  from contextlib import contextmanager
  from termcfg import herdr
  from work_helpers import FakeHerdr
  settings = local_settings(tmp_path)
  shell = tmp_path / "fixture-shell"
  shell.write_text("synthetic")
  shell.chmod(0o700)
  monkeypatch.setenv("SHELL", str(shell))
  client = FakeHerdr(str(tmp_path / "native.sock"), version="v2")
  starts = []
  @contextmanager
  def connection(settings, deadline, *, start):
    starts.append(start)
    client.deadline = deadline
    yield client, "/fixture/herdr"
  monkeypatch.setattr(work, "connected", connection)
  monkeypatch.setattr(herdr, "require_startup_evidence", lambda *a: {})
  return settings, client, starts


def test_named_add_enter_rename_retains_id_and_independent_binding(tmp_path, monkeypatch):
  settings, client, starts = native_cli(tmp_path, monkeypatch)
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "First", "--template", "dev") == 0
  assert client.requests == []
  # 在一个原生启动 pane 内进入，避免测试真的 attach。
  bootstrap = client.request("workspace.create", {"cwd": os.environ["HOME"], "label": "Native", "focus": False, "env": {}})
  monkeypatch.setenv("HERDR_PANE_ID", bootstrap["root_pane"]["pane_id"])
  monkeypatch.setenv("HERDR_SOCKET_PATH", client.socket_path)
  assert invoke(settings, "named", "enter", "case-a") == 0
  count = len(client.workspaces)
  assert invoke(settings, "named", "rename", "case-a", "--title", "Renamed") == 0
  assert len(client.workspaces) == count
  assert any(item["label"] == "Renamed" for item in client.workspaces.values())
  assert starts and not any(starts)


def test_live_list_and_status_reconcile_are_read_only(tmp_path, monkeypatch, capsys, sentinel_factory):
  settings, client, starts = native_cli(tmp_path, monkeypatch)
  before = sentinel_factory(tmp_path)
  for args in (("list", "--live", "--json"), ("status", "--json"), ("reconcile", "--json")):
    assert invoke(settings, *args) == 0
  before.assert_unchanged()
  assert not any(starts) and client.mutation_calls == []


def test_open_outside_confirmed_workspace_does_not_start_or_guess(tmp_path, monkeypatch):
  settings, client, starts = native_cli(tmp_path, monkeypatch)
  assert invoke(settings, "open", "shell") == 4
  assert starts == [] and client.mutation_calls == []


def test_unregistered_enter_refuses_before_connecting(tmp_path, monkeypatch):
  settings, client, starts = native_cli(tmp_path, monkeypatch)
  project = tmp_path / "unregistered"
  project.mkdir()
  assert invoke(settings, "enter", str(project)) == 2
  assert starts == [] and client.requests == []


def test_named_native_rename_failure_keeps_saved_title_and_reports_partial(tmp_path, monkeypatch, capsys):
  settings, client, starts = native_cli(tmp_path, monkeypatch)
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "First", "--template", "dev") == 0
  # 没有已验证 live binding 时，rename 只保存，不创建端点。
  assert invoke(settings, "named", "rename", "case-a", "--title", "Saved") == 0
  from termcfg.work_config import read_settings
  assert read_settings(local=settings.local_path).structured["workspaces"][0]["title"] == "Saved"
  assert client.mutation_calls == [] and not any(starts)


@pytest.mark.parametrize("enter_after", [False, True])
def test_worktree_cli_create_only_and_explicit_entry_are_separate(tmp_path, monkeypatch, enter_after):
  from termcfg import work_git
  settings = local_settings(tmp_path)
  calls = []
  destination = tmp_path / "copy"
  plan = SimpleNamespace(as_dict=lambda: {"path": str(destination)}, facts={"path": str(destination)})
  monkeypatch.setattr(work_git, "preview", lambda *a, **kw: plan)
  monkeypatch.setattr(work_git, "create", lambda *a, **kw: calls.append("git") or {"path": str(destination), "outcome": "completed"})
  monkeypatch.setattr(work, "structured_native_command", lambda args, settings: calls.append(args.command) or 4)
  args = ["worktree", "create", "--repo", str(tmp_path), "--new-branch", "topic", "--base", "HEAD",
    "--path", str(destination), "--template", "dev"]
  result = invoke(settings, *args, *(["--enter"] if enter_after else []))
  assert result == (4 if enter_after else 0)
  assert calls == (["git", "enter"] if enter_after else ["git"])


def test_worktree_dry_run_does_not_create_lock_receipt_or_checkout(tmp_path, monkeypatch, sentinel_factory):
  from termcfg import work_git
  settings = local_settings(tmp_path)
  plan = SimpleNamespace(as_dict=lambda: {"path": str(tmp_path / "copy")})
  monkeypatch.setattr(work_git, "preview", lambda *a, **kw: plan)
  monkeypatch.setattr(work_git, "create", lambda *a, **kw: pytest.fail("dry run dispatched Git"))
  before = sentinel_factory(tmp_path)
  assert invoke(settings, "worktree", "create", "--repo", str(tmp_path), "--existing-branch", "topic",
    "--path", str(tmp_path / "copy"), "--template", "dev", "--dry-run") == 0
  before.assert_unchanged()


@pytest.mark.parametrize("extra", [[], ["--new-branch", "one", "--existing-branch", "two"]])
def test_worktree_cli_requires_one_branch_mode(tmp_path, extra):
  settings = local_settings(tmp_path)
  assert invoke(settings, "worktree", "create", "--repo", str(tmp_path), "--path", str(tmp_path / "copy"),
    "--template", "dev", *extra) == 2


@pytest.mark.parametrize("args", [("--yes",), ("--scope", "a" * 64), ("--dry-run", "--yes"),
  ("--dry-run", "--scope", "a" * 64, "--yes")])
def test_close_incomplete_or_mixed_authorization_is_rejected_without_effects(tmp_path, args, sentinel_factory):
  settings = local_settings(tmp_path)
  before = sentinel_factory(tmp_path)
  assert invoke(settings, "close", *args) == 2
  before.assert_unchanged()


@pytest.mark.parametrize("model", [None, "structured-v99"])
def test_invalid_structured_opt_in_never_falls_back_to_legacy(tmp_path, monkeypatch, model):
  settings = local_settings(tmp_path)
  original = settings.local_path.read_text()
  settings.local_path.write_text(original.replace('model = "structured-v1"\n',
    '' if model is None else 'model = "' + model + '"\n'))
  monkeypatch.setattr(work, "connected", lambda *a, **k: pytest.fail("invalid config reached native"))
  assert invoke(settings, "config", "check") == 2


def test_legacy_config_does_not_enable_new_commands_or_write_anything(tmp_path, sentinel_factory):
  from test_work_config import local_file
  path = local_file(tmp_path)
  before = sentinel_factory(tmp_path)
  assert work.main(["--local", str(path), "list"]) == 2
  before.assert_unchanged()


@pytest.mark.parametrize("identifier,expected", [("case-a", 0), ("bad.id", 2)])
def test_manual_cli_and_selector_accept_the_same_named_inputs(tmp_path, monkeypatch, identifier, expected):
  import tomlkit
  from termcfg import work_ui
  from termcfg.work_config import read_settings
  from termcfg.work_projects import discover
  results, candidates = [], []
  for entrance in ("manual", "cli", "selector"):
    root = tmp_path / entrance
    root.mkdir()
    settings = local_settings(root)
    if entrance == "manual":
      document = tomlkit.parse(settings.local_path.read_text())
      document["machine"]["work"]["workspaces"] = [{"kind": "named", "id": identifier,
        "title": "调查 $literal", "template": "dev"}]
      settings.local_path.write_text(tomlkit.dumps(document))
      try:
        read_settings(local=settings.local_path)
        code = 0
      except TermcfgError as error:
        code = error.code
    elif entrance == "cli":
      code = invoke(settings, "named", "add", "--id", identifier, "--title", "调查 $literal", "--template", "dev")
    else:
      choices = iter(("named", "0", "accept"))
      fields = iter((identifier, "调查 $literal", ""))
      monkeypatch.setattr(work_ui, "select", lambda *a, **k: next(choices))
      monkeypatch.setattr(work_ui, "_text", lambda *a, **k: next(fields))
      code = invoke(settings)
    results.append(code)
    if code == 0:
      candidates.append(discover(read_settings(local=settings.local_path)).candidates)
  assert results == [expected] * 3
  if candidates:
    assert candidates[0] == candidates[1] == candidates[2]


def ui_worktree_facts(settings, repo, parent):
  from termcfg.work_projects import normalize_work
  return {"repo": str(repo), "path": str(parent / "topic"), "branch_mode": "new", "branch": "topic",
    "base": "HEAD", "commit": "a" * 40, "template": "dev",
    "repo_identity": [7, 11], "common": str(repo / ".git"), "common_identity": [7, 12],
    "git_dir": str(repo / ".git"), "git_dir_identity": [7, 12],
    "source": normalize_work(settings.structured, local_path=settings.local_path)["sources"][0],
    "selection_digest": settings.selection_digest,
    "config_files": {str(repo / ".git" / "config"): [7, 13, 33152, 99, 123456789, 987654321]},
    "private_canary": "must-not-dump-unreviewed-plan-fields"}


def ui_worktree_case(tmp_path, monkeypatch, *, coverage=True):
  from termcfg import work_git, work_ui
  from termcfg.work_edit import preview, save
  from termcfg.work_config import read_settings
  settings = local_settings(tmp_path)
  repo = tmp_path / "original"
  repo.mkdir()
  (repo / ".git").mkdir()
  parent = tmp_path / "copies"
  parent.mkdir()
  save(preview(settings, "project-add", {"path": str(repo), "mode": "git", "template": "dev"}))
  settings = read_settings(local=settings.local_path)
  if coverage:
    save(preview(settings, "source-add", {"id": "copies", "path": str(parent), "mode": "git", "template": "dev"}))
    settings = read_settings(local=settings.local_path)
  facts = ui_worktree_facts(settings, repo, parent) if coverage else None
  monkeypatch.setattr(work_git, "create", lambda *a, **k: pytest.fail("UI cancellation dispatched Git"))
  monkeypatch.setattr(work_git, "preview", lambda *a, **k: SimpleNamespace(facts=facts))
  def field(label, **kwargs):
    return {"Branch name": "topic", "Local base (for example HEAD or refs/heads/main)": "HEAD",
      "Destination (must not exist; parent must exist)": str(parent / "topic"), "New source ID (ASCII)": "copies"}[label]
  monkeypatch.setattr(work_ui, "_text", field)
  return settings, parent, field


@pytest.mark.parametrize("cancel", ["repo", "mode", "branch", "base", "destination", "template", "final"])
def test_worktree_ui_cancellation_points_have_no_current_effect(tmp_path, monkeypatch, sentinel_factory, cancel):
  from termcfg import work_ui
  settings, parent, field = ui_worktree_case(tmp_path, monkeypatch)
  def choose(rows, *, prompt, **kwargs):
    stage = {"Registered Git repository > ": "repo", "Branch mode > ": "mode",
      "Template > ": "template", "Confirm > ": "final"}[prompt]
    if stage == cancel:
      return None
    return {"repo": "0", "mode": "new", "template": "0", "final": "create"}[stage]
  def text(label, **kwargs):
    stage = "branch" if label == "Branch name" else "base" if label.startswith("Local base") else "destination"
    return None if stage == cancel else field(label)
  monkeypatch.setattr(work_ui, "select", choose)
  monkeypatch.setattr(work_ui, "_text", text)
  before = sentinel_factory(tmp_path)
  assert work_ui.worktree_form(settings) is None
  before.assert_unchanged()


def test_parent_source_save_survives_later_worktree_cancel(tmp_path, monkeypatch, capsys):
  from termcfg import work_ui, work_git
  from termcfg.work_config import read_settings
  settings, parent, field = ui_worktree_case(tmp_path, monkeypatch, coverage=False)
  calls = []
  def preview(current, **kwargs):
    calls.append(current)
    if len(calls) == 1:
      raise TermcfgError(2, "work_git_destination_source_required")
    assert current.structured["sources"][0]["path"] == str(parent)
    return SimpleNamespace(facts=ui_worktree_facts(current, tmp_path / "original", parent))
  monkeypatch.setattr(work_git, "preview", preview)
  choices = iter(("0", "new", "0", "accept", "accept", "cancel"))
  def choose(rows, **kwargs):
    if kwargs.get("prompt") == "Confirm > ":
      assert_worktree_review(capsys.readouterr().out, ui_worktree_facts(calls[-1], tmp_path / "original", parent))
    return next(choices)
  monkeypatch.setattr(work_ui, "select", choose)
  assert work_ui.worktree_form(settings) is None
  assert len(calls) == 2 and not (parent / "topic").exists()
  saved = read_settings(local=settings.local_path)
  assert saved.structured["sources"][0]["id"] == "copies"
  assert saved.structured["sources"][0]["path"] == str(parent)


def assert_worktree_review(output, facts):
  import json
  from termcfg.work_state import digest
  review = next(json.loads(line) for line in output.splitlines() if line.startswith("{"))
  for key in ("repo", "path", "branch_mode", "branch", "base", "commit", "template", "source",
      "repo_identity", "common", "common_identity", "git_dir", "git_dir_identity"):
    assert review[key] == facts[key]
  assert review["configuration"] == {"selection_digest": facts["selection_digest"],
    "git_config_paths": sorted(facts["config_files"]), "git_config_digest": digest(facts["config_files"])}
  assert "Original dirty files stay in place" in output and "No hooks, bootstrap, installs or services" in output
  assert facts["private_canary"] not in output and "123456789" not in output and "987654321" not in output


def test_worktree_configured_coverage_review_is_complete_before_cancel(tmp_path, monkeypatch, capsys, sentinel_factory):
  from termcfg import work_ui
  settings, parent, _ = ui_worktree_case(tmp_path, monkeypatch)
  facts = ui_worktree_facts(settings, tmp_path / "original", parent)
  choices = iter(("0", "new", "0", "cancel"))
  def choose(rows, **kwargs):
    if kwargs.get("prompt") == "Confirm > ":
      assert_worktree_review(capsys.readouterr().out, facts)
    return next(choices)
  monkeypatch.setattr(work_ui, "select", choose)
  before = sentinel_factory(tmp_path)
  assert work_ui.worktree_form(settings) is None
  before.assert_unchanged()


@pytest.mark.parametrize("new,has_instances", [(False, True), (True, True), (False, False), (True, False)])
def test_removed_type_selector_offers_only_existing_instance_focus(monkeypatch, new, has_instances):
  from termcfg import work_ui
  settings = SimpleNamespace(structured={"templates": {"dev": {"order": ["current"],
    "tab_types": {"current": {"label": "Current", "launcher": "shell"}}}}})
  binding = {"template": "dev", "types": {
    "current": {"instances": {}}, "retired": {"instances": {
      "existing-locator": {"kind": "extra", "tab_id": "tab-existing"}} if has_instances else {}}}}
  def choose(rows, **kwargs):
    current = [(key, label) for key, label in rows if label.startswith("Current |")]
    assert any(("New extra" if new else "Default: focus or create") in label for _, label in current)
    assert any("rebind" in label.lower() for _, label in current) == (not new)
    removed = [(key, label) for key, label in rows if label.startswith("retired |")]
    if new or not has_instances:
      assert removed == []
      return None
    assert len(removed) == 1
    assert "focus only" in removed[0][1].lower() and "verify before focus" in removed[0][1]
    assert "New extra" not in removed[0][1] and "rebind" not in removed[0][1].lower()
    return removed[0][0]
  monkeypatch.setattr(work_ui, "select", choose)
  assert work_ui.type_action(settings, binding, new=new) == (
    ("retired", "existing-locator") if has_instances and not new else None)
