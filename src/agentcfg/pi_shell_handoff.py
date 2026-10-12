"""可信父进程到已登记PID1的FD凭证；不签发产品许可，不接RPC或默认factory。

父侧保持原有owner/plan检查，子侧只按受信UID投影核验同FD，不重新打开来源路径。
consumer每进程仅一次尝试（失败也耗尽）；密封memfd自身不防跨进程重放，调用者还
必须以worker出生身份、nonce及单次父gate绑定交接。新worker须来自干净exec。
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
import stat
import sys

from . import pi_shell_execution as execution
from .pi_catalog import validate
from .pi_pid_namespace import local_namespace_identity
from .pi_shell_script import _close_owned
from .schema import ConfigError


_SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
_LIMIT = 256 * 1024
_CHANNELS = {}
_ADOPT_ATTEMPTED = False


def _check(condition):
  if not condition: raise ValueError()


def _closed(value, keys):
  _check(type(value) is dict and set(value) == set(keys))


def _hex(value, length):
  _check(type(value) is str and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None)


def _channel(fd):
  _check(type(fd) is int and fd > 2)
  info = os.fstat(fd)
  _check(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    and info.st_uid == os.geteuid() and info.st_nlink == 0)
  _check(os.readlink("/proc/self/fd/" + str(fd)) == "/memfd:agentcfg-shell-handoff (deleted)")
  return info


@contextmanager
def handoff_channel():
  fd, identity = None, None
  try:
    try:
      _check(sys.platform == "linux")
      fd = os.memfd_create("agentcfg-shell-handoff", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
      info = os.fstat(fd); identity = (info.st_dev, info.st_ino)
      os.fchmod(fd, 0o600)
      _CHANNELS[fd] = {"identity": identity, "used": False}
    except Exception:
      raise ConfigError("pi-shell-handoff") from None
    yield fd
  finally:
    if fd is not None:
      _CHANNELS.pop(fd, None)
      _close_owned(fd, identity)


def authorization_digest(value):
  """只验证受信父侧授权投影的形状；摘要本身不是许可签发。"""
  try:
    _closed(value, ("operation_id", "lease_id", "operation_digest", "allocation_digest", "runtime_identity",
      "lock_identity", "slice_identity", "context_digest", "grant_generation", "profile_id"))
    for key in ("operation_id", "lease_id"): _hex(value[key], 32)
    for key in ("operation_digest", "allocation_digest", "runtime_identity", "lock_identity", "slice_identity", "context_digest"):
      _hex(value[key], 64)
    _check(type(value["grant_generation"]) is int and 1 <= value["grant_generation"] <= 2**53 - 1)
    _check(value["profile_id"] in ("pi-base", "pi-full"))
    from .activity import digest
    return digest(value)
  except Exception:
    raise ConfigError("pi-shell-handoff") from None


def _binding(value, snapshots):
  _check(type(value) is dict and value.get("purpose") in ("shell-probe", "shell-execution"))
  fields = ("purpose", "nonce", "helper_identity", "plan_digest", "worker_identity", "worker_user_namespace", "uid_projection")
  if value["purpose"] == "shell-execution": fields += ("authorization",)
  _closed(value, fields)
  if value["purpose"] == "shell-execution": authorization_digest(value["authorization"])
  _hex(value["nonce"], 32); _hex(value["helper_identity"], 64); _hex(value["plan_digest"], 64)
  worker = value["worker_identity"]
  validate("process-identity", worker)
  _check(worker["platform"] == "linux" and type(worker["uid"]) is int
    and type(worker["pid"]) is int and worker["pid"] > 0
    and type(worker["namespace"]) is str and re.fullmatch(r"pid:\[[0-9]+\]", worker["namespace"]) is not None)
  _check(type(value["worker_user_namespace"]) is str and re.fullmatch(r"user:\[[0-9]+\]", value["worker_user_namespace"]) is not None)
  _check(type(value["uid_projection"]) is list)
  projection = {}
  for row in value["uid_projection"]:
    _closed(row, ("host_uid", "visible_uid"))
    _check(all(type(row[key]) is int and 0 <= row[key] <= 2**32 - 1 for key in row))
    _check(row["host_uid"] not in projection)
    projection[row["host_uid"]] = row["visible_uid"]
  _check({snapshot[2] for _, snapshot in snapshots} <= projection.keys() and worker["uid"] in projection)
  return projection


def _hash(fd):
  _check(0 < os.fstat(fd).st_size <= 64 * 1024 * 1024)
  checksum = hashlib.sha256(); offset = 0
  while block := os.pread(fd, 1024 * 1024, offset):
    checksum.update(block); offset += len(block)
    _check(offset <= 64 * 1024 * 1024)
  return checksum.hexdigest()


def seal_handoff(fd, prepared, binding):
  """一次转移父对象资格；写入或任何复核失败均不得重试。"""
  try:
    entry = _CHANNELS.get(fd)
    _check(entry is not None and not entry["used"])
    entry["used"] = True
    value, prepared_plan_digest = execution._export_prepared(prepared)
    info = _channel(fd)
    _check((info.st_dev, info.st_ino) == entry["identity"] and info.st_size == 0
      and fcntl.fcntl(fd, fcntl.F_GET_SEALS) == 0 and os.lseek(fd, 0, os.SEEK_CUR) == 0)
    _check(fd not in {value.helper_fd, *value.pass_fds})
    _binding(binding, value.snapshots)
    _check(_hash(value.helper_fd) == binding["helper_identity"] and binding["plan_digest"] == prepared_plan_digest)
    execution._verify(value)
    document = {"schema_version": 1, "binding": binding, "argv": list(value.argv), "helper_fd": value.helper_fd,
      "pass_fds": list(value.pass_fds), "script_fd": value.script_fd, "seccomp_fd": value.seccomp_fd,
      "mask_fds": list(value.mask_fds), "snapshots": [[item, list(snapshot)] for item, snapshot in value.snapshots]}
    data = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    _check(1 <= len(data) <= _LIMIT)
    offset = 0
    while offset < len(data):
      try: count = os.write(fd, data[offset:])
      except InterruptedError: continue
      _check(count > 0); offset += count
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, _SEALS)
    _check(fcntl.fcntl(fd, fcntl.F_GET_SEALS) & _SEALS == _SEALS)
    _check(os.lseek(fd, 0, os.SEEK_SET) == 0)
  except Exception:
    raise ConfigError("pi-shell-handoff") from None


def _pairs(items):
  value = {}
  for key, item in items:
    _check(key not in value); value[key] = item
  return value


def _constant(value):
  raise ValueError()


def _argv_roles(value):
  """验证固定编译器的隔离前缀和FD引用；不重新规划挂载或打开来源。"""
  argv = value["argv"]
  prefix = ["--unshare-user", "--disable-userns", "--assert-userns-disabled", "--unshare-pid", "--unshare-net",
    "--unshare-ipc", "--unshare-uts", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
  for name, item in (("HOME", "/.rotom-shell/home"), ("TMPDIR", "/tmp"), ("PATH", "/usr/bin:/bin"),
      ("LANG", "C.UTF-8"), ("LC_ALL", "C.UTF-8"), ("TERM", "dumb")):
    prefix.extend(("--setenv", name, item))
  prefix.extend(("--perms", "0700", "--tmpfs", "/.rotom-shell", "--perms", "0700", "--dir", "/.rotom-shell/home",
    "--perms", "1777", "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev"))
  _check(argv[1:1 + len(prefix)] == prefix)
  cursor, end = 1 + len(prefix), len(argv) - 5
  references, sources, data, filters, chdir = [], [], [], [], []
  arity = {"--symlink": 2, "--bind-fd": 2, "--ro-bind-fd": 2, "--perms": 1,
    "--ro-bind-data": 2, "--seccomp": 1, "--tmpfs": 1, "--remount-ro": 1, "--chdir": 1}
  while cursor < end:
    option = argv[cursor]
    _check(option in arity and cursor + arity[option] < end)
    args = argv[cursor + 1:cursor + arity[option] + 1]
    if option in ("--bind-fd", "--ro-bind-fd", "--ro-bind-data", "--seccomp"):
      _check(re.fullmatch(r"[0-9]+", args[0]) is not None)
      fd = int(args[0]); _check(str(fd) == args[0] and fd > 2); references.append(fd)
      if option == "--seccomp": filters.append(fd)
      elif option == "--ro-bind-data": data.append((fd, args[1]))
      else: sources.append((fd, args[1], option))
    elif option == "--perms": _check(args[0] in ("0400", "0000"))
    elif option == "--chdir":
      _check(cursor + 2 == end); chdir.append(args[0])
    cursor += arity[option] + 1
  _check(cursor == end and len(chdir) == 1)
  _check(len(set(references)) == len(references) and set(references) == set(value["pass_fds"]))
  _check(filters == [value["seccomp_fd"]])
  _check(data and data[0] == (value["script_fd"], "/.rotom-shell/script")
    and {fd for fd, _ in data[1:]} == set(value["mask_fds"]))
  _check(any(path == argv[-4] and option == "--ro-bind-fd" for _, path, option in sources))
  _check({fd for fd, _, _ in sources} == set(value["pass_fds"]) - {
    value["script_fd"], value["seccomp_fd"], *value["mask_fds"]})


def _document(raw):
  value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_constant)
  _closed(value, ("schema_version", "binding", "argv", "helper_fd", "pass_fds", "script_fd", "seccomp_fd", "mask_fds", "snapshots"))
  _check(type(value["schema_version"]) is int and value["schema_version"] == 1)
  _check(type(value["argv"]) is list and len(value["argv"]) >= 6
    and all(type(arg) is str and arg and "\0" not in arg and not any(0xD800 <= ord(c) <= 0xDFFF for c in arg) for arg in value["argv"]))
  _check(value["argv"][-5] == "--" and value["argv"][-3:] == ["--noprofile", "--norc", "/.rotom-shell/script"])
  for key in ("pass_fds", "mask_fds", "snapshots"): _check(type(value[key]) is list)
  roles = (value["helper_fd"], *value["pass_fds"])
  _check(all(type(fd) is int and fd > 2 for fd in roles) and len(set(roles)) == len(roles))
  data_fds = (value["script_fd"], value["seccomp_fd"], *value["mask_fds"])
  _check(all(type(fd) is int and fd > 2 for fd in data_fds) and len(set(data_fds)) == len(data_fds)
    and set(data_fds) <= set(value["pass_fds"]))
  snapshots = []
  for row in value["snapshots"]:
    _check(type(row) is list and len(row) == 2 and type(row[0]) is int and type(row[1]) is list and len(row[1]) == 8)
    _check(all(type(item) is int and item >= 0 for item in row[1]))
    snapshots.append((row[0], tuple(row[1])))
  _check(tuple(fd for fd, _ in snapshots) == roles)
  _argv_roles(value)
  return value, tuple(snapshots)


@contextmanager
def adopt_handoff(fd, *, nonce, helper_identity, plan_digest, expected_authorization=None):
  """仅供受信PID1一次交接；退出关闭核验所属FD，拒绝错误身份与重放。"""
  global _ADOPT_ATTEMPTED
  owned = []; channel_identity = None
  try:
    try:
      _check(not _ADOPT_ATTEMPTED); _ADOPT_ATTEMPTED = True
      info = _channel(fd); channel_identity = (info.st_dev, info.st_ino)
      _hex(nonce, 32); _hex(helper_identity, 64); _hex(plan_digest, 64)
      execution._require_worker_context()
      _check(1 <= info.st_size <= _LIMIT and fcntl.fcntl(fd, fcntl.F_GET_SEALS) & _SEALS == _SEALS)
      raw = os.pread(fd, _LIMIT + 1, 0)
      _check(len(raw) == info.st_size)
      document, snapshots = _document(raw)
      _check(fd not in {document["helper_fd"], *document["pass_fds"]})
      binding = document["binding"]; projection = _binding(binding, snapshots)
      if expected_authorization is None:
        _check(binding["purpose"] == "shell-probe")
      else:
        _hex(expected_authorization, 64)
        _check(binding["purpose"] == "shell-execution"
          and authorization_digest(binding["authorization"]) == expected_authorization)
      _check(binding["nonce"] == nonce and binding["helper_identity"] == helper_identity and binding["plan_digest"] == plan_digest)
      actual = local_namespace_identity()
      expected = binding["worker_identity"]
      _check(actual.get("platform") == "linux" and actual.get("pid") == 1
        and all(actual.get(key) == expected[key] for key in ("boot_id", "start_time", "namespace"))
        and actual.get("uid") == os.geteuid() == projection[expected["uid"]]
        and os.readlink("/proc/self/ns/user") == binding["worker_user_namespace"])
      projected = []
      for descriptor, original in snapshots:
        snapshot = (*original[:2], projection[original[2]], *original[3:])
        current = execution._snapshot(os.fstat(descriptor))
        _check(current == snapshot)
        owned.append((descriptor, snapshot[:2])); projected.append((descriptor, snapshot))
      value = execution.PreparedShellExecution(argv=tuple(document["argv"]), helper_fd=document["helper_fd"],
        pass_fds=tuple(document["pass_fds"]), script_fd=document["script_fd"], seccomp_fd=document["seccomp_fd"],
        mask_fds=tuple(document["mask_fds"]), snapshots=tuple(projected))
      _check(_hash(value.helper_fd) == helper_identity)
      execution._verify(value)
      for descriptor, _ in owned: os.set_inheritable(descriptor, False)
      _close_owned(fd, channel_identity); channel_identity = None
    except Exception:
      raise ConfigError("pi-shell-handoff") from None
    with execution._adopt_prepared(value, plan_digest=plan_digest): yield value
  finally:
    for descriptor, identity in reversed(owned): _close_owned(descriptor, identity)
    if channel_identity is not None: _close_owned(fd, channel_identity)
