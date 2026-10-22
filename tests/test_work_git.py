"""仅对临时合成仓库执行明确 Git 子命令；不恢复通用子进程能力。"""
from copy import deepcopy
from dataclasses import replace
import errno
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tomlkit

import pytest

from conftest import _REAL_POPEN
from termcfg.errors import TermcfgError
from termcfg.work_config import read_settings


class SyntheticGit:
  def __init__(self, root):
    self.root = root.resolve()
    self.calls = []
    self.allowed = {"init", "config", "add", "commit", "branch", "tag", "rev-parse",
      "check-ref-format", "show-ref", "worktree", "symbolic-ref", "for-each-ref", "update-ref"}
    self.after_add_timeout = False
    self.before_add = None

  def __call__(self, argv, **kwargs):
    fixture_mutation = kwargs.pop("_fixture_mutation", False)
    argv = list(map(os.fspath, argv))
    assert argv[0] == "/usr/bin/git" and not kwargs.get("shell")
    index = 1
    directory = None
    while index < len(argv) and argv[index] in ("-c", "-C"):
      if argv[index] == "-C":
        directory = Path(argv[index + 1]).resolve()
      index += 2
    command = argv[index:]
    if command != ["--version"]:
      assert directory is not None and directory.is_relative_to(self.root)
      assert command and command[0] in self.allowed
    if command[0] == "worktree":
      assert len(command) > 1 and command[1] in ("list", "add")
    assert not any(arg in ("--force", "-f") for arg in command)
    if "-D" in command:
      assert fixture_mutation and command == ["branch", "-D", "available"]
    if command[0] == "update-ref":
      assert fixture_mutation and command[1].startswith("refs/remotes/synthetic/")
    environment = dict(kwargs.pop("env", os.environ))
    assert Path(environment["HOME"]).resolve().is_relative_to(self.root)
    environment.update(GIT_AUTHOR_NAME="Synthetic Author", GIT_AUTHOR_EMAIL="author@example.invalid",
      GIT_COMMITTER_NAME="Synthetic Author", GIT_COMMITTER_EMAIL="author@example.invalid")
    self.calls.append((argv, deepcopy(environment)))
    timeout = min(kwargs.pop("timeout", 10), 30)
    check = kwargs.pop("check", False)
    kwargs.pop("capture_output", None)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    if command[:2] == ["worktree", "add"] and self.before_add is not None:
      callback, self.before_add = self.before_add, None
      callback()
    process = _REAL_POPEN(argv, env=environment, **kwargs)
    try:
      stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
      process.kill()
      process.communicate()
      raise
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if command[:2] == ["worktree", "add"] and self.after_add_timeout:
      raise subprocess.TimeoutExpired(argv, timeout)
    if check:
      result.check_returncode()
    return result

  def git(self, repo, *args):
    return self(["/usr/bin/git", "-C", str(repo), *args], check=True, _fixture_mutation=True).stdout

  def adds(self):
    return [argv for argv, _ in self.calls if "worktree" in argv and "add" in argv]


@pytest.fixture
def git_case(tmp_path):
  # 只提供已准入的 Git；其它通用子进程防护保持启用。
  (Path(os.environ["PATH"]) / "git").symlink_to("/usr/bin/git")
  runner = SyntheticGit(tmp_path)
  root = tmp_path / "projects"
  root.mkdir()
  repo = root / "original"
  repo.mkdir()
  runner.git(repo, "init", "-b", "main")
  (repo / "tracked.txt").write_text("original\n")
  runner.git(repo, "add", "tracked.txt")
  runner.git(repo, "commit", "-m", "synthetic initial")
  document = {"model": "structured-v1", "include_rotom": False,
    "herdr_binary": "fixture-herdr", "session": "trial",
    "templates": {"trial": {"order": ["shell"], "initial": "shell",
      "tab_types": {"shell": {"label": "Shell", "launcher": "shell"}}}},
    "sources": [{"id": "projects", "path": str(root), "mode": "git", "template": "trial"}],
    "workspaces": []}
  local = tmp_path / "machine.toml"
  local.write_text(tomlkit.dumps({"schema_version": 1, "machine": {"id": "synthetic", "work": document}}))
  local.chmod(0o600)
  settings = read_settings(local=local)
  from termcfg import work_git
  return SimpleNamespace(api=work_git, run=runner, repo=repo, root=root, settings=settings,
    path=root / "created", tmp=tmp_path)


