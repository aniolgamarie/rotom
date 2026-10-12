"""仅自有临时账户、固定六场景；真实HTTP/模型调用恒为零。

断电、namespace全域终止及schema2 workspace-claims共存不在此证据范围。
"""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time


CASES = ("concurrent-claim", "updating-before-ledger", "claimed-before-ready", "ready-before-replace", "ready-after-replace", "unknown-then-deny")
LIMITS = {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000}
OP = "0" * 31 + "1"
ENV = {"HOME": "/work/home", "TMPDIR": "/work/tmp", "PATH": "/nonexistent", "PWD": "/work", "LC_ALL": "C.UTF-8", "XDG_CONFIG_HOME": "/work/home/config", "XDG_STATE_HOME": "/work/home/state", "XDG_DATA_HOME": "/work/home/data", "XDG_CACHE_HOME": "/work/home/cache"}


def require(value):
  if not value: raise RuntimeError("REVIEW_ACCOUNT_OS_FAILED")


def write(path, value):
  body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  try:
    os.fchmod(fd, 0o600)
    offset = 0
    while offset < len(body):
      written = os.write(fd, body[offset:]); require(written > 0); offset += written
    os.fsync(fd)
  finally: os.close(fd)


def request(index=1):
  return {"binding": {"operation_id": f"{index:032x}", "request_id": f"{index+100:032x}", "operation_digest": "a"*64,
    "context_digest": "b"*64, "reviewer_identity": "c"*64}, "scope": {"session_scope": "d"*32, "intent_ref": "e"*32},
    "pricing": {"identity": "f"*64, "currency": "USD", "input_units_per_million": 1000000, "output_units_per_million": 2000000,
      "cache_read_units_per_million": 500000, "cache_write_units_per_million": 3000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10}}


def paths(case):
  require(case in CASES)
  base = Path("/work/cases") / case
  return base, base / "account"


def raw(home):
  anchor = home / ".agentcfg-workspaces"
  with Tree(anchor) as tree:
    registry = json.loads(tree.read("registry.json")[0])
    require(registry["schema_version"] == 1 and registry["roots"] == [] and "claim_protocol" not in registry)
    require(set(os.listdir(tree.fd)) == {"registry.json", "reviewer-budget.json", "reviewer-budget"})
    sentinel = json.loads(tree.read("reviewer-budget.json")[0])
  with Tree(anchor / "reviewer-budget") as tree:
    require(set(os.listdir(tree.fd)) == {"instance.lock", "reviewer-ledger.json"})
    ledger = json.loads(tree.read("reviewer-ledger.json")[0])
  require(set(ledger["rows"]) == {OP})
  return sentinel, ledger["rows"][OP]


def facade(home): return ReviewerAccountLedger(account_home=home, limits=LIMITS)


