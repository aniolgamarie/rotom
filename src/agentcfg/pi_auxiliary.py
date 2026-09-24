"""受管工作流的固定工作区与检查入口；不接受任意 shell 或模型提供的新命令。"""

import json
from pathlib import Path
import sys

from .activity import digest
from .deployment import json_bytes
from .paths import configured_path, safe_id
from .pi_checks import compile_check
from .pi_supervisor import SpawnCommand, closed
from .process import environment, DependencyError
from .storage import Conflict, Tree, ensure_private


def resolve_auxiliary(host, lease, program, payload):
  with Tree(host.runtime_root) as runtime:
    raw = runtime.read("runtime/commands.json")
  registry = json.loads(raw[0]) if raw else {}
  declared = registry.get("programs", {}).get(program)
  if not declared or declared["kind"] != lease["kind"]:
    raise DependencyError("辅助入口未进入当前运行包")
  manifest = host.manifest()
  task = manifest["options"].get("task_keeper", {})
  if not task.get("enabled"):
    raise Conflict("MANAGED_WORKFLOWS_DISABLED")
  root_id = task["project_root"]
  source = configured_path(manifest["options"]["paths"]["roots"][root_id]["path"]).resolve(strict=True)
  state = Path(host.config["instance_root"]) / "pi-home/task-keeper"
  capture = host.root / "activity/outputs" / lease["lease_id"]
  temporary = host.root / "activity/auxiliary-homes" / lease["lease_id"]
  ensure_private(temporary)
  env = environment(home=temporary)
  for name in ("SSH_AUTH_SOCK", "SSH_TTY", "EDITOR", "VISUAL", "TMUX", "TMUX_PANE"):
    env.pop(name, None)
  env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(host.server.endpoint),
    AGENTCFG_SUPERVISOR_CAPABILITY=host.service.issue_capability("worker", lease["lease_id"]),
    AGENTCFG_EXECUTION_LEASE_ID=lease["lease_id"], AGENTCFG_PYTHON=sys.executable,
    AGENTCFG_SUPERVISOR_CLIENT=str(host.repository / "scripts/pi-control.py"))
  if program == "workspace":
    closed(payload, ("operation", "cwd", "stateRoot", "jobId"), ("baselineTree", "extraInputs", "timeoutMs"))
    if lease["kind"] != "external" or payload["operation"] not in ("create", "snapshot") or payload["stateRoot"] != str(state):
      raise Conflict("WORKSPACE_OPERATION_BINDING")
    safe_id(payload["jobId"])
    cwd = configured_path(payload["cwd"]).resolve(strict=True)
    candidate = state / "worktrees" / payload["jobId"]
    allowed = source if payload["operation"] == "create" else candidate
    if not cwd.is_relative_to(allowed) or lease["task_id"] != payload["jobId"]:
      raise Conflict("WORKSPACE_OPERATION_BINDING")
    target = host.root / "activity/workspace-results" / (lease["lease_id"] + ".json")
    ensure_private(target.parent)
    value = {"schema_version": 1, "input": payload, "output": str(target), "lease_id": lease["lease_id"],
      "grant_generation": lease["grant_generation"], "protected_roots": host.config.get("protected_roots", [])}
    entry = host.runtime_root / "runtime/workspace-main.mjs"
    argv = (host.config["engine"], str(entry), "--input", str(host.root / "activity/auxiliary-inputs" / (lease["lease_id"] + ".json")), "--runtime-root", str(host.runtime_root))
  elif program == "check":
    closed(payload, ("check_id", "cwd", "task_id"))
    if lease["kind"] != "check" or lease["task_id"] != payload["task_id"] or payload["check_id"] not in task["check_ids"]:
      raise Conflict("CHECK_BINDING_REQUIRED")
    safe_id(payload["task_id"])
    candidate = state / "worktrees" / payload["task_id"]
    cwd = configured_path(payload["cwd"]).resolve(strict=True)
    if not cwd.is_relative_to(candidate):
      raise Conflict("CHECK_WORKSPACE_MISMATCH")
    binding = manifest["options"]["checks"][payload["check_id"]]
    if binding["project_root"] != root_id: raise Conflict("CHECK_PROJECT_BINDING")
    executable = configured_path(binding["executable"]).resolve(strict=True)
    declarations = manifest["options"].get("paths", {}).get("roots", {})
    extra = []
    for name in binding.get("read_roots", []):
      if name not in declarations: raise Conflict("CHECK_READ_ROOT_UNBOUND")
      path = configured_path(declarations[name]["path"]).resolve(strict=True)
      if path == Path("/") or path == Path.home(): raise Conflict("CHECK_READ_ROOT_TOO_BROAD")
      extra.append(path)
    check = compile_check(binding, candidate=cwd, executable=executable, read_roots=[executable, *extra])
    private = [Path(path).resolve(strict=True) for path in host.config.get("protected_roots", [])]
    denied_ids = manifest["options"].get("permissions", {}).get("denied_roots", [])
    if root_id in denied_ids or "project" in denied_ids: raise Conflict("CHECK_PROJECT_DENIED")
    denied = [configured_path(declarations[name]["path"]).resolve(strict=True) for name in denied_ids]
    for rule in manifest["permission_policy"]["rules"]:
      if rule["kind"] != "file" or rule["effect"] != "deny": continue
      root = cwd if rule["root_ref"] == "project" else configured_path(declarations[rule["root_ref"]]["path"]).resolve(strict=True)
      denied.append(root / rule["relative_path"])
    if any(cwd.is_relative_to(path) for path in denied): raise Conflict("CHECK_PROJECT_DENIED")
    for path in extra:
      if any(path.is_relative_to(secret) or secret.is_relative_to(path) and cwd.is_relative_to(secret) for secret in [*private, *denied]):
        raise Conflict("CHECK_READ_ROOT_PRIVATE")
    # 候选可位于私人实例中；不能为读取依赖而挂载候选的整个私人祖先。
    denied += [path for path in private if not cwd.is_relative_to(path)]
    value = {"check": check, "temporary": str(temporary), "lease_id": lease["lease_id"], "grant_generation": lease["grant_generation"], "denied_paths": sorted({str(path) for path in denied})}
    entry = host.repository / "scripts/pi-project-check"
    argv = (sys.executable, "-I", str(entry), "--input", str(host.root / "activity/auxiliary-inputs" / (lease["lease_id"] + ".json")))
  else:
    raise DependencyError("未声明的辅助执行入口")
  if not entry.is_file() or entry.is_symlink() or not lease["planned_workspaces"]:
    raise Conflict("AUXILIARY_EXECUTION_NOT_READY")
  planned = host.store.workspaces.identify(cwd)
  if not any(item["workspace_key"] == planned["workspace_key"] for item in lease["planned_workspaces"]):
    raise Conflict("WORKSPACE_BUSY")
  with Tree(host.root) as tree:
    tree.write_immutable("activity/auxiliary-inputs/" + lease["lease_id"] + ".json", json_bytes(value))
  return SpawnCommand(argv, cwd, env, capture_root=capture)
