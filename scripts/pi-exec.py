#!/usr/bin/env python3
"""Linux 执行闸门：监督者持久登记身份/租约后，才允许 exec 目标程序。"""

import os
import sys
import stat


def main():
  args = sys.argv[1:]
  if len(args) < 4 or args[0] != "--gate-fd":
    return 2
  control = int(args[3]) if args[2] == "--control-directory-fd" and len(args) >= 6 else None
  separator = 4 if control is not None else 2
  if args[separator] != "--": return 2
  descriptor = int(args[1])
  if descriptor < 3 or control is not None and (control < 3 or control == descriptor):
    return 2
  try:
    admitted = os.read(descriptor, 1)
  finally:
    os.close(descriptor)
  if admitted != b"G":
    if control is not None: os.close(control)
    return 125
  if control is not None:
    try:
      info = os.fstat(control)
      if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        return 125
      if control != 3: os.dup2(control, 3)
      os.set_inheritable(3, True)
      os.environ["AGENTCFG_SUPERVISOR_DIRECTORY_FD"] = "3"
    finally:
      if control != 3: os.close(control)
  # Pi/插件的原生会话与缓存也必须默认 0600/0700，不继承调用者的宽松 umask。
  os.umask(0o077)
  if os.environ.pop("AGENTCFG_EXECUTION_TTY", None) == "1":
    import fcntl
    import termios
    if not os.isatty(0):
      return 125
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
  os.execvpe(args[separator + 1], args[separator + 1:], os.environ)
  return 126


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception:
    sys.exit(126)