def role(case, name, index):
  base, home = paths(case)
  require(name in ("claim", "cut", "reopen", "unknown", "deny", "deny-check"))
  require(index in (0, 1))
  if name == "reopen":
    try: value = facade(home)
    except Conflict as error:
      require(str(error) == "REVIEW_ACCOUNT_RECOVERY_REQUIRED"); result = "recovery-required"
    else:
      try: value.claim_attempt(OP)
      except Conflict as error:
        require(str(error) == "REVIEW_ATTEMPT_ALREADY_CLAIMED"); result = "conflict"
      else: raise RuntimeError("REVIEW_ACCOUNT_OS_FAILED")
    write(base / "reopen.json", {"reopen": result}); return
  value = facade(home)
  if name == "claim":
    require(case == CASES[0]); write(base / ("ready-" + str(index)), {"ready": True})
    deadline = time.monotonic() + 10
    while not (base / "go").exists():
      require(time.monotonic() < deadline); time.sleep(0.01)
    try: value.claim_attempt(OP)
    except Conflict as error:
      require(str(error) in ("REVIEW_ACCOUNT_BUSY", "REVIEW_ATTEMPT_ALREADY_CLAIMED"))
      claimed = False; conflict = str(error)
    else:
      claimed = True; conflict = None
      write(base / "fake-dispatch", {"synthetic": True, "actual_http_requests": 0, "actual_model_requests": 0})
    write(base / ("claim-" + str(index) + ".json"), {"claimed": claimed, "conflict": conflict}); return
  if name == "cut":
    require(case in CASES[1:5]); original = Tree.replace
    anchor = home / ".agentcfg-workspaces"
    def cut(code):
      write(base / "cut.json", {"case": case, "exit_code": code})
      os._exit(code)
    def replacement(tree, path, data, mode=0o600, *, expected):
      state = json.loads(data) if data is not None else None
      sentinel = tree.root == anchor and path == "reviewer-budget.json"
      claimed = tree.root == anchor / "reviewer-budget" and path == "reviewer-ledger.json" and state["rows"][OP]["attempt_claimed"] is True
      if sentinel and state["state"] == "ready":
        require(raw(home)[1]["attempt_claimed"] is True)
        if case == "ready-before-replace": cut(73)
      result = original(tree, path, data, mode, expected=expected)
      if sentinel and state["state"] == "updating" and case == "updating-before-ledger": cut(71)
      if claimed and case == "claimed-before-ready": cut(72)
      if sentinel and state["state"] == "ready" and case == "ready-after-replace": cut(74)
      return result
    Tree.replace = replacement
    value.claim_attempt(OP)
    raise RuntimeError("REVIEW_ACCOUNT_OS_FAILED")
  if name == "unknown":
    require(case == CASES[5]); value.claim_attempt(OP); value.commit_send(OP)
    require(value.get(OP)["requests"] is None and value.snapshot()["unknown_requests"] == 1)
    write(base / "unknown.json", {"row": value.get(OP), "snapshot": value.snapshot()})
  elif name == "deny":
    require(case == CASES[5]); require(value.get(OP)["requests"] is None)
    require(value.snapshot()["unknown_requests"] == 1)
    value.mark_sent(OP); value.finish(OP, requests=1, outcome="valid", decision="deny", reason_code="outside-user-scope")
  elif name == "deny-check":
    require(case == CASES[5])
    try: value.reserve(**request(2))
    except Conflict as error: require(str(error) == "REVIEW_INTENT_DENIED")
    else: raise RuntimeError("REVIEW_ACCOUNT_OS_FAILED")
    write(base / "deny-check.json", {"reopen": "deny-locked"})