def preview(case, **kwargs):
  values = {"repo": case.repo, "path": case.path, "template": "trial",
    "new_branch": "created", "base": "HEAD", "run": case.run}
  values.update(kwargs)
  return case.api.preview(case.settings, **values)


def tree_bytes(root):
  return {str(path.relative_to(root)): (os.readlink(path).encode() if path.is_symlink() else path.read_bytes())
    for path in root.rglob("*") if path.is_file() or path.is_symlink()}


@pytest.mark.parametrize("options", [
  {"new_branch": None, "base": None},
  {"new_branch": "created", "base": None},
  {"existing_branch": "main"},
  {"new_branch": None, "existing_branch": "main", "base": "HEAD"},
])
def test_branch_modes_are_explicit_and_exclusive(git_case, options):
  case = git_case
  before = tree_bytes(case.tmp)
  with pytest.raises(TermcfgError):
    preview(case, **options)
  assert tree_bytes(case.tmp) == before and not case.run.adds()


@pytest.mark.parametrize("mode", ["new", "existing"])
def test_new_creation_or_existing_capability_refusal_preserves_dirty_sentinels(git_case, mode):
  case = git_case
  if mode == "existing":
    case.run.git(case.repo, "branch", "available")
  marker = case.tmp / "hook-ran"
  hook = case.repo / ".git" / "hooks" / "post-checkout"
  hook.write_text("#!/bin/sh\nprintf invoked > '" + str(marker) + "'\n")
  hook.chmod(0o700)
  monitor = case.tmp / "fsmonitor"
  monitor.write_text("#!/bin/sh\nprintf invoked > '" + str(marker) + "'\n")
  monitor.chmod(0o700)
  case.run.git(case.repo, "config", "core.fsmonitor", str(monitor))
  (case.repo / "tracked.txt").write_text("staged change\n")
  case.run.git(case.repo, "-c", "core.fsmonitor=false", "add", "tracked.txt")
  (case.repo / "tracked.txt").write_text("unstaged change\n")
  (case.repo / "untracked.txt").write_text("untracked sentinel\n")
  files = [case.repo / "tracked.txt", case.repo / "untracked.txt", case.repo / ".git/index", case.repo / ".git/config"]
  before = {path: path.read_bytes() for path in files}
  repository_before = tree_bytes(case.repo)
  preview_before = tree_bytes(case.tmp)
  plan = preview(case, **({"new_branch": None, "base": None, "existing_branch": "available"} if mode == "existing" else {}))
  assert isinstance(plan.facts, dict) and len(plan.fingerprint) == 64 and isinstance(plan.as_dict(), dict)
  assert not case.run.adds() and not case.path.exists() and not marker.exists()
  assert tree_bytes(case.tmp) == preview_before
  if mode == "existing":
    with pytest.raises(TermcfgError) as error:
      case.api.create(case.settings, plan, run=case.run)
    assert error.value.code == 5
    assert error.value.reason == "work_git_existing_branch_atomic_guard_unavailable"
    assert not case.run.adds() and not case.path.exists() and not marker.exists()
    assert tree_bytes(case.repo) == repository_before
    assert {path: path.read_bytes() for path in files} == before
    assert case.run.git(case.repo, "rev-parse", "refs/heads/available") == case.run.git(case.repo, "rev-parse", "HEAD")
    return
  result = case.api.create(case.settings, plan, run=case.run)
  assert isinstance(result, dict) and case.path.is_dir()
  assert case.run.git(case.path, "symbolic-ref", "--short", "HEAD").strip() == b"created"
  assert len(case.run.adds()) == 1 and not marker.exists()
  assert {path: path.read_bytes() for path in files} == before
  argv = case.run.adds()[0]
  assert "core.fsmonitor=false" in argv and "worktree.guessRemote=false" in argv
  hooks = [value.split("=", 1)[1] for value in argv if value.startswith("core.hooksPath=")]
  assert len(hooks) == 1 and hooks[0] != str(hook.parent)
  assert "-b" in argv and argv[-1] == case.run.git(case.repo, "rev-parse", "HEAD").decode().strip()


