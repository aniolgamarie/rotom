"""固定、有界的合成后台写入；仅由获准探针在隔离内启动。"""

import json
import os
from pathlib import Path
import re
import sys
import time


WORK_ROOT = Path(__file__).parent.parent


def main(nonce):
  if type(nonce) is not str or not re.fullmatch(r"[0-9a-f]{32}", nonce): raise ValueError()
  fd = os.open(WORK_ROOT / "project/heartbeat", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  try:
    value = {"schema_version": 1, "phase": "heartbeat", "nonce": nonce, "pid": os.getpid(),
      "namespaces": {name: os.readlink("/proc/self/ns/" + name) for name in ("pid", "net", "user", "mnt", "ipc", "uts")}}
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"); sys.stdout.flush()
    # 额外自限三十秒；退出计时本身不是父侧终止证明。
    for _ in range(600):
      if os.write(fd, (nonce + "\n").encode()) != 33: raise OSError()
      time.sleep(0.05)
  finally: os.close(fd)


if __name__ == "__main__":
  try:
    if len(sys.argv) != 2: raise ValueError()
    main(sys.argv[1])
  except Exception:
    sys.stderr.write("shell probe heartbeat unavailable\n"); sys.exit(5)
