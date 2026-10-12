"""可信FD交接的真实memfd与假PID1/exec测试；不运行helper或namespace。"""

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import pi_shell_handoff as module
from agentcfg import pi_shell_execution as execution
from agentcfg.schema import ConfigError
from test_pi_shell_execution import execution_case, assert_closed
from test_pi_shell_preparation import shell_case


NONCE = "a" * 32
SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL


@pytest.mark.parametrize("size", [0, 64 * 1024 * 1024 + 1])
def test_helper_hash_refuses_empty_or_oversized_before_read(tmp_path, monkeypatch, size):
  path = tmp_path / "synthetic-helper"
  with path.open("wb") as stream: stream.truncate(size)
  with path.open("rb") as stream:
    proxy = SimpleNamespace(**vars(os))
    proxy.pread = lambda *args: pytest.fail("invalid helper size must precede read")
    monkeypatch.setattr(module, "os", proxy)
    with pytest.raises(ValueError): module._hash(stream.fileno())


@pytest.fixture(autouse=True)
def adoption_state(monkeypatch):
  monkeypatch.setattr(module, "_ADOPT_ATTEMPTED", False)


@pytest.fixture
def local(monkeypatch):
  value = {"platform": "linux", "pid": 1, "boot_id": "synthetic-boot", "start_time": "123",
    "namespace": "pid:[222]", "uid": os.geteuid()}
  monkeypatch.setattr(module, "local_namespace_identity", lambda: deepcopy(value))
  proxy = SimpleNamespace(**vars(os)); original_readlink = os.readlink
  proxy.getpid = lambda: 1
  proxy.readlink = lambda path: "user:[333]" if path == "/proc/self/ns/user" else original_readlink(path)
  monkeypatch.setattr(module, "os", proxy); monkeypatch.setattr(execution, "os", proxy)
  monkeypatch.setattr(execution, "_task_ids", lambda: ("1",))
  monkeypatch.setattr(execution, "_FD_EXEC_SUPPORTED", True)
  return value, proxy


def binding(value, case):
  return {"purpose": "shell-probe", "nonce": NONCE, "helper_identity": case["helper_identity"], "plan_digest": case["plan_digest"],
    "worker_identity": {"platform": "linux", "pid": 201, "ppid": 200, "pgid": 201, "boot_id": "synthetic-boot",
      "start_time": "123", "namespace": "pid:[222]", "uid": os.geteuid()}, "worker_user_namespace": "user:[333]",
    "uid_projection": [{"host_uid": uid, "visible_uid": uid} for uid in sorted({row[2] for _, row in value.snapshots})]}


@contextmanager
def transferred(case, change=None):
  with execution.prepare_shell_execution(**case) as value:
    with module.handoff_channel() as fd:
      selected = binding(value, case)
      if change: change(selected)
      module.seal_handoff(fd, value, selected)
      yield value, fd, selected


def adopt(fd, case):
  return module.adopt_handoff(fd, nonce=NONCE, helper_identity=case["helper_identity"], plan_digest=case["plan_digest"])


@contextmanager
def forged(raw):
  with module.handoff_channel() as fd:
    assert os.write(fd, raw) == len(raw)
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, SEALS); os.lseek(fd, 0, os.SEEK_SET)
    yield fd


