"""termcfg 独立命令行与简短的可诊断结果。"""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from rotom.context import InputError, invocation_context, require_input
from .catalog import load_catalog
from .config import COMPONENTS, MachineSelection, encode_machine, environment_home, machine_path, read_machine, xdg_path
from .diagnostics import current_progress, emit, reset_progress
from .environment import inspect_environment, status_report
from .errors import TermcfgError
from .guidance import context_for, hint, resolve_hints
from .cli_help import ENTRY_GUIDE
from .cli_parser import Parser, build_parser
from .lease import operation_lease
from .packages import lock_plugin, sync
from .preview import build_preview
from .state import read_journal, require_no_pending_recovery
from .transaction import apply, recover, rollback, rollback_preview


def _write_new_machine(path: Path, payload: bytes, *, before_replace=None) -> None:
  for directory in (path.parent.parent, path.parent):
    if directory.exists() or directory.is_symlink():
      info = directory.lstat()
      if not directory.is_dir() or directory.is_symlink() or info.st_uid != os.getuid() or (info.st_mode & 0o777) != 0o700:
        raise TermcfgError(4, "unsafe_private_directory")
    else:
      directory.mkdir(mode=0o700)
  fd, temporary = tempfile.mkstemp(prefix=".machine-", dir=path.parent)
  try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as stream:
      stream.write(payload)
      stream.flush()
      os.fsync(stream.fileno())
    if before_replace is not None:
      before_replace()
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
      os.fsync(directory_fd)
    finally:
      os.close(directory_fd)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def _interactive_selection(previous: tuple[str, ...] | None, *, context=None) -> tuple[str, ...]:
  if context is not None:
    rows = [(name, name) for name in ("zsh", "tmux", "herdr")]
    rows.append(("none", "保存空组件选择"))
    if previous is not None:
      rows.append(("previous", "保持已经保存的组件选择"))
    selected = context.input_gateway.choose(rows, policy=context.input_policy, label="组件")
    return previous if selected == "previous" else () if selected == "none" else (selected,)
  defaults = previous if previous is not None else tuple(
    name for name in ("zsh", "tmux") if shutil.which(name)
  )
  print("选择组件（逗号分隔；留空保持默认；输入 none 清空）：", file=sys.stderr)
  for name in ("zsh", "tmux", "herdr"):
    required = "就绪" if shutil.which(name) else "缺少本地程序"
    print(f"  {name}: {required}{' [预选]' if name in defaults else ''}", file=sys.stderr)
  print("组件> ", end="", file=sys.stderr, flush=True)
  answer = input().strip()
  if not answer:
    return defaults
  if answer.lower() == "none":
    return ()
  values = tuple(part.strip() for part in answer.split(","))
  if len(set(values)) != len(values) or any(value not in COMPONENTS for value in values):
    raise TermcfgError(2, "invalid_components")
  return values


def _confirm(message: str, *, context=None) -> bool:
  if context is not None:
    return context.input_gateway.confirm(message, policy=context.input_policy)
  print(f"{message} 输入 yes 确认: ", end="", file=sys.stderr, flush=True)
  return input().strip().lower() == "yes"


