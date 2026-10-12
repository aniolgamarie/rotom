"""固定bwrap探针info读取；仅扩展探针协议，不改变生产进程注册schema。

bubblewrap 0.13.0的ns_infos包含cgroup/ipc/mnt/net/pid/uts；info writer在
namespace_ids_write后关闭FD。必须等EOF再判断，完整JSON前缀不能提前放行。
"""

import json
import math
import os
import selectors
import time

from .schema import ConfigError


REQUIRED = frozenset(("child-pid", "mnt-namespace", "pid-namespace"))
OPTIONAL = frozenset(("user-namespace", "ipc-namespace", "net-namespace", "uts-namespace", "cgroup-namespace"))
MAX_BYTES = 65535
MAX_ID = 2**63 - 1


def _pairs(items):
  value = {}
  for key, item in items:
    if key in value: raise ValueError()
    value[key] = item
  return value


def _constant(value):
  raise ValueError()


def read_namespace_info(fd, *, timeout=10):
  """有界、限时地读取一个完整JSON；调用方仍拥有输入FD。"""
  try:
    if (type(fd) is not int or fd < 0 or type(timeout) not in (int, float)
        or not math.isfinite(timeout) or timeout <= 0):
      raise ValueError()
    deadline = time.monotonic() + timeout
    body = bytearray()
    with selectors.DefaultSelector() as poll:
      poll.register(fd, selectors.EVENT_READ)
      while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not poll.select(remaining): raise ValueError()
        if time.monotonic() >= deadline: raise ValueError()
        try: chunk = os.read(fd, min(4096, MAX_BYTES + 1 - len(body)))
        except InterruptedError: continue
        if not chunk: break
        body.extend(chunk)
        if len(body) > MAX_BYTES: raise ValueError()
    if not body: raise ValueError()
    value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_constant)
    if (type(value) is not dict or not REQUIRED <= value.keys() or value.keys() - REQUIRED - OPTIONAL
        or any(type(item) is not int or not 1 <= item <= MAX_ID for item in value.values())):
      raise ValueError()
    return value
  except Exception:
    raise ConfigError("pi-shell-probe-info") from None
