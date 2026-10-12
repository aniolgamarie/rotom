"""挂载编译与实际交接共享同一FD作用域；不启动helper。"""

import os
from pathlib import Path

import pytest

from agentcfg.pi_shell_mounts import compile_mount_plan, pin_mount_plan
from agentcfg.schema import ConfigError
from test_pi_shell_mounts import baseline, public
from test_pi_shell_preparation import shell_case


def test_mount_fds_remain_open_through_handoff_and_close_afterward(shell_case, tmp_path):
  system = tmp_path / "system"; system.mkdir()
  value = public(shell_case)
  kwargs = {"system_roots": (str(system),), "mountinfo": baseline(shell_case)}
  expected = compile_mount_plan(value, **kwargs)
  with pin_mount_plan(value, **kwargs) as pinned:
    assert pinned["plan"] == expected
    descriptors = pinned["source_fds"]
    assert set(descriptors) == {row["path"] for row in expected["mounts"]}
    assert len(set(descriptors.values())) == len(descriptors)
    for path, fd in descriptors.items():
      actual, original = os.fstat(fd), Path(path).stat()
      assert (actual.st_dev, actual.st_ino) == (original.st_dev, original.st_ino)
      assert not os.get_inheritable(fd)
  for fd in descriptors.values():
    with pytest.raises(OSError): os.fstat(fd)
  assert "source_fds" not in expected


def test_handoff_retains_original_directory_after_rename(shell_case):
  project = Path(shell_case["cwd"])
  expected = project.stat()
  with pin_mount_plan(public(shell_case), system_roots=(), mountinfo=baseline(shell_case)) as pinned:
    fd = pinned["source_fds"][str(project)]
    project.rename(project.with_name("moved-project")); project.mkdir()
    assert os.fstat(fd).st_ino == expected.st_ino
    assert project.stat().st_ino != expected.st_ino


def test_consumer_exception_is_preserved_and_owned_fds_close(shell_case):
  failure = RuntimeError("synthetic consumer failure")
  with pytest.raises(RuntimeError) as caught:
    with pin_mount_plan(public(shell_case), system_roots=(), mountinfo=baseline(shell_case)) as pinned:
      fds = list(pinned["source_fds"].values())
      raise failure
  assert caught.value is failure
  for fd in fds:
    with pytest.raises(OSError): os.fstat(fd)


def test_failed_setup_closes_all_previously_opened_fds(shell_case, tmp_path, monkeypatch):
  system = tmp_path / "system"; system.mkdir()
  value = public(shell_case)
  duplicated = []
  original = os.dup
  def tracking(fd):
    result = original(fd)
    duplicated.append(result)
    return result
  monkeypatch.setattr(os, "dup", tracking)
  with pytest.raises(ConfigError):
    with pin_mount_plan(value, system_roots=(str(system), str(tmp_path / "missing")), mountinfo=baseline(shell_case)):
      pytest.fail("invalid system source handed off")
  assert duplicated
  for fd in duplicated:
    with pytest.raises(OSError): os.fstat(fd)


def test_closed_system_fd_cleanup_does_not_close_a_reused_fd(shell_case, tmp_path):
  system = tmp_path / "system"; system.mkdir()
  replacement = tmp_path / "replacement"; replacement.write_bytes(b"synthetic")
  foreign = None
  try:
    with pin_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=baseline(shell_case)) as pinned:
      fd = pinned["source_fds"][str(system)]
      os.close(fd)
      foreign = os.open(replacement, os.O_RDONLY | os.O_CLOEXEC)
      if foreign != fd:
        os.dup2(foreign, fd, inheritable=False)
        os.close(foreign)
        foreign = fd
    assert os.read(foreign, 9) == b"synthetic"
  finally:
    if foreign is not None: os.close(foreign)
