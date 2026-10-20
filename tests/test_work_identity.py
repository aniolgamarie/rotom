"""checkout归一、重复和并发只复用原生项目。"""

from pathlib import Path
import subprocess
import threading

import pytest

from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work import canonical_checkout, enter_project, operation_lock
from work_helpers import FakeHerdr


def test_git_literal_arguments_and_symlink_normalization(tmp_path, monkeypatch):
  root = tmp_path / "中文 project $()`quote'"
  root.mkdir()
  sub = root / "nested"
  sub.mkdir()
  link = tmp_path / "linked"
  link.symlink_to(sub, target_is_directory=True)
  calls = []
  def run(argv, **kwargs):
    calls.append((argv, kwargs))
    return subprocess.CompletedProcess(argv, 0, str(root) + "\n", "")
  monkeypatch.setattr(subprocess, "run", run)
  assert canonical_checkout(link, Deadline()) == root.resolve()
  assert calls[0][0] == ["git", "-C", str(sub), "rev-parse", "--show-toplevel"]
  assert not calls[0][1].get("shell", False)


def test_invalid_git_before_server_side_effects(tmp_path, monkeypatch):
  monkeypatch.setattr(subprocess, "run", lambda argv, **kw:
    subprocess.CompletedProcess(argv, 128, "", "synthetic not git"))
  with pytest.raises(TermcfgError) as error:
    canonical_checkout(tmp_path, Deadline())
  assert error.value.code == 2
  for path in (tmp_path / "missing", "bad\npath"):
    with pytest.raises(TermcfgError) as error:
      canonical_checkout(path, Deadline())
    assert error.value.code == 2


def test_nine_checkouts_repeat_and_concurrent_enter(tmp_path):
  api = FakeHerdr(deadline=Deadline())
  roots = []
  for project in range(3):
    for checkout in range(3):
      root = tmp_path / str(project) / str(checkout)
      root.mkdir(parents=True)
      roots.append(root)
      enter_project(api, root)
  for i in range(100): enter_project(api, roots[i % 9])
  barrier = threading.Barrier(10)
  errors = []
  def enter():
    try:
      barrier.wait()
      with operation_lock(Deadline(), root=tmp_path / "mutex"):
        enter_project(api, roots[0])
    except BaseException as error: errors.append(error)
  threads = [threading.Thread(target=enter) for _ in range(10)]
  for t in threads: t.start()
  for t in threads: t.join()
  assert not errors
  assert len(api.workspaces) == len(api.panes) == 9
  assert sum(m == "worktree.open" for m, _ in api.requests) == 9
  assert len({w["tokens"]["rw_project"] for w in api.workspaces.values()}) == 9


def test_three_projects_three_checkouts_three_terminals_keep_native_ownership(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline())
  for project in range(3):
    for checkout in range(3):
      root = tmp_path / str(project) / str(checkout)
      root.mkdir(parents=True)
      ws = enter_project(api, root)
      for label in ("native-build", "native-debug"):
        api.request("tab.create", {"workspace_id": ws["workspace_id"], "cwd": str(root), "label": label, "env": {}})
      for _ in range(2): enter_project(api, root)
  assert len(api.workspaces) == 9 and len(api.panes) == 27
  assert sum(m == "worktree.open" for m, _ in api.requests) == 9
  assert sum(bool(p.get("tokens", {}).get("rw_role")) for p in api.panes.values()) == 9


def test_linked_worktree_open_uses_confirmed_native_parent_source(tmp_path):
  parent = tmp_path / "main"
  parent.mkdir()
  linked = tmp_path / "linked"
  linked.mkdir()
  api = FakeHerdr(deadline=Deadline())
  original = api.request
  def request(method, params=None):
    if method == "worktree.list":
      result = original(method, params)
      result["source"].update(repo_root=str(parent), source_checkout_path=str(parent))
      result["worktrees"] = [{**result["worktrees"][0], "path": str(linked), "is_linked_worktree": True}]
      return result
    if method == "worktree.open" and params["cwd"] != str(parent):
      raise TermcfgError(5, "native_linked_worktree_source")
    return original(method, params)
  api.request = request
  ws = enter_project(api, linked)
  assert ws["worktree"]["checkout_path"] == str(linked)
  assert ("worktree.open", {"cwd": str(parent), "path": str(linked), "focus": False}) in api.requests
