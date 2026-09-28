"""termcfg 独立命令行与简短的可诊断结果。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .catalog import load_catalog
from .config import COMPONENTS, MachineSelection, encode_machine, machine_path, read_machine, xdg_path
from .diagnostics import current_progress, emit, reset_progress
from .environment import inspect_environment, status_report
from .errors import TermcfgError
from .lease import operation_lease
from .mihomo import service_operation
from .packages import _read_lock_raw, lock_mihomo, lock_plugin, sync
from .preview import build_preview
from .state import read_journal, require_no_pending_recovery
from .transaction import apply, recover, rollback, rollback_preview


class Parser(argparse.ArgumentParser):
  def error(self, message):
    raise TermcfgError(2, "invalid_arguments", "./termcfg --help")


def build_parser() -> Parser:
  parser = Parser(prog="./termcfg", description="同步公开的终端与代理配置")
  parser.add_argument("--machine", default="default")
  parser.add_argument("--json", action="store_true")
  commands = parser.add_subparsers(dest="command", required=True)
  commands.add_parser("components")
  init = commands.add_parser("init-local")
  init.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  init.add_argument("--edit", action="store_true")
  init.add_argument("--none", action="store_true")
  plan = commands.add_parser("plan")
  plan.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  plan.add_argument("--home")
  doctor_parser = commands.add_parser("doctor")
  doctor_parser.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  doctor_parser.add_argument("--strict", action="store_true")
  doctor_parser.add_argument("--home")
  status_parser = commands.add_parser("status")
  status_parser.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  status_parser.add_argument("--home")
  apply_parser = commands.add_parser("apply")
  apply_parser.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  apply_parser.add_argument("--plan-id")
  apply_parser.add_argument("--adopt-target", action="append", default=[])
  apply_parser.add_argument("--confirm-zshenv")
  commands.add_parser("recover")
  lock_parser = commands.add_parser("lock")
  lock_parser.add_argument("--component", required=True, choices=sorted(COMPONENTS))
  lock_parser.add_argument("--version", required=True)
  lock_parser.add_argument("--plugin")
  lock_parser.add_argument("--timeout", type=int, default=300)
  sync_parser = commands.add_parser("sync")
  sync_parser.add_argument("--component", required=True, choices=sorted(COMPONENTS))
  sync_parser.add_argument("--timeout", type=int, default=300)
  service_parser = commands.add_parser("service")
  service_parser.add_argument("action", choices=("status", "start", "stop", "reload", "restart"))
  service_parser.add_argument("--timeout", type=int)
  rollback_parser = commands.add_parser("rollback")
  rollback_parser.add_argument("--component", required=True, choices=sorted(COMPONENTS))
  rollback_parser.add_argument("--plan-only", action="store_true")
  rollback_parser.add_argument("--plan-id")
  for command in commands.choices.values():
    command.add_argument("--machine", default=argparse.SUPPRESS)
    command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
  return parser


def _write_new_machine(path: Path, payload: bytes) -> None:
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
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
      os.fsync(directory_fd)
    finally:
      os.close(directory_fd)
  finally:
    if os.path.exists(temporary):
      os.unlink(temporary)


def _interactive_selection(previous: tuple[str, ...] | None) -> tuple[str, ...]:
  defaults = previous if previous is not None else tuple(
    name for name in ("zsh", "tmux") if shutil.which(name)
  )
  print("选择组件（逗号分隔；留空保持默认；输入 none 清空）：", file=sys.stderr)
  for name in ("zsh", "tmux", "mihomo"):
    required = "就绪" if (name == "mihomo" or shutil.which(name)) else "缺少本地程序"
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


def _confirm(message: str) -> bool:
  print(f"{message} 输入 yes 确认: ", end="", file=sys.stderr, flush=True)
  return input().strip().lower() == "yes"


def cmd_init(args) -> dict:
  if args.none and args.component:
    raise TermcfgError(2, "component_and_none_conflict")
  path = machine_path(args.machine)
  with operation_lease(args.machine):
    exists = path.exists() or path.is_symlink()
    if exists and not args.edit:
      raise TermcfgError(2, "machine_exists", "./termcfg init-local --edit")
    if not exists and args.edit:
      raise TermcfgError(2, "machine_missing", "./termcfg init-local --component zsh")
    previous = read_machine(args.machine) if exists else None
    if previous is not None:
      require_no_pending_recovery(previous)
    if args.component:
      components = tuple(args.component)
      if len(set(components)) != len(components):
        raise TermcfgError(2, "duplicate_component")
    elif args.none:
      components = ()
    elif sys.stdin.isatty():
      components = _interactive_selection(previous.components if previous else None)
    else:
      raise TermcfgError(2, "selection_required", "./termcfg init-local --component zsh")
    home = previous.target_home if previous else Path.home()
    state = previous.private_state_root if previous else xdg_path("XDG_STATE_HOME") / "termcfg" / "machines" / args.machine
    machine = MachineSelection.from_dict({
      "machine_id": args.machine,
      "target_home": str(home),
      "private_state_root": str(state),
      "components": list(components),
    })
    before = ",".join(previous.components) if previous else "(未初始化)"
    after = ",".join(components) if components else "(空)"
    print(f"组件: {before} → {after}", file=sys.stderr)
    if sys.stdin.isatty() and not _confirm("保存私人机器选择？"):
      raise TermcfgError(4, "confirmation_declined", "./termcfg init-local --edit")
    _write_new_machine(path, encode_machine(machine))
    return {"command": "init-local", "machine_id": args.machine, "components": list(components), "private_file": str(path), "overall_ready": True, "ready": True, "next_command": "./termcfg doctor"}


def _selected(machine: MachineSelection, args, *, empty_all: bool = False) -> tuple[str, ...]:
  values = tuple(args.component) if args.component else machine.components
  if not values and empty_all:
    values = ("zsh", "tmux", "mihomo")
  if len(set(values)) != len(values):
    raise TermcfgError(2, "duplicate_component")
  if not values:
    raise TermcfgError(2, "empty_selection", "./termcfg init-local --edit --component zsh")
  return values


def _diagnostic_home(machine: MachineSelection, args) -> MachineSelection:
  if not getattr(args, "home", None):
    return machine
  return MachineSelection.from_dict({"machine_id": machine.machine_id,
                                     "target_home": args.home,
                                     "private_state_root": str(machine.private_state_root),
                                     "components": list(machine.components)})


def _interactive_apply(preview):
  print(f"计划 {preview.plan_id}", file=sys.stderr)
  for item in preview.targets:
    print(f"  {item.artifact.component}/{item.artifact.id}: {item.action}; 旧文件备份={item.backup}", file=sys.stderr)
  required = {item.artifact.id for item in preview.targets if item.action == "adopt-required"}
  if not _confirm("备份列出的旧目标并执行同步（含全部接管目标）？"):
    raise TermcfgError(4, "confirmation_declined", "./termcfg plan")
  custom = any(item.custom_zshenv for item in preview.targets)
  zshenv = preview.plan_id if not custom or _confirm(".zshenv 将整文件替换；旧非秘密内容已安排备份，继续？") else None
  return required, zshenv


def _failure_payload(args, reason: str, next_command: str, *, context: dict | None = None) -> dict:
  result = {"overall_ready": False, "ready": False, "reason": reason,
            "next_command": next_command}
  if args is None:
    return result
  result["command"] = args.command if args.command != "service" else "service " + args.action
  result["machine_id"] = args.machine
  component = getattr(args, "component", None)
  if isinstance(component, str):
    result["component"] = component
  elif isinstance(component, list):
    result["components"] = component
  elif args.command == "service":
    result["component"] = "mihomo"
  if context:
    result.update(context)
  for key, value in current_progress().items():
    result.setdefault(key, value)
  if args.command in {"apply", "rollback", "recover"}:
    try:
      journal = read_journal(read_machine(args.machine))
      if journal is not None:
        result["transaction_id"] = journal["transaction_id"]
        result["transaction_phase"] = journal["phase"]
        result["side_effect"] = "recovery_pending"
        result["next_command"] = "./termcfg recover"
    except (TermcfgError, OSError):
      pass
    result.setdefault("side_effect", "check_home_and_transaction_state" if args.command == "recover" else "home_unchanged")
  elif args.command == "sync":
    result["side_effect"] = ("private_package_or_selection_may_have_changed"
                             if result.get("stage") == "activate" else "package_selection_unchanged")
  elif args.command == "lock":
    result["side_effect"] = ("check_repository_lock" if result.get("stage") == "activate"
                             else "repository_lock_unchanged")
  elif args.command == "service" and args.action != "status":
    result["side_effect"] = ("service_may_have_changed" if result.get("stage") in {"start-or-signal", "health"}
                             else "private_effective_config_may_have_changed")
  return result


def main(argv: list[str] | None = None) -> int:
  reset_progress()
  json_mode = "--json" in (argv if argv is not None else sys.argv[1:])
  args = None
  try:
    args = build_parser().parse_args(argv)
    catalog = None
    if args.command in {"components", "plan", "doctor", "apply", "rollback"}:
      catalog = load_catalog()
      _read_lock_raw("mihomo")
      _read_lock_raw("zsh")
    if args.command == "components":
      result = {"command": "components", "components": {name: [entry.id for entry in catalog if entry.component == name] for name in sorted(COMPONENTS)}, "overall_ready": True, "ready": True, "next_command": "./termcfg init-local --component zsh"}
    elif args.command == "init-local":
      result = cmd_init(args)
    elif args.command == "plan":
      machine = _diagnostic_home(read_machine(args.machine), args)
      selection = _selected(machine, args, empty_all=True)
      result = build_preview(machine, selection).public_dict()
      result["environment"] = inspect_environment(machine, selection)
      result["overall_ready"] = result["ready"] = (
        result["ready"] and all(entry["ready"] for entry in result["environment"].values()))
      if not result["ready"]:
        result["next_command"] = "./termcfg doctor --strict"
      result["command"] = "plan"
    elif args.command == "doctor":
      machine = _diagnostic_home(read_machine(args.machine), args)
      selection = _selected(machine, args, empty_all=True)
      environments = inspect_environment(machine, selection)
      overall = all(value["ready"] for value in environments.values())
      result = {"command": "doctor", "components": environments, "overall_ready": overall,
                "ready": overall, "next_command": "./termcfg plan" if overall else "./termcfg doctor"}
      emit(result, json_mode=args.json)
      if args.strict and not overall:
        return 4 if any("recovery_pending" in entry["required_blockers"] or "external_service_identity" in entry["required_blockers"] for entry in environments.values()) else 5
      return 0
    elif args.command == "status":
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
                  "next_command": "./termcfg recover"}
    elif args.command == "apply":
      machine = read_machine(args.machine)
      selection = _selected(machine, args)
      if not sys.stdin.isatty() and args.plan_id is None:
        raise TermcfgError(2, "plan_id_required", "./termcfg plan")
      outcome = apply(machine, selection, plan_id=args.plan_id,
                      adopted=set(args.adopt_target), confirm_zshenv=args.confirm_zshenv,
                      confirm=_interactive_apply if sys.stdin.isatty() else None)
      result = {"command": "apply", "machine_id": args.machine,
                "components": {component: {"changed": [value for value in outcome["changed"] if value in [a.id for a in catalog if a.component == component]]} for component in selection},
                **outcome, "overall_ready": True, "ready": True, "next_command": "./termcfg doctor"}
    elif args.command == "recover":
      result = {"command": "recover", **recover(read_machine(args.machine)),
                "overall_ready": True, "ready": True, "next_command": "./termcfg plan"}
    elif args.command == "rollback":
      machine = read_machine(args.machine)
      if args.plan_only:
        if args.plan_id:
          raise TermcfgError(2, "plan_only_conflict")
        result = {"command": "rollback-plan", **rollback_preview(machine, args.component)}
      else:
        if not sys.stdin.isatty() and not args.plan_id:
          raise TermcfgError(2, "plan_id_required", "./termcfg rollback --component " + args.component + " --plan-only")
        def approve(plan):
          print(f"回滚计划 {plan['plan_id']}", file=sys.stderr)
          for target in plan["targets"]:
            print(f"  {target['target_id']}: 恢复 {target['restore_kind']}", file=sys.stderr)
          return _confirm("恢复上一版公开配置？")
        outcome = rollback(machine, args.component, plan_id=args.plan_id,
                           confirm=approve if sys.stdin.isatty() else None)
        result = {"command": "rollback", **outcome, "overall_ready": True,
                  "ready": True, "next_command": "./termcfg status"}
    elif args.command == "lock":
      if not 10 <= args.timeout <= 3600:
        raise TermcfgError(2, "invalid_timeout")
      if args.component == "mihomo":
        if args.plugin:
          raise TermcfgError(2, "plugin_not_applicable")
        outcome = lock_mihomo(args.version, timeout=args.timeout)
      else:
        plugin = args.plugin or ("zinit" if args.component == "zsh" else None)
        if plugin is None:
          raise TermcfgError(2, "plugin_required")
        outcome = lock_plugin(args.component, plugin, args.version, timeout=args.timeout)
      result = {"command": "lock", **outcome,
                "overall_ready": True, "ready": True}
    elif args.command == "sync":
      if not 10 <= args.timeout <= 3600:
        raise TermcfgError(2, "invalid_timeout")
      result = {"command": "sync", **sync(read_machine(args.machine), args.component, timeout=args.timeout),
                "overall_ready": True, "ready": True}
    elif args.command == "service":
      if args.timeout is not None and not 10 <= args.timeout <= 3600:
        raise TermcfgError(2, "invalid_timeout")
      result = {"command": "service " + args.action,
                **service_operation(read_machine(args.machine), args.action, timeout=args.timeout),
                "overall_ready": True, "ready": True,
                "next_command": "./termcfg service status"}
    else:
      raise TermcfgError(2, "unsupported_command")
    emit(result, json_mode=args.json)
    return 0
  except TermcfgError as exc:
    emit(_failure_payload(args, exc.reason, exc.next_command, context=exc.context), json_mode=json_mode)
    return exc.code
  except KeyboardInterrupt:
    emit(_failure_payload(args, "interrupted", "./termcfg doctor"), json_mode=json_mode)
    return 6
  except OSError:
    emit(_failure_payload(args, "filesystem_failure", "./termcfg status"), json_mode=json_mode)
    return 6
  except Exception:
    emit(_failure_payload(args, "internal_failure", "./termcfg status"), json_mode=json_mode)
    return 6


if __name__ == "__main__":
  raise SystemExit(main())
