"""ReadSeek 的显式工具绑定与私有计算沙箱准备，不在监督器内启动原生程序。"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import shlex
import shutil
import os
import stat

from .activity import digest
from .deployment import json_bytes
from .paths import configured_path, relative_path
from .pi_checks import compile_check
from .pi_guarded_files import GuardedFiles, root_identity
from .pi_readseek_results import project_path, validate_request, worker_parameters, fresh_anchors
from .pi_readseek_snapshot import export_snapshot
from .pi_readseek_select import selection_jobs, selected_paths
from .pi_readseek_selection import selection_manifest
from .pi_supervisor import closed
from .process import DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


def prepare(controller, principal, args):
  closed(args, ("operation_id", "session_id", "cwd", "tool_name", "input"))
  host, operations = controller.host, controller.operations
  manifest = host.manifest()
  if principal.role != "manager" or "pi-readseek" not in manifest.get("plugins", []): raise Conflict("READSEEK_MANAGER_REQUIRED")
  if not isinstance(args["session_id"], str) or not 1 <= len(args["session_id"]) <= 200: raise ConfigError("readseek-session")
  if len(controller.pending) >= 128: raise Conflict("READSEEK_CAPACITY")
  options = manifest["options"]; settings = options.get("readseek", {})
  name = settings.get("node_tool_ref")
  binding = options.get("external_tools", {}).get(name)
  if not binding or binding.get("args", []) or binding.get("interactive", False): raise ConfigError("readseek-node-binding")
  rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command"
    and row["command_ref"] == "tool:" + name and "bash" in row["tool_ids"] and "execute" in row["operations"]]
  if not any(row["effect"] == "allow" for row in rules) or any(row["effect"] == "deny" for row in rules): raise Conflict("PERMISSION_DENIED")
  with Tree(host.runtime_root) as tree:
    registry = tree.read("runtime/commands.json"); profile = tree.read("runtime/profile.json")
    contracts = tree.read("runtime/readseek-tool-contracts.json")
    programs = json.loads(registry[0])["programs"] if registry else {}
    installed = json.loads(profile[0]) if profile else {}
    if (programs.get("readseek") != {"entrypoint": "runtime/readseek-process.mjs", "kind": "external", "engine": "node"}
        or tree.read("runtime/readseek-process.mjs") is None or contracts is None): raise DependencyError("ReadSeek监督入口未安装")
  if binding.get("version") != installed.get("toolchains", {}).get("node") or not binding.get("version"):
    raise DependencyError("ReadSeek计算需要锁定Node版本的明确绑定")
  executable = configured_path(binding["executable"])
  native = host.runtime_root / "bin/readseek"
  if not native.is_file() or native.is_symlink(): raise DependencyError("ReadSeek原生依赖未安装")
  params = validate_request(json.loads(contracts[0]), args["tool_name"], args["input"])
  writing = args["tool_name"] in ("readSeek_write", "readSeek_edit") or args["tool_name"] == "readSeek_rename" and params.get("apply", True)
  permission_tool = "write" if args["tool_name"] == "readSeek_write" else "edit" if writing else "grep" if args["tool_name"] in ("readSeek_grep", "readSeek_search", "readSeek_refs", "readSeek_def") else "read"
  read_operation = "search" if permission_tool == "grep" else "read"
  cwd = configured_path(args["cwd"]).resolve(strict=True)
  raw_path = params.get("path", ".")
  path = Path(raw_path) if Path(raw_path).is_absolute() else cwd / raw_path
  payload = {"path": str(path)}
  if permission_tool == "write": payload["content"] = params["content"]
  elif permission_tool == "edit": payload["edits"] = []
  elif permission_tool == "grep": payload["pattern"] = params.get("pattern", "")
  key = digest({"owner": host.store.owner, "operation_id": args["operation_id"]})
  if key in controller.pending:
    saved = controller.pending[key]
    if saved["request_digest"] != digest(args): raise Conflict("READSEEK_OPERATION_CONFLICT")
    return saved["ticket"]
  base = operations.prepare(principal, {"operation_id": args["operation_id"], "role_id": "main", "cwd": str(cwd), "tool_name": permission_tool, "input": payload})
  value = deepcopy(operations.record(base["operation_id"]))
  lease = host.store.read(value["lease_id"])
  try:
    project = Path(value["grant"]["root_bindings"]["project"]["path"])
    path = project_path(project, str(path))
    if any(executable.is_relative_to(root) or host.runtime_root.is_relative_to(root) for root in
        (configured_path(row["path"]).resolve(strict=True) for row in options.get("paths", {}).get("roots", {}).values())):
      raise Conflict("READSEEK_RUNTIME_SCOPE")
    if not writing:
      lease = host.store.allocate(kind="external", execution_id="readseek-" + key, task_id=None, attempt_id=key,
        lock_identity=host.config["lock_identity"], slice_identity=host.config["slice_identity"], policy_digest=value["policy_digest"],
        candidate_digest=None, planned_workspaces=[])
      value["lease_id"] = lease["lease_id"]
      value["grant"]["grant_generation"] = lease["grant_generation"]
    timeout = settings.get("max_seconds", 300)
    if type(timeout) is not int or not 1 <= timeout <= 1800: raise ConfigError("readseek-timeout")
    value["grant"]["expires_at"] = (operations.now() + timedelta(seconds=timeout + 300)).isoformat()
    value["grant"]["grant_digest"] = digest({key: entry for key, entry in value["grant"].items() if key != "grant_digest"})
    operations.inputs[key] = value
    session_key = controller.session_key(args["session_id"], value)
    if session_key in controller.active_sessions: raise Conflict("READSEEK_SESSION_BUSY")
    session_root = host.root / "activity/readseek-sessions" / session_key
    ticket = {"kind": "readseek", "operation_id": key, "lease_id": lease["lease_id"], "write": writing, "timeout_seconds": timeout}
    controller.pending[key] = {"ticket": ticket, "request_digest": digest(args), "file_operation": value,
      "params": {**params, **({"path": str(path)} if "path" in params else {})}, "path": str(path), "project": str(project), "cwd": str(cwd),
      "tool": args["tool_name"], "session": args["session_id"], "node": str(executable), "native": str(native),
      "permission_tool": permission_tool, "read_operation": read_operation, "manifest_digest": digest(manifest), "node_ref": name,
      "session_key": session_key, "session_root": str(session_root), "snapshot_root": str(session_root / "snapshot"), "cache_root": str(session_root / "cache")}
    controller.active_sessions[session_key] = key
    return ticket
  except Exception:
    if writing or lease["kind"] != "host": host.store.abort_allocation(lease["lease_id"], host.store.owner)
    operations.inputs.pop(key, None)
    raise


def stage(controller, principal, args):
  closed(args, ("operation_id",))
  if principal.role != "manager": raise Conflict("READSEEK_MANAGER_REQUIRED")
  pending = controller.pending.get(args["operation_id"])
  if pending is None: raise Conflict("READSEEK_OPERATION_UNKNOWN")
  host, operations = controller.host, controller.operations
  key = args["operation_id"]; value = pending["file_operation"]; ticket = pending["ticket"]
  if key in controller.records or key in operations.commands.records: raise Conflict("READSEEK_ALREADY_STAGED")
  manifest = host.manifest()
  if digest(manifest) != pending["manifest_digest"]: raise Conflict("READSEEK_OPERATION_STALE")
  files = GuardedFiles(operations.policy(value, reserved=True), mutation=lambda *_: None,
    max_read_bytes=1024 * 1024 if ticket["write"] else 16 * 1024 * 1024)
  files.policy.current()
  path, project = Path(pending["path"]), Path(pending["project"])
  settings = manifest["options"].get("readseek", {})
  home = host.root / "activity/readseek-homes" / key; ensure_private(home)
  directory = path.is_dir() or pending["tool"] == "readSeek_rename" and pending["params"].get("workspace", False)
  pending["selection_jobs"] = selection_jobs(controller, pending) if directory else []
  pending["directory"] = directory
  if controller.active_sessions.get(pending["session_key"]) != key: raise Conflict("READSEEK_SESSION_BUSY")
  reset_snapshot(pending)
  command = {"schema_version": 1, "operation_id": key, "request_digest": pending["request_digest"], "lease_id": ticket["lease_id"],
    "command_ref": pending["node_ref"], "tool_name": "readseek", "manifest_digest": pending["manifest_digest"],
    "roots": {"readseek-home": {"path": str(home), "identity": root_identity(home)},
      "readseek-snapshot": {"path": pending["snapshot_root"], "identity": root_identity(pending["snapshot_root"])},
      "readseek-cache": {"path": pending["cache_root"], "identity": root_identity(pending["cache_root"])}},
    "temporary": str(Path(pending["session_root"]) / "scratch" / key),
    "grant_generation": value["grant"]["grant_generation"], "expires_at": value["grant"]["expires_at"], "stdin_enabled": True}
  rg = None
  if pending["tool"] == "readSeek_grep":
    from .pi_git_status import validate_binding
    rg_name = settings.get("rg_tool_ref")
    if not rg_name: raise ConfigError("readseek-selection-tool-required")
    _, rg_binding, rg_root = validate_binding(manifest["options"], name=rg_name)
    rg = configured_path(rg_binding["executable"])
    if configured_path(rg_root["path"]).resolve(strict=True) != project or rg.is_relative_to(project): raise Conflict("READSEEK_SELECTION_EXECUTABLE")
    rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command" and row["command_ref"] == "tool:" + rg_name
      and "bash" in row["tool_ids"] and "execute" in row["operations"]]
    if not any(row["effect"] == "allow" for row in rules) or any(row["effect"] == "deny" for row in rules): raise Conflict("PERMISSION_DENIED")
    pending["rg"] = str(rg)
    command["readseek_auxiliary_checks"] = [compile_check({"executable": str(rg), "args": [], "project_root": "readseek-home",
      "timeout_seconds": ticket["timeout_seconds"], "foreground": True}, candidate=home, executable=rg, read_roots=[rg])]
  node = Path(pending["node"])
  check = compile_check({"executable": str(node), "args": [str(host.runtime_root / "runtime/readseek-process.mjs")],
    "project_root": "readseek-home", "timeout_seconds": ticket["timeout_seconds"], "foreground": True}, candidate=home,
    executable=node, read_roots=[host.runtime_root, node, Path(pending["snapshot_root"]), Path(pending["cache_root"]), *([rg] if rg else [])])
  check["write_roots"] = [str(home), pending["snapshot_root"], pending["cache_root"]]
  check["service_environment"] = {"PI_OFFLINE": "1", "PI_CODING_AGENT_DIR": str(home / "pi"), "READSEEK_STATE_DIR": str(home / "state"),
    "HF_HOME": str(home / "models"), "HF_HUB_OFFLINE": "1", "PATH": str(home / "bin") + ":/usr/bin:/bin",
    "HF_HUB_CACHE": str(host.runtime_root / "data/readseek/hub"), "HF_HUB_DISABLE_SYMLINKS": "1",
    "AGENTCFG_READSEEK_SELECTION": str(home / "selection.json")}
  if rg:
    check["service_environment"].update(AGENTCFG_READSEEK_RG=str(rg), AGENTCFG_READSEEK_SNAPSHOT=pending["snapshot_root"])
  check["binding_digest"] = digest({key: entry for key, entry in check.items() if key != "binding_digest"})
  command.update(check=check, denied_paths=[pending["project"]], grant=value["grant"])
  if directory:
    with Tree(host.runtime_root) as tree:
      registry = json.loads(tree.read("runtime/commands.json")[0])["programs"]
      if (registry.get("readseek-driver") != {"entrypoint": "supervisor/scripts/pi-readseek.py", "kind": "external", "engine": "python"}
          or tree.read("supervisor/scripts/pi-readseek.py") is None): raise DependencyError("ReadSeek目录选择驱动未安装")
    command["readseek_driver"] = {"operation_id": key, "jobs": pending["selection_jobs"]}
  else:
    populate(controller, pending, command, reserved=True)
  with Tree(host.root) as tree: tree.write_new("activity/ordinary-commands/" + key + ".json", json_bytes(command))
  operations.commands.records[key] = command
  return operations.commands.summary(command)


def populate(controller, pending, command, *, reserved):
  host = controller.host; key = command["operation_id"]
  home = host.root / "activity/readseek-homes" / key
  path, project = Path(pending["path"]), Path(pending["project"])
  files = GuardedFiles(controller.operations.policy(pending["file_operation"], reserved=reserved), mutation=lambda *_: None,
    max_read_bytes=1024 * 1024 if pending["ticket"]["write"] else 16 * 1024 * 1024)
  files.policy.current()
  categories = selected_paths(home, pending["selection_jobs"], project) if pending["selection_jobs"] else None
  if categories is not None:
    selected = sorted({name for paths in categories.values() for name in paths})
  elif pending["directory"]: selected = None
  else:
    selected = [path.relative_to(project).as_posix()] if path.exists() else []
    if not selected and pending["tool"] != "readSeek_write": raise FileNotFoundError()
    if not selected: files.policy.authorize(pending["permission_tool"], "create", str(path))
  search = Path(pending["cwd"]) if pending["params"].get("workspace", False) else path
  snapshot = export_snapshot(files, pending["permission_tool"], project, Path(pending["snapshot_root"]), selected_paths=selected,
    operation=pending["read_operation"], scan_relative=search.relative_to(project).as_posix() if selected is None else ".")
  if not snapshot["scope_complete"] and pending["ticket"]["write"]: raise Conflict("READSEEK_INCOMPLETE_WORKSPACE")
  controller.bind(command, pending["file_operation"], session=pending["session"], tool=pending["tool"], params=pending["params"], snapshot=snapshot,
    home=home, permission_tool=pending["permission_tool"], read_operation=pending["read_operation"])
  request = {"schema_version": 1, "operation_id": key, "tool": pending["tool"], "params": worker_parameters(snapshot, pending["params"]),
    "snapshot_digest": snapshot["snapshot_digest"], "snapshot_root": snapshot["snapshot_root"], "cache_root": pending["cache_root"],
    "native_binary": pending["native"], "settings": host.manifest()["options"].get("readseek", {}).get("settings", {}),
    "anchors": fresh_anchors(snapshot, controller.records[key]["anchors"]),
    "working_directory": str(Path(snapshot["snapshot_root"]) / Path(pending["cwd"]).relative_to(project))}
  ensure_private(Path(request["working_directory"]))
  # 无显式路径时，cwd 应是调用者的查询目录；将其规范化为现有 path 参数而不扩大到项目根。
  if "path" not in request["params"]: request["params"]["path"] = str(Path(snapshot["snapshot_root"]) / path.relative_to(project))
  groups = categories if categories is not None and "rg" not in categories else {
    "cached": [row["path"] for row in snapshot["entries"]], "others": []}
  with Tree(home) as tree:
    tree.write_new("request.json", json_bytes(request))
    tree.write_new("selection.json", json_bytes(selection_manifest(snapshot, groups)))
    script = "#!/bin/sh\nexec " + shlex.quote(pending["node"]) + " " + shlex.quote(str(host.runtime_root / "runtime/readseek-git-main.mjs")) + ' "$@"\n'
    tree.replace("bin/git", script.encode(), mode=0o700, expected=None)
    if pending.get("rg"):
      script = "#!/bin/sh\nexec " + shlex.quote(pending["node"]) + " " + shlex.quote(str(host.runtime_root / "runtime/readseek-rg-main.mjs")) + ' "$@"\n'
      tree.replace("pi/bin/rg", script.encode(), mode=0o700, expected=None)


def driver_export(controller, principal, args):
  closed(args, ("operation_id",))
  pending = controller.pending.get(args["operation_id"])
  if not pending or principal.role != "worker" or principal.lease_id != pending["ticket"]["lease_id"]:
    raise Conflict("READSEEK_DRIVER_IDENTITY")
  if args["operation_id"] in controller.records: raise Conflict("READSEEK_ALREADY_STAGED")
  command = controller.operations.commands.records.get(args["operation_id"])
  if not command or command.get("readseek_driver", {}).get("operation_id") != args["operation_id"]:
    raise Conflict("READSEEK_DRIVER_IDENTITY")
  if digest(controller.host.manifest()) != pending["manifest_digest"]: raise Conflict("READSEEK_OPERATION_STALE")
  for root in command["roots"].values():
    if root_identity(root["path"]) != root["identity"]: raise Conflict("ROOT_IDENTITY")
  populate(controller, pending, command, reserved=False)
  return {"exported": True}


def reset_snapshot(pending):
  """仅在该会话预留已独占时清理上一份私人副本，缓存路径保持稳定。"""
  if not shutil.rmtree.avoids_symlink_attacks: raise DependencyError("ReadSeek私人副本清理需要基于目录句柄的rmtree")
  session = Path(pending["session_root"])
  with Tree(session, create=True) as tree:
    with tree.parent("snapshot") as (fd, name):
      try: info = os.stat(name, dir_fd=fd, follow_symlinks=False)
      except FileNotFoundError: info = None
      if info is not None:
        if stat.S_ISDIR(info.st_mode): shutil.rmtree(name, dir_fd=fd)
        elif stat.S_ISLNK(info.st_mode): os.unlink(name, dir_fd=fd)
        else: raise Conflict("READSEEK_SNAPSHOT_LAYOUT")
  ensure_private(Path(pending["snapshot_root"]))
  ensure_private(Path(pending["cache_root"]))
