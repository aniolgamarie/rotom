"""显式 O 层：独立合成进程竞争临时 Git 根，不启动宿主。"""
import json
import time
from pathlib import Path

import pytest

from test_pi_workspace_leases import worktree


pytestmark = pytest.mark.pi_lease_os


def wait_for(path, handle=None):
  deadline = time.monotonic() + 5
  while time.monotonic() < deadline:
    if path.exists(): return
    if handle is not None and handle.poll() is not None:
      pytest.fail("synthetic worker exited before checkpoint")
    time.sleep(0.01)
  pytest.fail("synthetic worker checkpoint timed out")


def case(tmp_path, name, workspace):
  root = tmp_path / name; root.mkdir()
  (root / "case.json").write_text(json.dumps({"role": name, "workspace": str(workspace)}))
  return root


def launch(pi_lease_worker, case_root, scenario):
  handle = pi_lease_worker.start(case_root, scenario)
  wait_for(case_root / "ready", handle)
  return handle


def result(case_root, handle):
  wait_for(case_root / "result.json", handle)
  return json.loads((case_root / "result.json").read_bytes())


@pytest.mark.parametrize("path_kind", ["alias", "subdirectory"])
def test_two_independent_profiles_admit_exactly_one_live_writer(tmp_path, pi_lease_worker, path_kind):
  root = worktree(tmp_path)
  if path_kind == "alias":
    second = tmp_path / "alias"; second.symlink_to(root, target_is_directory=True)
  else:
    second = root / "nested"; second.mkdir()
  cases = [case(tmp_path, "one", root), case(tmp_path, "two", second)]
  handles = [launch(pi_lease_worker, value, "reserve") for value in cases]
  assert handles[0].pid != handles[1].pid
  for value in cases: (value / "go").touch()
  outcomes = [result(value, handle) for value, handle in zip(cases, handles)]
  assert sorted(value["outcome"] for value in outcomes) == ["busy", "reserved"]
  writer = outcomes.index(next(value for value in outcomes if value["outcome"] == "reserved"))
  active = [index for index, (value, handle) in enumerate(zip(cases, handles)) if (value / "active.json").exists() and handle.poll() is None]
  assert active == [writer]
  assert json.loads((cases[writer] / "active.json").read_bytes())["pid"] == handles[writer].pid
  assert outcomes[0]["workspace_key"] == outcomes[1]["workspace_key"]
  assert outcomes[0]["home"] != outcomes[1]["home"]
  assert all(Path(value["home"]).is_relative_to(tmp_path) for value in outcomes)
  saved = json.loads((root / ".git/agentcfg/write-lease.json").read_bytes())
  assert saved["instance_id"] == "profile-" + cases[writer].name
  assert handles[writer].poll() is None


def test_actual_flock_busy_then_release_allows_new_reservation(tmp_path, pi_lease_worker):
  root = worktree(tmp_path)
  held = case(tmp_path, "holder", root); holder = launch(pi_lease_worker, held, "hold-lock")
  (held / "go").touch(); wait_for(held / "active.json", holder)
  denied = case(tmp_path, "two", root); probe = launch(pi_lease_worker, denied, "reserve")
  (denied / "go").touch()
  assert result(denied, probe)["outcome"] == "busy" and holder.poll() is None
  assert not (root / ".git/agentcfg/write-lease.json").exists()
  holder.stop(); assert holder.wait(timeout=5) == 0
  allowed = case(tmp_path, "probe", root); next_worker = launch(pi_lease_worker, allowed, "reserve")
  (allowed / "go").touch()
  assert result(allowed, next_worker)["outcome"] == "reserved" and next_worker.poll() is None


def test_direct_exit_before_commit_releases_kernel_lock_without_lease(tmp_path, pi_lease_worker):
  root = worktree(tmp_path)
  crashing = case(tmp_path, "one", root); first = launch(pi_lease_worker, crashing, "exit-before-commit")
  (crashing / "go").touch(); wait_for(crashing / "active.json", first)
  busy = case(tmp_path, "two", root); other = launch(pi_lease_worker, busy, "reserve")
  (busy / "go").touch(); assert result(busy, other)["outcome"] == "busy"
  (crashing / "exit").touch(); assert first.wait(timeout=5) == 71
  assert not (root / ".git/agentcfg/write-lease.json").exists()
  allowed = case(tmp_path, "probe", root); next_worker = launch(pi_lease_worker, allowed, "reserve")
  (allowed / "go").touch(); assert result(allowed, next_worker)["outcome"] == "reserved"
  assert next_worker.poll() is None


def test_direct_exit_after_reserved_without_reply_retains_unknown_occupancy(tmp_path, pi_lease_worker):
  root = worktree(tmp_path)
  crashing = case(tmp_path, "one", root); first = launch(pi_lease_worker, crashing, "exit-after-reserved")
  (crashing / "go").touch(); assert first.wait(timeout=5) == 72
  assert (crashing / "persisted").exists() and not (crashing / "result.json").exists()
  marker = root / ".git/agentcfg/write-lease.json"; before = marker.read_bytes()
  assert json.loads(before)["state"] == "reserved"
  other_case = case(tmp_path, "two", root); other = launch(pi_lease_worker, other_case, "reserve")
  (other_case / "go").touch(); assert result(other_case, other)["outcome"] == "busy"
  assert marker.read_bytes() == before and not (other_case / "active.json").exists()