def test_sealed_channel_and_adopted_once_exec_with_no_private_text(execution_case, local, monkeypatch):
  with transferred(execution_case) as (original, fd, selected):
    raw = os.pread(fd, 256 * 1024 + 1, 0)
    assert execution_case["command"].encode() not in raw
    assert hashlib.sha256(execution_case["command"].encode()).hexdigest().encode() not in raw
    assert fcntl.fcntl(fd, fcntl.F_GET_SEALS) & SEALS == SEALS
    assert os.fstat(fd).st_nlink == 0 and os.fstat(fd).st_mode & 0o777 == 0o600
    assert not os.get_inheritable(fd) and os.lseek(fd, 0, os.SEEK_CUR) == 0
    with pytest.raises(ConfigError): execution.exec_prepared(original)
    with adopt(fd, execution_case) as value:
      assert value == original and value is not original
      assert not any(os.get_inheritable(item) for item, _ in value.snapshots)
      assert_closed(fd)
      with module.handoff_channel() as other:
        with pytest.raises(ConfigError): module.seal_handoff(other, value, selected)
      calls = []
      monkeypatch.setattr(execution, "_fd_inventory", lambda: tuple(item for item, _ in value.snapshots))
      def fake_exec(descriptor, argv, env):
        calls.append((descriptor, argv, env))
        assert descriptor == value.helper_fd and env == {} and not os.get_inheritable(descriptor)
        assert all(os.get_inheritable(item) for item in value.pass_fds)
        raise OSError("synthetic exec, never run")
      monkeypatch.setattr(execution, "_exec_fd", fake_exec)
      with pytest.raises(ConfigError): execution.exec_prepared(value)
      with pytest.raises(ConfigError): execution.exec_prepared(value)
      assert len(calls) == 1
    for descriptor, _ in original.snapshots: assert_closed(descriptor)


def test_export_is_once_and_scope_is_not_reusable(execution_case):
  with transferred(execution_case) as (value, fd, selected):
    with pytest.raises(ConfigError): module.seal_handoff(fd, value, selected)
    with module.handoff_channel() as other:
      with pytest.raises(ConfigError): module.seal_handoff(other, value, selected)
  with module.handoff_channel() as other:
    with pytest.raises(ConfigError): module.seal_handoff(other, value, selected)


def test_untrusted_constructed_execution_cannot_export(execution_case):
  with execution.prepare_shell_execution(**execution_case) as original:
    fake = execution.PreparedShellExecution(**vars(original))
    with module.handoff_channel() as fd:
      with pytest.raises(ConfigError): module.seal_handoff(fd, fake, binding(original, execution_case))


@pytest.mark.parametrize("fault", ["helper", "plan", "nonce", "purpose", "unknown", "projection-missing", "projection-duplicate", "projection-bool", "worker"])
def test_export_binding_failures_burn_qualification(execution_case, fault):
  with execution.prepare_shell_execution(**execution_case) as value:
    selected = binding(value, execution_case)
    if fault == "helper": selected["helper_identity"] = "0" * 64
    elif fault == "plan": selected["plan_digest"] = "0" * 64
    elif fault == "nonce": selected["nonce"] = "private"
    elif fault == "purpose": selected["purpose"] = "product"
    elif fault == "unknown": selected["secret"] = "private"
    elif fault == "projection-missing": selected["uid_projection"] = []
    elif fault == "projection-duplicate": selected["uid_projection"] *= 2
    elif fault == "projection-bool": selected["uid_projection"][0]["visible_uid"] = True
    else: selected["worker_identity"]["platform"] = "darwin"
    with module.handoff_channel() as fd:
      with pytest.raises(ConfigError, match="pi-shell-handoff"): module.seal_handoff(fd, value, selected)
      with pytest.raises(ConfigError): module.seal_handoff(fd, value, binding(value, execution_case))
    with pytest.raises(ConfigError): execution.exec_prepared(value)


@pytest.mark.parametrize("field", ["script_fd", "seccomp_fd", "mask_fds"])
def test_changed_data_offset_prevents_export(execution_case, field):
  with execution.prepare_shell_execution(**execution_case) as value:
    fd = getattr(value, field); fd = fd[0] if field == "mask_fds" else fd
    os.lseek(fd, 1, os.SEEK_SET)
    with module.handoff_channel() as channel:
      with pytest.raises(ConfigError): module.seal_handoff(channel, value, binding(value, execution_case))


