"""产品PID1的adopt-only入口；授权由受信父侧绑定，子侧不重开来源或取正文。"""

import argparse
import os
import re
import sys

from .pi_shell_execution import exec_prepared
from .pi_shell_handoff import adopt_handoff
from .schema import ConfigError
from .storage import Conflict


def _hex(value, length):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
    raise ConfigError("pi-shell-worker")


def run(*, handoff_fd, nonce, helper_identity, plan_digest, authorization_digest):
  if type(handoff_fd) is not int or handoff_fd <= 2: raise ConfigError("pi-shell-worker")
  _hex(nonce, 32)
  for value in (helper_identity, plan_digest, authorization_digest): _hex(value, 64)
  if os.getpid() != 1: raise Conflict("SHELL_PROCESS_SCOPE_UNAVAILABLE")
  # 登记和授权密封由父侧完成；固定就绪字节不携带私有输入。
  sys.stdout.buffer.write(b"R"); sys.stdout.buffer.flush()
  if os.read(0, 2) != b"G": raise Conflict("SHELL_INPUT_UNAVAILABLE")
  fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
  try: os.dup2(fd, 0)
  finally:
    if fd != 0: os.close(fd)
  with adopt_handoff(handoff_fd, nonce=nonce, helper_identity=helper_identity, plan_digest=plan_digest,
      expected_authorization=authorization_digest) as execution:
    exec_prepared(execution)
    raise ConfigError("pi-shell-exec-unavailable")


def main(argv=None):
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--handoff-fd", type=int, required=True)
  parser.add_argument("--nonce", required=True)
  parser.add_argument("--helper-identity", required=True)
  parser.add_argument("--plan-digest", required=True)
  parser.add_argument("--authorization-digest", required=True)
  return run(**vars(parser.parse_args(argv)))
