import json
import os
from pathlib import Path

import pytest

from agentcfg import pi_benchmark as benchmark
from agentcfg.schema import ConfigError


def _fake_runtime():
  tree = "/private/installed-tree"
  package = tree + "/pi-base-test/node_modules/@earendil-works/pi-coding-agent"
  return {
    "runtime_document_path": "/private/runtime.json", "runtime_document_sha256": "d" * 64,
    "sdk_version": "1.0.1", "sdk_root": package, "sdk_tree_root": tree,
    "sdk_tree_id": "pi-base-test", "sdk_inventory_path": "/private/inventory.json", "sdk_inventory_sha256": "e" * 64,
    "cli_path": package + "/dist/cli.js", "cli_guest_path": "/opt/sdk-tree/pi-base-test/node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
    "cli_sha256": "a" * 64, "package_path": package + "/package.json", "package_sha256": "b" * 64,
    "node_path": "/private/node", "node_guest_path": "/opt/node", "node_sha256": "f" * 64,
    "bwrap_path": "/private/bwrap", "bwrap_sha256": "c" * 64,
  }


def _fake_platform():
  machine = "x86_64"
  core = {"machine": machine, "release": "test-kernel", "os_release_sha256": "d" * 64, "bwrap_sha256": "c" * 64,
    "clock_ticks": 100, "page_size_bytes": 4096}
  return {"platform": "linux-x86_64", "kernel_release": core["release"], "os_release_sha256": core["os_release_sha256"],
    "bwrap_sha256": core["bwrap_sha256"], "node_sha256": _fake_runtime()["node_sha256"],
    "clock_ticks": core["clock_ticks"], "page_size_bytes": core["page_size_bytes"],
    "platform_identity": benchmark._sha(benchmark._bytes(core))}


def _patch_plan_inputs(monkeypatch):
  runtime = _fake_runtime()
  platform = _fake_platform()
  monkeypatch.setattr(benchmark, "fixed_runtime", lambda _path: dict(runtime))
  monkeypatch.setattr(benchmark, "platform_snapshot", lambda _runtime: dict(platform))
  monkeypatch.setattr(benchmark, "_regular_digest", lambda _path: "e" * 64)
  monkeypatch.setattr(benchmark, "_tree_digest", lambda _paths: "f" * 64)


def _plan(monkeypatch):
  _patch_plan_inputs(monkeypatch)
  return benchmark.make_plan("approval-baseline-test", per_sample_timeout_seconds=120, runtime_document_path=Path("/private/runtime.json"))


def _stat_line(pid, comm, ppid, *, state="S", start=100, utime=1, stime=2, rss=9):
  fields = [state, str(ppid), "1"] + ["0"] * 19
  fields[11] = str(utime)
  fields[12] = str(stime)
  fields[19] = str(start)
  fields[21] = str(rss)
  return f"{pid} ({comm}) " + " ".join(fields)


def _proc_entry(root, pid, *, ppid, argv, exe, namespace, start=100, state="S"):
  base = root / str(pid)
  (base / "ns").mkdir(parents=True)
  (base / "fd").mkdir()
  ns_target = root / namespace
  ns_target.touch(exist_ok=True)
  (base / "ns" / "pid").symlink_to(ns_target)
  (base / "exe").symlink_to(exe)
  (base / "stat").write_text(_stat_line(pid, "worker (test)", ppid, state=state, start=start))
  (base / "status").write_text(f"Name:\ttest\nUid:\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\nNSpid:\t{pid}\nVmRSS:\t9 kB\n")
  (base / "cmdline").write_bytes(b"\0".join(value.encode() for value in argv) + b"\0")


def test_parse_proc_stat_uses_last_parenthesis():
  row = benchmark.parse_proc_stat(_stat_line(34, "name ) with (parens", 12, start=77, utime=8, stime=9, rss=10))
  assert row["pid"] == 34
  assert row["comm"] == "name ) with (parens"
  assert row["ppid"] == 12
  assert row["starttime"] == 77
  assert row["utime"] == 8
  assert row["stime"] == 9


