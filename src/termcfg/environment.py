"""离线汇总平台、程序、公开来源、目标和运行包状态。"""

import os
from pathlib import Path
import shutil

from .catalog import load_catalog
from .config import MachineSelection, xdg_path
from .errors import TermcfgError
from .home_targets import inspect_target
from .packages import current_platform, installed_plugins
from .state import journal_exists, read_journal, read_state


def private_hook_status(home: Path, config_home: str | None) -> dict[str, str]:
  """仅查看当前环境对应的 hook 元数据，不读取或执行私人正文。"""
  names = ("zshenv", "zshrc")
  if config_home and not Path(config_home).is_absolute():
    return {name: "invalid_config_home" for name in names}
  if not config_home and not home.is_absolute():
    return {name: "invalid_home" for name in names}
  config = Path(config_home) if config_home else home / ".config"
  result = {}
  for name in names:
    selected = config / "termcfg" / (name + ".local")
    legacy = home / ".config/termcfg" / (name + ".local")
    try:
      selected_present = selected.is_file()
      legacy_present = home.is_absolute() and legacy.is_file()
      if selected_present and legacy_present:
        result[name] = "shared" if selected.samefile(legacy) else "conflict"
      else:
        result[name] = "xdg" if selected_present else "legacy" if legacy_present else "absent" if home.is_absolute() else "invalid_home"
    except OSError:
      result[name] = "unverified"
  return result


def inspect_environment(machine: MachineSelection, components: tuple[str, ...]) -> dict:
  catalog = load_catalog()
  result = {}
  for component in components:
    blockers = []
    degraded = []
    unverified = []
    target_issues = {}
    xdg_paths = {}
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
      value = os.environ.get(name)
      try:
        xdg_path(name)
        xdg_paths[name] = "absolute" if value else "default"
      except TermcfgError as exc:
        xdg_paths[name] = "invalid_home" if exc.reason == "invalid_home" else "invalid_relative"
        blockers.append(exc.reason)
    if current_platform() != "linux-x86_64":
      blockers.append("unsupported_platform")
    if component in {"zsh", "tmux"} and shutil.which(component) is None:
      blockers.append("required_program_missing")
    if component == "tmux" and shutil.which("fzf") is None:
      degraded.append("optional_fzf_missing")
    if component in {"zsh", "tmux"} and xdg_paths["XDG_DATA_HOME"] in {"default", "absolute"}:
      try:
        if not installed_plugins(component):
          degraded.append("optional_plugins_not_synced")
      except TermcfgError as exc:
        degraded.append(exc.reason)
    hooks = private_hook_status(machine.target_home, os.environ.get("XDG_CONFIG_HOME")) if component == "zsh" else None
    if hooks and "conflict" in hooks.values():
      degraded.append("private_hook_conflict")
    if hooks and "invalid_config_home" in hooks.values():
      degraded.append("private_hook_invalid_config_home")
    if hooks and "invalid_home" in hooks.values():
      degraded.append("private_hook_invalid_home")
    if hooks and "unverified" in hooks.values():
      unverified.append("private_hook_metadata_unverified")
    service = {"service": "not_applicable"}
    if journal_exists(machine):
      blockers.append("recovery_pending")
    for item in catalog:
      if item.component != component:
        continue
      try:
        item.bytes()
        inspect_target(machine.target_home, item.destination)
      except TermcfgError as exc:
        blockers.append(exc.reason)
        target_issues[item.id] = exc.reason
    status = "blocked" if blockers else "degraded" if degraded else "unverified" if unverified else "ready"
    result[component] = {"status": status, "ready": not blockers, "xdg_paths": xdg_paths,
                         **({"private_hooks": {"scope": "current_environment_preview", "selection": hooks}} if hooks else {}),
                         "required_blockers": sorted(set(blockers)),
                         "optional_degradations": sorted(set(degraded)),
                         "unverified": sorted(set(unverified)),
                         "target_issues": target_issues,
                         "service": service,
                         "next_command": ("./termcfg recover" if "recovery_pending" in blockers else
                                          "./termcfg doctor" if blockers else "./termcfg plan")}
  return result


def status_report(machine: MachineSelection, components: tuple[str, ...]) -> dict:
  environment = inspect_environment(machine, components)
  state = read_state(machine)
  pending = journal_exists(machine)
  journal = read_journal(machine) if pending else None
  catalog = load_catalog()
  for component in components:
    targets = {}
    for item in catalog:
      if item.component != component:
        continue
      record = state["targets"].get(item.id)
      if record is None:
        targets[item.id] = "unmanaged"
        continue
      try:
        current = inspect_target(machine.target_home, item.destination)
        identity = current.as_dict()
        if current.kind == "file":
          from .home_targets import read_regular
          from .secret_boundary import admit_existing
          identity["digest"] = admit_existing(item.id, read_regular(machine.target_home, item.destination, current),
                                               known_public_contents={item.bytes()},
                                               trusted_digest=record["after"].get("digest"))
        targets[item.id] = "synced" if identity == record["after"] else "drift"
      except TermcfgError:
        targets[item.id] = "conflict"
    service = {"service": "not_applicable"}
    if any(value in {"drift", "conflict"} for value in targets.values()):
      blockers = set(environment[component]["required_blockers"])
      blockers.add("target_drift")
      environment[component]["required_blockers"] = sorted(blockers)
      environment[component]["status"] = "blocked"
      environment[component]["ready"] = False
      environment[component]["next_command"] = "./termcfg plan --component " + component
    environment[component].update(
      files=targets,
      previous_backup=component in state["previous"],
      recovery_pending=pending,
      service=service,
    )
  return {"components": environment, "overall_ready": all(value["ready"] for value in environment.values()) and not pending,
          "ready": all(value["ready"] for value in environment.values()) and not pending,
          "recovery_pending": pending,
          "transaction": ({"transaction_id": journal.get("transaction_id"),
                           "phase": journal.get("phase"),
                           "items": [{"target_id": item.get("target_id"), "component": item.get("component"),
                                      "stage": item.get("stage")} for item in journal.get("items", [])]}
                          if journal else None),
          "next_command": "./termcfg recover" if pending else "./termcfg plan"}
