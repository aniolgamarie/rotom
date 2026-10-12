"""默认纯协议；显式O层只运行固定、自有、断网的非Gitworker。"""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest


WORKER = Path(__file__).parent / "fixtures/pi/non-git-workspace-worker.py"
SPEC = importlib.util.spec_from_file_location("non_git_worker_protocol", WORKER)
protocol = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(protocol)


def case(tmp_path, name, workspace, roots=()):
  path = tmp_path / name; path.mkdir()
  (path / "case.json").write_text(json.dumps({"workspace": str(workspace), "register": [str(root) for root in roots]}))
  return path


def wait(path, handle):
  deadline = time.monotonic() + 5
  while time.monotonic() < deadline:
    if path.exists(): return
    if handle.poll() is not None: pytest.fail("fixed worker exited before checkpoint")
    time.sleep(0.01)
  pytest.fail("fixed worker checkpoint timed out")


def launch(fixture, value, scenario="reserve"):
  handle = fixture.start(value, scenario); wait(value / "ready", handle)
  (value / "go").touch(); return handle


def observation(value, handle):
  wait(value / "result.json", handle)
  return json.loads((value / "result.json").read_bytes())


def register(fixture, tmp_path, root, roots):
  value = case(tmp_path, "registration", root, roots)
  handle = launch(fixture, value, "register")
  assert observation(value, handle)["outcome"] == "registered"
  assert handle.wait(timeout=5) == 0


def assert_live(handles, values, expected):
  active = [value for value, handle in zip(values, handles) if (value / "active.json").exists() and handle.poll() is None]
  assert len(active) == expected
  assert len({handle.pid for handle in handles}) == len(handles)


def test_launcher_closed_mounts_and_default_guards(tmp_path):
  root = tmp_path / "work"; root.mkdir()
  value = case(tmp_path, "one", root)
  argv = protocol.invocation(value, tmp_path, "reserve", sys.executable)
  assert argv[:8] == ["/bin/bwrap", "--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL", "--ro-bind", "/usr"]
  assert ("--ro-bind", "/bin", "/bin") in tuple(zip(argv, argv[1:], argv[2:]))
  binds = [argv[index + 1:index + 3] for index, item in enumerate(argv) if item == "--bind"]
  assert binds == [[str(tmp_path), str(tmp_path)]]
  assert ["--tmpfs", "/tmp"] == argv[argv.index("--tmpfs"):argv.index("--tmpfs") + 2]
  assert argv[-4:] == ["-I", str(WORKER.resolve()), str(value), "reserve"]
  env = {argv[index + 1]: argv[index + 2] for index, item in enumerate(argv) if item == "--setenv"}
  assert set(env) == protocol.ENV_NAMES and env["HOME"] == str(value / "home")
  with pytest.raises(RuntimeError): subprocess.Popen([sys.executable])
  with pytest.raises(RuntimeError): socket.socket()
  with pytest.raises(RuntimeError): os.fork()


@pytest.mark.parametrize("fault", ["scenario", "nested", "case-link", "escape", "unknown", "control-link", "race-link", "race-directory", "race-hardlink"])
def test_launcher_rejects_external_routes(tmp_path, fault):
  root = tmp_path / "work"; root.mkdir(); value = case(tmp_path, "one", root)
  scenario = "reserve"
  if fault == "scenario": scenario = "shell"
  if fault == "nested":
    parent = tmp_path / "inner"; parent.mkdir(); value = case(parent, "one", root)
  if fault == "case-link":
    alias = tmp_path / "alias"; alias.symlink_to(value); value = alias
  if fault == "escape": (value / "case.json").write_text(json.dumps({"workspace": str(tmp_path.parent), "register": []}))
  if fault == "unknown": (value / "case.json").write_text(json.dumps({"workspace": str(root), "register": [], "argv": ["sh"]}))
  if fault == "control-link": (value / "go").symlink_to(root)
  if fault == "race-link": (tmp_path / "race-go").symlink_to(root)
  if fault == "race-directory": (tmp_path / "race-go").mkdir()
  if fault == "race-hardlink":
    source = tmp_path / "external-control"; source.touch(); os.link(source, tmp_path / "race-go")
  with pytest.raises(ValueError): protocol.invocation(value, tmp_path, scenario, sys.executable)


@pytest.mark.parametrize("fault", ["dead-process", "no-active-marker", "duplicate-handle"])
def test_live_oracle_requires_parent_observed_process_and_marker(tmp_path, fault):
  from types import SimpleNamespace
  root = tmp_path / "work"; root.mkdir()
  values = [case(tmp_path, name, root) for name in ("one", "two")]
  for value in values: (value / "active.json").write_text("{}")
  handles = [SimpleNamespace(pid=10 + index, poll=lambda: None) for index in range(2)]
  assert_live(handles, values, 2)
  if fault == "dead-process": handles[1].poll = lambda: 0
  if fault == "no-active-marker": (values[1] / "active.json").unlink()
  if fault == "duplicate-handle": handles[1].pid = handles[0].pid
  with pytest.raises(AssertionError): assert_live(handles, values, 2)