def test_plan_is_closed_and_auth_limits_are_fixed(monkeypatch):
  plan = _plan(monkeypatch)
  assert benchmark.validate_plan(plan) is plan
  assert plan["authorization"]["max_model_calls"] == 43
  assert plan["authorization"]["external_model_calls"] == 0
  changed = json.loads(json.dumps(plan))
  changed["input"]["response"] = "different"
  with pytest.raises(ConfigError):
    benchmark.validate_plan(changed)
  changed = json.loads(json.dumps(plan))
  changed["authorization"]["max_model_calls"] = 44
  with pytest.raises(ConfigError):
    benchmark.validate_plan(changed)
  changed = json.loads(json.dumps(plan))
  changed["platform"]["clock_ticks"] += 1
  with pytest.raises(ConfigError):
    benchmark.validate_plan(changed)
  with pytest.raises(ConfigError):
    benchmark.make_plan("approval-baseline-test", per_sample_timeout_seconds=121, runtime_document_path=Path("/private/runtime.json"))


def test_prepare_only_writes_private_plan_without_starting_process(tmp_path, monkeypatch):
  _patch_plan_inputs(monkeypatch)
  monkeypatch.setattr(benchmark, "_verify_fixed_inputs", lambda _plan: None)
  monkeypatch.setattr(benchmark.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("prepare launched a process"))
  output = tmp_path / "baseline"
  result = benchmark.prepare(output, "reviewed-reference", 120, Path("/private/runtime.json"))
  assert result == {"status": "prepared", "native_started": False, "product_gate": False, "profile": "pure-pi"}
  assert (output / "plan.json").stat().st_mode & 0o777 == 0o600
  assert (output / "runs").stat().st_mode & 0o777 == 0o700
  with pytest.raises(ConfigError):
    benchmark.prepare(output, "reviewed-reference", 120, Path("/private/runtime.json"))


