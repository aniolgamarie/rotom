#!/usr/bin/env python3
"""只为固定 benchmark 入口创建同 UID、无外部接口的临时命名空间。"""
import ctypes
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]


def enter_namespace():
  uid, gid = os.getuid(), os.getgid()
  libc = ctypes.CDLL(None, use_errno=True)
  if libc.unshare(0x10000000 | 0x40000000) != 0:
    raise OSError(ctypes.get_errno(), "unprivileged_namespace_unavailable")
  Path("/proc/self/uid_map").write_text(f"{uid} {uid} 1\n")
  Path("/proc/self/setgroups").write_text("deny\n")
  Path("/proc/self/gid_map").write_text(f"{gid} {gid} 1\n")
  interfaces = [line.split(":", 1)[0].strip() for line in Path("/proc/self/net/dev").read_text().splitlines()[2:] if ":" in line]
  if os.getuid() != uid or os.getgid() != gid or interfaces != ["lo"]:
    raise OSError("namespace_identity_or_network_unverified")


def protected_root_visible():
  return Path("/").stat().st_uid == 0 and Path("/tmp").stat().st_uid == 0


def main(argv=None):
  argv = list(sys.argv[1:] if argv is None else argv)
  if not argv or argv[0] not in {"run", "calibrate"} or "--allow-native" not in argv or "--isolated-netns" in argv:
    return 2
  try:
    enter_namespace()
    if not protected_root_visible():
      print("namespace_trusted_root_ancestor_unmapped", file=sys.stderr)
      return 5
    os.execv(sys.executable, [sys.executable, str(ROOT / "tools/bench/herdr_upgrade.py"), *argv])
  except OSError:
    print("unprivileged_namespace_unavailable_or_unverified", file=sys.stderr)
    return 5
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
