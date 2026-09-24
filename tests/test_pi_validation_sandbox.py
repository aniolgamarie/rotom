"""只核对原生验收沙箱意图，不运行 bwrap/sandbox-exec。"""
from pathlib import Path
from types import SimpleNamespace
import pytest
from agentcfg.pi_validation_sandbox import sandbox_argv
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def fixture(tmp_path):
  work = tmp_path / "work"; (work / "cases/host").mkdir(parents=True)
  programs = {"engine": "/toolchains/node/bin/node", "git": "/toolchains/git/bin/git", "python_runtime": "/toolchains/python",
    "python_packages": "/toolchains/manager/site-packages"}
  return SimpleNamespace(root=tmp_path / "runtime"), work, work / "cases/host/input.json", programs


def test_linux_native_host_has_private_pid_and_network_namespaces_without_real_home(tmp_path):
  runtime, work, path, programs = fixture(tmp_path)
  argv = sandbox_argv(runtime, work, path, programs, 41234, system="linux", system_roots=(), python_prefix="/toolchains/manager")
  assert "--unshare-all" in argv and "--share-net" not in argv and "--die-with-parent" in argv and "--new-session" in argv
  assert ("--ro-bind", "/", "/") not in tuple(zip(argv, argv[1:], argv[2:]))
  assert str(Path.home()) not in argv
  assert ("--bind", str(work), str(work)) in tuple(zip(argv, argv[1:], argv[2:]))
  assert argv[-2:] == ("--input", str(path))


def test_macos_native_network_is_only_the_declared_fixture_port_and_private_unix_paths(tmp_path):
  runtime, work, path, programs = fixture(tmp_path)
  argv = sandbox_argv(runtime, work, path, programs, 41234, system="darwin", system_roots=(), python_prefix="/toolchains/manager")
  policy = Path(argv[2]).read_text()
  assert '(remote ip "127.0.0.1:41234")' in policy and '(remote ip "127.0.0.1:*")' not in policy
  assert "(allow network*)" not in policy and "(deny default)" in policy
  assert '(deny file-write* (subpath "' + str(work / "source") + '"))' in policy


def test_runtime_and_scratch_cannot_alias_or_mount_a_complete_home(tmp_path):
  runtime, work, path, programs = fixture(tmp_path)
  with pytest.raises(ConfigError): sandbox_argv(SimpleNamespace(root=work), work, path, programs, 41234)
  with pytest.raises(ConfigError): sandbox_argv(runtime, work, path, programs, 41234, python_prefix=Path.home())


def test_standalone_cli_gets_a_readonly_runtime_at_its_fresh_instance_path(tmp_path):
  runtime, work, path, programs = fixture(tmp_path)
  runtime.profile = "pi-default"; runtime.identity = "a" * 64
  argv = sandbox_argv(runtime, work, path, programs, 41234, system="linux", system_roots=(), python_prefix="/toolchains/manager", local_runtime=True)
  expected = path.parent / "fixture/instances_root/pi/pi-default/runtimes" / runtime.identity
  assert ("--ro-bind", str(runtime.root), str(expected)) in tuple(zip(argv, argv[1:], argv[2:]))


def test_macos_standalone_cli_gets_a_real_runtime_copy_and_keeps_the_original_readonly(tmp_path):
  """sandbox-exec没有bind挂载且inspect_runtime拒绝符号链接；整包拷贝为真实目录，原始运行包仍只读。"""
  runtime, work, path, programs = fixture(tmp_path)
  (runtime.root / "runtime").mkdir(parents=True)
  (runtime.root / "runtime/profile.json").write_bytes(b"{}")
  runtime.profile = "pi-default"; runtime.identity = "a" * 64
  argv = sandbox_argv(runtime, work, path, programs, 41234, system="darwin", system_roots=(), python_prefix="/toolchains/manager", local_runtime=True)
  slot = path.parent / "fixture/instances_root/pi/pi-default/runtimes" / runtime.identity
  assert slot.is_dir() and not slot.is_symlink() and (slot / "runtime/profile.json").read_bytes() == b"{}"
  policy = Path(argv[2]).read_text()
  assert '(allow file-read* (subpath "' + str(runtime.root) + '"))' in policy
  with pytest.raises(Conflict):
    sandbox_argv(runtime, work, path, programs, 41234, system="darwin", system_roots=(), python_prefix="/toolchains/manager", local_runtime=True)


def test_bun_host_sandbox_also_binds_the_independent_node_binding(tmp_path):
  """Cursor/Bun 宿主的 ReadSeek worker 需要锁定 Node；其发行目录必须进入只读绑定，未提供时不扩权。"""
  runtime, work, path, programs = fixture(tmp_path)
  programs = dict(programs, engine="/toolchains/bun/bin/bun", node="/toolchains/pi-node/bin/node")
  argv = sandbox_argv(runtime, work, path, programs, 41234, system="linux", system_roots=(), python_prefix="/toolchains/manager")
  pairs = tuple(zip(argv, argv[1:]))
  assert ("--ro-bind", "/toolchains/pi-node") in pairs
  plain = sandbox_argv(runtime, work, path, {k: v for k, v in programs.items() if k != "node"},
    41234, system="linux", system_roots=(), python_prefix="/toolchains/manager")
  assert ("--ro-bind", "/toolchains/pi-node") not in tuple(zip(plain, plain[1:]))
