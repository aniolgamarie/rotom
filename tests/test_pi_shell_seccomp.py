"""独立 cBPF 解释器的语义证据；不安装过滤器，不声称内核执行通过。"""

import struct

import pytest

from agentcfg.pi_shell_seccomp import compile_filter
from agentcfg.schema import ConfigError


def evaluate(program, nr, *, arch=0xC000003E, args=()):
  assert type(program) is bytes and program and len(program) % 8 == 0
  instructions = list(struct.iter_unpack("<HBBI", program))
  assert len(instructions) <= 4096
  data = struct.pack("<IIQ6Q", nr & 0xFFFFFFFF, arch, 0, *(list(args) + [0] * (6 - len(args))))
  pc, accumulator = 0, 0
  for _ in range(len(instructions)):
    assert 0 <= pc < len(instructions)
    code, jt, jf, value = instructions[pc]
    if code == 0x20:
      assert jt == jf == 0 and value % 4 == 0 and value + 4 <= len(data)
      accumulator, = struct.unpack_from("<I", data, value)
      pc += 1
    elif code in (0x15, 0x35, 0x45):
      condition = accumulator == value if code == 0x15 else accumulator >= value if code == 0x35 else bool(accumulator & value)
      pc += 1 + (jt if condition else jf)
    elif code == 0x06:
      assert jt == jf == 0
      return value
    else: raise AssertionError("unexpected cBPF instruction")
  raise AssertionError("filter did not terminate")


@pytest.fixture
def program():
  return compile_filter("linux-x86_64")


def test_compilation_is_deterministic_without_files(tmp_path, sentinel_factory):
  sentinel = sentinel_factory(tmp_path)
  first = compile_filter("linux-x86_64")
  assert first == compile_filter("linux-x86_64") and type(first) is bytes
  assert len(first) % 8 == 0
  sentinel.assert_unchanged()


@pytest.mark.parametrize("platform_id", ["linux-aarch64", "linux-i386", "darwin-x86_64", "", None, 1])
def test_unknown_platform_fails_closed(platform_id):
  with pytest.raises(ConfigError) as caught: compile_filter(platform_id)
  assert caught.value.code == "pi-shell-seccomp-platform"


@pytest.mark.parametrize("nr", [0, 1, 2, 3, 9, 10, 12, 16, 17, 18, 19, 20, 22, 57, 58, 59, 60, 61, 202, 231, 257, 322])
def test_ordinary_io_memory_threads_fork_and_exec_are_allowed(program, nr):
  assert evaluate(program, nr) == 0x7FFF0000


@pytest.mark.parametrize("family", [1, 2, 10, 16])
def test_socket_creation_is_denied_for_unix_inet_inet6_and_netlink(program, family):
  assert evaluate(program, 41, args=(family, 1, 0)) == 0x00050001


def test_anonymous_socketpair_is_allowed(program):
  assert evaluate(program, 53, args=(1, 1, 0)) == 0x7FFF0000


@pytest.mark.parametrize("name,nr", [
  ("connect", 42), ("bind", 49), ("ptrace", 101), ("pivot_root", 155),
  ("mount", 165), ("umount2", 166), ("unshare", 272), ("open_by_handle_at", 304),
  ("setns", 308), ("process_vm_readv", 310), ("process_vm_writev", 311),
  ("io_uring_setup", 425), ("io_uring_enter", 426), ("io_uring_register", 427),
  ("open_tree", 428), ("move_mount", 429), ("fsopen", 430), ("fsconfig", 431),
  ("fsmount", 432), ("fspick", 433), ("pidfd_getfd", 438), ("mount_setattr", 442)])
def test_escape_and_alternative_entry_points_return_eperm(program, name, nr):
  assert evaluate(program, nr, args=(0xFFFFFFFFFFFFFFFF,)) == 0x00050001


@pytest.mark.parametrize("arch", [0x40000003, 0xC00000B7, 0x8000003E, 0x4000003E, 0, 0xFFFFFFFF])
@pytest.mark.parametrize("nr", [0, 41, 56, 435])
def test_i386_other_arch_and_wrong_endianness_are_killed_before_syscall_dispatch(program, arch, nr):
  assert evaluate(program, nr, arch=arch) == 0x80000000


@pytest.mark.parametrize("nr", [0x40000000, 0x40000029, 0x40000208, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, -1, -42])
def test_x32_and_negative_syscall_numbers_are_killed(program, nr):
  assert evaluate(program, nr) == 0x80000000


@pytest.mark.parametrize("flags", [0x00020000, 0x02000000, 0x04000000, 0x08000000, 0x10000000, 0x20000000, 0x40000000,
  0x7E020000, 0x00020000 | 0x00000100, 0x40000000 | 17])
def test_clone_namespace_flags_return_eperm(program, flags):
  assert evaluate(program, 56, args=(flags,)) == 0x00050001


@pytest.mark.parametrize("flags", [0, 17, 0x100, 0x000D0F00, 0x003D0F00, 0x80000000])
def test_clone_without_namespace_flags_remains_allowed(program, flags):
  assert evaluate(program, 56, args=(flags,)) == 0x7FFF0000


def test_clone_checks_only_flags_argument(program):
  assert evaluate(program, 56, args=(17, 0x7E020000)) == 0x7FFF0000


def test_clone3_returns_enosys_for_standard_library_fallback(program):
  assert evaluate(program, 435, args=(0x123456789ABCDEF0, 88)) == 0x00050026


def test_remaining_numbers_are_not_accidentally_denied(program):
  for nr in (40, 43, 48, 50, 52, 54, 55, 100, 102, 154, 156, 164, 167, 271, 273,
      303, 305, 307, 309, 312, 424, 434, 436, 437, 439, 440, 441, 443, 999):
    assert evaluate(program, nr) == 0x7FFF0000