@pytest.mark.parametrize("destination", ["existing", "hidden", "excluded", "too-deep"])
def test_destination_requires_absence_and_visible_source_coverage(git_case, destination):
  case = git_case
  if destination == "existing":
    case.path.mkdir()
  elif destination == "hidden":
    case.path = case.root / ".hidden"
  elif destination == "excluded":
    case.settings.structured["sources"][0]["exclude"] = ["created"]
  else:
    parent = case.root / "nested"
    parent.mkdir()
    case.path = parent / "created"
  with pytest.raises(TermcfgError):
    preview(case)
  assert not case.run.adds()


def test_builtin_or_unregistered_repository_does_not_authorize_creation(git_case):
  case = git_case
  case.settings.structured["sources"] = []
  case.settings = replace(case.settings, repo_root=case.repo)
  case.settings.structured.update(include_rotom=True, rotom_template="trial")
  with pytest.raises(TermcfgError):
    preview(case)
  assert not case.path.exists() and not case.run.adds()


def test_occupied_and_ambiguous_local_refs_refuse_without_creation(git_case):
  case = git_case
  case.run.git(case.repo, "tag", "main")
  with pytest.raises(TermcfgError):
    preview(case, base="main")
  with pytest.raises(TermcfgError):
    preview(case, new_branch=None, base=None, existing_branch="main")
  assert not case.path.exists() and not case.run.adds()


def test_executable_checkout_filter_is_refused_without_running_it(git_case):
  case = git_case
  marker = case.tmp / "filter-ran"
  script = case.tmp / "filter"
  script.write_text("#!/bin/sh\nprintf invoked > '" + str(marker) + "'\n/bin/cat\n")
  script.chmod(0o700)
  (case.repo / ".gitattributes").write_text("*.txt filter=synthetic\n")
  case.run.git(case.repo, "add", ".gitattributes")
  case.run.git(case.repo, "commit", "-m", "synthetic attributes")
  case.run.git(case.repo, "config", "filter.synthetic.smudge", str(script))
  case.run.git(case.repo, "config", "filter.synthetic.required", "true")
  before = tree_bytes(case.repo)
  with pytest.raises(TermcfgError):
    plan = preview(case)
    case.api.create(case.settings, plan, run=case.run)
  assert not marker.exists() and not case.path.exists() and not case.run.adds()
  assert tree_bytes(case.repo) == before


def test_destination_race_refuses_before_dispatch(git_case):
  case = git_case
  plan = preview(case)
  case.path.mkdir()
  sentinel = case.path / "foreign"
  sentinel.write_text("must remain")
  with pytest.raises(TermcfgError):
    case.api.create(case.settings, plan, run=case.run)
  assert sentinel.read_text() == "must remain" and not case.run.adds()


def test_timeout_after_git_applied_retains_checkout_and_never_retries(git_case):
  case = git_case
  plan = preview(case)
  case.run.after_add_timeout = True
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=case.run)
  assert error.value.code == 4 and case.path.is_dir()
  assert case.run.git(case.repo, "show-ref", "--verify", "refs/heads/created")
  assert len(case.run.adds()) == 1
  before = tree_bytes(case.tmp)
  report = case.api.report(case.settings, run=case.run)
  assert isinstance(report, dict) and tree_bytes(case.tmp) == before
  with pytest.raises(TermcfgError):
    case.api.create(case.settings, plan, run=case.run)
  assert len(case.run.adds()) == 1 and case.path.is_dir()


