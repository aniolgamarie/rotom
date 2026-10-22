"""明确本地引用的 Git worktree 创建；仅一次派发，任何不确定结果都保留。"""
from copy import deepcopy
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import re
import subprocess
import uuid

from .errors import TermcfgError
from .herdr import Deadline
from .work_config import literal, resolve_executable
from .work_projects import canonical_boundary, directory, discover, normalize_work, _git_marker
from .work_state import GitState, digest
from agentcfg.storage import identity, Tree


def failure(reason, code=2):
  return TermcfgError(code, reason, "work reconcile")


@dataclass(frozen=True, repr=False)
class GitPlan:
  facts: dict

  @property
  def fingerprint(self):
    return digest(self.facts)

  def as_dict(self):
    return deepcopy(self.facts)


def _environment():
  value = {key: item for key, item in os.environ.items() if not key.startswith("GIT_")}
  value.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
  return value


def _invoke(binary, argv, *, run=None, deadline=None, pass_fds=()):
  try:
    result = (run or subprocess.run)([binary, *argv], env=_environment(), stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=(deadline or Deadline()).remaining(10),
      **({"pass_fds": pass_fds} if pass_fds else {}))
  except subprocess.TimeoutExpired:
    raise failure("work_git_query_timeout", 5) from None
  except OSError:
    raise failure("work_git_unavailable", 5) from None
  if not isinstance(result.stdout, bytes) or len(result.stdout) > 1024 * 1024:
    raise failure("work_git_query_invalid", 5)
  return result


def _git(binary, repo, args, *, run=None, deadline=None, hooks="/dev/null", repo_fd=None):
  directory_arg = "/proc/self/fd/" + str(repo_fd) if repo_fd is not None else str(repo)
  return _invoke(binary, ["-c", "core.hooksPath=" + str(hooks), "-c", "core.fsmonitor=false",
    "-c", "worktree.guessRemote=false", "-c", "submodule.recurse=false", "-C", directory_arg, *args],
    run=run, deadline=deadline, pass_fds=(repo_fd,) if repo_fd is not None else ())


def _text(result, *, allow_missing=False):
  if result.returncode:
    if allow_missing and result.returncode in (1, 128):
      return None
    raise failure("work_git_local_query_failed")
  try:
    return result.stdout.decode("utf-8").rstrip("\n")
  except UnicodeError:
    raise failure("work_git_query_invalid", 5) from None


