"""目录选择计划使用固定 Git/rg 参数和只读沙箱；不在监督器进程中执行工具。"""
from pathlib import Path
import stat

from .activity import digest
from .paths import configured_path
from .pi_checks import compile_check
from .pi_git_review import PREFIX
from .pi_git_status import validate_binding
from .pi_readseek_selection import decode_git_paths, git_queries
from .schema import ConfigError
from .storage import Conflict, Tree


def selection_jobs(controller, pending):
  host = controller.host; options = host.manifest()["options"]
  settings = options.get("readseek", {}); project = Path(pending["project"])
  search = Path(pending["cwd"]) if pending["params"].get("workspace", False) else Path(pending["path"])
  permission = host.manifest()["permission_policy"]
  declarations = options.get("paths", {}).get("roots", {})
  denied = [configured_path(row).resolve(strict=True) for row in host.config.get("protected_roots", [])]
  denied += [configured_path(declarations[name]["path"]).resolve(strict=True) for name in options.get("permissions", {}).get("denied_roots", [])]
  for rule in permission["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    root = project if rule["root_ref"] == "project" else configured_path(declarations[rule["root_ref"]]["path"]).resolve(strict=True)
    denied.append(root / rule["relative_path"])
  if any(search.is_relative_to(path) for path in denied): raise Conflict("PERMISSION_DENIED")
  is_grep = pending["tool"] == "readSeek_grep"
  marker = project / ".git"
  if not is_grep and not marker.exists() and not marker.is_symlink():
    # 普通目录才使用上游 fallback；损坏仓库或缺失绑定不能退化成无 Git 语义。
    return []
  name = settings.get("rg_tool_ref" if is_grep else "git_tool_ref")
  if not name: raise ConfigError("readseek-selection-tool-required")
  name, binding, declaration = validate_binding(options, name=name)
  if configured_path(declaration["path"]).resolve(strict=True) != project: raise Conflict("READSEEK_SELECTION_PROJECT")
  rules = [row for row in permission["rules"] if row["kind"] == "command" and row["command_ref"] == "tool:" + name
    and "bash" in row["tool_ids"] and "execute" in row["operations"]]
  if not any(row["effect"] == "allow" for row in rules) or any(row["effect"] == "deny" for row in rules): raise Conflict("PERMISSION_DENIED")
  metadata = []
  if marker.exists() or marker.is_symlink():
    workspace = host.store.workspaces.identify(project)
    if Path(workspace["worktree_path"]) != project: raise Conflict("READSEEK_SELECTION_PROJECT")
    metadata.append(Path(workspace["git_dir_path"]))
    with Tree(metadata[0], private=False) as tree: common = tree.read("commondir")
    if common: metadata.append((metadata[0] / common[0].decode().strip()).resolve(strict=True))
  if any(root.is_relative_to(path) or path.is_relative_to(root) for root in metadata for path in denied):
    raise Conflict("READSEEK_SELECTION_METADATA_DENIED")
  executable = configured_path(binding["executable"])
  if executable.is_relative_to(project) or any(executable.is_relative_to(path) for path in denied): raise Conflict("READSEEK_SELECTION_EXECUTABLE")
  if is_grep:
    # rg --files --hidden 会列出.git元数据；worker绝不能接收Git元数据作为输入，源头排除。
    argv = ["--files", "--hidden", "--null", "--glob", "!.git", "--glob", "!**/.git/**", "--glob", "!.readseek"]
    if "glob" in pending["params"]: argv += ["--glob", pending["params"]["glob"]]
    queries = {"rg": [*argv, "--", str(search)]}
  else: queries = {name: [*PREFIX, *argv] for name, argv in git_queries(search, pending["params"]).items()}
  jobs = []
  for category, argv in queries.items():
    check = compile_check({"executable": str(executable), "args": argv, "project_root": binding["project_root"],
      "timeout_seconds": min(binding["timeout_seconds"], pending["ticket"]["timeout_seconds"]), "foreground": True},
      candidate=search if search.is_dir() else search.parent, executable=executable,
      read_roots=[executable, project, *metadata])
    check["write_roots"] = []
    check["git_status"] = True  # 禁止系统/全局 Git 配置、lazy fetch 与交互认证。
    check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
    jobs.append({"category": category, "check": check, "denied_paths": sorted({str(path) for path in denied}), "search_root": str(search)})
  return jobs


def selected_paths(home, jobs, project):
  """只读取受监督 driver 的固定输出文件；不接受 RPC 传入任意文件列表。"""
  categories = {}
  with Tree(Path(home)) as tree:
    for index, job in enumerate(jobs):
      raw = tree.read("selection-" + str(index) + ".stdout", max_bytes=8 * 1024 * 1024)
      if raw is None: raise Conflict("READSEEK_SELECTION_MISSING")
      search = Path(job["search_root"])
      if job["category"] == "rg":
        # rg --files 对绝对查询路径返回绝对文件名；先限制在查询范围再交给统一路径校验。
        if raw[0] and not raw[0].endswith(b"\0"): raise Conflict("READSEEK_SELECTION_INVALID")
        try: names = raw[0][:-1].decode().split("\0") if raw[0] else []
        except UnicodeError: raise Conflict("READSEEK_SELECTION_INVALID") from None
        base = search if search.is_dir() else search.parent
        if any(not Path(name).is_absolute() or not Path(name).is_relative_to(base) for name in names): raise Conflict("READSEEK_SELECTION_INVALID")
        names = decode_git_paths(b"".join(str(Path(name).relative_to(project)).encode() + b"\0" for name in names))
      else:
        names = [str(search.relative_to(project) / path) for path in decode_git_paths(raw[0])]
      # Git 的 gitlink/已删除 index 项不属于当前普通文件，与上游行为一致；链接不跟随。
      files = []
      for name in names:
        try: info = (Path(project) / name).lstat()
        except FileNotFoundError: continue
        if stat.S_ISREG(info.st_mode): files.append(name)
        elif stat.S_ISLNK(info.st_mode): raise Conflict("READSEEK_SELECTION_SYMLINK")
      categories[job["category"]] = sorted(set(files))
  return categories