def test_run_sample_keeps_outer_stderr_open_until_pipe_is_drained(tmp_path, monkeypatch):
  _patch_plan_inputs(monkeypatch)
  monkeypatch.setattr(benchmark, "_verify_fixed_inputs", lambda _plan: None)
  output = tmp_path / "baseline"; output.mkdir(mode=0o700)
  (output / "runs").mkdir(mode=0o700)
  plan = benchmark.make_plan("reviewed-reference", per_sample_timeout_seconds=120, runtime_document_path=Path("/private/runtime.json"))
  benchmark._write_new(output / "plan.json", benchmark._bytes(plan))

  class FakeProcess:
    pid = 1234
    returncode = 0
    def __init__(self):
      self.stdout = self._reader(b"")
      self.stderr = self._reader(b"synthetic bwrap diagnostic\n")
    @staticmethod
    def _reader(data):
      read_fd, write_fd = os.pipe()
      if data: os.write(write_fd, data)
      os.close(write_fd)
      return os.fdopen(read_fd, "rb", buffering=0)
    def poll(self): return 0
    def wait(self, timeout=None): return self.returncode
    def terminate(self): pass
    def kill(self): pass

  class FakeObserver:
    def __init__(self, **_kwargs): pass
    def identify(self, _pid): return {"status": "unknown", "reason": "synthetic"}

  monkeypatch.setattr(benchmark.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
  monkeypatch.setattr(benchmark, "ProcObserver", FakeObserver)
  record = benchmark.run_sample(output, "cold", 0)
  assert record["status"] == "failed"
  assert (output / "runs/cold-00/outer.stderr").read_bytes() == b"synthetic bwrap diagnostic\n"


def test_runtime_document_is_closed_private_and_hash_pinned(tmp_path):
  tree = tmp_path / "sdk-tree"; package = tree / "pi-base-test/node_modules/@earendil-works/pi-coding-agent"
  package.joinpath("dist").mkdir(parents=True)
  cli = package / "dist/cli.js"; cli.write_bytes(b"fixed cli")
  manifest = package / "package.json"; manifest.write_text(json.dumps({"name": "@earendil-works/pi-coding-agent", "version": "1.0.1"}))
  inventory = tmp_path / "inventory.json"; inventory.write_text("[]")
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  node.chmod(0o755); bwrap.chmod(0o755)
  def sha(path): return benchmark._sha(path.read_bytes())
  document = {"schema_version": 1, "sdk_version": "1.0.1", "sdk_tree_root": str(tree), "sdk_root": str(package),
    "sdk_inventory_path": str(inventory), "sdk_inventory_sha256": sha(inventory), "cli_path": str(cli), "cli_sha256": sha(cli),
    "package_path": str(manifest), "package_sha256": sha(manifest), "node_path": str(node), "node_sha256": sha(node),
    "bwrap_path": str(bwrap), "bwrap_sha256": sha(bwrap)}
  runtime_doc = tmp_path / "runtime-document.json"; runtime_doc.write_text(json.dumps(document)); runtime_doc.chmod(0o600)
  runtime = benchmark.fixed_runtime(runtime_doc)
  assert runtime["sdk_tree_id"] == "pi-base-test"
  assert runtime["cli_guest_path"] == "/opt/sdk-tree/pi-base-test/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
  document["unexpected"] = True
  runtime_doc.write_text(json.dumps(document)); runtime_doc.chmod(0o600)
  with pytest.raises(ConfigError):
    benchmark.fixed_runtime(runtime_doc)


def test_proc_observer_requires_executable_and_birth_matched_sdk_node(tmp_path):
  proc = tmp_path / "proc"
  proc.mkdir()
  node = tmp_path / "node"
  node.write_bytes(b"fixed node")
  node.chmod(0o755)
  bwrap = tmp_path / "bwrap"
  bwrap.write_bytes(b"fixed bwrap")
  bwrap.chmod(0o755)
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 101, ppid=100, argv=["/opt/node", "/probe/driver.mjs"], exe=node, namespace="ns0", start=11)
  _proc_entry(proc, 102, ppid=101, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  _proc_entry(proc, 103, ppid=102, argv=["/helper"], exe=bwrap, namespace="ns1", start=13)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  sample = observer.identify(100)
  assert sample["status"] == "verified"
  assert sample["target"] == {"pid": 102, "starttime": 12, "pidns_inode": (proc / "ns1").stat().st_ino}
  assert {row["pid"] for row in sample["processes"]} == {102, 103}
  assert sample["descendant_count"] == 1


def test_proc_observer_does_not_accept_process_name_without_cli_argv(tmp_path):
  proc = tmp_path / "proc"
  proc.mkdir()
  node = tmp_path / "node"
  node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"
  bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 101, ppid=100, argv=["/opt/node", "/unrelated.js"], exe=node, namespace="ns0", start=11)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  assert observer.identify(100)["status"] == "missing"


def test_proc_observer_keeps_empty_post_exit_tree_verified(tmp_path):
  import shutil
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  first = observer.identify(100)
  assert first["status"] == "verified"
  shutil.rmtree(proc / "102")
  after_exit = observer.identify(100)
  assert after_exit["status"] == "verified"
  assert after_exit["target_exited"] is True
  assert after_exit["descendant_count"] == 0
  assert after_exit["processes"] == []


def test_proc_observer_accepts_same_owner_zombie_target_without_telemetry_files(tmp_path):
  import shutil
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  assert observer.identify(100)["status"] == "verified"
  target = proc / "102"
  (target / "exe").unlink(); (target / "cmdline").unlink(); shutil.rmtree(target / "fd")
  (target / "status").write_text(f"Uid:\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\n")
  (target / "stat").write_text(_stat_line(102, "worker (test)", 100, state="Z", start=12))
  after_exit = observer.identify(100)
  assert after_exit["status"] == "verified"
  assert after_exit["target_exited"] is True
  assert after_exit["processes"] == []