def test_existing_capability_gate_prevents_dispatch_and_remote_guess_race(git_case):
  case = git_case
  tip = case.run.git(case.repo, "rev-parse", "HEAD").decode().strip()
  case.run.git(case.repo, "branch", "available")
  case.run.git(case.repo, "config", "remote.synthetic.url", str(case.tmp / "never-contacted.git"))
  case.run.git(case.repo, "config", "remote.synthetic.fetch", "+refs/heads/*:refs/remotes/synthetic/*")
  case.run.git(case.repo, "update-ref", "refs/remotes/synthetic/available", tip)
  plan = preview(case, new_branch=None, base=None, existing_branch="available")
  before = tree_bytes(case.repo)
  case.run.before_add = lambda: case.run.git(case.repo, "branch", "-D", "available")
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=case.run)
  local = case.run(["/usr/bin/git", "-C", str(case.repo), "show-ref", "--verify", "refs/heads/available"])
  assert error.value.code == 5
  assert error.value.reason == "work_git_existing_branch_atomic_guard_unavailable"
  assert not case.run.adds() and not case.path.exists()
  assert local.returncode == 0 and local.stdout.split()[0].decode() == tip
  assert tree_bytes(case.repo) == before and case.run.before_add is not None


@pytest.mark.parametrize("section", ["template", "source"])
def test_manual_configuration_change_after_preview_refuses_dispatch(git_case, section):
  case = git_case
  plan = preview(case)
  document = tomlkit.parse(case.settings.local_path.read_text())
  ordinary = document["machine"]["work"]
  if section == "template":
    ordinary["templates"]["trial"]["tab_types"]["shell"]["launcher"] = "editor"
  else:
    ordinary["sources"][0]["exclude"] = ["created"]
  case.settings.local_path.write_text(tomlkit.dumps(document))
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=case.run)
  assert error.value.code in (2, 4)
  assert not case.run.adds() and not case.path.exists()


def test_repository_replacement_at_dispatch_is_never_reported_complete(git_case):
  case = git_case
  plan = preview(case)
  moved = case.root / "reviewed-original"
  def replace_repository():
    case.repo.rename(moved)
    case.repo.mkdir()
    case.run.git(case.repo, "init", "-b", "main")
  case.run.before_add = replace_repository
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=case.run)
  assert error.value.code == 4
  assert not (case.repo / ".git/refs/heads/created").exists()
  assert (moved / "tracked.txt").read_text() == "original\n"


@pytest.mark.parametrize("effect,ended,outcome", [
  ("none", True, "failed"),
  ("branch", True, "partial"),
  ("checkout", True, "partial"),
  ("none", False, "unknown"),
  ("branch", False, "partial"),
  ("checkout", False, "partial"),
])
def test_failed_creation_classifies_only_proved_effects_and_retains_blocking(git_case, effect, ended, outcome):
  case = git_case
  plan = preview(case)
  def run(argv, **kwargs):
    if "worktree" not in argv or "add" not in argv:
      return case.run(argv, **kwargs)
    if effect == "checkout":
      case.run(argv, **kwargs)
    elif effect == "branch":
      case.run.git(case.repo, "branch", "created")
    if ended:
      return subprocess.CompletedProcess(argv, 1, b"private output", b"private diagnostic")
    raise subprocess.TimeoutExpired(argv, 1)
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=run)
  assert error.value.code == 4
  assert error.value.reason == "work_git_result_" + outcome + "_checkout_retained"
  before = tree_bytes(case.tmp)
  row = case.api.report(case.settings, run=case.run)["git_operations"][0]
  assert row["phase"] == "unknown" and row["outcome"] == outcome
  assert row["command_returncode"] == (1 if ended else None)
  assert tree_bytes(case.tmp) == before
  assert all(b"private output" not in data and b"private diagnostic" not in data for data in before.values())
  assert case.path.exists() == (effect == "checkout")
  with pytest.raises(TermcfgError) as blocked:
    case.api.create(case.settings, plan, run=case.run)
  assert blocked.value.reason == "work_git_recovery_required"


def test_unavailable_observation_is_unknown_even_after_nonzero_exit(git_case, monkeypatch):
  case = git_case
  plan = preview(case)
  def run(argv, **kwargs):
    if "worktree" in argv and "add" in argv:
      return subprocess.CompletedProcess(argv, 1, b"", b"")
    return case.run(argv, **kwargs)
  monkeypatch.setattr(case.api, "_observation", lambda *args, **kwargs: None)
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=run)
  assert error.value.reason == "work_git_result_unknown_checkout_retained"
  assert case.api.report(case.settings, run=case.run)["git_operations"][0]["outcome"] == "unknown"


