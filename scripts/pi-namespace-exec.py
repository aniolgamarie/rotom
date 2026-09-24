#!/usr/bin/env python3
"""PID 1 的一次性门控入口；只在监督者写入G后exec固定命令，EOF不放行。"""
import os
import socket
import sys


def main():
  if len(sys.argv) >= 5 and sys.argv[1] == "--host-gate" and sys.argv[3] == "--":
    token = sys.argv[2]
    if os.getpid() != 1 or len(token) != 64 or any(char not in "0123456789abcdef" for char in token): return 2
    # 保留宿主原始stdin/TTY；门控走经SO_PEERCRED核验的独立一次性通道。
    os.setsid()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as gate:
      gate.connect("\0agentcfg-host-gate-" + token)
      gate.sendall(b"R")
      if gate.recv(1) != b"G": return 125
    os.umask(0o077)
    if os.environ.pop("AGENTCFG_EXECUTION_TTY", None) == "1":
      import fcntl
      import termios
      if not os.isatty(0): return 125
      fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.execvpe(sys.argv[4], sys.argv[4:], os.environ)
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