def cmd_init(args) -> dict:
  if args.none and args.component:
    raise TermcfgError(2, "component_and_none_conflict")
  home = None if args.edit else environment_home()
  path = machine_path(args.machine)
  context = invocation_context(args)
  selected = None
  snapshot = None
  def identity():
    try:
      info = path.lstat()
      return (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size, info.st_mode, info.st_uid, info.st_nlink)
    except FileNotFoundError:
      return None
  if context is not None:
    # 输入与批准先于创建协作锁；接受后在原锁内复核所审阅文件身份。
    exists = path.exists() or path.is_symlink()
    if exists and not args.edit:
      raise TermcfgError(2, "machine_exists", hint("init-local", "--edit"))
    if not exists and args.edit:
      raise TermcfgError(2, "machine_missing", hint("init-local"))
    snapshot = identity()
    previous = read_machine(args.machine) if exists else None
    if identity() != snapshot:
      raise TermcfgError(4, "machine_selection_changed", hint("init-local", "--edit"))
    if args.component:
      selected = tuple(args.component)
      if len(set(selected)) != len(selected):
        raise TermcfgError(2, "duplicate_component")
    elif args.none:
      selected = ()
    else:
      require_input(context)
      selected = _interactive_selection(previous.components if previous else None, context=context)
    if context.input_gateway.allows_input(context.input_policy):
      print("组件: " + (",".join(previous.components) if previous else "(未初始化)")
        + " → " + (",".join(selected) or "(空)"), file=context.input_gateway.stderr)
      _confirm("保存私人机器选择？", context=context)
  with operation_lease(args.machine):
    if context is not None and identity() != snapshot:
      raise TermcfgError(4, "machine_selection_changed", hint("init-local", "--edit"))
    exists = path.exists() or path.is_symlink()
    if exists and not args.edit:
      raise TermcfgError(2, "machine_exists", hint("init-local", "--edit"))
    if not exists and args.edit:
      raise TermcfgError(2, "machine_missing", hint("init-local", fallback_components=("zsh",)))
    previous = read_machine(args.machine) if exists else None
    if previous is not None:
      require_no_pending_recovery(previous)
    if context is not None:
      components = selected
    elif args.component:
      components = tuple(args.component)
      if len(set(components)) != len(components):
        raise TermcfgError(2, "duplicate_component")
    elif args.none:
      components = ()
    elif sys.stdin.isatty():
      components = _interactive_selection(previous.components if previous else None)
    else:
      raise TermcfgError(2, "selection_required", hint("init-local", fallback_components=("zsh",)))
    home = previous.target_home if previous else home
    state = previous.private_state_root if previous else xdg_path("XDG_STATE_HOME") / "termcfg" / "machines" / args.machine
    machine = MachineSelection.from_dict({
      "machine_id": args.machine,
      "target_home": str(home),
      "private_state_root": str(state),
      "components": list(components),
    })
    before = ",".join(previous.components) if previous else "(未初始化)"
    after = ",".join(components) if components else "(空)"
    if context is None:
      print(f"组件: {before} → {after}", file=sys.stderr)
    if context is None and sys.stdin.isatty() and not _confirm("保存私人机器选择？"):
      next_step = hint("init-local", "--edit") if exists else hint("init-local")
      raise TermcfgError(4, "confirmation_declined", next_step)
    def check_reviewed_identity():
      if identity() != snapshot:
        raise TermcfgError(4, "machine_selection_changed", hint("init-local", "--edit"))
    _write_new_machine(path, encode_machine(machine),
      **({"before_replace": check_reviewed_identity} if context is not None else {}))
    args._guidance_components = components
    return {"command": "init-local", "machine_id": args.machine, "components": list(components), "private_file": str(path), "overall_ready": True, "ready": True, "next_command": hint("doctor")}


def _selected(machine: MachineSelection, args, *, empty_all: bool = False) -> tuple[str, ...]:
  values = tuple(args.component) if args.component else machine.components
  if not values and empty_all:
    values = ("zsh", "tmux")
  if len(set(values)) != len(values):
    raise TermcfgError(2, "duplicate_component")
  if not values:
    raise TermcfgError(2, "empty_selection", hint("init-local", "--edit", fallback_components=("zsh",)))
  args._guidance_components = values
  return values


def _diagnostic_home(machine: MachineSelection, args) -> MachineSelection:
  if not getattr(args, "home", None):
    return machine
  selected = MachineSelection.from_dict({"machine_id": machine.machine_id,
                                        "target_home": args.home,
                                        "private_state_root": str(machine.private_state_root),
                                        "components": list(machine.components)})
  args._guidance_home = str(selected.target_home)
  return selected