@pytest.mark.parametrize("fault", ["unsealed", "truncated", "duplicate", "unknown", "fd-duplicate", "fd-bool", "snapshot", "role", "argv", "oversize"])
def test_channel_shape_and_seals_fail_closed(execution_case, local, fault):
  with transferred(execution_case) as (_, channel, _):
    raw = os.pread(channel, 256 * 1024, 0); doc = json.loads(raw)
    if fault == "truncated": raw = raw[:-1]
    elif fault == "duplicate": raw = raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
    elif fault == "unknown": doc["secret"] = "private"; raw = json.dumps(doc).encode()
    elif fault == "fd-duplicate": doc["pass_fds"][0] = doc["helper_fd"]; raw = json.dumps(doc).encode()
    elif fault == "fd-bool": doc["helper_fd"] = True; raw = json.dumps(doc).encode()
    elif fault == "snapshot": doc["snapshots"][0][1][0] += 1; raw = json.dumps(doc).encode()
    elif fault == "role": doc["script_fd"] = doc["helper_fd"]; raw = json.dumps(doc).encode()
    elif fault == "argv": doc["argv"][-1] = "private-command"; raw = json.dumps(doc).encode()
    elif fault == "oversize": raw += b" " * (256 * 1024)
    if fault == "unsealed":
      with module.handoff_channel() as other:
        os.write(other, raw)
        with pytest.raises(ConfigError):
          with adopt(other, execution_case): pytest.fail("unsealed channel")
    else:
      with forged(raw) as other:
        with pytest.raises(ConfigError, match="pi-shell-handoff"):
          with adopt(other, execution_case): pytest.fail("invalid channel")


@pytest.mark.parametrize("fault", ["birth", "boot", "pid-namespace", "user-namespace", "pid", "threads", "nonce", "helper", "plan", "uid"])
def test_worker_identity_mismatch_refuses_adoption(execution_case, local, monkeypatch, fault):
  identity, proxy = local
  with transferred(execution_case) as (_, fd, _):
    if fault == "birth": identity["start_time"] = "999"
    elif fault == "boot": identity["boot_id"] = "other"
    elif fault == "pid-namespace": identity["namespace"] = "pid:[999]"
    elif fault == "user-namespace": proxy.readlink = lambda _: "user:[999]"
    elif fault == "pid": proxy.getpid = lambda: 201
    elif fault == "threads": monkeypatch.setattr(execution, "_task_ids", lambda: ("1", "2"))
    elif fault == "uid": identity["uid"] += 1
    kwargs = {"nonce": "d" * 32 if fault == "nonce" else NONCE,
      "helper_identity": "0" * 64 if fault == "helper" else execution_case["helper_identity"],
      "plan_digest": "0" * 64 if fault == "plan" else execution_case["plan_digest"]}
    with pytest.raises(ConfigError):
      with module.adopt_handoff(fd, **kwargs): pytest.fail("worker mismatch")


def test_uid_projection_changes_only_snapshot_uid(execution_case, local, monkeypatch):
  identity, proxy = local
  with transferred(execution_case, lambda b: [row.update(visible_uid=42) for row in b["uid_projection"]]) as (original, fd, _):
    actual_fstat = os.fstat
    def mapped(descriptor):
      info = actual_fstat(descriptor)
      fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}; fields["st_uid"] = 42
      return SimpleNamespace(**fields)
    proxy.fstat = mapped; proxy.geteuid = lambda: 42; identity["uid"] = 42
    with adopt(fd, execution_case) as value:
      assert all(row[2] == 42 for _, row in value.snapshots)
      assert [(*row[:2], *row[3:]) for _, row in value.snapshots] == [(*row[:2], *row[3:]) for _, row in original.snapshots]


def test_wrong_uid_projection_refuses_same_inode(execution_case, local):
  with transferred(execution_case, lambda b: [row.update(visible_uid=42) for row in b["uid_projection"]]) as (_, fd, _):
    with pytest.raises(ConfigError):
      with adopt(fd, execution_case): pytest.fail("wrong UID")


