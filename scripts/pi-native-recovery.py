#!/usr/bin/env python3
"""原生恢复验收的固定第一方进程；不是模型可调用的任意命令入口。"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.deployment import json_bytes
from agentcfg.pi_host import HostSupervisor
from agentcfg.pi_lifecycle import guard
from agentcfg.pi_recovery import recovery_workspace
from agentcfg.pi_supervisor import SpawnCommand, closed
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree, instance_lock


def main(argv=None):
  if os.environ.get("AGENTCFG_NATIVE_VALIDATION") != "1" or sys.platform not in ("linux", "darwin"):
    raise ConfigError("pi-native-recovery-authorization")
  parser = argparse.ArgumentParser(allow_abbrev=False)
  mode = parser.add_mutually_exclusive_group(required=True)
  mode.add_argument("--owner-input", type=Path)
  mode.add_argument("--worker-marker", type=Path)
  args = parser.parse_args(argv)
  if args.worker_marker is not None:
    if not args.worker_marker.is_absolute() or args.worker_marker.name != "recovery-worker.json": raise ConfigError("pi-native-recovery-path")
    with Tree(args.worker_marker.parent) as tree: tree.write_new(args.worker_marker.name, json_bytes({"pid": os.getpid()}))
    while True: signal.pause()
  path = args.owner_input
  if not path.is_absolute() or path.name != "recovery-input.json": raise ConfigError("pi-native-recovery-path")
  with Tree(path.parent) as tree: raw = tree.read(path.name)
  value = json.loads(raw[0])
  closed(value, ("config", "local", "profile", "nonce"))
  if Path(value["local"]) != path.parent / "fixture/local.toml": raise ConfigError("pi-native-recovery-path")
  workspace = recovery_workspace(SimpleNamespace(agent="pi", local=Path(value["local"]), profile=value["profile"]))
  config = value["config"]
  if (workspace.instance != Path(config["instance_root"]) or workspace.state_root != Path(config["state_root"])
      or not workspace.instance.is_relative_to(path.parent / "fixture") or not workspace.state_root.is_relative_to(path.parent / "fixture")):
    raise ConfigError("pi-native-recovery-path")
  with guard(workspace), Tree(workspace.state_root, create=True) as tree, instance_lock(tree) as lease_fd:
    host = HostSupervisor(config, lease_fd=lease_fd)
    lease = host.store.allocate(kind="external", execution_id="native-recovery-target", task_id=None, attempt_id="native-recovery-attempt",
      lock_identity=config["lock_identity"], slice_identity=config["slice_identity"], policy_digest=config["policy_digest"], candidate_digest=None, planned_workspaces=[])
    command = SpawnCommand((sys.executable, "-B", "-I", str(Path(__file__).absolute()), "--worker-marker", str(path.parent / "recovery-worker.json")),
      Path(config["cwd"]), {"HOME": os.environ["HOME"], "PATH": os.defpath, "AGENTCFG_NATIVE_VALIDATION": "1"})
    started = host.store.start(lease["lease_id"], host.store.owner, spawn=lambda current: host.spawn(command, current))
    host.activate(started)
    with Tree(path.parent) as output:
      output.write_new("recovery-owner.json", json_bytes({"nonce": value["nonce"], "lease_id": lease["lease_id"],
        "owner": host.store.owner["supervisor_process_identity"], "target": started["process_identity"]}))
    if sys.platform == "darwin":
      # 测试侧helper将整体停止本进程作用域；worker保持活动，由恢复路径经自己的helper留下终止收据。
      # 武装后等待kill-control，不在owner死亡前主动停止worker。
      with Tree(path.parent) as output:
        output.write_new("recovery-armed.json", json_bytes({"nonce": value["nonce"], "pid": os.getpid()}))
    while True: signal.pause()


if __name__ == "__main__":
  try: sys.exit(main())
  except Exception:
    sys.stderr.write("原生停止恢复探测未完成。\n")
    sys.exit(5)