def _oid(binary, repo, ref, *, run=None, deadline=None):
  value = _text(_git(binary, repo, ["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
    run=run, deadline=deadline), allow_missing=True)
  if value is not None and not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", value):
    raise failure("work_git_query_invalid", 5)
  return value


def _local_base(binary, repo, ref, *, run=None, deadline=None):
  literal(ref)
  if ref == "HEAD" or re.fullmatch(r"[a-fA-F0-9]{7,64}", ref) or ref.startswith(("refs/heads/", "refs/tags/")):
    value = _oid(binary, repo, ref, run=run, deadline=deadline)
  else:
    choices = [item for item in (_oid(binary, repo, prefix + ref, run=run, deadline=deadline)
      for prefix in ("refs/heads/", "refs/tags/")) if item is not None]
    if len(choices) != 1:
      raise failure("work_git_local_ref_missing_or_ambiguous")
    value = choices[0]
  if value is None:
    raise failure("work_git_local_ref_missing_or_ambiguous")
  return value


def _worktrees(binary, repo, *, run=None, deadline=None):
  result = _git(binary, repo, ["worktree", "list", "--porcelain", "-z"], run=run, deadline=deadline)
  if result.returncode:
    raise failure("work_git_worktree_list_unavailable", 5)
  rows, item = [], None
  try:
    for field in result.stdout.decode("utf-8").split("\0"):
      if field.startswith("worktree "):
        if item is not None:
          rows.append(item)
        item = {"path": literal(field[9:]), "branch": None, "commit": None}
      elif field.startswith("branch ") and item is not None:
        item["branch"] = literal(field[7:])
      elif field.startswith("HEAD ") and item is not None:
        item["commit"] = literal(field[5:])
    if item is not None:
      rows.append(item)
    if len(rows) > 4096 or not rows or any(not Path(row["path"]).is_absolute() for row in rows):
      raise ValueError()
    return sorted(rows, key=lambda row: row["path"])
  except (UnicodeError, ValueError):
    raise failure("work_git_query_invalid", 5) from None


def destination_source(settings, path, template):
  sources = normalize_work(settings.structured, local_path=settings.local_path)["sources"]
  eligible = []
  for source in sources:
    root = Path(source["path"])
    if source["mode"] != "git" or not path.is_relative_to(root):
      continue
    parts = path.relative_to(root).parts
    if not 1 <= len(parts) <= source["depth"] or any((source["exclude_hidden"] and part.startswith(".")) or
        any(fnmatch.fnmatchcase(part, pattern) for pattern in source["exclude"]) for part in parts):
      continue
    if any(_git_marker(root.joinpath(*parts[:index])) for index in range(1, len(parts))):
      continue
    eligible.append(source)
  if not eligible:
    raise failure("work_git_destination_source_required")
  depth = max(len(Path(source["path"]).parts) for source in eligible)
  eligible = [source for source in eligible if len(Path(source["path"]).parts) == depth]
  if any(source["template"] != template for source in eligible):
    raise failure("work_git_destination_template_conflict")
  return eligible[0]


def preview(settings, *, repo, path, template, new_branch=None, base=None, existing_branch=None, run=None, deadline=None):
  deadline = deadline or Deadline()
  if bool(new_branch) == bool(existing_branch) or (new_branch and not base) or (existing_branch and base is not None):
    raise failure("work_git_explicit_branch_mode_required")
  if template not in settings.structured["templates"]:
    raise failure("work_unknown_template")
  repo = canonical_boundary(repo, "git")
  matches = [item for item in discover(settings).candidates if item.kind == "project" and item.key == str(repo)
    and item.mode == "git" and item.origin != "builtin"]
  if len(matches) != 1:
    raise failure("work_git_registered_repository_required")
  selected = Path(literal(os.fspath(path))).expanduser()
  if not selected.is_absolute():
    selected = Path.cwd() / selected
  if os.path.lexists(selected):
    raise failure("work_git_destination_exists")
  parent = directory(selected.parent)
  selected = parent / selected.name
  source = destination_source(settings, selected, template)
  binary = resolve_executable("git")
  version = _text(_invoke(binary, ["--version"], run=run, deadline=deadline))
  parsed = re.match(r"git version (\d+)\.(\d+)", version)
  if not parsed or tuple(map(int, parsed.groups())) < (2, 36):
    raise failure("work_git_fsmonitor_boolean_unsupported", 5)
  branch = literal(new_branch or existing_branch)
  if branch.startswith("-") or "@{" in branch or branch == "HEAD" or _git(binary, repo,
      ["check-ref-format", "--branch", branch], run=run, deadline=deadline).returncode:
    raise failure("work_git_invalid_branch")
  current = _oid(binary, repo, "refs/heads/" + branch, run=run, deadline=deadline)
  if new_branch and current is not None:
    raise failure("work_git_new_branch_exists")
  if existing_branch and current is None:
    raise failure("work_git_existing_branch_missing")
  commit = _local_base(binary, repo, base, run=run, deadline=deadline) if new_branch else current
  worktrees = _worktrees(binary, repo, run=run, deadline=deadline)
  if any(item["branch"] == "refs/heads/" + branch for item in worktrees):
    raise failure("work_git_branch_occupied")
  filters = _git(binary, repo, ["config", "--null", "--get-regexp", r"^filter\..*\.(clean|smudge|process)$"], run=run, deadline=deadline)
  if filters.returncode not in (0, 1):
    raise failure("work_git_filter_check_failed", 5)
  if filters.returncode == 0 and filters.stdout:
    raise failure("work_git_executable_checkout_filter_unsupported", 5)
  common = Path(_text(_git(binary, repo, ["rev-parse", "--git-common-dir"], run=run, deadline=deadline)))
  common = (common if common.is_absolute() else repo / common).resolve(strict=True)
  git_dir = Path(_text(_git(binary, repo, ["rev-parse", "--absolute-git-dir"], run=run, deadline=deadline))).resolve(strict=True)
  def stamp(path):
    try:
      return list(identity(path.stat()))
    except FileNotFoundError:
      return None
  facts = {"repo": str(repo), "path": str(selected), "template": template, "branch": branch,
    "branch_mode": "new" if new_branch else "existing", "base": base, "commit": commit,
    "common": str(common), "git_dir": str(git_dir), "git_binary": binary, "git_version": version,
    "repo_identity": list((repo.stat().st_dev, repo.stat().st_ino)),
    "common_identity": list((common.stat().st_dev, common.stat().st_ino)),
    "git_dir_identity": list((git_dir.stat().st_dev, git_dir.stat().st_ino)),
    "parent_identity": list((parent.stat().st_dev, parent.stat().st_ino)), "binary_identity": stamp(Path(binary)),
    "config_files": {str(item): stamp(item) for item in (common / "config", git_dir / "config.worktree")},
    "selection_digest": settings.selection_digest, "source": source, "worktrees": worktrees}
  return GitPlan(facts)


def _reviewed_paths_match(facts):
  try:
    for name in ("repo", "common", "git_dir"):
      value = Path(facts[name]).stat()
      if list((value.st_dev, value.st_ino)) != facts[name + "_identity"]:
        return False
    parent = Path(facts["path"]).parent.stat()
    if list((parent.st_dev, parent.st_ino)) != facts["parent_identity"]:
      return False
    for name, expected in facts["config_files"].items():
      try:
        actual = list(identity(Path(name).stat()))
      except FileNotFoundError:
        actual = None
      if actual != expected:
        return False
    return True
  except OSError:
    return False


def _observation(facts, *, run=None, deadline=None):
  try:
    binary = resolve_executable("git")
    if (binary != facts["git_binary"] or list(identity(Path(binary).stat())) != facts["binary_identity"]
        or not _reviewed_paths_match(facts)):
      return None
    # --quiet 明确区分引用缺失(1)与查询失败；不能将任意 128 当作不存在。
    ref = "refs/heads/" + facts["branch"]
    presence = _git(binary, facts["repo"], ["show-ref", "--verify", "--quiet", ref], run=run, deadline=deadline)
    if presence.returncode not in (0, 1):
      return None
    branch = _oid(binary, facts["repo"], ref, run=run, deadline=deadline) if presence.returncode == 0 else None
    if presence.returncode == 0 and branch is None:
      return None
    rows = _worktrees(facts["git_binary"], facts["repo"], run=run, deadline=deadline)
    if not _reviewed_paths_match(facts):
      return None
    try:
      os.lstat(facts["path"])
      path_exists = True
    except FileNotFoundError:
      path_exists = False
    return {"path_exists": path_exists, "branch_oid": branch,
      "registered": any(item["path"] == facts["path"] and item["branch"] == "refs/heads/" + facts["branch"]
        and item["commit"] == facts["commit"] for item in rows)}
  except (TermcfgError, OSError):
    return None


def _outcome(facts, observation, command_returncode=None, *, previous=None):
  """只解释可验证效果；已结束的非零结果才允许无效果失败。"""
  if any(item is not None and (item["registered"] or item["branch_oid"] == facts["commit"])
      for item in (previous, observation)):
    return "partial"
  if (command_returncode is not None and command_returncode != 0 and observation is not None
      and not observation["path_exists"] and observation["branch_oid"] is None and not observation["registered"]
      and (previous is None or (not previous["path_exists"] and previous["branch_oid"] is None and not previous["registered"]))):
    return "failed"
  return "unknown"


def create(settings, plan, *, deadline=None, run=None):
  """调用者持 per-UID 操作锁；复核通过后一次 Git add，绝不补发或删除。"""
  deadline = deadline or Deadline()
  facts = deepcopy(plan.facts)
  if facts["branch_mode"] == "existing":
    raise failure("work_git_existing_branch_atomic_guard_unavailable", 5)
  if not hasattr(os, "O_PATH") or not Path("/proc/self/fd").is_dir():
    raise failure("work_git_directory_pinning_unavailable", 5)
  from .work_config import read_settings
  try:
    settings = read_settings(local=settings.local_path, repo_root=settings.repo_root)
  except TermcfgError as error:
    if error.code == 2:
      raise failure("work_git_reviewed_configuration_changed", 4) from None
    raise
  with GitState(create=True) as state:
    if any(row["phase"] != "completed" and (row["facts"]["common"] == facts["common"] or
        row["facts"]["path"] == facts["path"]) for row in state.records()):
      raise failure("work_git_recovery_required", 4)
    try:
      fresh = preview(settings, repo=facts["repo"], path=facts["path"], template=facts["template"],
        new_branch=facts["branch"] if facts["branch_mode"] == "new" else None, base=facts["base"],
        existing_branch=facts["branch"] if facts["branch_mode"] == "existing" else None, run=run, deadline=deadline)
    except TermcfgError as error:
      if error.code == 2:
        raise failure("work_git_preview_changed", 4) from None
      raise
    if fresh.fingerprint != plan.fingerprint:
      raise failure("work_git_preview_changed", 4)
    op = uuid.uuid4().hex
    state.publish(op, facts)
    with Tree(state.root / "hooks" / op, create=True) as hooks:
      if os.listdir(hooks.fd):
        raise failure("work_git_hooks_directory_not_empty", 4)
      state.update(op, "dispatched")
      args = ["worktree", "add", "--no-guess-remote"]
      if facts["branch_mode"] == "new":
        args.extend(("-b", facts["branch"]))
      args.extend(("--", facts["path"], facts["commit"] if facts["branch_mode"] == "new" else facts["branch"]))
      repo_fd = None
      try:
        repo_fd = os.open(facts["repo"], os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        pinned = os.fstat(repo_fd)
        if [pinned.st_dev, pinned.st_ino] != facts["repo_identity"] or not _reviewed_paths_match(facts) or os.path.lexists(facts["path"]):
          raise failure("work_git_dispatch_identity_changed", 4)
        result = _git(facts["git_binary"], facts["repo"], args, run=run, deadline=deadline,
          hooks=hooks.root, repo_fd=repo_fd)
      except (TermcfgError, OSError):
        observed = _observation(facts, run=run, deadline=deadline)
        state.update(op, "unknown", observed)
        outcome = _outcome(facts, observed)
        raise failure("work_git_result_" + outcome + "_checkout_retained", 4) from None
      finally:
        if repo_fd is not None:
          os.close(repo_fd)
      observed = _observation(facts, run=run, deadline=deadline)
      if result.returncode or observed is None or not observed["registered"] or observed["branch_oid"] != facts["commit"] or not observed["path_exists"]:
        state.update(op, "unknown", observed, command_returncode=result.returncode)
        outcome = _outcome(facts, observed, result.returncode)
        raise failure("work_git_result_" + outcome + "_checkout_retained", 4)
      state.update(op, "completed", observed, command_returncode=result.returncode)
      return {"op": op, "outcome": "completed", "path": facts["path"], "branch": facts["branch"]}


def report(settings, *, run=None):
  with GitState() as state:
    rows = []
    for item in state.records():
      observed = _observation(item["facts"], run=run)
      # completed 是持久历史结果；当前观察独立呈现，不改写 receipt。
      outcome = ("completed" if item["phase"] == "completed" else _outcome(item["facts"], observed,
        item["command_returncode"], previous=item["observation"]))
      rows.append({"op": item["op"], "phase": item["phase"], "outcome": outcome,
        "command_returncode": item["command_returncode"], "path": item["facts"]["path"],
        "repo": item["facts"]["repo"], "observation": observed})
    return {"git_operations": rows}
