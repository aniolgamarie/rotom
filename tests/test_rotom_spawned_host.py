"""完全模拟 /proc/pidfd；不创建进程、真实句柄或发送信号。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import spawned_host as host
from agentcfg.storage import Conflict


BOOT = "12345678-1234-1234-1234-123456789abc"
MANAGER = {"pid": 101, "birth_id": "linux:" + BOOT + ":7"}
IDENTITY = {"pid": 202, "birth_id": "linux:" + BOOT + ":99"}


def stat(pid=202, ppid=101, state="S", start="99"):
  # 字段3起：state/ppid，starttime在索引19；comm可含空格与括号。
  return str(pid) + " (synthetic (child)) " + " ".join([state, str(ppid)] + ["0"] * 17 + [start])


@pytest.fixture
def fake(monkeypatch):
  state = SimpleNamespace(child=SimpleNamespace(pid=202, returncode=None), manager=deepcopy(MANAGER),
    threads=1, handler=host.signal.SIG_DFL, platform="linux", boot=BOOT, stat=stat(),
    reads=[], opens=[], closes=[], events=[], polls=[], inherited=False, on_read=None, on_poll=None,
    open_error=None, close_error=None, inheritable_error=None)
  def identity(): return deepcopy(state.manager)
  monkeypatch.setattr(host, "current_process_identity", identity)
  monkeypatch.setattr(host, "sys", SimpleNamespace(platform=state.platform))
  monkeypatch.setattr(host, "threading", SimpleNamespace(active_count=lambda: state.threads))
  monkeypatch.setattr(host, "signal", SimpleNamespace(SIGCHLD=17, SIG_DFL=0, getsignal=lambda signum: state.handler))
  class Proc:
    def __init__(self, path): self.path = path
    def read_text(self, *, encoding):
      assert encoding == "ascii"
      state.reads.append(self.path)
      if state.on_read: state.on_read(self.path)
      if self.path == "/proc/sys/kernel/random/boot_id": return state.boot
      assert self.path == "/proc/202/stat", "no non-fake /proc read"
      return state.stat
  monkeypatch.setattr(host, "Path", Proc)
  def opened(pid, flags):
    state.opens.append((pid, flags))
    if state.open_error: raise state.open_error
    return 77
  def closed(fd):
    state.closes.append(fd)
    if state.close_error: raise state.close_error
  def inheritable(fd):
    assert fd == 77
    if state.inheritable_error: raise state.inheritable_error
    return state.inherited
  monkeypatch.setattr(host, "os", SimpleNamespace(pidfd_open=opened, close=closed, get_inheritable=inheritable))
  class Poll:
    def register(self, fd, mask): assert fd == 77
    def poll(self, timeout):
      assert timeout == 0
      state.polls.append(True)
      if state.on_poll: state.on_poll()
      return state.events
  monkeypatch.setattr(host, "select", SimpleNamespace(poll=Poll, POLLIN=1, POLLHUP=16, POLLERR=8))
  def forbidden(*args): pytest.fail("no poll/wait/signal on child")
  for name in ("wait", "poll", "kill", "terminate", "send_signal"):
    setattr(state.child, name, forbidden)
  return state


def capture(fake): return host.capture_spawned_host(fake.child, deepcopy(MANAGER))


def test_snapshot_exact_schema_is_defensive_and_close_is_idempotent(fake):
  manager = deepcopy(MANAGER)
  handle = host.capture_spawned_host(fake.child, manager)
  assert type(handle) is host.SpawnedHost
  manager["pid"] = 999
  value = handle.snapshot()
  assert value == {"identity": IDENTITY, "manager_identity": MANAGER,
    "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}
  value["identity"]["pid"] = 999; value["manager_identity"]["pid"] = 999
  assert handle.snapshot()["identity"] == IDENTITY
  assert fake.opens == [(202, 0)] and fake.closes == []
  handle.close(); handle.close()
  assert fake.closes == [77]
  with pytest.raises(Conflict): handle.snapshot()


def test_context_manager_only_closes_owned_fd(fake):
  with capture(fake) as handle:
    assert handle.snapshot()["identity"] == IDENTITY
  assert fake.closes == [77] and fake.child.returncode is None


@pytest.mark.parametrize("change", ["platform", "threads", "handler", "manager", "manager-bool", "manager-extra", "pid-bool", "pid-zero", "same-pid", "returned"])
def test_untrusted_launch_conditions_do_not_open_pidfd(fake, monkeypatch, change):
  manager = deepcopy(MANAGER)
  if change == "platform": monkeypatch.setattr(host, "sys", SimpleNamespace(platform="darwin"))
  elif change == "threads": fake.threads = 2
  elif change == "handler": fake.handler = object()
  elif change == "manager": fake.manager["birth_id"] = "linux:" + BOOT + ":8"
  elif change == "manager-bool": manager["pid"] = True
  elif change == "manager-extra": manager["extra"] = True
  elif change == "pid-bool": fake.child.pid = True
  elif change == "pid-zero": fake.child.pid = 0
  elif change == "same-pid": fake.child.pid = 101
  else: fake.child.returncode = 0
  assert host.capture_spawned_host(fake.child, manager) is None
  assert fake.opens == [] and fake.closes == []


@pytest.mark.parametrize("change", ["wrong-pid", "ppid", "zombie", "dead", "dead-lower", "zero-start", "invalid-start", "malformed", "bad-boot", "different-boot", "inheritable", "event", "open-error", "inherit-error"])
def test_capture_failure_is_unknown_and_closes_acquired_fd(fake, change):
  if change == "wrong-pid": fake.stat = stat(pid=203)
  elif change == "ppid": fake.stat = stat(ppid=999)
  elif change in ("zombie", "dead", "dead-lower"): fake.stat = stat(state={"zombie": "Z", "dead": "X", "dead-lower": "x"}[change])
  elif change == "zero-start": fake.stat = stat(start="0")
  elif change == "invalid-start": fake.stat = stat(start="bad")
  elif change == "malformed": fake.stat = "synthetic malformed"
  elif change == "bad-boot": fake.boot = "synthetic-private-canary"
  elif change == "different-boot": fake.boot = "22345678-1234-1234-1234-123456789abc"
  elif change == "inheritable": fake.inherited = True
  elif change == "event": fake.events = [(77, 1)]
  elif change == "open-error": fake.open_error = OSError("synthetic-private-canary")
  else: fake.inheritable_error = OSError("synthetic-private-canary")
  assert capture(fake) is None
  assert fake.closes == ([] if change == "open-error" else [77])


@pytest.mark.parametrize("change", ["pid", "returncode", "stat", "ppid", "boot", "manager", "thread", "handler", "event"])
def test_capture_sampling_race_cannot_bind_reused_or_exited_child(fake, change):
  def race():
    if len(fake.polls) != 2: return
    if change == "pid": fake.child.pid = 203
    elif change == "returncode": fake.child.returncode = 0
    elif change == "stat": fake.stat = stat(start="100")
    elif change == "ppid": fake.stat = stat(ppid=999)
    elif change == "boot": fake.boot = "22345678-1234-1234-1234-123456789abc"
    elif change == "manager": fake.manager["birth_id"] = "linux:" + BOOT + ":8"
    elif change == "thread": fake.threads = 2
    elif change == "handler": fake.handler = object()
    else: fake.events = [(77, 16)]
  fake.on_poll = race
  assert capture(fake) is None and fake.closes == [77]


@pytest.mark.parametrize("change", ["pid", "returncode", "stat", "ppid", "boot", "manager", "thread", "handler", "event", "read-error", "poll-error"])
def test_snapshot_rechecks_original_binding_with_fixed_diagnostic(fake, change):
  handle = capture(fake)
  if change == "pid": fake.child.pid = 203
  elif change == "returncode": fake.child.returncode = -9
  elif change == "stat": fake.stat = stat(start="100")
  elif change == "ppid": fake.stat = stat(ppid=999)
  elif change == "boot": fake.boot = "22345678-1234-1234-1234-123456789abc"
  elif change == "manager": fake.manager["pid"] = 303
  elif change == "thread": fake.threads = 2
  elif change == "handler": fake.handler = object()
  elif change == "event": fake.events = [(77, 8)]
  else:
    def failed(*args): raise OSError("synthetic-private-canary")
    if change == "read-error": fake.on_read = failed
    else: fake.on_poll = failed
  with pytest.raises(Conflict) as caught: handle.snapshot()
  assert "synthetic-private-canary" not in str(caught.value)
  assert fake.opens == [(202, 0)]
  handle.close(); assert fake.closes == [77]
  with pytest.raises(Conflict): handle.snapshot()
  assert fake.opens == [(202, 0)]


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("site", ["read", "poll"])
def test_capture_control_interrupt_closes_without_masking(fake, error_type, site):
  error = error_type("synthetic-private-canary")
  def failed(*args): raise error
  if site == "read": fake.on_read = failed
  else: fake.on_poll = failed
  fake.close_error = OSError("synthetic-close-failure")
  with pytest.raises(error_type) as caught: capture(fake)
  assert caught.value is error and fake.closes == [77]


def test_close_oserror_is_not_retried(fake):
  handle = capture(fake); fake.close_error = OSError("synthetic-private-canary")
  handle.close(); handle.close()
  assert fake.closes == [77]


def test_private_constructor_rejects_user_dictionary(fake):
  with pytest.raises((TypeError, Conflict)):
    host.SpawnedHost({"identity": IDENTITY})


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("site", ["read", "poll"])
def test_snapshot_control_interrupt_is_original_and_closes(fake, error_type, site):
  handle = capture(fake)
  error = error_type("synthetic-private-canary")
  def failed(*args): raise error
  if site == "read": fake.on_read = failed
  else: fake.on_poll = failed
  with pytest.raises(error_type) as caught: handle.snapshot()
  assert caught.value is error and fake.closes == [77]
  handle.close(); assert fake.closes == [77]
  with pytest.raises(Conflict): handle.snapshot()
  assert fake.opens == [(202, 0)]


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("close_type", [KeyboardInterrupt, SystemExit, OSError])
def test_context_close_cannot_mask_original_body_control(fake, error_type, close_type):
  body_error = error_type("synthetic-body-control")
  fake.close_error = close_type("synthetic-cleanup-control")
  caught = None
  try:
    with capture(fake):
      raise body_error
  except BaseException as error:
    caught = error
  assert caught is body_error and fake.closes == [77]