def test_proc_observer_keeps_target_proc_disappearance_verified_after_anchor(tmp_path):
  import shutil
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  assert observer.identify(100)["status"] == "verified"
  shutil.rmtree(proc / "102")
  after_exit = observer.identify(100)
  assert after_exit["status"] == "verified"
  assert after_exit["target_exited"] is True
  assert after_exit["processes"] == []


def test_proc_observer_keeps_permission_denied_exit_state_unknown(tmp_path, monkeypatch):
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  assert observer.identify(100)["status"] == "verified"
  target_stat = proc / "102" / "stat"
  original = Path.read_text
  def denied(path, *args, **kwargs):
    if path == target_stat: raise PermissionError("synthetic proc denial")
    return original(path, *args, **kwargs)
  monkeypatch.setattr(Path, "read_text", denied)
  result = observer.identify(100)
  assert result["status"] == "unknown"
  assert result["reason"] == "inner_node_exit_unverified"


def test_proc_observer_rechecks_target_when_details_race_with_zombie_exit(tmp_path, monkeypatch):
  import shutil
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  assert observer.identify(100)["status"] == "verified"
  target = proc / "102"
  (target / "exe").unlink(); (target / "cmdline").unlink(); shutil.rmtree(target / "fd")
  (target / "status").write_text(f"Uid:\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\n")
  original = observer._details
  calls = 0
  def race(pid, row):
    nonlocal calls
    if pid == 102:
      calls += 1
      if calls == 2:
        (target / "stat").write_text(_stat_line(102, "worker (test)", 100, state="Z", start=12))
      return None
    return original(pid, row)
  monkeypatch.setattr(observer, "_details", race)
  result = observer.identify(100)
  assert calls == 2
  assert result["status"] == "verified"
  assert result["target_exited"] is True
  assert result["processes"] == []


def test_proc_observer_never_reanchors_to_replacement_node(tmp_path):
  import shutil
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  assert observer.identify(100)["status"] == "verified"
  shutil.rmtree(proc / "102")
  _proc_entry(proc, 104, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=14)
  assert observer.identify(100)["reason"] == "inner_node_birth_changed"


def test_proc_observer_rejects_ambiguous_sdk_nodes(tmp_path):
  proc = tmp_path / "proc"; proc.mkdir()
  node = tmp_path / "node"; node.write_bytes(b"fixed node")
  bwrap = tmp_path / "bwrap"; bwrap.write_bytes(b"fixed bwrap")
  _proc_entry(proc, 100, ppid=1, argv=[str(bwrap), "--unshare-all"], exe=bwrap, namespace="ns0", start=10)
  _proc_entry(proc, 102, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=12)
  _proc_entry(proc, 104, ppid=100, argv=["/opt/node", "/sdk/dist/cli.js", "--mode", "rpc"], exe=node, namespace="ns1", start=14)
  observer = benchmark.ProcObserver(proc, node_path=node, node_guest_path="/opt/node", bwrap_path=bwrap, cli_guest_path="/sdk/dist/cli.js")
  sample = observer.identify(100)
  assert sample["status"] == "unknown"
  assert sample["reason"] == "inner_node_ambiguous"


def test_identity_tracking_rejects_pid_reuse_or_missing_samples():
  target = {"pid": 77, "starttime": 100, "pidns_inode": 200}
  assert benchmark._identity_samples_complete([
    {"identity_status": "missing", "target": None},
    {"identity_status": "verified", "target": target},
    {"identity_status": "verified", "target": target},
  ])
  reused = {"pid": 77, "starttime": 101, "pidns_inode": 200}
  assert not benchmark._identity_samples_complete([
    {"identity_status": "verified", "target": target},
    {"identity_status": "verified", "target": reused},
  ])
  assert not benchmark._identity_samples_complete([
    {"identity_status": "verified", "target": target},
    {"identity_status": "unknown", "target": target},
  ])


