"""固定联网媒体命令通过私人中继执行，复用普通命令租约及终止证据。"""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
from urllib.parse import urlsplit
import uuid

from .activity import digest, protected
from .deployment import json_bytes
from .paths import configured_path, relative_path
from .pi_checks import compile_check
from .pi_guarded_files import root_identity
from .pi_services import file_snapshot, socket_snapshot
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


def media_arguments(operation, payload, *, javascript=None):
  if operation == "youtube-info":
    closed(payload, ("video_id",))
    if not isinstance(payload["video_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", payload["video_id"]):
      raise ConfigError("pi-web-youtube-id")
    if javascript is None: raise ConfigError("pi-web-youtube-javascript-binding")
    return ["--ignore-config", "--no-config-locations", "--no-plugin-dirs", "--no-cache-dir", "--no-playlist",
      "--no-js-runtimes", "--js-runtimes", "node:" + str(javascript), "--no-remote-components", "--no-progress",
      "--proxy", "AGENTCFG_WEB_PROXY", "--format", "best[protocol=https]/bestvideo[protocol=https]",
      "--print", "%(.{url,duration})j", "--skip-download", "--", "https://www.youtube.com/watch?v=" + payload["video_id"]]
  if operation != "remote-frame": raise ConfigError("pi-web-cli-operation")
  closed(payload, ("url", "seconds"))
  if (not isinstance(payload["url"], str) or len(payload["url"]) > 16384
      or any(ord(char) < 32 or ord(char) == 127 for char in payload["url"])): raise ConfigError("pi-web-media-url")
  url = urlsplit(payload["url"])
  try:
    if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None or url.port not in (None, 443) or url.fragment:
      raise ValueError()
  except ValueError: raise ConfigError("pi-web-media-url") from None
  seconds = payload["seconds"]
  if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
    raise ConfigError("pi-web-media-position")
  return ["-nostdin", "-v", "error", "-protocol_whitelist", "https,tls,tcp,httpproxy", "-format_whitelist", "mov,matroska,webm",
    "-http_proxy", "AGENTCFG_WEB_PROXY", "-ss", str(seconds), "-i", payload["url"], "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]


def selected_tool(manifest, field, section="media"):
  options = manifest["options"]
  name = options.get("web", {}).get(section, {}).get(field)
  tool = options.get("external_tools", {}).get(name)
  if not tool or tool.get("args", []) or tool.get("interactive", False): raise ConfigError("pi-web-media-tool-binding")
  rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command" and row["command_ref"] == "tool:" + name
    and "bash" in row["tool_ids"] and "execute" in row["operations"]]
  if not any(row["effect"] == "allow" for row in rules) or any(row["effect"] == "deny" for row in rules): raise Conflict("PERMISSION_DENIED")
  executable = configured_path(tool["executable"])
  roots = options.get("paths", {}).get("roots", {})
  reads = [executable]
  for ref in tool.get("read_roots", []):
    if ref not in roots or roots[ref]["purpose"] != "read": raise ConfigError("pi-web-media-read-root")
    reads.append(configured_path(roots[ref]["path"]).resolve(strict=True))
  return name, tool, executable, reads


def prepare(operations, principal, args):
  closed(args, ("operation_id", "operation", "input", "socket_path", "token"), ("cwd", "github_authorization"))
  host = operations.host; manifest = host.manifest(); options = manifest["options"]
  if principal.role != "manager" or manifest.get("bootstrap") or "pi-web" not in manifest.get("plugins", []): raise Conflict("WEB_CLI_CONTEXT")
  if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200: raise ConfigError("pi-operation-id")
  if not isinstance(args["token"], str) or not re.fullmatch(r"[0-9a-f]{64}", args["token"]): raise ConfigError("pi-web-cli-token")
  reclaim(operations)
  cloning = args["operation"] == "git-clone"
  if not cloning and ("cwd" in args or "github_authorization" in args): raise ConfigError("pi-web-cli-fields")
  if cloning and "cwd" not in args: raise ConfigError("pi-web-github-cwd")
  credential = args.get("github_authorization")
  if credential is not None and (not isinstance(credential, str) or not 1 <= len(credential) <= 16384
      or any(ord(char) < 32 or ord(char) == 127 for char in credential)): raise ConfigError("pi-web-github-credential")
  service = "github" if cloning else "public"
  if service not in manifest.get("web_services", {}): raise Conflict("WEB_CLI_SERVICE_UNBOUND")
  if cloning and "https://github.com" not in manifest["web_services"]["github"].get("origins", []): raise Conflict("WEB_CLI_SERVICE_UNBOUND")
  socket_path = configured_path(args["socket_path"])
  if socket_path.name != "proxy.sock" or len(str(socket_path).encode()) > 100: raise ConfigError("pi-web-cli-socket")
  with Tree(socket_path.parent) as tree:
    if tree.fd is None: raise Conflict("WEB_CLI_SOCKET_MISSING")
  sockets = [socket_snapshot(str(socket_path))]
  name, binding, executable, reads = selected_tool(manifest, "git_tool_ref" if cloning else "yt_dlp_tool_ref" if args["operation"] == "youtube-info" else "ffmpeg_tool_ref", "github_clone" if cloning else "media")
  javascript = None; auxiliary = []
  if args["operation"] == "youtube-info":
    _, _, javascript, dependencies = selected_tool(manifest, "javascript_tool_ref")
    reads.extend(dependencies)
    auxiliary.append(javascript)
  argv = None if cloning else media_arguments(args["operation"], args["input"], javascript=javascript)
  key = digest({"owner": host.store.owner, "operation_id": args["operation_id"]}); request_digest = digest(args)
  if key in operations.commands.records:
    old = operations.commands.records[key]
    if old["request_digest"] != request_digest: raise Conflict("ORDINARY_OPERATION_CONFLICT")
    return operations.commands.summary(old)
  if len(operations.commands.records) >= 128: raise Conflict("ORDINARY_OPERATION_CAPACITY")
  timeout = min(options.get("web", {}).get("github_clone" if cloning else "media", {}).get("max_seconds", 60), binding.get("timeout_seconds", 60))
  directory = uuid.uuid4().hex; home = host.root / "activity/web-cli" / directory
  ensure_private(home)
  expires = (datetime.now(timezone.utc) + timedelta(seconds=timeout + 300)).isoformat()
  marker = {"schema_version": 1, "kind": "web-cli-input", "instance_id": host.store.owner["instance_id"],
    "directory": directory, "expires_at": expires, "lease_id": None}
  lease = None; destination = None; source_roots = {}
  try:
    if cloning:
      from .pi_web_git import prepare_destination, clone_arguments
      destination, lease, source_roots = prepare_destination(operations, principal, args)
      argv = clone_arguments(args["input"], destination)
    python = Path(sys.executable).resolve(strict=True)
    script = host.runtime_root / "supervisor/scripts/pi-web-cli.py"
    source = host.runtime_root / "supervisor/src/agentcfg/pi_web_relay.py"
    if not script.is_file() or not source.is_file(): raise ConfigError("pi-web-cli-driver-missing")
    port = 20000 + secrets.randbelow(40000)
    with Tree(home) as tree:
      tree.write_new("owner.json", json_bytes(marker))
      tree.write_immutable("input.json", json_bytes({"argv": [str(executable), *argv], "socket_path": str(socket_path),
        "port": port, "token": args["token"], "timeout_seconds": timeout, **({"github_authorization": credential} if credential else {})}))
    check = compile_check({"executable": str(python), "args": ["-B", "-I", str(script), "--input", str(home / "input.json")],
      "project_root": "web-cli", "timeout_seconds": timeout, "foreground": True}, candidate=home, executable=python,
      read_roots=[*reads, Path(sys.base_prefix).resolve(), script, source, socket_path])
    check.update(write_roots=[str(destination)] if destination else [], socket_paths=[str(socket_path)], web_cli_port=port)
    check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
    native = [compile_check({"executable": str(path), "args": [], "project_root": "web-cli", "timeout_seconds": timeout, "foreground": True},
      candidate=home, executable=path) for path in [executable, *auxiliary]]
    roots = options.get("paths", {}).get("roots", {})
    denied = [configured_path(row["path"]) for row in roots.values() if row["purpose"] in ("project", "write") and not (destination and destination.is_relative_to(configured_path(row["path"]))) ]
    denied += [configured_path(roots[ref]["path"]) for ref in options.get("permissions", {}).get("denied_roots", [])]
    protected_roots = [configured_path(path) for path in host.config.get("protected_roots", [])]
    if any(path.is_relative_to(blocked) or blocked.is_relative_to(path) for path in reads for blocked in protected_roots):
      raise Conflict("WEB_CLI_TOOL_SCOPE")
    # 只读挂载第一方脚本；保护父目录不能把这两份可信源码重新遮住。
    denied += [path for path in protected_roots if not any(allowed.is_relative_to(path) for allowed in (home, script, source))]
    for rule in manifest["permission_policy"]["rules"]:
      if rule["kind"] != "file" or rule["effect"] != "deny": continue
      if rule["root_ref"] not in roots: raise Conflict("WEB_CLI_DENIAL_UNBOUND")
      base = configured_path(roots[rule["root_ref"]]["path"])
      denied.append(base if rule["relative_path"] == "." else base / relative_path(rule["relative_path"]))
    if any(path.is_relative_to(blocked) for path in [home, *([destination] if destination else []), *map(Path, check["read_roots"])] for blocked in denied): raise Conflict("WEB_CLI_TOOL_SCOPE")
    lease = lease or host.store.allocate(kind="external", execution_id="web-cli-" + key, task_id=None, attempt_id=key,
      lock_identity=host.config["lock_identity"], slice_identity=host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]),
      candidate_digest=None, planned_workspaces=[])
    marker["lease_id"] = lease["lease_id"]
    with Tree(home) as tree: tree.write_state("owner.json", json_bytes(marker))
    value = {"schema_version": 1, "operation_id": key, "request_digest": request_digest, "lease_id": lease["lease_id"], "command_ref": name,
      "tool_name": "web-cli", "manifest_digest": digest(manifest), "roots": {**source_roots, "web-cli-home": {"path": str(home), "identity": root_identity(home)}, **({"web-clone": {"path": str(destination), "identity": root_identity(destination)}} if destination else {})},
      "check": check, "denied_paths": list(map(str, denied)), "grant_generation": lease["grant_generation"], "stdin_enabled": False,
      "expires_at": expires, "web_cli_directory": directory,
      "web_cli_checks": native, "service_files": [file_snapshot(str(home / "input.json")), file_snapshot(str(script)), file_snapshot(str(source))], "service_sockets": sockets}
    if destination: value["web_clone_destination"] = str(destination)
    with Tree(host.root) as tree: tree.write_immutable("activity/ordinary-commands/" + key + ".json", json_bytes(value))
    operations.commands.records[key] = value
    return operations.commands.summary(value)
  except Exception:
    if lease is not None: host.store.abort_allocation(lease["lease_id"], host.store.owner)
    remove_directory(host, directory)
    if destination is not None: destination.rmdir()
    raise