def test_legacy_unknown_receipt_cannot_infer_failure_from_absence(git_case):
  from termcfg.work_state import GitState
  case = git_case
  plan = preview(case)
  with GitState(create=True) as state:
    state.publish("a" * 32, plan.facts)
    state.update("a" * 32, "dispatched")
    state.update("a" * 32, "unknown")
  before = tree_bytes(case.tmp)
  row = case.api.report(case.settings, run=case.run)["git_operations"][0]
  assert row["outcome"] == "unknown" and row["command_returncode"] is None
  assert tree_bytes(case.tmp) == before


@pytest.mark.parametrize("foreign", ["path", "branch"])
def test_unrelated_residue_does_not_prove_partial_success(git_case, foreign):
  case = git_case
  plan = preview(case)
  if foreign == "branch":
    (case.repo / "tracked.txt").write_text("another commit\n")
    case.run.git(case.repo, "add", "tracked.txt")
    case.run.git(case.repo, "commit", "-m", "synthetic second")
    other = case.run.git(case.repo, "rev-parse", "HEAD").decode().strip()
    plan = preview(case, base=plan.facts["commit"])
  def run(argv, **kwargs):
    if "worktree" in argv and "add" in argv:
      if foreign == "path":
        case.path.mkdir()
      else:
        case.run.git(case.repo, "branch", "created", other)
      return subprocess.CompletedProcess(argv, 1, b"", b"")
    return case.run(argv, **kwargs)
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=run)
  assert error.value.reason == "work_git_result_unknown_checkout_retained"
  assert case.api.report(case.settings, run=case.run)["git_operations"][0]["outcome"] == "unknown"


def test_completed_report_is_historical_even_when_current_observation_unavailable(git_case, monkeypatch):
  case = git_case
  case.api.create(case.settings, preview(case), run=case.run)
  monkeypatch.setattr(case.api, "_observation", lambda *args, **kwargs: None)
  before = tree_bytes(case.tmp)
  row = case.api.report(case.settings, run=case.run)["git_operations"][0]
  assert row["outcome"] == "completed" and row["command_returncode"] == 0
  assert row["observation"] is None and tree_bytes(case.tmp) == before


def test_git_receipt_returncode_is_strict_and_legacy_compatible(git_case):
  from termcfg.work_state import GitState, json_bytes
  case = git_case
  plan = preview(case)
  op = "a" * 32
  with GitState(create=True) as state:
    state.publish(op, plan.facts)
    assert state.records()[0]["command_returncode"] is None
    state.update(op, "dispatched")
    with pytest.raises(TermcfgError):
      state.update(op, "unknown", command_returncode=True)
    assert state.records()[0]["phase"] == "dispatched"
    state.update(op, "unknown", command_returncode=1)
    assert state.records()[0]["command_returncode"] == 1
    receipt = state._read("receipts", op)
    receipt["command_returncode"] = True
    state.tree.write_state("receipts/" + op + ".json", json_bytes(receipt))
    with pytest.raises(TermcfgError):
      state.records()


@pytest.mark.parametrize("path_errno", [errno.EACCES, errno.EIO])
def test_unreadable_destination_cannot_prove_failed_without_effects(git_case, monkeypatch, path_errno):
  case = git_case
  plan = preview(case)
  original_lstat = os.lstat
  def lstat(path, *args, **kwargs):
    if os.fspath(path) == str(case.path):
      raise OSError(path_errno, "synthetic unavailable destination")
    return original_lstat(path, *args, **kwargs)
  def run(argv, **kwargs):
    if "worktree" in argv and "add" in argv:
      monkeypatch.setattr(os, "lstat", lstat)
      return subprocess.CompletedProcess(argv, 1, b"", b"")
    return case.run(argv, **kwargs)
  with pytest.raises(TermcfgError) as error:
    case.api.create(case.settings, plan, run=run)
  assert error.value.reason == "work_git_result_unknown_checkout_retained"
  row = case.api.report(case.settings, run=case.run)["git_operations"][0]
  assert row["outcome"] == "unknown" and row["observation"] is None
  assert row["command_returncode"] == 1
