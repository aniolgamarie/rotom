"""受管工作流的固定工作区与检查入口；不接受任意 shell 或模型提供的新命令。"""

import hashlib
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


def check_binding_snapshot(host, payload):
  """原管理通道的只读来源快照；不创建 lease、目录或能力。"""
  closed(payload, ("check_id", "task_id", "cwd"))
  from .pi_trusted_checks import contract_digest, host_context
  if any(type(payload[key]) is not str or not payload[key] for key in ("check_id", "task_id", "cwd")):
    raise Conflict("CHECK_BINDING_REQUIRED")
  manifest = host.manifest()
  task = manifest["options"].get("task_keeper", {})
  if (manifest.get("profile_id") != "pi-full" or "task-keeper" not in manifest.get("plugins", [])
      or not task.get("enabled") or payload["check_id"] not in task.get("check_ids", [])):
    raise Conflict("CHECK_BINDING_REQUIRED")
  safe_id(payload["task_id"])
  state = Path(host.config["instance_root"]) / "pi-home/task-keeper"
  candidate = state / "worktrees" / payload["task_id"]
  cwd = configured_path(payload["cwd"])
  if cwd != candidate or cwd.resolve(strict=True) != cwd:
    raise Conflict("CHECK_WORKSPACE_MISMATCH")
  host.store.workspaces.identify(cwd)
  binding = manifest["options"]["checks"][payload["check_id"]]
  if binding["project_root"] != task["project_root"]: raise Conflict("CHECK_PROJECT_BINDING")
  declarations = manifest["options"]["paths"]["roots"]
  executable = configured_path(binding["executable"])
  extra = []
  for name in binding.get("read_roots", []):
    if name not in declarations: raise Conflict("CHECK_READ_ROOT_UNBOUND")
    extra.append(configured_path(declarations[name]["path"]))
  context = host_context(host, manifest, None, payload["check_id"], cwd)
  check = compile_check(binding, candidate=cwd, executable=executable,
    read_roots=[executable, *extra], trusted_context=context)
  denied = manifest["options"].get("permissions", {}).get("denied_roots", [])
  if task["project_root"] in denied or "project" in denied:
    raise Conflict("CHECK_PROJECT_DENIED")
  for name in denied:
    if cwd.is_relative_to(configured_path(declarations[name]["path"])):
      raise Conflict("CHECK_PROJECT_DENIED")
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    base = cwd if rule["root_ref"] == "project" else configured_path(declarations[rule["root_ref"]]["path"])
    if cwd.is_relative_to(base / rule["relative_path"]):
      raise Conflict("CHECK_PROJECT_DENIED")
  return {"schema_version": 1, "check_id": payload["check_id"], "task_id": payload["task_id"],
    "contract_digest": contract_digest(check)}


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
  process_scope = "default"
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
    # Task Keeper工作树helper调用Git；普通文件和固定命令不走此入口。
    host.store.workspaces.identify_git(cwd)
    target = host.root / "activity/workspace-results" / (lease["lease_id"] + ".json")
    ensure_private(target.parent)
    value = {"schema_version": 1, "input": payload, "output": str(target), "lease_id": lease["lease_id"],
      "grant_generation": lease["grant_generation"], "protected_roots": host.config.get("protected_roots", [])}
    if manifest.get("profile_id") == "pi-full":
      from .pi_input_snapshots import host_scope
      value["input_scope"] = host_scope(host, manifest, source=source, candidate=candidate, creating=payload["operation"] == "create")
    entry = host.runtime_root / "runtime/workspace-main.mjs"
    argv = (host.config["engine"], str(entry), "--input", str(host.root / "activity/auxiliary-inputs" / (lease["lease_id"] + ".json")), "--runtime-root", str(host.runtime_root))
  elif program == "check":
    closed(payload, ("check_id", "cwd", "task_id"), ("contract_digest",))
    if lease["kind"] != "check" or lease["task_id"] != payload["task_id"] or payload["check_id"] not in task["check_ids"]:
      raise Conflict("CHECK_BINDING_REQUIRED")
    safe_id(payload["task_id"])
    candidate = state / "worktrees" / payload["task_id"]
    cwd = configured_path(payload["cwd"]).resolve(strict=True)
    if not cwd.is_relative_to(candidate):
      raise Conflict("CHECK_WORKSPACE_MISMATCH")
    if manifest.get("profile_id") == "pi-full" and (cwd != candidate or configured_path(payload["cwd"]) != cwd):
      raise Conflict("CHECK_WORKSPACE_MISMATCH")
    binding = manifest["options"]["checks"][payload["check_id"]]
    if binding["project_root"] != root_id: raise Conflict("CHECK_PROJECT_BINDING")
    executable = configured_path(binding["executable"])
    if manifest.get("profile_id") != "pi-full": executable = executable.resolve(strict=True)
    declarations = manifest["options"].get("paths", {}).get("roots", {})
    extra = []
    for name in binding.get("read_roots", []):
      if name not in declarations: raise Conflict("CHECK_READ_ROOT_UNBOUND")
      path = configured_path(declarations[name]["path"]).resolve(strict=True)
      if path == Path("/") or path == Path.home(): raise Conflict("CHECK_READ_ROOT_TOO_BROAD")
      extra.append(path)
    context = None
    if manifest.get("profile_id") == "pi-full":
      from .pi_trusted_checks import host_context
      if "contract_digest" not in payload: raise Conflict("CHECK_CONTRACT_REQUIRED")
      context = host_context(host, manifest, lease, payload["check_id"], cwd)
    check = compile_check(binding, candidate=cwd, executable=executable, read_roots=[executable, *extra], trusted_context=context)
    if "contract_digest" in payload:
      from .pi_trusted_checks import contract_digest
      expected = payload["contract_digest"]
      if (context is None or type(expected) is not str or len(expected) != 64
          or any(char not in "0123456789abcdef" for char in expected)
          or expected != contract_digest(check)):
        raise Conflict("CHECK_CONTRACT_CHANGED")
    private = [Path(path).resolve(strict=False) for path in host.config.get("protected_roots", [])]
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
    if manifest.get("profile_id") == "pi-full" and sys.platform == "linux":
      from .pi_pid_namespace import host_namespace_binary
      binary = host_namespace_binary(host)
      with Tree(host.runtime_root) as tree:
        helper = tree.read("bin/pi-bwrap", max_bytes=16 * 1024 * 1024)
      if binary != host.runtime_root / "bin/pi-bwrap" or helper is None or helper[1] != 0o700:
        raise Conflict("CHECK_NAMESPACE_HELPER_UNAVAILABLE")
      if host_namespace_binary(host) != binary:
        raise Conflict("CHECK_NAMESPACE_HELPER_UNAVAILABLE")
      with Tree(host.runtime_root) as tree:
        current = tree.read("bin/pi-bwrap", max_bytes=16 * 1024 * 1024)
      if current is None or current[:2] != helper[:2]:
        raise Conflict("CHECK_NAMESPACE_HELPER_UNAVAILABLE")
      value["namespace_helper"] = {"path": str(binary), "sha256": hashlib.sha256(helper[0]).hexdigest()}
      process_scope = "linux-pid-namespace"
    entry = host.repository / "scripts/pi-project-check"
    argv = (sys.executable, "-I", str(entry), "--input", str(host.root / "activity/auxiliary-inputs" / (lease["lease_id"] + ".json")))
  else:
    raise DependencyError("未声明的辅助执行入口")
  if not entry.is_file() or entry.is_symlink() or not lease["planned_workspaces"]:
    raise Conflict("AUXILIARY_EXECUTION_NOT_READY")
  planned = host.store.workspaces.identify(cwd)
  if not any(item["workspace_key"] == planned["workspace_key"] for item in lease["planned_workspaces"]):
    raise Conflict("WORKSPACE_BUSY")
  ensure_private(temporary)
  env = environment(home=temporary)
  for name in ("SSH_AUTH_SOCK", "SSH_TTY", "EDITOR", "VISUAL", "TMUX", "TMUX_PANE"):
    env.pop(name, None)
  env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(host.server.endpoint),
    AGENTCFG_SUPERVISOR_CAPABILITY=host.service.issue_capability("worker", lease["lease_id"]),
    AGENTCFG_EXECUTION_LEASE_ID=lease["lease_id"], AGENTCFG_PYTHON=sys.executable,
    AGENTCFG_SUPERVISOR_CLIENT=str(host.repository / "scripts/pi-control.py"))
  with Tree(host.root) as tree:
    tree.write_immutable("activity/auxiliary-inputs/" + lease["lease_id"] + ".json", json_bytes(value))
  return SpawnCommand(argv, cwd, env, capture_root=capture, process_scope=process_scope)
