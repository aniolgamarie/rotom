"""现代CLI调用同一Host私有source与v3 core；查询从不注册或启动监督者。"""

from copy import deepcopy
import json
from pathlib import Path
import uuid

from .activity import digest
from .model_delegate import DelegationRuns, artifact_chunk
from .model_delegate_v3_execution import LogicalExecutions
from .model_delegate_v3_intents import _read_run, _document
from .schema import ConfigError
from .storage import Conflict, Tree


def selected(instance, run_id=None):
  if run_id is not None:
    key = DelegationRuns(instance / "pi-home/model-delegate/runs")._key(run_id)
    with Tree(instance) as tree: historical = tree.read("pi-home/model-delegate/runs/" + key, max_bytes=1024 * 1024)
    if historical is not None:
      record = json.loads(historical[0])
      if record.get("schema_version") == 3: return True
  with Tree(instance) as tree: raw = tree.read("pi-home/agentcfg-manifest.json", max_bytes=8 * 1024 * 1024)
  if raw is None: return False
  manifest = json.loads(raw[0])
  return (manifest.get("profile_id") == "pi-full" and "model-delegate" in manifest.get("plugins", [])
    and manifest.get("plugin_capabilities", {}).get("model-delegate", {}).get("capability_id") == "unified-delegate")


def saved(instance, bound, run_id):
  runs = DelegationRuns(instance / "pi-home/model-delegate/runs")
  record = runs._transaction(lambda tree: deepcopy(_read_run(tree, runs, run_id)))
  if record["origin"]["instance_id"] != digest({"instance": str(instance), "binding": bound["binding"]}):
    raise Conflict("DELEGATE_INSTANCE_MISMATCH")
  logical = LogicalExecutions(runs)
  result = logical.query(record["origin"], run_id, record["binding"])
  for action in result["actions"]:
    if action["physical_run_id"] is None: continue
    physical = runs.read(action["physical_run_id"])
    receipt = physical["receipt"]
    action.update(physical_state=physical["state"], task_succeeded=physical["verification"] == "verified-execution"
      and receipt is not None and receipt["terminal_status"] == "completed", termination_verified=physical["verification"] == "verified-execution"
      and receipt is not None and receipt["process_terminated"] is True and receipt["resources_reclaimed"] is True)
  return result


def execute(instance, bound, args, call):
  if args.action in {"status", "poll", "wait", "result"}:
    if not args.run_id: raise ConfigError("delegate-run-id-required")
    result = saved(instance, bound, args.run_id)
    if args.action == "result":
      active = next((row for row in reversed(result["actions"]) if row["termination_verified"]), None)
      if active is None: raise Conflict("DELEGATE_RESULT_UNVERIFIED")
      runs = DelegationRuns(instance / "pi-home/model-delegate/runs")
      physical = runs.read(active["physical_run_id"])
      result = artifact_chunk(instance / "pi-home/model-delegate", physical["receipt"], offset=args.offset, limit=args.limit)
    return result
  if args.action == "probe": raise Conflict("DELEGATE_STRICT_SEND_UNQUALIFIED")
  # 原Host.run在实际current owner下登记，CLI只读取已有引用；绝不自动打开backend。
  with Tree(instance / "pi-home/model-delegate") as tree: raw = tree.read("cli-source-ref.json", max_bytes=1024)
  if raw is None: raise Conflict("DELEGATE_SUPERVISOR_UNAVAILABLE")
  source = json.loads(raw[0])
  if set(source) != {"schema_version", "source_ref", "activation"} or source["schema_version"] != 3:
    raise Conflict("DELEGATE_SOURCE_STALE")
  request_id = args.idempotency_key or "cli-" + uuid.uuid4().hex
  if args.action == "cancel":
    if not args.run_id: raise ConfigError("delegate-run-id-required")
    action = {"schema_version": 3, "action": "cancel", "request_id": request_id, "run_id": args.run_id}
  else:
    if args.prompt_file is None: raise ConfigError("delegate-prompt-missing")
    path = args.prompt_file.absolute()
    with Tree(path.parent, private=False) as tree: raw = tree.read(path.name, max_bytes=65536)
    if raw is None: raise ConfigError("delegate-prompt-missing")
    try: text = raw[0].decode("utf8")
    except UnicodeError: raise ConfigError("delegate-prompt-invalid") from None
    if args.action in {"resume", "message"}:
      if not args.run_id: raise ConfigError("delegate-run-id-required")
      action = {"schema_version": 3, "action": "continue" if args.action == "resume" else "message",
        "request_id": request_id, "run_id": args.run_id, "text": text}
      if args.action == "resume": action["timeout_seconds"] = args.timeout_seconds
    else:
      if not all((args.backend, args.mode, args.model, args.provider, args.cwd)): raise ConfigError("delegate-explicit-request-required")
      if args.context_file or args.memory_file: raise Conflict("DELEGATE_CONTEXT_IMPORT_UNAVAILABLE")
      action = {"schema_version": 3, "action": "submit", "request_id": request_id,
        "backend": args.backend, "mode": args.mode, "preset": args.preset, "task": text,
        "model": {"provider_id": args.provider, "model_id": args.model}, "cwd": str(args.cwd.resolve(strict=True)),
        "timeout_seconds": args.timeout_seconds, "context_artifact": args.context_artifact,
        "feedback_required": args.feedback_required, "allow_workspace_write": args.allow_workspace_write,
        "worktree_root": str(args.worktree_root.resolve(strict=True)) if args.worktree_root else None}
  return call(instance, "delegate_action_v3", {"source_ref": source["source_ref"], "action": action})