def test_fixture_opt_in_does_not_remove_global_guards(tmp_path, pi_non_git_worker):
  root = tmp_path / "work"; root.mkdir(); value = case(tmp_path, "one", root)
  with pytest.raises(RuntimeError, match="explicit opt-in"): pi_non_git_worker.start(value, "reserve")
  assert pi_non_git_worker.handles == []
  with pytest.raises(RuntimeError): subprocess.Popen([sys.executable])
  with pytest.raises(RuntimeError): socket.socket()


@pytest.mark.pi_lease_os
@pytest.mark.parametrize("kind", ["alias", "subdirectory", "child-first", "parent-first"])
def test_physical_overlap_denies_second_independent_writer(tmp_path, pi_non_git_worker, kind):
  root = tmp_path / "work"; root.mkdir(); child = root / "child"; child.mkdir()
  alias = tmp_path / "alias"; alias.symlink_to(root, target_is_directory=True)
  register(pi_non_git_worker, tmp_path, root, [root, child] if "first" in kind else [root])
  paths = {"alias": (root, alias), "subdirectory": (root, child), "child-first": (child, root), "parent-first": (root, child)}[kind]
  values = [case(tmp_path, name, path) for name, path in zip(("one", "two"), paths)]
  first = launch(pi_non_git_worker, values[0]); initial = observation(values[0], first)
  assert initial["outcome"] == "reserved"
  assert initial["planned"]["workspace_kind"] == "registered-root"
  assert initial["planned"]["git_dir_path"] is None and initial["planned"]["git_dir_identity"] is None
  second = launch(pi_non_git_worker, values[1]); denied = observation(values[1], second)
  assert denied["outcome"] == "denied"
  assert initial["home"] != denied["home"]
  assert initial["guards"] == denied["guards"] == {"network": True, "process": True, "fork": True}
  assert initial["private_tmp"] and denied["private_tmp"]
  assert_live([first, second], values, 1)
  table = json.loads((tmp_path / "os-account/.agentcfg-workspaces/claims.json").read_bytes())
  assert len(table["claims"]) == 1 and table["claims"][0]["record"]["instance_id"] == "profile-one"


@pytest.mark.pi_lease_os
def test_unrelated_roots_simultaneously_hold_claims(tmp_path, pi_non_git_worker):
  roots = [tmp_path / name for name in ("left", "right")]
  for root in roots: root.mkdir()
  register(pi_non_git_worker, tmp_path, roots[0], roots)
  values = [case(tmp_path, name, root) for name, root in zip(("one", "two"), roots)]
  handles = []
  for value in values:
    handle = launch(pi_non_git_worker, value); handles.append(handle)
    assert observation(value, handle)["outcome"] == "reserved"
  assert_live(handles, values, 2)
  assert len(json.loads((tmp_path / "os-account/.agentcfg-workspaces/claims.json").read_bytes())["claims"]) == 2


@pytest.mark.pi_lease_os
@pytest.mark.parametrize("registered", [False, True])
def test_unregistered_or_replaced_root_denied(tmp_path, pi_non_git_worker, registered):
  root = tmp_path / "work"; root.mkdir()
  if registered:
    register(pi_non_git_worker, tmp_path, root, [root]); root.rename(tmp_path / "old"); root.mkdir()
  value = case(tmp_path, "one", root); handle = launch(pi_non_git_worker, value)
  assert observation(value, handle)["outcome"] == "denied"
  assert not (value / "active.json").exists()
  assert not (tmp_path / "os-account/.agentcfg-workspaces/claims.json").exists()


@pytest.mark.pi_lease_os
def test_exit_before_reserve_releases_lock_and_allows_new_writer(tmp_path, pi_non_git_worker):
  root = tmp_path / "work"; root.mkdir(); register(pi_non_git_worker, tmp_path, root, [root])
  value = case(tmp_path, "one", root); first = launch(pi_non_git_worker, value, "exit-before-reserve")
  wait(value / "active.json", first)
  other = case(tmp_path, "two", root); second = launch(pi_non_git_worker, other)
  assert observation(other, second)["outcome"] == "denied"
  (value / "exit").touch(); assert first.wait(timeout=5) == 71
  assert not (tmp_path / "os-account/.agentcfg-workspaces/claims.json").exists()
  next_case = case(tmp_path, "three", root); third = launch(pi_non_git_worker, next_case)
  assert observation(next_case, third)["outcome"] == "reserved" and third.poll() is None