def _interactive_apply(preview):
  print(f"计划 {preview.plan_id}", file=sys.stderr)
  for item in preview.targets:
    print(f"  {item.artifact.component}/{item.artifact.id}: {item.action}; 旧文件备份={item.backup}", file=sys.stderr)
  required = {item.artifact.id for item in preview.targets if item.action == "adopt-required"}
  if not _confirm("备份列出的旧目标并执行同步（含全部接管目标）？"):
    raise TermcfgError(4, "confirmation_declined", hint("plan"))
  custom = any(item.custom_zshenv for item in preview.targets)
  zshenv = preview.plan_id if not custom or _confirm(".zshenv 将整文件替换；旧非秘密内容已安排备份，继续？") else None
  return required, zshenv


def _context_apply_approval(args, preview, context):
  """完整批准直接交回原事务；缺批准只在三流允许时单独审阅。"""
  if args.plan_id is not None and args.plan_id != preview.plan_id:
    raise TermcfgError(2, "plan_id_mismatch", hint("plan"))
  required = {item.artifact.id for item in preview.targets if item.action == "adopt-required"}
  adopted = set(args.adopt_target)
  if adopted - required:
    raise TermcfgError(2, "invalid_adoption_target", hint("plan"))
  custom = any(item.custom_zshenv for item in preview.targets)
  if args.confirm_zshenv is not None and args.confirm_zshenv != preview.plan_id:
    raise TermcfgError(2, "zshenv_confirmation_mismatch", hint("plan"))
  missing = args.plan_id is None or bool(required - adopted)
  zshenv = args.confirm_zshenv
  if missing or (custom and zshenv is None):
    require_input(context)
    print("计划 " + preview.plan_id, file=context.input_gateway.stderr)
    for item in preview.targets:
      print(f"  {item.artifact.component}/{item.artifact.id}: {item.action}; 旧文件备份={item.backup}",
        file=context.input_gateway.stderr)
    if missing:
      _confirm("备份列出的旧目标并应用此计划（含列出的接管目标）？", context=context)
      adopted = required
    if custom and zshenv is None:
      _confirm(".zshenv 将整文件替换；旧非秘密内容已安排备份，继续？", context=context)
      zshenv = preview.plan_id
  return preview.plan_id, adopted, zshenv


def _failure_payload(args, reason: str, next_command: str, *, context: dict | None = None) -> dict:
  result = {"overall_ready": False, "ready": False, "reason": reason,
            "next_command": next_command}
  if args is None:
    return result
  result["command"] = args.command
  result["machine_id"] = context_for(args).machine or "<invalid>"
  component = getattr(args, "component", None)
  if isinstance(component, str):
    result["component"] = component
  elif isinstance(component, list):
    result["components"] = component
  if context:
    result.update(context)
  for key, value in current_progress().items():
    result.setdefault(key, value)
  if args.command in {"apply", "rollback", "recover"}:
    try:
      # 只读恢复诊断也支持严格校验的旧元数据，不改变实际写入的迁移门禁。
      journal = read_journal(read_machine(args.machine, legacy=True))
      if journal is not None:
        result["transaction_id"] = journal["transaction_id"]
        result["transaction_phase"] = journal["phase"]
        result["side_effect"] = "recovery_pending"
        # 恢复已经失败时先观察，不能用 pending 覆盖目标漂移等拒绝原因。
        result["next_command"] = hint("status") if args.command == "recover" else hint("recover")
    except (TermcfgError, OSError):
      pass
    if "side_effect" not in result:
      changed_or_unknown = args.command == "recover" or result.get("stage") in {"backup", "write", "verify", "commit"}
      result["side_effect"] = "check_home_and_transaction_state" if changed_or_unknown else "home_unchanged"
      if changed_or_unknown:
        result["next_command"] = hint("status")
  elif args.command == "sync":
    result["side_effect"] = ("private_package_or_selection_may_have_changed"
                             if result.get("stage") == "activate" else "package_selection_unchanged")
  elif args.command == "lock":
    result["side_effect"] = ("check_repository_lock" if result.get("stage") == "activate"
                             else "repository_lock_unchanged")
  return result


def _emit_result(args, payload, *, json_mode):
  context = context_for(args)
  emit(resolve_hints(payload, context), json_mode=json_mode, context=context.public())


