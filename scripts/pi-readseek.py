#!/usr/bin/env python3
"""同一监督租约内依次选择文件和隔离计算；第三方子进程没有监督 RPC 凭据。"""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_checks import check_environment, linux_verifier_argv, macos_verifier_policy
from agentcfg.pi_control import request
from agentcfg.pi_supervisor import closed
from agentcfg.storage import Tree, ensure_private


def rpc(method, args):
  reply = request(os.environ["AGENTCFG_SUPERVISOR_ENDPOINT"], os.environ["AGENTCFG_SUPERVISOR_CAPABILITY"],
    {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": method, "args": args})
  if not reply.get("ok"): raise RuntimeError("READSEEK_DRIVER_REJECTED")
  return reply["result"]


def sandbox(check, temporary, denied):
  ensure_private(temporary)
  inherited = {}
  if sys.platform == "linux":
    try:
      for item in denied:
        path = Path(item)
        if path.is_file() and not path.is_symlink():
          fd = os.memfd_create("agentcfg-denied", 0); os.set_inheritable(fd, True)
          inherited[str(path)] = fd
      return linux_verifier_argv(check, temporary=temporary, denied_paths=denied, denied_fds=inherited), list(inherited.values())
    except Exception:
      for fd in inherited.values(): os.close(fd)
      raise
  if sys.platform == "darwin":
    profile = macos_verifier_policy(check, temporary=temporary, denied_paths=denied)
    with Tree(temporary) as tree: tree.write_new("check.sb", profile.encode())
    return ("/usr/bin/sandbox-exec", "-f", str(temporary / "check.sb"), *check["argv"]), []
  raise RuntimeError("READSEEK_PLATFORM_UNAVAILABLE")


def selection_limit():
  # stdout/stderr 写固定私人文件；内核限制保证目录清单超限不会无限占用磁盘。
  resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False); parser.add_argument("--input", type=Path, required=True)
  args = parser.parse_args()
  with Tree(args.input.parent) as tree: raw = tree.read(args.input.name)
  if raw is None: return 5
  value = json.loads(raw[0])
  closed(value, ("check", "temporary", "lease_id", "grant_generation", "denied_paths", "readseek_driver"))
  plan = value["readseek_driver"]; closed(plan, ("operation_id", "jobs"))
  if not isinstance(plan["jobs"], list) or len(plan["jobs"]) > 3: return 2
  authority = {"lease_id": value["lease_id"], "grant_generation": value["grant_generation"]}
  if rpc("authorize", authority).get("valid") is not True: return 4
  home = Path(value["check"]["cwd"]); scratch = Path(value["temporary"])
  deadline = time.monotonic() + value["check"]["timeout_seconds"]
  for index, job in enumerate(plan["jobs"]):
    closed(job, ("category", "check", "denied_paths", "search_root"))
    if rpc("authorize", authority).get("valid") is not True: return 4
    temporary = scratch / ("selection-" + str(index))
    argv, descriptors = sandbox(job["check"], temporary, job["denied_paths"])
    streams = []
    try:
      with Tree(home) as tree:
        for stream in ("stdout", "stderr"):
          with tree.parent("selection-" + str(index) + "." + stream, create=True) as (fd, name):
            streams.append(os.fdopen(os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=fd), "wb"))
      remaining = min(deadline - time.monotonic(), job["check"]["timeout_seconds"])
      if remaining <= 0: return 5
      result = subprocess.run(argv, cwd=job["check"]["cwd"], env=check_environment(job["check"], temporary),
        stdin=subprocess.DEVNULL, stdout=streams[0], stderr=streams[1], pass_fds=tuple(descriptors),
        timeout=remaining, preexec_fn=selection_limit)
      if result.returncode != 0: return 5
    finally:
      for stream in streams: stream.close()
      for fd in descriptors: os.close(fd)
  if rpc("ordinary_readseek_export", {"operation_id": plan["operation_id"]}).get("exported") is not True: return 5
  if time.monotonic() >= deadline or rpc("authorize", authority).get("valid") is not True: return 4
  argv, _ = sandbox(value["check"], scratch / "compute", value["denied_paths"])
  os.chdir(value["check"]["cwd"])
  os.execvpe(argv[0], argv, check_environment(value["check"], scratch / "compute"))
  return 6


if __name__ == "__main__":
  try: sys.exit(main())
  except Exception:
    sys.stderr.write("READSEEK_DRIVER_FAILED\n")
    sys.exit(5)