def test_process_sample_bound_turns_oversized_tree_into_unknown():
  row = {"pid": 1, "starttime": 1, "pidns_inode": 1, "uid": 1, "rss_bytes": 1, "fd_count": 1,
    "utime": 1, "stime": 1, "exe_device": 1, "exe_inode": 1}
  class Observer:
    def identify(self, _pid):
      return {"status": "verified", "processes": [dict(row) for _ in range(benchmark.MAX_PROCESSES_PER_SAMPLE + 1)],
        "outer": {}, "target": {}, "rss_bytes": 2, "cpu_ticks": 2, "fd_count": 2, "descendant_count": 32}
  sample = benchmark._proc_sample(Observer(), 1, 100, "active")
  assert sample["identity_status"] == "unknown"
  assert sample["identity_reason"] == "process_sample_limit"
  assert sample["processes"] == []
  assert sample["rss_bytes"] is None


def test_driver_result_rejects_extra_fields_wrong_provider_and_calls(monkeypatch):
  expected = {
    "phase": "cold", "index": 0, "cli_exit_code": 0, "cli_signal": None, "stdout_bytes": 20, "stderr_bytes": 0,
    "synthetic_request_count": 1,
    "synthetic_requests": [{"method": "POST", "path": "/v1/chat/completions", "model": "synthetic-main", "stream": True,
      "message_count": 1, "synthetic_auth_present": True}],
    "assistant_sentinel_count": 1, "rpc_tool_event_count": 0, "prompt_latency_ms": [12.5],
  }
  assert benchmark._valid_driver_result(expected, "cold", 0, 1)
  extra = {**expected, "account": "must-not-appear"}
  assert not benchmark._valid_driver_result(extra, "cold", 0, 1)
  wrong = json.loads(json.dumps(expected))
  wrong["synthetic_requests"][0]["model"] = "other"
  assert not benchmark._valid_driver_result(wrong, "cold", 0, 1)
  wrong = json.loads(json.dumps(expected))
  wrong["synthetic_request_count"] = 2
  assert not benchmark._valid_driver_result(wrong, "cold", 0, 1)


def test_run_invocation_uses_fixed_tree_and_network_namespace(monkeypatch, tmp_path):
  plan = _plan(monkeypatch)
  argv = benchmark.build_invocation(plan, Path("/private/work"), "cold", 0, Path("/private/driver.mjs"))
  assert "--unshare-all" in argv
  assert "--ro-bind" in argv
  assert "--bind" in argv
  assert "--setenv" in argv
  assert "--share-net" not in argv
  assert "--clearenv" not in argv
  assert argv[argv.index("PATH") + 1] == "/opt:/usr/bin:/bin"
  assert argv[-4:] == ["--cli", plan["runtime"]["cli_guest_path"], "--work", "/work"]
  tree = plan["runtime"]["sdk_tree_root"]
  assert [tree, "/opt/sdk-tree"] == argv[argv.index(tree):argv.index(tree) + 2]