def start(case, name, index=0):
  return subprocess.Popen([sys.executable, "-I", "-B", "-S", "/probe/worker.py", "--role", case, name, str(index)],
    env=ENV, cwd="/work", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def await_child(child, code=0): require(child.wait(timeout=10) == code)


def ready_claim_pair(case, children):
  base, _ = paths(case); pair = []
  # 构造器自身也持非阻塞账户锁；先逐一完成构造，再用go同步真正claim。
  for index in (0, 1):
    child = start(case, "claim", index); children.append(child); pair.append(child)
    deadline = time.monotonic() + 10
    while not (base / ("ready-" + str(index))).exists():
      require(time.monotonic() < deadline and child.poll() is None); time.sleep(0.01)
  return pair


def coordinate():
  global PHASE
  require(set(os.environ) == set(ENV) and dict(os.environ) == ENV)
  require(sys.argv == ["/probe/worker.py"])
  rows = []; children = []
  try:
    PHASE = "initialization"
    (Path("/work") / "cases").mkdir(mode=0o700)
    for i, case in enumerate(CASES):
      PHASE = "initialization"
      base, home = paths(case); base.mkdir(mode=0o700); home.mkdir(mode=0o700)
      value = facade(home); value.reserve(**request()); raw(home)
      if i == 0:
        PHASE = "concurrent-ready"
        pair = ready_claim_pair(case, children)
        PHASE = "claim"
        write(base / "go", {"go": True})
        for child in pair: await_child(child)
        outcomes = [json.loads((base / ("claim-" + str(j) + ".json")).read_bytes())["claimed"] for j in (0, 1)]
        require(outcomes.count(True) == 1 and outcomes.count(False) == 1)
        PHASE = "reopen"
        child = start(case, "reopen"); children.append(child); await_child(child)
        reopen = "conflict"
      elif i in (1, 2, 3, 4):
        PHASE = "cut"
        child = start(case, "cut"); children.append(child); await_child(child, 70+i)
        PHASE = "reopen"
        child = start(case, "reopen"); children.append(child); await_child(child)
        reopen = json.loads((base / "reopen.json").read_bytes())["reopen"]
      else:
        for name in ("unknown", "deny", "deny-check"):
          PHASE = name
          child = start(case, name); children.append(child); await_child(child)
        reopen = "deny-locked"
      PHASE = "observe"
      sentinel, row = raw(home)
      rows.append({"case": case, "status": "observed", "claim_returns": 1 if i == 0 else 0,
        "fake_dispatches": int((base / "fake-dispatch").exists()), "attempt_claimed": row["attempt_claimed"],
        "sentinel_state": sentinel["state"], "reopen": reopen, "synthetic_requests": 1 if i == 5 else 0,
        "actual_http_requests": 0, "actual_model_requests": 0})
    result = {"schema_version": 1, "status": "observed", "cases": rows,
      "scope_termination": "not-independently-observed", "product_gate": False}
    write(Path("/work/result.json"), result)
    print(json.dumps({"schema_version": 1, "status": "observed", "cases": 6, "product_gate": False}, separators=(",", ":")), flush=True)
  finally:
    for child in children:
      if child.poll() is None:
        child.terminate()
        try: child.wait(timeout=1)
        except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=1)


PHASES = ("environment", "argv", "imports", "initialization", "concurrent-ready", "claim", "reopen", "cut", "unknown", "deny", "deny-check", "observe", "cleanup")
PHASE = "environment"


def diagnostic(phase, environment, argv):
  require(phase in PHASES)
  keys = sorted({key if type(key) is str and re.fullmatch("[A-Za-z_][A-Za-z0-9_]{0,63}", key) else "invalid_environment_key" for key in environment})
  return {"schema_version": 1, "status": "failed", "phase": phase, "environment_keys": keys[:32],
    "environment_keys_truncated": len(keys) > 32, "environment_matches": dict(environment) == ENV,
    "pwd_present": "PWD" in environment, "pwd_matches_chdir": environment.get("PWD") == "/work",
    "argv": {"count": min(len(argv), 16), "count_truncated": len(argv) > 16,
      "entry_matches": bool(argv) and argv[0] == "/probe/worker.py",
      "role_shape": len(argv) == 5 and argv[0] == "/probe/worker.py" and argv[1] == "--role"
        and argv[2] in CASES and argv[3] in ("claim", "cut", "reopen", "unknown", "deny", "deny-check") and argv[4] in ("0", "1")},
    "product_gate": False}


def record_failure(value):
  # 固定私有工件，只含阶段、键名和形状；首个失败保留，不覆盖或输出底层异常。
  try: write(Path("/work/failure.json"), value)
  except Exception: pass


def entry():
  global PHASE, ReviewerAccountLedger, Conflict, Tree
  try:
    PHASE = "environment"
    require(dict(os.environ) == ENV)
    PHASE = "argv"
    require(sys.argv == ["/probe/worker.py"] or diagnostic("argv", os.environ, sys.argv)["argv"]["role_shape"] is True)
    PHASE = "imports"
    sys.path[:0] = ["/probe/src", "/python-deps"]
    from agentcfg.pi_reviewer_account import ReviewerAccountLedger
    from agentcfg.storage import Conflict, Tree
    if len(sys.argv) == 1: coordinate()
    else:
      PHASE = sys.argv[3]
      role(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    return 0
  except Exception:
    record_failure(diagnostic(PHASE, os.environ, sys.argv))
    return 5


if __name__ == "__main__": raise SystemExit(entry())
