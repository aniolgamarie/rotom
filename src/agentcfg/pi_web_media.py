"""固定本地媒体命令只读已授权副本；复用普通命令监督，不开放 shell。"""
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

from .activity import digest
from .paths import configured_path, relative_path
from .pi_checks import compile_check
from .pi_guarded_files import root_identity
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree
from .deployment import json_bytes


FORMATS = {".mp4": "mov", ".mov": "mov", ".3gp": "mov", ".3gpp": "mov", ".webm": "matroska,webm",
  ".avi": "avi", ".mpeg": "mpeg,mpegvideo", ".mpg": "mpeg,mpegvideo", ".wmv": "asf", ".flv": "flv"}


def prepare_media(operations, principal, args):
  closed(args, ("operation_id", "file_id", "operation"), ("seconds",))
  host = operations.host; manifest = host.manifest(); options = manifest["options"]
  if principal.role != "manager" or "pi-web" not in manifest.get("plugins", []): raise Conflict("WEB_MEDIA_CONTEXT")
  if args["operation"] not in ("frame", "duration"): raise ConfigError("pi-web-media-operation")
  if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200: raise ConfigError("pi-operation-id")
  seconds = args.get("seconds")
  if args["operation"] == "frame":
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
      raise ConfigError("pi-web-media-position")
  elif "seconds" in args: raise ConfigError("pi-web-media-position")
  settings = options.get("web", {}).get("media", {})
  name = settings.get("ffmpeg_tool_ref" if args["operation"] == "frame" else "ffprobe_tool_ref")
  binding = options.get("external_tools", {}).get(name)
  if not binding or binding.get("args", []) or binding.get("interactive", False): raise ConfigError("pi-web-media-tool-binding")
  rules = [row for row in (manifest.get("permission_policy") or {}).get("rules", []) if row["kind"] == "command"
    and row["command_ref"] == "tool:" + name and "bash" in row["tool_ids"] and "execute" in row["operations"]]
  if not any(row["effect"] == "allow" for row in rules) or any(row["effect"] == "deny" for row in rules): raise Conflict("PERMISSION_DENIED")
  key = digest({"owner": host.store.owner, "operation_id": args["operation_id"]})
  request_digest = digest(args)
  if key in operations.commands.records:
    old = operations.commands.records[key]
    if old["request_digest"] != request_digest: raise Conflict("ORDINARY_OPERATION_CONFLICT")
    return operations.commands.summary(old)
  if len(operations.commands.records) >= 128: raise Conflict("ORDINARY_OPERATION_CAPACITY")
  source = operations.web_files.verify(args["file_id"])
  media = source["result"]; format_name = FORMATS.get(Path(media["path"]).suffix.lower())
  if not format_name: raise ConfigError("pi-web-media-format")
  home = Path(media["directory"]); executable = configured_path(binding["executable"])
  common = ["-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", format_name]
  if args["operation"] == "frame":
    argv = ["-nostdin", *common, "-ss", str(seconds), "-i", str(home / "input"), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
  else:
    argv = [*common, "-show_entries", "format=duration", "-of", "csv=p=0", str(home / "input")]
  roots = options.get("paths", {}).get("roots", {})
  reads = [executable]
  for ref in binding.get("read_roots", []):
    if ref not in roots or roots[ref]["purpose"] != "read": raise ConfigError("pi-web-media-read-root")
    dependency = configured_path(roots[ref]["path"]).resolve(strict=True)
    if any(dependency.is_relative_to(configured_path(path)) or configured_path(path).is_relative_to(dependency) for path in host.config.get("protected_roots", [])):
      raise Conflict("WEB_MEDIA_TOOL_SCOPE")
    reads.append(dependency)
  denied = [configured_path(roots[ref]["path"]) for ref in options.get("permissions", {}).get("denied_roots", [])]
  denied.extend(configured_path(path) for path in host.config.get("protected_roots", []) if not home.is_relative_to(configured_path(path)))
  for ref, root in roots.items():
    if root["purpose"] in ("project", "write"): denied.append(configured_path(root["path"]))
  for rule in (manifest.get("permission_policy") or {}).get("rules", []):
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    root = source["source_roots"].get(rule["root_ref"])
    if not root: raise Conflict("WEB_MEDIA_DENIAL_UNBOUND")
    base = configured_path(root["path"])
    denied.append(base if rule["relative_path"] == "." else base / relative_path(rule["relative_path"]))
  if any(path.is_relative_to(blocked) for path in reads for blocked in denied): raise Conflict("WEB_MEDIA_TOOL_SCOPE")
  timeout = min(settings.get("max_seconds", 60), binding.get("timeout_seconds", 60))
  check = compile_check({"executable": str(executable), "args": argv, "project_root": "web-media", "timeout_seconds": timeout, "foreground": True},
    candidate=home, executable=executable, read_roots=reads)
  check["write_roots"] = []; check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
  lease = host.store.allocate(kind="external", execution_id="web-media-" + key, task_id=None, attempt_id=key,
    lock_identity=host.config["lock_identity"], slice_identity=host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]),
    candidate_digest=None, planned_workspaces=[])
  value = {"schema_version": 1, "operation_id": key, "request_digest": request_digest, "lease_id": lease["lease_id"], "command_ref": name,
    "tool_name": "web-media", "manifest_digest": digest(manifest), "roots": {"media": {"path": str(home), "identity": root_identity(home)}},
    "check": check, "denied_paths": [str(path) for path in denied], "grant_generation": lease["grant_generation"], "stdin_enabled": False,
    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=timeout + 300)).isoformat(), "web_file_id": args["file_id"]}
  try:
    operations.web_files.link_command(source, lease["lease_id"])
    with Tree(host.root) as tree: tree.write_immutable("activity/ordinary-commands/" + key + ".json", json_bytes(value))
    operations.commands.records[key] = value
    return operations.commands.summary(value)
  except Exception:
    host.store.abort_allocation(lease["lease_id"], host.store.owner)
    raise
