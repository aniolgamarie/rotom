"""GitHub clone 的固定参数和显式产物目录，写入复用普通文件授权与工作区租约。"""
from pathlib import Path
import os
import re
import uuid

from .paths import configured_path
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree
from .pi_guarded_files import GuardedFiles


def clone_arguments(payload, destination):
  closed(payload, ("owner", "repo"), ("ref",))
  if (not isinstance(payload["owner"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", payload["owner"])
      or not isinstance(payload["repo"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", payload["repo"])
      or payload["repo"] in (".", "..")): raise ConfigError("pi-web-github-repository")
  ref = payload.get("ref")
  if ref is not None and (not isinstance(ref, str) or not 1 <= len(ref) <= 1024 or ref.startswith(("-", ".", "/")) or ref.endswith((".", "/", ".lock"))
      or any(ord(char) <= 32 or ord(char) == 127 or char in "~^:?*[\\" for char in ref) or any(part in ref for part in ("..", "//", "@{"))):
    raise ConfigError("pi-web-github-ref")
  return ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "credential.helper=",
    "-c", "core.hooksPath=/dev/null", "-c", "init.templateDir=", "-c", "http.followRedirects=false",
    "clone", "--depth", "1", "--single-branch", "--no-recurse-submodules", "--no-local",
    *(["--branch=" + ref] if ref is not None else []), "--", "https://github.com/" + payload["owner"] + "/" + payload["repo"] + ".git", str(destination)]


def prepare_destination(operations, principal, args):
  manifest = operations.host.manifest(); options = manifest["options"]
  settings = options.get("web", {}).get("github_clone", {})
  root = options.get("paths", {}).get("roots", {}).get(settings.get("root_ref"))
  if not root or root["purpose"] != "write": raise ConfigError("pi-web-github-output-root")
  parent = configured_path(root["path"])
  destination = parent / ("clone-" + uuid.uuid4().hex)
  clone_arguments(args["input"], destination)
  base = operations.prepare(principal, {"operation_id": args["operation_id"], "role_id": "main", "cwd": args["cwd"],
    "tool_name": "write", "input": {"path": str(destination), "content": ""}})
  try:
    value = operations.record(base["operation_id"])
    operations.policy(value, reserved=True).authorize("write", "create", str(destination))
    with Tree(parent, private=False) as tree:
      os.mkdir(destination.name, mode=0o700, dir_fd=tree.fd)
    return destination, operations.host.store.read(base["lease_id"]), value["grant"]["root_bindings"]
  except Exception:
    operations.host.store.abort_allocation(base["lease_id"], operations.host.store.owner)
    raise
  finally:
    operations.inputs.pop(base["operation_id"], None)


def content(operations, principal, args):
  closed(args, ("cwd", "directory", "type", "path"))
  manifest = operations.host.manifest()
  if principal.role != "manager" or manifest.get("bootstrap") or "pi-web" not in manifest.get("plugins", []): raise Conflict("WEB_CLI_CONTEXT")
  options = manifest["options"]; binding = options.get("web", {}).get("github_clone", {})
  root = options.get("paths", {}).get("roots", {}).get(binding.get("root_ref"))
  directory = configured_path(args["directory"])
  if (not root or directory.parent != configured_path(root["path"]) or not re.fullmatch(r"clone-[0-9a-f]{32}", directory.name)
      or args["type"] not in ("root", "tree", "blob") or not isinstance(args["path"], str)
      or Path(args["path"]).is_absolute() or any(part in ("..", ".git") for part in Path(args["path"]).parts)):
    raise ConfigError("pi-web-github-content-path")
  path = directory / args["path"]
  ticket = operations.prepare(principal, {"operation_id": uuid.uuid4().hex, "role_id": "main", "cwd": args["cwd"],
    "tool_name": "read" if args["type"] == "blob" else "ls", "input": {"path": str(path)}})
  try:
    record = operations.record(ticket["operation_id"])
    files = GuardedFiles(operations.policy(record), mutation=None)
    lines = ["Repository cloned to: " + str(directory), ""]
    if args["type"] == "blob":
      try:
        body = files.read("read", str(path))
        text = body.decode("utf-8")
        if "\0" in text: raise UnicodeError()
        lines += ["## " + args["path"], text[:100000]]
        if len(text) > 100000: lines.append("[File truncated at 100K characters]")
      except UnicodeError:
        lines += ["## " + args["path"], "Binary file; use the configured file tools to inspect."]
    else:
      entries = []
      def walk(current, prefix, recursive):
        for row in files.list("ls", str(current)):
          if len(entries) >= 200: return
          label = prefix + row["name"]
          entries.append(label + ("/" if row["kind"] == "directory" else ""))
          if recursive and row["kind"] == "directory" and row["name"] not in {"node_modules", "vendor", "dist", "build", ".venv", "target", "__pycache__"}:
            walk(current / row["name"], label + "/", True)
      walk(path, "", args["type"] == "root")
      lines += ["## " + ("Structure" if args["type"] == "root" else args["path"] or "/"), "\n".join(entries)]
      if len(entries) >= 200: lines.append("[Structure truncated at 200 entries]")
      if args["type"] == "root":
        for name in ("README.md", "readme.md", "README", "README.txt", "README.rst"):
          try: text = files.read("read", str(directory / name)).decode("utf-8")
          except (FileNotFoundError, UnicodeError): continue
          except Conflict as error:
            if str(error) == "PERMISSION_DENIED": continue
            raise
          lines += ["", "## " + name, text[:8192] + ("\n[README truncated at 8K characters]" if len(text) > 8192 else "")]
          break
    return {"content": "\n".join([*lines, "", "Use the configured read and command tools at the path above to explore further."])}
  finally: operations.inputs.pop(ticket["operation_id"], None)
