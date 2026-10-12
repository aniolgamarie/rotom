"""合成overflow UID的当前失败关闭证据；不创建user/PID namespace或执行helper。

这里不证明bubblewrap实际映射方式；映射发生与否须由独立原生证据决定。
"""

import hashlib
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from agentcfg import paths, pi_shell_preparation, pi_shell_sources, pi_pid_namespace
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_shell_preparation import shell_case
from test_pi_pid_namespace import modern_host


OVERFLOW = 65534


def changed(info, **fields):
  result = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
  result.update(fields)
  return SimpleNamespace(**result)


@pytest.mark.parametrize("owner", [0, 1002, OVERFLOW])
def test_ancestor_allowlist_refuses_overflow_even_without_write_bits(tmp_path, monkeypatch, owner):
  fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  try:
    observed = changed(os.fstat(fd), st_uid=owner, st_mode=stat.S_IFDIR | 0o755)
    proxy = SimpleNamespace(**vars(os)); proxy.geteuid = lambda: 1002; proxy.fstat = lambda _: observed
    monkeypatch.setattr(paths, "os", proxy)
    if owner == OVERFLOW:
      with pytest.raises(paths.PathError, match="路径祖先不属于可信用户"): paths._check_ancestor(fd)
    else: paths._check_ancestor(fd)
  finally: os.close(fd)


@pytest.mark.parametrize("failed_path", ["/", "/usr"])
def test_absolute_directory_stops_at_first_unmapped_ancestor(monkeypatch, failed_path):
  opened = []; original_open, original_fstat = os.open, os.fstat
  proxy = SimpleNamespace(**vars(os)); proxy.geteuid = lambda: 1002
  def opened_fd(*args, **kwargs):
    fd = original_open(*args, **kwargs); opened.append((fd, os.readlink("/proc/self/fd/" + str(fd)))); return fd
  def observed(fd):
    path = os.readlink("/proc/self/fd/" + str(fd)); info = original_fstat(fd)
    return changed(info, st_uid=OVERFLOW if path == failed_path else 0)
  proxy.open = opened_fd; proxy.fstat = observed
  monkeypatch.setattr(paths, "os", proxy)
  with pytest.raises(paths.PathError, match="路径祖先不属于可信用户"):
    with paths._absolute_directory(Path("/usr/bin")): pytest.fail("overflow ancestor must close")
  assert [path for _, path in opened] == (["/"] if failed_path == "/" else ["/", "/usr"])
  for fd, _ in opened:
    with pytest.raises(OSError): os.fstat(fd)


def overflow_root(monkeypatch):
  proxy = SimpleNamespace(**vars(os)); original = os.fstat
  def observed(fd):
    info = original(fd)
    if os.readlink("/proc/self/fd/" + str(fd)) == "/": return changed(info, st_uid=OVERFLOW)
    return info
  proxy.fstat = observed
  monkeypatch.setattr(paths, "os", proxy)


def test_prepare_fails_at_declared_root_before_executable_or_mounts(shell_case, monkeypatch):
  overflow_root(monkeypatch)
  monkeypatch.setattr(pi_shell_preparation, "_executable", lambda _: pytest.fail("ancestor must reject before executable"))
  with pytest.raises(ConfigError) as caught: pi_shell_preparation.prepare_shell(**shell_case)
  assert caught.value.code == "pi-shell-preparation"


def test_production_worker_helper_receipt_lookup_fails_before_rpc_when_root_overflows(tmp_path, monkeypatch):
  host = modern_host(tmp_path, monkeypatch)
  overflow_root(monkeypatch)
  with pytest.raises(Conflict, match="宿主PID命名空间helper未绑定到所选运行包"):
    pi_pid_namespace.host_namespace_binary(host)


@pytest.mark.parametrize("owner", [0, "current", OVERFLOW])
def test_executable_source_independently_rejects_overflow_after_trusted_ancestors(tmp_path, monkeypatch, owner):
  file = tmp_path / "synthetic-bash"; file.write_bytes(b"synthetic bash, never execute"); file.chmod(0o700)
  info = file.stat(); uid = os.geteuid() if owner == "current" else owner
  expected = {"path": str(file), "device": info.st_dev, "inode": info.st_ino, "uid": uid,
    "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
  proxy = SimpleNamespace(**vars(os)); original_stat, original_fstat = os.stat, os.fstat
  proxy.stat = lambda *args, **kwargs: changed(original_stat(*args, **kwargs), st_uid=uid)
  proxy.fstat = lambda fd: changed(original_fstat(fd), st_uid=uid)
  monkeypatch.setattr(pi_shell_sources, "os", proxy)
  if owner == OVERFLOW:
    proxy.read = lambda *args: pytest.fail("UID refusal must precede content hash")
    with pytest.raises(Conflict, match="SHELL_SOURCE_IDENTITY"): pi_shell_sources._executable(expected)
  else:
    fd = pi_shell_sources._executable(expected)
    try: assert os.read(fd, 65536) == b"synthetic bash, never execute"
    finally: os.close(fd)


@pytest.mark.parametrize("kind", ["host", "delegate"])
def test_production_namespace_argv_has_no_explicit_user_mapping_contract(tmp_path, monkeypatch, kind):
  """只证明仓库argv；不能据此推断所选helper内部是否自动unshare-user。"""
  if kind == "host":
    host = modern_host(tmp_path, monkeypatch)
    command = SimpleNamespace(cwd=tmp_path, argv=("synthetic-command",))
    argv = pi_pid_namespace.host_namespace_argv(host, command, 42, "a" * 64)
    assert argv[argv.index("--bind"):argv.index("--bind") + 3] == ["--bind", "/", "/"]
  else:
    runtime = tmp_path / "runtime"; runtime.mkdir()
    (runtime / "bin/codex-resources").mkdir(parents=True)
    (runtime / "bin/codex-resources/bwrap").write_bytes(b"synthetic never execute")
    repository = tmp_path / "repo"; (repository / "scripts").mkdir(parents=True)
    (repository / "scripts/pi-namespace-exec.py").write_bytes(b"synthetic never execute")
    host = SimpleNamespace(runtime_root=runtime, repository=repository, root=tmp_path,
      config={"instance_root": str(tmp_path)}, manifest=lambda: {"options": {}},
      store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _: {"git_dir_path": None})))
    command = SimpleNamespace(cwd=tmp_path, argv=("synthetic-command",))
    argv = pi_pid_namespace.namespace_argv(host, command, 42)
  assert "--unshare-pid" in argv and "--as-pid-1" in argv
  assert all(flag not in argv for flag in ("--unshare-user", "--uid", "--gid", "--uid-map", "--gid-map"))
