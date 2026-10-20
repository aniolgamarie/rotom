"""Herdr 静态意图和入口准备检查；不运行第三方宿主。"""

import os
from pathlib import Path
import tomllib

from .catalog import REPO_ROOT
from .errors import TermcfgError
from .work_config import check_config_location, resolve_executable


def inspect_herdr(home: Path) -> dict:
  check_config_location(home)
  blockers = []
  try:
    resolve_executable("herdr")
  except TermcfgError:
    blockers.append("herdr_binary_not_prepared")
  launcher = REPO_ROOT / "rotom-work-shell"
  try:
    selected = Path(resolve_executable("rotom-work-shell"))
    if selected != launcher.resolve() or launcher.is_symlink() or not launcher.is_file() or not os.access(launcher, os.X_OK):
      blockers.append("herdr_launcher_source_mismatch")
  except TermcfgError:
    blockers.append("herdr_launcher_not_prepared")
  python = REPO_ROOT / ".venv/bin/python"
  if not python.is_file() or not os.access(python, os.X_OK) or not (REPO_ROOT / ".venv/pyvenv.cfg").is_file():
    blockers.append("herdr_venv_not_prepared")
  if not (REPO_ROOT / "src/termcfg/work_shell.py").is_file():
    blockers.append("herdr_launcher_source_missing")
  try:
    candidate = tomllib.loads((REPO_ROOT / "terminals/herdr/config.toml").read_text())
    if (candidate["terminal"]["default_shell"] != "rotom-work-shell" or
        candidate["terminal"]["shell_mode"] != "non_login" or
        candidate["session"]["resume_agents_on_restore"] is not False):
      blockers.append("herdr_config_intent_mismatch")
  except (OSError, ValueError, KeyError, TypeError):
    blockers.append("herdr_config_intent_invalid")
  return {"required_blockers": blockers, "unverified": ["herdr_native_config_and_handshake_not_verified"]}
