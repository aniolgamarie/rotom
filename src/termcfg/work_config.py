"""work仅消费已校验的普通选择，不解析凭据或安装工具。"""

from dataclasses import dataclass, field
import os
import hashlib
import json
from pathlib import Path
import re
import shutil

from .errors import TermcfgError


ROOT = Path(__file__).resolve().parents[2]
ROLES = ("shell", "edit", "build", "debug", "pi", "codex", "dsh")
PAYLOAD_ENV = "ROTOM_WORK_LAUNCH_V1"


def operation_timeout(role=None):
  return 60 if role in ("pi", "dsh") else 30


@dataclass(frozen=True, repr=False)
class WorkSettings:
  local_path: Path
  herdr_binary: str
  session: str
  editor: str | None = None
  pi_profile: str | None = None
  dsh_profile: str | None = None
  codex_binary: str | None = None
  codex_daemon: bool = False
  repo_root: Path = field(default=ROOT)

  def __repr__(self):
    return "WorkSettings()"

  @property
  def selectors(self):
    return ("--local", str(self.local_path))

  @property
  def selection_digest(self):
    # 仅限这些普通选择，绝不摘要原始local或secrets文件。
    value = {key: getattr(self, key) for key in ("herdr_binary", "session", "editor",
      "pi_profile", "dsh_profile", "codex_binary", "codex_daemon")}
    value["local"] = str(self.local_path)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
      separators=(",", ":")).encode()).hexdigest()


def literal(value):
  if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
    raise TermcfgError(2, "work_invalid_literal", "work --help")
  return value


def executable_name(value):
  value = literal(value)
  if value.startswith("~/"):
    value = str(Path(os.environ.get("HOME", "")) / value[2:])
  path = Path(value)
  if path.is_absolute():
    if ".." in path.parts:
      raise TermcfgError(2, "work_invalid_executable", "work --help")
  elif not re.fullmatch(r"[\w.+-]+", value) or value in (".", ".."):
    raise TermcfgError(2, "work_invalid_executable", "work --help")
  return value


def resolve_executable(value):
  value = executable_name(value)
  path = value if Path(value).is_absolute() else shutil.which(value)
  try:
    if path is None or not Path(path).is_file() or not os.access(path, os.X_OK):
      raise OSError()
    return str(Path(path).resolve(strict=True))
  except (OSError, ValueError):
    raise TermcfgError(5, "work_executable_not_prepared", "work --help") from None


def check_config_location(home=None):
  home = Path(home or os.environ.get("HOME", ""))
  if not home.is_absolute():
    raise TermcfgError(2, "work_invalid_home", "work --help")
  expected = home / ".config" / "herdr" / "config.toml"
  xdg = os.environ.get("XDG_CONFIG_HOME")
  override = os.environ.get("HERDR_CONFIG_PATH")
  if ((xdg is not None and Path(xdg) != home / ".config") or
      (override is not None and Path(override) != expected)):
    raise TermcfgError(2, "work_unsupported_config_location", "work --help")
  return expected


def prepared_config():
  """缺文件不能交给原生默认值；启动前另作官方完整加载诊断。"""
  import tomllib
  import stat
  from agentcfg.paths import read_private_file, PathError
  path = check_config_location()
  try:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
      raise TermcfgError(4, "work_unsafe_native_config", "termcfg doctor --component herdr")
    content = read_private_file(path)
    value = tomllib.loads(content.decode("utf-8"))
    if (value.get("terminal", {}).get("default_shell") != "rotom-work-shell" or
        value.get("terminal", {}).get("shell_mode") != "non_login" or
        value.get("session", {}).get("resume_agents_on_restore") is not False):
      raise TermcfgError(5, "work_native_config_not_prepared", "termcfg doctor --component herdr")
    return path, hashlib.sha256(content).hexdigest()
  except TermcfgError:
    raise
  except PathError:
    raise TermcfgError(4, "work_unsafe_native_config", "termcfg doctor --component herdr") from None
  except (OSError, UnicodeError, ValueError, AttributeError):
    raise TermcfgError(5, "work_native_config_not_prepared", "termcfg doctor --component herdr") from None


def validate_native_config(binary, deadline):
  import subprocess
  path, digest = prepared_config()
  environment = dict(os.environ, HERDR_CONFIG_PATH=str(path))
  try:
    result = subprocess.run([binary, "config", "check"], env=environment,
      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      timeout=deadline.remaining(5), check=False)
    if result.returncode != 0 or prepared_config() != (path, digest):
      raise TermcfgError(5, "work_native_config_diagnostics_failed", "termcfg doctor --component herdr")
  except (OSError, subprocess.TimeoutExpired):
    raise TermcfgError(5, "work_native_config_diagnostics_failed", "termcfg doctor --component herdr") from None


