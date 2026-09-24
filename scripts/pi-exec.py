#!/usr/bin/env python3
"""Linux 执行闸门：监督者持久登记身份/租约后，才允许 exec 目标程序。"""

import os
import sys


def main():
  args = sys.argv[1:]
  if len(args) < 4 or args[0] != "--gate-fd" or args[2] != "--":
    return 2
  descriptor = int(args[1])
  if descriptor < 3:
    return 2
  try:
    admitted = os.read(descriptor, 1)
  finally:
    os.close(descriptor)
  if admitted != b"G":
    return 125
  # Pi/插件的原生会话与缓存也必须默认 0600/0700，不继承调用者的宽松 umask。
  os.umask(0o077)
  if os.environ.pop("AGENTCFG_EXECUTION_TTY", None) == "1":
    import fcntl
    import termios
    if not os.isatty(0):
      return 125
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
  os.execvpe(args[3], args[3:], os.environ)
  return 126


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception:
    sys.exit(126)
