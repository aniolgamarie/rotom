"""真实 FD/合成 ELF 的准备证据；exec 替身仅关闭测试自有 FD，不启动进程。"""

from dataclasses import FrozenInstanceError
import errno
import fcntl
import hashlib
import os
import stat

import pytest

from agentcfg.activity import digest
import agentcfg.pi_shell_execution as module
from agentcfg.pi_shell_mounts import compile_mount_plan
from agentcfg.pi_shell_preparation import prepare_shell
from agentcfg.pi_shell_script import sealed_data
from agentcfg.schema import ConfigError
from test_pi_assets import executable
from test_pi_shell_mounts import baseline
from test_pi_shell_preparation import shell_case


@pytest.fixture
def execution_case(shell_case, tmp_path):
  project = tmp_path / "project"
  hidden = project / "hidden"; hidden.write_bytes(b"synthetic hidden data")
  value = prepare_shell(**shell_case)
  public = {key: value[key] for key in ("resolution", "physical")}
  public["physical"]["denied_paths"] = [str(hidden)]
  helper = tmp_path / "synthetic-bwrap"
  body = executable() + b"synthetic binary body, never execute"
  helper.write_bytes(body); helper.chmod(0o700)
  info = baseline(shell_case)
  plan = compile_mount_plan(public, system_roots=(), mountinfo=info)
  return {"public": public, "command": shell_case["command"], "helper_path": str(helper),
    "helper_identity": hashlib.sha256(body).hexdigest(), "plan_digest": digest(plan),
    "system_roots": (), "mountinfo": info}


def assert_closed(fd):
  with pytest.raises(OSError) as caught: os.fstat(fd)
  assert caught.value.errno == errno.EBADF


def exec_seams(monkeypatch, *, inventory):
  monkeypatch.setattr(module.os, "getpid", lambda: 1)
  monkeypatch.setattr(module, "_task_ids", lambda: ("1",))
  monkeypatch.setattr(module, "_fd_inventory", inventory)
  monkeypatch.setattr(module, "_FD_EXEC_SUPPORTED", True)


def test_preparation_holds_unique_cloexec_sealed_fds_and_cleans_all(execution_case):
  before_cwd, before_env = os.getcwd(), dict(os.environ)
  with module.prepare_shell_execution(**execution_case) as value:
    assert "private shell marker" not in repr(value) and "synthetic-bwrap" not in repr(value)
    descriptors = (value.helper_fd, *value.pass_fds)
    assert len(set(descriptors)) == len(descriptors)
    assert all(os.get_inheritable(fd) is False for fd in descriptors)
    assert value.argv[0] == execution_case["helper_path"]
    assert value.argv[-5:] == ("--", execution_case["public"]["physical"]["executable_identity"]["path"],
      "--noprofile", "--norc", "/.rotom-shell/script")
    assert os.pread(value.script_fd, 65537, 0) == execution_case["command"].encode()
    assert os.fstat(value.seccomp_fd).st_size > 0
    assert len(value.mask_fds) == 1
    assert os.fstat(value.mask_fds[0]).st_size == 0
    for fd in (value.script_fd, value.seccomp_fd, *value.mask_fds):
      assert fcntl.fcntl(fd, fcntl.F_GET_SEALS) & 0xF == 0xF
      assert os.lseek(fd, 0, os.SEEK_CUR) == 0
    with pytest.raises(FrozenInstanceError): value.argv = ()
    assert os.getcwd() == before_cwd and dict(os.environ) == before_env
  for fd in descriptors: assert_closed(fd)
  assert os.getcwd() == before_cwd and dict(os.environ) == before_env


@pytest.mark.parametrize("mutation", ["helper-hash", "plan", "mode", "platform", "script-helper", "symlink", "hardlink", "relative", "bad-digest"])
def test_drift_or_invalid_helper_is_rejected(execution_case, tmp_path, mutation):
  helper = execution_case["helper_path"]
  if mutation == "helper-hash": execution_case["helper_identity"] = "0" * 64
  elif mutation == "plan": execution_case["plan_digest"] = "0" * 64
  elif mutation == "mode": os.chmod(helper, 0o755)
  elif mutation in ("platform", "script-helper"):
    body = executable("linux-aarch64") if mutation == "platform" else b"#!/bin/sh\nprivate helper text\n"
    with open(helper, "wb") as stream: stream.write(body)
    execution_case["helper_identity"] = hashlib.sha256(body).hexdigest()
  elif mutation == "symlink":
    alias = tmp_path / "alias"; alias.symlink_to(helper)
    execution_case["helper_path"] = str(alias)
  elif mutation == "hardlink": os.link(helper, tmp_path / "alias")
  elif mutation == "relative": execution_case["helper_path"] = "relative"
  else: execution_case["plan_digest"] = "invalid"
  with pytest.raises(ConfigError):
    with module.prepare_shell_execution(**execution_case): pytest.fail("invalid preparation yielded")