def remove_directory(host, directory):
  if not re.fullmatch(r"[0-9a-f]{32}", directory) or not shutil.rmtree.avoids_symlink_attacks: raise Conflict("WEB_CLI_CLEANUP_UNAVAILABLE")
  with Tree(host.root / "activity/web-cli") as tree:
    if tree.fd is not None:
      try: shutil.rmtree(directory, dir_fd=tree.fd)
      except FileNotFoundError: pass


def reclaim(operations, *, now=None):
  now = now or datetime.now(timezone.utc)
  active = {row["web_cli_directory"] for row in operations.commands.records.values() if "web_cli_directory" in row}
  host = operations.host
  with Tree(host.root / "activity/web-cli") as tree:
    if tree.fd is None: return
    for directory in os.listdir(tree.fd):
      if directory in active or not re.fullmatch(r"[a-f0-9]{32}", directory): continue
      raw = tree.read(directory + "/owner.json", max_bytes=4096)
      if raw is None: continue
      try:
        value = json.loads(raw[0])
        if (set(value) != {"schema_version", "kind", "instance_id", "directory", "expires_at", "lease_id"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "web-cli-input"
            or value["instance_id"] != host.store.owner["instance_id"] or value["directory"] != directory): continue
        if datetime.fromisoformat(value["expires_at"]) > now: continue
        lease_id = value["lease_id"]
        if lease_id is not None:
          if not isinstance(lease_id, str) or not re.fullmatch(r"[a-f0-9]{32}", lease_id): raise ValueError()
          try:
            if protected(host.store.read(lease_id)): continue
          except Conflict: continue
      except (ValueError, TypeError): raise Conflict("WEB_CLI_CACHE_INVALID") from None
      remove_directory(host, directory)


def authorize(operations, principal, args):
  closed(args, ("operation_id",))
  if principal.role != "manager": raise Conflict("WEB_CLI_CONTEXT")
  value = operations.commands.records.get(args["operation_id"])
  if value is None or "web_cli_directory" not in value: raise Conflict("WEB_CLI_UNKNOWN")
  lease = operations.host.store.read(value["lease_id"])
  revoked = (lease["grant_generation"] != value["grant_generation"] or digest(operations.host.manifest()) != value["manifest_digest"]
    or datetime.now(timezone.utc) >= datetime.fromisoformat(value["expires_at"]))
  valid = (not revoked and lease["state"] == "running" and lease["grant_generation"] == value["grant_generation"]
    and operations.host.store.processes.observe(lease["process_identity"]) == "alive"
    and datetime.now(timezone.utc) < datetime.fromisoformat(value["expires_at"])
    and digest(operations.host.manifest()) == value["manifest_digest"])
  return {"valid": valid, "revoked": revoked}