def read_settings(*, machine=None, local=None, repo_root=ROOT):
  from agentcfg.cli import local_path
  from agentcfg.config import load_local
  from agentcfg.paths import xdg_config_home, safe_id
  from agentcfg.schema import ConfigError
  from agentcfg.storage import Conflict
  if machine is not None and local is not None:
    raise TermcfgError(2, "work_selector_conflict", "work --help")
  try:
    if local is None:
      identifier = machine or "default"
      safe_id(identifier)
      path = xdg_config_home() / "agentcfg" / "machines" / (identifier + ".toml")
    else:
      path = local_path(local)
    try:
      config, _ = load_local(path, load_credentials=False)
    except ConfigError as error:
      if error.code != "adapter-schema":
        raise
      # 只有原生覆盖确需上下文时才加载完整公共目录，再走同一严格校验。
      from agentcfg.workspace import load_public_catalog
      catalog, _ = load_public_catalog(repository=repo_root)
      config, _ = load_local(path, adapter_schemas=catalog.adapter_schemas, load_credentials=False)
    data = config.data["machine"]
    work = data.get("work")
    if not work:
      raise TermcfgError(2, "work_configuration_required", "work --help")
    session = work["session"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session):
      raise TermcfgError(2, "work_invalid_session", "work --help")
    return WorkSettings(path.absolute(), executable_name(work["herdr_binary"]), session,
      executable_name(data["editor"]) if "editor" in data else None,
      work.get("pi_profile"), work.get("dsh_profile"),
      executable_name(work["codex_binary"]) if "codex_binary" in work else None,
      work.get("codex_daemon", False), Path(repo_root))
  except TermcfgError:
    raise
  except Conflict:
    raise TermcfgError(4, "work_unsafe_local_configuration", "work --help") from None
  except (ConfigError, OSError, ValueError, KeyError):
    raise TermcfgError(2, "work_invalid_configuration", "work --help") from None


def shell_command():
  value = os.environ.get("SHELL") or "/bin/sh"
  executable = resolve_executable(value)
  if Path(executable) == (ROOT / "rotom-work-shell").resolve():
    raise TermcfgError(2, "work_recursive_shell", "work --help")
  return [executable]


def _prepared_agent(settings, role, profile):
  from agentcfg.workspace import load_workspace
  from agentcfg.storage import Tree, Conflict, StateError
  from agentcfg.deployment import read_state
  from agentcfg.schema import ConfigError
  from agentcfg.paths import PathError
  from agentcfg.execution_environment import declarations, caller_paths
  try:
    workspace = load_workspace(settings.local_path, profile=profile, repository=settings.repo_root)
    if workspace.agent != role:
      raise TermcfgError(2, "work_profile_agent_mismatch", "work --help")
    with Tree(workspace.state_root) as state:
      if state.read("pending.json"):
        raise conflict_error()
      current = read_state(state)["current"]
      if not current or current["binding"] != workspace.binding:
        raise TermcfgError(5, "work_agent_not_deployed", "agentcfg plan")
      contract = current["launch"]
      if (declarations(contract["machine"]) != declarations(workspace.resolved.data["machine"]) or
          ("environment_version" in contract and (contract["environment_version"] != 1 or
            contract.get("caller_paths") != caller_paths()))):
        raise TermcfgError(4, "work_agent_environment_changed", "agentcfg plan")
    identity = contract.get("runtime_identity", contract["lock_identity"])
    if workspace.backend.status(workspace, identity) != "installed":
      raise TermcfgError(5, "work_agent_runtime_not_prepared", "agentcfg sync")
  except TermcfgError:
    raise
  except ConfigError:
    raise TermcfgError(2, "work_profile_invalid", "agentcfg validate") from None
  except Conflict:
    raise TermcfgError(4, "work_agent_deployment_conflict", "agentcfg plan") from None
  except StateError as error:
    raise TermcfgError(error.exit_code, "work_agent_preparation_failed", "agentcfg plan") from None
  except (OSError, ValueError, PathError):
    raise TermcfgError(5, "work_agent_not_prepared", "agentcfg plan") from None


def conflict_error():
  return TermcfgError(4, "work_agent_recovery_pending", "agentcfg plan")


def prepare_tool(settings, role, root):
  if role in ("shell", "build", "debug"):
    return shell_command()
  if role == "edit":
    if settings.editor is None:
      raise TermcfgError(2, "work_editor_choice_required", "work --help")
    return [resolve_executable(settings.editor)]
  if role in ("pi", "dsh"):
    profile = getattr(settings, role + "_profile")
    if not profile:
      raise TermcfgError(2, "work_agent_profile_required", "work --help")
    _prepared_agent(settings, role, profile)
    entry = resolve_executable(str(settings.repo_root / "agentcfg"))
    return [entry, *settings.selectors, "--profile", profile, "run", role, "--cwd", str(root)]
  if role == "codex":
    if settings.codex_binary is None:
      raise TermcfgError(2, "work_codex_choice_required", "work --help")
    return [resolve_executable(settings.codex_binary), *([] if settings.codex_daemon else ["--no-daemon"])]
  raise TermcfgError(2, "work_invalid_role", "work --help")