def test_event_sequence_requires_each_prompt_to_match_one_ordered_synthetic_request():
  schedule = {"idle_seconds_per_run": 60, "post_task_seconds_per_run": 30}
  names = [
    ("spawn_requested", {}), ("spawn_returned", {}), ("cli_ready", {}),
    ("idle_start", {}), ("idle_end", {}), ("prompt_write", {"prompt_index": 0}),
    ("synthetic_request", {"call_index": 1, "model": "synthetic-main"}),
    ("synthetic_response_first", {"call_index": 1}), ("synthetic_response_last", {"call_index": 1}),
    ("agent_end", {"prompt_index": 0}), ("rpc_eof", {}), ("cli_exit", {"exit_code": 0, "signal": None}),
    ("task_end", {}), ("driver_done", {"exit_code": 0, "requests": 1}),
  ]
  times = [1, 2, 3, 4, 64, 65, 66, 67, 68, 69, 70, 71, 72, 102]
  events = [{"name": name, "host_monotonic_ns": timestamp * 1_000_000_000,
    **({"driver_monotonic_ns": str(timestamp * 1_000_000_000)} if name not in ("spawn_requested", "spawn_returned") else {}), **fields}
    for (name, fields), timestamp in zip(names, times)]
  assert benchmark._valid_event_sequence(events, "cold", 1, schedule)
  short_host_post = [dict(row) for row in events]
  short_host_post[-1]["host_monotonic_ns"] = short_host_post[-2]["host_monotonic_ns"] + 1
  assert benchmark._valid_event_sequence(short_host_post, "cold", 1, schedule)
  short_driver_post = [dict(row) for row in events]
  short_driver_post[-1]["driver_monotonic_ns"] = str(int(short_driver_post[-2]["driver_monotonic_ns"]) + 1)
  assert not benchmark._valid_event_sequence(short_driver_post, "cold", 1, schedule)
  short_host_idle = [dict(row) for row in events]
  short_host_idle[4]["host_monotonic_ns"] = short_host_idle[3]["host_monotonic_ns"] + 1
  assert benchmark._valid_event_sequence(short_host_idle, "cold", 1, schedule)
  short_driver_idle = [dict(row) for row in events]
  short_driver_idle[4]["driver_monotonic_ns"] = str(int(short_driver_idle[3]["driver_monotonic_ns"]) + 1)
  assert not benchmark._valid_event_sequence(short_driver_idle, "cold", 1, schedule)
  mismatched = [dict(row) for row in events]
  mismatched[6]["call_index"] = 2
  assert not benchmark._valid_event_sequence(mismatched, "cold", 1, schedule)
  reordered = [dict(row) for row in events]
  reordered[7]["host_monotonic_ns"] = reordered[6]["host_monotonic_ns"] - 1
  assert not benchmark._valid_event_sequence(reordered, "cold", 1, schedule)


def test_metrics_include_host_spawn_to_cli_ready_interval():
  events = [
    {"name": "spawn_requested", "host_monotonic_ns": 1_000_000},
    {"name": "cli_ready", "host_monotonic_ns": 4_000_000},
    {"name": "prompt_write", "host_monotonic_ns": 5_000_000},
    {"name": "agent_end", "host_monotonic_ns": 10_000_000},
  ]
  metrics = benchmark._derive_metrics("cold", events, [], {}, "observed")
  assert metrics["cli_ready_ms"] == 3
  assert metrics["first_response_ms"] == 5


def test_post_window_sample_must_be_verified_and_near_thirty_second_end():
  schedule = {"post_task_seconds_per_run": 30}
  events = [{"name": "task_end", "host_monotonic_ns": 1_000_000_000}]
  samples = [{"phase": "post-task", "identity_status": "verified", "host_monotonic_ns": 30_100_000_000}]
  assert benchmark._post_window_sample_valid(events, samples, 1_000_000_000, schedule)
  samples[0]["host_monotonic_ns"] = 30_500_000_000
  assert not benchmark._post_window_sample_valid(events, samples, 1_000_000_000, schedule)
  samples[0]["host_monotonic_ns"] = 30_000_000_000
  samples[0]["identity_status"] = "unknown"
  assert not benchmark._post_window_sample_valid(events, samples, 1_000_000_000, schedule)


