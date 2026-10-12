#!/usr/bin/env python3
"""PID 1 的一次性门控入口；只在监督者写入G后exec固定命令，EOF不放行。"""
import os
import socket
import sys
import stat
import array


def receive_control_directory(gate):
  received = []
  valid = True
  try:
    data, ancillary, flags, _ = gate.recvmsg(1, socket.CMSG_SPACE(2 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
    for level, kind, body in ancillary:
      if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS or len(body) % array.array("i").itemsize:
        valid = False
        continue
      values = array.array("i"); values.frombytes(body); received.extend(values)
    if not valid or data != b"G" or flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) or len(received) != 1:
      raise ValueError()
    info = os.fstat(received[0])
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise ValueError()
    return received.pop()
  finally:
    for descriptor in received: os.close(descriptor)


def main():
  if len(sys.argv) >= 5 and sys.argv[1] == "--host-gate":
    token = sys.argv[2]
    control = sys.argv[3] == "--control-directory"
    separator = 4 if control else 3
    if len(sys.argv) <= separator + 1 or sys.argv[separator] != "--": return 2
    if os.getpid() != 1 or len(token) != 64 or any(char not in "0123456789abcdef" for char in token): return 2
    # 保留宿主原始stdin/TTY；门控走经SO_PEERCRED核验的独立一次性通道。
    os.setsid()
    directory = None
    try:
      with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as gate:
        gate.connect("\0agentcfg-host-gate-" + token)
        gate.sendall(b"R")
        if control: directory = receive_control_directory(gate)
        elif gate.recv(1) != b"G": return 125
      # gate已关闭；只在当前专用子进程映射固定3，不触及父线程FD表。
      if directory is not None:
        if directory != 3:
          os.dup2(directory, 3); os.close(directory)
        directory = None
        os.set_inheritable(3, True)
        os.environ["AGENTCFG_SUPERVISOR_DIRECTORY_FD"] = "3"
    finally:
      if directory is not None: os.close(directory)
    os.umask(0o077)
    if os.environ.pop("AGENTCFG_EXECUTION_TTY", None) == "1":
      import fcntl
      import termios
      if not os.isatty(0): return 125
      fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.execvpe(sys.argv[separator + 1], sys.argv[separator + 1:], os.environ)
    return 126
  if len(sys.argv) < 3 or sys.argv[1] != "--" or os.getpid() != 1: return 2
  if os.read(0, 1) != b"G": return 125
  os.close(0)
  fd = os.open("/dev/null", os.O_RDONLY)
  if fd != 0:
    os.dup2(fd, 0); os.close(fd)
  os.set_inheritable(0, True)
  os.umask(0o077)
  os.execv(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
  try: sys.exit(main())
  except Exception: sys.exit(126)
