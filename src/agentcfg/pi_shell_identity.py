"""父侧读取子userns映射；其坐标相对读取者，来源身份仍由调用方固定。"""

import os
import re

from .schema import ConfigError


def _require(value):
  if not value: raise ConfigError("pi-shell-identity")


def parse_uid_map(raw):
  _require(type(raw) is str and 0 < len(raw) <= 16384 and raw.isascii())
  rows = []
  for line in raw.splitlines():
    _require(re.fullmatch(r"[ \t]*[0-9]+[ \t]+[0-9]+[ \t]+[0-9]+[ \t]*", line))
    inside, outside, count = map(int, line.split())
    # Linux有意不映射(uid_t)-1；溢出或重叠的映射不能成为凭证。
    _require(count > 0 and inside + count <= 2**32 - 1 and outside + count <= 2**32 - 1)
    rows.append((inside, outside, count))
  _require(0 < len(rows) <= 340)
  for column in (0, 1):
    ordered = sorted(rows, key=lambda row: row[column])
    _require(all(left[column] + left[2] <= right[column] for left, right in zip(ordered, ordered[1:])))
  return rows


def project_uid(uid, rows, overflow):
  _require(type(uid) is int and 0 <= uid < 2**32 - 1)
  for inside, outside, count in rows:
    if outside <= uid < outside + count: return inside + uid - outside
  return overflow


def _read(path, limit):
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
  try:
    data = b""
    while block := os.read(fd, limit + 1 - len(data)):
      data += block
      _require(len(data) <= limit)
    _require(data)
    return data.decode("ascii", errors="strict")
  finally: os.close(fd)


def identity_projection(execution, *, processes, leader):
  """稳定出生身份与namespace复核前后均成功，才返回parent-reader UID投影。"""
  _require(processes.observe(leader) == "alive")
  own_namespace = os.readlink("/proc/self/ns/user")
  prefix = "/proc/" + str(leader["pid"])
  namespace = os.readlink(prefix + "/ns/user")
  _require(namespace != own_namespace)
  raw = _read(prefix + "/uid_map", 16384)
  rows = parse_uid_map(raw)
  overflow_raw = _read("/proc/sys/kernel/overflowuid", 32)
  _require(re.fullmatch(r"[0-9]+\n?", overflow_raw))
  overflow = int(overflow_raw); _require(0 <= overflow < 2**32 - 1)
  uids = {snapshot[2] for _, snapshot in execution.snapshots} | {leader["uid"], 0, os.geteuid()}
  projection = {uid: project_uid(uid, rows, overflow) for uid in uids}
  _require(processes.observe(leader) == "alive"
    and os.readlink("/proc/self/ns/user") == own_namespace
    and os.readlink(prefix + "/ns/user") == namespace
    and _read(prefix + "/uid_map", 16384) == raw)
  return {"reader_user_namespace": own_namespace, "worker_user_namespace": namespace,
    "parent_read_uid_map": raw, "overflow_uid": overflow,
    "uid_projection": [{"host_uid": uid, "visible_uid": projection[uid]} for uid in sorted(projection)]}