def test_summary_requires_exact_runs_and_keeps_under_20_samples_without_p95(monkeypatch):
  plan = _plan(monkeypatch)
  records = []
  metric_keys = set(benchmark.METRIC_UNITS) - {"same_session_response_ms"}
  for phase, count in (("warmup", 3), ("cold", 10)):
    for index in range(count):
      records.append({"phase": phase, "index": index, "status": "observed", "metrics": {key: 10 for key in metric_keys}})
  records.append({"phase": "same-session", "index": 0, "status": "observed", "metrics": {"same_session_response_ms": [2.0] * 30}})
  baseline = benchmark.summarize_samples(plan, records)
  assert len(baseline["metrics"]["cli_ready_ms"]["samples"]) == 10
  assert len(baseline["metrics"]["cli_ready_ms"]["warmup_samples"]) == 3
  assert len(baseline["metrics"]["same_session_response_ms"]["samples"]) == 30
  failed = json.loads(json.dumps(records))
  failed[0]["status"] = "failed"
  failed[0]["metrics"]["cli_ready_ms"] = 12
  failed[-1]["status"] = "failed"
  failed[-1]["metrics"]["same_session_response_ms"] = [3.0] * 30
  failed_summary = benchmark.summarize_samples(plan, failed)
  assert failed_summary["metrics"]["cli_ready_ms"]["warmup_samples"][0] == {"status": "failed"}
  assert all(row == {"status": "failed"} for row in failed_summary["metrics"]["same_session_response_ms"]["samples"])
  with pytest.raises(ConfigError):
    benchmark.summarize_samples(plan, records[:-1])
  with pytest.raises(ConfigError):
    benchmark.summarize_samples(plan, records[:-1] + [records[-1], records[-1]])


def test_unfinished_or_unknown_call_record_blocks_another_run(tmp_path):
  (tmp_path / "runs").mkdir(mode=0o700)
  unfinished = tmp_path / "runs" / "cold-00"
  unfinished.mkdir(mode=0o700)
  with pytest.raises(ConfigError):
    benchmark._existing_records(tmp_path)
  benchmark._write_new(unfinished / "record.json", json.dumps({"phase": "cold", "index": 0, "status": "failed", "synthetic_request_count": None}).encode())
  with pytest.raises(ConfigError):
    benchmark._existing_records(tmp_path)


@pytest.mark.parametrize("fault", [None, "running", "wrong-child", "unanchored", "known-unreadable", "birth-changed"])
def test_owned_outer_wait_only_completes_known_birth_exit_observation(fault):
  from types import SimpleNamespace
  outer = {"pid": 91, "starttime": 100, "pidns_inode": 200}
  target = {"pid": 92, "starttime": 101, "pidns_inode": 201}
  known = [{"status": "missing", "identity": (92, 101, 201)}]
  reason = "outer_birth_changed" if fault == "birth-changed" else "outer_unreadable"
  observer = SimpleNamespace(identify=lambda _: {"status": "unknown", "reason": reason},
    _target_exit_seen=lambda: False,
    outer_identity=None if fault == "unanchored" else outer, target_identity=target,
    known_alive=lambda: [{"status": "unknown"}] if fault == "known-unreadable" else known)
  child = SimpleNamespace(pid=93 if fault == "wrong-child" else 91, poll=lambda: None if fault == "running" else 0)
  row = benchmark._proc_sample(observer, 91, 1, "post-task", owned_process=child)
  assert row["identity_status"] == ("verified" if fault is None else "unknown")
  if fault is None:
    assert row["outer_wait_exit_code"] == 0
    assert row["target"] == target and row["outer"] == outer
    assert row["descendant_count"] == row["rss_bytes"] == row["fd_count"] == 0


def test_owned_outer_wait_does_not_hide_a_still_live_known_descendant():
  from types import SimpleNamespace
  outer = {"pid": 91, "starttime": 100, "pidns_inode": 200}
  target = {"pid": 92, "starttime": 101, "pidns_inode": 201}
  live = {"pid": 93, "starttime": 102, "ppid": 92, "nspid": [93], "pidns_inode": 201, "uid": os.geteuid(), "rss_bytes": 8192,
    "fd_count": 4, "utime": 3, "stime": 2, "exe_device": 1, "exe_inode": 8}
  observer = SimpleNamespace(identify=lambda _: {"status": "unknown", "reason": "outer_missing"},
    _target_exit_seen=lambda: False,
    outer_identity=outer, target_identity=target, known_alive=lambda: [
      {"status": "missing", "identity": (92, 101, 201)}, {"status": "verified", "identity": (93, 102, 201), "process": live}])
  row = benchmark._proc_sample(observer, 91, 1, "post-task", owned_process=SimpleNamespace(pid=91, poll=lambda: 0))
  assert row["identity_status"] == "verified" and row["descendant_count"] == 1
  assert row["rss_bytes"] == 8192 and row["cpu_ticks"] == 5 and row["fd_count"] == 4