def test_fixed_worker_rejects_invalid_scenario_paths_and_arbitrary_argv(tmp_path, pi_lease_worker):
  root = worktree(tmp_path); valid = case(tmp_path, "one", root)
  with pytest.raises(ValueError): pi_lease_worker.start(valid, "shell")
  with pytest.raises(TypeError): pi_lease_worker.start(valid, "reserve", argv=["git"])
  outside = tmp_path / "nested"; outside.mkdir(); inner = outside / "case"; inner.mkdir()
  with pytest.raises(ValueError): pi_lease_worker.start(inner, "reserve")
  alias = tmp_path / "case-link"; alias.symlink_to(valid, target_is_directory=True)
  with pytest.raises(ValueError): pi_lease_worker.start(alias, "reserve")
  escape = tmp_path / "escape"; escape.symlink_to(tmp_path.parent, target_is_directory=True)
  (valid / "case.json").write_text(json.dumps({"role": "one", "workspace": str(escape)}))
  with pytest.raises(ValueError): pi_lease_worker.start(valid, "reserve")
  assert pi_lease_worker.handles == []



def test_child_environment_is_closed_and_global_guards_remain_installed(tmp_path, pi_lease_worker, monkeypatch):
  import os
  import socket
  import subprocess
  import sys
  monkeypatch.setenv("SYNTHETIC_AUTH_TOKEN", "synthetic-unused-secret")
  root = worktree(tmp_path); value = case(tmp_path, "one", root)
  handle = launch(pi_lease_worker, value, "reserve"); (value / "go").touch()
  outcome = result(value, handle)
  assert outcome["env_keys"] == sorted({"HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMPDIR", "PATH", "LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE"})
  assert outcome["guards"] == {"network": True, "process": True, "fork": True}
  assert "synthetic-unused-secret" not in (value / "result.json").read_text()
  assert handle.poll() is None
  with pytest.raises(RuntimeError, match="process disabled"): subprocess.Popen([sys.executable, "-c", "pass"])
  with pytest.raises(RuntimeError, match="network disabled"): socket.socket()
  with pytest.raises(RuntimeError, match="process disabled"): os.fork()


@pytest.mark.parametrize("kind", ["nested-git", "linked-worktree"])
@pytest.mark.parametrize("child_first", [False, True])
def test_independent_workers_cannot_overlap_physical_git_roots(tmp_path, pi_lease_worker, kind, child_first):
  from test_pi_workspace_overlap import nested_worktree
  parent, child = nested_worktree(tmp_path, kind)
  if kind == "linked-worktree":
    (parent / ".git/worktrees/nested/HEAD").write_text("ref: refs/heads/fixture\n")
  first_path, second_path = (child, parent) if child_first else (parent, child)
  held = case(tmp_path, "one", first_path)
  first = launch(pi_lease_worker, held, "reserve")
  (held / "go").touch()
  assert result(held, first)["outcome"] == "reserved"
  other = case(tmp_path, "two", second_path)
  second = launch(pi_lease_worker, other, "reserve")
  (other / "go").touch()
  assert result(other, second)["outcome"] == "busy"
  assert first.poll() is None
  active = json.loads((held / "active.json").read_bytes())
  assert active["pid"] == first.pid
  assert not (other / "active.json").exists()
  table = json.loads((tmp_path / "os-account/.agentcfg-workspaces/claims.json").read_bytes())
  assert len(table["claims"]) == 1 and table["claims"][0]["record"]["instance_id"] == "profile-one"


def test_unrelated_roots_have_two_simultaneously_active_workers(tmp_path, pi_lease_worker):
  cases = [case(tmp_path, name, worktree(tmp_path, name + "-work")) for name in ("one", "two")]
  handles = []
  for value in cases:
    handle = launch(pi_lease_worker, value, "reserve"); handles.append(handle)
    (value / "go").touch()
    assert result(value, handle)["outcome"] == "reserved"
  assert handles[0].pid != handles[1].pid
  assert all(handle.poll() is None for handle in handles)
  assert all(json.loads((value / "active.json").read_bytes())["pid"] == handle.pid for value, handle in zip(cases, handles))
  table = json.loads((tmp_path / "os-account/.agentcfg-workspaces/claims.json").read_bytes())
  assert len(table["claims"]) == 2
  assert {item["record"]["instance_id"] for item in table["claims"]} == {"profile-one", "profile-two"}


@pytest.mark.parametrize("committed", [False, True])
def test_sigkill_releases_kernel_lock_but_keeps_committed_writer_unknown(tmp_path, pi_lease_worker, committed):
  root = worktree(tmp_path)
  first_case = case(tmp_path, "one", root)
  first = launch(pi_lease_worker, first_case, "reserve" if committed else "exit-before-commit")
  (first_case / "go").touch(); wait_for(first_case / "active.json", first)
  if committed: assert result(first_case, first)["outcome"] == "reserved"
  marker = root / ".git/agentcfg/write-lease.json"
  before = marker.read_bytes() if committed else None
  first.crash(); assert first.wait(timeout=5) == -9
  second_case = case(tmp_path, "two", root)
  second = launch(pi_lease_worker, second_case, "reserve"); (second_case / "go").touch()
  assert result(second_case, second)["outcome"] == ("busy" if committed else "reserved")
  if committed:
    assert marker.read_bytes() == before and not (second_case / "active.json").exists()
  else:
    assert second.poll() is None and (second_case / "active.json").exists()