def test_replaced_fd_is_not_closed_on_failed_adoption(execution_case, local):
  with transferred(execution_case) as (value, channel, _):
    fd = value.pass_fds[0]; foreign = os.memfd_create("synthetic-foreign", os.MFD_CLOEXEC)
    os.close(fd); os.dup2(foreign, fd, inheritable=False)
    try:
      with pytest.raises(ConfigError):
        with adopt(channel, execution_case): pytest.fail("replaced FD")
      assert os.fstat(fd).st_ino == os.fstat(foreign).st_ino
      assert_closed(value.helper_fd)  # 此FD已复核，可安全清理。
    finally: os.close(fd); os.close(foreign)


def test_adopt_body_exception_and_reused_fd_cleanup(execution_case, local):
  error = RuntimeError("synthetic caller")
  foreign = os.memfd_create("synthetic-foreign", os.MFD_CLOEXEC)
  try:
    with transferred(execution_case) as (_, channel, _):
      with pytest.raises(RuntimeError) as caught:
        with adopt(channel, execution_case) as value:
          fd = value.helper_fd; os.close(fd); os.dup2(foreign, fd, inheritable=False)
          raise error
      assert caught.value is error and os.fstat(fd).st_ino == os.fstat(foreign).st_ino
      os.close(fd)
  finally: os.close(foreign)


def test_repeated_adopt_is_rejected_even_through_dup_channel(execution_case, local):
  with transferred(execution_case) as (_, channel, _):
    alias = os.dup(channel)
    try:
      with adopt(channel, execution_case): pass
      with pytest.raises(ConfigError):
        with adopt(alias, execution_case): pytest.fail("repeat")
    finally: os.close(alias)


def test_failed_adopt_also_consumes_process_attempt(execution_case, local):
  with transferred(execution_case) as (_, channel, _):
    with pytest.raises(ConfigError):
      with module.adopt_handoff(channel, nonce="wrong", helper_identity=execution_case["helper_identity"], plan_digest=execution_case["plan_digest"]): pass
    with pytest.raises(ConfigError):
      with adopt(channel, execution_case): pytest.fail("failed attempt retry")


def test_setup_failure_has_no_disk_fallback(monkeypatch):
  def unavailable(*args): raise OSError("synthetic unavailable")
  monkeypatch.setattr(module.os, "memfd_create", unavailable)
  with pytest.raises(ConfigError):
    with module.handoff_channel(): pytest.fail("no fallback")


@pytest.mark.parametrize("fault", ["script-role", "seccomp-role", "source-stdio", "extra-option", "isolation-prefix"])
def test_argv_role_disconnect_is_rejected(execution_case, local, fault):
  with transferred(execution_case) as (_, channel, _):
    doc = json.loads(os.pread(channel, 256 * 1024, 0)); argv = doc["argv"]
    if fault == "script-role": argv[argv.index("--ro-bind-data") + 1] = str(doc["seccomp_fd"])
    elif fault == "seccomp-role": argv[argv.index("--seccomp") + 1] = str(doc["script_fd"])
    elif fault == "source-stdio": argv[argv.index("--bind-fd") + 1] = "2"
    elif fault == "extra-option": argv[1:1] = ["--setenv", "PRIVATE", "private-script-marker"]
    else: argv[1] = "--unshare-user-try"
    with forged(json.dumps(doc).encode()) as other:
      with pytest.raises(ConfigError):
        with adopt(other, execution_case): pytest.fail("disconnected argv")


@pytest.mark.parametrize("field", ["script_fd", "seccomp_fd", "mask_fds"])
def test_data_offset_drift_after_export_is_rejected_and_verified_fds_closed(execution_case, local, field):
  with transferred(execution_case) as (value, channel, _):
    fd = getattr(value, field); fd = fd[0] if field == "mask_fds" else fd
    os.lseek(fd, 1, os.SEEK_SET)
    with pytest.raises(ConfigError):
      with adopt(channel, execution_case): pytest.fail("changed offset")
    for item, _ in value.snapshots: assert_closed(item)