@pytest.mark.parametrize("flags,expected", [(0, False), (1, True), (16, True), (8, False), (32, False), (9, False)])
def test_original_target_pidfd_only_accepts_exit_readiness_not_invalid_fd(monkeypatch, flags, expected):
  from types import SimpleNamespace
  observer = object.__new__(benchmark.ProcObserver)
  observer.target_identity = {"pid": 19, "starttime": 20, "pidns_inode": 21}
  observer.pidfd_identity = dict(observer.target_identity); observer.target_pidfd = 10
  monkeypatch.setattr(benchmark.select, "poll", lambda: SimpleNamespace(register=lambda *_: None,
    poll=lambda _: [] if flags == 0 else [(10, flags)]))
  assert observer._target_exit_seen() is expected
  observer.pidfd_identity = {**observer.target_identity, "starttime": 22}
  assert not observer._target_exit_seen()


def test_pidfd_pin_rechecks_birth_and_closes_drifted_descriptor(monkeypatch):
  from types import SimpleNamespace
  observer = object.__new__(benchmark.ProcObserver)
  observer.proc_root = Path("/proc"); observer.target_pidfd = None; observer.pidfd_identity = None
  observer.node_identity = (1, 2)
  target = {"pid": 19, "ppid": 18, "starttime": 20, "pidns_inode": 21, "uid": os.geteuid(), "exe_device": 1, "exe_inode": 2}
  rows = iter([target, {**target, "starttime": 22}]); observer._details = lambda *_: next(rows)
  opened = []; closed = []
  monkeypatch.setattr(os, "pidfd_open", lambda pid, flags: opened.append((pid, flags)) or 10)
  monkeypatch.setattr(os, "set_inheritable", lambda fd, value: None)
  monkeypatch.setattr(os, "close", closed.append)
  observer._pin_target(target)
  assert opened == [(19, 0)] and closed == [10] and observer.target_pidfd is None
  observer._details = lambda *_: target
  observer._pin_target(target)
  assert observer.target_pidfd == 10 and observer.pidfd_identity == benchmark.birth_tuple(target)
  observer.close(); observer.close()
  assert closed == [10, 10]


def test_pidfd_exit_between_two_polls_only_completes_original_target(tmp_path, monkeypatch):
  observer = object.__new__(benchmark.ProcObserver)
  target = {"pid": 19, "starttime": 20, "pidns_inode": 21}
  observer.target_identity = target; observer.proc_root = tmp_path
  observer.known = {(19, 20, 21): {**target}, (22, 23, 24): {"pid": 22, "starttime": 23, "pidns_inode": 24}}
  calls = iter([False, True]); observer._target_exit_seen = lambda _timeout=0: next(calls)
  monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError()))
  rows = observer.known_alive()
  assert rows[0] == {"status": "missing", "identity": (19, 20, 21), "exit_fact": "original-pidfd-readable"}
  assert rows[1]["status"] == "unknown"


def test_exit_observation_wait_is_bounded_and_timeout_remains_unknown(monkeypatch):
  from types import SimpleNamespace
  observer = object.__new__(benchmark.ProcObserver)
  observer.target_identity = {"pid": 19, "starttime": 20, "pidns_inode": 21}
  observer.pidfd_identity = dict(observer.target_identity); observer.target_pidfd = 10
  waits = []
  monkeypatch.setattr(benchmark.select, "poll", lambda: SimpleNamespace(register=lambda *_: None,
    poll=lambda ms: waits.append(ms) or []))
  assert not observer._target_exit_seen(100)
  assert waits == [100]
  for value in (-1, 101, True, "100"):
    assert not observer._target_exit_seen(value)
  assert waits == [100]
