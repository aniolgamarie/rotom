"""Slopchop 的 Git 查询白名单；可执行程序、元数据和工作区均由配置绑定。"""
from pathlib import Path
import re
import hashlib

from .paths import configured_path, relative_path
from .pi_git_status import validate_binding
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


PREFIX = ["--no-pager", "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
  "-c", "core.hooksPath=/dev/null", "-c", "core.untrackedCache=false"]


def revision(value):
  if not isinstance(value, str) or len(value) > 256 or not re.fullmatch(r"\w[\w./-]*(?:[~^][0-9]*)?", value):
    raise ConfigError("pi-git-review-revision")
  return value


def query(argv):
  if not isinstance(argv, list) or not argv or len(argv) > 16 or any(not isinstance(value, str) or "\0" in value or len(value) > 4096 for value in argv):
    raise ConfigError("pi-git-review-query")
  command, args = argv[0], argv[1:]
  valid = False
  if command == "rev-parse":
    valid = args == ["--show-toplevel"] or len(args) == 3 and args[:2] == ["--verify", "--quiet"] and bool(revision(args[2]))
  elif command == "symbolic-ref":
    valid = args == ["--quiet", "--short", "refs/remotes/origin/HEAD"]
  elif command == "ls-files":
    valid = args in (["--others", "--exclude-standard"], ["--cached"], ["--deleted"])
  elif command == "merge-base":
    valid = len(args) == 2 and all(revision(value) for value in args)
  elif command == "show" and len(args) == 1:
    ref, separator, path = args[0].partition(":")
    if separator and revision(ref):
      relative_path(path)
      if ".git" in Path(path).parts: raise ConfigError("pi-git-review-query")
      valid = True
  elif command in ("diff", "diff-tree"):
    start = ["--find-renames", "-M"] if command == "diff" else ["--root", "--find-renames", "-M"]
    if args[:len(start)] == start:
      rest = args[len(start):]
      if rest[:1] in (["--name-status"], ["--numstat"]): rest = rest[1:]
      elif rest[:2] == ["--raw", "-z"]: rest = rest[2:]
      else: raise ConfigError("pi-git-review-query")
      if command == "diff":
        valid = 2 <= len(rest) <= 3 and rest[-1] == "--" and all(revision(value) for value in rest[:-1])
      else:
        valid = rest == ["--no-commit-id", "-r", "HEAD"]
  if not valid: raise ConfigError("pi-git-review-query")
  flags = ["--no-ext-diff", "--no-textconv"] if command in ("diff", "diff-tree", "show") else []
  if command == "ls-files" or command in ("diff", "diff-tree") and "-z" not in args:
    flags.append("-z")
  return [*PREFIX, command, *flags, *args]


def prepare_review(commands, principal, args):
  closed(args, ("operation_id", "cwd", "argv"))
  manifest = commands.host.manifest()
  if principal.role != "manager" or "pi-slopchop" not in manifest.get("plugins", []):
    raise Conflict("GIT_REVIEW_CONTEXT_UNAVAILABLE")
  argv = query(args["argv"])
  options = manifest["options"]
  if not options.get("slopchop", {}).get("git_tool_ref"):
    raise ConfigError("pi-git-review-binding-required")
  name, binding, declaration = validate_binding(options, name=options.get("slopchop", {}).get("git_tool_ref"))
  project = configured_path(declaration["path"]).resolve(strict=True)
  cwd = configured_path(args["cwd"]).resolve(strict=True)
  parent_workspace = commands.host.store.workspaces.identify(project)
  if not cwd.is_relative_to(project):
    raise Conflict("GIT_REVIEW_PROJECT_UNBOUND")
  def metadata_roots(identity):
    roots = [Path(identity["git_dir_path"])]
    with Tree(roots[0], private=False) as tree:
      common = tree.read("commondir")
    if common: roots.append((roots[0] / common[0].decode().strip()).resolve(strict=True))
    return roots
  parents = metadata_roots(parent_workspace)
  markers = []
  try:
    workspace = commands.host.store.workspaces.identify(cwd)
    metadata = metadata_roots(workspace)
  except Conflict:
    # Git 子模块的 gitdir 通常没有 linked-worktree backlink；只读审查仍可在父授权内进行。
    nested = cwd
    while nested != project and not (nested / ".git").exists() and not (nested / ".git").is_symlink(): nested = nested.parent
    if nested == project: raise
    with Tree(nested, private=False) as tree:
      raw = tree.read(".git", max_bytes=4096)
    text = raw[0].decode().rstrip("\n") if raw else ""
    if not text.startswith("gitdir: ") or "\n" in text: raise Conflict("GIT_REVIEW_METADATA_UNBOUND")
    directory = (nested / text[8:]).resolve(strict=True)
    if not any(directory.is_relative_to(root / "modules") for root in parents):
      raise Conflict("GIT_REVIEW_METADATA_UNBOUND")
    with Tree(directory, private=False) as tree:
      if not tree.read("HEAD"): raise Conflict("GIT_REVIEW_METADATA_UNBOUND")
    metadata, workspace = [directory], parent_workspace
    markers = [{"root": str(nested), "sha256": hashlib.sha256(raw[0]).hexdigest()}]
  if not Path(workspace["worktree_path"]).is_relative_to(project): raise Conflict("GIT_REVIEW_PROJECT_UNBOUND")
  if any(not any(path.is_relative_to(root) for root in [project, *parents]) for path in metadata):
    raise Conflict("GIT_REVIEW_METADATA_UNBOUND")
  # 嵌套仓库同时预留父业务树和自己的工作区，避免与任意一侧的 writer 交叉。
  workspaces = [parent_workspace]
  if workspace["workspace_key"] != parent_workspace["workspace_key"]: workspaces.append(workspace)
  return commands.prepare(principal, {"operation_id": args["operation_id"], "cwd": str(cwd), "role_id": "main", "tool_name": "bash",
    "input": {"command": "agentcfg:" + name}}, inspection={"metadata": metadata, "workspace": workspace, "workspaces": workspaces,
      "markers": markers, "argv": argv})