def test_channel_scope_does_not_close_reused_descriptor():
  foreign = os.memfd_create("synthetic-foreign-channel", os.MFD_CLOEXEC)
  try:
    with module.handoff_channel() as fd:
      os.close(fd); os.dup2(foreign, fd, inheritable=False)
    assert os.fstat(fd).st_ino == os.fstat(foreign).st_ino
    os.close(fd)
  finally: os.close(foreign)


def authorization():
  return {"operation_id": "1" * 32, "lease_id": "2" * 32, "operation_digest": "3" * 64,
    "allocation_digest": "4" * 64, "runtime_identity": "5" * 64, "lock_identity": "6" * 64,
    "slice_identity": "7" * 64, "context_digest": "8" * 64, "grant_generation": 1, "profile_id": "pi-base"}


def product_binding(value):
  value.update(purpose="shell-execution", authorization=authorization())


def test_product_authorization_digest_and_adopt(execution_case, local):
  from agentcfg.activity import digest
  assert module.authorization_digest(authorization()) == digest(authorization())
  with transferred(execution_case, product_binding) as (_, fd, selected):
    with module.adopt_handoff(fd, nonce=NONCE, helper_identity=execution_case["helper_identity"],
        plan_digest=execution_case["plan_digest"], expected_authorization=module.authorization_digest(selected["authorization"])):
      pass


@pytest.mark.parametrize("key", list(authorization()))
def test_any_authorization_field_change_refuses_expected_digest(execution_case, local, key):
  expected = module.authorization_digest(authorization())
  def changed(value):
    product_binding(value)
    old = value["authorization"][key]
    value["authorization"][key] = 2 if key == "grant_generation" else "pi-full" if key == "profile_id" else "9" * len(old)
  with transferred(execution_case, changed) as (_, fd, _):
    with pytest.raises(ConfigError, match="pi-shell-handoff"):
      with module.adopt_handoff(fd, nonce=NONCE, helper_identity=execution_case["helper_identity"],
          plan_digest=execution_case["plan_digest"], expected_authorization=expected): pass


@pytest.mark.parametrize("fault", ["extra", "missing", "bool", "zero", "overflow", "profile", "hex", "non-object"])
def test_authorization_closed_schema(fault):
  value = authorization()
  if fault == "extra": value["extra"] = "secret"
  elif fault == "missing": del value["lease_id"]
  elif fault == "bool": value["grant_generation"] = True
  elif fault == "zero": value["grant_generation"] = 0
  elif fault == "overflow": value["grant_generation"] = 2**53
  elif fault == "profile": value["profile_id"] = "pi"
  elif fault == "hex": value["operation_id"] = "A" * 32
  else: value = []
  with pytest.raises(ConfigError, match="pi-shell-handoff"): module.authorization_digest(value)


@pytest.mark.parametrize("purpose,expected", [("shell-probe", "f" * 64), ("shell-execution", None)])
def test_purpose_cannot_cross_consumer_contract(execution_case, local, purpose, expected):
  with transferred(execution_case, product_binding if purpose == "shell-execution" else None) as (_, fd, _):
    with pytest.raises(ConfigError, match="pi-shell-handoff"):
      with module.adopt_handoff(fd, nonce=NONCE, helper_identity=execution_case["helper_identity"],
          plan_digest=execution_case["plan_digest"], expected_authorization=expected): pass


@pytest.mark.parametrize("fault", ["probe-extra", "product-missing", "product-extra"])
def test_producer_binding_purpose_shape_is_closed(execution_case, fault):
  def change(value):
    if fault == "probe-extra": value["authorization"] = authorization()
    else:
      product_binding(value)
      if fault == "product-missing": del value["authorization"]
      else: value["extra"] = True
  with pytest.raises(ConfigError, match="pi-shell-handoff"):
    with transferred(execution_case, change): pass