@pytest.mark.pi_lease_os
def test_exit_after_reserve_keeps_persistent_protection(tmp_path, pi_non_git_worker):
  root = tmp_path / "work"; root.mkdir(); register(pi_non_git_worker, tmp_path, root, [root])
  value = case(tmp_path, "one", root); first = launch(pi_non_git_worker, value, "exit-after-reserve")
  assert first.wait(timeout=5) == 72 and (value / "persisted").exists()
  assert not (value / "result.json").exists()
  file = tmp_path / "os-account/.agentcfg-workspaces/claims.json"; before = file.read_bytes()
  row = json.loads(before)["claims"][0]["record"]
  assert row["state"] == "reserved" and row["instance_id"] == "profile-one"
  local = file.parent / "workspace-leases" / row["registered_root_id"] / "write-lease.json"
  local_before = local.read_bytes()
  assert json.loads(local_before)["state"] == "reserved"
  other = case(tmp_path, "two", root); second = launch(pi_non_git_worker, other)
  assert observation(other, second)["outcome"] == "denied" and file.read_bytes() == before
  assert not (other / "active.json").exists()
  assert local.read_bytes() == local_before
  assert not (root / ".git").exists()


@pytest.mark.pi_lease_os
@pytest.mark.parametrize("kind", ["alias", "parent-child"])
def test_prepared_independent_workers_race_at_shared_gate(tmp_path, pi_non_git_worker, kind):
  root = tmp_path / "work"; root.mkdir()
  if kind == "alias":
    other = tmp_path / "alias"; other.symlink_to(root, target_is_directory=True)
    roots = [root]
  else:
    other = root / "child"; other.mkdir(); roots = [root, other]
  register(pi_non_git_worker, tmp_path, root, roots)
  values = [case(tmp_path, name, path) for name, path in zip(("one", "two"), (root, other))]
  handles = [pi_non_git_worker.start(value, "reserve-race") for value in values]
  for value, handle in zip(values, handles): wait(value / "ready", handle)
  assert all(handle.poll() is None for handle in handles)
  assert len({handle.pid for handle in handles}) == 2
  assert not any((value / "active.json").exists() or (value / "result.json").exists() for value in values)
  anchor = tmp_path / "os-account/.agentcfg-workspaces"
  assert not (anchor / "claims.json").exists()
  prepared = [json.loads((value / "ready").read_bytes())["planned"] for value in values]
  if kind == "alias": assert prepared[0] == prepared[1]
  # 两个独立进程已经identify；只写一次共享gate，不串行重试reserve。
  (tmp_path / "race-go").touch()
  outcomes = [observation(value, handle) for value, handle in zip(values, handles)]
  assert sorted(row["outcome"] for row in outcomes) == ["denied", "reserved"]
  assert_live(handles, values, 1)
  winner = next(index for index, row in enumerate(outcomes) if row["outcome"] == "reserved")
  assert handles[winner].poll() is None
  assert (values[winner] / "active.json").exists() and not (values[1 - winner] / "active.json").exists()
  claims = json.loads((anchor / "claims.json").read_bytes())["claims"]
  assert len(claims) == 1
  saved = claims[0]["record"]
  assert saved["state"] == "reserved" and saved["instance_id"] == "profile-" + values[winner].name
  assert saved["registered_root_id"] == prepared[winner]["registered_root_id"]
  markers = list((anchor / "workspace-leases").glob("*/write-lease.json"))
  assert len(markers) == 1 and json.loads(markers[0].read_bytes()) == saved


@pytest.mark.pi_lease_os
def test_alias_can_independently_reserve_original_registered_root(tmp_path, pi_non_git_worker):
  root = tmp_path / "work"; root.mkdir()
  alias = tmp_path / "alias"; alias.symlink_to(root, target_is_directory=True)
  register(pi_non_git_worker, tmp_path, root, [root])
  recorded = json.loads((tmp_path / "os-account/.agentcfg-workspaces/registry.json").read_bytes())["roots"][0]
  value = case(tmp_path, "one", alias); handle = launch(pi_non_git_worker, value)
  outcome = observation(value, handle)
  assert outcome["outcome"] == "reserved" and handle.poll() is None
  assert outcome["planned"]["registered_root_id"] == recorded["root_id"]
  assert outcome["planned"]["worktree_path"] == str(root)


@pytest.mark.pi_lease_os
@pytest.mark.parametrize("committed", [False, True])
def test_sigkill_never_clears_a_committed_non_git_writer_claim(tmp_path, pi_non_git_worker, committed):
  root = tmp_path / "work"; root.mkdir(); register(pi_non_git_worker, tmp_path, root, [root])
  first_case = case(tmp_path, "one", root)
  first = launch(pi_non_git_worker, first_case, "reserve" if committed else "exit-before-reserve")
  wait(first_case / "active.json", first)
  if committed: assert observation(first_case, first)["outcome"] == "reserved"
  marker = tmp_path / "os-account/.agentcfg-workspaces/claims.json"
  before = marker.read_bytes() if committed else None
  first.crash(); assert first.wait(timeout=5) == -9
  second_case = case(tmp_path, "two", root); second = launch(pi_non_git_worker, second_case)
  assert observation(second_case, second)["outcome"] == ("denied" if committed else "reserved")
  if committed:
    assert marker.read_bytes() == before and not (second_case / "active.json").exists()
  else:
    assert second.poll() is None and (second_case / "active.json").exists()
