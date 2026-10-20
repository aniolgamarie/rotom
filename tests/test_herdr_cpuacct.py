"""仅使用临时假内核树，不向真实 cgroup 写入。"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("herdr_cpuacct", ROOT / "tools/bench/cpuacct.py")
cpu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cpu)


@pytest.fixture
def kernel(tmp_path, monkeypatch):
  source = tmp_path / "mount"
  source.mkdir()
  token = "a" * 32
  scope = source / ("rotom-bench-" + token)
  scope.mkdir()
  roles = {}
  root_owned = {source, scope}
  for role in cpu.ROLES:
    directory = scope / role
    directory.mkdir()
    root_owned.add(directory)
    for name in ("cgroup.procs", "cpuacct.usage_user", "cpuacct.usage_sys"):
      path = directory / name
      path.write_bytes(b"" if name == "cgroup.procs" else b"123\n")
      path.chmod(0o600 if name == "cgroup.procs" else 0o444)
      if name != "cgroup.procs":
        root_owned.add(path)
    info = directory.stat()
    roles[role] = {"dev": info.st_dev, "ino": info.st_ino}
  receipt = tmp_path / "receipt.json"
  info = scope.stat()
  value = {"schema_version": 1, "method": "cpuacct-v1", "uid": os.getuid(),
    "boot_id": "12345678-1234-1234-1234-123456789abc", "source_cgroup": "/source",
    "scope_path": str(scope), "scope_dev": info.st_dev, "scope_ino": info.st_ino,
    "roles": roles, "admin_token": token}
  receipt.write_text(json.dumps(value))
  receipt.chmod(0o600)
  actual_fstat = os.fstat
  bad_owners = set()
  def fstat(fd):
    info = actual_fstat(fd)
    path = Path(os.readlink(f"/proc/self/fd/{fd}"))
    if path in root_owned or path in bad_owners:
      fields = list(info)
      fields[4] = os.getuid() + 1 if path in bad_owners else 0
      return os.stat_result(fields)
    return info
  monkeypatch.setattr(cpu.os, "fstat", fstat)
  monkeypatch.setattr(cpu, "_statfs", lambda fd: cpu.CGROUP_SUPER_MAGIC)
  monkeypatch.setattr(cpu, "_boot_id", lambda: "12345678-1234-1234-1234-123456789abc")
  monkeypatch.setattr(cpu, "_mount", lambda source: str(tmp_path / "mount"))
  current = ["/source"]
  monkeypatch.setattr(cpu, "_current", lambda: current[0])
  monkeypatch.setattr(cpu, "_single_thread", lambda: True)
  writes = []
  def write(fd, data):
    path = Path(os.readlink(f"/proc/self/fd/{fd}"))
    assert path.parent.parent == scope
    assert path.name == "cgroup.procs"
    assert data == b"0"
    writes.append((path.parent.name, data))
    current[0] = "/source/" + scope.name + "/" + path.parent.name
    return len(data)
  monkeypatch.setattr(cpu.os, "write", write)
  return {"receipt": receipt, "value": value, "scope": scope, "source": source,
    "current": current, "writes": writes, "bad_owners": bad_owners}


def save(kernel):
  kernel["receipt"].write_text(json.dumps(kernel["value"]))


def test_counts_and_closure(kernel):
  groups = cpu.CpuacctGroups(kernel["receipt"])
  fds = list(groups._fds)
  snapshot = groups.read()
  assert snapshot == {role: {"user_ns": 123, "system_ns": 123} for role in cpu.ROLES}
  snapshot["server"]["user_ns"] = 999999
  path = kernel["scope"] / "server/cpuacct.usage_user"
  path.chmod(0o644)
  path.write_text("124\n")
  path.chmod(0o444)
  assert groups.read()["server"]["user_ns"] == 124
  groups.close()
  groups.close()
  for fd in fds:
    with pytest.raises(OSError):
      os.fstat(fd)
  with pytest.raises(cpu.CpuacctError, match="cpuacct_closed"):
    groups.read()
  assert kernel["scope"].exists()


@pytest.mark.parametrize("mutation", ["unknown", "uid", "bool", "source", "scope", "boot", "roles"])
def test_invalid_receipts(kernel, mutation):
  value = kernel["value"]
  if mutation == "unknown":
    value["unknown"] = 0
  elif mutation == "uid":
    value["uid"] += 1
  elif mutation == "bool":
    value["scope_dev"] = True
  elif mutation == "source":
    value["source_cgroup"] = "/different"
  elif mutation == "scope":
    value["scope_path"] += "-different"
  elif mutation == "boot":
    value["boot_id"] = "invalid"
  else:
    value["roles"]["server"]["unknown"] = 1
  save(kernel)
  with pytest.raises(cpu.CpuacctError):
    cpu.CpuacctGroups(kernel["receipt"])
  assert not kernel["writes"]


@pytest.mark.parametrize("raw", ['{"schema_version":1,"schema_version":1}', '{"value":NaN}', '[]', '{}'])
def test_invalid_json(kernel, raw):
  kernel["receipt"].write_text(raw)
  with pytest.raises(cpu.CpuacctError):
    cpu.CpuacctGroups(kernel["receipt"])


@pytest.mark.parametrize("kind", ["receipt_symlink", "receipt_hardlink", "receipt_mode", "directory_symlink", "file_symlink", "wrong_uid", "wrong_fs"])
def test_unsafe_kernel_inputs(kernel, monkeypatch, kind):
  receipt = kernel["receipt"]
  target = kernel["scope"] / "server"
  if kind == "receipt_symlink":
    original = receipt.with_suffix(".original")
    receipt.rename(original)
    receipt.symlink_to(original)
  elif kind == "receipt_hardlink":
    os.link(receipt, receipt.with_suffix(".link"))
  elif kind == "receipt_mode":
    receipt.chmod(0o644)
  elif kind == "directory_symlink":
    moved = target.with_name("saved")
    target.rename(moved)
    target.symlink_to(moved)
  elif kind == "file_symlink":
    path = target / "cpuacct.usage_user"
    path.unlink()
    path.symlink_to(target / "cpuacct.usage_sys")
  elif kind == "wrong_uid":
    kernel["bad_owners"].add(target)
  else:
    monkeypatch.setattr(cpu, "_statfs", lambda fd: 0)
  with pytest.raises(cpu.CpuacctError):
    cpu.CpuacctGroups(receipt)


@pytest.mark.parametrize("which", ["scope", "role", "counter"])
def test_replacement_rejected(kernel, which):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    path = kernel["scope"]
    if which == "role":
      path /= "server"
    elif which == "counter":
      path /= "server/cpuacct.usage_user"
    path.rename(path.with_name(path.name + "-old"))
    if which == "counter":
      path.write_text("999")
    else:
      path.mkdir()
    with pytest.raises(cpu.CpuacctError, match="cpuacct_replaced"):
      groups.read()


@pytest.mark.parametrize("counter", ["-1\n", "+1\n", "1.0", "1\n2", "", "1" * 129])
def test_bad_counter(kernel, counter):
  path = kernel["scope"] / "server/cpuacct.usage_sys"
  path.chmod(0o644)
  path.write_text(counter)
  path.chmod(0o444)
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    with pytest.raises(cpu.CpuacctError, match="cpuacct_counter"):
      groups.read()


def test_counter_regression(kernel):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    groups.read()
    path = kernel["scope"] / "server/cpuacct.usage_sys"
    path.chmod(0o644)
    path.write_text("122\n")
    path.chmod(0o444)
    with pytest.raises(cpu.CpuacctError, match="cpuacct_counter_regressed"):
      groups.read()


def test_spawn_exception_restores_driver_and_only_writes_zero(kernel):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    with pytest.raises(RuntimeError, match="popen_failed"):
      with groups.spawn("server"):
        assert kernel["current"][0].endswith("/server")
        raise RuntimeError("popen_failed")
    assert kernel["current"][0].endswith("/driver")
    with groups.spawn("client"):
      pass
  assert kernel["writes"] == [(role, b"0") for role in ("server", "driver", "client", "driver")]


def test_spawn_rejects_threads_before_move(kernel, monkeypatch):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    monkeypatch.setattr(cpu, "_single_thread", lambda: False)
    with pytest.raises(cpu.CpuacctError, match="cpuacct_threads"):
      with groups.spawn("server"):
        pytest.fail("must not spawn")
  assert kernel["writes"] == []


def test_migration_from_unrelated_group_rejected(kernel):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    kernel["current"][0] = "/unrelated"
    with pytest.raises(cpu.CpuacctError, match="cpuacct_source"):
      groups.join_self("driver")
  assert not kernel["writes"]


def test_producer_only_moves_itself_from_server_or_producer(kernel, monkeypatch):
  monkeypatch.setattr(cpu, "_single_thread", lambda: False)
  with pytest.raises(cpu.CpuacctError, match="cpuacct_source"):
    cpu.join_producer(kernel["receipt"])
  kernel["current"][0] = "/source/" + kernel["scope"].name + "/server"
  cpu.join_producer(kernel["receipt"])
  cpu.join_producer(kernel["receipt"])
  assert kernel["writes"] == [("producer", b"0"), ("producer", b"0")]


def test_failed_construction_closes_fds(kernel, monkeypatch):
  actual_open, actual_close = os.open, os.close
  opened, closed = [], []
  def track_open(*args, **kwargs):
    fd = actual_open(*args, **kwargs)
    opened.append(fd)
    return fd
  def track_close(fd):
    closed.append(fd)
    return actual_close(fd)
  monkeypatch.setattr(cpu.os, "open", track_open)
  monkeypatch.setattr(cpu.os, "close", track_close)
  kernel["value"]["roles"]["client"]["ino"] += 1
  save(kernel)
  with pytest.raises(cpu.CpuacctError):
    cpu.CpuacctGroups(kernel["receipt"])
  assert sorted(opened) == sorted(closed)


def test_proc_controller_binding_and_mount_root(monkeypatch):
  import io
  sources = {
    "/proc/self/cgroup": "8:memory:/unrelated\n7:cpu,cpuacct:/parent/source\n0::/unified\n",
    "/proc/self/mountinfo": "29 20 0:27 /parent /fake/cpu\\040account rw,nosuid - cgroup cgroup rw,cpu,cpuacct\n",
  }
  monkeypatch.setattr(cpu, "open", lambda path, **kwargs: io.StringIO(sources[path]), raising=False)
  assert cpu._current() == "/parent/source"
  assert cpu._mount("/parent/source") == "/fake/cpu account/source"
  assert cpu._mount("/parent") == "/fake/cpu account"
  with pytest.raises(cpu.CpuacctError, match="cpuacct_mount"):
    cpu._mount("/different")
  sources["/proc/self/cgroup"] = "0::/unified\n"
  with pytest.raises(cpu.CpuacctError, match="cpuacct_controller"):
    cpu._current()
  sources["/proc/self/cgroup"] = "7:cpuacct:/one\n8:cpuacct:/two\n"
  with pytest.raises(cpu.CpuacctError, match="cpuacct_controller"):
    cpu._current()


def test_usage_permissions_rechecked(kernel):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    (kernel["scope"] / "server/cpuacct.usage_sys").chmod(0o644)
    with pytest.raises(cpu.CpuacctError, match="cpuacct_file_permissions"):
      groups.read()


def test_invalid_role_cannot_write_pid(kernel):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    with pytest.raises(cpu.CpuacctError, match="cpuacct_role"):
      groups.join_self("1234")
  assert not kernel["writes"]


@pytest.mark.parametrize("target", ["receipt", "procs", "usage"])
def test_file_owner_rejected(kernel, target):
  path = {"receipt": kernel["receipt"],
    "procs": kernel["scope"] / "server/cgroup.procs",
    "usage": kernel["scope"] / "server/cpuacct.usage_user"}[target]
  kernel["bad_owners"].add(path)
  with pytest.raises(cpu.CpuacctError):
    cpu.CpuacctGroups(kernel["receipt"])


def test_boot_identity_mismatch(kernel):
  kernel["value"]["boot_id"] = "87654321-4321-4321-4321-123456789abc"
  save(kernel)
  with pytest.raises(cpu.CpuacctError, match="cpuacct_boot"):
    cpu.CpuacctGroups(kernel["receipt"])


def test_members_use_pinned_kernel_files_and_readonly_identity(kernel, monkeypatch):
  path = kernel["scope"] / "server/cgroup.procs"
  path.write_text("17\n18\n")
  monkeypatch.setattr(cpu, "_member_identity", lambda pid, group: {"pid": pid, "starttime": pid * 100}, raising=False)
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    assert groups.members()["server"] == [{"pid": 17, "starttime": 1700}, {"pid": 18, "starttime": 1800}]
    assert not kernel["writes"]
    path.unlink()
    path.write_text("19\n")
    with pytest.raises(cpu.CpuacctError, match="cpuacct_replaced"):
      groups.members()


def test_fixed_procs_fd_rewound_before_every_write(kernel):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    fd = groups._roles["driver"][1]["cgroup.procs"]
    os.lseek(fd, 9, os.SEEK_SET)
    groups.join_self("driver")
    assert os.lseek(fd, 0, os.SEEK_CUR) == 0


def descriptor_view(monkeypatch, groups, extra=()):
  actual = cpu.os.listdir
  names = ["0", "1", "2", *[str(fd) for fd in groups._fds], *[str(fd) for fd in extra]]
  monkeypatch.setattr(cpu.os, "listdir", lambda path: names if path == "/proc/self/fd" else actual(path))
  return names


def test_driver_descriptor_audit_only_allows_fixed_noninheritable_group_fds(kernel, monkeypatch):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    descriptor_view(monkeypatch, groups)
    assert len(groups._fds) == 18
    assert groups.check_driver_descriptors() is None
    assert all(not os.get_inheritable(fd) for fd in groups._fds)
  assert not kernel["writes"]


@pytest.mark.parametrize("kind", ["regular", "socket", "duplicate"])
def test_driver_descriptor_audit_rejects_unknown_live_fds(kernel, monkeypatch, tmp_path, kind):
  import stat
  from types import SimpleNamespace
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    unknown = tmp_path / "unknown-file"
    unknown.write_bytes(b"synthetic")
    extra = os.dup(groups._fds[0]) if kind == "duplicate" else os.open(unknown, os.O_RDONLY)
    try:
      descriptor_view(monkeypatch, groups, [extra])
      if kind == "socket":
        actual = cpu.os.fstat
        monkeypatch.setattr(cpu.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFSOCK) if fd == extra else actual(fd))
      with pytest.raises(cpu.CpuacctError):
        groups.check_driver_descriptors()
      os.fstat(extra)  # 审计不会擅自关闭任何未知描述符。
    finally:
      os.close(extra)


@pytest.mark.parametrize("kind", ["inheritable", "closed", "replaced", "missing_registry", "duplicate_registry", "missing_scan", "stat_error"])
def test_driver_descriptor_audit_rejects_changed_or_incomplete_fds(kernel, monkeypatch, kind):
  import errno
  groups = cpu.CpuacctGroups(kernel["receipt"])
  originals = list(groups._fds)
  names = descriptor_view(monkeypatch, groups)
  try:
    fd = groups._roles["server"][1]["cpuacct.usage_user"]
    if kind == "inheritable":
      os.set_inheritable(fd, True)
    elif kind == "closed":
      os.close(fd)
    elif kind == "replaced":
      path = kernel["scope"] / "server/cpuacct.usage_user"
      path.rename(path.with_name("saved"))
      path.write_text("123\n")
      path.chmod(0o444)
    elif kind == "missing_registry":
      groups._fds.pop()
    elif kind == "duplicate_registry":
      groups._fds.append(fd)
    elif kind == "missing_scan":
      names.remove(str(fd))
    else:
      names.append("99999")
      actual = cpu.os.fstat
      def fstat(value):
        if value == 99999:
          raise OSError(errno.EACCES, "synthetic denied")
        return actual(value)
      monkeypatch.setattr(cpu.os, "fstat", fstat)
    with pytest.raises(cpu.CpuacctError):
      groups.check_driver_descriptors()
  finally:
    groups._fds = originals
    if kind == "closed":
      groups._fds.remove(fd)
    groups.close()


def test_driver_descriptor_audit_only_ignores_disappeared_enumeration_fd(kernel, monkeypatch):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    ghost = max(groups._fds) + 10000
    descriptor_view(monkeypatch, groups, [ghost])
    assert groups.check_driver_descriptors() is None


def fake_member_read_once(fd, content):
  if os.lseek(fd, 0, os.SEEK_CUR):
    return b""
  os.lseek(fd, max(1, len(content)), os.SEEK_SET)
  return content


def test_case_empty_wait_reads_only_target_role_fresh_fds_and_keeps_driver(kernel, monkeypatch):
  clock, sleeps, reads = [0.0], [], []
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    fixed = set(groups._fds)
    def read(fd, size):
      assert fd not in fixed and 0 < size <= 131073
      path = Path(os.readlink(f"/proc/self/fd/{fd}"))
      assert path.name == "cgroup.procs" and path.parent.name in {"server", "client", "producer"}
      reads.append(fd)
      return fake_member_read_once(fd, b"123\n" if clock[0] < 0.02 else b"")
    def sleep(seconds):
      sleeps.append(seconds)
      clock[0] += seconds
    monkeypatch.setattr(cpu.os, "read", read)
    monkeypatch.setattr(cpu.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cpu.time, "sleep", sleep)
    monkeypatch.setattr(cpu, "_member_identity", lambda *args: pytest.fail("cleanup must not inspect exiting PID"))
    monkeypatch.setattr(groups, "_write", lambda *args: pytest.fail("cleanup is read only"))
    monkeypatch.setattr(cpu.os, "kill", lambda *args: pytest.fail("cleanup cannot signal"))
    (kernel["scope"] / "driver/cgroup.procs").write_text("999\n")
    assert groups.wait_case_empty() is None
    assert sleeps == [0.01, 0.01] and len(reads) == 15
    assert (kernel["scope"] / "driver/cgroup.procs").read_text() == "999\n"
    assert not kernel["writes"]


def test_case_empty_wait_persistent_members_timeout_is_bounded(kernel, monkeypatch):
  clock, sleeps = [0.0], []
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    monkeypatch.setattr(cpu.os, "read", lambda fd, size: fake_member_read_once(fd, b"123\n"))
    monkeypatch.setattr(cpu.time, "monotonic", lambda: clock[0])
    def sleep(seconds):
      sleeps.append(seconds)
      clock[0] += seconds
    monkeypatch.setattr(cpu.time, "sleep", sleep)
    with pytest.raises(cpu.CpuacctError, match="cpuacct_case_cleanup_timeout"):
      groups.wait_case_empty(timeout=0.025)
    assert clock[0] == 0.025 and sleeps == [0.01, 0.01, pytest.approx(0.005)]


@pytest.mark.parametrize("fault", ["format", "duplicate", "overflow", "read", "fd", "permissions"])
def test_case_empty_wait_faults_never_retry(kernel, monkeypatch, fault):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    reads = []
    def read(fd, size):
      reads.append(fd)
      if fault == "read":
        raise OSError("synthetic failure")
      if fault == "overflow":
        return b"1\n" * 65537
      return fake_member_read_once(fd, b"123\n123\n" if fault == "duplicate" else b"bad\n")
    monkeypatch.setattr(cpu.os, "read", read)
    monkeypatch.setattr(cpu.time, "sleep", lambda *args: pytest.fail("fault must not retry"))
    if fault == "fd":
      path = kernel["scope"] / "server/cgroup.procs"
      path.rename(path.with_name("saved-procs"))
      path.write_bytes(b"")
      path.chmod(0o600)
    elif fault == "permissions":
      (kernel["scope"] / "producer/cgroup.procs").chmod(0o644)
    with pytest.raises(cpu.CpuacctError):
      groups.wait_case_empty()
    assert len(reads) == (0 if fault in {"fd", "permissions"} else 2 if fault in {"format", "duplicate"} else 1)


@pytest.mark.parametrize("timeout", [0, -1, 6, True, float("inf"), float("nan"), 10**400])
def test_case_empty_wait_invalid_timeout_never_reads(kernel, monkeypatch, timeout):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    monkeypatch.setattr(cpu.os, "read", lambda *args: pytest.fail("invalid timeout cannot read"))
    with pytest.raises(cpu.CpuacctError):
      groups.wait_case_empty(timeout=timeout)


def test_case_empty_wait_cannot_accept_late_empty_read(kernel, monkeypatch):
  clock = [0.0]
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    monkeypatch.setattr(cpu.time, "monotonic", lambda: clock[0])
    def late_empty(*args):
      clock[0] = 6.0
      return b""
    monkeypatch.setattr(cpu.os, "read", late_empty)
    monkeypatch.setattr(cpu.time, "sleep", lambda *args: pytest.fail("late read cannot retry"))
    with pytest.raises(cpu.CpuacctError, match="cpuacct_case_cleanup_timeout"):
      groups.wait_case_empty()


def test_fresh_member_reads_bypass_fixed_fd_cache_and_close_before_audit(kernel, monkeypatch):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    fixed = set(groups._fds)
    procs = {files["cgroup.procs"] for directory, files in groups._roles.values()}
    current = {role: b"" for role in cpu.ROLES}
    opened, closed, fresh = [], [], {}
    actual_open, actual_close, actual_read, actual_pread = cpu.os.open, cpu.os.close, cpu.os.read, cpu.os.pread
    def open_file(name, flags, *, dir_fd=None):
      fd = actual_open(name, flags, dir_fd=dir_fd)
      if name == "cgroup.procs":
        assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC and flags & os.O_ACCMODE == os.O_RDONLY
        role = next(role for role, (directory, _) in groups._roles.items() if directory == dir_fd)
        fresh[fd] = current[role]
        opened.append((fd, role))
      return fd
    def close(fd):
      if fd in fresh:
        closed.append(fd)
        del fresh[fd]
      actual_close(fd)
    def read(fd, count):
      if fd in fresh:
        assert fd not in fixed and 0 < count <= 131073
        chunk, fresh[fd] = fresh[fd], b""
        return chunk
      return actual_read(fd, count)
    monkeypatch.setattr(cpu.os, "open", open_file)
    monkeypatch.setattr(cpu.os, "close", close)
    monkeypatch.setattr(cpu.os, "read", read)
    monkeypatch.setattr(cpu.os, "pread", lambda fd, size, offset: b"" if fd in procs else actual_pread(fd, size, offset))
    def member_identity(pid, group):
      assert not fresh
      return {"pid": pid, "starttime": 100}
    monkeypatch.setattr(cpu, "_member_identity", member_identity)
    assert all(not rows for rows in groups.members().values())
    current.update(server=b"17\n", driver=b"18\n")
    assert groups.members()["server"] == [{"pid": 17, "starttime": 100}]
    assert os.pread(groups._roles["server"][1]["cgroup.procs"], 131073, 0) == b""
    assert len(opened) == len(closed) == 8 and not fresh
    assert set(groups._fds) == fixed and len(groups._fds) == 18
    descriptor_view(monkeypatch, groups)
    groups.check_driver_descriptors()
    assert not kernel["writes"]


@pytest.mark.parametrize("fault", ["symlink", "replaced", "replaced_after_read", "permissions", "uid", "not_regular", "filesystem", "format", "read", "short_read_error"])
def test_fresh_member_fault_closes_temporary_fd_without_retry(kernel, monkeypatch, fault):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    opened, closed, consumed = [], [], set()
    actual_open, actual_close, actual_read, actual_fstat = cpu.os.open, cpu.os.close, cpu.os.read, cpu.os.fstat
    path = kernel["scope"] / "server/cgroup.procs"
    def open_file(name, flags, *, dir_fd=None):
      if name == "cgroup.procs" and fault == "symlink":
        path.rename(path.with_name("saved-procs"))
        path.symlink_to(path.with_name("saved-procs"))
      fd = actual_open(name, flags, dir_fd=dir_fd)
      if name == "cgroup.procs":
        opened.append(fd)
        if fault == "permissions":
          path.chmod(0o644)
        elif fault == "replaced":
          path.rename(path.with_name("saved-procs"))
          path.write_bytes(b"")
          path.chmod(0o600)
      return fd
    def close(fd):
      if fd in opened:
        closed.append(fd)
      actual_close(fd)
    def read(fd, count):
      if fd in opened:
        if fault == "read" or fault == "short_read_error" and fd in consumed:
          raise OSError("synthetic denied")
        if fault in {"format", "short_read_error"}:
          if fd in consumed:
            return b""
          consumed.add(fd)
          return b"17\n17\n" if fault == "format" else b"17\n"
        if fault == "replaced_after_read":
          path.rename(path.with_name("saved-procs"))
          path.write_bytes(b"")
          path.chmod(0o600)
      return actual_read(fd, count)
    def fstat(fd):
      info = actual_fstat(fd)
      if fd in opened and fault in {"uid", "not_regular"}:
        fields = list(info)
        if fault == "uid":
          fields[4] = os.getuid() + 1
        else:
          import stat
          fields[0] = stat.S_IFDIR | 0o600
        return os.stat_result(fields)
      return info
    monkeypatch.setattr(cpu.os, "open", open_file)
    monkeypatch.setattr(cpu.os, "close", close)
    monkeypatch.setattr(cpu.os, "read", read)
    monkeypatch.setattr(cpu.os, "fstat", fstat)
    monkeypatch.setattr(cpu, "_statfs", lambda fd: 0 if fault == "filesystem" and fd in opened else cpu.CGROUP_SUPER_MAGIC)
    monkeypatch.setattr(cpu.time, "sleep", lambda *args: pytest.fail("fresh reader faults cannot retry"))
    with pytest.raises(cpu.CpuacctError):
      groups.wait_case_empty()
    assert len(opened) == len(closed) == (0 if fault == "symlink" else 1)


def test_fresh_member_reader_requires_eof_and_collects_split_pids(kernel, monkeypatch):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    reads, chunks, opened = [], [b"17", b"\n18", b"\n", b""], []
    actual_open = cpu.os.open
    def open_file(name, flags, *, dir_fd=None):
      fd = actual_open(name, flags, dir_fd=dir_fd)
      opened.append(fd)
      return fd
    def read(fd, count):
      reads.append(count)
      return chunks.pop(0)
    monkeypatch.setattr(cpu.os, "open", open_file)
    monkeypatch.setattr(cpu.os, "read", read)
    assert groups._member_pids("server") == [17, 18]
    assert reads == [131073, 131071, 131068, 131067] and not chunks
    assert len(opened) == 1
    with pytest.raises(OSError):
      os.fstat(opened[0])


def test_fresh_member_reader_bounds_total_across_short_reads(kernel, monkeypatch):
  with cpu.CpuacctGroups(kernel["receipt"]) as groups:
    chunks = [b"1\n" * 32768, b"1\n" * 32768, b"1"]
    reads = []
    def read(fd, count):
      reads.append(count)
      return chunks.pop(0)
    monkeypatch.setattr(cpu.os, "read", read)
    with pytest.raises(cpu.CpuacctError, match="cpuacct_members"):
      groups._member_pids("server")
    assert reads == [131073, 65537, 1] and not chunks
