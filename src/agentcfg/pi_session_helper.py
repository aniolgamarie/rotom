"""Pi 公开扩展的匿名管道租约 helper；不输出原始输入或异常正文。"""
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

# 直接脚本目录不能遮蔽 stdlib secrets 等模块；-I 也排除用户 site/PYTHONPATH。
if __name__ == "__main__":
  directory = Path(__file__).resolve().parent
  sys.path[:] = [str(directory.parent), *(value for value in sys.path if value != str(directory))]
try:
  from agentcfg import pi_session_guard as guard, run_owners
except Exception:
  raise SystemExit(4) from None


def _wait_for_host(claims):
  """仅等待原 Popen 的登记；不重试 claim，不从当前 PID 补造 host。"""
  parent = os.getppid()
  identity = run_owners.observed_process_identity(parent)
  if identity is None:
    raise ValueError()
  record = guard._current(claims.workspace, claims.run_id)
  manager = record["manager_identity"]
  marker = guard._verify_guard(claims.workspace, record)
  claims.guard_identity = marker
  start = time.monotonic()
  if type(start) not in (int, float) or not math.isfinite(start):
    raise ValueError()
  last, deadline = start, start + 2
  while True:
    now = time.monotonic()
    if (type(now) not in (int, float) or not math.isfinite(now) or now < last or now > deadline
        or os.getppid() != parent or run_owners.observed_process_identity(parent) != identity):
      raise ValueError()
    last = now
    record = guard._current(claims.workspace, claims.run_id)
    if (record["manager_identity"] != manager
        or guard._verify_guard(claims.workspace, record) != marker):
      raise ValueError()
    if record["host_identity"] is not None:
      claims._owner()
      return
    if now >= deadline:
      raise ValueError()
    time.sleep(min(0.02, deadline - now))


def main():
  claims = None
  try:
    raw = os.environ.get("ROTOM_PI_CONTROL_CONTEXT", "")
    if len(raw.encode("utf-8")) > 16384:
      return 4
    value = json.loads(raw, object_pairs_hook=run_owners._pairs,
      parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
    if (type(value) is not dict or set(value) != {"state_root", "instance", "profile", "binding", "run_id", "initial_session", "lease_fd"}
        or type(value["binding"]) is not dict or set(value["binding"]) != {"machine", "local", "profile"}
        or value["profile"] != value["binding"]["profile"]):
      return 4
    workspace = SimpleNamespace(agent="pi", instance=run_owners._absolute(value["instance"]),
      state_root=run_owners._absolute(value["state_root"]), profile=value["profile"], binding=value["binding"])
    claims = guard.Claims(workspace, value["run_id"], helper=True)
    guard.source_identity()
    _wait_for_host(claims)
    if value["initial_session"] is not None:
      if value["lease_fd"] != 3:
        return 4
      claims.claim(value["initial_session"], inherited_fd=3)
    elif value["lease_fd"] is not None:
      return 4
    sequence = 0
    while True:
      line = sys.stdin.buffer.readline(16385)
      if not line:
        return 0
      sequence += 1
      ok = False
      try:
        if len(line) > 16384 or not line.endswith(b"\n"):
          raise ValueError()
        request = json.loads(line, object_pairs_hook=run_owners._pairs)
        if request.get("seq") != sequence:
          raise ValueError()
        guard.handle(claims, request)
        ok = True
      except Exception:
        pass
      print(json.dumps({"seq": sequence, "ok": ok}), flush=True)
      if not ok:
        return 4
  except Exception:
    return 4
  finally:
    if claims is not None:
      problem = sys.exc_info()[0]
      try:
        claims.close()
      except Exception:
        if problem is None:
          return 4
      except BaseException:
        if problem is None:
          raise


if __name__ == "__main__":
  raise SystemExit(main())
