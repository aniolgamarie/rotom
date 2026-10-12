"""父侧UID映射与准备的默认测试；仅临时文件、合成proc事实和替身。"""

from contextlib import contextmanager
import os
import shlex
from types import SimpleNamespace

import pytest

from agentcfg import pi_shell_probe_binding as binding
from agentcfg import pi_shell_identity as identity
from agentcfg.schema import ConfigError


@pytest.mark.parametrize("raw", ["", "0 0 0\n", "-1 0 1\n", "0 0 4294967296\n", "4294967295 0 1\n",
  "0 4294967295 1\n", "0 0 1\n0 2 1\n", "0 0 1\n2 0 1\n", "0 0 1 extra\n", "零 0 1\n", "0 0 1\n\n", "0 0 1\n" * 341])
def test_invalid_or_ambiguous_map_refuses(raw):
  with pytest.raises(ConfigError): binding.parse_uid_map(raw)


def test_map_projection_uses_outside_column_in_parent_coordinates():
  rows = binding.parse_uid_map(" 1002 1002 1\n 2000 3000 10\n")
  assert [binding.project_uid(uid, rows, 60000) for uid in (0, 1002, 2999, 3000, 3009, 3010)] == [60000, 1002, 60000, 2000, 2009, 60000]
  assert binding.project_uid(0, binding.parse_uid_map("0 0 4294967295\n"), 60000) == 0


@pytest.fixture
def mapping(monkeypatch):
  monkeypatch.setattr(binding, "os", SimpleNamespace(**vars(os)))
  monkeypatch.setattr(binding.os, "geteuid", lambda: 1002)
  monkeypatch.setattr(identity, "os", binding.os)
  state = SimpleNamespace(map="1002 1002 1\n", overflow="65534\n", fault=None, observations=0, links=0, reads=[])
  def observe(leader):
    state.observations += 1
    return "unknown" if state.fault == "birth" and state.observations == 2 else "alive"
  def link(path):
    state.links += 1
    if path == "/proc/self/ns/user": return "user:[10]" if not (state.fault == "reader" and state.links > 2) else "user:[99]"
    assert path == "/proc/123/ns/user"
    return "user:[20]" if not (state.fault == "worker" and state.links > 2) else "user:[99]"
  def read(path, limit):
    state.reads.append((path, limit))
    if path == "/proc/sys/kernel/overflowuid": return state.overflow
    assert path == "/proc/123/uid_map" and limit == 16384
    return state.map if not (state.fault == "map" and len(state.reads) > 2) else "1002 0 1\n"
  monkeypatch.setattr(binding.os, "readlink", link)
  monkeypatch.setattr(identity, "_read", read)
  state.args = {"processes": SimpleNamespace(observe=observe), "leader": {"pid": 123, "uid": 1002},
    "bootstrap": {"user_namespace": "user:[20]", "uid": 1002, "uid_map": "1002 0 1\n",
      "owners": {"root": 1002, "usr": 65534, "bash": 65534}},
    "nonce": "a" * 32, "helper_identity": "b" * 64, "plan_digest": "c" * 64}
  state.execution = SimpleNamespace(snapshots=((4, (1, 2, 0, 0, 1, 10, 3, 4)), (5, (1, 3, 1002, 0, 1, 10, 3, 4))))
  return state


def test_binding_ignores_worker_self_reader_outside_column_and_uses_parent_map(mapping):
  value, evidence = binding.bind_worker(mapping.execution, **mapping.args)
  assert value["uid_projection"] == [{"host_uid": 0, "visible_uid": 65534}, {"host_uid": 1002, "visible_uid": 1002}]
  assert value["worker_identity"] == mapping.args["leader"] and value["plan_digest"] == "c" * 64
  assert evidence["parent_read_uid_map"] == "1002 1002 1\n" and evidence["reader_user_namespace"] == "user:[10]"
  assert mapping.observations == 2 and len(mapping.reads) == 3


@pytest.mark.parametrize("fault", ["birth", "reader", "worker", "map", "bootstrap-ns", "uid", "root", "usr", "bash", "overflow", "overflow-negative"])
def test_unstable_or_mismatched_projection_never_grants(mapping, fault):
  mapping.fault = fault
  if fault == "bootstrap-ns": mapping.args["bootstrap"]["user_namespace"] = "user:[99]"
  if fault == "uid": mapping.args["bootstrap"]["uid"] = 0
  if fault in ("root", "usr", "bash"): mapping.args["bootstrap"]["owners"][fault] = 42
  if fault == "overflow": mapping.overflow = "4294967295\n"
  if fault == "overflow-negative": mapping.overflow = "-1\n"
  with pytest.raises(ConfigError): binding.bind_worker(mapping.execution, **mapping.args)


def test_configured_kernel_overflow_is_used_not_hardcoded(mapping):
  mapping.overflow = "60000\n"
  mapping.args["bootstrap"]["owners"].update(usr=60000, bash=60000)
  value, _ = binding.bind_worker(mapping.execution, **mapping.args)
  assert value["uid_projection"][0]["visible_uid"] == 60000


@pytest.mark.parametrize("body", [b"", b"x" * 33, b"\xff"])
def test_proc_read_is_bounded_ascii_and_nonempty(tmp_path, body):
  path = tmp_path / "synthetic-proc"; path.write_bytes(body)
  with pytest.raises((ConfigError, UnicodeError)): binding._read(path, 32)


def test_proc_read_rejects_symlink_and_returns_exact_bytes(tmp_path):
  path = tmp_path / "synthetic-proc"; path.write_bytes(b"1002 1002 1\n")
  assert binding._read(path, 32) == "1002 1002 1\n"
  link = tmp_path / "link"; link.symlink_to(path)
  with pytest.raises(OSError): binding._read(link, 32)


@pytest.mark.parametrize("case", ["boundary", "descendants"])
def test_parent_policy_uses_real_preparer_temp_paths_and_quotes_script(tmp_path, monkeypatch, case):
  real_prepare = binding.prepare_shell
  directory = tmp_path / "bundle ' space"
  root = directory / "cases" / case / "work"
  for path in (root / "project/private", root / "readonly", root / "home", root / "outside", directory / "inputs", directory / "deps"):
    path.mkdir(parents=True)
  executable = directory / "synthetic-bash"; executable.write_bytes(b"synthetic never execute"); executable.chmod(0o700)
  def prepare(**kwargs):
    kwargs["binding"]["executable"] = str(executable)
    return real_prepare(**kwargs)
  monkeypatch.setattr(binding, "prepare_shell", prepare)
  plan = {"nonces": {case: "a" * 32}, "system": {"dependencies": {"path": str(directory / "deps")}}}
  part = binding.preparation(directory, plan, case)
  command = part["private_input"]["command"]
  lines = command.splitlines()
  payload = shlex.split(lines[1] if case == "descendants" else lines[0])
  assert payload == ["/usr/bin/python3.11", "-I", "-B", "-S", str(root / "readonly/payload.py"), "--payload", "a" * 32]
  if case == "descendants": assert shlex.split(lines[0])[-3:] == [str(root / "readonly/heartbeat.py"), "a" * 32, "&"] and lines[-1] == "wait"
  assert part["physical"]["readonly_paths"] == [str(root / "readonly")]
  assert str(root / "project/private") in part["physical"]["denied_paths"]
  assert [row["path"] for row in part["resolution"]["write_roots"]] == [str(root / "project")]
