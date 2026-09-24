"""停止恢复只依赖已保存身份和机器定位；不解析模型、秘密或当前依赖锁。"""

import json
import os
from pathlib import Path
import re
import secrets
import sys
import tomllib
from types import SimpleNamespace
import uuid

from .activity import ExecutionStore, digest, protected
from .activity_linux import LinuxProcesses
from .activity_macos import MacProcesses
from .config import _machine_layers, read_local_document
from .merge import merge_layers
from .paths import safe_id
from .pi_catalog import validate
from .pi_lifecycle import guard
from .process import DependencyError
from .schema import ConfigError, validate_document
from .storage import Conflict, Tree
from .workspace_leases import WorkspaceLeases


ROOT = Path(__file__).resolve().parents[2]


def recovery_workspace(args):
  if args.agent != "pi":
    raise ConfigError("pi-recovery-agent")
  safe_id(args.profile)
  document = read_local_document(args.local)
  machine = document.get("machine")
  if not isinstance(machine, dict):
    raise ConfigError("pi-recovery-machine")
  selected = {key: machine[key] for key in ("id", "paths", "default_profile") if key in machine}
  # 只校验用于定位的字段，不因当前新模型/凭据/插件配置尚未就绪拒绝旧执行停止。
  validate_document("local", {"schema_version": document.get("schema_version"), "machine": selected})
  defaults, override = _machine_layers(selected, set())
  resolved = merge_layers((("defaults", defaults), ("local", override))).data
  profile_file = ROOT / "profiles" / (args.profile + ".toml")
  if profile_file.exists():
    with Tree(ROOT, private=False) as tree:
      raw = tree.read(profile_file.relative_to(ROOT).as_posix())
    if tomllib.loads(raw[0].decode()).get("agent") != "pi":
      raise ConfigError("agent-profile-mismatch")
  return SimpleNamespace(agent="pi", profile=args.profile, local_path=args.local,
    instance=Path(resolved["paths"]["instances_root"]) / "pi" / args.profile,
    state_root=Path(resolved["paths"]["state_root"]) / "pi" / args.profile,
    binding={"machine": resolved["id"], "local": str(args.local), "profile": args.profile})


def make_processes(workspace, lease):
  records = workspace.state_root / "activity/processes"
  if sys.platform == "linux":
    return LinuxProcesses(records)
  if sys.platform == "darwin":
    # 只找保存的旧锁/切片 helper，不要求当前模型或新的runtime已安装。
    matches = []
    for root in (workspace.instance / "runtimes").glob("*"):
      with Tree(root) as tree:
        raw = tree.read(".agentcfg-receipt.json")
      if raw is None:
        continue
      try:
        receipt = json.loads(raw[0])
        validate("runtime-receipt", receipt)
        if receipt["lock_identity"] == lease["lock_identity"] and receipt["slice_identity"] == lease["slice_identity"]:
          matches.append((root / "bin/pi-supervisor-macos", receipt["files"]["bin/pi-supervisor-macos"]["sha256"]))
      except (ValueError, KeyError, ConfigError):
        continue
    if len(matches) != 1:
      raise DependencyError("旧执行的macOS helper身份缺失或不唯一")
    return MacProcesses(matches[0][0], records, helper_digest=matches[0][1])
  raise DependencyError("此平台没有实现停止恢复")


def recover(args):
  if bool(args.stop) != bool(args.expect_plan) or args.expect_plan is not None and not re.fullmatch(r"[0-9a-f]{64}", args.expect_plan):
    raise ConfigError("pi-recovery-plan-arguments")
  workspace = recovery_workspace(args)
  with guard(workspace, allow_active=True, create=False):
    with Tree(workspace.state_root) as tree:
      raw = tree.read("activity/leases/" + safe_id(args.lease) + ".json")
    try:
      lease = json.loads(raw[0])
      validate("execution-lease", lease)
      if raw[1] != 0o600:
        raise ValueError()
    except (ValueError, TypeError, ConfigError):
      raise Conflict("旧执行记录缺失或损坏，不能推定已结束") from None
    processes = make_processes(workspace, lease)
    identity = processes.identity(os.getpid())
    owner = {"instance_id": lease["instance_id"], "supervisor_activation_id": uuid.uuid4().hex,
      "manager_activation_id": "recovery-only", "owner_nonce": secrets.token_hex(32), "supervisor_process_identity": identity}
    store = ExecutionStore(workspace.state_root, owner, processes, workspaces=WorkspaceLeases(identity["boot_id"]))
    if args.stop:
      result = store.recover_stop(args.lease, args.expect_plan, request_id="stop-" + args.expect_plan)
      return workspace, {"lease_id": result["lease_id"], "state": result["state"], "protected": protected(result)}
    plan = store.plan_stop(args.lease)
    return workspace, {"lease_id": plan["lease_id"], "plan_kind": plan["plan_kind"], "plan_digest": plan["plan_digest"],
      "expires_at": plan["expires_at"], "target_processes": len(plan["target_process_identities"]),
      "external_work": len(plan["external_work_ids"]), "workspace_leases": len(plan["workspace_write_lease_ids"])}
