"""自有隔离探针payload；只在明确启动的新helper内部观察，无导入动作。"""

import errno
import json
import os
from pathlib import Path
import re
import socket
import sys


WORK_ROOT = Path(__file__).parent.parent
ROOTS = {"project": WORK_ROOT / "project", "readonly": WORK_ROOT / "readonly", "outside": WORK_ROOT / "outside",
  "home": Path("/.rotom-shell/home"), "tmp": Path("/tmp")}
DENIED = {errno.EACCES, errno.EPERM, errno.ENOENT, errno.ENOTDIR, errno.EROFS}
NAMESPACES = ("pid", "net", "user", "mnt", "ipc", "uts")


def _read(path):
  with path.open("rb") as stream: return stream.read(65537)


def _create(path, data):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
  try:
    offset = 0
    while offset < len(data):
      try: written = os.write(fd, data[offset:])
      except InterruptedError: continue
      if written <= 0: raise OSError(errno.EIO, "probe-write")
      offset += written
  finally: os.close(fd)


def _read_blocked(path):
  try: _read(path)
  except OSError as error: return error.errno in DENIED
  return False


def _write_blocked(path):
  try: _create(path, b"probe-blocked\n")
  except OSError as error: return error.errno in DENIED
  # 普通文件系统上的成功写入必须报告失败，并清理自建文件。
  path.unlink()
  return False


def _positive(path, data, *, remove=False):
  created = False
  try:
    _create(path, data); created = True
    return _read(path) == data
  except OSError: return False
  finally:
    if remove and created: path.unlink()


def _environment():
  return dict(os.environ)


def _env_clean():
  fixed = {"HOME": "/.rotom-shell/home", "TMPDIR": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8", "TERM": "dumb"}
  optional = {"PWD": {str(WORK_ROOT / "project")}, "SHLVL": {"0", "1"}, "_": {"/usr/bin/python3.11"}}
  env = _environment()
  return (all(env.get(key) == value for key, value in fixed.items())
    and all(key in fixed or key in optional and value in optional[key] for key, value in env.items()))


def _namespace_links():
  return {name: os.readlink("/proc/self/ns/" + name) for name in NAMESPACES}


def _open_fds():
  result = []
  for name in os.listdir("/proc/self/fd"):
    if not name.isdecimal(): raise ValueError("probe-fds")
    fd = int(name)
    try: os.fstat(fd)
    except OSError as error:
      # listdir的临时目录FD可能已关；仅忽略确定的EBADF。
      if error.errno == errno.EBADF: continue
      raise
    result.append(fd)
  return tuple(sorted(result))


def _mountinfo():
  with open("/proc/self/mountinfo", "rb") as stream:
    data = stream.read(4 * 1024 * 1024 + 1)
  if len(data) > 4 * 1024 * 1024: raise ValueError("probe-mountinfo")
  return data.decode("utf-8", errors="strict")


def _system_readonly():
  matches = []
  for line in _mountinfo().splitlines():
    fields = line.split()
    if len(fields) < 10 or "-" not in fields[6:]: raise ValueError("probe-mountinfo")
    if fields[4] == "/usr":
      access = set(fields[5].split(",")) & {"ro", "rw"}
      matches.append(access == {"ro"})
  return len(matches) == 1 and matches[0]


def _socket_denied(family):
  value = None
  try:
    value = socket.socket(family, socket.SOCK_STREAM)
    return False
  except OSError as error: return error.errno == errno.EPERM
  finally:
    if value is not None: value.close()


def _socketpair_works():
  ends = ()
  try:
    ends = socket.socketpair()
    ends[0].sendall(b"probe")
    data = b""
    while len(data) < 5:
      part = ends[1].recv(5 - len(data))
      if not part: return False
      data += part
    return data == b"probe"
  except OSError: return False
  finally:
    for end in ends: end.close()


def observe(nonce):
  if type(nonce) is not str or not re.fullmatch(r"[0-9a-f]{32}", nonce): raise ValueError("probe-nonce")
  project, readonly, outside = (ROOTS[key] for key in ("project", "readonly", "outside"))
  data = (nonce + "\n").encode("ascii")
  written = _positive(project / "positive", data)
  try: read = _read(project / "positive") == data
  except OSError: read = False
  try: readonly_read = _read(readonly / "canary") == b"probe-readonly\n"
  except OSError: readonly_read = False
  observations = {"project_write": written, "project_read": read, "readonly_read": readonly_read,
    "readonly_write_blocked": _write_blocked(readonly / "blocked-write"),
    "outside_read_blocked": _read_blocked(outside / "canary"), "outside_write_blocked": _write_blocked(outside / "blocked-write"),
    "deny_read_blocked": _read_blocked(project / "private/canary"), "deny_write_blocked": _write_blocked(project / "private/blocked-write"),
    "git_read_blocked": _read_blocked(project / "nested/.git/canary"), "git_write_blocked": _write_blocked(project / "nested/.git/blocked-write"),
    "private_home_write": _positive(ROOTS["home"] / "positive", data, remove=True),
    "private_tmp_write": _positive(ROOTS["tmp"] / "positive", data, remove=True),
    "env_clean": _env_clean(), "fds_only_stdio": _open_fds() == (0, 1, 2),
    "inet_socket_denied": _socket_denied(socket.AF_INET), "inet6_socket_denied": _socket_denied(socket.AF_INET6),
    "unix_socket_denied": _socket_denied(socket.AF_UNIX), "socketpair_works": _socketpair_works(), "system_readonly": _system_readonly()}
  namespaces = _namespace_links()
  if set(namespaces) != set(NAMESPACES) or any(type(value) is not str or not re.fullmatch(name + r":\[[0-9]+\]", value)
      for name, value in namespaces.items()): raise ValueError("probe-namespaces")
  return {"schema_version": 1, "phase": "payload", "nonce": nonce, "observations": observations, "namespaces": namespaces}


def main(argv=None):
  try:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--payload": raise ValueError("probe-arguments")
    result = observe(args[1])
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0
  except Exception:
    sys.stderr.write("shell-probe-payload-failed\n")
    return 5


if __name__ == "__main__":
  sys.exit(main())