def test_body_exception_is_preserved_and_all_prepared_fds_closed(execution_case):
  error = RuntimeError("synthetic caller failure")
  with pytest.raises(RuntimeError) as caught:
    with module.prepare_shell_execution(**execution_case) as value:
      descriptors = (value.helper_fd, *value.pass_fds)
      raise error
  assert caught.value is error
  for fd in descriptors: assert_closed(fd)


def test_closed_and_reused_helper_fd_is_not_closed_at_scope_exit(execution_case):
  with sealed_data(b"foreign") as foreign:
    with module.prepare_shell_execution(**execution_case) as value:
      reused = value.helper_fd
      os.close(reused); os.dup2(foreign, reused, inheritable=False)
    assert os.fstat(reused).st_ino == os.fstat(foreign).st_ino
    os.close(reused)


def test_mock_exec_inherits_only_whitelist_closes_rogues_and_uses_empty_env(execution_case, monkeypatch, tmp_path):
  rogue_directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  rogue_file = os.memfd_create("synthetic-rogue", os.MFD_CLOEXEC)
  calls = []
  try:
    with module.prepare_shell_execution(**execution_case) as value:
      def inventory():
        remaining = []
        for fd in (value.helper_fd, *value.pass_fds, rogue_directory, rogue_file):
          try: os.fstat(fd)
          except OSError: continue
          remaining.append(fd)
        return remaining
      exec_seams(monkeypatch, inventory=inventory)
      def fake_exec(fd, argv, env):
        calls.append((fd, argv, env))
        assert fd == value.helper_fd and env == {}
        assert os.get_inheritable(fd) is False
        assert all(os.get_inheritable(source) is True for source in value.pass_fds)
        assert_closed(rogue_directory); assert_closed(rogue_file)
        raise OSError(errno.ENOEXEC, "synthetic private exec failure")
      monkeypatch.setattr(module, "_exec_fd", fake_exec)
      with pytest.raises(ConfigError, match="pi-shell-exec-unavailable"): module.exec_prepared(value)
      with pytest.raises(ConfigError): module.exec_prepared(value)
      assert len(calls) == 1
  finally:
    for fd in (rogue_directory, rogue_file):
      try: os.close(fd)
      except OSError as error:
        assert error.errno == errno.EBADF


@pytest.mark.parametrize("failure", ["pid", "threads", "platform", "fd-exec", "offset", "filter-offset", "mask-offset",
  "seals", "helper-drift", "helper-inherit", "reused-fd", "stdio-directory", "stdio-socket", "stdio-closed"])
