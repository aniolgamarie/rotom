#!/usr/bin/env python3
"""One-round cpuacct delegation. No remount, quotas, existing PID writes, or process stopping."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

ROLES = ("driver", "server", "client", "producer")
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def identity(info):
  return {"dev": info.st_dev, "ino": info.st_ino}


def decoded(value):
  return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def directory(parent, name):
  fd = os.open(name, FLAGS, dir_fd=parent)
  info = os.fstat(fd)
  if info.st_uid != 0 or info.st_mode & 0o022:
    os.close(fd)
    raise RuntimeError("unsafe_kernel_directory")
  return fd


def empty(fd):
  for name in ("cgroup.procs", "tasks"):
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    try:
      if os.read(source, 1048576).strip():
        raise RuntimeError("group_not_empty")
    finally:
      os.close(source)
  if any(entry.is_dir(follow_symlinks=False) for entry in os.scandir(fd)):
    raise RuntimeError("unexpected_child_group")


def locate():
  sources = []
  for line in Path("/proc/self/cgroup").read_text().splitlines():
    _, controllers, path = line.split(":", 2)
    if "cpuacct" in controllers.split(","):
      sources.append(decoded(path))
  if len(sources) != 1:
    raise RuntimeError("cpuacct_source_not_unique")
  source = sources[0]
  if PurePosixPath(source).as_posix() != source or ".." in PurePosixPath(source).parts:
    raise RuntimeError("unsupported_cgroup_namespace_path")
  matches = []
  for line in Path("/proc/self/mountinfo").read_text().splitlines():
    left, right = line.split(" - ", 1)
    a, b = left.split(), right.split()
    if b[0] != "cgroup" or "cpuacct" not in b[2].split(","):
      continue
    if "rw" not in a[5].split(",") or "rw" not in b[2].split(","):
      continue
    mounted_root, mount = decoded(a[3]), decoded(a[4])
    try:
      relative = PurePosixPath(source).relative_to(PurePosixPath(mounted_root))
    except ValueError:
      continue
    target = Path(mount).joinpath(*relative.parts)
    if all((target / n).is_file() for n in ("cpuacct.usage_user", "cpuacct.usage_sys", "cgroup.procs")):
      matches.append(target)
  if len(matches) != 1:
    raise RuntimeError("writable_cpuacct_source_not_unique")
  return source, matches[0]


def prepare(uid, gid):
  source, parent = locate()
  token = uuid.uuid4().hex
  name = "rotom-bench-" + token
  parent_fd = os.open(parent, FLAGS)
  scope = parent / name
  roles, created = {}, []
  try:
    os.mkdir(name, 0o711, dir_fd=parent_fd)
    scope_fd = directory(parent_fd, name)
    try:
      os.fchown(scope_fd, 0, gid)
      os.fchmod(scope_fd, 0o750)
      for role in ROLES:
        os.mkdir(role, 0o711, dir_fd=scope_fd)
        created.append(role)
        fd = directory(scope_fd, role)
        try:
          os.fchown(fd, 0, gid)
          os.fchmod(fd, 0o750)
          empty(fd)
          os.chown("cgroup.procs", uid, gid, dir_fd=fd, follow_symlinks=False)
          os.chmod("cgroup.procs", 0o600, dir_fd=fd, follow_symlinks=False)
          roles[role] = identity(os.fstat(fd))
        finally:
          os.close(fd)
      current = os.fstat(scope_fd)
      receipt = {"schema_version": 1, "method": "cpuacct-v1", "uid": uid,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "source_cgroup": source, "scope_path": str(scope), "scope_dev": current.st_dev,
        "scope_ino": current.st_ino, "roles": roles, "admin_token": token}
      record = Path("/run") / ("rotom-herdr-bench-" + token + ".json")
      out = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
      with os.fdopen(out, "w") as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
      print(json.dumps(receipt, sort_keys=True))
    except BaseException:
      # Only remove newly created empty groups; never kill or move a process.
      for role in reversed(created):
        fd = directory(scope_fd, role)
        try:
          empty(fd)
        finally:
          os.close(fd)
        os.rmdir(role, dir_fd=scope_fd)
      os.rmdir(name, dir_fd=parent_fd)
      raise
    finally:
      os.close(scope_fd)
  finally:
    os.close(parent_fd)


def cleanup(uid, token):
  if not re.fullmatch("[a-f0-9]{32}", token):
    raise RuntimeError("invalid_admin_token")
  record = Path("/run") / ("rotom-herdr-bench-" + token + ".json")
  info = record.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
    raise RuntimeError("invalid_admin_record")
  with record.open() as stream:
    receipt = json.load(stream)
  if receipt["uid"] != uid or receipt["admin_token"] != token or receipt["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
    raise RuntimeError("admin_record_identity_changed")
  scope = Path(receipt["scope_path"])
  if scope.name != "rotom-bench-" + token:
    raise RuntimeError("unexpected_scope")
  parent_fd = os.open(scope.parent, FLAGS)
  fd = directory(parent_fd, scope.name)
  try:
    if identity(os.fstat(fd)) != {"dev": receipt["scope_dev"], "ino": receipt["scope_ino"]}:
      raise RuntimeError("scope_replaced")
    names = {entry.name for entry in os.scandir(fd) if entry.is_dir(follow_symlinks=False)}
    if not names <= set(ROLES):
      raise RuntimeError("unexpected_child_group")
    for role in ROLES:
      if role not in names:
        continue
      leaf = directory(fd, role)
      try:
        if identity(os.fstat(leaf)) != receipt["roles"][role]:
          raise RuntimeError("role_replaced")
        empty(leaf)
      finally:
        os.close(leaf)
    for role in reversed(ROLES):
      if role in names:
        os.rmdir(role, dir_fd=fd)
    empty(fd)
    os.rmdir(scope.name, dir_fd=parent_fd)
    record.unlink()
    print(json.dumps({"status": "removed_empty_owned_cpuacct_groups"}))
  finally:
    os.close(fd)
    os.close(parent_fd)


def main():
  os.umask(0o077)
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("action", choices=("prepare", "cleanup"))
  parser.add_argument("--token")
  args = parser.parse_args()
  if os.geteuid() != 0 or not os.environ.get("SUDO_UID", "").isdigit() or int(os.environ["SUDO_UID"]) == 0:
    raise RuntimeError("run_from_your_normal_user_with_sudo")
  uid, gid = int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
  if args.action == "prepare" and args.token is None:
    prepare(uid, gid)
  elif args.action == "cleanup" and args.token is not None:
    cleanup(uid, args.token)
  else:
    parser.error("cleanup requires --token; prepare does not accept it")


if __name__ == "__main__":
  main()
