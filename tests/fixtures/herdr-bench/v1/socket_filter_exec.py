#!/usr/bin/env python3
"""固定合成基准的 Unix-only socket 入口；不是任意恶意程序的完整沙箱。"""
import ctypes
import errno
import os
from pathlib import Path
import socket
import stat
import sys

ROOT = Path(__file__).resolve().parents[4]
ALLOW = 0x7FFF0000
DENY = 0x00050000 | errno.EPERM


class ArgCmp(ctypes.Structure):
  _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_uint),
    ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def libraries():
  lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
  libc = ctypes.CDLL(None, use_errno=True)
  return lib, libc


def configure(lib, libc):
  lib.seccomp_init.argtypes = [ctypes.c_uint32]
  lib.seccomp_init.restype = ctypes.c_void_p
  lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
  lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
  lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
    ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ArgCmp)]
  lib.seccomp_rule_add_array.restype = ctypes.c_int
  lib.seccomp_load.argtypes = [ctypes.c_void_p]
  lib.seccomp_load.restype = ctypes.c_int
  lib.seccomp_release.argtypes = [ctypes.c_void_p]
  lib.seccomp_release.restype = None
  libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
  libc.prctl.restype = ctypes.c_int


def install_filter(*, lib=None, libc=None):
  if lib is None or libc is None:
    lib, libc = libraries()
  configure(lib, libc)
  if libc.prctl(38, 1, 0, 0, 0) != 0:
    raise OSError("no_new_privs_unavailable")
  ctx = lib.seccomp_init(ALLOW)
  if not ctx:
    raise OSError("seccomp_context_unavailable")
  try:
    for name in (b"socket", b"socketpair", b"io_uring_setup"):
      number = lib.seccomp_syscall_resolve_name(name)
      if number < 0:
        raise OSError("seccomp_syscall_unresolved")
      # libseccomp 负责本地 ABI/架构检查；不手写可混淆的 syscall 数字。
      comparison = ArgCmp(0, 1, socket.AF_UNIX, 0)  # SCMP_CMP_NE
      count = 0 if name == b"io_uring_setup" else 1
      result = lib.seccomp_rule_add_array(ctx, DENY, number, count, ctypes.pointer(comparison) if count else None)
      if result != 0:
        raise OSError("seccomp_rule_unavailable")
    if lib.seccomp_load(ctx) != 0:
      raise OSError("seccomp_filter_unavailable")
  finally:
    lib.seccomp_release(ctx)


def fd_numbers():
  return sorted(int(name) for name in os.listdir("/proc/self/fd"))


def close_inherited_fds(*, fd_numbers=fd_numbers, close=os.close):
  for fd in fd_numbers():
    if fd > 2:
      try:
        close(fd)
      except OSError as error:
        if error.errno != errno.EBADF:
          raise


def family_for_fd(fd):
  with socket.socket(fileno=os.dup(fd)) as stream:
    return stream.getsockopt(socket.SOL_SOCKET, getattr(socket, "SO_DOMAIN", 39))


def check_stdio(*, stat_fd=os.fstat, family_for_fd=family_for_fd):
  for fd in (0, 1, 2):
    try:
      info = stat_fd(fd)
    except OSError as error:
      if error.errno == errno.EBADF:
        continue
      raise
    if stat.S_ISSOCK(info.st_mode) and family_for_fd(fd) != socket.AF_UNIX:
      raise OSError("network_stdio_refused")


def check_no_extra_fds():
  for fd in fd_numbers():
    if fd > 2:
      try:
        os.fstat(fd)
      except OSError as error:
        if error.errno == errno.EBADF:
          continue
        raise
      raise OSError("inherited_nonstdio_fd_refused")


def ring_errno():
  lib, libc = libraries()
  lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
  lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
  number = lib.seccomp_syscall_resolve_name(b"io_uring_setup")
  if number < 0:
    raise OSError("io_uring_syscall_unresolved")
  params = ctypes.create_string_buffer(256)
  libc.syscall.restype = ctypes.c_long
  ctypes.set_errno(0)
  result = libc.syscall(ctypes.c_long(number), ctypes.c_uint(1), ctypes.byref(params))
  if result >= 0:
    os.close(result)
    return 0
  return ctypes.get_errno()


def unix_check():
  left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
  try:
    left.settimeout(1)
    right.settimeout(1)
    return left.send(b"x") == 1 and right.recv(1) == b"x"
  finally:
    left.close()
    right.close()


def denied_errno(call, family):
  try:
    result = call(family, socket.SOCK_STREAM)
  except OSError as error:
    return error.errno
  for stream in result if isinstance(result, tuple) else (result,):
    stream.close()
  return 0


def prove_policy(*, status_text=None, create_socket=None, create_pair=None,
    unix_check=unix_check, ring_errno=ring_errno, stdio_check=check_stdio,
    extra_fds_check=check_no_extra_fds, root_visible=None):
  stdio_check()
  extra_fds_check()
  status_text = Path("/proc/self/status").read_text() if status_text is None else status_text
  fields = dict(line.split(":", 1) for line in status_text.splitlines() if ":" in line)
  if fields.get("NoNewPrivs", "").strip() != "1" or fields.get("Seccomp", "").strip() != "2":
    raise OSError("socket_filter_kernel_status_unverified")
  visible = Path("/").stat().st_uid == 0 if root_visible is None else root_visible
  if not visible:
    raise OSError("trusted_root_ancestor_unmapped")
  create_socket = socket.socket if create_socket is None else create_socket
  create_pair = socket.socketpair if create_pair is None else create_pair
  checks = [denied_errno(call, family) for call in (create_socket, create_pair)
    for family in (socket.AF_INET, socket.AF_INET6)]
  unix = unix_check()
  ring = ring_errno()
  if checks != [errno.EPERM] * 4 or not unix or ring != errno.EPERM:
    raise OSError("offline_socket_capabilities_unverified")
  return {"mode": "offline-sockets-seccomp", "no_new_privs": 1, "seccomp": 2,
    "inet_errno": checks[0], "inet6_errno": checks[1], "inet_pair_errno": checks[2],
    "inet6_pair_errno": checks[3], "unix_ipc": True, "io_uring_errno": ring,
    "root_owner_visible": True, "network_stdio_absent": True, "extra_fds_absent": True,
    "uid": os.getuid(), "gid": os.getgid()}


def main(argv=None):
  argv = list(sys.argv[1:] if argv is None else argv)
  if (not argv or argv[0] not in {"run", "calibrate"} or "--allow-native" not in argv
      or "--offline-sockets" not in argv or "--isolated-netns" in argv or "--socket-filter-active" in argv):
    return 2
  try:
    check_stdio()
    close_inherited_fds()
    install_filter()
    prove_policy()
    os.execv(sys.executable, [sys.executable, str(ROOT / "tools/bench/herdr_upgrade.py"), *argv, "--socket-filter-active"])
  except (OSError, AttributeError):
    print("offline_socket_filter_unavailable_or_unverified", file=sys.stderr)
    return 5
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