def test_exec_preconditions_fail_without_attempting_exec(execution_case, monkeypatch, failure, tmp_path):
  calls = []
  with module.prepare_shell_execution(**execution_case) as value:
    exec_seams(monkeypatch, inventory=lambda: (value.helper_fd, *value.pass_fds))
    monkeypatch.setattr(module, "_exec_fd", lambda *args: calls.append(args))
    if failure == "pid": monkeypatch.setattr(module.os, "getpid", lambda: 99)
    elif failure == "threads": monkeypatch.setattr(module, "_task_ids", lambda: ("1", "2"))
    elif failure == "platform": monkeypatch.setattr(module.sys, "platform", "darwin")
    elif failure == "fd-exec": monkeypatch.setattr(module, "_FD_EXEC_SUPPORTED", False)
    elif failure == "offset": os.lseek(value.script_fd, 1, os.SEEK_SET)
    elif failure == "filter-offset": os.lseek(value.seccomp_fd, 1, os.SEEK_SET)
    elif failure == "mask-offset": os.lseek(value.mask_fds[0], 1, os.SEEK_SET)
    elif failure == "seals":
      original = fcntl.fcntl
      def unsealed(fd, operation, *args):
        if fd == value.seccomp_fd and operation == fcntl.F_GET_SEALS: return 0
        return original(fd, operation, *args)
      monkeypatch.setattr(module.fcntl, "fcntl", unsealed)
    elif failure == "helper-drift":
      with open(execution_case["helper_path"], "ab") as stream: stream.write(b"changed")
    elif failure == "helper-inherit": os.set_inheritable(value.helper_fd, True)
    elif failure == "reused-fd":
      with sealed_data(b"foreign") as foreign:
        os.close(value.script_fd); os.dup2(foreign, value.script_fd, inheritable=False)
      # 复用的 FD 不属于准备对象，由本测试清理。
    else:
      original = os.fstat
      def changed(fd):
        if fd == 0:
          if failure == "stdio-closed": raise OSError(errno.EBADF, "synthetic closed stdin")
          mode = stat.S_IFDIR if failure == "stdio-directory" else stat.S_IFSOCK
          return os.stat_result((mode | 0o600, 1, 1, 1, 0, 0, 0, 0, 0, 0))
        return original(fd)
      monkeypatch.setattr(module.os, "fstat", changed)
    with pytest.raises(ConfigError): module.exec_prepared(value)
    assert calls == []
    if failure == "reused-fd": os.close(value.script_fd)


def test_fake_exec_return_is_failure_and_scope_expiry_is_rejected(execution_case, monkeypatch):
  calls = []
  with module.prepare_shell_execution(**execution_case) as value:
    exec_seams(monkeypatch, inventory=lambda: (value.helper_fd, *value.pass_fds))
    monkeypatch.setattr(module, "_exec_fd", lambda *args: calls.append(args))
    with pytest.raises(ConfigError): module.exec_prepared(value)
    assert len(calls) == 1
  with pytest.raises(ConfigError): module.exec_prepared(value)
  with pytest.raises(ConfigError): module.exec_prepared({"argv": ()})


def open_fds():
  result = set()
  for fd in module._fd_inventory():
    try: os.fstat(fd)
    except OSError as error:
      assert error.errno == errno.EBADF
      continue
    result.add(fd)
  return result


@pytest.mark.parametrize("when", ["script-input", "filter-create", "mask-create"])
def test_failed_preparation_leaves_no_owned_fd_open(execution_case, monkeypatch, when):
  before = open_fds()
  original = os.memfd_create
  created = []
  def create(name, flags):
    if len(created) == (1 if when == "filter-create" else 2):
      raise OSError(errno.EMFILE, "synthetic private setup failure")
    fd = original(name, flags)
    created.append(fd)
    return fd
  if when == "script-input": execution_case["command"] = "invalid\0script"
  else: monkeypatch.setattr(os, "memfd_create", create)
  with pytest.raises(ConfigError):
    with module.prepare_shell_execution(**execution_case): pytest.fail("failed setup yielded")
  assert open_fds() == before
  assert module._ACTIVE == {}


def test_close_failure_stops_before_exec_and_scope_registry_is_removed(execution_case, monkeypatch):
  original = os.close
  rogue = os.memfd_create("synthetic-rogue", os.MFD_CLOEXEC)
  calls = []
  try:
    with module.prepare_shell_execution(**execution_case) as value:
      exec_seams(monkeypatch, inventory=lambda: (value.helper_fd, *value.pass_fds, rogue))
      def failed_close(fd):
        if fd == rogue: raise OSError(errno.EIO, "synthetic close failure")
        return original(fd)
      monkeypatch.setattr(module.os, "close", failed_close)
      monkeypatch.setattr(module, "_exec_fd", lambda *args: calls.append(args))
      with pytest.raises(ConfigError): module.exec_prepared(value)
      assert calls == []
    assert module._ACTIVE == {}
  finally: original(rogue)


def test_transient_closed_inventory_fd_is_ignored_only_as_ebadf(execution_case, monkeypatch):
  calls = []
  with module.prepare_shell_execution(**execution_case) as value:
    transient = os.memfd_create("synthetic-transient", os.MFD_CLOEXEC)
    os.close(transient)
    exec_seams(monkeypatch, inventory=lambda: (value.helper_fd, *value.pass_fds, transient))
    monkeypatch.setattr(module, "_exec_fd", lambda *args: calls.append(args))
    with pytest.raises(ConfigError): module.exec_prepared(value)
    assert len(calls) == 1