def main(argv: list[str] | None = None, *, context=None) -> int:
  reset_progress()
  tokens = list(argv if argv is not None else sys.argv[1:])
  json_mode = "--json" in tokens
  args = None
  try:
    args = build_parser().parse_args(tokens)
    if context is not None:
      args.invocation_context = context
    catalog = None
    if args.command in {"components", "plan", "doctor", "apply", "rollback"}:
      catalog = load_catalog()
    if args.command == "components":
      result = {"command": "components", "components": {name: [entry.id for entry in catalog if entry.component == name] for name in sorted(COMPONENTS)}, "overall_ready": True, "ready": True, "next_command": hint("init-local", fallback_components=("zsh",))}
    elif args.command == "init-local":
      result = cmd_init(args)
    elif args.command == "plan":
      machine = _diagnostic_home(read_machine(args.machine), args)
      selection = _selected(machine, args, empty_all=True)
      options = {"entry_repo": args.entry_repo} if args.entry_repo is not None else {}
      result = build_preview(machine, selection, **options).public_dict()
      result["environment"] = inspect_environment(machine, selection)
      result["overall_ready"] = result["ready"] = (
        result["ready"] and all(entry["ready"] for entry in result["environment"].values()))
      if not result["ready"]:
        result["next_command"] = hint("doctor", "--strict")
      result["command"] = "plan"
    elif args.command == "doctor":
      machine = _diagnostic_home(read_machine(args.machine), args)
      selection = _selected(machine, args, empty_all=True)
      environments = inspect_environment(machine, selection)
      overall = all(value["ready"] for value in environments.values())
      pending = any("recovery_pending" in value["required_blockers"] for value in environments.values())
      result = {"command": "doctor", "components": environments, "overall_ready": overall,
                "ready": overall, "next_command": hint("recover") if pending else hint("plan") if overall else hint("doctor")}
      _emit_result(args, result, json_mode=args.json)
      if args.strict and not overall:
        return 4 if any("recovery_pending" in entry["required_blockers"] for entry in environments.values()) else 5
      return 0
    elif args.command == "status":
      machine = read_machine(args.machine, legacy=True)
      from .state import read_state
      state = read_state(machine, legacy=True)
      if "mihomo" in machine.components or state["version"] == 1:
        journal = read_journal(machine)
        result = {"command": "status", "machine_id": args.machine,
                  "ready": False, "overall_ready": False,
                  "reason": "legacy_migration_required", "recovery_pending": journal is not None,
                  "next_command": hint("recover") if journal else hint("migrate", "--drop-mihomo")}
        _emit_result(args, result, json_mode=args.json)
        return 0
      machine = _diagnostic_home(read_machine(args.machine), args)
      try:
        result = {"command": "status", **status_report(machine, _selected(machine, args, empty_all=True))}
      except TermcfgError as exc:
        journal = read_journal(machine)
        if journal is None:
          raise
        result = {"command": "status", "machine_id": machine.machine_id,
                  "overall_ready": False, "ready": False, "recovery_pending": True,
                  "source_diagnostic": exc.reason,
                  "transaction": {"transaction_id": journal["transaction_id"],
                                  "phase": journal["phase"],
                                  "items": [{"target_id": item["target_id"], "component": item["component"],
                                             "stage": item["stage"]} for item in journal["items"]]},
                  "next_command": hint("recover")}
    elif args.command == "apply":
      machine = read_machine(args.machine)
      selection = _selected(machine, args)
      options = {"entry_repo": args.entry_repo} if args.entry_repo is not None else {}
      if context is not None:
        plan_id, adopted, zshenv = _context_apply_approval(args, build_preview(machine, selection, **options), context)
        outcome = apply(machine, selection, plan_id=plan_id, adopted=adopted, confirm_zshenv=zshenv, **options)
      else:
        if not sys.stdin.isatty() and args.plan_id is None:
          raise TermcfgError(2, "plan_id_required", hint("plan"))
        outcome = apply(machine, selection, plan_id=args.plan_id,
                        adopted=set(args.adopt_target), confirm_zshenv=args.confirm_zshenv,
                        confirm=_interactive_apply if sys.stdin.isatty() else None, **options)
      result = {"command": "apply", "machine_id": args.machine,
                "components": {component: {"changed": [value for value in outcome["changed"] if value in [a.id for a in catalog if a.component == component]]} for component in selection},
                **outcome, "overall_ready": True, "ready": True, "next_command": hint("doctor")}
    elif args.command == "recover":
      result = {"command": "recover", **recover(read_machine(args.machine, legacy=True)),
                "overall_ready": True, "ready": True, "next_command": hint("plan")}
    elif args.command == "rollback":
      machine = read_machine(args.machine)
      if args.plan_only:
        if args.plan_id:
          raise TermcfgError(2, "plan_only_conflict")
        result = {"command": "rollback-plan", **rollback_preview(machine, args.component)}
      else:
        if context is not None and args.plan_id is None:
          require_input(context)
        elif context is None and not sys.stdin.isatty() and not args.plan_id:
          raise TermcfgError(2, "plan_id_required", hint("rollback", "--plan-only", components=(args.component,)))
        def approve(plan):
          print(f"回滚计划 {plan['plan_id']}", file=sys.stderr)
          for target in plan["targets"]:
            print(f"  {target['target_id']}: 恢复 {target['restore_kind']}", file=sys.stderr)
          return _confirm("恢复上一版公开配置？", **({"context": context} if context is not None else {}))
        if context is not None:
          plan_id = args.plan_id
          if plan_id is None:
            plan = rollback_preview(machine, args.component)
            approve(plan)
            plan_id = plan["plan_id"]
          outcome = rollback(machine, args.component, plan_id=plan_id)
        else:
          outcome = rollback(machine, args.component, plan_id=args.plan_id,
                             confirm=approve if sys.stdin.isatty() else None)
        result = {"command": "rollback", **outcome, "overall_ready": True,
                  "ready": True, "next_command": hint("status")}
    elif args.command == "lock":
      if not 10 <= args.timeout <= 3600:
        raise TermcfgError(2, "invalid_timeout")
      plugin = args.plugin or ("zinit" if args.component == "zsh" else None)
      if plugin is None:
        raise TermcfgError(2, "plugin_required")
      outcome = lock_plugin(args.component, plugin, args.version, repo=args.repo,
                            entry=args.entry, timeout=args.timeout)
      result = {"command": "lock", **outcome,
                "overall_ready": True, "ready": True}
    elif args.command == "sync":
      if not 10 <= args.timeout <= 3600:
        raise TermcfgError(2, "invalid_timeout")
      result = {"command": "sync", **sync(read_machine(args.machine), args.component, timeout=args.timeout),
                "overall_ready": True, "ready": True}
    elif args.command == "migrate":
      from .migration import migrate
      result = {"command": "migrate", **migrate(args.machine), "ready": True, "overall_ready": True}
    else:
      raise TermcfgError(2, "unsupported_command")
    _emit_result(args, result, json_mode=args.json)
    return 0
  except InputError as exc:
    _emit_result(args, _failure_payload(args, "input_cancelled" if exc.exit_code == 130 else "input_required", hint("plan")), json_mode=json_mode)
    return exc.exit_code
  except TermcfgError as exc:
    if not tokens:
      print(ENTRY_GUIDE, file=sys.stderr, end="")
    elif getattr(exc, "usage_detail", None):
      print(exc.usage_detail + "；用法：" + str(exc.next_command), file=sys.stderr)
    _emit_result(args, _failure_payload(args, exc.reason, exc.next_command, context=exc.context), json_mode=json_mode)
    return exc.code
  except KeyboardInterrupt:
    _emit_result(args, _failure_payload(args, "interrupted", hint("doctor")), json_mode=json_mode)
    return 6
  except OSError:
    _emit_result(args, _failure_payload(args, "filesystem_failure", hint("status")), json_mode=json_mode)
    return 6
  except Exception:
    _emit_result(args, _failure_payload(args, "internal_failure", hint("status")), json_mode=json_mode)
    return 6


if __name__ == "__main__":
  raise SystemExit(main())
