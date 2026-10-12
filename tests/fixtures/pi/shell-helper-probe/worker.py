"""只用于获准探针的可信PID1；没有产品receipt或执行许可的含义。"""

import argparse
import json
import os
from pathlib import Path
import re
import sys

# -I -S：只加载明确只读挂载的自有模块和Rotom Python依赖，不处理.pth。
sys.dont_write_bytecode = True
sys.path[:0] = ["/probe/supervisor/src", "/python-deps"]

from agentcfg.pi_shell_execution import exec_prepared
from agentcfg.pi_shell_handoff import adopt_handoff
from agentcfg.schema import ConfigError


CASES = ("boundary", "helper-mismatch", "descendants")
NAMESPACES = ("pid", "net", "user", "mnt", "ipc", "uts")


def emit(value):
  sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
  sys.stdout.flush()


def namespaces():
  return {name: os.readlink("/proc/self/ns/" + name) for name in NAMESPACES}


def bootstrap(case, nonce):
  """先提供真实身份事实；父侧未明确放行前不进入helper准备。"""
  with open("/proc/self/uid_map", "rb") as stream:
    raw = stream.read(16385)
  if not 1 <= len(raw) <= 16384: raise ValueError()
  uid_map = raw.decode("ascii", errors="strict")
  return {"schema_version": 1, "phase": "bootstrap", "case_id": case, "nonce": nonce,
    "uid": os.geteuid(), "owners": {"root": os.stat("/").st_uid, "usr": os.stat("/usr").st_uid,
      "bash": os.stat("/usr/bin/bash").st_uid},
    "user_namespace": os.readlink("/proc/self/ns/user"), "uid_map": uid_map}


def run(case, nonce, helper_identity, handoff_fd, plan_digest, work_root):
  if (case not in CASES or not re.fullmatch(r"[0-9a-f]{32}", nonce)
      or not re.fullmatch(r"[0-9a-f]{64}", helper_identity)
      or type(handoff_fd) is not int or handoff_fd <= 2
      or type(plan_digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", plan_digest)
      or not isinstance(work_root, Path) or not work_root.is_absolute() or ".." in work_root.parts or work_root == Path("/")
      or os.getpid() != 1): raise ValueError()
  emit(bootstrap(case, nonce))
  signal = os.read(0, 2)
  if signal != b"G": raise ValueError()
  # stdin是bootstrap明确保留的唯一gate；helper/payload只继承空输入。
  null = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
  try: os.dup2(null, 0, inheritable=True)
  finally: os.close(null)
  # 故意使用错误身份的case只测试失败关闭，不替代真正成功的正控制。
  selected = "0" * 64 if case == "helper-mismatch" else helper_identity
  try:
    with adopt_handoff(handoff_fd, nonce=nonce, helper_identity=selected, plan_digest=plan_digest) as execution:
      if case == "helper-mismatch": raise RuntimeError()
      canary = os.open(work_root / "outside/canary", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
      info = os.fstat(canary); identity = (info.st_dev, info.st_ino)
      try:
        os.set_inheritable(canary, True)
        emit({"schema_version": 1, "phase": "prepared", "case_id": case, "nonce": nonce,
          "helper_identity": helper_identity, "plan_digest": plan_digest, "namespaces": namespaces()})
        exec_prepared(execution)
      finally:
        try:
          current = os.fstat(canary)
          if (current.st_dev, current.st_ino) == identity: os.close(canary)
        except OSError: pass
      raise RuntimeError()
  except ConfigError as error:
    if case == "helper-mismatch" and error.code == "pi-shell-handoff":
      emit({"schema_version": 1, "phase": "helper-rejected", "case_id": case, "nonce": nonce, "code": "pi-shell-handoff"})
      return
    raise


class _Parser(argparse.ArgumentParser):
  def error(self, message):
    # 不将底层argparse诊断或参数值写入私有报告通道。
    raise ValueError()


def main(argv=None):
  parser = _Parser(allow_abbrev=False)
  parser.add_argument("--probe-worker", choices=CASES, required=True)
  parser.add_argument("--nonce", required=True)
  parser.add_argument("--helper-identity", required=True)
  parser.add_argument("--handoff-fd", type=int, required=True)
  parser.add_argument("--plan-digest", required=True)
  parser.add_argument("--work-root", type=Path, required=True)
  args = parser.parse_args(argv)
  run(args.probe_worker, args.nonce, args.helper_identity, args.handoff_fd, args.plan_digest, args.work_root)


if __name__ == "__main__":
  try: main()
  except Exception:
    sys.stderr.write("shell probe worker unavailable\n")
    sys.exit(5)
