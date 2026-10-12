"""原生只读观察的临时账户测试；不读取真实账户或启动宿主。"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
import hashlib
import os
import pwd
import stat
import traceback

import pytest

from agentcfg import pi_durable_service_index_readonly as reader
from agentcfg import pi_durable_service_index as codec
from agentcfg.deployment import json_bytes
from agentcfg.pi_durable_registration_record import DirectoryIdentity
from agentcfg.storage import Conflict


SECRET = "SYNTHETIC_PRIVATE_SOURCE"
LIMIT = 16 * 1024 * 1024


def invalid(action=reader.inspect_service_index):
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Conflict) as caught: action()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable服务索引无法安全读取",)
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def directory(path):
  info = path.stat()
  return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}


def passwd(uid, home):
  return pwd.struct_passwd(("synthetic-account", "x", uid, os.getegid(), "", str(home), ""))


def wire(home, control, stage="reserved"):
  result = {"schema": 1, "platform": "linux", "account_home": str(home),
    "account_identity": directory(home), "index_identity": directory(control), "generation": 17,
    "services": [], "associations": []}
  for number in (1, 2):
    binding = {"machine": "fixture", "local": str(home / "local.toml"), "profile": "pi-full"}
    instance, state = str(home / f"instance{number}"), str(home / f"state{number}")
    record = {"schema": 1, "platform": "linux", "service_id": f"{number:064x}", "stage": stage,
      "account_home": str(home), "account_identity": directory(home), "index_identity": directory(control),
      "initial_binding": binding, "initial_instance": instance, "initial_state_root": state,
      "storage_path": state + "/durable/storage", "storage_identity": None if stage == "reserved" else {"device": 0, "inode": 1},
      "initial_deployment_identity": "a" * 64}
    result["services"].append({"registration": record, "initialization_request_id": f"{number:064x}", "initialization_identity": "b" * 64})
    for suffix in ("", "/alias"):
      projection = {"schema": 1, "kind": "pi-durable-service-association", "binding": deepcopy(binding),
        "instance": instance + suffix, "state_root": state + suffix}
      result["associations"].append({"association_id": hashlib.sha256(json_bytes(projection)).hexdigest(),
        "binding": deepcopy(binding), "instance": instance + suffix, "state_root": state + suffix, "service_id": record["service_id"]})
  return result


@pytest.fixture
def account(tmp_path, monkeypatch):
  home = tmp_path / "account"
  home.mkdir(mode=0o700)
  uid = os.geteuid()
  monkeypatch.setattr(reader, "_getpwuid", lambda requested: passwd(uid, home))
  monkeypatch.setattr(reader, "_geteuid", lambda: uid)
  monkeypatch.setattr(reader, "_PLATFORM", "linux")
  return {"home": home, "uid": uid, "control": home / ".agentcfg-pi-durable", "file": home / ".agentcfg-pi-durable" / "index.json"}


def publish(account, stage="reserved"):
  account["control"].mkdir(mode=0o700, exist_ok=True)
  data = wire(account["home"], account["control"], stage)
  raw = codec.encode_service_index(codec.capture_service_index(data))
  account["file"].write_bytes(raw); account["file"].chmod(0o600)
  return data, raw


def native_calls(monkeypatch):
  calls = {"attempts": [], "open": [], "read": [], "close": []}
  original_open, original_read, original_close = reader._open, reader._read, reader._close
  def open_spy(name, flags, **kwargs):
    calls["attempts"].append((name, flags))
    fd = original_open(name, flags, **kwargs)
    calls["open"].append((name, flags, fd))
    assert flags & os.O_CLOEXEC and flags & os.O_NOFOLLOW
    assert flags & os.O_ACCMODE == os.O_RDONLY
    assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
    assert not os.get_inheritable(fd)
    return fd
  def read_spy(fd, amount):
    calls["read"].append((fd, amount))
    assert 0 < amount <= 64 * 1024
    return original_read(fd, amount)
  def close_spy(fd):
    calls["close"].append(fd)
    return original_close(fd)
  monkeypatch.setattr(reader, "_open", open_spy)
  monkeypatch.setattr(reader, "_read", read_spy)
  monkeypatch.setattr(reader, "_close", close_spy)
  return calls


def assert_handles_closed(calls):
  # 按每次open/close计数，不把可能复用的raw fd当永不复用的身份。
  assert len(calls["open"]) == len(calls["close"])
  for fd in {item[2] for item in calls["open"]}:
    with pytest.raises(OSError): os.fstat(fd)


@pytest.mark.parametrize("state", ["absent", "incomplete", "present"])
@pytest.mark.parametrize("mode", [0o700, 0o750, 0o755])
def test_three_states_no_creation_false_flags_and_closed_handles(account, monkeypatch, state, mode):
  account["home"].chmod(mode)
  raw = None
  if state == "incomplete": account["control"].mkdir(mode=0o700)
  elif state == "present": _, raw = publish(account)
  before = tuple(account["home"].iterdir())
  calls = native_calls(monkeypatch)
  observed = reader.inspect_service_index()
  assert observed.state == state and observed.account_home == str(account["home"])
  assert observed.account_identity == DirectoryIdentity(**directory(account["home"]))
  assert [field.name for field in fields(observed)] == ["account_home", "account_identity", "state", "index_identity", "snapshot"]
  assert all(getattr(observed, flag) is False for flag in ("writer_lock_verified", "database_allowed", "can_take_over"))
  assert tuple(account["home"].iterdir()) == before
  assert not hasattr(observed, "__dict__")
  with pytest.raises(FrozenInstanceError): observed.state = "present"
  if state == "absent": assert observed.index_identity is None and observed.snapshot is None
  else: assert observed.index_identity == DirectoryIdentity(**directory(account["control"]))
  if state != "present":
    assert observed.snapshot is None and calls["read"] == []
    assert not any(name == "index.json" for name, _ in calls["attempts"])
    if state == "absent": assert not any(name == ".agentcfg-pi-durable" for name, _ in calls["attempts"])
  else: assert account["file"].read_bytes() == raw
  assert_handles_closed(calls)


@pytest.mark.parametrize("stage", ["reserved", "registered"])
def test_present_full_snapshot_bytes_unchanged_environment_ignored(account, monkeypatch, stage):
  _, raw = publish(account, stage)
  other = account["home"].parent / "environment-home"; other.mkdir()
  monkeypatch.setenv("HOME", str(other)); monkeypatch.setenv("XDG_CONFIG_HOME", str(other))
  observed = reader.inspect_service_index()
  assert observed.snapshot == codec.decode_service_index(raw)
  assert len(observed.snapshot.services) == 2 and len(observed.snapshot.associations) == 4
  assert observed.snapshot.generation == 17
  assert all(entry.registration.stage == stage for entry in observed.snapshot.services)
  assert account["file"].read_bytes() == raw and not list(other.iterdir())
  forged = reader.ServiceIndexInspection("/forged", DirectoryIdentity(0, 1, 0), "present", None, None)
  assert forged.writer_lock_verified is False and forged.database_allowed is False and forged.can_take_over is False


@pytest.mark.parametrize("platform", ["darwin", "win32", True])
def test_platform_before_account_or_filesystem(account, monkeypatch, platform):
  calls = []
  def forbidden(*args, **kwargs): calls.append("query"); raise AssertionError()
  monkeypatch.setattr(reader, "_PLATFORM", platform)
  for name in ("_geteuid", "_getpwuid", "_open", "_stat"): monkeypatch.setattr(reader, name, forbidden)
  invalid(); assert calls == []


@pytest.mark.parametrize("uid", [True, -1, 2**32-1, "1000", 1.0])
def test_native_euid_range_before_lookup_or_io(account, monkeypatch, uid):
  calls = []
  monkeypatch.setattr(reader, "_geteuid", lambda: uid)
  def forbidden(*args, **kwargs): calls.append("called"); raise AssertionError()
  monkeypatch.setattr(reader, "_getpwuid", forbidden); monkeypatch.setattr(reader, "_open", forbidden)
  invalid(); assert calls == []


@pytest.mark.parametrize("path", ["/", "relative", "//a/b", "/a/", "/a//b", "/a/./b", "/a/../b", "/a\\b", "/a\x00b", "/a\x9fb", "/a\ud800b", "/" + "界" * 1366, True])
def test_account_native_path_before_filesystem(account, monkeypatch, path):
  calls = []
  entry = pwd.struct_passwd(("fixture", "x", account["uid"], 0, "", path, ""))
  monkeypatch.setattr(reader, "_getpwuid", lambda uid: entry)
  def forbidden(*args, **kwargs): calls.append("open"); raise AssertionError()
  monkeypatch.setattr(reader, "_open", forbidden)
  invalid(); assert calls == []


@pytest.mark.parametrize("kind", ["wronguid", "booluid", "foreignentry", "foreignpath", "foreignstat"])
def test_native_types_before_foreign_hooks(account, monkeypatch, kind):
  calls = []
  class Foreign:
    def __getattribute__(self, name): calls.append(name); raise AssertionError()
  class Text(str):
    def startswith(self, other): calls.append("startswith"); raise AssertionError()
  if kind == "wronguid": entry = passwd(account["uid"] + 1, account["home"])
  elif kind == "booluid": entry = passwd(True, account["home"])
  elif kind == "foreignpath": entry = pwd.struct_passwd(("f", "x", account["uid"], 0, "", Text(str(account["home"])), ""))
  else: entry = Foreign()
  if kind == "foreignstat":
    monkeypatch.setattr(reader, "_fstat", lambda fd: Foreign())
  else: monkeypatch.setattr(reader, "_getpwuid", lambda uid: entry)
  invalid(); assert calls == []


@pytest.mark.parametrize("state", ["absent", "incomplete", "present"])
def test_home_missing_or_unsafe_is_never_absent(account, state):
  if state == "incomplete": account["control"].mkdir(mode=0o700)
  elif state == "present": publish(account)
  assert reader.inspect_service_index().state == state
  account["home"].chmod(0o777)
  invalid()


def test_missing_account_directory_is_error(account):
  assert reader.inspect_service_index().state == "absent"
  account["home"].rmdir(); invalid()


def test_real_unsafe_ancestor_with_sticky_positive(account):
  # 真实自有祖先权限；系统/tmp的sticky策略也由其余正例实际经过。
  ancestor = account["home"].parent
  original = stat.S_IMODE(ancestor.stat().st_mode)
  ancestor.chmod(0o1777)
  try:
    assert reader.inspect_service_index().state == "absent"
    ancestor.chmod(0o777)
    invalid()
  finally: ancestor.chmod(original)


@pytest.mark.parametrize("object_kind", ["symlink", "file", "mode755", "mode1700"])
def test_control_objects_single_constraint(account, object_kind):
  account["control"].mkdir(mode=0o700)
  assert reader.inspect_service_index().state == "incomplete"
  if object_kind == "symlink":
    other = account["home"] / "other"; account["control"].rename(other); account["control"].symlink_to(other, target_is_directory=True)
  elif object_kind == "file": account["control"].rmdir(); account["control"].write_bytes(b"x")
  else: account["control"].chmod(0o755 if object_kind == "mode755" else 0o1700)
  invalid()


@pytest.mark.parametrize("object_kind", ["symlink", "hardlink", "directory", "fifo", "mode644", "mode1600"])
def test_index_objects_single_constraint(account, object_kind):
  _, raw = publish(account); assert reader.inspect_service_index().state == "present"
  target = account["file"]
  if object_kind == "symlink":
    other = account["control"] / "other.json"; target.rename(other); target.symlink_to(other)
  elif object_kind == "hardlink": os.link(target, account["control"] / "other.json")
  elif object_kind == "directory": target.unlink(); target.mkdir()
  elif object_kind == "fifo": target.unlink(); os.mkfifo(target)
  else: target.chmod(0o644 if object_kind == "mode644" else 0o1600)
  invalid()


@pytest.mark.parametrize("raw", [b"", b"{}", b"\xff", b'{"schema":1,"schema":1}', b'{"x":NaN}', b'{"x":1e999}', b"[" * 2000 + b"0" + b"]" * 2000],
  ids=["empty", "unknown", "utf8", "duplicate", "nonfinite", "overflowfloat", "deep"])
def test_json_rejects_without_rewrite(account, raw):
  publish(account); assert reader.inspect_service_index().state == "present"
  account["file"].write_bytes(raw)
  invalid(); assert account["file"].read_bytes() == raw


@pytest.mark.parametrize("field", ["account_home", "account_identity", "index_identity"])
def test_snapshot_original_physical_crossmatch(account, field):
  data, _ = publish(account); assert reader.inspect_service_index().state == "present"
  if field == "account_home":
    data[field] = "/other"
    for entry in data["services"]: entry["registration"][field] = "/other"
  else:
    data[field]["inode"] += 1
    for entry in data["services"]: entry["registration"][field]["inode"] += 1
  raw = codec.encode_service_index(codec.capture_service_index(data))
  account["file"].write_bytes(raw)
  invalid(); assert account["file"].read_bytes() == raw


def simulated_stat(info, **overrides):
  # exact stat_result替身只模拟属性事实，不证明非本UID的内核攻击防护。
  extra = {name: getattr(info, name) for name in ("st_atime_ns", "st_mtime_ns", "st_ctime_ns")}
  extra.update(overrides)
  values = list(info)
  indexes = {"st_mode": 0, "st_ino": 1, "st_dev": 2, "st_nlink": 3, "st_uid": 4, "st_size": 6}
  for name, value in overrides.items():
    if name in indexes: values[indexes[name]] = value
  return os.stat_result(values, extra)


@pytest.mark.parametrize("where", ["account", "control", "file", "ancestor"])
def test_wrong_uid_factual_stat_simulation(account, monkeypatch, where):
  publish(account); assert reader.inspect_service_index().state == "present"
  original_stat, original_fstat = reader._stat, reader._fstat
  home_inode = account["home"].stat().st_ino
  control_inode = account["control"].stat().st_ino
  file_inode = account["file"].stat().st_ino
  chosen = {"account": home_inode, "control": control_inode, "file": file_inode, "ancestor": account["home"].parent.stat().st_ino}[where]
  def altered(info): return simulated_stat(info, st_uid=account["uid"] + 1) if info.st_ino == chosen else info
  monkeypatch.setattr(reader, "_stat", lambda *args, **kwargs: altered(original_stat(*args, **kwargs)))
  monkeypatch.setattr(reader, "_fstat", lambda *args, **kwargs: altered(original_fstat(*args, **kwargs)))
  invalid()


@pytest.mark.parametrize("basename", [".agentcfg-pi-durable", "index.json"])
def test_first_present_then_open_missing_never_degrades(account, monkeypatch, basename):
  publish(account); assert reader.inspect_service_index().state == "present"
  original = reader._open
  removed = []
  def vanish(name, flags, **kwargs):
    if name == basename:
      if name == "index.json": account["file"].unlink()
      else: account["control"].rename(account["home"] / "moved")
      removed.append(name)
    return original(name, flags, **kwargs)
  monkeypatch.setattr(reader, "_open", vanish)
  invalid(); assert removed == [basename]


@pytest.mark.parametrize("point", ["read_error", "unlink", "replace", "chmod", "truncate"])
def test_read_changes_or_missing_fail(account, monkeypatch, point):
  _, raw = publish(account); assert reader.inspect_service_index().state == "present"
  original = reader._read
  changed = []
  def alter(fd, amount):
    if not changed:
      changed.append(point)
      if point == "read_error": raise FileNotFoundError(SECRET)
      elif point == "unlink": account["file"].unlink()
      elif point == "replace":
        replacement = account["control"] / "replacement"; replacement.write_bytes(raw); replacement.chmod(0o600); replacement.replace(account["file"])
      elif point == "chmod": account["file"].chmod(0o644)
      else: account["file"].write_bytes(raw[:-1])
    return original(fd, amount)
  monkeypatch.setattr(reader, "_read", alter)
  invalid(); assert changed == [point]


@pytest.mark.parametrize("initial_state,where", [("absent", "account"), ("incomplete", "account"),
  ("incomplete", "control"), ("present", "account"), ("present", "control")])
def test_directory_replacement_at_final_rewalk(account, monkeypatch, where, initial_state):
  if initial_state == "incomplete": account["control"].mkdir(mode=0o700)
  elif initial_state == "present": publish(account)
  assert reader.inspect_service_index().state == initial_state
  original = reader._open
  root_opens = []; changed = []
  def alter(name, flags, **kwargs):
    if name == "/":
      root_opens.append(name)
      if len(root_opens) == 2:
        changed.append(where)
        if where == "account":
          account["home"].rename(account["home"].with_name("moved-account")); account["home"].mkdir(mode=0o700)
        else:
          account["control"].rename(account["home"] / "moved-control"); account["control"].mkdir(mode=0o700)
    return original(name, flags, **kwargs)
  monkeypatch.setattr(reader, "_open", alter)
  invalid(); assert changed == [where]


@pytest.mark.parametrize("state", ["absent", "incomplete"])
def test_first_missing_then_appears_at_final_stat(account, monkeypatch, state):
  if state == "incomplete": account["control"].mkdir(mode=0o700)
  assert reader.inspect_service_index().state == state
  original = reader._stat
  basename = ".agentcfg-pi-durable" if state == "absent" else "index.json"
  counts = []
  def alter(name, **kwargs):
    if name == basename:
      counts.append(name)
      if len(counts) == 2:
        if state == "absent": account["control"].mkdir(mode=0o700)
        else: account["file"].write_bytes(b"{}"); account["file"].chmod(0o600)
    return original(name, **kwargs)
  monkeypatch.setattr(reader, "_stat", alter)
  invalid(); assert len(counts) == 2


@pytest.mark.parametrize("change", ["path", "uid", "foreignentry"])
def test_final_pwd_change_rejected(account, monkeypatch, change):
  publish(account); assert reader.inspect_service_index().state == "present"
  calls = []
  def lookup(uid):
    calls.append(uid)
    if len(calls) == 1: return passwd(uid, account["home"])
    if change == "path": return passwd(uid, account["home"].parent / "other")
    if change == "uid": return passwd(uid + 1, account["home"])
    return object()
  monkeypatch.setattr(reader, "_getpwuid", lookup)
  invalid(); assert len(calls) == 2


def test_short_read_complete_bounded_and_exact_limit(account, monkeypatch):
  _, raw = publish(account)
  original = reader._read; amounts = []
  def short(fd, amount):
    amounts.append(amount)
    return original(fd, min(amount, 7))
  monkeypatch.setattr(reader, "_read", short)
  assert reader.inspect_service_index().snapshot == codec.decode_service_index(raw)
  assert len(amounts) > 2 and max(amounts) <= 64 * 1024
  monkeypatch.setattr(reader, "_read", original)
  padded = raw + b" " * (LIMIT - len(raw)); account["file"].write_bytes(padded)
  assert reader.inspect_service_index().state == "present"
  account["file"].write_bytes(padded + b" ")
  reads = []
  def forbidden(fd, amount): reads.append(amount); raise AssertionError()
  monkeypatch.setattr(reader, "_read", forbidden)
  invalid(); assert reads == []


def test_read_growth_bounded_without_unlimited_allocation(account, monkeypatch):
  publish(account); requests = []; total = 0
  def endless(fd, amount):
    nonlocal total
    requests.append(amount); total += amount
    return b" " * amount
  monkeypatch.setattr(reader, "_read", endless)
  invalid()
  assert total == LIMIT + 1 and all(0 < amount <= 64 * 1024 for amount in requests)


def test_premature_eof_does_not_accept_complete_json_prefix(account, monkeypatch):
  _, raw = publish(account); account["file"].write_bytes(raw + b" " * 100)
  original = reader._read; calls = []
  def early(fd, amount):
    calls.append(amount)
    return original(fd, len(raw)) if len(calls) == 1 else b""
  monkeypatch.setattr(reader, "_read", early)
  invalid(); assert len(calls) == 2


@pytest.mark.parametrize("point", ["file", "control", "ancestor"])
def test_close_failure_continues_cleanup_once_and_fresh_error(account, monkeypatch, point):
  publish(account); assert reader.inspect_service_index().state == "present"
  calls = native_calls(monkeypatch)
  real_close = reader._close
  target_inode = account["file"].stat().st_ino if point == "file" else account["control"].stat().st_ino if point == "control" else account["home"].parent.stat().st_ino
  failed = []
  def close(fd):
    selected = not failed and os.fstat(fd).st_ino == target_inode
    real_close(fd)
    if selected: failed.append(fd); raise OSError(SECRET)
  monkeypatch.setattr(reader, "_close", close)
  invalid(); assert len(failed) == 1
  assert_handles_closed(calls)


@pytest.mark.parametrize("failure", ["open", "fstat", "read", "decode", "close"])
def test_foreign_exception_preserved_all_handles_cleaned(account, monkeypatch, failure):
  publish(account); calls = native_calls(monkeypatch)
  cause = ValueError("foreign cause"); context = RuntimeError("foreign context")
  foreign = OSError(SECRET)
  def fail(*args, **kwargs):
    try: raise foreign
    except OSError:
      foreign.__cause__ = cause; foreign.__context__ = context
      raise
  if failure == "open":
    original = reader._open
    def bad_open(name, flags, **kwargs):
      if name == "index.json": return fail()
      return original(name, flags, **kwargs)
    monkeypatch.setattr(reader, "_open", bad_open)
  elif failure == "close":
    original = reader._close; done = []
    def bad_close(fd):
      original(fd)
      if not done: done.append(fd); fail()
    monkeypatch.setattr(reader, "_close", bad_close)
  else: monkeypatch.setattr(reader, {"fstat": "_fstat", "read": "_read", "decode": "decode_service_index"}[failure], fail)
  own = invalid()
  assert own is not foreign and foreign.args == (SECRET,) and foreign.__cause__ is cause and foreign.__context__ is context
  assert_handles_closed(calls)


def test_directory_open_identity_drift_closes_new_child(account, monkeypatch):
  assert reader.inspect_service_index().state == "absent"
  calls = native_calls(monkeypatch); original = reader._fstat
  home_inode = account["home"].stat().st_ino
  def drift(fd):
    info = original(fd)
    return simulated_stat(info, st_ino=info.st_ino + 1) if info.st_ino == home_inode else info
  monkeypatch.setattr(reader, "_fstat", drift)
  invalid(); assert_handles_closed(calls)


def test_file_identity_drift_after_decode_rejected(account, monkeypatch):
  _, raw = publish(account); assert reader.inspect_service_index().state == "present"
  original = reader.decode_service_index
  def decode(data):
    result = original(data)
    replacement = account["control"] / "new"; replacement.write_bytes(raw); replacement.chmod(0o600); replacement.replace(account["file"])
    return result
  monkeypatch.setattr(reader, "decode_service_index", decode)
  invalid()


def test_no_public_path_uid_callback_inputs(account):
  assert reader.inspect_service_index().state == "absent"
  with pytest.raises(TypeError): reader.inspect_service_index(str(account["home"]))
  with pytest.raises(TypeError): reader.inspect_service_index(approved=True)


@pytest.mark.parametrize("state", ["absent", "incomplete", "present"])
def test_external_own_fd_is_not_closed(account, state):
  if state == "incomplete": account["control"].mkdir(mode=0o700)
  elif state == "present": publish(account)
  external = account["home"] / "external"
  external.write_bytes(b"synthetic external handle")
  fd = os.open(external, os.O_RDONLY | os.O_CLOEXEC)
  before = os.fstat(fd)
  try:
    assert reader.inspect_service_index().state == state
    assert os.fstat(fd) == before
  finally: os.close(fd)


@pytest.mark.parametrize("basename", [".agentcfg-pi-durable", "index.json"])
@pytest.mark.parametrize("failure", [PermissionError, OSError])
def test_first_basename_other_errors_do_not_mean_missing(account, monkeypatch, basename, failure):
  publish(account); assert reader.inspect_service_index().state == "present"
  original = reader._stat; injected = []
  def fail(name, **kwargs):
    if name == basename:
      injected.append(name); raise failure(SECRET)
    return original(name, **kwargs)
  monkeypatch.setattr(reader, "_stat", fail)
  invalid(); assert injected == [basename]


def test_first_stat_foreign_return_is_not_missing(account, monkeypatch):
  assert reader.inspect_service_index().state == "absent"
  original = reader._stat
  def false_missing(name, **kwargs):
    return None if name == ".agentcfg-pi-durable" else original(name, **kwargs)
  monkeypatch.setattr(reader, "_stat", false_missing)
  invalid()


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"])
def test_file_all_eight_native_identity_fields_bound_before_read(account, monkeypatch, field):
  publish(account); assert reader.inspect_service_index().state == "present"
  file_inode = account["file"].stat().st_ino
  original = reader._fstat
  def drift(fd):
    info = original(fd)
    return simulated_stat(info, **{field: getattr(info, field) + 1}) if info.st_ino == file_inode else info
  calls = native_calls(monkeypatch)
  monkeypatch.setattr(reader, "_fstat", drift)
  invalid(); assert calls["read"] == []
  assert_handles_closed(calls)


def test_exact_stat_result_foreign_scalar_hooks_zero(account, monkeypatch):
  calls = []
  class Number(int):
    def __lt__(self, other): calls.append("lt"); raise AssertionError()
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  original = reader._fstat
  def forged(fd): return simulated_stat(original(fd), st_uid=Number(account["uid"]))
  monkeypatch.setattr(reader, "_fstat", forged)
  invalid(); assert calls == []


def test_file_opened_as_readonly_cannot_write_and_no_extra_objects(account, monkeypatch, sentinel_factory):
  publish(account)
  before = sentinel_factory(account["home"])
  calls = native_calls(monkeypatch)
  observed = reader.inspect_service_index()
  assert observed.state == "present"
  before.assert_unchanged()
  assert all(flags & os.O_ACCMODE == os.O_RDONLY for _, flags in calls["attempts"])
  assert_handles_closed(calls)


@pytest.mark.parametrize("new_fd_close_error", [False, True])
def test_open_registration_allocation_failure_closes_new_and_old_fds(account, monkeypatch, new_fd_close_error):
  # 有限故障模拟：真实native open已成功，append在插入前抛错。
  # 这不是实际OS OOM；close异常版本先真实关闭再抛错，不证明失败kernel close已关闭。
  publish(account)
  assert reader.inspect_service_index().state == "present"
  external = account["home"] / "external-allocation"
  external.write_bytes(b"synthetic external fd")
  external_fd = os.open(external, os.O_RDONLY | os.O_CLOEXEC)
  external_identity = os.fstat(external_fd)
  original_init = reader._Handles.__init__
  original_open, original_close = reader._open, reader._close
  names = {}; failed = []; old_stack = []; closes_after_failure = []
  cause = ValueError("allocation cause"); context = RuntimeError("allocation context")
  foreign = MemoryError(SECRET)
  class FaultRegistry(list):
    def append(self, fd):
      if names[fd] == "index.json":
        assert not failed and fd not in self
        old_stack.extend(self)
        failed.append(fd)
        try: raise foreign
        except MemoryError:
          foreign.__cause__ = cause; foreign.__context__ = context
          raise
      return list.append(self, fd)
  def init(handles):
    original_init(handles)
    handles.fds = FaultRegistry()
  def open_owned(name, flags, **kwargs):
    fd = original_open(name, flags, **kwargs)
    names[fd] = name
    return fd
  def close_owned(fd):
    if failed: closes_after_failure.append(fd)
    original_close(fd)
    if failed and fd == failed[0] and new_fd_close_error: raise OSError("synthetic close fault")
  monkeypatch.setattr(reader._Handles, "__init__", init)
  monkeypatch.setattr(reader, "_open", open_owned)
  monkeypatch.setattr(reader, "_close", close_owned)
  try:
    own = invalid()
    assert len(failed) == 1 and len(old_stack) == 2
    assert own is not foreign
    assert foreign.args == (SECRET,) and foreign.__cause__ is cause and foreign.__context__ is context
    assert os.fstat(external_fd) == external_identity
    # 在test teardown清理之前确认程序已经关闭，不靠测试补关制造通过。
    with pytest.raises(OSError): os.fstat(failed[0])
    assert closes_after_failure.count(failed[0]) == 1
    assert all(closes_after_failure.count(fd) == 1 for fd in old_stack)
    assert external_fd not in closes_after_failure
    assert closes_after_failure[0] == failed[0]
  finally:
    # red保留证据后只清理模拟暴露的test自有fd，不让故障污染其他cases。
    for fd in failed:
      try: os.fstat(fd)
      except OSError: pass
      else: os.close(fd)
    os.close(external_fd)
