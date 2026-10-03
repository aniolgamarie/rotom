"""离线汇总平台、程序、公开来源、目标和运行包状态。"""

import os
from pathlib import Path
import shutil
import stat

from .catalog import load_catalog
from .config import MachineSelection
from .errors import TermcfgError
from .home_targets import inspect_target
from .packages import current_platform, installed_core, installed_plugins
from .state import journal_exists, read_journal, read_state


def inspect_environment(machine: MachineSelection, components: tuple[str, ...]) -> dict:
  catalog = load_catalog()
  result = {}
  for component in components:
    blockers = []
    degraded = []
    unverified = []
    target_issues = {}
    if current_platform() != "linux-x86_64":
      blockers.append("unsupported_platform")
    if component in {"zsh", "tmux"} and shutil.which(component) is None:
      blockers.append("required_program_missing")
    if component == "tmux" and shutil.which("fzf") is None:
      degraded.append("optional_fzf_missing")
    if component in {"zsh", "tmux"}:
      try:
        if not installed_plugins(component):
          degraded.append("optional_plugins_not_synced")
      except TermcfgError as exc:
        degraded.append(exc.reason)
    if component == "mihomo":
      try:
        installed_core(machine)
      except TermcfgError as exc:
        blockers.append(exc.reason)
      private_config = machine.private_state_root / "mihomo" / "private.yaml"
      if not private_config.exists():
        unverified.append("private_config_missing")
      else:
        info = private_config.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
          unverified.append("private_config_unsafe")
      from .mihomo import service_status
      service = service_status(machine)
      if service["service"] == "unknown/external":
        blockers.append("external_service_identity")
      elif service["service"] != "running":
        unverified.append("service_not_running")
      elif service["effective"] == "unverified":
        unverified.append("service_effect_unverified")
    else:
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
    result[component] = {"status": status, "ready": not blockers,
                         "required_blockers": sorted(set(blockers)),
                         "optional_degradations": sorted(set(degraded)),
                         "unverified": sorted(set(unverified)),
                         "target_issues": target_issues,
                         "service": service,
                         "next_command": ("./termcfg recover" if "recovery_pending" in blockers else
                                          "./termcfg sync --component mihomo" if component == "mihomo" and blockers else
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
    from .mihomo import service_status
    service = service_status(machine) if component == "mihomo" else {"service": "not_applicable"}
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
      pending_core_effect=state["pending_core_effect"] if component == "mihomo" else False,
      pending_config_effect=state["pending_config_effect"] if component == "mihomo" else False,
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
