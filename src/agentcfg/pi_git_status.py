"""只读 Git 状态检查：显式命令授权、元数据范围和共享执行队列。"""

from pathlib import Path

from .paths import configured_path
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


STATUS_ARGS = ["--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
  "-c", "core.hooksPath=/dev/null", "-c", "core.untrackedCache=false", "-c", "status.relativePaths=false",
  "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"]


def validate_binding(options, *, name=None):
  name = name or options.get("dirty_repo_guard", {}).get("tool_ref")
  binding = options.get("external_tools", {}).get(name)
  if not binding or not {"project_root", "read_roots", "write_roots", "timeout_seconds"} <= binding.keys():
    raise ConfigError("pi-git-status-binding-required")
  project = binding["project_root"]
  root = options.get("paths", {}).get("roots", {}).get(project)
  if (not root or root["purpose"] != "project" or binding.get("args", []) != [] or binding.get("interactive", False)
      or binding["read_roots"] != [project] or binding["write_roots"] != []):
    raise ConfigError("pi-git-status-readonly-binding")
  return name, binding, root


def prepare_status(commands, principal, args):
  closed(args, ("operation_id", "cwd"))
  manifest = commands.host.manifest()
  if principal.role != "manager" or "dirty-repo-guard" not in manifest.get("resource_ids", {}).get("extensions", {}):
    raise Conflict("GIT_STATUS_CONTEXT_UNAVAILABLE")
  name, binding, declaration = validate_binding(manifest["options"])
  project = configured_path(declaration["path"]).resolve(strict=True)
  cwd = configured_path(args["cwd"]).resolve(strict=True)
  if not cwd.is_dir() or not cwd.is_relative_to(project):
    raise Conflict("GIT_STATUS_PROJECT_REQUIRED")
  # 只有确实不存在 Git 标记才返回非仓库；损坏标记、权限不足均失败。
  current = cwd
  while True:
    try:
      (current / ".git").lstat()
      break
    except FileNotFoundError:
      if current == current.parent:
        return {"status": "not-repository"}
      current = current.parent
  if current != project:
    raise Conflict("GIT_STATUS_PROJECT_REQUIRED")
  workspace = commands.host.store.workspaces.identify(cwd)
  if Path(workspace["worktree_path"]) != project:
    raise Conflict("GIT_STATUS_PROJECT_REQUIRED")
  metadata = [Path(workspace["git_dir_path"])]
  with Tree(metadata[0], private=False) as tree:
    common = tree.read("commondir")
  if common:
    metadata.append((metadata[0] / common[0].decode().strip()).resolve(strict=True))
  inspection = {"metadata": metadata, "workspace": workspace, "argv": STATUS_ARGS}
  # 复用固定命令准入；专用 RPC 无法传入任意 argv 或解除其他命令的 .git 隔离。
  return commands.prepare(principal, {**args, "cwd": str(project), "role_id": "main", "tool_name": "bash",
    "input": {"command": "agentcfg:" + name}}, inspection=inspection)
