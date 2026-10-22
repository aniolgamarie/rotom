"""可选 fzf 前端；不解释显示文本，不注入预览命令或继承用户绑定。"""
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from .errors import TermcfgError
from .work_config import resolve_executable


FLAGS = ("--read0", "--print0", "--no-multi", "--delimiter", "--with-nth", "--prompt",
  "--height", "--layout", "--border")


def display(value):
  return "".join(char if ord(char) >= 32 and not 127 <= ord(char) <= 159 else
    "\\u" + format(ord(char), "04x") for char in str(value))


def select(rows, *, prompt="Choose > ", run=None):
  rows = list(rows)
  if len(rows) > 20000 or len({key for key, _ in rows}) != len(rows) or any(
      not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) for key, _ in rows):
    raise TermcfgError(2, "work_invalid_selector_rows", "work --help")
  binary = resolve_executable("fzf")
  environment = {key: value for key, value in os.environ.items() if not key.startswith("FZF_")}
  invoke = run or subprocess.run
  def call(argv, **kwargs):
    try:
      return invoke([binary, *argv], env=environment, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
      raise TermcfgError(5, "work_selector_unavailable", "work list") from None
  version = call(["--version"], stdin=subprocess.DEVNULL, timeout=5)
  help_text = call(["--help"], stdin=subprocess.DEVNULL, timeout=5)
  if (version.returncode or help_text.returncode or not re.match(rb"\d+\.\d+\.\d+", version.stdout) or
      any(flag.encode() not in help_text.stdout and not
        (flag == "--no-multi" and b"--multi" in help_text.stdout) for flag in FLAGS)):
    raise TermcfgError(5, "work_selector_unsupported", "work list")
  mapping = {key: (key + "\t" + display(label)).encode("utf-8") for key, label in rows}
  payload = b"".join(value + b"\0" for value in mapping.values())
  if len(payload) > 4 * 1024 * 1024:
    raise TermcfgError(2, "work_selector_list_limit", "work list")
  result = call(["--read0", "--print0", "--no-multi", "--delimiter=\t", "--with-nth=2..",
    "--prompt=" + prompt, "--height=80%", "--layout=reverse", "--border"], input=payload)
  if result.returncode in (1, 130):
    return None
  if result.returncode != 0 or not result.stdout.endswith(b"\0") or result.stdout.count(b"\0") != 1:
    raise TermcfgError(5, "work_selector_failed", "work list")
  selected = result.stdout[:-1]
  for key, expected in mapping.items():
    if selected == expected:
      return key
  raise TermcfgError(5, "work_selector_unknown_result", "work list")


def _text(prompt, *, optional=False):
  if not sys.stdin.isatty():
    raise TermcfgError(2, "work_interactive_input_required", "work --help")
  try:
    value = input(prompt + " (Esc/Ctrl-D to cancel): ")
  except (EOFError, KeyboardInterrupt):
    return None
  if value == "\x1b" or (not value and not optional):
    return None
  return value


def confirm(label):
  return select([("accept", "Confirm: " + label), ("cancel", "Cancel")], prompt="Review > ") == "accept"


def candidate_label(item):
  return " | ".join(display(value) for value in
    (item.title, item.kind, item.mode or "named", item.key, item.template, item.origin))


def present_discovery(discovery, *, show_candidates=True):
  if show_candidates:
    print("Candidates: " + str(len(discovery.candidates)))
    for item in discovery.candidates:
      print(candidate_label(item))
  for diagnostic in discovery.diagnostics:
    print(" | ".join(display(diagnostic[key]) for key in ("reason", "source", "origin")
      if key in diagnostic), file=sys.stderr)


def present_proposal(proposal):
  print(proposal.fragment, end="" if proposal.fragment.endswith("\n") else "\n")
  present_discovery(proposal.discovery)


def registration(settings, kind):
  from .work_edit import preview
  values = {}
  fields = ("id", "title", "start_path") if kind == "named" else (("id", "path") if kind == "source" else ("path",))
  for field in fields:
    value = _text(field, optional=field == "start_path")
    if value is None:
      return None
    if value:
      values[field] = value
  if kind != "named":
    mode = select([("git", "Git checkout root"), ("directory", "Selected directory boundary")], prompt="Mode > ")
    if mode is None:
      return None
    values["mode"] = mode
  templates = list(settings.structured["templates"])
  choice = select([(str(index), name) for index, name in enumerate(templates)], prompt="Template > ")
  if choice is None:
    return None
  values["template"] = templates[int(choice)]
  proposal = preview(settings, kind + "-add", values)
  present_proposal(proposal)
  if not confirm("Save configuration only"):
    return None
  args = [kind, "add"]
  for key, value in values.items():
    args.extend(("--" + key.replace("_", "-"), value))
  return args


def selector(settings):
  from .work_projects import discover
  while True:
    discovery = discover(settings)
    present_discovery(discovery, show_candidates=False)
    candidates = list(discovery.candidates)
    rows = [(str(index), candidate_label(item))
      for index, item in enumerate(candidates)]
    rows.extend((("source", "+ Import search path"), ("project", "+ Import directory"),
      ("named", "+ Named workspace"), ("worktree", "+ New Git worktree"), ("refresh", "Refresh"),
      ("config", "Edit workspace configuration"), ("status", "Read-only live status / unknown outcomes"),
      ("rename", "Rename named workspace"), ("close", "Review current workspace close scope (guard unavailable)")))
    choice = select(rows, prompt="Project > ")
    if choice is None:
      return None
    if choice == "refresh":
      continue
    if choice in ("source", "project", "named"):
      return registration(settings, choice)
    if choice == "config":
      return ["config", "edit"]
    if choice == "status":
      return ["status"]
    if choice == "close":
      return ["close", "--dry-run"]
    if choice == "rename":
      named = [item for item in candidates if item.kind == "named"]
      selected = select([(str(i), item.title + " | " + item.key) for i, item in enumerate(named)], prompt="Named > ")
      if selected is None:
        return None
      title = _text("New title")
      if title is None or not confirm("Save title, then update verified native presentation"):
        return None
      return ["named", "rename", named[int(selected)].key, "--title", title]
    if choice == "worktree":
      return worktree_form(settings)
    item = candidates[int(choice)]
    return ["named", "enter", item.key] if item.kind == "named" else ["enter", item.key]


def type_action(settings, binding, *, new=False):
  template = settings.structured["templates"].get(binding["template"], {})
  definitions = template.get("tab_types", {})
  order = list(template.get("order", []))
  order.extend(key for key in binding["types"] if key not in order)
  rows, actions = [], {}
  for key in order:
    configured = key in definitions
    definition = definitions.get(key, {})
    label = definition.get("label", key)
    if configured:
      action = str(len(actions))
      actions[action] = (key, None)
      rows.append((action, label + (" | New extra" if new else " | Default: focus or create")))
    if not new:
      for locator, reference in binding["types"].get(key, {}).get("instances", {}).items():
        action = str(len(actions))
        actions[action] = (key, locator)
        rows.append((action, label + (" | " if configured else " | Removed type: focus only | ")
          + reference["kind"] + " | " + reference["tab_id"] + " | verify before focus"))
      if configured and key in binding["types"]:
        action = str(len(actions))
        actions[action] = ("!rebind", key)
        rows.append((action, label + " | Review explicit rebind (requires zero active instances)"))
  selected = select(rows, prompt="Terminal type > ")
  return actions[selected] if selected is not None else None


@dataclass(frozen=True, repr=False)
class ReviewedWorktreeAction:
  settings: object
  plan: object
  enter: bool


def present_worktree_plan(plan):
  from .work_state import digest
  import json
  facts = plan.facts
  review = {key: facts[key] for key in ("repo", "path", "branch_mode", "branch", "base", "commit",
    "template", "repo_identity", "common", "common_identity", "git_dir", "git_dir_identity")}
  # 配置身份使用摘要，不输出内部时间戳或扩展的非审阅字段。
  review["source"] = {key: facts["source"][key] for key in
    ("id", "path", "mode", "template", "depth", "exclude_hidden", "exclude", "follow_symlinks")}
  review["configuration"] = {"selection_digest": facts["selection_digest"],
    "git_config_paths": sorted(facts["config_files"]), "git_config_digest": digest(facts["config_files"])}
  print(json.dumps(review, ensure_ascii=False))
  print("Original dirty files stay in place. No hooks, bootstrap, installs or services. Executable checkout filters are refused.")


def worktree_form(settings):
  from .work_projects import discover, directory
  from .work_edit import preview as config_preview, save
  from .work_config import read_settings
  from .work_git import preview
  from pathlib import Path
  candidates = [item for item in discover(settings).candidates if item.kind == "project" and item.mode == "git" and item.origin != "builtin"]
  selected = select([(str(i), item.title + " | " + item.key) for i, item in enumerate(candidates)], prompt="Registered Git repository > ")
  if selected is None:
    return None
  repo = candidates[int(selected)].key
  mode = select([("new", "New local branch from explicit local base"),
    ("existing", "Existing branch (requires native atomic protection)")], prompt="Branch mode > ")
  if mode is None:
    return None
  branch = _text("Branch name")
  if branch is None:
    return None
  base = _text("Local base (for example HEAD or refs/heads/main)") if mode == "new" else None
  if mode == "new" and base is None:
    return None
  destination = _text("Destination (must not exist; parent must exist)")
  if destination is None:
    return None
  templates = list(settings.structured["templates"])
  choice = select([(str(i), name) for i, name in enumerate(templates)], prompt="Template > ")
  if choice is None:
    return None
  template = templates[int(choice)]
  while True:
    try:
      plan = preview(settings, repo=repo, path=destination, template=template,
        new_branch=branch if mode == "new" else None, base=base, existing_branch=branch if mode == "existing" else None)
      break
    except TermcfgError as error:
      if error.reason != "work_git_destination_source_required":
        raise
      if not confirm("Separately import destination parent as Git search path"):
        return None
      identifier = _text("New source ID (ASCII)")
      if identifier is None:
        return None
      parent = directory(Path(destination).expanduser().absolute().parent)
      proposal = config_preview(settings, "source-add", {"id": identifier, "path": str(parent),
        "mode": "git", "template": template})
      present_proposal(proposal)
      if not confirm("Save parent source only; checkout creation still requires review"):
        return None
      save(proposal)
      settings = read_settings(local=settings.local_path, repo_root=settings.repo_root)
  present_worktree_plan(plan)
  action = select([("create", "Create only"), ("enter", "Create, then enter workspace"), ("cancel", "Cancel")], prompt="Confirm > ")
  return ReviewedWorktreeAction(settings, plan, action == "enter") if action in ("create", "enter") else None
