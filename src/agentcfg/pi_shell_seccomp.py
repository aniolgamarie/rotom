"""固定 Linux x86_64 Shell cBPF 生成器；不安装过滤器、不执行进程。

此规则只是隔离组合的一部分，不是完整 sandbox；其余 syscall 默认允许。
布局与动作：https://docs.kernel.org/userspace-api/seccomp_filter.html
编号：https://raw.githubusercontent.com/torvalds/linux/v5.10/arch/x86/entry/syscalls/syscall_64.tbl
mount_setattr 编号补充：https://raw.githubusercontent.com/torvalds/linux/v6.12/arch/x86/entry/syscalls/syscall_64.tbl
"""

import struct

from .schema import ConfigError


LD_WORD_ABSOLUTE = 0x20
JUMP_EQUAL = 0x15
JUMP_GREATER_EQUAL = 0x35
JUMP_BITS_SET = 0x45
RETURN_CONSTANT = 0x06
KILL_PROCESS = 0x80000000
ERRNO = 0x00050000
ALLOW = 0x7FFF0000

# 固定 x86_64 ABI；不得使用编译机器自身的 errno/syscall 编号替换目标 ABI。
DENIED_SYSCALLS = (
  41, 42, 49,                         # socket、connect、bind
  101, 155, 165, 166,                 # ptrace、pivot_root、mount、umount2
  272, 304, 308, 310, 311,            # unshare、句柄打开、setns、跨进程内存
  425, 426, 427,                     # io_uring 的替代入口
  428, 429, 430, 431, 432, 433,       # 新挂载 API
  438, 442,                         # pidfd_getfd、mount_setattr
)


def compile_filter(platform_id):
  """返回 bwrap --seccomp 所需的小端 sock_filter 字节，不创建 FD。"""
  if type(platform_id) is not str or platform_id != "linux-x86_64":
    raise ConfigError("pi-shell-seccomp-platform")
  instructions = [
    (LD_WORD_ABSOLUTE, 0, 0, 4),
    (JUMP_EQUAL, 1, 0, 0xC000003E),
    (RETURN_CONSTANT, 0, 0, KILL_PROCESS),
    (LD_WORD_ABSOLUTE, 0, 0, 0),
    # unsigned 比较同时拒绝 x32 位与负数，先于任何 syscall 分派。
    (JUMP_GREATER_EQUAL, 0, 1, 0x40000000),
    (RETURN_CONSTANT, 0, 0, KILL_PROCESS),
  ]
  for nr in DENIED_SYSCALLS:
    instructions.extend(((JUMP_EQUAL, 0, 1, nr), (RETURN_CONSTANT, 0, 0, ERRNO | 1)))
  instructions.extend((
    (JUMP_EQUAL, 0, 1, 435),
    (RETURN_CONSTANT, 0, 0, ERRNO | 38),  # clone3: ENOSYS，让线程库回退普通 clone。
    (JUMP_EQUAL, 0, 3, 56),
    # legacy clone 的 namespace flags；低 8 位是退出信号，NEWTIME 只用于 unshare/clone3。
    (LD_WORD_ABSOLUTE, 0, 0, 16),
    (JUMP_BITS_SET, 0, 1, 0x7E020000),
    (RETURN_CONSTANT, 0, 0, ERRNO | 1),
    (RETURN_CONSTANT, 0, 0, ALLOW),
  ))
  return b"".join(struct.pack("<HBBI", *instruction) for instruction in instructions)
