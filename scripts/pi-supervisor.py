#!/usr/bin/env python3
"""Pi 监督进程入口；只接受父管理器交付的私人启动意图和实例锁句柄。"""

import argparse
import json
import os
from pathlib import Path
import sys

# 已密封运行包不能在导入时生成 __pycache__。
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_host import HostSupervisor


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--bootstrap-fd", type=int, required=True)
  parser.add_argument("--lease-fd", type=int, required=True)
  parser.add_argument("--instance-fd", type=int, required=True)
  parser.add_argument("--ready-fd", type=int)
  parser.add_argument("argv", nargs=argparse.REMAINDER)
  args = parser.parse_args()
  if min(args.bootstrap_fd, args.lease_fd, args.instance_fd) < 3 or len({args.bootstrap_fd, args.lease_fd, args.instance_fd}) != 3:
    return 2
  if args.ready_fd is not None and (args.ready_fd < 3 or args.ready_fd in (args.bootstrap_fd, args.lease_fd, args.instance_fd)):
    return 2
  with os.fdopen(args.bootstrap_fd, "rb") as stream:
    raw = stream.read(1024 * 1024 + 1)
  if len(raw) > 1024 * 1024:
    return 2
  config = json.loads(raw)
  info = os.fstat(args.instance_fd)
  actual = os.stat(config["instance_root"], follow_symlinks=False)
  if (info.st_dev, info.st_ino) != (actual.st_dev, actual.st_ino):
    return 4
  if (args.argv[1:] if args.argv[:1] == ["--"] else args.argv) != config["argv"]:
    return 2
  supervisor = HostSupervisor(config, lease_fd=args.lease_fd)
  if "delegate_request" in config:
    if args.ready_fd is None:
      return 2
    return supervisor.run_delegate(args.ready_fd)
  if args.ready_fd is not None:
    return 2
  return supervisor.run()


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception as error:
    sys.stderr.write("Pi监督启动或控制失败；持久活动保护未被自动清除。\n")
    sys.exit(getattr(error, "exit_code", 6))
