"""adopt-only worker协议；假门控/身份/exec，不运行helper或新进程。"""

from contextlib import contextmanager
from types import SimpleNamespace
import os

import pytest

from agentcfg import pi_shell_worker as module
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


@pytest.fixture
def worker_case(monkeypatch):
  args = {"handoff_fd": 40, "nonce": "a" * 32, "helper_identity": "b" * 64,
    "plan_digest": "c" * 64, "authorization_digest": "d" * 64}
  calls = []; gate = [b"G"]
  proxy = SimpleNamespace(**vars(os))
  proxy.getpid = lambda: 1
  def read(fd, size):
    assert (fd, size) == (0, 2); calls.append("G"); return gate[0]
  proxy.read = read
  def opened(path, flags):
    assert path == "/dev/null" and flags == os.O_RDONLY | os.O_CLOEXEC
    calls.append("devnull"); return 41
  proxy.open = opened
  proxy.dup2 = lambda source, target: calls.append(("dup2", source, target))
  proxy.close = lambda fd: calls.append(("close", fd))
  monkeypatch.setattr(module, "os", proxy)
  class Output:
    def write(self, value): assert value == b"R"; calls.append("R")
    def flush(self): calls.append("flush")
  monkeypatch.setattr(module, "sys", SimpleNamespace(stdout=SimpleNamespace(buffer=Output())))
  @contextmanager
  def adopt(fd, **kwargs):
    assert fd == args["handoff_fd"]
    assert kwargs == {"nonce": args["nonce"], "helper_identity": args["helper_identity"],
      "plan_digest": args["plan_digest"], "expected_authorization": args["authorization_digest"]}
    calls.append("adopt")
    try: yield "trusted prepared"
    finally: calls.append("cleanup")
  monkeypatch.setattr(module, "adopt_handoff", adopt)
  class Executed(BaseException): pass
  def execute(value):
    assert value == "trusted prepared"; calls.append("exec"); raise Executed()
  monkeypatch.setattr(module, "exec_prepared", execute)
  return args, calls, gate, proxy, Executed


def test_worker_readiness_gate_stdin_adoption_order(worker_case):
  args, calls, _, _, executed = worker_case
  with pytest.raises(executed): module.run(**args)
  assert calls == ["R", "flush", "G", "devnull", ("dup2", 41, 0), ("close", 41), "adopt", "exec", "cleanup"]


@pytest.mark.parametrize("gate", [b"", b"GG", b"X", b"G\n"])
def test_gate_refusal_never_adopts(worker_case, gate):
  args, calls, value, _, _ = worker_case; value[0] = gate
  with pytest.raises(Conflict): module.run(**args)
  assert calls == ["R", "flush", "G"]


@pytest.mark.parametrize("key,value", [("handoff_fd", 2), ("handoff_fd", True), ("handoff_fd", "40"),
  ("nonce", "A" * 32), ("nonce", "a" * 31), ("helper_identity", "bad"),
  ("plan_digest", None), ("authorization_digest", "E" * 64)])
def test_bad_parameters_refuse_before_readiness(worker_case, key, value):
  args, calls, _, _, _ = worker_case; args[key] = value
  with pytest.raises(ConfigError): module.run(**args)
  assert calls == []


def test_non_pid1_refuses_before_readiness(worker_case):
  args, calls, _, proxy, _ = worker_case; proxy.getpid = lambda: 201
  with pytest.raises(Conflict): module.run(**args)
  assert calls == []


def test_returning_exec_fails_once_and_cleans(worker_case, monkeypatch):
  args, calls, _, _, _ = worker_case
  monkeypatch.setattr(module, "exec_prepared", lambda value: calls.append("returned"))
  with pytest.raises(ConfigError, match="pi-shell-exec-unavailable"): module.run(**args)
  assert calls[-3:] == ["adopt", "returned", "cleanup"]


def test_adoption_failure_is_not_retried(worker_case, monkeypatch):
  args, calls, _, _, _ = worker_case
  @contextmanager
  def refused(*args, **kwargs):
    calls.append("refused"); raise ConfigError("pi-shell-handoff"); yield
  monkeypatch.setattr(module, "adopt_handoff", refused)
  with pytest.raises(ConfigError, match="pi-shell-handoff"): module.run(**args)
  assert calls.count("refused") == 1 and "exec" not in calls


def test_cli_only_accepts_new_required_contract(worker_case):
  args, _, _, _, executed = worker_case
  argv = [item for key, value in args.items() for item in ("--" + key.replace("_", "-"), str(value))]
  with pytest.raises(executed): module.main(argv)
  with pytest.raises(SystemExit): module.main([*argv, "--runtime-root", "/untrusted"])


from test_pi_shell_execution import execution_case
from test_pi_shell_preparation import shell_case
from test_pi_shell_handoff import local, adoption_state


def test_worker_adopts_real_product_capsule_and_executes_once(worker_case, execution_case, local, monkeypatch):
  from agentcfg import pi_shell_handoff as handoff
  from agentcfg import pi_shell_execution as execution
  from test_pi_shell_handoff import transferred, product_binding, NONCE
  from test_pi_shell_execution import assert_closed
  args, calls, _, _, _ = worker_case
  monkeypatch.setattr(module, "adopt_handoff", handoff.adopt_handoff)
  monkeypatch.setattr(module, "exec_prepared", execution.exec_prepared)
  with transferred(execution_case, product_binding) as (original, fd, selected):
    args.update(handoff_fd=fd, nonce=NONCE, helper_identity=execution_case["helper_identity"],
      plan_digest=execution_case["plan_digest"], authorization_digest=handoff.authorization_digest(selected["authorization"]))
    monkeypatch.setattr(execution, "_fd_inventory", lambda: tuple(item for item, _ in original.snapshots))
    attempts = []
    def fake_exec(fd, argv, env):
      assert fd == original.helper_fd and env == {}
      attempts.append(argv)
      raise OSError("synthetic exec failure")
    monkeypatch.setattr(execution, "_exec_fd", fake_exec)
    with pytest.raises(ConfigError, match="pi-shell-exec-unavailable"): module.run(**args)
    assert len(attempts) == 1
    assert calls == ["R", "flush", "G", "devnull", ("dup2", 41, 0), ("close", 41)]
    for descriptor, _ in original.snapshots: assert_closed(descriptor)
