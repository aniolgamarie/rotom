"""真实本进程FD的Shell源身份检查；不执行任何mount/helper/Shell。"""

from copy import deepcopy
import errno
import os
from pathlib import Path

import pytest

from agentcfg.pi_shell_preparation import prepare_shell
from agentcfg.pi_shell_sources import pin_shell_sources
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_shell_preparation import shell_case


def public(case):
  value = prepare_shell(**case)
  return {key: value[key] for key in ("resolution", "physical")}


def closed(fd):
  with pytest.raises(OSError) as caught: os.fstat(fd)
  assert caught.value.errno == errno.EBADF


def test_root_cwd_and_executable_descriptors_are_owned_and_cloexec(shell_case):
  value = public(shell_case)
  with pin_shell_sources(value) as sources:
    root, = sources["roots"]
    assert root["path"] == shell_case["cwd"] and root["writable"] is True
    assert os.fstat(root["fd"]).st_ino == Path(shell_case["cwd"]).stat().st_ino
    assert os.fstat(sources["cwd_fd"]).st_ino == Path(shell_case["cwd"]).stat().st_ino
    assert os.read(sources["executable_fd"], 1000) == Path(shell_case["binding"]["executable"]).read_bytes()
    fds = [root["fd"], sources["cwd_fd"], sources["executable_fd"]]
    assert all(not os.get_inheritable(fd) for fd in fds)
  for fd in fds: closed(fd)


def test_replacement_after_pinning_does_not_retarget_descriptor(shell_case):
  value = public(shell_case)
  project = Path(shell_case["cwd"])
  (project / "marker").write_text("approved")
  with pin_shell_sources(value) as sources:
    project.rename(project.with_name("moved")); project.mkdir()
    (project / "marker").write_text("replacement")
    fd = os.open("marker", os.O_RDONLY, dir_fd=sources["roots"][0]["fd"])
    try: assert os.read(fd, 100) == b"approved"
    finally: os.close(fd)


@pytest.mark.parametrize("change", ["root", "cwd", "executable", "contents", "symlink", "hardlink"])
def test_stale_or_aliased_sources_are_rejected_before_handoff(shell_case, change):
  project = Path(shell_case["cwd"])
  child = project / "build"; child.mkdir()
  shell_case["cwd"] = str(child)
  value = public(shell_case)
  executable = Path(shell_case["binding"]["executable"])
  if change == "contents": executable.write_bytes(b"changed in same inode")
  elif change == "hardlink": os.link(executable, executable.with_name("alias"))
  else:
    target = project if change == "root" else child if change == "cwd" else executable
    moved = target.with_name(target.name + "-moved"); target.rename(moved)
    if change == "symlink": target.symlink_to(moved)
    elif change in ("root", "cwd"): target.mkdir()
    else: target.write_bytes(moved.read_bytes()); target.chmod(0o700)
  with pytest.raises((ConfigError, Conflict)):
    with pin_shell_sources(value): pytest.fail("stale source handed off")


@pytest.mark.parametrize("change", ["unknown", "unknown-policy", "cwd-identity", "physical-roots", "physical-executable", "duplicate-root", "root-identity", "body"])
def test_closed_public_projection_rejects_mutation(shell_case, change):
  value = public(shell_case)
  if change == "unknown": value["extra"] = True
  elif change == "unknown-policy": value["resolution"]["policy"]["extra"] = True
  elif change == "body": value["private_input"] = {"command": "secret"}
  elif change == "cwd-identity": value["physical"]["cwd_identity"] = "0" * 64
  elif change == "physical-roots": value["physical"]["write_roots"] = []
  elif change == "physical-executable": value["physical"]["executable_identity"]["sha256"] = "0" * 64
  elif change == "duplicate-root": value["resolution"]["read_roots"] *= 2
  else: value["resolution"]["read_roots"][0]["identity"] = "0" * 64
  with pytest.raises((ConfigError, Conflict)):
    with pin_shell_sources(value): pytest.fail("mutated projection handed off")


def test_readonly_root_and_input_copy_are_preserved(shell_case):
  shell_case["binding"]["write_roots"] = []
  value = public(shell_case); original = deepcopy(value)
  with pin_shell_sources(value) as sources:
    assert sources["roots"][0]["writable"] is False
  assert value == original


def test_setup_failure_closes_all_opened_sources(shell_case, monkeypatch):
  import agentcfg.pi_shell_sources as module
  value = public(shell_case)
  opened = []
  original = module._directory
  def directory(*args):
    fd = original(*args)
    opened.append(fd)
    return fd
  monkeypatch.setattr(module, "_directory", directory)
  value["physical"]["cwd_identity"] = "0" * 64
  with pytest.raises(Conflict):
    with pin_shell_sources(value): pytest.fail("failed setup handed off")
  assert opened
  for fd in opened: closed(fd)


def test_body_exception_closes_all_owned_sources(shell_case):
  error = RuntimeError("synthetic consumer failure")
  with pytest.raises(RuntimeError) as caught:
    with pin_shell_sources(public(shell_case)) as sources:
      fds = [row["fd"] for row in sources["roots"]] + [sources["cwd_fd"], sources["executable_fd"]]
      raise error
  assert caught.value is error
  for fd in fds: closed(fd)
