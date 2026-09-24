"""只读取明确声明的规则根；不扫描真实 HOME，不跟随目录或文件链接。"""
import os
from pathlib import Path
import stat

from .deployment import json_bytes
from .paths import configured_path
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


def validate_rules(options):
  selected = options.get("rules", {}).get("root_refs")
  roots = options.get("paths", {}).get("roots", {})
  if options.get("rules", {}).get("enabled") is False and selected == []: return []
  if not selected or set(selected) - roots.keys(): raise ConfigError("pi-rules-roots-required")
  return selected


def read_rules(host, principal, args):
  closed(args, ())
  manifest = host.manifest()
  if principal.role != "manager" or "pi-rules" not in manifest.get("plugins", []): raise Conflict("RULES_CONTEXT_UNAVAILABLE")
  options = manifest["options"]; settings = options["rules"]
  selected = validate_rules(options)
  if settings.get("enabled", True) is False: return {"rules": []}
  declarations = options["paths"]["roots"]
  denied = [configured_path(declarations[name]["path"]).resolve(strict=True) for name in options.get("permissions", {}).get("denied_roots", [])]
  denied += [Path(path) for path in host.config.get("protected_roots", [])]
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] == "file" and rule["effect"] == "deny":
      if rule["root_ref"] not in declarations: raise Conflict("RULES_DENIAL_ROOT_UNBOUND")
      root = configured_path(declarations[rule["root_ref"]]["path"])
      denied.append(root if rule["relative_path"] == "." else root / rule["relative_path"])
  results = []; size = 0
  for name in selected:
    root = configured_path(declarations[name]["path"])
    if any(root.is_relative_to(path) or path.is_relative_to(root) for path in denied): raise Conflict("RULES_SCOPE_DENIED")
    with Tree(root, private=False) as tree:
      if tree.fd is None: raise Conflict("RULES_ROOT_MISSING")
      stack = [""]; visited = 0
      while stack:
        prefix = stack.pop(); visited += 1
        if visited > 1024: raise Conflict("RULES_LIMIT")
        with tree.parent(prefix + ".agentcfg-probe") as (fd, _):
          for child in sorted(os.listdir(fd)):
            relative = prefix + child
            info = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode): raise Conflict("RULES_LINK_REJECTED")
            if stat.S_ISDIR(info.st_mode):
              if child not in (".git", ".ssh", ".pi", ".codex"): stack.append(relative + "/")
            elif stat.S_ISREG(info.st_mode) and child.endswith(".md"):
              raw = tree.read(relative, max_bytes=65536)
              if raw is None: raise Conflict("RULES_CHANGED")
              try: text = raw[0].decode("utf-8")
              except UnicodeError: raise ConfigError("pi-rules-encoding") from None
              size += len(raw[0]); results.append({"id": name + "/" + relative, "body": text})
              if size > 512 * 1024 or len(results) > 256: raise Conflict("RULES_LIMIT")
  result = {"rules": results}
  if len(json_bytes(result)) > 768 * 1024: raise Conflict("RULES_LIMIT")
  return result
