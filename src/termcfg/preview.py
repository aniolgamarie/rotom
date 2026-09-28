"""离线、只读的逐目标计划与确定性快照 ID。"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .catalog import SourceArtifact, load_catalog
from .config import MachineSelection
from .errors import TermcfgError
from .home_targets import TargetIdentity, inspect_target, read_regular
from .secret_boundary import admit_existing
from .state import journal_file, read_state


@dataclass(frozen=True)
class PlannedTarget:
  artifact: SourceArtifact
  before: TargetIdentity
  action: str
  reason: str | None
  backup: bool
  custom_zshenv: bool = False

  def public_dict(self) -> dict:
    return {"target_id": self.artifact.id, "component": self.artifact.component,
            "path": str(self.artifact.destination), "action": self.action,
            "backup": self.backup, "reason": self.reason,
            "source_digest": self.artifact.sha256}


@dataclass(frozen=True)
class Preview:
  plan_id: str
  targets: tuple[PlannedTarget, ...]
  state: dict
  state_digest: str
  lock_digest: str

  def public_dict(self) -> dict:
    blocked = any(item.action in {"blocked", "conflict"} for item in self.targets)
    return {"plan_id": self.plan_id, "targets": [item.public_dict() for item in self.targets],
            "overall_ready": not blocked, "ready": not blocked,
            "next_command": "./termcfg doctor" if blocked else "./termcfg apply"}


def _digest_object(value: object) -> str:
  return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _lock_digest() -> str:
  from .catalog import REPO_ROOT
  values = {}
  for name in ("mihomo.json", "plugins.json"):
    path = REPO_ROOT / "locks/termcfg" / name
    values[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
  return _digest_object(values)


def _old_starter_link(target_id: str, link: str) -> bool:
  mapping = {"zshrc": "zshrc.zsh", "tmux-conf": "tmux.conf", "tmux-fzf-window": "fzf-window.sh"}
  return target_id in mapping and "/starter/shell_config/" in link and link.endswith(mapping[target_id])


def build_preview(machine: MachineSelection, components: tuple[str, ...]) -> Preview:
  if journal_file(machine).exists():
    raise TermcfgError(4, "recovery_pending", "./termcfg status")
  catalog = load_catalog()
  state = read_state(machine)
  known = {artifact.bytes() for artifact in catalog}
  targets = []
  for artifact in catalog:
    if artifact.component not in components:
      continue
    before = inspect_target(machine.target_home, artifact.destination)
    action = "create"
    reason = None
    custom_zshenv = False
    backup = before.kind != "absent"
    record = state["targets"].get(artifact.id)
    if before.kind == "file":
      data = read_regular(machine.target_home, artifact.destination, before)
      try:
        digest = admit_existing(artifact.id, data, known_public_contents=known,
                                trusted_digest=record["after"].get("digest") if record else None)
        before = TargetIdentity(**{**before.as_dict(), "digest": digest})
        custom_zshenv = artifact.id == "zshenv" and data != artifact.bytes()
      except TermcfgError as exc:
        action, reason = "blocked", exc.reason
    elif before.kind == "symlink":
      if not _old_starter_link(artifact.id, before.link or ""):
        action, reason = "blocked", "unclassified_existing_link"
    if action != "blocked" and record:
      if before.as_dict() != record["after"]:
        action, reason = "conflict", "target_drift"
      elif before.kind == "file" and before.digest == artifact.sha256 and before.mode == artifact.mode:
        action = "unchanged"
      else:
        action = "replace"
    elif action != "blocked" and before.kind != "absent":
      action, reason = "adopt-required", "unmanaged_target"
    targets.append(PlannedTarget(artifact, before, action, reason, backup, custom_zshenv))
  snapshot = {"machine_id": machine.machine_id, "home": str(machine.target_home),
              "components": components, "state": state, "lock": _lock_digest(),
              "targets": [{"id": t.artifact.id, "source": t.artifact.sha256,
                           "before": t.before.as_dict(), "action": t.action} for t in targets]}
  return Preview(_digest_object(snapshot), tuple(targets), state,
                 _digest_object(state), snapshot["lock"])
